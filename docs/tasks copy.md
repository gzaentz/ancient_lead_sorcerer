Lead-Sorcerer Task List

Note: References like (§75-76) refer to line numbers in docs/brd.md. Check the BRD for detailed specifications.

0. Repo & Infra Setup
   0.1 Scaffold poetry-based Python repo, CI & pre-commit hooks (§allowed imports).
   0.2 Add `config/costs.yaml` default pricing (§387-407).
   0.3 Create `data/`, `data/evidence/`, `data/crawl_artifacts/`, `data/exports/` dirs (§29-33, 42-46).
   0.4 Create `data/domain_history.jsonl` for Domain tool's cross-run deduplication (§239).
   0.5 Install & pin third-party libs: `httpx>=0.27`, `openrouter`, `firecrawl`, `proxycurl`, `mailgun`, `snovio`, `phonenumbers`, `portalocker`, `publicsuffix2` (§48-49).
   0.6 Inject env-var loader & .env template for all required keys (§75-76).
   0.7 Add nightly GitHub Actions job placeholder for GC (§34-39).
   0.8 Create `schemas/unified_lead_record.json` with canonical JSON schema (§100-156).
   0.9 Create `icp_config.json` template with all required fields (§387-407).
   0.10 Add `.env` template with all required environment variables (§75-76).
   0.11 Create `config/costs.yaml` with default pricing for all providers (§387-407).

1. Common / Cross-Cutting
   1.1 Data & File Conventions
   1.1.1 Implement eTLD+1 domain normalizer (§25, 273, 327) (unit test converts "sub.foo.co.uk"→"foo.co.uk").
   1.1.2 Implement Unicode NFKD + single-space normalizer for names/roles (§12, 279, 327).
   1.1.3 Implement deterministic `lead_id` & `contact_id` uuid5 helpers (§8-11, 237, 279).
   1.1.4 Implement ISO-8601 UTC `now_z()` helper (§7, 132-147).
   1.1.5 Implement masking helpers: email, phone, LinkedIn (§483-485) (unit tests validate "j*\*\*@d.com", "+XXXXXXXX7890").
   1.1.6 Central `append_status(history, new_status, notes)` utility (§91-99).
   1.1.7 `recompute_total_cost(record)` to sum stage costs (§72, 371-375, 385).
   1.1.8 Single-line JSON logger w/PII masking (§75, 481).
   1.1.9 `resolve_data_dir(payload)` with precedence (§26-27, 437).
   1.1.10 Evidence writer & pointer updater (§29-33, 248, 281).
   1.1.11 Enforce evidence array truncation: company.evidence_urls ≤ 10, contacts[*].evidence_urls ≤ 5 (§155).
   1.1.12 Implement phone number parsing with country code fallback logic (§21-24).
   1.1.13 Implement LinkedIn canonicalization regex for /in/<slug> and /company/<slug> (§22-24).
   1.1.14 Implement `compute_next_revisit` with max-rule: `max(existing_next_revisit_at or 0, now + revisit_after_days)` (§5-6, 240-242, 286-312, 353, 470).
   1.1.15 Implement `append_audit(record, step, notes)` utility for audit trail (§91-99).
   1.1.16 Implement portalocker for write locks on \*.jsonl and artifact files (§40-41).
   1.1.17 Implement lock acquisition only during write phase, not during network I/O (§40-41).
   1.1.18 Implement failure_revisit_days logic: set next_revisit_at = max(existing, now + failure_revisit_days) on failures (§5-6, 240-242, 286-312, 353, 470).
   1.1.19 Implement icp_config.refresh_policy.domain_ttl_days override for domain history TTL (§239).
   1.1.20 Implement icp_config.search.max_pages override for SERP pagination (§239-244).
   1.1.21 Implement icp_config.default_country fallback for phone number parsing (§21-24).
   1.1.22 Implement icp_config.role_priority configuration loading (§309-311).
   1.1.23 Implement `mask_linkedin(path)` helper for deterministic LinkedIn path masking (§483-485).
   1.1.24 Implement `enforce_field_ownership(record_before, record_after, stage)` helper to raise on unauthorized mutations (BRD §157-166).
   1.1.24.1 Implement enforce_field_ownership() helper function
   1.1.24.2 Define field ownership matrix per BRD §157-166
   1.1.24.3 Raise appropriate error when unauthorized mutations detected
   1.1.24.4 Unit test field ownership enforcement for each tool
   1.1.25 Implement schema drift detection: re-hash schema after processing and raise SCHEMA_VALIDATION if changed mid-run (§153-154).
   1.1.25.1 Implement schema checksum computation at startup
   1.1.25.2 Re-hash schema after processing each record
   1.1.25.3 Raise SCHEMA_VALIDATION if schema changed mid-run
   1.1.25.4 Unit test schema drift detection
   1.1.26 Implement `icp_config.queries` template placeholder validation (§226, 229).
   1.1.26.1 Implement template placeholder detection using regex
   1.1.26.2 Validate all placeholders are satisfied before processing
   1.1.26.3 Return SCHEMA_VALIDATION error for unsatisfied placeholders
   1.1.26.4 Unit test placeholder validation scenarios
   1.1.27 Implement `icp_config.required_fields` and `icp_config.optional_fields` validation (§100-156).
   1.1.27.1 Implement required_fields validation for company and contact
   1.1.27.2 Implement optional_fields handling for enrichment
   1.1.27.3 Validate field requirements before status transitions
   1.1.27.4 Unit test field validation logic
   1.1.28 Implement `icp_config.mode` (fast/thorough) handling for Domain tool (§239-244).
   1.1.28.1 Implement fast mode (1 page) vs thorough mode (5 pages)
   1.1.28.2 Respect icp_config.search.max_pages override
   1.1.28.3 Unit test mode-specific behavior
   1.1.29 Implement `icp_config.filtering_strict` handling for Domain tool (§250-253).
   1.1.29.1 Implement filtering_strict logic for scoring
   1.1.29.2 Handle disqualifier detection (geo_mismatch, etc.)
   1.1.29.3 Set icp.pre_flags appropriately
   1.1.29.4 Unit test filtering strict vs lenient modes

   1.2 Concurrency Guard
   1.2.1 Create `AsyncSemaphorePool` enforcing `max_concurrent_requests` across libraries (§40-41, 418) (unit test blocks on >N).
   1.2.2 Implement AsyncSemaphorePool with asyncio.Semaphore for max_concurrent_requests enforcement (§40-41, 418).
   1.2.3 Implement SyncSemaphorePool: a thread-safe wrapper around threading.Semaphore to cap concurrent **blocking** SDK calls; share permits with AsyncSemaphorePool (§40-41, 418).
   1.2.4 Unit test: ensure Portalocker lock is released during simulated 2-second HTTP call and re-acquired only for the write section.

   1.3 Error Handling & Retries
   1.3.1 Define authoritative `ErrorCode` enum (§54-62).
   1.3.1.1 Define complete ErrorCode enum with all BRD-specified codes: - SCHEMA_VALIDATION - HTTP_429 - HTTP_TIMEOUT - SMTP_TIMEOUT - DNS_FAILURE - PROVIDER_ERROR - EXTRACT_ERROR - BUDGET_EXCEEDED - PARSE_ERROR - UNKNOWN
   1.3.2 Back-off wrapper 1→2→4→8→16 s, 45 s cap (§52-57).
   1.3.3 Map HTTP/DNS/SMTP/etc. to errors[] per spec (§54-62).
   1.3.4 Global `wrap_unknown_errors` decorator → code=UNKNOWN (§63-67).
   1.3.5 Provider presence checks: fail fast with PROVIDER_ERROR if required providers missing from config/costs.yaml (§409, §76).
   1.3.5.1 Implement provider presence validation at startup
   1.3.5.2 Check config/costs.yaml for required providers
   1.3.5.3 Fail fast with PROVIDER_ERROR if providers missing
   1.3.5.4 Unit test provider validation scenarios
   1.3.6 Map EXTRACT_ERROR for Firecrawl parse failures (§54-62).
   1.3.6.1 Map Firecrawl parse failures to EXTRACT_ERROR
   1.3.6.2 Handle 2xx responses with parse failures
   1.3.6.3 Unit test EXTRACT_ERROR scenarios
   1.3.7 Implement `wrap_unknown_errors` decorator for uncaught exceptions (§63-67).
   1.3.7.1 Implement wrap_unknown_errors decorator
   1.3.7.2 Catch uncaught exceptions and return UNKNOWN code
   1.3.7.3 Truncate exception messages appropriately
   1.3.7.4 Unit test unknown error handling
   1.3.8 Implement error mapping for HTTP status codes (§54-62):

   - 429 → HTTP_429, retryable=true
   - 5xx → PROVIDER_ERROR, retryable=true, include http_status
   - 4xx (non-429) → PROVIDER_ERROR, retryable=false, include http_status
   - DNS failures → DNS_FAILURE, retryable=false
   - SMTP timeouts → SMTP_TIMEOUT, retryable=true

     1.3.8.1 Map all HTTP status codes to appropriate error codes
     1.3.8.2 Implement retryable logic for each error type
     1.3.8.3 Include http_status in provider errors
     1.3.8.4 Unit test all error mapping scenarios
     1.3.9 Implement exponential backoff with 45s wall-clock cap (§52-57).
     1.3.9.1 Implement 1→2→4→8→16 second backoff ladder
     1.3.9.2 Enforce 45-second wall-clock cap per item
     1.3.9.3 Unit test backoff timing and caps
     1.3.10 Implement connect/read timeouts (3s/10s) per attempt (§52-57).
     1.3.10.1 Implement 3-second connect timeout per attempt
     1.3.10.2 Implement 10-second read timeout per attempt
     1.3.10.3 Unit test timeout behavior
     1.3.11 Add metrics.health.unknown_error_count to orchestrator (§63-67).
     1.3.11.1 Add metrics.health.unknown_error_count to orchestrator
     1.3.11.2 Track UNKNOWN errors across all tools
     1.3.11.3 Include in summary metrics
     1.3.11.4 Unit test unknown error counting
     1.3.12 Implement provider presence validation at startup (§409, §76).
     1.3.12.1 Validate provider configuration at startup
     1.3.12.2 Check config/costs.yaml for required providers
     1.3.12.3 Fail fast with PROVIDER_ERROR if missing
     1.3.12.4 Unit test provider validation
     1.3.13 Implement audit trail logging for each tool step (§91-99).
     1.3.13.1 Implement append_audit() utility function
     1.3.13.2 Log audit trail for each tool step
     1.3.13.3 Include step, notes, and timestamp
     1.3.13.4 Unit test audit trail logging
     1.3.14 Implement template placeholder validation for all tools (§226, §229).
     1.3.14.1 Implement template placeholder validation for all tools
     1.3.14.2 Use Python string.Template.substitute()
     1.3.14.3 Return SCHEMA_VALIDATION for unsatisfied placeholders
     1.3.14.4 Unit test placeholder validation
     1.3.15 Implement error code mapping for all HTTP status codes (§54-62).
     1.3.15.1 Implement error code mapping for all HTTP status codes
     1.3.15.2 Map DNS failures to DNS_FAILURE
     1.3.15.3 Map SMTP timeouts to SMTP_TIMEOUT
     1.3.15.4 Unit test all error mapping scenarios
     1.3.16 Add PARSE_ERROR to ErrorCode enum for phone parsing failures (§21-24).
     1.3.16.1 Add PARSE_ERROR to ErrorCode enum
     1.3.16.2 Emit PARSE_ERROR for phone parsing failures
     1.3.16.3 Emit PARSE_ERROR for other parsing failures
     1.3.16.4 Unit test PARSE_ERROR scenarios
     1.3.17 Add EXTRACT_ERROR to ErrorCode enum for Firecrawl parse failures (§54-62).
     1.3.17.1 Add EXTRACT_ERROR to ErrorCode enum
     1.3.17.2 Map Firecrawl parse failures to EXTRACT_ERROR
     1.3.17.3 Handle 2xx responses with parse failures
     1.3.17.4 Unit test EXTRACT_ERROR scenarios
     1.3.18 Implement `icp_config.refresh_policy.failure_revisit_days` logic for all tools (§5-6, 240-242, 286-312, 353, 470).
     1.3.18.1 Implement failure_revisit_days logic for all tools
     1.3.18.2 Set next_revisit_at = max(existing, now + failure_revisit_days)
     1.3.18.3 Apply to crawl_failed, enrich_failed, and other failures
     1.3.18.4 Unit test failure revisit logic
     1.3.19 Implement `icp_config.refresh_policy.domain_ttl_days` override for domain history TTL (§239).
     1.3.19.1 Implement icp_config.refresh_policy.domain_ttl_days override
     1.3.19.2 Override default 180-day TTL when specified
     1.3.19.3 Apply to domain history cleanup
     1.3.19.4 Unit test TTL override logic
     1.3.20 Implement `icp_config.search.max_pages` override for SERP pagination (§239-244).
     1.3.20.1 Implement icp_config.search.max_pages override
     1.3.20.2 Override default pagination limits
     1.3.20.3 Apply to SERP pagination logic
     1.3.20.4 Unit test max pages override
     1.3.21 Implement `icp_config.default_country` fallback for phone parsing (§21-24).
     1.3.21.1 Implement icp_config.default_country fallback
     1.3.21.2 Use for phone number parsing when country code missing
     1.3.21.3 Apply fallback logic in all tools
     1.3.21.4 Unit test country fallback logic
     1.3.22 Implement `icp_config.role_priority` configuration loading (§309-311).
     1.3.22.1 Implement icp_config.role_priority configuration loading
     1.3.22.2 Load role priority mapping from config
     1.3.22.3 Apply to best contact selection
     1.3.22.4 Unit test role priority logic
     1.3.23 Add HTTP_TIMEOUT to ErrorCode enum for per-attempt timeouts (§52-57).
     1.3.23.1 Add HTTP_TIMEOUT to ErrorCode enum
     1.3.23.2 Use for per-attempt timeouts
     1.3.23.3 Map timeout failures appropriately
     1.3.23.4 Unit test HTTP_TIMEOUT scenarios
     1.3.24 Add SMTP_TIMEOUT to ErrorCode enum for SMTP validation timeouts (§54-62).
     1.3.24.1 Add SMTP_TIMEOUT to ErrorCode enum
     1.3.24.2 Use for SMTP validation timeouts
     1.3.24.3 Map SMTP failures appropriately
     1.3.24.4 Unit test SMTP_TIMEOUT scenarios
     1.3.25 Implement error mapping for HTTP_TIMEOUT and SMTP_TIMEOUT (§54-62).
     1.3.25.1 Implement error mapping for HTTP_TIMEOUT
     1.3.25.2 Implement error mapping for SMTP_TIMEOUT
     1.3.25.3 Set retryable flags appropriately
     1.3.25.4 Unit test timeout error mapping

     1.4 Schema Validation & Versioning
     1.4.1 Load canonical schema once; compute sha256 checksum (§100-156, 153-154).
     1.4.1.1 Load unified_lead_record.json schema at startup
     1.4.1.2 Compute sha256 checksum of schema file
     1.4.1.3 Cache schema and checksum for validation
     1.4.1.4 Unit test schema loading and checksum computation
     1.4.2 `validate_envelope(io_data)` for all tools (§69-74, 443-447).
     1.4.2.1 Implement validate_envelope() function for all tools
     1.4.2.2 Validate input/output against canonical schema
     1.4.2.3 Return SCHEMA_VALIDATION error on mismatch
     1.4.2.4 Unit test envelope validation
     1.4.3 Inject `INTERNAL_VERSION` per tool & stamp provenance.tool_versions.{tool}.{version|schema_version} (§48, 262, 306, 349, 476).
     1.4.3.1 Define INTERNAL_VERSION constant per tool
     1.4.3.2 Set provenance.tool_versions.{tool}.version on every run
     1.4.3.3 Set provenance.tool_versions.{tool}.schema_version on every run
     1.4.3.4 Unit test version stamping
     1.4.4 Implement schema checksum computation: sha256 of unified_lead_record.json (§153-154).
     1.4.4.1 Implement sha256 checksum computation
     1.4.4.2 Compute checksum at startup
     1.4.4.3 Store checksum in tool_versions.schema_version
     1.4.4.4 Unit test checksum computation
     1.4.5 Implement string length validation (≤2KB per string) (§155).
     1.4.5.1 Implement string length validation (≤2KB per string)
     1.4.5.2 Validate all string fields against limit
     1.4.5.3 Truncate strings that exceed limit
     1.4.5.4 Unit test string length validation
     1.4.6 Implement array truncation validation: company.evidence_urls ≤ 10, contacts[*].evidence_urls ≤ 5 (§155).
     1.4.6.1 Implement array truncation validation
     1.4.6.2 Enforce company.evidence_urls ≤ 10
     1.4.6.3 Enforce contacts[*].evidence_urls ≤ 5
     1.4.6.4 Unit test array truncation
     1.4.7 Implement template placeholder detection and validation (§226, §229).
     1.4.7.1 Implement template placeholder detection using regex
     1.4.7.2 Validate all placeholders are satisfied
     1.4.7.3 Return SCHEMA_VALIDATION for unsatisfied placeholders
     1.4.7.4 Unit test template validation
     1.4.8 Implement provider configuration validation (§409, §76).
     1.4.8.1 Validate provider configuration at startup
     1.4.8.2 Check config/costs.yaml for required providers
     1.4.8.3 Fail fast with PROVIDER_ERROR if missing
     1.4.8.4 Unit test provider validation
     1.4.9 Implement template placeholder validation using Python string.Template.substitute() (§226, 229).
     1.4.9.1 Implement Python string.Template.substitute() validation
     1.4.9.2 Validate all template placeholders
     1.4.9.3 Return SCHEMA_VALIDATION for unsatisfied placeholders
     1.4.9.4 Unit test template substitution validation
     1.4.10 Implement SCHEMA_VALIDATION error when placeholders are unsatisfied (§226, 229).
     1.4.10.1 Implement SCHEMA_VALIDATION error for unsatisfied placeholders
     1.4.10.2 Detect missing template variables
     1.4.10.3 Return appropriate error with context
     1.4.10.4 Unit test SCHEMA_VALIDATION scenarios
     1.4.11 Implement schema checksum computation: sha256 of unified_lead_record.json at startup (§153-154).
     1.4.11.1 Implement schema checksum computation at startup
     1.4.11.2 Compute sha256 of schema file
     1.4.11.3 Store checksum for validation
     1.4.11.4 Unit test startup checksum computation
     1.4.12 Implement provider configuration validation against config/costs.yaml (§409, 76).
     1.4.12.1 Validate provider configuration against config/costs.yaml
     1.4.12.2 Check for required provider entries
     1.4.12.3 Validate pricing structure
     1.4.12.4 Unit test provider config validation
     1.4.13 Implement audit trail logging with append_audit() utility (§91-99).
     1.4.13.1 Implement append_audit() utility function
     1.4.13.2 Log audit trail for each tool step
     1.4.13.3 Include step, notes, and timestamp
     1.4.13.4 Unit test audit trail logging
     1.4.14 Implement `icp_config.refresh_policy.domain_ttl_days` override validation (§239).
     1.4.14.1 Implement domain_ttl_days override validation
     1.4.14.2 Validate override value is positive integer
     1.4.14.3 Apply override to domain history TTL
     1.4.14.4 Unit test TTL override validation
     1.4.15 Implement `icp_config.search.max_pages` override validation (§239-244).
     1.4.15.1 Implement max_pages override validation
     1.4.15.2 Validate override value is positive integer
     1.4.15.3 Apply override to SERP pagination
     1.4.15.4 Unit test max_pages override validation
     1.4.16 Implement `icp_config.default_country` fallback validation (§21-24).
     1.4.16.1 Implement default_country fallback validation
     1.4.16.2 Validate country code format (ISO-3166)
     1.4.16.3 Apply fallback for phone parsing
     1.4.16.4 Unit test country fallback validation
     1.4.17 Implement `icp_config.role_priority` configuration validation (§309-311).
     1.4.17.1 Implement role_priority configuration validation
     1.4.17.2 Validate role priority mapping structure
     1.4.17.3 Apply to best contact selection
     1.4.17.4 Unit test role priority validation
     1.4.18 Implement LinkedIn path masking validation (§483-485).
     1.4.18.1 Implement LinkedIn path masking validation
     1.4.18.2 Validate mask_linkedin() helper usage
     1.4.18.3 Ensure PII masking in logs/errors
     1.4.18.4 Unit test LinkedIn masking validation
     1.4.19 Implement schema checksum validation at startup (§153-154).
     1.4.19.1 Implement schema checksum validation at startup
     1.4.19.2 Validate schema file integrity
     1.4.19.3 Fail fast if schema is corrupted
     1.4.19.4 Unit test schema integrity validation
     1.4.20 Implement schema checksum drift detection during processing (§153-154).
     1.4.20.1 Implement schema checksum drift detection
     1.4.20.2 Re-hash schema after processing each record
     1.4.20.3 Raise SCHEMA_VALIDATION if checksum changed
     1.4.20.4 Unit test schema drift detection

     1.5 Refresh / Revisit Policy
     1.5.1 `compute_next_revisit(existing, delta_days)` implementing max-rule (§5-6, 240-242, 286-312, 353, 470).
     1.5.1.1 Implement compute_next_revisit() function with max-rule
     1.5.1.2 Apply max(existing_next_revisit_at or 0, now + revisit_after_days)
     1.5.1.3 Handle failure_revisit_days logic for failures
     1.5.1.4 Unit test max-rule implementation
     1.5.1.5 Unit test failure revisit logic
     1.5.1.6 Unit test revisit policy across all tools

     1.6 Artifact Retention & GC
     1.6.1 GC script: keep 3 versions, delete >365 d, skip referenced (§34-39).
     1.6.1.1 Implement nightly garbage collection script
     1.6.1.2 Keep latest 3 versions per domain
     1.6.1.3 Delete files older than 365 days
     1.6.1.4 Skip deletion if file referenced in provenance.evidence_paths.\*
     1.6.1.5 Unit test garbage collection logic
     1.6.2 Sink rotation: >10 MB or >30 d for append-only logs (§42-46).
     1.6.2.1 Implement sink rotation logic
     1.6.2.2 Rotate when >10 MB or >30 days
     1.6.2.3 Apply to domain_all.jsonl and domain_pass.jsonl
     1.6.2.4 Use copy-on-write compaction for rotated sinks
     1.6.2.5 Ensure atomic pointer swap during compaction
     1.6.2.6 Unit test sink rotation and compaction

     1.7 Metrics
     1.7.1 Metrics struct builder per tool (§362-376).
     1.7.1.1 Implement metrics struct builder for each tool
     1.7.1.2 Build metrics with count_in, count_out, duration_ms
     1.7.1.3 Include cache_hit_rate and pass_rate where applicable
     1.7.1.4 Include cost_usd breakdown per tool
     1.7.1.5 Unit test metrics building
     1.7.2 Implement `load_costs_config(path="config/costs.yaml")` helper to cache YAML once and return per-provider unit prices (§387-407).
     1.7.2.1 Implement load_costs_config() helper function
     1.7.2.2 Load and cache config/costs.yaml
     1.7.2.3 Return per-provider unit prices
     1.7.2.4 Cache configuration for performance
     1.7.2.5 Unit test cost configuration loading
     1.7.3 Implement high-resolution timer for metrics.duration_ms in every tool run() entry (§362-370).
     1.7.3.1 Implement high-resolution timer for tool runs
     1.7.3.2 Start timer at run() entry
     1.7.3.3 Stop timer before return
     1.7.3.4 Set metrics.duration_ms in all tools
     1.7.3.5 Unit test timing accuracy

     1.8 Secret Redaction
     1.8.1 Extend JSON logger to strip/replace any value whose key contains "key", "token", "secret".
     1.8.1.1 Extend JSON logger to detect secret keys
     1.8.1.2 Strip/replace values with keys containing "key", "token", "secret"
     1.8.1.3 Ensure no secrets are logged
     1.8.1.4 Unit test secret redaction
     1.8.2 Extend JSON logger to redact large provider payloads (>2 KB or containing "headers/body") before serialization.
     1.8.2.1 Extend JSON logger to detect large provider payloads
     1.8.2.2 Redact payloads >2 KB or containing "headers/body"
     1.8.2.3 Ensure sensitive data is not logged
     1.8.2.4 Unit test payload redaction

     1.9 Error Object Helper
     1.9.1 `build_error(code, exc, tool, lead_id=None, context=None)` with PII & secret masking, message truncation.
     1.9.1.1 Implement build_error() helper function
     1.9.1.2 Apply PII masking to error messages
     1.9.1.3 Apply secret masking to error context
     1.9.1.4 Truncate error messages appropriately
     1.9.1.5 Include tool, lead_id, and context in errors
     1.9.1.6 Unit test error building and masking

     1.10 Float Rounding
     1.10.1 Implement `round4(f)` utility for cost_usd & metrics before emit (§386).
     1.10.1.1 Implement round4() utility function
     1.10.1.2 Round all cost_usd values to 4 decimal places
     1.10.1.3 Round all metrics values to 4 decimal places
     1.10.1.4 Apply before emitting records and metrics
     1.10.1.5 Unit test rounding accuracy

2. Tool: Domain (`tools/domain.py`)
   2.1 CLI: read stdin JSON, write stdout JSON, log to stderr (§71).
   2.2 Input validation vs schema; on fail append SCHEMA_VALIDATION error (§443-447).
   2.3 Implement search cache w/TTL (`domain_serp_ttl_hours`) (§243-245).
   2.4 Call Google Programmable Search (GSE) paginated, honour `max_pages` & mode fast/thorough (§239-244, 271).
   2.5 Respect `AsyncSemaphorePool` for outbound GSE (§40-41).
   2.6 Generate `lead_id` before scoring (§236-237).
   2.7 LLM scoring: gpt-4o-mini via OpenRouter, temp 0, prompt_fp sha256 (§237-238).
   2.8 Filter ≥threshold, set `icp.pre_pass`, `pre_reason`, `pre_score` (§250-253, 260).
   2.9 Persist SERP snapshot to `data/evidence/domain/{eTLD+1}.json` & pointer (§248-249).
   2.10 Maintain domain-history JSONL w/180 d TTL dedupe (§239).
   2.11 Compute `provenance.scored_at`, `next_revisit_at`, `cache.domain_cache_hit` (§242, 247, 268).
   2.12 Append status_history "scored" (§242).
   2.13 Cost accounting: GSE unit price, update `cost.domain_usd` & recompute total (§371-375).
   2.14 Metrics: count_in/out, pass_rate, cache_hit_rate (§362-380).
   2.15 Error handling per common utilities (§256-257).
   2.16 Unit test idempotence & cache reuse (§460-462).
   2.17 Validate template placeholders: detect unsatisfied ${placeholders} and emit SCHEMA_VALIDATION (§226, §229).
   2.18 Handle GSE API authentication and GSE_CX configuration (§239-244).
   2.19 Implement domain history TTL cleanup (180 days) (§239).
   2.20 Handle progressive SERP pagination for subsequent runs (§239-244).
   2.21 Handle fallback to gpt-3.5-turbo when gpt-4o-mini fails (§237-238).
   2.22 Set `icp.pre_flags` when scoring prompt detects disqualifiers (e.g., geo_mismatch) (§250-253).
   2.23 Implement icp_config.refresh_policy.domain_ttl_days override (§239).
   2.24 Implement template placeholder validation for queries (§226, §229).
   2.25 Implement provider presence checks for GSE and OpenRouter (§409, §76).
   2.26 Implement audit trail logging for scoring steps (§91-99).
   2.27 Implement failure_revisit_days logic for failed scoring attempts (§5-6, 240-242, 286-312, 353, 470).
   2.28 Graceful zero-SERP handling (§256): emit NO_RESULTS (non-retryable), return empty lead_records.
   2.29 Implement `icp_config.default_country` fallback for phone parsing (§21-24).
   2.30 Implement `icp_config.role_priority` configuration loading (§309-311).
   2.31 Include OpenRouter token cost in cost.domain_usd (add to 2.13 which currently lists only GSE). Unit price is in costs.yaml (§387-407).
   2.32 Respect AsyncSemaphorePool for OpenRouter LLM requests as well as GSE (§40-41).
   2.33 Add unit test that verifies Domain respects max_concurrent_requests across both GSE and LLM calls.
   2.34 Use exact model name "gpt-4o-mini-1.5" via OpenRouter with fallback to "gpt-3.5-turbo" (§237-238).
   2.35 Implement `icp_config.mode` (fast/thorough) handling for SERP pagination (§239-244).
   2.36 Implement `icp_config.filtering_strict` handling for scoring logic (§250-253).
   2.37 Implement `icp_config.queries` template placeholder validation (§226, 229).
   2.38 Implement `icp_config.required_fields` and `icp_config.optional_fields` validation (§100-156).

3. Tool: Crawl (`tools/crawl.py`)
   3.1 CLI + envelope validator (§71).
   3.2 Check artifact cache TTL (`crawl_ttl_days`), content_hash dedupe (§283-285).
   3.3 Call Firecrawl extract (https→http fallback) (§290-297).
   3.4 Generate contact IDs deterministically (§279-280).
   3.5 Normalize fields (domain, names, email, phone) (§287-288).
   3.6 Populate company & contacts, dedupe contacts (§273-309).
   3.7 Second ICP validation → `icp.crawl_score`, `crawl_reason` (§298).
   3.8 Set status crawled/enrich_ready/crawl_failed & append status_history (§280-289, 312).
   3.9 Persist artifacts to `data/crawl_artifacts/{eTLD+1}.json` & pointer (§281-317).
   3.10 Compute `provenance.crawled_at`, `next_revisit_at` max-rule (§286-313).
   3.11 Fill `company.ids` from onsite links (§307).
   3.12 Update `contacts[*].seniority`, `role_priority` mapping (§309-311).
   3.13 Cost accounting: Firecrawl pricing → `cost.crawl_usd` (§371-375).
   3.14 Metrics: cache_hit_rate, pass_rate (§362-380).
   3.15 Error handling & retries (§301-303).
   3.16 Idempotence, TTL, state-machine tests (§449-460).
   3.17 Respect `AsyncSemaphorePool` for outbound Firecrawl calls (§40-41).
   3.18 Validate template placeholders in queries if present (§226, §229).
   3.19 Implement content_hash deduplication logic (§283-285).
   3.20 Handle LinkedIn company page vs contact routing (§22-24).
   3.21 Implement seniority ranking mapping: `{"c-level":1, "vp":2, "head":3, "director":3, "manager":4, "lead":5, "ic":6, "other|unknown":99}` (§309-311).
   3.22 Set `provenance.evidence_paths.crawl` to `"data/crawl_artifacts/{eTLD+1}.json"` (§281-317).
   3.23 Implement template placeholder validation for queries if present (§226, §229).
   3.24 Implement provider presence checks for Firecrawl (§409, §76).
   3.25 Implement audit trail logging for extraction steps (§91-99).
   3.26 Implement failure_revisit_days logic for crawl failures (§5-6, 240-242, 286-312, 353, 470).
   3.27 Implement icp_config.role_priority configuration loading for seniority ranking (§309-311).
   3.28 Populate company.size_hint when Firecrawl returns employee count or size brackets.
   3.29 Implement `icp_config.refresh_policy.crawl_ttl_days` override validation (§283-285).
   3.30 Implement `icp_config.default_country` fallback for phone parsing (§21-24).
   3.31 Implement LinkedIn path masking for all LinkedIn URLs in logs and errors (§483-485).
   3.32 Implement `icp_config.required_fields.company` validation for status transitions (§298).
   3.33 Implement `icp_config.required_fields.contact` validation for contact extraction (§273-309).

4. Tool: Enrich (`tools/enrich.py`)
   4.1 CLI + schema validation (§71).
   4.2 Resolve caps & track cumulative spend (§325-341).
   4.3 Deterministic best-contact selection tuple (§333-336).
   4.4 Enrich company via Proxycurl first (§338-340).
   4.5 Validate/append email via Mailgun; enrich via Snov.io within caps (§321-360).
   4.6 Normalize all fields (domain, email, phone, names) (§327-328).
   4.7 Set `best_contact_id`, `contacts[*].email_status`, `email_confidence` (§349-352).
   4.8 Backfill `company.ids` if missing (§352).
   4.9 Enforce caps: skip lead & log BUDGET_EXCEEDED when over limit (§328-341).
   4.10 Status enriched/enrich_partial & append status_history (§330-331).
   4.11 Persist evidence to `data/evidence/enrich/{eTLD+1}.json` & pointer (§355-356).
   4.12 Compute `provenance.enriched_at`, maybe `next_revisit_at` (§353-355).
   4.13 Cost accounting: Proxycurl/Mailgun/Snov.io unit pricing → `cost.enrich_usd` (§371-375).
   4.14 Metrics: pass_rate, cost_usd total (§362-380).
   4.15 Error handling & UNKNOWN wrapper (§345-347).
   4.16 Tests for cap logic, best-contact tie-break, state machine (§341-460).
   4.17 Respect `AsyncSemaphorePool` for outbound API calls (§40-41).
   4.18 Implement email status ranking for best-contact selection (§333-336).
   4.19 Handle provider failover when primary enrichment fails (§321-360).
   4.20 Implement cost cap enforcement per individual lead (§328-341).
   4.21 Implement email status ranking: `valid=0, risky=1, catch_all=2, unknown=3, invalid=4` (§333-336).
   4.22 Set `provenance.evidence_paths.enrich` to `"data/evidence/enrich/{eTLD+1}.json"` (§355-356).
   4.23 Handle best_contact_id recomputation when previously selected contact no longer exists (§333-336).
   4.24 Implement template placeholder validation for queries if present (§226, §229).
   4.25 Implement provider presence checks for Proxycurl, Mailgun, and Snov.io (§409, §76).
   4.26 Implement audit trail logging for enrichment steps (§91-99).
   4.27 Implement failure_revisit_days logic for enrichment failures (§5-6, 240-242, 286-312, 353, 470).
   4.28 Implement icp_config.role_priority configuration loading for best contact selection (§333-336).
   4.29 Ensure paid enrichment calls (Proxycurl, Mailgun, Snov.io) also share the global AsyncSemaphorePool semaphore (§40-41).
   4.30 Populate contacts[*].email_source when an email is added/verified (§349-352).
   4.31 Append new links to contacts[*].other_links; maintain append-only semantics (§349-352).
   4.32 Extend best-contact sort tuple to (role_priority, seniority_rank, email_status_rank, has_linkedin, contact_id) per BRD §333-336.
   4.33 Implement LinkedIn path masking for all LinkedIn URLs in logs and errors (§483-485).
   4.34 Implement `icp_config.required_fields.contact` validation for enrichment completion (§349-352).
   4.35 Implement `icp_config.optional_fields` handling for optional enrichment (§321-360).

5. Orchestrator (`orchestrator.py`)
   5.1 Load `icp_config.json`, resolve data_dir, secrets (§418-419).
   5.2 Default batch_size 50; CLI & JSON I/O.
   5.3 Call Domain → filter → Crawl → Enrich per gating flags (§416-420).
   5.4 Enforce `AsyncSemaphorePool` global across tool runs (§418).
   5.5 Persist `data/domain_all.jsonl` (pass+reject) and `data/domain_pass.jsonl` (§421-425).
   5.6 Rotate sinks >10 MB or >30 d (§42-43).
   5.7 Export leads JSONL/CSV when enabled (§426-435).
   5.8 CSV flattening & column order rules (§430-435).
   5.9 Summarize & log metrics (§436-437).
   5.10 Never mutate beyond persistence/gating (§439).
   5.11 Nightly GC invocation hook (§34-39).
   5.12 Implement testing flags (process_rejected, process_low_crawl) (§416-420).
   5.13 Handle data directory precedence resolution (§26-27, 437).
   5.14 Implement export directory creation with UTC timestamps (§426-435).
   5.15 Handle CSV flattening with dot-notation for objects and array joining with "|" (§430-435).
   5.16 Export only best contact using columns: `contact.full_name`, `contact.role`, `contact.email`, `contact.phone`, `contact.linkedin` (§430-435).
   5.17 Implement metrics.health.unknown_error_count tracking (§63-67).
   5.18 Implement provider configuration validation at startup (§409, §76).
   5.19 Implement audit trail logging for orchestration steps (§91-99).
   5.20 Copy-on-write compaction for rotated sinks (§46).
   5.21 Implement icp_config.role_priority configuration loading (§309-311).
   5.22 Implement icp_config.default_country fallback for phone parsing (§21-24).
   5.23 Aggregate metrics.health.unknown_error_count over run and include in summary (§63-67).
   5.24 Implement `icp_config.refresh_policy.failure_revisit_days` logic for all tools (§5-6, 240-242, 286-312, 353, 470).
   5.25 Implement `icp_config.refresh_policy.domain_ttl_days` override validation (§239).
   5.26 Implement `icp_config.search.max_pages` override validation (§239-244).
   5.27 Expose metrics.duration_ms for the whole pipeline run (start/stop timer around Domain→Crawl→Enrich) (§362-370).
   5.28 On copy-on-write sink compaction, ensure atomic pointer swap (§46) – add explicit unit test.
   5.29 Implement SyncSemaphorePool for blocking SDK calls in tools (§40-41, 418).

6. Testing & CI
   6.1 Unit Tests per Tool
   6.1.1 Validate required/invalid inputs (§443-447).
   6.1.2 Caching TTL & cache_hit_rate accuracy (§244-246, 284-286).
   6.1.3 Concurrency guard blocks excess tasks (§41).
   6.1.4 Deterministic IDs & best contact (§457).
   6.1.5 Provider missing checks: verify PROVIDER_ERROR on startup when required providers absent (§409, §76).
   6.1.6 Evidence array truncation: validate company.evidence_urls ≤ 10, contacts[*].evidence_urls ≤ 5 (§155).
   6.1.7 Template placeholder validation: test SCHEMA_VALIDATION on unsatisfied ${placeholders} (§226, §229).
   6.1.8 Phone parse failure: verify PARSE_ERROR emission on unparseable numbers (§21-24).
   6.1.9 Log PII masking: validate single-line JSON logs with masked PII (§75, §481-485).
   6.1.10 Test LinkedIn canonicalization regex patterns (§22-24).
   6.1.11 Test country code fallback for phone parsing (§21-24).
   6.1.12 Test progressive SERP pagination logic (§239-244).
   6.1.13 Test best_contact_id recomputation when contact no longer exists (§333-336).
   6.1.14 Test CSV export flattening and column ordering (§430-435).
   6.1.15 Test export directory creation with UTC timestamps (§426-435).
   6.1.16 Test portalocker write lock behavior (§40-41).
   6.1.17 Test exponential backoff with 45s wall-clock cap (§52-57).
   6.1.18 Test error mapping for all HTTP status codes (§54-62).
   6.1.19 Test schema checksum validation (§153-154).
   6.1.20 Test string length and array truncation limits (§155).
   6.1.21 Test provider failover logic (§321-360).
   6.1.22 Test cost cap enforcement per individual lead (§328-341).
   6.1.23 Test testing flags (process_rejected, process_low_crawl) (§416-420).
   6.1.24 Test data directory precedence resolution (§26-27, 437).
   6.1.25 Test template placeholder validation for all tools (§226, §229).
   6.1.26 Test provider presence validation at startup (§409, §76).
   6.1.27 Test audit trail logging for all tool steps (§91-99).
   6.1.28 Test failure_revisit_days logic for all tools (§5-6, 240-242, 286-312, 353, 470).
   6.1.29 Test icp_config.refresh_policy.domain_ttl_days override (§239).
   6.1.30 Test icp_config.search.max_pages override (§239-244).
   6.1.31 Test icp_config.default_country fallback for phone parsing (§21-24).
   6.1.32 Test icp_config.role_priority configuration loading (§309-311).
   6.1.33 Test error code mapping for all specified error types (§54-62).
   6.1.34 Test content hash deduplication logic (§283-285).
   6.1.35 Test LinkedIn routing and canonicalization (§22-24).
   6.1.36 Test seniority ranking mapping (§309-311).
   6.1.37 Test that OpenRouter costs are included in record.cost.domain_usd and tool-run metrics.cost_usd.domain (§387-407).
   6.1.38 Test metrics.duration_ms population in every tool envelope (§362-370).
   6.1.39 Test atomic pointer swap during copy-on-write sink compaction (§46).
   6.1.40 Unit-test SyncSemaphorePool blocks >N parallel blocking calls (§40-41).
   6.1.41 Unit-test that email_source affects best-contact tie-break (§349-352).
   6.1.42 Unit-test mask_linkedin() redacts slugs in logs/errors (§483-485).
   6.1.43 Field-ownership enforcement test (uses helper from 1.1.24).
   6.1.44 Status_history completeness test: feed a record that undergoes Domain → Crawl → Enrich and assert three chronological history entries.
   6.1.45 Portalocker write-phase timing test (ties to 1.2.4).
   6.1.46 Provider-payload redaction test: logger output must not contain raw "headers" or "body" keys when log_redaction filter is on.
   6.1.47 Test `icp_config.mode` (fast/thorough) handling in Domain tool (§239-244).
   6.1.48 Test `icp_config.filtering_strict` handling in Domain tool (§250-253).
   6.1.49 Test `icp_config.queries` template placeholder validation (§226, 229).
   6.1.50 Test `icp_config.required_fields` and `icp_config.optional_fields` validation (§100-156).
   6.1.51 Test HTTP_TIMEOUT and SMTP_TIMEOUT error mapping (§54-62).
   6.1.52 Test schema checksum validation and drift detection (§153-154).

   6.2 Contract Tests
   6.2.1 Envelope shape & schema validation (§69-74, 443-447).
   6.2.2 State-machine transitions allowed only (§458-460).
   6.2.3 Error contract & PII masking (§454-456, 481-485).
   6.2.4 Version stamping changes on logic edits (§450-476).
   6.2.5 Revisit max-rule enforcement (§461).

   6.3 Fixtures & Mocks
   6.3.1 `responses` / `httpx_mock` stubs for GSE, Firecrawl, Proxycurl, Mailgun, Snov.io (§442-445).

   6.4 CI Pipeline
   6.4.1 GitHub Actions: lint, type-check, tests, coverage ≥90%.

   6.5 Integration Tests
   6.5.1 End-to-end pipeline test: Domain→Crawl→Enrich happy-path.
   6.5.2 Pipeline error-path test: inject Domain 0-SERP, verify partials & accumulated errors.

7. Documentation / README
   7.1 Add "Schema Validation & Contract" section (§464-468).
   7.2 "Status History" rules (§465-469).
   7.3 "Caching & Revisit Policy" (§470-472).
   7.4 "Versioning Policy" (§472-476).
   7.5 "Rejected Lead Handling" (§477).
   7.6 "Error Handling & PII Masking" (§478-485).
   7.7 "Metrics Semantics" (§486-488).
   7.8 "Exports" guide (§489-491).
   7.9 "State Machine (Authoritative)" section with allowed transitions and gating rules (§91-99).
   7.10 "Field Ownership" section documenting which tools can update which fields (§91-99).
   7.11 "Error Mapping & HTTP Status Codes" section (§54-62).
   7.12 "Exponential Backoff & Timeouts" section (§52-57).
   7.13 "Portalocker & File Locking" section (§40-41).
   7.14 "Schema Checksums & Validation" section (§153-154).
   7.15 "Testing Flags & Configuration" section (§416-420).
   7.16 "Template Placeholder Validation" section (§226, §229).
   7.17 "Provider Configuration & Validation" section (§409, §76).
   7.18 "Audit Trail & Logging" section (§91-99).
   7.19 "Progressive SERP Pagination" section (§239-244).
   7.20 "Content Hash Deduplication" section (§283-285).
   7.21 "LinkedIn Routing & Canonicalization" section (§22-24).
   7.22 "Seniority Ranking & Role Priority" section (§309-311).
   7.23 "Provider Failover & Best Contact Selection" section (§321-360, §333-336).
   7.24 "Cost Model & Unit Pricing" subsection: document load_costs_config(), how each stage converts provider usage to USD, and where costs.yaml lives (§387-407).
   7.25 "LinkedIn Path Masking" section documenting mask_linkedin() helper and usage (§483-485).
   7.26 "SyncSemaphorePool & Blocking SDK Concurrency" section (§40-41, 418).
   7.27 "Field Ownership Enforcement" subsection describing helper, errors raised, and example.

8. Compliance & GC
   8.1 Implement nightly GC job as separate script (§34-39).
   8.2 Verify no cross-imports between tools (§47).
   8.3 Static analysis to restrict imports to approved list (§48).
   8.4 Ensure raw PII never logged; audit masking functions (§481-485).
   8.5 Implement audit trail logging for each tool step (§91-99).
   8.6 Verify all tools respect the max-rule for `next_revisit_at` (§5-6, 240-242, 286-312, 353, 470).
   8.7 Implement portalocker for all file writes (§40-41).
   8.8 Verify exponential backoff implementation (§52-57).
   8.9 Verify error mapping implementation (§54-62).
   8.10 Verify schema checksum implementation (§153-154).
   8.11 Verify template placeholder validation implementation (§226, §229).
   8.12 Verify provider presence validation implementation (§409, §76).
   8.13 Verify failure_revisit_days logic implementation (§5-6, 240-242, 286-312, 353, 470).
   8.14 Verify icp_config.refresh_policy.domain_ttl_days override implementation (§239).
   8.15 Verify icp_config.search.max_pages override implementation (§239-244).
   8.16 Verify icp_config.default_country fallback for phone parsing implementation (§21-24).
   8.17 Verify icp_config.role_priority configuration loading implementation (§309-311).
   8.18 Verify audit trail logging implementation (§91-99).
   8.19 Implement nightly garbage collection script with 3-version retention and 365-day TTL (§34-39).
   8.20 Verify progressive SERP pagination implementation (§239-244).
   8.21 Verify content hash deduplication implementation (§283-285).
   8.22 Verify LinkedIn routing and canonicalization implementation (§22-24).
   8.23 Verify seniority ranking mapping implementation (§309-311).
   8.24 Verify provider failover logic implementation (§321-360).
   8.25 Verify best contact selection and recomputation logic (§333-336).
   8.26 Verify copy-on-write compaction for rotated sinks (§46).
   8.27 Verify `icp_config.refresh_policy.failure_revisit_days` logic implementation (§5-6, 240-242, 286-312, 353, 470).
   8.28 Verify `icp_config.refresh_policy.domain_ttl_days` override implementation (§239).
   8.29 Verify `icp_config.search.max_pages` override implementation (§239-244).
   8.30 Verify `icp_config.default_country` fallback for phone parsing implementation (§21-24).
   8.31 Verify `icp_config.role_priority` configuration loading implementation (§309-311).
   8.32 Verify LinkedIn path masking implementation (§483-485).
   8.33 Verify SyncSemaphorePool implementation for blocking SDK calls (§40-41, 418).
   8.34 Verify email_source population and best-contact selection logic (§349-352).
   8.35 Verify other_links append-only semantics (§349-352).
   8.36 Verify exact model name usage in Domain tool (§237-238).
   8.37 Verify round4() utility implementation for cost and metrics (§386).
   8.38 Verify `icp_config.mode` (fast/thorough) implementation (§239-244).
   8.39 Verify `icp_config.filtering_strict` implementation (§250-253).
   8.40 Verify `icp_config.queries` template placeholder validation implementation (§226, 229).
   8.41 Verify `icp_config.required_fields` and `icp_config.optional_fields` validation implementation (§100-156).
   8.42 Verify HTTP_TIMEOUT and SMTP_TIMEOUT error mapping implementation (§54-62).
   8.43 Verify schema checksum validation and drift detection implementation (§153-154).

Backlog / Phase-2
B1 Multi-currency cost support (spec placeholder).
B2 GUI dashboard for metrics.
