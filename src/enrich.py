"""
Enrich tool for Lead Sorcerer.

This tool enriches company and contact data using external APIs like Coresignal,
Snov.io, and Mailgun. It handles email validation, contact discovery, and
company data enrichment.

Authoritative specifications: BRD §333-336, §410-439
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

import httpx
# import portalocker  # Removed due to Windows compatibility issues

from src.common import (
    ErrorCode,
    append_audit,
    append_status,
    build_error,
    build_metrics,
    get_email_status_rank,
    get_role_priority,
    get_seniority_rank,
    load_costs_config,
    load_schema_checksum,
    normalize_domain,
    now_z,
    parse_phone_number,
    recompute_total_cost,
    resolve_data_dir,
    setup_logging,
    truncate_evidence_arrays,
    validate_envelope,
    validate_testing_flags,
)

from src.enrich_provider_router import create_enrichment_router
from src.enrich_providers.base import EnrichmentRequest

# Load environment variables
load_dotenv()

# Debug: Show environment variable status without exposing sensitive data
logging.info("🔑 Environment variables will be checked during router initialization")
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
    "invalid": 4,
}

# Default timeout values
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 10.0
MAX_WALL_CLOCK = 45.0


# ============================================================================
# Provider Clients
# ============================================================================


class MailgunClient:
    """Client for Mailgun SMTP validation."""

    def __init__(self, smtp_login: str, smtp_password: str):
        self.smtp_login = smtp_login
        self.smtp_password = smtp_password
        self.base_url = "https://api.mailgun.net/v3"
        self.domain = smtp_login.split("@")[1] if "@" in smtp_login else None

    async def validate_email(self, email: str) -> Dict[str, Any]:
        """
        Validate email address using Mailgun.

        Args:
            email: Email address to validate

        Returns:
            Validation result with status and confidence
        """
        url = f"{self.base_url}/address/validate"
        params = {"address": email, "api_key": self.smtp_password}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=None, pool=None
            )
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()


# ============================================================================
# Field Mapping Functions
# ============================================================================


# Field mapping now handled by router and providers


# Contact field mapping now handled by router and providers


# ============================================================================
# Core Enrichment Logic
# ============================================================================


def select_best_contact(
    contacts: List[Dict[str, Any]], role_priority_config: Dict[str, int]
) -> Optional[str]:
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
        contact_id = contact.get("contact_id", "")
        role = contact.get("role", "")
        seniority = contact.get("seniority", 99)
        email_status = (
            contact.get("email_status", ["unknown"])[0]
            if isinstance(contact.get("email_status"), list)
            else contact.get("email_status", "unknown")
        )
        linkedin = contact.get("linkedin", "")

        # Get role priority
        role_priority = get_role_priority(role, role_priority_config)

        # Get seniority rank
        seniority_rank = get_seniority_rank(role) if seniority is None else seniority

        # Get email status rank
        email_status_rank = get_email_status_rank(email_status)

        # Check if has LinkedIn
        has_linkedin = 0 if linkedin else 1

        # Create sort tuple: (role_priority, seniority_rank, email_status_rank, has_linkedin, contact_id)
        sort_tuple = (
            role_priority,
            seniority_rank,
            email_status_rank,
            has_linkedin,
            contact_id,
        )
        scored_contacts.append((sort_tuple, contact_id))

    # Sort by tuple (ascending) and pick first
    scored_contacts.sort(key=lambda x: x[0])
    return scored_contacts[0][1] if scored_contacts else None


# Company enrichment now handled by router


# Contact enrichment now handled by router


# Contact discovery now handled by router


def write_evidence_file(
    domain: str, evidence_data: Dict[str, Any], data_dir: str
) -> str:
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
        # Write directly without locking (Windows compatibility)
        with open(evidence_path, "w") as f:
            json.dump(evidence_data, f, indent=2)
    except Exception as e:
        raise RuntimeError(f"Failed to write evidence file {evidence_path}: {e}")

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
    print("🚀🚀🚀 RUN_ENRICH FUNCTION STARTED 🚀🚀🚀", flush=True)
    start_time = time.time()

    # Resolve data directory first for logging setup. Child tool will use shared
    # run log path from env if orchestrator provided one.
    data_dir = resolve_data_dir(payload)
    setup_logging(TOOL_NAME, data_dir=data_dir)

    try:
        # Validate input
        if not isinstance(payload, dict):
            return {
                "data": {"lead_records": []},
                "errors": [build_error(ErrorCode.SCHEMA_VALIDATION, tool=TOOL_NAME)],
                "metrics": build_metrics(0, 0, 0),
            }

        lead_records = payload.get("lead_records", [])
        icp_config = payload.get("icp_config", {})
        caps = payload.get("caps", {})

        if not lead_records or not icp_config:
            return {
                "data": {"lead_records": []},
                "errors": [build_error(ErrorCode.SCHEMA_VALIDATION, tool=TOOL_NAME)],
                "metrics": build_metrics(0, 0, 0),
            }

        # Validate testing flags
        try:
            logging.info("🔍 Validating testing flags...")
            logging.info(f"🔍 ICP config keys: {list(icp_config.keys())}")
            logging.info(
                f"🔍 Testing section: {icp_config.get('testing', 'NOT_FOUND')}"
            )
            logging.info("🔍 About to call validate_testing_flags...")
            validate_testing_flags(icp_config)
            logging.info("🔍 validate_testing_flags returned successfully")
            logging.info("✅ Testing flags validation passed")
        except ValueError as exc:
            return {
                "data": {"lead_records": []},
                "errors": [
                    build_error(ErrorCode.SCHEMA_VALIDATION, exc=exc, tool=TOOL_NAME)
                ],
                "metrics": build_metrics(0, 0, 0),
            }

        # Load costs configuration
        try:
            logging.info("🔍 Loading costs configuration...")
            costs_config = load_costs_config()
            logging.info(f"✅ Costs config loaded: {list(costs_config.keys())}")

            # Provider validation now handled by router
            logging.info("✅ Provider configuration will be validated by router")
        except (FileNotFoundError, KeyError) as exc:
            return {
                "data": {"lead_records": []},
                "errors": [
                    build_error(ErrorCode.PROVIDER_ERROR, exc=exc, tool=TOOL_NAME)
                ],
                "metrics": build_metrics(0, 0, 0),
            }

        # Load schema checksum
        try:
            logging.info("🔍 Loading schema checksum...")
            schema_checksum = load_schema_checksum()
            logging.info(f"✅ Schema checksum loaded: {schema_checksum[:8]}...")
        except FileNotFoundError as exc:
            return {
                "data": {"lead_records": []},
                "errors": [
                    build_error(ErrorCode.SCHEMA_VALIDATION, exc=exc, tool=TOOL_NAME)
                ],
                "metrics": build_metrics(0, 0, 0),
            }

        # Data directory already resolved for logging setup above
        logging.info(f"✅ Using data directory: {data_dir}")

        # Note: Removed permit manager and semaphore pools since we no longer use file locking
        logging.info("🔍 Skipping concurrency controls (no file locking needed)")

        # Initialize provider clients
        logging.info("🔍 Checking environment variables...")
        mailgun_login = os.environ.get("MAILGUN_SMTP_LOGIN")
        mailgun_password = os.environ.get("MAILGUN_SMTP_PW")

        logging.info(
            f"🔑 Environment check - Mailgun: {'✅' if mailgun_login else '❌'}"
        )

        # Check which specific environment variables are missing
        missing_vars = []
        if not mailgun_login:
            missing_vars.append("MAILGUN_SMTP_LOGIN")
        if not mailgun_password:
            missing_vars.append("MAILGUN_SMTP_PW")

        if missing_vars:
            return {
                "data": {"lead_records": []},
                "errors": [
                    build_error(
                        ErrorCode.PROVIDER_ERROR,
                        tool=TOOL_NAME,
                        context={
                            "error": f"Missing required environment variables: {', '.join(missing_vars)}",
                            "missing_variables": missing_vars,
                            "expected_variables": [
                                "MAILGUN_SMTP_LOGIN",
                                "MAILGUN_SMTP_PW",
                            ],
                        },
                    )
                ],
                "metrics": build_metrics(0, 0, 0),
            }

        # Initialize enrichment provider router
        enrichment_router = create_enrichment_router(icp_config)
        mailgun_client = MailgunClient(mailgun_login, mailgun_password)

        # Get configuration values
        role_priority_config = icp_config.get("role_priority", {})
        # Ensure role_priority_config is a dictionary
        if not isinstance(role_priority_config, dict):
            logging.warning(
                f"⚠️ role_priority_config is not a dictionary: {type(role_priority_config)}, resetting to empty dict"
            )
            role_priority_config = {}

        default_country = icp_config.get("default_country", "US")
        run_usd_max = caps.get("run_usd_max", float("inf"))
        company_usd_cap = caps.get("company_usd", 0.02)
        contact_usd_cap = caps.get("contact_usd", 0.03)

        # Process each lead record
        processed_records = []
        errors = []
        total_cost = 0.0
        enriched_count = 0
        partial_count = 0

        print(
            f"📋📋📋 ABOUT TO PROCESS {len(lead_records)} LEAD RECORDS 📋📋📋",
            flush=True,
        )
        for record in lead_records:
            try:
                # EARLY DEBUG: Log that we're starting to process a record
                logging.info(
                    f"🚀 STARTING RECORD PROCESSING FOR: {record.get('domain', 'UNKNOWN')}"
                )

                # Debug logging to see what record contains
                logging.info(
                    f"🔍 Processing record: type={type(record)}, content={record}"
                )

                # Check if we should process this record
                status = record.get("status", "")
                if status not in ["enrich_ready", "crawled"]:
                    # Skip records that aren't ready for enrichment
                    processed_records.append(record)
                    continue

                # Check if processing this lead would exceed run_usd_max
                if total_cost >= run_usd_max:
                    errors.append(
                        build_error(
                            ErrorCode.BUDGET_EXCEEDED,
                            tool=TOOL_NAME,
                            lead_id=record.get("lead_id"),
                            context={
                                "error": "Run budget exceeded",
                                "total_cost": total_cost,
                                "run_usd_max": run_usd_max,
                            },
                        )
                    )
                    # Skip this lead entirely
                    processed_records.append(record)
                    continue

                domain = record.get("domain", "")
                company = record.get("company", {})
                contacts = record.get("contacts", [])

                # Debug logging for contacts
                logging.info(f"🔍 Contacts field type for {domain}: {type(contacts)}")
                logging.info(f"🔍 Contacts field content for {domain}: {contacts}")

                # Ensure contacts is always a list
                if not isinstance(contacts, list):
                    logging.warning(
                        f"⚠️ Contacts field is not a list for {domain}, resetting to empty list"
                    )
                    contacts = []
                    record["contacts"] = contacts

                # Normalize domain
                normalized_domain = normalize_domain(domain)
                record["domain"] = normalized_domain

                # Enrich company data first (cheaper)
                company_cost = 0.0
                if company_usd_cap > 0:
                    try:
                        logging.info(
                            f"🔍 About to call enrich_company_data for {normalized_domain}"
                        )
                        # Use router for company enrichment
                        request = EnrichmentRequest(domain=normalized_domain)
                        result = await enrichment_router.enrich_company(request)

                        if result.success and result.data:
                            # Map the enriched data to company fields
                            enriched_data = result.data
                            fields_updated = 0

                            # Update company fields with enriched data
                            if enriched_data.get("name"):
                                company["name"] = enriched_data["name"]
                                fields_updated += 1
                            if enriched_data.get("description"):
                                company["description"] = enriched_data["description"]
                                fields_updated += 1
                            if enriched_data.get("industry"):
                                company["industry"] = enriched_data["industry"]
                                fields_updated += 1
                            if enriched_data.get("size"):
                                company["size"] = enriched_data["size"]
                                fields_updated += 1
                            if enriched_data.get("address"):
                                company["address"] = enriched_data["address"]
                                fields_updated += 1
                            if enriched_data.get("technologies"):
                                company["technologies"] = enriched_data["technologies"]
                                fields_updated += 1

                            logging.info(
                                f"✅ Company enrichment completed for {normalized_domain}: {fields_updated} fields updated"
                            )
                            company_cost = result.cost
                        else:
                            logging.warning(
                                f"Company enrichment failed for {normalized_domain}: {result.error}"
                            )
                            company_cost = 0.0

                        enriched_company = company
                        logging.info(
                            f"🔍 enrich_company_data returned: type={type(enriched_company)}, content={enriched_company}"
                        )
                        company_cost = min(company_cost, company_usd_cap)
                        # Update the record's company data
                        record["company"] = enriched_company
                        company = enriched_company  # Update local company variable
                    except Exception as e:
                        logging.warning(
                            f"⚠️ Company enrichment failed for {normalized_domain}: {e}"
                        )
                        # Continue with contact discovery even if company enrichment fails
                        company_cost = 0.0

                # Ensure company is always a dictionary for safety
                if not isinstance(company, dict):
                    logging.warning(
                        f"⚠️ Company data is not a dictionary for {normalized_domain}, resetting to empty dict"
                    )
                    company = {}
                    record["company"] = company

                # Debug logging to see what company contains
                logging.info(
                    f"🔍 Company data type for {normalized_domain}: {type(company)}"
                )
                logging.info(
                    f"🔍 Company data content for {normalized_domain}: {company}"
                )
                logging.info(
                    f"🔍 Record company field type: {type(record.get('company'))}"
                )
                logging.info(
                    f"🔍 Record company field content: {record.get('company')}"
                )

                # Select best contact
                logging.info(
                    f"🔍 Contacts type before select_best_contact: {type(contacts)}"
                )
                logging.info(
                    f"🔍 Contacts content before select_best_contact: {contacts}"
                )
                logging.info(f"🔍 Role priority config: {role_priority_config}")
                best_contact_id = select_best_contact(contacts, role_priority_config)
                record["best_contact_id"] = best_contact_id

                # Enrich contacts (only if within budget)
                contact_cost = 0.0

                # Log the current state before contact discovery
                logging.info(
                    f"🔍 About to start contact discovery logic for {normalized_domain}"
                )
                logging.info(f"🔍 Current contacts list: {contacts}")
                logging.info(f"🔍 Contact USD cap: {contact_usd_cap}")
                logging.info(
                    f"🔍 Force contact discovery flag: {icp_config.get('testing', {}).get('force_contact_discovery', False)}"
                )

                # If no contacts exist, try to discover them using Snov.io
                if (
                    not contacts
                    or icp_config.get("testing", {}).get(
                        "force_contact_discovery", False
                    )
                ) and contact_usd_cap > 0:
                    # Debug logging to see what's happening
                    logging.info(f"🔍 DEBUG: contacts list length: {len(contacts)}")
                    logging.info(
                        f"🔍 DEBUG: force_contact_discovery flag: {icp_config.get('testing', {}).get('force_contact_discovery', False)}"
                    )
                    logging.info(f"🔍 DEBUG: contact_usd_cap: {contact_usd_cap}")

                    # If force_contact_discovery is enabled, clear existing contacts to force fresh discovery
                    if icp_config.get("testing", {}).get(
                        "force_contact_discovery", False
                    ):
                        logging.info(
                            f"🔍 Force contact discovery enabled for {normalized_domain}, clearing existing contacts and starting fresh..."
                        )
                        contacts = []
                        record["contacts"] = contacts
                        logging.info(
                            f"🔍 DEBUG: After clearing, contacts list length: {len(contacts)}"
                        )

                    logging.info(
                        f"🔍 {'No contacts found' if not contacts else 'Force contact discovery enabled'} for {normalized_domain}, attempting contact discovery..."
                    )
                    try:
                        # Use router for contact discovery
                        try:
                            request = EnrichmentRequest(domain=normalized_domain)
                            result = await enrichment_router.get_all_domain_prospects(
                                request
                            )

                            if result.success and result.data:
                                prospects_data = result.data
                                discovered_contacts = []

                                # Process prospects data to extract contacts
                                if (
                                    isinstance(prospects_data, dict)
                                    and "data" in prospects_data
                                ):
                                    prospects = prospects_data["data"]
                                elif isinstance(prospects_data, list):
                                    prospects = prospects_data
                                else:
                                    prospects = []

                                # Build decision-maker titles from role priorities
                                role_priority = icp_config.get("role_priority", {})
                                decision_maker_titles = []

                                for role, priority in role_priority.items():
                                    if priority <= 5:  # Focus on high-priority roles
                                        decision_maker_titles.append(role.title())
                                        # Add common variations
                                        if role.lower() == "ceo":
                                            decision_maker_titles.extend(
                                                [
                                                    "Chief Executive Officer",
                                                    "Chief Executive",
                                                ]
                                            )
                                        elif role.lower() == "owner":
                                            decision_maker_titles.extend(
                                                ["Founder", "Proprietor"]
                                            )
                                        elif role.lower() == "president":
                                            decision_maker_titles.extend(
                                                [
                                                    "Chief Executive",
                                                    "Executive Director",
                                                ]
                                            )
                                        elif role.lower() == "vp":
                                            decision_maker_titles.extend(
                                                ["Vice President", "Vice-President"]
                                            )
                                        elif role.lower() == "director":
                                            decision_maker_titles.extend(
                                                [
                                                    "Managing Director",
                                                    "Executive Director",
                                                    "General Manager",
                                                ]
                                            )
                                        elif role.lower() == "head":
                                            decision_maker_titles.extend(
                                                [
                                                    "Head of",
                                                    "Department Head",
                                                    "Division Head",
                                                ]
                                            )
                                        elif role.lower() == "manager":
                                            # Use configurable manager titles from ICP config, or fall back to generic ones
                                            manager_titles = icp_config.get(
                                                "role_priority", {}
                                            ).get(
                                                "manager_titles",
                                                [
                                                    "Operations Manager",
                                                    "General Manager",
                                                    "Department Manager",
                                                ],
                                            )
                                            decision_maker_titles.extend(manager_titles)

                                decision_set = {
                                    t.lower() for t in decision_maker_titles
                                }

                                # Process prospects and build contacts
                                for profile in prospects[:5]:  # Limit to 5 contacts
                                    title_value = (
                                        profile.get("jobTitle")
                                        or profile.get("position")
                                        or profile.get("title")
                                        or ""
                                    )

                                    if (
                                        title_value
                                        and title_value.lower() not in decision_set
                                    ):
                                        continue

                                    contact = {
                                        "contact_id": f"discovered_{len(discovered_contacts)}",
                                        "first_name": profile.get("firstName", ""),
                                        "last_name": profile.get("lastName", ""),
                                        "email": "",
                                        "job_title": title_value,
                                        "company": profile.get("company", ""),
                                        "linkedin_url": profile.get("linkedinUrl", ""),
                                        "location": profile.get("location", ""),
                                        "discovery_source": "router",
                                        "discovery_method": "domain_prospects",
                                    }

                                    # Try to discover email for this prospect
                                    if (
                                        profile.get("prospectHash")
                                        or profile.get("hash")
                                        or profile.get("id")
                                    ):
                                        try:
                                            prospect_request = EnrichmentRequest(
                                                prospect_hash=profile.get(
                                                    "prospectHash"
                                                )
                                                or profile.get("hash")
                                                or profile.get("id")
                                            )
                                            email_result = await enrichment_router.search_prospect_email(
                                                prospect_request
                                            )

                                            if (
                                                email_result.success
                                                and email_result.data
                                            ):
                                                email_data = email_result.data
                                                if (
                                                    isinstance(email_data, list)
                                                    and len(email_data) > 0
                                                ):
                                                    first_email = email_data[0]
                                                    if isinstance(
                                                        first_email, dict
                                                    ) and first_email.get("email"):
                                                        contact["email"] = first_email[
                                                            "email"
                                                        ]
                                                        logging.info(
                                                            f"✅ Found email for {contact['first_name']} {contact['last_name']}: {contact['email']}"
                                                        )
                                        except Exception as exc:
                                            logging.warning(
                                                f"Email discovery failed for prospect: {exc}"
                                            )

                                    # Only add if we have identifying info
                                    has_identifying_info = (
                                        (contact["first_name"] and contact["last_name"])
                                        or contact["email"]
                                        or contact["job_title"]
                                    )

                                    if has_identifying_info:
                                        # Check for duplicates
                                        is_duplicate = any(
                                            c.get("email") == contact["email"]
                                            and contact["email"]
                                            or (
                                                c.get("first_name")
                                                == contact["first_name"]
                                                and c.get("last_name")
                                                == contact["last_name"]
                                                and contact["first_name"]
                                                and contact["last_name"]
                                            )
                                            for c in discovered_contacts
                                        )

                                        if not is_duplicate:
                                            discovered_contacts.append(contact)
                                            logging.info(
                                                f"✅ Discovered contact: {contact['first_name']} {contact['last_name']} - {contact['job_title']} - {contact['email']}"
                                            )

                                if discovered_contacts:
                                    logging.info(
                                        f"🎯 Successfully discovered {len(discovered_contacts)} contacts for {normalized_domain}"
                                    )
                                else:
                                    logging.warning(
                                        f"❌ No contacts discovered for {normalized_domain}"
                                    )
                            else:
                                discovered_contacts = []
                                logging.warning(
                                    f"Contact discovery failed for {normalized_domain}: {result.error}"
                                )
                        except Exception as exc:
                            discovered_contacts = []
                            logging.warning(
                                f"Contact discovery failed for {normalized_domain}: {exc}"
                            )

                        if discovered_contacts:
                            contacts = discovered_contacts
                            record["contacts"] = contacts
                            logging.info(
                                f"✅ Discovered {len(contacts)} contacts for {normalized_domain}"
                            )
                        else:
                            logging.warning(
                                f"⚠️ No contacts discovered for {normalized_domain}"
                            )
                    except Exception as contact_discovery_error:
                        # Check if it's a credit exhaustion error
                        if "402 Payment Required" in str(contact_discovery_error):
                            logging.warning(
                                f"⚠️ Snov.io API credits exhausted for {normalized_domain} - skipping contact discovery"
                            )
                        else:
                            logging.warning(
                                f"⚠️ Contact discovery failed for {normalized_domain}: {contact_discovery_error}"
                            )
                        # Continue without contacts rather than failing the entire enrichment

                # Enrich existing or discovered contacts
                if contacts and contact_usd_cap > 0:
                    logging.info(
                        f"🔍 About to enrich {len(contacts)} contacts for {normalized_domain}"
                    )
                    for i, contact in enumerate(contacts):
                        logging.info(
                            f"🔍 Contact {i}: type={type(contact)}, content={contact}"
                        )

                        # Check if contact is a dictionary (defensive programming)
                        if not isinstance(contact, dict):
                            logging.warning(
                                f"⚠️ Contact {i} is not a dictionary (type: {type(contact)}), skipping: {contact}"
                            )
                            continue

                        if contact_cost >= contact_usd_cap:
                            break

                        # Add company country and default country for phone parsing
                        contact["company_country"] = company.get("hq_location")
                        contact["default_country"] = default_country

                        # Use router for contact enrichment
                        single_contact_cost = 0.0

                        # Try to enrich contact via router if no email
                        if not contact.get("email"):
                            try:
                                request = EnrichmentRequest(domain=normalized_domain)
                                result = await enrichment_router.enrich_contacts(
                                    request
                                )

                                if result.success and result.data:
                                    # Update contact with enriched data
                                    enriched_contact_data = result.data
                                    if enriched_contact_data.get(
                                        "email"
                                    ) and not contact.get("email"):
                                        contact["email"] = enriched_contact_data[
                                            "email"
                                        ]
                                        contact["email_source"] = ["provider"]
                                        contact["email_status"] = ["unknown"]
                                    if enriched_contact_data.get(
                                        "phone"
                                    ) and not contact.get("phone"):
                                        contact["phone"] = enriched_contact_data[
                                            "phone"
                                        ]
                                    if enriched_contact_data.get(
                                        "role"
                                    ) and not contact.get("role"):
                                        contact["role"] = enriched_contact_data["role"]

                                    single_contact_cost += result.cost
                                    logging.info(
                                        f"✅ Contact enrichment completed for {normalized_domain}"
                                    )
                            except Exception as exc:
                                logging.warning(
                                    f"Contact enrichment failed for {normalized_domain}: {exc}"
                                )

                        # Try to find email if still missing
                        if (
                            not contact.get("email")
                            and contact.get("first_name")
                            and contact.get("last_name")
                        ):
                            try:
                                request = EnrichmentRequest(
                                    domain=normalized_domain,
                                    first_name=contact["first_name"],
                                    last_name=contact["last_name"],
                                )
                                result = await enrichment_router.find_email(request)

                                if result.success and result.data and result.data.email:
                                    contact["email"] = result.data.email
                                    contact["email_source"] = ["provider"]
                                    contact["email_status"] = ["unknown"]
                                    single_contact_cost += result.cost
                                    logging.info(
                                        f"✅ Email discovery completed for {normalized_domain}"
                                    )
                            except Exception as exc:
                                logging.warning(
                                    f"Email discovery failed for {normalized_domain}: {exc}"
                                )

                        # Validate email if present
                        if contact.get("email"):
                            try:
                                validation_result = await mailgun_client.validate_email(
                                    contact["email"]
                                )

                                # Map Mailgun status to our email_status
                                mailgun_status = validation_result.get(
                                    "result", "unknown"
                                )
                                if mailgun_status == "valid":
                                    contact["email_status"] = ["valid"]
                                    contact["email_confidence"] = validation_result.get(
                                        "score", 0.0
                                    )
                                elif mailgun_status == "catch_all":
                                    contact["email_status"] = ["catch_all"]
                                    contact["email_confidence"] = 0.5
                                elif mailgun_status == "invalid":
                                    contact["email_status"] = ["invalid"]
                                    contact["email_confidence"] = 0.0
                                else:
                                    contact["email_status"] = ["unknown"]
                                    contact["email_confidence"] = 0.5

                                single_contact_cost += costs_config.get("mailgun", 0.0)

                            except Exception as exc:
                                logging.warning(f"Failed to validate email: {exc}")
                                contact["email_status"] = ["unknown"]
                                contact["email_confidence"] = 0.0

                        # Normalize phone number if present
                        if contact.get("phone"):
                            try:
                                normalized_phone = parse_phone_number(
                                    contact["phone"],
                                    country_code=contact.get("company_country"),
                                    default_country=contact.get(
                                        "default_country", "US"
                                    ),
                                )
                                contact["phone"] = normalized_phone
                            except ValueError:
                                # Keep original phone if parsing fails
                                pass

                        # Cap individual contact cost
                        single_contact_cost = min(
                            single_contact_cost, contact_usd_cap - contact_cost
                        )
                        contact_cost += single_contact_cost

                # Update costs
                # Update costs
                if "cost" not in record:
                    record["cost"] = {
                        "domain_usd": 0.0,
                        "crawl_usd": 0.0,
                        "enrich_usd": 0.0,
                        "total_usd": 0.0,
                    }
                record["cost"]["enrich_usd"] = company_cost + contact_cost
                recompute_total_cost(record)  # Update total cost
                total_cost += company_cost + contact_cost

                # Update provenance
                if "provenance" not in record:
                    record["provenance"] = {}

                record["provenance"]["enriched_at"] = now_z()
                record["provenance"]["tool_versions"] = record["provenance"].get(
                    "tool_versions", {}
                )
                record["provenance"]["tool_versions"]["enrich"] = {
                    "version": INTERNAL_VERSION,
                    "schema_version": schema_checksum,
                }

                # Set evidence path
                evidence_data = {
                    "domain": normalized_domain,
                    "enriched_at": now_z(),
                    "company_enrichment": company,
                    "contacts_enrichment": contacts,
                    "costs": {
                        "company_usd": company_cost,
                        "contact_usd": contact_cost,
                        "total_usd": company_cost + contact_cost,
                    },
                }

                evidence_path = write_evidence_file(
                    normalized_domain, evidence_data, data_dir
                )
                record["provenance"]["evidence_paths"] = record["provenance"].get(
                    "evidence_paths", {}
                )
                record["provenance"]["evidence_paths"]["enrich"] = evidence_path

                # Update status

                # Check if all required fields are filled
                required_fields = icp_config.get("required_fields", {})

                # Handle both old format (list) and new format (dict)
                if isinstance(required_fields, list):
                    # Old format: required_fields is a list, assume all are company fields
                    required_company_fields = required_fields
                    required_contact_fields = []
                elif isinstance(required_fields, dict):
                    # New format: required_fields is a dict with company/contact keys
                    required_company_fields = required_fields.get("company", [])
                    required_contact_fields = required_fields.get("contact", [])
                else:
                    # Fallback
                    required_company_fields = []
                    required_contact_fields = []

                company_complete = all(
                    company.get(field) for field in required_company_fields
                )

                contact_complete = True
                if required_contact_fields and contacts:
                    best_contact = next(
                        (c for c in contacts if c.get("contact_id") == best_contact_id),
                        None,
                    )
                    if best_contact:
                        contact_complete = all(
                            best_contact.get(field) for field in required_contact_fields
                        )
                    else:
                        contact_complete = False

                if company_complete and contact_complete:
                    new_status = "enriched"
                    enriched_count += 1
                else:
                    new_status = "enrich_partial"
                    partial_count += 1

                # Update status and append to history
                record["status"] = new_status
                append_status(
                    record["status_history"],
                    new_status,
                    f"Enrichment completed. Company: {company_complete}, Contact: {contact_complete}",
                )

                # Append audit entry
                append_audit(
                    record,
                    "Enrich",
                    f"Enriched company and contacts. Cost: ${company_cost + contact_cost:.4f}",
                )

                # Truncate evidence arrays
                truncate_evidence_arrays(record)

                # Validate schema
                validation_errors = validate_envelope(record, TOOL_NAME)
                if validation_errors:
                    errors.extend(validation_errors)

                processed_records.append(record)

            except Exception as exc:
                # Handle individual record errors

                # Create a more specific error message based on the actual error
                if "'list' object has no attribute 'get'" in str(exc):
                    if "402" in str(exc) or "credits" in str(exc).lower():
                        error_msg = "API credits exhausted - some enrichment features unavailable"
                    else:
                        error_msg = "API response format issue - contact discovery may be unavailable"
                elif "402" in str(exc) or "Payment Required" in str(exc):
                    if "Snov.io" in str(exc) or "contact" in str(exc).lower():
                        error_msg = (
                            "Snov.io API credits exhausted - contact discovery skipped"
                        )
                    else:
                        error_msg = "CoreSignal API credits exhausted - company enrichment limited"
                else:
                    error_msg = f"Enrichment failed: {str(exc)}"

                # Ensure record is a dictionary
                if not isinstance(record, dict):
                    logging.error(
                        f"⚠️ Record is not a dictionary: {type(record)}, content: {record}"
                    )
                    # Create a minimal error without trying to access record fields
                    error = build_error(
                        ErrorCode.UNKNOWN,
                        exc=exc,
                        tool=TOOL_NAME,
                        lead_id="unknown",
                        context={
                            "error": "Record is not a dictionary",
                            "record_type": str(type(record)),
                        },
                    )
                else:
                    error = build_error(
                        ErrorCode.UNKNOWN,
                        exc=exc,
                        tool=TOOL_NAME,
                        lead_id=record.get("lead_id"),
                        context={"domain": record.get("domain", "")},
                    )
                errors.append(error)

                # Keep the record but mark as failed
                record["status"] = "enrich_partial"

                # Ensure status_history exists and is a list
                if "status_history" not in record:
                    record["status_history"] = []
                elif not isinstance(record["status_history"], list):
                    logging.warning(
                        f"⚠️ status_history is not a list for {record.get('domain', 'unknown')}, resetting to empty list"
                    )
                    record["status_history"] = []

                try:
                    append_status(
                        record["status_history"],
                        "enrich_partial",
                        error_msg,
                    )
                except Exception as append_error:
                    logging.error(
                        f"⚠️ Failed to append status for {record.get('domain', 'unknown')}: {append_error}"
                    )
                    # Create a minimal status entry manually
                    record["status_history"].append(
                        {
                            "status": "enrich_partial",
                            "ts": now_z(),
                            "notes": f"Enrichment failed: {str(exc)} (status append also failed: {append_error})",
                        }
                    )

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
                "total": total_cost,
            },
        )

        return {
            "data": {"lead_records": processed_records},
            "errors": errors,
            "metrics": metrics,
        }

    except Exception as exc:
        # Handle tool-level errors
        error = build_error(ErrorCode.UNKNOWN, exc=exc, tool=TOOL_NAME)
        duration_ms = int((time.time() - start_time) * 1000)

        return {
            "data": {"lead_records": []},
            "errors": [error],
            "metrics": build_metrics(0, 0, duration_ms),
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
            "errors": [
                build_error(ErrorCode.SCHEMA_VALIDATION, exc=exc, tool=TOOL_NAME)
            ],
            "metrics": build_metrics(0, 0, 0),
        }
        print(json.dumps(error_result))
        exit(1)

    except Exception as exc:
        # Handle other errors
        error_result = {
            "data": {"lead_records": []},
            "errors": [build_error(ErrorCode.UNKNOWN, exc=exc, tool=TOOL_NAME)],
            "metrics": build_metrics(0, 0, 0),
        }
        print(json.dumps(error_result))
        exit(1)


if __name__ == "__main__":
    main()
