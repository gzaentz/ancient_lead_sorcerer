# Enrichment Migration Task List

_Last updated: 2025-08-23_

## 0. Scaffolding

- [x] 0.1 Create `src/enrich_providers/` and `__init__.py`.
- [x] 0.2 Add `base.py` interface + typed exceptions.
- [x] 0.3 **Definition of Done:** Directory structure created, base classes defined, imports working

## 1. Extract Legacy Providers

- [x] 1.1 Move Snovio client -> `enrich_providers/snovio.py`.
- [x] 1.2 Move Coresignal logic -> `enrich_providers/coresignal.py`.
- [x] 1.3 Delete moved blocks from `src/enrich.py`.
- [x] 1.4 **Definition of Done:** Unit tests pass, legacy code removed, CI green, no PII leakage verified

## 2. Add New Primary Providers

- [x] 2.1 Implement `company_enrich.py` (CompanyEnrich API).
- [x] 2.2 Implement `anymail_finder.py` (Anymail Finder API).
- [x] 2.3 Add secrets to `.env` / `env.template`.
- [x] 2.4 Update `config/costs.yaml`.
- [x] 2.5 **Definition of Done:** Both providers tested, secrets documented, cost config updated, no PII leakage verified
- [x] 2.6 **Risk:** Vendor onboarding lead time (blocked by: API access, account setup)

## 3. Provider Router

- [x] 3.1 Create `src/enrich_provider_router.py`.
- [x] 3.2 Make tiers configurable via `icp_config`. **(No ICP hard-coding)**
- [x] 3.3 Update `src/orchestrator.py` to call the router.
- [x] 3.4 Add mypy types and docstrings for public methods.
- [x] 3.5 **Definition of Done:** Router handles fallbacks, orchestrator integration complete, types documented
- [ ] 3.6 **Dependencies:** Blocked by 1.x (legacy providers extracted), 2.x (new providers implemented)

## 4. Refactor `src/enrich.py`

- [x] 4.1 Remove direct provider calls.
- [x] 4.2 Import & call router (`get_company`, `get_contacts`).
- [x] 4.3 Keep budgeting, evidence, metrics.
- [x] 4.4 Ensure PII-safe logging throughout.
- [x] 4.5 **Definition of Done:** No direct provider calls, router integration complete, PII logging verified
- [x] 4.6 **Dependencies:** Blocked by 3.x (router implementation)

## 5. Tests & CI

- [x] 5.1 Unit tests for CompanyEnrich provider.
- [x] 5.2 Unit tests for Anymail Finder provider.
- [x] 5.3 Router fallback tests.
- [x] 5.4 Integration pipeline test.
- [x] 5.5 Ensure coverage ≥ 90 %.
- [x] 5.6 Add mypy + flake8/ruff to CI pipeline.
- [x] 5.7 Update CI config file (`.github/workflows/ci.yml` or equivalent).
- [x] 5.8 Mock API fixtures added for new providers.
- [x] 5.9 **Definition of Done:** All tests pass, coverage ≥90%, CI pipeline updated, pre-commit hooks updated

## 6. Documentation

- [x] 6.1 Keep this file up-to-date.
- [x] 6.2 Update README architecture diagram.
- [x] 6.3 Document provider cost table in `docs/provider_costs.md`.
- [x] 6.4 Regenerate sequence/flow charts and publish to internal wiki.
- [x] 6.5 **Definition of Done:** All docs updated, diagrams regenerated, cost table published

## 7. Roll-out

- [ ] 7.1 Shadow mode (new providers in logs only).
- [ ] 7.2 Promote new providers to tier-0.
- [ ] 7.3 One-week monitoring.
- [ ] 7.4 Remove legacy fallback if success ≥ 95 %.
- [ ] 7.5 Add Grafana dashboard + alerts for enrich error rate & spend.
- [ ] 7.6 **Risk Mitigation:** Feature flag/env var to switch back to legacy providers instantly.
- [ ] 7.7 **Monitoring Panels:** Error rate, cost per lead, latency, success rate by provider.
- [ ] 7.8 **Alert Rules:** PagerDuty/Slack channel integration for error rate >5%, cost >$X/day.
- [ ] 7.9 **Definition of Done:** New providers stable, legacy removed, monitoring active, alerts configured

## 8. Security & Privacy

- [ ] 8.1 Update DPIA or security review for new vendors.
- [ ] 8.2 Verify no PII leakage in all provider implementations.
- [ ] 8.3 **Definition of Done:** Security review complete, PII safeguards verified

---

**Owner:** `@data-eng`
**Target release:** _Sprint 34_
**Expected timeline:**

- Phase 0-2: Sprint 32-33 ✅ **COMPLETED** (Provider extraction & implementation)
- Phase 3-4: Sprint 33-34 ✅ **COMPLETED** (Router & refactoring)
- Phase 5: Sprint 34 ✅ **COMPLETED** (Testing & CI)
- Phase 6: Sprint 34 ✅ **COMPLETED** (Documentation)
- Phase 7-8: Sprint 35+ (Rollout & security)

**Rollback Plan:** Feature flag to instantly switch back to legacy providers if issues arise during rollout.
