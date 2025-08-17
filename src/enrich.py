"""
Enrich tool for Lead Sorcerer.

This tool fills required fields first, enriches only the best contact per domain,
and keeps costs to cents. It uses Proxycurl for firmographic + role enrichment,
Mailgun for primary SMTP validation, and Snov.io for email enrichment.

External API dependencies:
- Proxycurl for firmographic + role enrichment
- Mailgun for primary SMTP validation
- Snov.io for email enrichment
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
import phonenumbers
import portalocker
import publicsuffix2

from common import (
    AsyncSemaphorePool, ErrorCode, PermitManager, append_audit, append_status,
    build_error, build_metrics, canonicalize_linkedin, compute_next_revisit,
    enforce_field_ownership, get_email_status_rank, get_role_priority,
    get_seniority_rank, load_costs_config, load_schema_checksum, mask_email,
    mask_linkedin, mask_phone, normalize_domain, normalize_text, now_z,
    parse_phone_number, recompute_total_cost, resolve_data_dir, round4,
    setup_logging, truncate_evidence_arrays, validate_envelope,
    validate_provider_config, validate_testing_flags, wrap_unknown_errors
)


# ============================================================================
# Constants and Configuration
# ============================================================================

INTERNAL_VERSION = "1.0.0"
TOOL_NAME = "enrich"

# Email status ranking for best contact selection
EMAIL_STATUS_RANKS = {
    "valid": 0,
    "risky": 1,
    "catch_all": 2,
    "unknown": 3,
    "invalid": 4
}

# Default timeout values
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 10.0
MAX_WALL_CLOCK = 45.0


# ============================================================================
# Provider Clients
# ============================================================================

class ProxycurlClient:
    """Client for Proxycurl API."""

    def __init__(self, api_key: str, semaphore_pool: AsyncSemaphorePool):
        self.api_key = api_key
        self.base_url = "https://nubela.co/proxycurl/api/v2"
        self.semaphore_pool = semaphore_pool

    async def enrich_company(self, domain: str) -> Dict[str, Any]:
        """
        Enrich company information using Proxycurl.

        Args:
            domain: Company domain

        Returns:
            Enriched company data
        """
        async with self.semaphore_pool:
            url = f"{self.base_url}/company"
            params = {
                "domain": domain,
                "api_key": self.api_key
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT, read=READ_TIMEOUT
            )) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()

    async def enrich_contact(self, linkedin_url: str) -> Dict[str, Any]:
        """
        Enrich contact information using Proxycurl.

        Args:
            linkedin_url: LinkedIn profile URL

        Returns:
            Enriched contact data
        """
        async with self.semaphore_pool:
            url = f"{self.base_url}/linkedin"
            params = {
                "linkedin_profile_url": linkedin_url,
                "api_key": self.api_key
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT, read=READ_TIMEOUT
            )) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()


class MailgunClient:
    """Client for Mailgun SMTP validation."""

    def __init__(self, smtp_login: str, smtp_password: str, semaphore_pool: AsyncSemaphorePool):
        self.smtp_login = smtp_login
        self.smtp_password = smtp_password
        self.base_url = "https://api.mailgun.net/v3"
        self.domain = smtp_login.split('@')[1] if '@' in smtp_login else None
        self.semaphore_pool = semaphore_pool

    async def validate_email(self, email: str) -> Dict[str, Any]:
        """
        Validate email address using Mailgun.

        Args:
            email: Email address to validate

        Returns:
            Validation result with status and confidence
        """
        async with self.semaphore_pool:
            url = f"{self.base_url}/address/validate"
            params = {
                "address": email,
                "api_key": self.smtp_password
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT, read=READ_TIMEOUT
            )) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()


class SnovioClient:
    """Client for Snov.io email enrichment."""

    def __init__(self, client_id: str, client_secret: str, semaphore_pool: AsyncSemaphorePool):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://api.snov.io/v1"
        self.semaphore_pool = semaphore_pool
        self._access_token = None

    async def _get_access_token(self) -> str:
        """Get access token for Snov.io API."""
        if self._access_token:
            return self._access_token

        async with self.semaphore_pool:
            url = f"{self.base_url}/oauth/access_token"
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT, read=READ_TIMEOUT
            )) as client:
                response = await client.post(url, data=data)
                response.raise_for_status()
                token_data = response.json()
                self._access_token = token_data["access_token"]
                return self._access_token

    async def find_email(self, domain: str, first_name: str, last_name: str) -> Dict[str, Any]:
        """
        Find email address using Snov.io.

        Args:
            domain: Company domain
            first_name: Contact's first name
            last_name: Contact's last name

        Returns:
            Email discovery result
        """
        async with self.semaphore_pool:
            token = await self._get_access_token()
            url = f"{self.base_url}/search-profile"
            params = {
                "access_token": token,
                "domain": domain,
                "firstName": first_name,
                "lastName": last_name
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT, read=READ_TIMEOUT
            )) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()


# ============================================================================
# Core Enrichment Logic
# ============================================================================

def select_best_contact(contacts: List[Dict[str, Any]],
                       role_priority_config: Dict[str, int]) -> Optional[str]:
    """
    Select best contact using deterministic ranking.

    Args:
        contacts: List of contacts
        role_priority_config: Role priority configuration

    Returns:
        Contact ID of best contact or None
    """
    if not contacts:
        return None

    # Score each contact
    scored_contacts = []
    for contact in contacts:
        contact_id = contact.get('contact_id', '')
        role = contact.get('role', '')
        seniority = contact.get('seniority', 99)
        email_status = contact.get('email_status', 'unknown')
        linkedin = contact.get('linkedin', '')

        # Get role priority
        role_priority = get_role_priority(role, role_priority_config)

        # Get seniority rank
        seniority_rank = get_seniority_rank(role) if seniority is None else seniority

        # Get email status rank
        email_status_rank = get_email_status_rank(email_status)

        # Check if has LinkedIn
        has_linkedin = 0 if linkedin else 1

        # Create sort tuple: (role_priority, seniority_rank, email_status_rank, has_linkedin, contact_id)
        sort_tuple = (role_priority, seniority_rank, email_status_rank, has_linkedin, contact_id)
        scored_contacts.append((sort_tuple, contact_id))

    # Sort by tuple (ascending) and pick first
    scored_contacts.sort(key=lambda x: x[0])
    return scored_contacts[0][1] if scored_contacts else None


async def enrich_company_data(company: Dict[str, Any], domain: str,
                             proxycurl_client: ProxycurlClient,
                             costs_config: Dict[str, float]) -> Tuple[Dict[str, Any], float]:
    """
    Enrich company data using Proxycurl.

    Args:
        company: Company data to enrich
        domain: Company domain
        proxycurl_client: Proxycurl client
        costs_config: Costs configuration

    Returns:
        Tuple of (enriched_company, cost_usd)
    """
    try:
        # Enrich company information
        enriched_data = await proxycurl_client.enrich_company(domain)

        # Update company fields
        if enriched_data.get('name') and not company.get('name'):
            company['name'] = enriched_data['name']

        if enriched_data.get('description') and not company.get('description'):
            company['description'] = enriched_data['description']

        if enriched_data.get('industry') and not company.get('industry'):
            company['industry'] = enriched_data['industry']

        if enriched_data.get('hq_location') and not company.get('hq_location'):
            company['hq_location'] = enriched_data['hq_location']

        if enriched_data.get('size_hint') and not company.get('size_hint'):
            company['size_hint'] = enriched_data['size_hint']

        # Backfill company.ids if missing
        if enriched_data.get('linkedin_company_id') and not company.get('ids', {}).get('linkedin'):
            if 'ids' not in company:
                company['ids'] = {}
            company['ids']['linkedin'] = f"/company/{enriched_data['linkedin_company_id']}"

        if enriched_data.get('crunchbase_id') and not company.get('ids', {}).get('crunchbase'):
            if 'ids' not in company:
                company['ids'] = {}
            company['ids']['crunchbase'] = enriched_data['crunchbase_id']

        # Calculate cost
        cost_usd = costs_config.get('proxycurl', 0.0)

        return company, cost_usd

    except Exception as exc:
        logging.warning(f"Failed to enrich company data for {domain}: {exc}")
        return company, 0.0


async def enrich_contact_data(contact: Dict[str, Any], domain: str,
                             proxycurl_client: ProxycurlClient,
                             mailgun_client: MailgunClient,
                             snovio_client: SnovioClient,
                             costs_config: Dict[str, float]) -> Tuple[Dict[str, Any], float]:
    """
    Enrich contact data using multiple providers.

    Args:
        contact: Contact data to enrich
        domain: Company domain
        proxycurl_client: Proxycurl client
        mailgun_client: Mailgun client
        snovio_client: Snov.io client
        costs_config: Costs configuration

    Returns:
        Tuple of (enriched_contact, cost_usd)
    """
    total_cost = 0.0

    try:
        # Enrich via Proxycurl if LinkedIn available
        if contact.get('linkedin'):
            try:
                enriched_data = await proxycurl_client.enrich_contact(contact['linkedin'])

                # Update contact fields
                if enriched_data.get('email') and not contact.get('email'):
                    contact['email'] = enriched_data['email']
                    contact['email_source'] = 'provider'
                    contact['email_status'] = 'unknown'  # Will be validated by Mailgun

                if enriched_data.get('phone') and not contact.get('phone'):
                    contact['phone'] = enriched_data['phone']

                if enriched_data.get('role') and not contact.get('role'):
                    contact['role'] = enriched_data['role']

                total_cost += costs_config.get('proxycurl', 0.0)

            except Exception as exc:
                logging.warning(f"Failed to enrich contact via Proxycurl: {exc}")

        # Try Snov.io for email discovery if no email
        if not contact.get('email'):
            try:
                full_name = contact.get('full_name', '')
                if full_name and ' ' in full_name:
                    first_name, last_name = full_name.split(' ', 1)

                    email_data = await snovio_client.find_email(domain, first_name, last_name)

                    if email_data.get('email'):
                        contact['email'] = email_data['email']
                        contact['email_source'] = 'provider'
                        contact['email_status'] = 'unknown'  # Will be validated by Mailgun
                        total_cost += costs_config.get('snovio', 0.0)

            except Exception as exc:
                logging.warning(f"Failed to discover email via Snov.io: {exc}")

        # Validate email if present
        if contact.get('email'):
            try:
                validation_result = await mailgun_client.validate_email(contact['email'])

                # Map Mailgun status to our email_status
                mailgun_status = validation_result.get('result', 'unknown')
                if mailgun_status == 'valid':
                    contact['email_status'] = 'valid'
                    contact['email_confidence'] = validation_result.get('score', 0.0)
                elif mailgun_status == 'catch_all':
                    contact['email_status'] = 'catch_all'
                    contact['email_confidence'] = 0.5
                elif mailgun_status == 'invalid':
                    contact['email_status'] = 'invalid'
                    contact['email_confidence'] = 0.0
                else:
                    contact['email_status'] = 'unknown'
                    contact['email_confidence'] = 0.5

                total_cost += costs_config.get('mailgun', 0.0)

            except Exception as exc:
                logging.warning(f"Failed to validate email: {exc}")
                contact['email_status'] = 'unknown'
                contact['email_confidence'] = 0.0

        # Normalize phone number if present
        if contact.get('phone'):
            try:
                normalized_phone = parse_phone_number(
                    contact['phone'],
                    company_country=contact.get('company_country'),
                    default_country=contact.get('default_country', 'US')
                )
                contact['phone'] = normalized_phone
            except ValueError:
                # Keep original phone if parsing fails
                pass

        return contact, total_cost

    except Exception as exc:
        logging.warning(f"Failed to enrich contact data: {exc}")
        return contact, total_cost


def write_evidence_file(domain: str, evidence_data: Dict[str, Any], data_dir: str) -> str:
    """
    Write evidence to file and return path.

    Args:
        domain: Company domain
        evidence_data: Evidence data to write
        data_dir: Data directory

    Returns:
        Evidence file path
    """
    # Normalize domain for file path
    normalized_domain = normalize_domain(domain)

    # Create evidence directory
    evidence_dir = os.path.join(data_dir, "evidence", "enrich")
    os.makedirs(evidence_dir, exist_ok=True)

    # Write evidence file
    evidence_path = os.path.join(evidence_dir, f"{normalized_domain}.json")

    try:
        with portalocker.Lock(evidence_path, timeout=10):
            with open(evidence_path, 'w') as f:
                json.dump(evidence_data, f, indent=2)
    except portalocker.exceptions.LockException as e:
        raise RuntimeError(f"Failed to acquire lock for {evidence_path}: {e}")

    return evidence_path


# ============================================================================
# Main Tool Logic
# ============================================================================

async def run_enrich(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main enrichment function.

    Args:
        payload: Input payload with lead_records, icp_config, and caps

    Returns:
        Enrichment results with data, errors, and metrics
    """
    start_time = time.time()
    logger = setup_logging(TOOL_NAME)

    try:
        # Validate input
        if not isinstance(payload, dict):
            return {
                "data": {"lead_records": []},
                "errors": [build_error(ErrorCode.SCHEMA_VALIDATION, tool=TOOL_NAME)],
                "metrics": build_metrics(0, 0, 0)
            }

        lead_records = payload.get('lead_records', [])
        icp_config = payload.get('icp_config', {})
        caps = payload.get('caps', {})

        if not lead_records or not icp_config:
            return {
                "data": {"lead_records": []},
                "errors": [build_error(ErrorCode.SCHEMA_VALIDATION, tool=TOOL_NAME)],
                "metrics": build_metrics(0, 0, 0)
            }

        # Validate testing flags
        try:
            validate_testing_flags(icp_config)
        except ValueError as exc:
            return {
                "data": {"lead_records": []},
                "errors": [build_error(ErrorCode.SCHEMA_VALIDATION, exc=exc, tool=TOOL_NAME)],
                "metrics": build_metrics(0, 0, 0)
            }

        # Load costs configuration
        try:
            costs_config = load_costs_config()
            required_providers = ['proxycurl', 'mailgun', 'snovio']
            validate_provider_config(required_providers, costs_config)
        except (FileNotFoundError, KeyError) as exc:
            return {
                "data": {"lead_records": []},
                "errors": [build_error(ErrorCode.PROVIDER_ERROR, exc=exc, tool=TOOL_NAME)],
                "metrics": build_metrics(0, 0, 0)
            }

        # Load schema checksum
        try:
            schema_checksum = load_schema_checksum()
        except FileNotFoundError as exc:
            return {
                "data": {"lead_records": []},
                "errors": [build_error(ErrorCode.SCHEMA_VALIDATION, exc=exc, tool=TOOL_NAME)],
                "metrics": build_metrics(0, 0, 0)
            }

        # Resolve data directory
        data_dir = resolve_data_dir(payload)

        # Initialize permit manager and semaphore pools
        max_concurrent = icp_config.get('concurrency', {}).get('max_concurrent_requests', 3)
        permit_manager = PermitManager(max_concurrent)
        async_semaphore_pool = AsyncSemaphorePool(permit_manager)

        # Initialize provider clients
        proxycurl_key = os.environ.get('PROXYCURL_KEY')
        mailgun_login = os.environ.get('MAILGUN_SMTP_LOGIN')
        mailgun_password = os.environ.get('MAILGUN_SMTP_PW')
        snovio_id = os.environ.get('SNOV_IO_ID')
        snovio_secret = os.environ.get('SNOV_IO_SECRET')

        if not all([proxycurl_key, mailgun_login, mailgun_password, snovio_id, snovio_secret]):
            return {
                "data": {"lead_records": []},
                "errors": [build_error(ErrorCode.PROVIDER_ERROR, tool=TOOL_NAME, context={"error": "Missing required environment variables"})],
                "metrics": build_metrics(0, 0, 0)
            }

        proxycurl_client = ProxycurlClient(proxycurl_key, async_semaphore_pool)
        mailgun_client = MailgunClient(mailgun_login, mailgun_password, async_semaphore_pool)
        snovio_client = SnovioClient(snovio_id, snovio_secret, async_semaphore_pool)

        # Get configuration values
        role_priority_config = icp_config.get('role_priority', {})
        default_country = icp_config.get('default_country', 'US')
        run_usd_max = caps.get('run_usd_max', float('inf'))
        company_usd_cap = caps.get('company_usd', 0.02)
        contact_usd_cap = caps.get('contact_usd', 0.03)

        # Process each lead record
        processed_records = []
        errors = []
        total_cost = 0.0
        enriched_count = 0
        partial_count = 0

        for record in lead_records:
            try:
                # Check if we should process this record
                status = record.get('status', '')
                if status not in ['enrich_ready', 'crawled']:
                    # Skip records that aren't ready for enrichment
                    processed_records.append(record)
                    continue

                # Check if processing this lead would exceed run_usd_max
                if total_cost >= run_usd_max:
                    errors.append(build_error(
                        ErrorCode.BUDGET_EXCEEDED,
                        tool=TOOL_NAME,
                        lead_id=record.get('lead_id'),
                        context={"error": "Run budget exceeded", "total_cost": total_cost, "run_usd_max": run_usd_max}
                    ))
                    # Skip this lead entirely
                    processed_records.append(record)
                    continue

                lead_id = record.get('lead_id', '')
                domain = record.get('domain', '')
                company = record.get('company', {})
                contacts = record.get('contacts', [])

                # Normalize domain
                normalized_domain = normalize_domain(domain)
                record['domain'] = normalized_domain

                # Enrich company data first (cheaper)
                company_cost = 0.0
                if company_usd_cap > 0:
                    company, company_cost = await enrich_company_data(
                        company, normalized_domain, proxycurl_client, costs_config
                    )
                    company_cost = min(company_cost, company_usd_cap)

                # Select best contact
                best_contact_id = select_best_contact(contacts, role_priority_config)
                record['best_contact_id'] = best_contact_id

                # Enrich contacts (only if within budget)
                contact_cost = 0.0
                if contacts and contact_usd_cap > 0:
                    for contact in contacts:
                        if contact_cost >= contact_usd_cap:
                            break

                        # Add company country and default country for phone parsing
                        contact['company_country'] = company.get('hq_location')
                        contact['default_country'] = default_country

                        enriched_contact, single_contact_cost = await enrich_contact_data(
                            contact, normalized_domain, proxycurl_client,
                            mailgun_client, snovio_client, costs_config
                        )

                        # Cap individual contact cost
                        single_contact_cost = min(single_contact_cost, contact_usd_cap - contact_cost)
                        contact_cost += single_contact_cost

                # Update costs
                record['cost']['enrich_usd'] = company_cost + contact_cost
                recompute_total_cost(record)

                # Update total cost
                total_cost += company_cost + contact_cost

                # Update provenance
                if 'provenance' not in record:
                    record['provenance'] = {}

                record['provenance']['enriched_at'] = now_z()
                record['provenance']['tool_versions'] = record['provenance'].get('tool_versions', {})
                record['provenance']['tool_versions']['enrich'] = {
                    'version': INTERNAL_VERSION,
                    'schema_version': schema_checksum
                }

                # Set evidence path
                evidence_data = {
                    'domain': normalized_domain,
                    'enriched_at': now_z(),
                    'company_enrichment': company,
                    'contacts_enrichment': contacts,
                    'costs': {
                        'company_usd': company_cost,
                        'contact_usd': contact_cost,
                        'total_usd': company_cost + contact_cost
                    }
                }

                evidence_path = write_evidence_file(normalized_domain, evidence_data, data_dir)
                record['provenance']['evidence_paths'] = record['provenance'].get('evidence_paths', {})
                record['provenance']['evidence_paths']['enrich'] = evidence_path

                # Update status
                old_status = record.get('status', '')

                # Check if all required fields are filled
                required_company_fields = icp_config.get('required_fields', {}).get('company', [])
                required_contact_fields = icp_config.get('required_fields', {}).get('contact', [])

                company_complete = all(
                    company.get(field) for field in required_company_fields
                )

                contact_complete = True
                if required_contact_fields and contacts:
                    best_contact = next(
                        (c for c in contacts if c.get('contact_id') == best_contact_id),
                        None
                    )
                    if best_contact:
                        contact_complete = all(
                            best_contact.get(field) for field in required_contact_fields
                        )
                    else:
                        contact_complete = False

                if company_complete and contact_complete:
                    new_status = 'enriched'
                    enriched_count += 1
                else:
                    new_status = 'enrich_partial'
                    partial_count += 1

                # Update status and append to history
                record['status'] = new_status
                append_status(record['status_history'], new_status,
                            f"Enrichment completed. Company: {company_complete}, Contact: {contact_complete}")

                # Append audit entry
                append_audit(record, "Enrich", f"Enriched company and contacts. Cost: ${company_cost + contact_cost:.4f}")

                # Truncate evidence arrays
                truncate_evidence_arrays(record)

                # Validate schema
                validation_errors = validate_envelope(record, TOOL_NAME)
                if validation_errors:
                    errors.extend(validation_errors)

                processed_records.append(record)

            except Exception as exc:
                # Handle individual record errors
                error = build_error(
                    ErrorCode.UNKNOWN,
                    exc=exc,
                    tool=TOOL_NAME,
                    lead_id=record.get('lead_id'),
                    context={"domain": record.get('domain', '')}
                )
                errors.append(error)

                # Keep the record but mark as failed
                record['status'] = 'enrich_partial'
                append_status(record['status_history'], 'enrich_partial', f"Enrichment failed: {str(exc)}")
                processed_records.append(record)

        # Calculate metrics
        duration_ms = int((time.time() - start_time) * 1000)
        pass_rate = enriched_count / len(lead_records) if lead_records else 0.0

        metrics = build_metrics(
            count_in=len(lead_records),
            count_out=len(processed_records),
            duration_ms=duration_ms,
            cache_hit_rate=None,  # Enrich doesn't have cache hits
            pass_rate=pass_rate,
            cost_usd={
                "domain": 0.0,
                "crawl": 0.0,
                "enrich": total_cost,
                "total": total_cost
            }
        )

        return {
            "data": {"lead_records": processed_records},
            "errors": errors,
            "metrics": metrics
        }

    except Exception as exc:
        # Handle tool-level errors
        error = build_error(ErrorCode.UNKNOWN, exc=exc, tool=TOOL_NAME)
        duration_ms = int((time.time() - start_time) * 1000)

        return {
            "data": {"lead_records": []},
            "errors": [error],
            "metrics": build_metrics(0, 0, duration_ms)
        }


# ============================================================================
# CLI Interface
# ============================================================================

def main():
    """CLI entry point for the Enrich tool."""
    try:
        # Read JSON from stdin
        input_data = input()
        payload = json.loads(input_data)

        # Run enrichment
        result = asyncio.run(run_enrich(payload))

        # Write JSON to stdout
        print(json.dumps(result))

    except json.JSONDecodeError as exc:
        # Handle JSON parsing errors
        error_result = {
            "data": {"lead_records": []},
            "errors": [build_error(ErrorCode.SCHEMA_VALIDATION, exc=exc, tool=TOOL_NAME)],
            "metrics": build_metrics(0, 0, 0)
        }
        print(json.dumps(error_result))
        exit(1)

    except Exception as exc:
        # Handle other errors
        error_result = {
            "data": {"lead_records": []},
            "errors": [build_error(ErrorCode.UNKNOWN, exc=exc, tool=TOOL_NAME)],
            "metrics": build_metrics(0, 0, 0)
        }
        print(json.dumps(error_result))
        exit(1)


if __name__ == "__main__":
    main()
