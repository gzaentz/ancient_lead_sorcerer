Architecture & Constraints
Exactly 3 tools: tools/domain.py, tools/crawl.py, tools/enrich.py.
Single-file isolation:
Each tool must contain all of its logic, caching, prompts, retries inside its own file. (Schema is shared and loaded from schemas/unified_lead_record.json.)
All tools must respect refresh_policy.revisit_after_days; when setting provenance.next_revisit_at, use max(existing_next_revisit_at, now + revisit_after_days). refresh_policy.failure_revisit_days (default: 1).
On failures (e.g., crawl_failed, provider unavailable), set provenance.next_revisit_at = max(existing_next_revisit_at, now + failure_revisit_days).
All timestamps are ISO-8601 UTC with Z suffix.
IDs are deterministic (use stdlib constants uuid.NAMESPACE_DNS and uuid.NAMESPACE_URL):
lead_id = uuid5(uuid.NAMESPACE_DNS, eTLD+1)
contact_id = uuid5(uuid.NAMESPACE_URL, f"{domain}|{normalized_full_name}|{normalized_role}|{linkedin or ''}")
Do not regenerate IDs on re-runs.
normalized_full_name and normalized_role = trim, collapse internal whitespace to single spaces, lowercase, and Unicode NFKD fold (strip accents).
LinkedIn canonicalizer regex: r"^(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?P<type>in|company)/(?P<slug>[^/?#]+)" Keep both groups; normalize the stored fields as:
contacts[*].linkedin = "/in/<slug>" # contacts: people only
company.ids.linkedin = "/company/<slug>" # company's own page id
company.socials.linkedin = "https://www.linkedin.com/company/<slug>"
If an input link is a company page, never place it in contacts[*].linkedin; route to company.ids/company.socials per above.
Phone numbers MUST be normalized to E.164 using the phonenumbers library.
If a number lacks a country code, parse in this order:

1. company.hq_location country (if present)
2. icp*config.default_country
   If parsing still fails → emit PARSE_ERROR. PARSE_ERROR must originate from the authoritative error-enum.
   Never log raw phone numbers; mask as "+XXXXXXXX{last4}" in errors/logs.
   All tools MUST normalize domains to eTLD+1 via the Public Suffix List (PSL) BEFORE computing lead_id/contact_id or writing any record fields.
   Use data_dir from config for persistent stores: data/domain_history.jsonl, data/crawl_artifacts/.
   Data directory precedence (first non-empty wins): payload.config.data_dir → env LEADPOET_DATA_DIR → ./data.
   All tools MUST use portalocker for write locks on *.jsonl and artifact files; acquire the lock only for the write phase, not during network I/O.
   Evidence persistence: Each tool MUST persist its full, untruncated evidence to disk and set a pointer in provenance.evidence*paths:
   Domain → data/evidence/domain/{eTLD+1}.json
   Crawl → data/crawl_artifacts/{eTLD+1}.json (already required)
   Enrich → data/evidence/enrich/{eTLD+1}.json
   Artifacts MUST exclude secrets/tokens; PII is allowed. Record JSON holds only summarized evidence (e.g., discovery_evidence, company/contacts evidence_urls) and may be truncated per schema limits.
   Artifact Retention & Garbage Collection
   Artifacts under `data/evidence/**` and `data/crawl_artifacts/**` MUST be garbage-collected by a nightly orchestrator task:
   Keep the latest **3** versions per domain.
   Delete files older than **365 days**.
   Skip deletion if a file path is currently referenced in any `provenance.evidence_paths.*`.
Individual tools **never** delete files; GC is orchestration-layer only.
All three tools MUST honor icp_config.concurrency.max_concurrent_requests (default 3) for any outbound HTTP/SDK calls they initiate.
Implementation note: wrap **all** outbound network calls in an `asyncio.Semaphore(max*concurrent_requests)`(or a thread-safe equivalent for sync code) so the cap is enforced batch-wide. Unit tests should assert that >N parallel tasks block until permits free.
   Orchestrator rotates only append-only sinks (>10 MB or >30 days):
   data/domain_all.jsonl, data/domain_pass.jsonl, and dated exports under data/exports/\*\*
   Do NOT rotate per-domain artifacts referenced by provenance.evidence_paths.*:
   data/crawl_artifacts/{eTLD+1}.json, data/evidence/**
   If compaction is required, use copy-on-write to a new path and update the pointer atomically in the same run.
   No cross-imports between tools. No shared utility modules.
   Allowed imports: standard library + approved third-party libs (httpx ≥ 0.27 for HTTP; async supported), OpenAI SDK, OpenRouter client, Firecrawl SDK, Google Programmable Search (GSE), Proxycurl, Mailgun, Snov.io, phonenumbers, portalocker. Each tool declares an internal version string (e.g., 1.0.0) and sets provenance.tool_versions.{tool} on every run. Bump the version when logic, prompts, or schema usage changes.
   Domain must call Google Programmable Search (GSE); Crawl must call Firecrawl. Enrich must call Proxycurl, Mailgun, and Snov.io.
   Prompts may be duplicated per-file; the schema is not duplicated and must be loaded from schemas/unified_lead_record.json. Each tool validates inputs/outputs at runtime; on mismatch, fail fast for that item, add a structured errors[] entry, and still return the standard envelope. errors[] objects use {code, message, tool, lead_id?, item?, retryable, context?}. code is from a fixed enum: SCHEMA_VALIDATION, HTTP_429, HTTP_TIMEOUT, SMTP_TIMEOUT, DNS_FAILURE, PROVIDER_ERROR, EXTRACT_ERROR, BUDGET_EXCEEDED, PARSE_ERROR, UNKNOWN. errors[] MUST mask PII (emails "j\***@domain.com", phones "+1**\*\***7890", LinkedIn paths masked). Full PII is forbidden in errors[] and logs. Backoff: 1s → 2s → 4s → 8s → 16s (max 5 attempts), within a 45s wall-clock cap per item.
   Connect/read timeouts (3 s / 10 s) apply per attempt.
   The exponential back-off ladder governs the delay **between** attempts.
   Both safeguards run under the 45 s wall-clock cap per item.
   Error mapping (authoritative):
   Exhausted retries on 429 → code=HTTP_429, retryable=true.
   Exhausted retries on 5xx → code=PROVIDER_ERROR, retryable=true, include http_status.
   Per-attempt timeout OR 45s wall-clock hit with no success → code=HTTP_TIMEOUT, retryable=true.
   Non-429 4xx → code=PROVIDER_ERROR, retryable=false, include http_status.
   DNS resolution failure → code=DNS_FAILURE, retryable=false.
   SMTP validation timeout → code=SMTP_TIMEOUT, retryable=true.
   EXTRACT_ERROR = Firecrawl returned 2xx but parse failed.
   PARSE_ERROR = Data failed client-side parsing/normalisation (e.g., phone number). retryable=false.
   Uncaught Exceptions
   Any unhandled exception MUST surface as:
   &nbsp;&nbsp;&nbsp;code = UNKNOWN
   &nbsp;&nbsp;&nbsp;retryable = false
   &nbsp;&nbsp;&nbsp;message = "<ExceptionClass>: <truncated_message>"
   The orchestrator MUST count these and expose`metrics.health.unknown_error_count`.
   Interfaces each tool must expose: Inputs/outputs must conform to the canonical schema; no alternative formats or interfaces (strict contract for run() and main() only). On schema validation failure, include lead_id if available in errors[].
   run(input: dict) -> dict (pure, deterministic given inputs and cache state). Each tool always receives a generic payload: dict; expected keys for that stage are documented below (e.g., Domain expects {icp_config}, Crawl expects {lead_records, icp_config}, etc.).
   main() CLI: reads JSON from stdin, writes JSON-only to stdout; all logs go to stderr. Use non-zero exit only for fatal startup/CLI errors. Tool logic errors go into errors[] while still returning the envelope.
   Outputs are append-only, canonical JSON (see schemas below). Tools may update only: status, provenance.*\_at, provenance.next*revisit_at (max-rule), cost.\* cumulative totals, and fields owned by that tool. All other fields are append-only. When a tool updates any record.cost.{domain_usd|crawl_usd|enrich_usd}, it MUST recompute cost.total_usd = sum(domain_usd, crawl_usd, enrich_usd).
   All tools must always return { "data": { "lead_records": [...] }, "errors": [...], "metrics": {...} }. On any error, return partial results and append an error object including lead_id where applicable; do not crash.
   Orchestrator (separate file, not a tool): imports or shells to each tool, connects data flow Domain → Crawl → Enrich, handles batch sizing and persistence. Orchestrator is the only place tools “meet”.
   Load secrets from env/secret manager; never print secrets. Redact PII in logs (mask emails/phones). All logs → stderr. Logs are single-line JSON objects {ts, level, tool, msg} with PII masked.
   Expected env vars: GSE_API_KEY, FIRECRAWL_KEY, PROXYCURL_KEY, MAILGUN_SMTP_LOGIN, MAILGUN_SMTP_PW, SNOV_IO_ID, SNOV_IO_SECRET, GSE_CX (Google Programmable Search Engine-ID (CX) used in all GSE calls), OPENROUTER_KEY

Data Flow
icp_config.json → Domain.run(config)
→ lead_records[] (canonical per domain; includes pre_score/pre_pass and provenance)
→ Crawl.run({ lead_records, icp_config })
→ lead_records[] (company + 0..N contacts + icp.crawl_score)
→ Enrich.run({ lead_records, icp_config, caps })
→ lead_records[] (required fields filled / gaps noted, costs)
All three tools must accept JSON in, return JSON out with a top-level { "data": ..., "errors": [...], "metrics": {...} }.
Never crash the pipeline: accumulate per-item errors; return partials; set status.
Each stage that changes status must append a status event to status_history[] with { status, ts, notes }

State Machine (Authoritative)
Allowed transitions:
Domain-generated records start with status "scored". Status "new" is reserved exclusively for externally imported leads; no current tool emits it. Each tool MUST add an initial status_history entry the first time it sets or changes status. No other transitions permitted. Every transition MUST append {status, ts, notes} to status_history[].
new → scored → crawled → enrich_ready → enriched
scored → crawl_failed
crawled → enrich_partial
Gates:
Domain: new→scored
Crawl: scored→crawled; MAY set crawled→enrich_ready iff (icp.crawl_score ≥ icp.threshold AND required_fields.company satisfied)
Enrich: enrich_ready→enriched OR crawled→enrich_partial

Canonical JSON (unified_lead_record.json)
All tools load the canonical schema from schemas/unified_lead_record.json and validate I/O against it.
{
"lead_id": "uuid",
"domain": "example.com",
"company": {
"name": null,
"description": null,
"industry": null,
"naics_keywords": [],
"hq_location": null,
"locations": [],
"size_hint": null,
"socials": { "linkedin": null, "github": null, "twitter": null, "telegram": null, "instagram": null },
"careers_url": null,
"blog_url": null,
"tech_stack": [],
"evidence_urls": [],
"ids": { "linkedin": null, "crunchbase": null }
},
"contacts": [
{ "contact_id": "uuid", "full_name": null, "role": null, "department": null,
"seniority": null, "role_priority": null,
"email": null, "email_confidence": null,
"email_status": ["unknown", "valid", "risky", "invalid", "catch_all"], "email_source": ["provider", "csv"],
"phone": null, "linkedin": null, "other_links": [], "evidence_urls": [] }
],
"icp": { "pre_score": null, "pre_reason": null,
"pre_pass": null, "pre_flags": [],
"scoring_meta": { "method": null, "model": null, "prompt_fingerprint": null, "temperature": null },
"crawl_score": null, "crawl_reason": null,
"threshold": 0.7, "filtering_strict": true },
"provenance": {
"queries": [],
"discovery_evidence": [],
"scored_at": null,
"crawled_at": null,
"enriched_at": null,
"next_revisit_at": null,
"tool_versions": {
"domain": { "version": null, "schema_version": null },
"crawl": { "version": null, "schema_version": null },
"enrich": { "version": null, "schema_version": null }
},
"cache": { "domain_cache_hit": null },
"evidence_paths": { "domain": null, "crawl": null, "enrich": null }
},
"best_contact_id": null,
"status": ["new", "scored", "crawled", "enrich_ready", "enriched", "crawl_failed", "enrich_partial"],
"status_history": [ { "status": "string", "ts": "iso8601", "notes": "string|null" } ],
"audit": [ { "step": "Domain|Crawl|Enrich", "notes": "string", "ts": "iso8601" } ],
"cost": { "domain_usd": 0.0, "crawl_usd": 0.0, "enrich_usd": 0.0, "total_usd": 0.0 }
}
Tools must record the schema they validated against: set provenance.tool_versions.{tool}.schema_version to a checksum (e.g., sha256 of the schema) each run.
Checksum algorithm: schema_version = sha256(open('schemas/unified_lead_record.json','rb').read()) # hex digest. This checksum is stored only in provenance.tool_versions.{tool}.schema_version.
Truncate arrays: company.evidence_urls ≤ 10, contacts[*].evidence_urls ≤ 5. Truncation limits apply to the record JSON only; artifact evidence files are untruncated. Strings ≤ 2KB each. Large blobs go in persisted artifacts, not the record.

Field Ownership (Authoritative)

Cost bookkeeping: Domain sets cost.domain*usd, Crawl sets cost.crawl_usd, Enrich sets cost.enrich_usd; orchestrator never edits cost fields. All costs are USD; multi-currency would add currency_code to icp_config.
Canonicalization: company.socials.* store normalized full URLs; company.ids._ store canonical provider identifiers/slugs (e.g., LinkedIn "/company/<slug>"). Crawl prefers filling socials; Enrich may backfill ids.
Domain MAY set/update:
icp.pre_score, icp.pre_reason, icp.pre_pass, icp.pre_flags, icp.scoring_meta, provenance.queries, provenance.discovery_evidence, provenance.scored_at, provenance.tool_versions.domain, provenance.next_revisit_at (max-rule), provenance.cache.domain_cache_hit, cost.domain_usd, cost.total_usd (recompute sum)
Crawl MAY set/update:
company._ (as defined in canonical schema), company.evidence*urls (≤10), contacts[] (create/update; dedupe by contact_id; each evidence_urls ≤5), contacts[*].seniority, contacts[*].role_priority, icp.crawl_score, icp.crawl_reason, provenance.crawled_at, provenance.tool_versions.crawl, provenance.next_revisit_at (max-rule), cost.crawl_usd, cost.total_usd, status to crawled|enrich_ready|crawl_failed,
Enrich MAY set/update:
best_contact_id, contacts[*].email, email_status, email_source, email_confidence, phone, linkedin, other_links (append-only semantics), company.ids backfill, provenance.enriched_at, provenance.tool_versions.enrich, provenance.next_revisit_at (if changed; max-rule), cost.enrich_usd, cost.total_usd, status to enriched|enrich_partial

ICP JSON (icp.json)
{
"name": "<icp_name>",
"icp_text": "<one-sentence ICP description>",
"queries": [
"${industry} companies in ${region}"
],
"required_fields": {
"company": ["name", "hq_location"],
"contact": ["email"]
},
"optional_fields": {
"company": ["tech_stack"],
"contact": ["phone"]
},
"threshold": 0.7,
"filtering_strict": true,
"mode": "fast | thorough",

"refresh_policy": {
"revisit_after_days": 90,
"failure_revisit_days": 1,
"domain_serp_ttl_hours": 24,
"crawl_ttl_days": 14
},

"concurrency": {
"max_concurrent_requests": 3
},

"search": {
"max_pages": 5 // default; fast mode uses min(1, max_pages)
},

"testing": {
"process_rejected": false,
"process_low_crawl": false
},

"caps": {
"company_usd": 0.02,
"contact_usd": 0.03,
"run_usd_max": 5.0
},

"role_priority": {
"ceo": 1,
"vp sales": 2,
"director": 3,
"default": 99
},

"exports": {
"enabled": true
},

"default_country": "<ISO-3166 country code>"
}
Templates use ${placeholder} syntax and are rendered via Python string.Template(...).substitute(\*\*context).
If any placeholder is missing, the tool MUST return SCHEMA_VALIDATION (no partial substitution).

Tool Requirements
tools/domain.py (Domain)
Purpose
Generate qualified domains from ICP queries using cheap pre-crawl scoring.
Inputs
icp_config.json fields: name, icp_text, queries/query_templates (+placeholders), required_fields: { company: [<field names>], contact: [<field names>] }, optional_fields, icp.threshold, filtering_strict, mode, refresh_policy.revisit_after_days (default: 90), refresh_policy.failure_revisit_days (default: 1), search.max_pages (int, optional)
Behavior
Generate `lead_id = uuid5(uuid.NAMESPACE_DNS, eTLD+1)` for every emitted record **before** any scoring logic.
LLM scoring runs with temperature=0. Record prompt_fingerprint=sha256(full_prompt).
Model: gpt-4o-mini-1.5 via OpenRouter (fallback gpt-3.5-turbo via the same OpenRouter endpoint).
Persist a durable ‘domain history’ store (pass + reject) for cross-run deduplication and TTL enforcement. Domain-history TTL (authoritative): purge any domain-history entry older than 180 days at Domain-tool startup. Override via icp_config.refresh_policy.domain_ttl_days (int, days).
SERP pagination: fast → 1 page (default) · thorough → 5 pages (default). Override both via icp_config.search.max_pages. The tool may progressively fetch the next page on subsequent runs when provenance.cache.domain_cache_hit = false and current page < max_pages.
Respect refresh_policy.revisit_after_days; set/refresh provenance.next_revisit_at using the max-rule.
When setting status="scored", append {status, ts, notes} to status_history.
Cache (inline): search_pages[{query}|{page}|google] = results + fetched_at with TTL; skip refetch within TTL.
Default ttl_hours = 24 (overridable via icp_config.refresh_policy.domain_serp_ttl_hours)
cache_hit_rate (for Domain) = domain_cache_hits / (domain_cache_hits + domain_cache_misses) for this run
Respect icp_config.concurrency.max_concurrent_requests (default 3) when issuing external HTTP calls.
Set provenance.cache.domain_cache_hit = true|false per record when SERP results reused
Persist a SERP snapshot per processed domain to data/evidence/domain/{eTLD+1}.json containing: { queries run, fetched_at, topN SERP results (title, url, snippet, rank, page_index), scoring prompt fingerprint }. Set provenance.evidence_paths.domain = "data/evidence/domain/{eTLD+1}.json".
Normalize results: domain (eTLD+1 via PSL), url, title, snippet, query, page_index, rank_on_page, fetched_at.
Cheap LLM scoring on (title, snippet, query) + icp_text.
Filter ≥ threshold; dedupe by domain; keep rejected with reasons.
Emit canonical lead_records[] items (one per unique domain) with icp.pre_pass set (true/false) and status="scored" for both pass and reject.
Output: lead_records[] (canonical, one per unique domain). Includes both passing and screened-out records with icp.pre_score, icp.pre_reason, icp.pre_pass, and icp.scoring_meta. Metrics include pass rate.

Errors & Resilience
429/backoff, zero-yield handling, continue on partials. Never raise; return partials; append errors with lead_id (if available) and the originating query. Abandon any external request after 45 s total elapsed time per item (wall clock, includes retries) to prevent long-tail hangs. Per-attempt timeouts: connect 3s, read 10s.
Interface
run(icp_config: dict) -> {"data": {"lead_records": [...]}, "errors": [...], "metrics": {...}}
Population of new fields
icp.pre_pass: set to icp.pre_score >= icp.threshold.
icp.scoring_meta: { method: "llm", model: "<model>", prompt_fingerprint: "<sha256>", temperature: 0.0 } recorded when scoring runs.
provenance.tool_versions.domain: set from internal version string on every run.
provenance.discovery_evidence: up to 3 SERP items { url, title, snippet, query, page_index, rank_on_page, fetched_at }.
provenance.next_revisit_at: compute with max-rule.
provenance.cache.domain_cache_hit: true|false depending on search cache usage.
icp.pre_flags: optional flags when the scoring prompt detects disqualifiers (e.g., geo_mismatch).
best_contact_id, company.ids, contacts[*] extensions are untouched here.
provenance.scored_at = now()
provenance.evidence_paths.domain = "data/evidence/domain/{eTLD+1}.json".
External API dependencies
Google Search Engine (GSE) for search.

tools/crawl.py (Crawl)
Purpose
Fetch site, extract company & contacts, re-validate ICP; emit one row per contact (plus company-only if none).
Inputs
{ "lead*records": [...], "icp_config": {...} }
Behavior
Generate contacts[*].contact_id = uuid5(NAMESPACE_URL, f"{domain}|{normalized_full_name}|{normalized_role}|{linkedin or ''}") during extraction. Dedupe contacts per lead by contact_id. Use canonicalized LinkedIn handle (strip protocol, domain, and query; keep /in/<slug> or company page path only).
Set status="enrich_ready" iff icp.crawl_score >= icp.threshold and company meets required_fields.company. Otherwise keep status="crawled".
Persist crawl_artifacts to disk (not memory-only) to support cross-run caching and refresh policy.
Persist to: data/crawl_artifacts/{eTLD+1}.json
Default crawl_ttl_days = 14 (overridable via icp_config.refresh_policy.crawl_ttl_days)
Reuse artifacts if (now - crawled_at) < crawl_ttl_days AND content_hash unchanged; otherwise refetch. content_hash = sha256(json.dumps(extracted_json, sort_keys=True).encode())
cache_hit_rate (for Crawl) counts artifact reuses vs total lookups during this run
Respect revisit policy; when successful, recompute provenance.next_revisit_at with max-rule.
Normalize: domain → eTLD+1; names/roles → trimmed single-space; emails lowercase with punycoded domain; phones E.164 (if present).
Preserve any original email string only inside artifact files; the record JSON stores the normalized form.
On transition to crawled or crawl_failed, append a status_history entry.
Firecrawl extraction:
Firecrawl extract (single-call; respects robots, throttling, and retries).
Call POST /extract on https://{domain} (fallback to http:// if TLS fails or the origin redirects) with predefined JSON schema to extract:
company.name, description, industry, hq_location, socials.linkedin, careers_url, blog_url
employees[*].full_name, role, linkedin, email
Store extracted result in data/crawl_artifacts/{eTLD+1}.json.
Do not request raw HTML or markdown.
Extract with evidence URLs.
Second ICP validation → icp.crawl_score / icp.crawl_reason.
Cache (inline): crawl_artifacts[{domain}] = crawled_at, content_hash, extracted_summary; honor refresh_policy.
Output: lead_records[] in canonical schema; set status to crawled or crawl_failed.
Errors & Resilience
On hard fail, return minimal record with status="crawl_failed"; do not block batch. Never raise; return partials; append errors with lead_id. Abandon any external request after 45 s total elapsed time per item (wall clock, includes retries) to prevent long-tail hangs. Per-attempt timeouts: connect 3s, read 10s.
Interface
run(payload: dict) -> {"data": {"lead_records": [...]}, "errors": [...], "metrics": {...}}
Population of new fields
provenance.tool_versions.crawl: set from internal version string on every run.
company.ids: populate from onsite links/metadata (linkedin/crunchbase) when detected.
contacts[*].seniority and contacts[*].role_priority: inferred from titles/role patterns during extraction.
seniority_rank mapping (case-insensitive on title):
{"c-level":1, "vp":2, "head":3, "director":3, "manager":4, "lead":5, "ic":6, "other|unknown":99}
Crawl sets contacts[*].seniority; Enrich MUST NOT change seniority.
provenance.next_revisit_at: recompute using the max-rule (max(existing, now + revisit_after_days)).
icp.pre\*\* unchanged; icp.crawl_score/icp.crawl_reason set here. Ensure status change is logged in status_history.
provenance.discovery_evidence unchanged; append page URLs to company.evidence_urls instead.
best_contact_id not set in this stage.
provenance.crawled_at = now()
provenance.evidence_paths.crawl = "data/crawl_artifacts/{eTLD+1}.json".
External API dependencies
Firecrawl SDK for page crawl (fetch & parsing).

tools/enrich.py (Enrich)
Purpose
Fill required fields first; enrich only the best contact per domain; keep costs to cents.
Inputs
{ "lead*records": [...], "icp_config": {...}, "caps": {"company_usd": 0.02, "contact_usd": 0.03} }
Behavior
Normalize domain to eTLD+1 via Public Suffix List; emails lowercase with punycoded domain; phones to E.164; trim/condense whitespace in names/roles.
Caps may include {run_usd_max}. When reached, stop paid enrichment, return partials, and append a single BUDGET_EXCEEDED error for the run.
If processing the next lead would exceed `run_usd_max`, the tool MUST skip that lead entirely (no partial enrichment) and append one `BUDGET_EXCEEDED` error referencing the skipped `lead_id`.
Before returning, set status to enriched or enrich_partial and append a status_history entry.
Respect caps; stop optional enrichment when cap hit; still return partials and log in errors[] if any provider fails.
Deterministic best-contact selection:
Sort by this tuple (ascending) and pick first:
(role_priority, seniority_rank, email_status_rank, has_linkedin, contact_id)
email_status_rank: valid=0, risky=1, catch_all=2, unknown=3, invalid=4
has_linkedin: True=0, False=1
Ties fall back to smallest contact_id (lexicographic), guaranteeing stability.
Company-first enrichment (cheap providers first, e.g., Proxycurl).
Paid discovery only if within cap.
Track provider, confidence, and per-lead cost; stop optional when cap hit.
If a single lead would exceed run_usd_max, skip that lead and log a BUDGET_EXCEEDED error.
Role-priority mapping lives in icp_config.role_priority (object).
Output: updated lead_records[], status → enriched|enrich_partial, audit, costs.
Errors & Resilience
429/backoff, provider failover, never block batch. Never raise; return partials; append errors with lead_id. Abandon any external request after 45 s total elapsed time per item (wall clock, includes retries) to prevent long-tail hangs. Per-attempt timeouts: connect 3s, read 10s.
Interface
run(payload: dict) -> {"data": {"lead_records": [...]}, "errors": [...], "metrics": {...}}
Population of new fields
provenance.tool_versions.enrich: set from internal version string on every run.
best_contact_id: set to the deterministically chosen contact ID. best_contact_id MUST reference an existing contacts[*].contact_id in the same record. If no contact meets selection criteria, leave best_contact_id=null. If the previously selected contact no longer exists, recompute deterministically and select the smallest contact_id on tie.
contacts[*].email_status and contacts[*].email_source: set during verification, or provider lookup; update email_confidence accordingly.
company.ids: backfill linkedin/crunchbase IDs from providers if missing.
provenance.next_revisit_at: typically unchanged; if updated, apply max-rule and log in status_history.
icp.scoring_meta, icp.pre\*\* unchanged.
provenance.enriched_at = now()
provenance.evidence_paths.enrich = "data/evidence/enrich/{eTLD+1}.json".
External API dependencies
Proxycurl for firmographic + role enrichment.
Mailgun for primary SMTP validation.
Snov.io for email enrichment.

Metrics
Returned by every tool in envelope.metrics:
{
count*in: int,
count_out: int,
duration_ms: int,
cache_hit_rate: float|null, // hits / (hits + misses) within this tool
pass_rate: float|null, // Domain: pre_pass true rate; Crawl: enrich_ready / crawled; Enrich: enriched / processed
cost_usd: {
domain: float, // cumulative for this tool-run
crawl: float,
enrich: float,
total: float // domain + crawl + enrich
}
}
Cost Model: Each tool must convert provider usage into USD using unit prices defined in config/costs.yaml and recompute record.cost.<stage>\_usd and cost.total_usd.
For Enrich, cache_hit_rate MAY be null.
pass_rate definitions:
Domain: pre_pass true / processed
Crawl: enrich_ready / crawled
Enrich: enriched / processed
metrics.duration_ms covers tool runtime (wall clock) for the batch.
metrics.cost_usd.* are tool-run totals; use 0.0 for non-applicable fields.
record.cost.\_ are per-lead cumulative and MUST sum to record.cost.total_usd.
All floats rounded to 4 decimals.
Cost Configuration (Authoritative): Each tool looks up unit pricing from `config/costs.yaml`.

Example YAML:

```yaml
proxycurl:
  unit: 'lookup'
  usd_per_unit: 0.0100
mailgun:
  unit: 'smtp_validation'
  usd_per_unit: 0.0020
snovio:
  unit: 'email_enrich'
  usd_per_unit: 0.0150
openrouter:
  unit: '1k_tokens'
  usd_per_unit: 0.0020
gse:
  unit: 'request'
  usd_per_unit: 0.0005
```

If a provider is missing, the tool MUST raise PROVIDER_ERROR during startup.

Orchestrator Contract
Not a tool; separate file (e.g., orchestrate.py).
May import each tool module and call run, or shell the CLI variants and pipe JSON.
Always write domain*all.jsonl (pass + rejects) with icp.pre_score, icp.pre_reason, and icp.scoring_meta retained for rejects.
Do not mutate records beyond routing/persistence; tools are solely responsible for status changes and status_history.
By default, only records with status="enrich_ready" are passed to Enrich. To also process below-threshold crawled items, set icp_config.testing.process_low_crawl=true.
Responsibilities:
Load icp_config.json; set batch size & caps. Default batch_size=50 (configurable).
Each tool enforces icp_config.concurrency.max_concurrent_requests (default 3) across all external calls (LLMs, HTTP, SDKs).
Call Domain.run → filter lead_records where icp.pre_pass=true → pass lead_records to Crawl.run → pass lead_records to Enrich.run.
Two persisted sinks:
data/domain_all.jsonl
Domain output, pass + rejects, include icp.pre*\* and icp.scoring_meta
data/domain_pass.jsonl
Domain output filtered to icp.pre_pass=true
Enrich exports (when requested via icp_config.exports.enabled=true):
data/exports/{icp_config.name}/{YYYYMMDD_HHMM}/leads.jsonl
data/exports/{icp_config.name}/{YYYYMMDD_HHMM}/leads.csv
Timestamps in {YYYYMMDD_HHMM} are in UTC to match “All timestamps are ISO-8601 UTC with Z suffix.”
CSV is UTF-8, comma-delimited, double-quoted; columns follow canonical JSON flattened with dot-notation.
CSV flattening rules:
Dot-notation for objects (e.g., "company.name").
Arrays joined by "|" in field order; arrays of objects not exported unless explicitly mapped.Contact export mapping: export only the best contact (when best_contact_id is set) using columns contact.full_name, contact.role, contact.email, contact.phone, contact.linkedin. Arrays of additional contacts are omitted.
Booleans as "true"/"false"; null as empty string.
Columns sorted lexicographically by flattened key for stability across runs.
Summarize metrics (precision proxy, domains/hour, $/qualified).
Data directory precedence (first non-empty wins): payload.config.data_dir → env LEADPOET_DATA_DIR → ./data. The orchestrator MUST pass payload.config.data_dir when set.
By default, only icp.pre_pass=true go to Crawl. To include pre_pass=false (rejects), set icp_config.testing.process_rejected=true.
No logic leakage: Any scoring/extraction/enrichment lives inside the tools, not the orchestrator.

Testing
Contract tests (one file per tool, same directory) may import the tool and feed fixtures; no shared helpers.
Test fixtures live in tests/fixtures/; CI uses responses or httpx_mock to stub external APIs – no real keys hit.
Validate that each tool:
Accepts required keys, rejects malformed input with clear errors.
Preserves canonical schema shape; only appends/updates allowed fields.
Is idempotent with same inputs and caches.
Validate other tests for:
Status history: Every tool appends a history entry on each status change; order is chronological.
Versioning: Each tool stamps provenance.tool_versions.{tool}; value changes when logic/prompt/schema usage changes.
Caching/persistence: Domain history used for cross-run dedupe/TTL; Crawl artifacts persist across runs; revisit max-rule enforced.
Rejected-lead policy: By default, rejects are not sent to Crawl/Enrich; when icp_config.testing.process_rejected=true, pipeline includes them.
Error contract: On injected failures, tools return partials and populate errors[] with lead_id.
Envelope: Outputs always match {data, errors, metrics} even on failures.
Idempotence: Same inputs + cache state ⇒ identical outputs.
Metrics includes at minimum: {count_in, count_out, duration_ms, cache_hit_rate, pass_rate, cost_usd: {domain, crawl, enrich, total}}.
Deterministic IDs: same inputs + cache ⇒ identical lead_id / contact_id (when using uuid5); different contact tuple ⇒ different contact_id.
State machine tests: Disallow any transition not listed in the authoritative state machine. Verify gate: Enrich receives only enrich_ready unless testing flag set.
Errors contract: errors[] shape matches schema; PII is masked; codes are from the enum.
Caching: Domain respects ttl_hours and reports cache_hit_rate. Crawl respects crawl_ttl_days and reports cache_hit_rate.
Revisit policy: Test revisit_after_days, both failures and passes.
Determinism: Domain normalization to eTLD+1 before IDs. Best-contact tie resolves by smallest contact_id. Duplicate inputs with same cache state ⇒ identical outputs/IDs.

Documentation
README sections to add:
“Schema Validation & Contract” — how each tool validates inputs/outputs vs canonical schema; strict envelope.
Feed an outdated schema to ensure tool returns SCHEMA_VALIDATION error.
“Status History” — rules, examples, and where it’s appended.
“Caching & Revisit Policy” — domain history, crawl artifacts, TTL, and the max-rule for next_revisit_at.
Max-rule (authoritative): provenance.next_revisit_at = max(existing_next_revisit_at or 0, now + revisit_after_days). All tools must apply this rule whenever they set or update next_revisit_at and must append a status_history note whenever the field changes.
“Versioning Policy” — internal version strings and when to bump.
Version bump rules:
MAJOR: envelope shape or required I/O fields change.
MINOR: backward-incompatible change to canonical schema or selection/scoring semantics.
PATCH: prompt wording, heuristics, retry tuning, logging, or bug fixes without observable contract change.
Tools MUST set provenance.tool_versions.{tool}.version and .schema_version on every run. schema_version is computed once at process start from schemas/unified_lead_record.json (sha256 hex).
“Rejected Lead Handling” — defaults and icp_config.testing.process_rejected flag.
“Error Handling” — partial returns, errors[] shape, inclusion of lead_id.
“State Machine (Authoritative)” — allowed transitions, gating rules, examples.
“Errors Contract & PII Masking” — errors[] schema, codes, masking examples.
Raw phone numbers and emails may reside only inside persisted artifact files under data/evidence/**. They must never appear in logs, errors[], status_history, or audit notes. Masking functions are mandatory for all outbound log/error paths.
Masking functions are deterministic and idempotent:
Email: "j\***@domain.com" (first character + "**\*" + domain)
Phone: "+XXXXXXXX{last4}" (preserve plus and last 4 digits)
LinkedIn paths: show "/in/\*\***" or "/company/\*\*\*\*"
Never log full provider payloads; redact before serialization.
“Metrics Semantics” — tool-run vs per-lead costs, rounding, examples.
“Caching & TTLs” — Domain SERP ttl_hours, Crawl artifact crawl_ttl_days, cache_hit_rate definitions.
“Revisit Policy” — success vs failure, max-rule, config keys.
“Exports” — exact paths/patterns and how to enable.
