# Proxycurl to Coresignal Migration Tasks

## Overview

This document outlines the complete migration plan from Proxycurl to Coresignal for the Lead Sorcerer enrichment pipeline. The migration involves replacing the company and contact enrichment provider while maintaining all existing functionality, cost tracking, and error handling.

## Migration Phases

### Phase 1: Analysis & Planning (Days 1-2)

**Owner: Lead Developer + Product Owner**

#### 1.1 Coresignal API Analysis

- [x] **Task 1.1.1**: Review Coresignal API documentation ✅ COMPLETED

  - [x] Study company enrichment endpoints (`/company/v2/companies/by-domain/{domain}`)
  - [x] Study people enrichment endpoints (`/person/v2/people/by-company-domain/{domain}`)
  - [x] Document authentication method (Bearer token)
  - [x] Document rate limits and pagination
  - [x] Document response schemas and field mappings

- [x] **Task 1.1.2**: Map Proxycurl fields to Coresignal equivalents ✅ COMPLETED

  - [x] Company fields mapping (size, industry, revenue, funding, etc.)
  - [x] Contact fields mapping (role, seniority, LinkedIn ID, etc.)
  - [x] Identify missing fields that need fallback providers
  - [x] Document field type differences and conversion requirements

#### 1.2 Architecture Impact Assessment

- [x] **Task 1.2.1**: Review current Proxycurl integration points ✅ COMPLETED

  - [x] Map all files and classes that reference Proxycurl
  - [x] Identify shared interfaces and abstraction layers
  - [x] Document dependency injection patterns
  - [x] Assess test coverage and mocking strategies

- [x] **Task 1.2.2**: Design new provider architecture ✅ COMPLETED
  - [x] Design abstract provider interface
  - [x] Plan provider selection strategy (feature flags vs config)
  - [x] Design fallback and failover mechanisms
  - [x] Plan gradual rollout strategy

### Phase 2: Core Implementation (Days 3-7)

**Owner: Development Team**

#### 2.1 Replace Proxycurl with Coresignal

- [ ] **Task 2.1.1**: Replace ProxycurlClient with CoresignalClient

  - [ ] Replace `ProxycurlClient` class with `CoresignalClient` in `src/enrich.py`
  - [ ] Update authentication from API key to Bearer token
  - [ ] Update base URL to Coresignal API endpoints
  - [ ] Maintain same method signatures (`enrich_company`, `enrich_contact`)
  - [ ] Ensure all existing tests still pass

- [ ] **Task 2.1.2**: Update Coresignal API integration
  - [ ] Update company enrichment endpoint to use Coresignal company API
  - [ ] Update contact enrichment endpoint to use Coresignal people API
  - [ ] Map Coresignal response fields to existing data structure
  - [ ] Handle Coresignal-specific error responses and rate limits

#### 2.2 Implement Coresignal Client in enrich.py

- [ ] **Task 2.2.1**: Implement CoresignalClient class

  - [ ] Replace `ProxycurlClient` class with `CoresignalClient` in `src/enrich.py`
  - [ ] Update constructor to use `CORESIGNAL_TOKEN` environment variable
  - [ ] Update base URL to `https://api.coresignal.com`
  - [ ] Implement Bearer token authentication in headers
  - [ ] Add proper error handling and logging

- [ ] **Task 2.2.2**: Implement company enrichment method

  - [ ] Update `enrich_company(domain)` method to use Coresignal company API
  - [ ] Use endpoint `/v2/company_clean/enrich?website={domain}`
  - [ ] Map Coresignal response fields to existing company data structure
  - [ ] Handle Coresignal rate limits (100 req/min) and error responses
  - [ ] Maintain same return format for backward compatibility

- [ ] **Task 2.2.3**: Implement contact enrichment method
  - [ ] Update `enrich_contact(linkedin_url)` method to use Coresignal people API
  - [ ] Use endpoint `/v2/people/by-company-domain/{domain}` for company contacts
  - [ ] Map Coresignal response fields to existing contact data structure
  - [ ] Handle contact lookup by company domain instead of LinkedIn URL
  - [ ] Maintain same return format for backward compatibility

#### 2.3 Update Enrichment Pipeline

- [ ] **Task 2.3.1**: Update enrichment tool for Coresignal

  - [ ] Update `src/enrich.py` to use `CoresignalClient` instead of `ProxycurlClient`
  - [ ] Update environment variable references from `PROXYCURL_KEY` to `CORESIGNAL_TOKEN`
  - [ ] Update cost calculation to use Coresignal pricing
  - [ ] Maintain backward compatibility with existing data structures
  - [ ] Update error handling for Coresignal-specific error responses

- [ ] **Task 2.3.2**: Update orchestrator validation
  - [ ] Modify `src/orchestrator.py` required providers list to include `coresignal`
  - [ ] Update provider presence validation to check for Coresignal token
  - [ ] Update error messages and logging to reference Coresignal
  - [ ] Ensure Coresignal token is properly validated at startup

#### 2.4 Configuration and Environment

- [ ] **Task 2.4.1**: Update environment configuration

  - [ ] Add `CORESIGNAL_TOKEN` to `env.template`
  - [ ] Remove `PROXYCURL_KEY` from `env.template` (or mark as deprecated)
  - [ ] Update provider validation logic to check for Coresignal token
  - [ ] Add Coresignal-specific configuration options (base URL, rate limits)

- [ ] **Task 2.4.2**: Update cost configuration
  - [ ] Add Coresignal costs to `config/costs.yaml`
  - [ ] Update cost calculation logic to use Coresignal pricing
  - [ ] Remove or deprecate Proxycurl costs
  - [ ] Update budget enforcement rules for new pricing

### Phase 3: Testing & Quality Assurance (Days 8-10)

**Owner: QA Team + Development Team**

#### 3.1 Unit Testing

- [ ] **Task 3.1.1**: Test CoresignalClient implementation

  - [ ] Update existing tests to use `CoresignalClient` instead of `ProxycurlClient`
  - [ ] Test company enrichment with various domains using Coresignal API
  - [ ] Test contact enrichment with various profiles using Coresignal API
  - [ ] Test error handling and edge cases for Coresignal responses
  - [ ] Test rate limiting and retry logic for Coresignal (100 req/min)

- [ ] **Task 3.1.2**: Test Coresignal integration

  - [ ] Test Bearer token authentication
  - [ ] Test Coresignal API endpoint responses
  - [ ] Test field mapping from Coresignal to existing data structure
  - [ ] Test cost calculation accuracy with Coresignal pricing

- [ ] **Task 3.1.3**: Test integration points
  - [ ] Test enrichment tool with CoresignalClient
  - [ ] Test orchestrator validation with Coresignal token
  - [ ] Test cost tracking and metrics with new provider
  - [ ] Test error handling and logging for Coresignal-specific errors

#### 3.2 Integration Testing

- [ ] **Task 3.2.1**: End-to-end pipeline testing

  - [ ] Test complete Domain → Crawl → Enrich flow with Coresignal
  - [ ] Test with real Coresignal API (staging)
  - [ ] Test error scenarios and recovery
  - [ ] Test performance and concurrency limits (100 req/min)

- [ ] **Task 3.2.2**: Coresignal data quality validation
  - [ ] Test company enrichment data quality and completeness
  - [ ] Test contact enrichment data quality and completeness
  - [ ] Validate cost per enriched lead with Coresignal pricing
  - [ ] Document any data quality differences from Proxycurl

#### 3.3 Performance and Load Testing

- [ ] **Task 3.3.1**: Coresignal rate limit testing

  - [ ] Test Coresignal rate limits (100 req/min) thoroughly
  - [ ] Test concurrency pool behavior with rate limit constraints
  - [ ] Test retry and backoff strategies for rate limit errors
  - [ ] Test error handling under load and rate limit conditions

- [ ] **Task 3.3.2**: Cost optimization testing
  - [ ] Test cost per API call accuracy with Coresignal pricing
  - [ ] Test budget enforcement with new cost structure
  - [ ] Test cost tracking and reporting for Coresignal usage
  - [ ] Identify optimization opportunities with Coresignal data quality

### Phase 4: Deployment & Rollout (Days 11-13)

**Owner: DevOps Team + Development Team**

#### 4.1 Staging Deployment

- [ ] **Task 4.1.1**: Deploy to staging environment

  - [ ] Deploy updated `enrich.py` with CoresignalClient
  - [ ] Configure Coresignal staging credentials
  - [ ] Test with staging data
  - [ ] Validate all functionality works with Coresignal

- [ ] **Task 4.1.2**: Staging validation
  - [ ] Run full test suite with CoresignalClient
  - [ ] Test with real domains and companies
  - [ ] Validate cost calculations with Coresignal pricing
  - [ ] Check error handling and logging for Coresignal responses

#### 4.2 Production Rollout Strategy

- [ ] **Task 4.2.1**: Direct replacement rollout

  - [ ] Deploy updated `enrich.py` with CoresignalClient to production
  - [ ] Define rollback criteria and procedures (revert to Proxycurl if needed)
  - [ ] Plan monitoring and alerting for Coresignal API usage
  - [ ] Prepare customer communication about provider change

- [ ] **Task 4.2.2**: Production deployment
  - [ ] Deploy with CoresignalClient active
  - [ ] Monitor error rates and performance with new provider
  - [ ] Validate cost tracking accuracy with Coresignal pricing
  - [ ] Monitor data quality metrics and compare with previous results

#### 4.3 Monitoring and Validation

- [ ] **Task 4.3.1**: Production monitoring

  - [ ] Monitor Coresignal API error rates and types
  - [ ] Monitor cost per enriched lead with Coresignal pricing
  - [ ] Monitor Coresignal API response times
  - [ ] Monitor Coresignal rate limit usage (100 req/min)

- [ ] **Task 4.3.2**: Data quality validation
  - [ ] Compare enrichment success rates with Coresignal vs Proxycurl
  - [ ] Validate data completeness and quality with new provider
  - [ ] Monitor customer feedback on data quality changes
  - [ ] Track business metrics impact of provider change

### Phase 5: Cleanup and Documentation (Days 14-15)

**Owner: Development Team + Technical Writer**

#### 5.1 Code Cleanup

- [ ] **Task 5.1.1**: Remove Proxycurl dependencies

  - [ ] Remove Proxycurl client code from `enrich.py`
  - [ ] Remove Proxycurl configuration and environment variables
  - [ ] Clean up unused imports and references
  - [ ] Ensure CoresignalClient is the only enrichment client

- [ ] **Task 5.1.2**: Optimize Coresignal implementation
  - [ ] Optimize Coresignal client performance and error handling
  - [ ] Clean up any temporary migration code
  - [ ] Update error messages and logging for Coresignal
  - [ ] Ensure clean, maintainable code structure

#### 5.2 Documentation Updates

- [ ] **Task 5.2.1**: Update technical documentation

  - [ ] Update `README.md` with Coresignal setup and configuration
  - [ ] Update `docs/brd.md` with Coresignal provider details
  - [ ] Update `docs/tasks.md` with migration completion
  - [ ] Update API documentation and examples for Coresignal

- [ ] **Task 5.2.2**: Update operational documentation
  - [ ] Update deployment procedures for Coresignal integration
  - [ ] Update monitoring and alerting guides for Coresignal API
  - [ ] Update troubleshooting guides for Coresignal-specific issues
  - [ ] Update cost optimization guides with Coresignal pricing

#### 5.3 Knowledge Transfer

- [ ] **Task 5.3.1**: Team training and handover
  - [ ] Document lessons learned
  - [ ] Update onboarding materials
  - [ ] Conduct knowledge sharing sessions
  - [ ] Update runbooks and procedures

## Risk Mitigation

### Technical Risks

- **Data quality degradation**: Implement parallel enrichment comparison during rollout
- **Performance issues**: Monitor response times and implement caching if needed
- **Cost overruns**: Implement strict budget controls and monitoring
- **API rate limits**: Implement proper backoff and retry strategies

### Business Risks

- **Service disruption**: Maintain Proxycurl as fallback during initial rollout
- **Data accuracy**: Validate enrichment quality with business stakeholders
- **Cost increases**: Monitor and optimize API usage patterns

## Success Criteria

### Technical Success

- [ ] All tests pass (≥90% coverage maintained)
- [ ] No increase in error rates
- [ ] Performance meets or exceeds current levels
- [ ] Cost per enriched lead within acceptable range

### Business Success

- [ ] Enrichment quality maintained or improved
- [ ] No customer impact during migration
- [ ] Cost optimization opportunities identified
- [ ] Team confidence in new system

## Dependencies

### External Dependencies

- Coresignal API access and credentials
- Coresignal API documentation and support
- Team availability and capacity

### Internal Dependencies

- Existing test infrastructure
- Monitoring and alerting systems
- Deployment and CI/CD pipelines
- Cost tracking and reporting systems

## Timeline Summary

| Phase                   | Duration | Key Deliverables                                        |
| ----------------------- | -------- | ------------------------------------------------------- |
| Analysis & Planning     | 2 days   | Migration plan, API mapping, simplified approach design |
| Core Implementation     | 3 days   | CoresignalClient in enrich.py, pipeline updates         |
| Testing & QA            | 3 days   | Unit tests, integration tests, performance validation   |
| Deployment & Rollout    | 3 days   | Staging deployment, production rollout, monitoring      |
| Cleanup & Documentation | 2 days   | Code cleanup, documentation updates, knowledge transfer |

**Total Estimated Duration: 13 working days**

## Resource Requirements

### Development Team

- 1 Lead Developer (full-time)
- 1 Developer (full-time)
- 1 QA Engineer (full-time)

### Infrastructure

- Staging environment for testing
- Coresignal API access and credentials
- Monitoring and alerting tools
- Cost tracking and reporting tools

### Documentation

- Technical writer support
- API documentation access
- Migration procedure documentation

## Post-Migration Tasks

### Immediate (Week 1)

- Monitor system performance and stability
- Validate cost tracking accuracy
- Address any critical issues

### Short-term (Month 1)

- Optimize API usage patterns
- Implement caching strategies if needed
- Monitor data quality metrics

### Long-term (Quarter 1)

- Evaluate additional Coresignal features
- Plan cost optimization strategies
- Consider multi-provider strategies for redundancy

---

**Document Version**: 1.0
**Last Updated**: [Current Date]
**Next Review**: [Date + 1 week]
**Owner**: [Lead Developer Name]
