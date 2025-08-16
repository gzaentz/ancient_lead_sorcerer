Lead-Sorcerer Task List 0. Repo & Infra Setup
0.1 Scaffold poetry-based Python repo, CI & pre-commit hooks (§allowed imports).
0.2 Add `config/costs.yaml` default pricing (§387-407).
0.3 Create `data/`, `data/evidence/`, `data/crawl_artifacts/`, `data/exports/` dirs (§29-33, 42-46).
0.4 Install & pin third-party libs: `httpx>=0.27`, `openrouter`, `firecrawl`, `proxycurl`, `mailgun`, `snovio`, `phonenumbers`, `portalocker`, `publicsuffix2` (§48-49).
0.5 Inject env-var loader & .env template for all required keys (§75-76).
0.6 Add nightly GitHub Actions job placeholder for GC (§34-39).

1. Common / Cross-Cutting
   1.1 Data & File Conventions
   1.1.1 Implement eTLD+1 domain normalizer (§25, 273, 327) (unit test converts “sub.foo.co.uk”→“foo.co.uk”).
   1.1.2 Implement Unicode NFKD + single-space normalizer for names/roles (§12, 279, 327).
   1.1.3 Implement deterministic `lead_id` & `contact_id` uuid5 helpers (§8-11, 237, 279).
   1.1.4 Implement ISO-8601 UTC `now_z()` helper (§7, 132-147).
   1.1.5 Implement masking helpers: email, phone, LinkedIn (§483-485) (unit tests validate “j\*\*\*@d.com”, “+XXXXXXXX7890”).
   1.1.6 Central `append_status(history, new_status, notes)` utility (§91-99).
   1.1.7 `recompute_total_cost(record)` to sum stage costs (§72, 371-375, 385).
   1.1.8 Single-line JSON logger w/PII masking (§75, 481).
   1.1.9 `resolve_data_dir(payload)` with precedence (§26-27, 437).
   1.1.10 Evidence writer & pointer updater (§29-33, 248, 281).

1.2 Concurrency Guard
1.2.1 Create `AsyncSemaphorePool` enforcing `max_concurrent_requests` across libraries (§40-41, 418) (unit test blocks on >N).

1.3 Error Handling & Retries
1.3.1 Define authoritative `ErrorCode` enum (§54-62).
1.3.2 Back-off wrapper 1→2→4→8→16 s, 45 s cap (§52-57).
1.3.3 Map HTTP/DNS/SMTP/etc. to errors[] per spec (§54-62).
1.3.4 Global `wrap_unknown_errors` decorator → code=UNKNOWN (§63-67).

1.4 Schema Validation & Versioning
1.4.1 Load canonical schema once; compute sha256 checksum (§100-156, 153-154).
1.4.2 `validate_envelope(io_data)` for all tools (§69-74, 443-447).
1.4.3 Inject `INTERNAL_VERSION` per tool & stamp provenance.tool_versions.{tool}.{version|schema_version} (§48, 262, 306, 349, 476).

1.5 Refresh / Revisit Policy
1.5.1 `compute_next_revisit(existing, delta_days)` implementing max-rule (§5-6, 240-242, 286-312, 353, 470).

1.6 Artifact Retention & GC
1.6.1 GC script: keep 3 versions, delete >365 d, skip referenced (§34-39).
1.6.2 Sink rotation: >10 MB or >30 d for append-only logs (§42-46).

1.7 Metrics
1.7.1 Metrics struct builder per tool (§362-376).

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
   2.12 Append status_history “scored” (§242).
   2.13 Cost accounting: GSE unit price, update `cost.domain_usd` & recompute total (§371-375).
   2.14 Metrics: count_in/out, pass_rate, cache_hit_rate (§362-380).
   2.15 Error handling per common utilities (§256-257).
   2.16 Unit test idempotence & cache reuse (§460-462).

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

5. Orchestrator (`orchestrate.py`)
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

6. Testing & CI
   6.1 Unit Tests per Tool
   6.1.1 Validate required/invalid inputs (§443-447).
   6.1.2 Caching TTL & cache_hit_rate accuracy (§244-246, 284-286).
   6.1.3 Concurrency guard blocks excess tasks (§41).
   6.1.4 Deterministic IDs & best contact (§457).
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

7. Documentation / README
   7.1 Add “Schema Validation & Contract” section (§464-468).
   7.2 “Status History” rules (§465-469).
   7.3 “Caching & Revisit Policy” (§470-472).
   7.4 “Versioning Policy” (§472-476).
   7.5 “Rejected Lead Handling” (§477).
   7.6 “Error Handling & PII Masking” (§478-485).
   7.7 “Metrics Semantics” (§486-488).
   7.8 “Exports” guide (§489-491).

8. Compliance & GC
   8.1 Implement nightly GC job as separate script (§34-39).
   8.2 Verify no cross-imports between tools (§47).
   8.3 Static analysis to restrict imports to approved list (§48).
   8.4 Ensure raw PII never logged; audit masking functions (§481-485).

Backlog / Phase-2
B1 Multi-currency cost support (spec placeholder).
B2 GUI dashboard for metrics.
