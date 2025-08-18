"""
Crawl Tool for Lead Sorcerer

This tool fetches company websites, extracts company and contact information,
and validates ICP fit based on crawled data.

Purpose: Fetch site, extract company & contacts, re-validate ICP; emit one row per contact
(plus company-only if none).

Inputs: { "lead_records": [...], "icp_config": {...} }
Output: lead_records[] with company + 0..N contacts + icp.crawl_score

Authoritative specifications: docs/brd.md §273-320
"""

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from firecrawl import FirecrawlApp
from .common import (
    AsyncSemaphorePool,
    ErrorCode,
    PermitManager,
    append_audit,
    append_status,
    build_error,
    canonicalize_linkedin,
    compute_content_hash,
    compute_next_revisit,
    generate_contact_id,
    get_role_priority,
    get_seniority_rank,
    load_costs_config,
    load_schema_checksum,
    normalize_domain,
    normalize_text,
    now_z,
    resolve_data_dir,
    round4,
    setup_logging,
    truncate_evidence_arrays,
    write_with_lock,
)


# ============================================================================
# Constants and Configuration
# ============================================================================

INTERNAL_VERSION = "1.0.0"
TOOL_NAME = "crawl"

# Firecrawl extraction schema - using JSON Schema format
FIRECRAWL_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "industry": {"type": "string"},
                "hq_location": {"type": "string"},
                "socials": {
                    "type": "object",
                    "properties": {
                        "linkedin": {"type": "string"}
                    }
                },
                "careers_url": {"type": "string"},
                "blog_url": {"type": "string"}
            }
        },
        "employees": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "full_name": {"type": "string"},
                    "role": {"type": "string"},
                    "linkedin": {"type": "string"},
                    "email": {"type": "string"}
                }
            }
        }
    }
}


# ============================================================================
# Main Tool Class
# ============================================================================


class CrawlTool:
    """Crawl tool for extracting company and contact information from websites."""

    def __init__(self):
        self.logger = setup_logging(TOOL_NAME)
        self.schema_version = load_schema_checksum()
        self.costs_config = load_costs_config()

        # Validate required providers
        required_providers = ["firecrawl"]
        for provider in required_providers:
            if provider not in self.costs_config:
                raise KeyError(
                    f"Missing required provider in costs configuration: {provider}"
                )

        # Initialize Firecrawl client
        self.firecrawl_key = os.environ.get("FIRECRAWL_KEY")
        if not self.firecrawl_key:
            raise ValueError("FIRECRAWL_KEY environment variable is required")

        self.firecrawl_client = FirecrawlApp(api_key=self.firecrawl_key)
        # Global permit manager for concurrency control
        self.permit_manager = PermitManager(
            max_permits=3
        )  # Default, will be overridden
        self.async_semaphore_pool = AsyncSemaphorePool(self.permit_manager)

    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point for the crawl tool.

        Args:
            payload: Input payload with lead_records and icp_config

        Returns:
            Standard envelope with data, errors, and metrics
        """
        start_time = time.time()

        self.logger.info(
            f"🚀 Crawl tool starting with payload: {len(payload.get('lead_records', []))} lead records"
        )
        self.logger.info(
            f"📋 ICP config keys: {list(payload.get('icp_config', {}).keys())}"
        )

        try:
            # Note: We don't validate the input envelope here since it's a tool input payload
            # The validate_envelope function is for validating individual lead records, not tool inputs
            self.logger.info("🔍 Processing tool input payload...")

            # Extract and validate required fields
            lead_records = payload.get("lead_records", [])
            icp_config = payload.get("icp_config", {})

            self.logger.info(
                f"📊 Extracted {len(lead_records)} lead records from payload"
            )
            self.logger.info(f"⚙️ ICP config: {len(icp_config)} configuration items")

            if not lead_records:
                self.logger.warning("⚠️ No lead records found in payload")
                return {
                    "data": {"lead_records": []},
                    "errors": [],
                    "metrics": self._build_metrics(0, 0, 0),
                }

            # Update concurrency limits from icp_config
            max_concurrent = icp_config.get("concurrency", {}).get(
                "max_concurrent_requests", 3
            )
            self.permit_manager.max_permits = max_concurrent

            # Validate testing flags
            testing = icp_config.get("testing", {})
            process_rejected = testing.get("process_rejected", False)
            process_low_crawl = testing.get("process_low_crawl", False)

            # Filter records based on status and testing flags
            self.logger.info("🔍 Filtering records based on status...")
            records_to_process = []
            for record in lead_records:
                status = record.get("status", "")
                domain = record.get("domain", "unknown")
                self.logger.info(f"📋 Record {domain}: status='{status}'")

                if status == "scored":
                    self.logger.info(
                        f"✅ Adding {domain} to processing queue (status: scored)"
                    )
                    records_to_process.append(record)
                elif status == "crawled" and process_low_crawl:
                    self.logger.info(
                        f"🔄 Adding {domain} to processing queue (status: crawled, process_low_crawl: true)"
                    )
                    records_to_process.append(record)
                elif status == "crawl_failed" and process_rejected:
                    self.logger.info(
                        f"🔄 Adding {domain} to processing queue (status: crawl_failed, process_rejected: true)"
                    )
                    records_to_process.append(record)
                else:
                    self.logger.info(
                        f"⏭️ Skipping {domain} (status: {status}, process_low_crawl: {process_low_crawl}, process_rejected: {process_rejected})"
                    )

            self.logger.info(
                f"📊 Filtering complete: {len(records_to_process)} records to process out of {len(lead_records)} total"
            )

            if not records_to_process:
                self.logger.warning("⚠️ No records to process after filtering")
                return {
                    "data": {"lead_records": lead_records},
                    "errors": [],
                    "metrics": self._build_metrics(
                        len(lead_records), len(lead_records), 0
                    ),
                }

            # Process records
            processed_records = []
            errors = []
            cache_hits = 0
            cache_misses = 0
            total_cost = 0.0

            for record in records_to_process:
                try:
                    result = await self._process_single_record(record, icp_config)
                    if result["success"]:
                        processed_records.append(result["record"])
                        if result["cache_hit"]:
                            cache_hits += 1
                        else:
                            cache_misses += 1
                        total_cost += result["cost"]
                    else:
                        processed_records.append(result["record"])
                        if result["error"]:
                            errors.append(result["error"])
                except Exception as exc:
                    self.logger.error(
                        f"Unexpected error processing record {record.get('lead_id', 'unknown')}: {exc}"
                    )
                    error = build_error(
                        code=ErrorCode.UNKNOWN,
                        exc=exc,
                        tool=TOOL_NAME,
                        lead_id=record.get("lead_id"),
                    )
                    errors.append(error)
                    processed_records.append(record)

            # Update all records with processed data
            final_records = []
            for original_record in lead_records:
                # Find processed version
                processed_record = next(
                    (
                        r
                        for r in processed_records
                        if r.get("lead_id") == original_record.get("lead_id")
                    ),
                    original_record,
                )
                final_records.append(processed_record)

            # Calculate metrics
            duration_ms = int((time.time() - start_time) * 1000)
            cache_hit_rate = (
                cache_hits / (cache_hits + cache_misses)
                if (cache_hits + cache_misses) > 0
                else None
            )

            # Calculate pass rate: enrich_ready / crawled
            crawled_count = sum(
                1 for r in final_records if r.get("status") == "crawled"
            )
            enrich_ready_count = sum(
                1 for r in final_records if r.get("status") == "enrich_ready"
            )
            pass_rate = (
                enrich_ready_count / crawled_count if crawled_count > 0 else None
            )

            return {
                "data": {"lead_records": final_records},
                "errors": errors,
                "metrics": self._build_metrics(
                    len(lead_records),
                    len(final_records),
                    duration_ms,
                    cache_hit_rate,
                    pass_rate,
                    {"crawl": total_cost},
                ),
            }

        except Exception as exc:
            self.logger.error(f"Fatal error in crawl tool: {exc}")
            error = build_error(code=ErrorCode.UNKNOWN, exc=exc, tool=TOOL_NAME)
            return {
                "data": {
                    "lead_records": lead_records if "lead_records" in locals() else []
                },
                "errors": [error],
                "metrics": self._build_metrics(
                    len(lead_records) if "lead_records" in locals() else 0,
                    0,
                    int((time.time() - start_time) * 1000),
                ),
            }

    async def _process_single_record(
        self, record: Dict[str, Any], icp_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single lead record.

        Args:
            record: Lead record to process
            icp_config: ICP configuration

        Returns:
            Dictionary with success status, processed record, cache hit status, cost, and optional error
        """
        lead_id = record.get("lead_id")
        domain = record.get("domain")

        if not domain:
            error = build_error(
                code=ErrorCode.SCHEMA_VALIDATION,
                exc=ValueError("Missing domain in record"),
                tool=TOOL_NAME,
                lead_id=lead_id,
            )
            return {
                "success": False,
                "record": record,
                "cache_hit": False,
                "cost": 0.0,
                "error": error,
            }

        # Normalize domain to eTLD+1
        normalized_domain = normalize_domain(domain)
        if normalized_domain != domain:
            record["domain"] = normalized_domain

        # Check artifact cache
        data_dir = resolve_data_dir({"config": {"data_dir": None}})
        artifact_path = f"{data_dir}/crawl_artifacts/{normalized_domain}.json"

        cache_hit = False
        extracted_data = None

        # Check if artifact exists and is fresh
        if os.path.exists(artifact_path):
            try:
                with open(artifact_path, "r") as f:
                    artifact = json.load(f)

                # Check TTL
                crawl_ttl_days = icp_config.get("refresh_policy", {}).get(
                    "crawl_ttl_days", 14
                )
                crawled_at = artifact.get("crawled_at")

                if crawled_at:
                    try:
                        crawled_dt = datetime.fromisoformat(
                            crawled_at.replace("Z", "+00:00")
                        )
                        # Ensure crawled_dt is timezone-aware
                        if crawled_dt.tzinfo is None:
                            crawled_dt = crawled_dt.replace(tzinfo=timezone.utc)

                        if datetime.now(timezone.utc) - crawled_dt < timedelta(
                            days=crawl_ttl_days
                        ):
                            # Check content hash
                            current_hash = compute_content_hash(
                                artifact.get("extracted_data", {})
                            )
                            if current_hash == artifact.get("content_hash"):
                                cache_hit = True
                                extracted_data = artifact.get("extracted_data")
                                self.logger.info(
                                    f"Cache hit for domain {normalized_domain}"
                                )
                    except ValueError:
                        # Invalid timestamp, treat as cache miss
                        pass
            except Exception as exc:
                self.logger.warning(
                    f"Failed to read artifact for {normalized_domain}: {exc}"
                )

        # Extract data if not cached
        if not cache_hit:
            try:
                extracted_data = await self._extract_with_firecrawl(normalized_domain)

                # Store artifact
                artifact_data = {
                    "crawled_at": now_z(),
                    "content_hash": compute_content_hash(extracted_data),
                    "extracted_data": extracted_data,
                }

                # Ensure directory exists
                os.makedirs(os.path.dirname(artifact_path), exist_ok=True)

                # Write with lock
                write_with_lock(artifact_path, artifact_data)

                self.logger.info(
                    f"Extracted and cached data for domain {normalized_domain}"
                )

            except Exception as exc:
                self.logger.error(
                    f"Failed to extract data for {normalized_domain}: {exc}"
                )
                error = build_error(
                    code=ErrorCode.EXTRACT_ERROR,
                    exc=exc,
                    tool=TOOL_NAME,
                    lead_id=lead_id,
                    context={"domain": normalized_domain},
                )

                # Set status to crawl_failed
                record["status"] = "crawl_failed"
                if "status_history" not in record:
                    record["status_history"] = []
                append_status(
                    record["status_history"],
                    "crawl_failed",
                    f"Extraction failed: {exc}",
                )

                failure_revisit_days = icp_config.get("refresh_policy", {}).get(
                    "failure_revisit_days", 1
                )
                if "provenance" not in record:
                    record["provenance"] = {}
                record["provenance"]["next_revisit_at"] = compute_next_revisit(
                    record["provenance"].get("next_revisit_at"),
                    failure_revisit_days,
                    is_failure=True,
                )

                return {
                    "success": False,
                    "record": record,
                    "cache_hit": False,
                    "cost": 0.0,
                    "error": error,
                }

        # Process extracted data (including cache hits)
        if extracted_data or cache_hit:
            try:
                self._process_extracted_data(record, extracted_data, icp_config)

                # Very permissive logic: Pass through leads by default
                # Only reject if we have clear evidence they're not dental practices

                # Check if this is clearly NOT a dental practice
                company = record.get("company", {})
                industry = company.get("industry", "").lower()
                name = company.get("name", "").lower()

                # Only reject if we have clear evidence it's not dental-related
                is_dental_related = (
                    "dental" in industry or
                    "dental" in name or
                    "dentist" in name or
                    "orthodont" in name or
                    "oral" in industry or
                    "oral" in name
                )

                if is_dental_related:
                    record["status"] = "enrich_ready"
                    append_status(
                        record.get("status_history", []),
                        "enrich_ready",
                        "Dental practice identified - ready for enrichment",
                    )
                else:
                    record["status"] = "crawled"
                    if "status_history" not in record:
                        record["status_history"] = []
                    append_status(
                        record.get("status_history", []),
                        "crawled",
                        "Not clearly dental-related - needs further validation",
                    )

                # Update provenance
                record["provenance"]["crawled_at"] = now_z()
                record["provenance"]["evidence_paths"]["crawl"] = artifact_path

                # Set next_revisit_at
                revisit_after_days = icp_config.get("refresh_policy", {}).get(
                    "revisit_after_days", 90
                )
                record["provenance"]["next_revisit_at"] = compute_next_revisit(
                    record["provenance"].get("next_revisit_at"), revisit_after_days
                )

                # Update tool versions
                if "tool_versions" not in record["provenance"]:
                    record["provenance"]["tool_versions"] = {}
                record["provenance"]["tool_versions"]["crawl"] = {
                    "version": INTERNAL_VERSION,
                    "schema_version": self.schema_version,
                }

                # Add audit trail
                append_audit(
                    record,
                    "Crawl",
                    f"Extracted {len(record.get('contacts', []))} contacts from {normalized_domain}",
                )

                # Truncate evidence arrays
                truncate_evidence_arrays(record)

                cost = 0.0 if cache_hit else self.costs_config["firecrawl"]
                if "cost" not in record:
                    record["cost"] = {
                        "domain_usd": 0.0,
                        "crawl_usd": 0.0,
                        "enrich_usd": 0.0,
                        "total_usd": 0.0,
                    }
                record["cost"]["crawl_usd"] = round4(cost)
                record["cost"]["total_usd"] = round4(
                    record["cost"].get("domain_usd", 0.0)
                    + record["cost"].get("crawl_usd", 0.0)
                    + record["cost"].get("enrich_usd", 0.0)
                )

                return {
                    "success": True,
                    "record": record,
                    "cache_hit": cache_hit,
                    "cost": cost,
                    "error": None,
                }

            except Exception as exc:
                self.logger.error(
                    f"Failed to process extracted data for {normalized_domain}: {exc}"
                )
                error = build_error(
                    code=ErrorCode.EXTRACT_ERROR,
                    exc=exc,
                    tool=TOOL_NAME,
                    lead_id=lead_id,
                    context={"domain": normalized_domain},
                )

                # Set status to crawl_failed
                record["status"] = "crawl_failed"
                append_status(
                    record.get("status_history", []),
                    "crawl_failed",
                    f"Data processing failed: {exc}",
                )

                return {
                    "success": False,
                    "record": record,
                    "cache_hit": cache_hit,
                    "cost": 0.0,
                    "error": error,
                }

        return {
            "success": False,
            "record": record,
            "cache_hit": cache_hit,
            "cost": 0.0,
            "error": None,
        }

    async def _extract_with_firecrawl(self, domain: str) -> Dict[str, Any]:
        """
        Extract data from domain using Firecrawl.

        Args:
            domain: Domain to extract from

        Returns:
            Extracted data dictionary
        """
        self.logger.info(f"🔍 Starting Firecrawl extraction for domain: {domain}")
        self.logger.info(
            f"🔑 Firecrawl API key: {self.firecrawl_key[:10]}..."
            if self.firecrawl_key
            else "❌ No API key"
        )
        self.logger.info(f"📋 Using schema: {FIRECRAWL_EXTRACT_SCHEMA}")

        async with self.async_semaphore_pool:
            self.logger.info(f"🔒 Acquired semaphore for domain: {domain}")
            try:
                # Try HTTPS first, fallback to HTTP
                urls_to_try = [f"https://{domain}", f"http://{domain}"]
                self.logger.info(f"🌐 Will try URLs: {urls_to_try}")

                for url in urls_to_try:
                    self.logger.info(f"📡 Attempting extraction from: {url}")
                    try:
                        # Call Firecrawl extract tool
                        self.logger.info(
                            f"🤖 Calling Firecrawl API with urls=[{url}] and schema..."
                        )
                        response = await asyncio.wait_for(
                            asyncio.to_thread(
                                self.firecrawl_client.extract,
                                urls=[url],  # Use 'urls' parameter (list)
                                schema=FIRECRAWL_EXTRACT_SCHEMA,
                            ),
                            timeout=10.0,  # 10 second timeout per attempt
                        )

                        if response and hasattr(response, 'success') and response.success:
                            self.logger.info(f"✅ Firecrawl extraction successful for {url}")
                            return response.data if hasattr(response, 'data') else {}
                        else:
                            self.logger.warning(
                                f"Firecrawl extract failed for {url}: {response}"
                            )

                    except asyncio.TimeoutError:
                        self.logger.warning(f"Timeout extracting from {url}")
                        continue
                    except Exception as exc:
                        self.logger.warning(f"Failed to extract from {url}: {exc}")
                        continue

                # If all attempts failed
                raise Exception(
                    f"Failed to extract data from {domain} after trying both HTTP and HTTPS"
                )

            except Exception as exc:
                raise Exception(f"Firecrawl extraction failed: {exc}")

    def _process_extracted_data(
        self,
        record: Dict[str, Any],
        extracted_data: Dict[str, Any],
        icp_config: Dict[str, Any],
    ) -> None:
        """
        Process extracted data and populate record fields.

        Args:
            record: Lead record to populate
            extracted_data: Data extracted from Firecrawl
            icp_config: ICP configuration
        """
        # Process company data
        company_data = extracted_data.get("company", {})
        if "company" not in record:
            record["company"] = {}

        company = record["company"]

        # Populate company fields
        company["name"] = company_data.get("name")
        company["description"] = company_data.get("description")
        company["industry"] = company_data.get("industry")

        # Initialize company structures
        if "ids" not in company:
            company["ids"] = {"linkedin": None, "crunchbase": None}
        if "socials" not in company:
            company["socials"] = {
                "linkedin": None,
                "github": None,
                "twitter": None,
                "telegram": None,
                "instagram": None,
            }

        # Handle LinkedIn
        linkedin_url = company_data.get("socials", {}).get("linkedin")
        if linkedin_url:
            link_type, slug = canonicalize_linkedin(linkedin_url)
            if link_type == "company":
                company["ids"]["linkedin"] = f"/company/{slug}"
                company["socials"]["linkedin"] = (
                    f"https://www.linkedin.com/company/{slug}"
                )
            elif link_type == "in":
                # This is a person, not company - skip
                pass

        company["careers_url"] = company_data.get("careers_url")
        company["blog_url"] = company_data.get("blog_url")

        # Add evidence URLs
        if "evidence_urls" not in company:
            company["evidence_urls"] = []

        # Add the crawled URL as evidence
        domain = record.get("domain", "")
        if domain:
            company["evidence_urls"].append(f"https://{domain}")

        # Calculate crawl score based on processed data
        self._validate_icp_fit(record, icp_config)

        # Process contacts
        employees = extracted_data.get("employees", [])
        contacts = []

        for employee in employees:
            full_name = employee.get("full_name")
            role = employee.get("role")
            linkedin = employee.get("linkedin")
            email = employee.get("email")

            if not full_name or not role:
                continue

            # Normalize name and role
            normalized_name = normalize_text(full_name)
            normalized_role = normalize_text(role)

            # Generate contact ID
            contact_id = generate_contact_id(
                domain, normalized_name, normalized_role, linkedin or ""
            )

            # Check if contact already exists
            existing_contact = next(
                (c for c in contacts if c.get("contact_id") == contact_id), None
            )

            if existing_contact:
                # Update existing contact with new information
                if email and not existing_contact.get("email"):
                    existing_contact["email"] = email.lower()
                if linkedin and not existing_contact.get("linkedin"):
                    existing_contact["linkedin"] = linkedin
                continue

            # Create new contact
            contact = {
                "contact_id": contact_id,
                "full_name": normalized_name,
                "role": normalized_role,
                "department": None,
                "seniority": None,
                "role_priority": None,
                "email": email.lower() if email else None,
                "email_confidence": None,
                "email_status": ["unknown"],
                "email_source": ["provider"],
                "phone": None,
                "linkedin": None,
                "other_links": [],
                "evidence_urls": [],
            }

            # Handle LinkedIn
            if linkedin:
                link_type, slug = canonicalize_linkedin(linkedin)
                if link_type == "in":
                    contact["linkedin"] = f"/in/{slug}"
                elif link_type == "company":
                    # This is a company page, not a person - skip
                    continue

            # Set seniority and role priority
            contact["seniority"] = get_seniority_rank(role)

            role_priority_config = icp_config.get("role_priority", {})
            contact["role_priority"] = get_role_priority(role, role_priority_config)

            # Add evidence URLs
            if domain:
                contact["evidence_urls"].append(f"https://{domain}")

            contacts.append(contact)

        # Update record with contacts
        record["contacts"] = contacts

        # Perform ICP validation
        self._validate_icp_fit(record, icp_config)

    def _check_company_requirements(
        self, record: Dict[str, Any], required_fields: List[str]
    ) -> bool:
        """
        Check if company meets required field requirements.

        Args:
            record: Lead record
            required_fields: List of required company fields

        Returns:
            True if all required fields are satisfied
        """
        if not required_fields:
            return True

        company = record.get("company", {})

        for field in required_fields:
            value = company.get(field)
            if not value:
                return False

        return True

    def _validate_icp_fit(
        self, record: Dict[str, Any], icp_config: Dict[str, Any]
    ) -> None:
        """
        Validate ICP fit based on crawled data.

        Args:
            record: Lead record to validate
            icp_config: ICP configuration
        """
        # This is a simplified ICP validation
        # In practice, this would use more sophisticated logic based on company data

        company = record.get("company", {})
        contacts = record.get("contacts", [])

        # More permissive scoring - pass by default unless clear ICP violations
        score = 0.5  # Start with a passing score
        reasons = ["Basic company information available"]

        # Bonus points for additional data
        if company.get("name"):
            score += 0.1
            reasons.append("Company name available")

        if company.get("industry"):
            score += 0.1
            reasons.append("Industry information available")

        if company.get("hq_location"):
            score += 0.1
            reasons.append("Location information available")

        if contacts:
            score += 0.2
            reasons.append(f"Found {len(contacts)} contacts")

            # High-quality contacts (with email) are more valuable
            contacts_with_email = sum(1 for c in contacts if c.get("email"))
            if contacts_with_email > 0:
                score += 0.1
                reasons.append(f"{contacts_with_email} contacts have email addresses")

        # Cap score at 1.0
        score = min(score, 1.0)

        # Update record
        if "icp" not in record:
            record["icp"] = {}

        record["icp"]["crawl_score"] = round4(score)
        record["icp"]["crawl_reason"] = (
            "; ".join(reasons) if reasons else "No specific reasons"
        )

    def _build_metrics(
        self,
        count_in: int,
        count_out: int,
        duration_ms: int,
        cache_hit_rate: Optional[float] = None,
        pass_rate: Optional[float] = None,
        cost_usd: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Build metrics structure for tool output.

        Args:
            count_in: Number of input records
            count_out: Number of output records
            duration_ms: Tool runtime in milliseconds
            cache_hit_rate: Cache hit rate (0.0 to 1.0)
            pass_rate: Pass rate (0.0 to 1.0)
            cost_usd: Cost breakdown by stage

        Returns:
            Metrics dictionary
        """
        metrics = {
            "count_in": count_in,
            "count_out": count_out,
            "duration_ms": duration_ms,
            "cache_hit_rate": round4(cache_hit_rate)
            if cache_hit_rate is not None
            else None,
            "pass_rate": round4(pass_rate) if pass_rate is not None else None,
            "cost_usd": {
                "domain": 0.0,
                "crawl": round4(cost_usd.get("crawl", 0.0)) if cost_usd else 0.0,
                "enrich": 0.0,
                "total": round4(cost_usd.get("crawl", 0.0)) if cost_usd else 0.0,
            },
        }

        return metrics


# ============================================================================
# CLI Interface
# ============================================================================


def main():
    """CLI entry point for the crawl tool."""
    import sys

    try:
        # Read JSON from stdin
        input_data = sys.stdin.read()
        payload = json.loads(input_data)

        # Create tool instance
        tool = CrawlTool()

        # Run tool
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(tool.run(payload))
        loop.close()

        # Write JSON to stdout
        json.dump(result, sys.stdout)

    except json.JSONDecodeError as exc:
        error_result = {
            "data": {"lead_records": []},
            "errors": [
                {
                    "code": "SCHEMA_VALIDATION",
                    "message": f"Invalid JSON input: {exc}",
                    "tool": TOOL_NAME,
                    "retryable": False,
                }
            ],
            "metrics": {
                "count_in": 0,
                "count_out": 0,
                "duration_ms": 0,
                "cache_hit_rate": None,
                "pass_rate": None,
                "cost_usd": {"domain": 0.0, "crawl": 0.0, "enrich": 0.0, "total": 0.0},
            },
        }
        json.dump(error_result, sys.stdout)
        sys.exit(1)
    except Exception as exc:
        error_result = {
            "data": {"lead_records": []},
            "errors": [
                {
                    "code": "UNKNOWN",
                    "message": f"Fatal error: {exc}",
                    "tool": TOOL_NAME,
                    "retryable": False,
                }
            ],
            "metrics": {
                "count_in": 0,
                "count_out": 0,
                "duration_ms": 0,
                "cache_hit_rate": None,
                "pass_rate": None,
                "cost_usd": {"domain": 0.0, "crawl": 0.0, "enrich": 0.0, "total": 0.0},
            },
        }
        json.dump(error_result, sys.stdout)
        sys.exit(1)


if __name__ == "__main__":
    main()
