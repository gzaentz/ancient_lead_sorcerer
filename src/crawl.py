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

# Firecrawl extraction schema - using v2 API format (COST OPTIMIZED)
FIRECRAWL_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Company name"},
                "description": {
                    "type": "string",
                    "description": "Business description",
                },
                "industry": {"type": "string", "description": "Industry or sector"},
                "hq_location": {
                    "type": "string",
                    "description": "Headquarters location (city, state, country)",
                },
                "number_of_locations": {
                    "type": "integer",
                    "description": "Total number of office locations",
                },
                "locations_summary": {
                    "type": "object",
                    "properties": {
                        "primary_location": {
                            "type": "object",
                            "properties": {
                                "city": {"type": "string", "description": "City name"},
                                "state": {
                                    "type": "string",
                                    "description": "State/province",
                                },
                                "country": {
                                    "type": "string",
                                    "description": "Country name",
                                },
                            },
                        },
                        "location_count_by_state": {
                            "type": "object",
                            "description": "Count of locations by state/province (e.g., 'NJ': 15, 'NY': 3)",
                        },
                        "representative_locations": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 5,
                            "description": "Sample of 3-5 location cities (not exhaustive)",
                        },
                    },
                },
                "founded_year": {
                    "type": "integer",
                    "description": "Year company was founded",
                },
                "employee_count": {
                    "type": "string",
                    "description": "Number of employees or range",
                },
                "revenue_range": {
                    "type": "string",
                    "description": "Annual revenue range",
                },
                "ownership_type": {
                    "type": "string",
                    "description": "Private, public, nonprofit, etc.",
                },
                "company_type": {
                    "type": "string",
                    "description": "LLC, Corp, Partnership, etc.",
                },
                "emails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                    "description": "Company email addresses (limit to 5 most important)",
                },
                "phone_numbers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 3,
                    "description": "Company phone numbers (limit to 3 main numbers)",
                },
                "careers_url": {
                    "type": "string",
                    "description": "URL to careers/jobs page",
                },
                "blog_url": {"type": "string", "description": "URL to company blog"},
                "socials": {
                    "type": "object",
                    "properties": {
                        "linkedin": {
                            "type": "string",
                            "description": "LinkedIn company page URL",
                        },
                        "facebook": {
                            "type": "string",
                            "description": "Facebook page URL",
                        },
                        "twitter": {
                            "type": "string",
                            "description": "Twitter/X profile URL",
                        },
                        "instagram": {
                            "type": "string",
                            "description": "Instagram profile URL",
                        },
                        "youtube": {
                            "type": "string",
                            "description": "YouTube channel URL",
                        },
                    },
                },
                "tech_stack": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 10,
                    "description": "Technologies and tools used by the company (limit to 10)",
                },
                "specialties": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 8,
                    "description": "Company specialties or focus areas (limit to 8)",
                },
                "intent": {
                    "type": "object",
                    "properties": {
                        "business_intent_score": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Confidence score (0-1) that company matches ICP intent",
                        },
                        "intent_signals": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 10,
                            "description": "Specific evidence found indicating intent",
                        },
                        "intent_category": {
                            "type": "string",
                            "description": "Primary intent category based on signals found",
                        },
                        "timeline_indicator": {
                            "type": "string",
                            "description": "When they might act on this intent",
                        },
                        "decision_maker_intent": {
                            "type": "string",
                            "description": "Specific decision maker's stated or implied intent",
                        },
                    },
                },
            },
        },
        "team_members": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Full name"},
                    "role": {"type": "string", "description": "Job title/role"},
                    "department": {
                        "type": "string",
                        "description": "Department or division",
                    },
                    "email": {"type": "string", "description": "Email address"},
                    "phone": {"type": "string", "description": "Phone number"},
                    "linkedin": {
                        "type": "string",
                        "description": "LinkedIn profile URL",
                    },
                    "decision_maker": {
                        "type": "boolean",
                        "description": "Whether this person is a decision maker",
                    },
                    "location": {
                        "type": "string",
                        "description": "Office location if specified",
                    },
                },
            },
            "maxItems": 15,
            "description": "Staff members and their contact information (limit to 15 most important)",
        },
    },
}

# Firecrawl extraction prompt - COST OPTIMIZED with DYNAMIC INTENT
FIRECRAWL_EXTRACT_PROMPT = (
    "Extract essential business intelligence for lead generation. Focus on SUMMARY data, not exhaustive details.\n\n"
    "CRITICAL EXTRACTION RULES:\n"
    "- Use only on-domain pages (homepage, /about, /locations, /contact, /team, /careers)\n"
    "- Do NOT invent data; use nulls when unknown\n"
    "- Prioritize business intelligence over exhaustive detail\n"
    "- Limit arrays to reasonable sizes (see schema maxItems)\n\n"
    "LOCATION OPTIMIZATION (CRITICAL FOR COST):\n"
    "- Extract TOTAL COUNT of locations\n"
    "- Get PRIMARY location details only\n"
    "- Provide LOCATION SUMMARY by state (e.g., 'NJ': 15, 'NY': 3)\n"
    "- List 3-5 REPRESENTATIVE location cities (not every single one)\n"
    "- DO NOT extract detailed address for every location\n\n"
    "INTENT ANALYSIS FRAMEWORK (DYNAMIC - HIGHEST PRIORITY):\n"
    "The ICP configuration will provide specific intent signals to look for.\n"
    "Follow these general intent detection principles:\n"
    "- Look for TRANSITION language (succession, retirement, growth, partnership)\n"
    "- Identify TIMELINE indicators (age, years in business, expansion plans)\n"
    "- Detect OWNERSHIP changes (acquisitions, mergers, private equity)\n"
    "- Find DECISION MAKER statements about future plans\n"
    "- Analyze CAREER pages for leadership changes or growth signals\n\n"
    "CONTACT OPTIMIZATION:\n"
    "- Company emails: limit to 5 most important (info@, contact@, etc.)\n"
    "- Company phones: limit to 3 main numbers\n"
    "- Team members: limit to 15 most important (executives, directors, managers)\n\n"
    "COMPANY DATA PRIORITIES:\n"
    "- Company name, description, industry\n"
    "- HQ location (city, state, country)\n"
    "- Total location count and location summary\n"
    "- Founded year, employee count, revenue range\n"
    "- Ownership type, company type\n"
    "- Social media profiles\n"
    "- Tech stack (limit 10), specialties (limit 8)\n\n"
    "TEAM MEMBER DATA:\n"
    "- Focus on decision makers and executives\n"
    "- Limit to 15 most important contacts\n"
    "- Include role, department, contact info\n\n"
    "COST CONTROL:\n"
    "- Avoid exhaustive location listings\n"
    "- Use summary data instead of detailed arrays\n"
    "- Focus on business intelligence, not data completeness\n"
    "- If you find 25 locations, extract count and sample, not all 25\n"
)


# ============================================================================
# Main Tool Class
# ============================================================================


class CrawlTool:
    """Crawl tool for extracting company and contact information from websites."""

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or "./data"
        # Setup logging (child tools inherit shared run log via env)
        self.logger = setup_logging(TOOL_NAME, data_dir=self.data_dir)
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

        from firecrawl import FirecrawlApp

        self.firecrawl_client = FirecrawlApp(api_key=self.firecrawl_key)
        # Global permit manager for concurrency control
        self.permit_manager = PermitManager(
            max_permits=3
        )  # Default, will be overridden
        self.async_semaphore_pool = AsyncSemaphorePool(self.permit_manager)

    def generate_dynamic_intent_prompt(self, icp_config):
        """Generate intent prompt based on ICP configuration"""

        intent_config = icp_config.get("intent_config", {})

        if not intent_config:
            return ""  # No intent analysis if not configured

        purpose = intent_config.get("purpose", "business opportunity")
        target_action = intent_config.get("target_action", "take action")

        # Enhanced prompt with more specific guidance
        prompt = f"""
INTENT ANALYSIS FOR {purpose.upper().replace("_", " ")}:

Your goal is to determine if this company has INTENT to {target_action.replace("_", " ")}.

ANALYSIS METHODOLOGY:
1. SCAN ALL AVAILABLE PAGES for intent signals
2. LOOK FOR SPECIFIC LANGUAGE that indicates intent
3. IDENTIFY TIMELINE indicators (when they might act)
4. DETECT DECISION MAKER statements about future plans
5. ANALYZE OWNERSHIP and business structure changes

INTENT SIGNALS TO LOOK FOR:

HIGH INTENT (Strong evidence they want to {target_action.replace("_", " ")}):
{chr(10).join(f"- {signal}" for signal in intent_config.get("intent_signals", {}).get("high_intent", []))}

MEDIUM INTENT (Some evidence they might be open to {target_action.replace("_", " ")}):
{chr(10).join(f"- {signal}" for signal in intent_config.get("intent_signals", {}).get("medium_intent", []))}

LOW INTENT (Evidence they are NOT interested in {target_action.replace("_", " ")}):
{chr(10).join(f"- {signal}" for signal in intent_config.get("intent_signals", {}).get("low_intent", []))}

LOOK IN THESE SOURCES (PRIORITIZE IN ORDER):
{chr(10).join(f"- {source}" for source in intent_config.get("intent_sources", []))}

SPECIFIC ANALYSIS INSTRUCTIONS:
- READ ABOUT/LEADERSHIP pages for owner statements about future plans
- CHECK CAREERS pages for leadership changes or growth indicators
- LOOK for age-related language (e.g., "founded in 1985", "30+ years")
- IDENTIFY succession planning language (e.g., "next generation", "transition")
- DETECT growth vs. exit language (e.g., "expanding" vs. "considering options")
- ANALYZE ownership structure changes or mentions

SCORING APPROACH:
- Start with base score of {intent_config.get("scoring_rules", {}).get("base_score", 0.5)}
- Add {intent_config.get("scoring_rules", {}).get("high_intent_weight", 0.8)} for each HIGH INTENT signal found
- Add {intent_config.get("scoring_rules", {}).get("medium_intent_weight", 0.4)} for each MEDIUM INTENT signal found
- Subtract {intent_config.get("scoring_rules", {}).get("low_intent_weight", 0.3)} for each LOW INTENT signal found
- Cap final score between 0.0 and 1.0

REQUIRED OUTPUT:
- business_intent_score: Calculated score (0.0-1.0)
- intent_signals: List of specific evidence found (quotes preferred)
- intent_category: "high", "medium", or "low" based on signals
- timeline_indicator: When they might act (e.g., "within 2 years", "retirement age")
- decision_maker_intent: Specific statements from key people

IMPORTANT: If no clear intent signals are found, set business_intent_score to {intent_config.get("scoring_rules", {}).get("base_score", 0.5)} and explain why in intent_signals.
"""
        return prompt

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
                extracted_data = await self._extract_with_firecrawl(
                    normalized_domain, icp_config
                )

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
                industry = (company.get("industry") or "").lower()
                name = (company.get("name") or "").lower()

                # Only reject if we have clear evidence it's not dental-related
                is_dental_related = (
                    "dental" in industry
                    or "dental" in name
                    or "dentist" in name
                    or "orthodont" in name
                    or "oral" in industry
                    or "oral" in name
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

                # Initialize provenance if not exists
                if "provenance" not in record:
                    record["provenance"] = {}
                if "evidence_paths" not in record["provenance"]:
                    record["provenance"]["evidence_paths"] = {}

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

    async def _extract_with_firecrawl(
        self, domain: str, icp_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract data from domain using Firecrawl v2 API with support for specific URLs.

        Args:
            domain: Domain to extract from
            icp_config: ICP configuration for dynamic intent prompts and specific URLs

        Returns:
            Extracted data dictionary
        """
        self.logger.info(f"🔍 Starting Firecrawl v2 extraction for domain: {domain}")
        self.logger.info(
            f"🔑 Firecrawl API key: {self.firecrawl_key[:10]}..."
            if self.firecrawl_key
            else "❌ No API key"
        )
        self.logger.info(f"📋 Using schema: {FIRECRAWL_EXTRACT_SCHEMA}")

        async with self.async_semaphore_pool:
            self.logger.info(f"🔒 Acquired semaphore for domain: {domain}")
            try:
                # Build URLs to extract - combine specific URLs with domain base pages
                urls_to_extract = []

                # Check if we have specific URLs to crawl
                specific_urls = icp_config.get("specific_urls", [])
                if specific_urls:
                    urls_to_extract.extend(specific_urls)
                    self.logger.info(
                        f"🔗 Added {len(specific_urls)} specific URLs to extraction list"
                    )

                # Only add domain base pages if we don't have specific URLs
                # This prevents crawling multiple domains when we only want specific practice listings
                if not specific_urls:
                    domain_base_urls = [
                        f"https://{domain}",
                        f"https://{domain}/about",
                        f"https://{domain}/locations",
                        f"https://{domain}/contact",
                        f"https://{domain}/team",
                        f"https://{domain}/leadership",
                        f"https://{domain}/staff",
                        f"https://{domain}/careers",
                    ]
                    urls_to_extract.extend(domain_base_urls)
                    self.logger.info(
                        "🔗 Added domain base pages for comprehensive data"
                    )
                else:
                    self.logger.info(
                        "🔗 Skipping domain base pages - focusing on specific URLs only"
                    )

                # Remove duplicates while preserving order (specific URLs first, then domain pages)
                seen = set()
                unique_urls = []
                for url in urls_to_extract:
                    if url not in seen:
                        seen.add(url)
                        unique_urls.append(url)

                urls_to_extract = unique_urls

                # Filter out URLs that might not exist (Firecrawl will handle 404s gracefully)
                self.logger.info(f"🌐 Will try URLs: {urls_to_extract}")
                self.logger.info(
                    "📡 Attempting extraction from multiple pages for comprehensive data..."
                )

                try:
                    self.logger.info(
                        f"🤖 Calling Firecrawl v2 API with urls={urls_to_extract} and schema+prompt..."
                    )
                    # Generate dynamic intent prompt based on ICP config
                    dynamic_intent_prompt = self.generate_dynamic_intent_prompt(
                        icp_config
                    )

                    # Combine base prompt with dynamic intent prompt
                    full_prompt = FIRECRAWL_EXTRACT_PROMPT
                    if dynamic_intent_prompt:
                        full_prompt += f"\n\n{dynamic_intent_prompt}"

                    # Enhanced v2 API call with JavaScript handling and dynamic intent
                    # Add parameters for better JavaScript content extraction
                    extract_params = {
                        "urls": urls_to_extract,
                        "prompt": full_prompt,
                        "schema": FIRECRAWL_EXTRACT_SCHEMA,
                    }

                    # Add JavaScript handling parameters if available in Firecrawl v2
                    try:
                        # Try to add JavaScript-specific parameters for better content extraction
                        response = self.firecrawl_client.extract(
                            **extract_params,
                            # Enhanced parameters for JavaScript-rendered content
                            wait_for_timeout=10000,  # Wait 10 seconds for content to load
                            javascript_enabled=True,  # Ensure JavaScript execution
                            scroll_to_bottom=True,  # Scroll through entire page
                        )
                    except TypeError:
                        # Fallback to basic parameters if enhanced ones aren't supported
                        self.logger.info(
                            "Using basic Firecrawl v2 parameters (enhanced JS params not supported)"
                        )
                        response = self.firecrawl_client.extract(**extract_params)

                    if response and hasattr(response, "success") and response.success:
                        self.logger.info(
                            f"✅ Firecrawl v2 extraction successful for {domain}"
                        )
                        return response.data if hasattr(response, "data") else {}
                    else:
                        self.logger.warning(
                            f"Firecrawl v2 extract failed for {domain}: {response}"
                        )
                        raise Exception(
                            "Firecrawl v2 extract returned unsuccessful response"
                        )

                except asyncio.TimeoutError:
                    self.logger.warning(f"Timeout extracting from {domain}")
                    raise Exception("Firecrawl v2 extraction timed out")
                except Exception as exc:
                    self.logger.warning(f"Failed to extract from {domain}: {exc}")
                    raise

            except Exception as exc:
                raise Exception(f"Firecrawl v2 extraction failed: {exc}")

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

        # Populate basic company fields
        company["name"] = company_data.get("name")
        company["description"] = company_data.get("description")
        company["industry"] = company_data.get("industry")
        company["hq_location"] = company_data.get("hq_location")

        # New comprehensive company fields
        company["number_of_locations"] = company_data.get("number_of_locations")

        # Handle new locations_summary structure (cost optimized)
        locations_summary = company_data.get("locations_summary", {})
        if locations_summary:
            company[
                "locations"
            ] = []  # Initialize empty array for backward compatibility

            # Extract primary location if available
            primary_location = locations_summary.get("primary_location", {})
            if primary_location:
                company["locations"].append(
                    {
                        "address": f"{primary_location.get('city', '')}, {primary_location.get('state', '')}, {primary_location.get('country', '')}",
                        "city": primary_location.get("city"),
                        "state": primary_location.get("state"),
                        "country": primary_location.get("country"),
                        "is_primary": True,
                    }
                )

            # Add representative locations as simple strings
            representative_locations = locations_summary.get(
                "representative_locations", []
            )
            for city in representative_locations[:3]:  # Limit to 3 for cost control
                company["locations"].append(city)

        company["founded_year"] = company_data.get("founded_year")
        company["employee_count"] = company_data.get("employee_count")
        company["revenue_range"] = company_data.get("revenue_range")
        company["ownership_type"] = company_data.get("ownership_type")
        company["company_type"] = company_data.get("company_type")
        company["specialties"] = company_data.get("specialties", [])
        company["tech_stack"] = company_data.get("tech_stack", [])

        # Intent analysis fields
        intent_data = company_data.get("intent", {})
        if intent_data:
            # Enhanced intent processing with better defaults
            business_intent_score = intent_data.get("business_intent_score")
            intent_signals = intent_data.get("intent_signals", [])
            intent_category = intent_data.get("intent_category")
            timeline_indicator = intent_data.get("timeline_indicator")
            decision_maker_intent = intent_data.get("decision_maker_intent")

            # Set defaults if missing
            if business_intent_score is None:
                business_intent_score = (
                    icp_config.get("intent_config", {})
                    .get("scoring_rules", {})
                    .get("base_score", 0.5)
                )

            if not intent_signals:
                intent_signals = ["No specific intent signals found during analysis"]

            if not intent_category:
                if business_intent_score >= 0.7:
                    intent_category = "high"
                elif business_intent_score >= 0.5:
                    intent_category = "medium"
                else:
                    intent_category = "low"

            company["intent"] = {
                "business_intent_score": business_intent_score,
                "intent_signals": intent_signals,
                "intent_category": intent_category,
                "timeline_indicator": timeline_indicator or "Timeline unclear",
                "decision_maker_intent": decision_maker_intent
                or "No specific decision maker statements found",
            }
        else:
            # Fallback intent data when Firecrawl doesn't extract intent
            base_score = (
                icp_config.get("intent_config", {})
                .get("scoring_rules", {})
                .get("base_score", 0.5)
            )
            company["intent"] = {
                "business_intent_score": base_score,
                "intent_signals": ["Intent analysis not performed - no data extracted"],
                "intent_category": "unknown",
                "timeline_indicator": "Timeline unclear",
                "decision_maker_intent": "No decision maker intent data available",
            }

        # Contact information fields
        company["emails"] = company_data.get("emails", [])
        company["phone_numbers"] = company_data.get("phone_numbers", [])

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
                "facebook": None,
                "youtube": None,
            }

        # Handle social media links
        socials_data = company_data.get("socials", {})

        # Handle LinkedIn
        linkedin_url = socials_data.get("linkedin")
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

        # Handle other social platforms
        for platform in ["twitter", "facebook", "github", "instagram", "youtube"]:
            if socials_data.get(platform):
                company["socials"][platform] = socials_data[platform]

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

        # Process contacts from team_members (new schema) or employees (legacy)
        team_members = extracted_data.get("team_members", [])
        employees = extracted_data.get("employees", [])  # Legacy support
        all_members = team_members + employees  # Combine both sources
        contacts = []

        for member in all_members:
            # Handle both new and legacy field names
            full_name = member.get("name") or member.get("full_name")
            role = member.get("role")
            department = member.get("department")
            linkedin = member.get("linkedin")
            email = member.get("email")
            phone = member.get("phone")
            decision_maker = member.get("decision_maker", False)
            location = member.get("location")

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
                "department": department,  # Use extracted department
                "seniority": None,
                "role_priority": None,
                "email": email.lower() if email else None,
                "email_confidence": None,
                "email_status": ["unknown"],
                "email_source": ["provider"],
                "phone": phone,  # Use extracted phone
                "linkedin": None,
                "other_links": [],
                "evidence_urls": [],
                "decision_maker": decision_maker,  # New field from expanded schema
                "location": location,  # New field from expanded schema
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

        if company.get("description"):
            score += 0.05
            reasons.append("Company description available")

        if company.get("industry"):
            score += 0.1
            reasons.append("Industry information available")

        if company.get("hq_location"):
            score += 0.1
            reasons.append("Location information available")

        # New comprehensive data fields
        if company.get("number_of_locations"):
            score += 0.1
            reasons.append("Location count available")

        if company.get("locations") and len(company["locations"]) > 0:
            score += 0.1
            reasons.append(
                f"Detailed location data available ({len(company['locations'])} locations)"
            )

        if company.get("founded_year"):
            score += 0.05
            reasons.append("Founded year available")

        if company.get("employee_count"):
            score += 0.05
            reasons.append("Employee count available")

        if company.get("ownership_type"):
            score += 0.05
            reasons.append("Ownership type available")

        if company.get("emails") and len(company["emails"]) > 0:
            score += 0.1
            reasons.append(
                f"Company emails available ({len(company['emails'])} emails)"
            )

        if company.get("phone_numbers") and len(company["phone_numbers"]) > 0:
            score += 0.05
            reasons.append(
                f"Company phone numbers available ({len(company['phone_numbers'])} numbers)"
            )

        # Intent analysis scoring (high priority for business intelligence)
        if company.get("intent", {}).get("business_intent_score"):
            intent_score = company["intent"]["business_intent_score"]
            if intent_score >= 0.7:
                score += 0.3
                reasons.append(f"High business intent score: {intent_score:.2f}")
            elif intent_score >= 0.5:
                score += 0.2
                reasons.append(f"Medium business intent score: {intent_score:.2f}")
            elif intent_score >= 0.3:
                score += 0.1
                reasons.append(f"Low business intent score: {intent_score:.2f}")

            # Add specific intent signals
            intent_signals = company.get("intent", {}).get("intent_signals", [])
            if intent_signals:
                reasons.append(f"Intent signals found: {', '.join(intent_signals[:3])}")

        if company.get("socials"):
            social_count = sum(1 for v in company["socials"].values() if v)
            if social_count > 0:
                score += 0.05
                reasons.append(
                    f"Social media profiles available ({social_count} platforms)"
                )

        if contacts:
            score += 0.2
            reasons.append(f"Found {len(contacts)} contacts")

            # High-quality contacts (with email) are more valuable
            contacts_with_email = sum(1 for c in contacts if c.get("email"))
            if contacts_with_email > 0:
                score += 0.1
                reasons.append(f"{contacts_with_email} contacts have email addresses")

            # Decision makers are especially valuable
            decision_makers = sum(1 for c in contacts if c.get("decision_maker"))
            if decision_makers > 0:
                score += 0.1
                reasons.append(f"{decision_makers} decision makers identified")

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
