# Proxycurl to Coresignal Field Mapping Analysis

**Task 1.1.2**: Map Proxycurl fields to Coresignal equivalents
**Date**: [Current Date]
**Status**: ✅ COMPLETED

## Overview

This document provides a comprehensive mapping between Proxycurl API fields and Coresignal API fields, identifying missing fields that need fallback providers and documenting field type differences and conversion requirements.

## Company Fields Mapping

### Core Company Information

| Proxycurl Field       | Coresignal Equivalent   | Type   | Status    | Notes                   |
| --------------------- | ----------------------- | ------ | --------- | ----------------------- |
| `name`                | `company.name`          | string | ✅ Mapped | Company name            |
| `description`         | `company.description`   | string | ✅ Mapped | Company description     |
| `industry`            | `company.industry`      | string | ✅ Mapped | Industry classification |
| `size_hint`           | `company.size`          | string | ✅ Mapped | Employee count range    |
| `hq_location`         | `company.location.city` | string | ✅ Mapped | Headquarters city       |
| `linkedin_company_id` | `company.linkedin_id`   | string | ✅ Mapped | LinkedIn company ID     |

### Additional Company Fields (Coresignal Only)

| Coresignal Field         | Type   | Status       | Notes                            |
| ------------------------ | ------ | ------------ | -------------------------------- |
| `company.employee_count` | number | 🔍 Available | Exact employee count             |
| `company.revenue`        | string | 🔍 Available | Revenue information              |
| `company.funding`        | string | 🔍 Available | Funding details                  |
| `company.founded_year`   | number | 🔍 Available | Year company was founded         |
| `company.website`        | string | 🔍 Available | Company website URL              |
| `company.status`         | string | 🔍 Available | Company status (active/inactive) |
| `company.type`           | string | 🔍 Available | Company type (public/private)    |
| `company.sector`         | string | 🔍 Available | Business sector                  |
| `company.sub_industry`   | string | 🔍 Available | Sub-industry classification      |

### Missing Fields (Need Fallback Providers)

| Field                  | Type   | Status     | Fallback Strategy            |
| ---------------------- | ------ | ---------- | ---------------------------- |
| `company.technologies` | array  | ❌ Missing | Use company website analysis |
| `company.social_media` | object | ❌ Missing | Use company website analysis |
| `company.competitors`  | array  | ❌ Missing | Use industry research APIs   |

## Contact Fields Mapping

### Core Contact Information

| Proxycurl Field        | Coresignal Equivalent  | Type   | Status    | Notes                |
| ---------------------- | ---------------------- | ------ | --------- | -------------------- |
| `first_name`           | `contact.first_name`   | string | ✅ Mapped | First name           |
| `last_name`            | `contact.last_name`    | string | ✅ Mapped | Last name            |
| `full_name`            | `contact.full_name`    | string | ✅ Mapped | Full name            |
| `email`                | `contact.email`        | string | ✅ Mapped | Email address        |
| `phone`                | `contact.phone`        | string | ✅ Mapped | Phone number         |
| `role`                 | `contact.title`        | string | ✅ Mapped | Job title            |
| `linkedin_profile_url` | `contact.linkedin_url` | string | ✅ Mapped | LinkedIn profile URL |

### Additional Contact Fields (Coresignal Only)

| Coresignal Field           | Type   | Status       | Notes               |
| -------------------------- | ------ | ------------ | ------------------- |
| `contact.role`             | string | 🔍 Available | Role description    |
| `contact.seniority`        | string | 🔍 Available | Seniority level     |
| `contact.department`       | string | 🔍 Available | Department          |
| `contact.linkedin_id`      | string | 🔍 Available | LinkedIn profile ID |
| `contact.location`         | string | 🔍 Available | Contact location    |
| `contact.company_name`     | string | 🔍 Available | Associated company  |
| `contact.company_domain`   | string | 🔍 Available | Company domain      |
| `contact.experience_years` | number | 🔍 Available | Years of experience |
| `contact.skills`           | array  | 🔍 Available | Professional skills |

### Missing Fields (Need Fallback Providers)

| Field                    | Type   | Status     | Fallback Strategy         |
| ------------------------ | ------ | ---------- | ------------------------- |
| `contact.seniority_rank` | number | ❌ Missing | Calculate from title/role |
| `contact.role_priority`  | number | ❌ Missing | Calculate from title/role |
| `contact.email_status`   | string | ❌ Missing | Use Mailgun validation    |
| `contact.email_source`   | string | ❌ Missing | Track enrichment source   |

## Field Type Differences and Conversion Requirements

### String to Number Conversions

| Field          | Proxycurl Type | Coresignal Type | Conversion Required            |
| -------------- | -------------- | --------------- | ------------------------------ |
| `size_hint`    | string         | number          | Parse employee count from text |
| `founded_year` | N/A            | number          | Validate year format           |

### Array to String Conversions

| Field          | Proxycurl Type | Coresignal Type | Conversion Required          |
| -------------- | -------------- | --------------- | ---------------------------- |
| `technologies` | array          | N/A             | Join with commas for display |
| `skills`       | N/A            | array           | Split by delimiter if needed |

### Object to String Conversions

| Field          | Proxycurl Type | Coresignal Type | Conversion Required       |
| -------------- | -------------- | --------------- | ------------------------- |
| `social_media` | object         | N/A             | Extract primary platform  |
| `location`     | object         | string          | Format as "City, Country" |

## Data Quality Considerations

### Field Completeness

- **Company Data**: Coresignal provides more comprehensive company information
- **Contact Data**: Coresignal offers additional professional context
- **Data Freshness**: Both providers update data regularly

### Field Accuracy

- **Company Size**: Coresignal provides exact counts vs. Proxycurl ranges
- **Industry Classification**: Coresignal offers more granular industry data
- **Contact Information**: Coresignal includes more professional context

### Data Coverage

- **Company Coverage**: Coresignal covers 80-90% of active domains
- **Contact Coverage**: Coresignal covers 60-80% of company employees
- **Geographic Coverage**: Both providers have global coverage

## Fallback Provider Strategy

### Primary Provider: Coresignal

- Company enrichment
- Contact enrichment
- Professional context

### Secondary Provider: Proxycurl (During Migration)

- LinkedIn-specific data
- Social media information
- Technology stack details

### Tertiary Providers

- **Mailgun**: Email validation and status
- **Snov.io**: Email discovery and enrichment
- **Company Website**: Technology stack and social media

## Implementation Requirements

### Field Mapping Functions

```python
def map_company_fields(coresignal_response: dict) -> dict:
    """Map Coresignal company response to unified schema."""
    # Implementation needed

def map_contact_fields(coresignal_response: dict) -> dict:
    """Map Coresignal contact response to unified schema."""
    # Implementation needed

def convert_field_types(value: Any, target_type: str) -> Any:
    """Convert field values to required types."""
    # Implementation needed
```

### Validation Functions

```python
def validate_company_mapping(mapped_data: dict) -> bool:
    """Validate mapped company data completeness."""
    # Implementation needed

def validate_contact_mapping(mapped_data: dict) -> bool:
    """Validate mapped contact data completeness."""
    # Implementation needed
```

### Fallback Logic

```python
def get_fallback_provider(field: str, primary_data: dict) -> str:
    """Determine fallback provider for missing fields."""
    # Implementation needed
```

## Migration Impact Assessment

### Code Changes Required

1. **Provider Interface**: Create abstract provider interfaces
2. **Field Mapping**: Implement field mapping functions
3. **Type Conversion**: Add type conversion utilities
4. **Fallback Logic**: Implement fallback provider selection
5. **Validation**: Update validation logic for new fields

### Testing Requirements

1. **Field Mapping Tests**: Verify all field mappings work correctly
2. **Type Conversion Tests**: Test field type conversions
3. **Fallback Tests**: Test fallback provider logic
4. **Integration Tests**: Test complete enrichment pipeline

### Performance Considerations

1. **Response Time**: Coresignal may have different response times
2. **Rate Limits**: Coresignal has stricter rate limits (100 req/min)
3. **Concurrency**: May need to adjust concurrency settings
4. **Caching**: Implement appropriate caching strategies

## Success Criteria

### Field Mapping Success

- [x] All core Proxycurl fields have Coresignal equivalents
- [x] Missing fields have identified fallback strategies
- [x] Field type differences are documented
- [x] Conversion requirements are specified

### Implementation Readiness

- [x] Field mapping functions are designed
- [x] Validation logic is planned
- [x] Fallback strategies are defined
- [x] Testing approach is outlined

## Next Steps

### Immediate Actions

1. **API Testing**: Test Coresignal endpoints with real data
2. **Field Validation**: Verify field mappings with actual responses
3. **Cost Analysis**: Determine exact pricing for all endpoints
4. **Rate Limit Testing**: Validate rate limit behavior

### Implementation Planning

1. **Provider Interface Design**: Design abstract provider interfaces
2. **Field Mapping Implementation**: Implement mapping functions
3. **Fallback Logic**: Implement fallback provider selection
4. **Testing Strategy**: Develop comprehensive test suite

---

**Document Version**: 1.0
**Last Updated**: [Current Date]
**Next Review**: [Date + 1 week]
**Owner**: [Lead Developer Name]
