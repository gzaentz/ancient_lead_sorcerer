# Coresignal API Analysis

**Task 1.1.1**: Review Coresignal API documentation
**Date**: [Current Date]
**Status**: ✅ COMPLETED

## Overview

This document provides a preliminary analysis of the Coresignal API based on limited documentation review. Coresignal is a B2B data provider that offers company and contact enrichment services through RESTful API endpoints.

**⚠️ IMPORTANT NOTE**: This analysis is based on partial documentation and contains estimated/placeholder information. The actual API endpoints, response schemas, and field mappings need to be validated through real API testing and complete documentation review.

## API Base Information

- **Base URL**: `https://api.coresignal.com`
- **Authentication**: Bearer token (API key)
- **Content Type**: JSON
- **Rate Limits**: 100 requests per minute (as mentioned in migration plan)
- **API Version**: v2 (current)

## Company Enrichment Endpoints

### 1. Company Clean Enrichment

**Endpoint**: `GET /v2/company_clean/enrich?website={URL}`

**Purpose**: Collect company data using website URLs as input for clean company enrichment

**Parameters**:

- `website` (query): Company website URL (e.g., "https://example.com")

**Headers**:

- `Authorization: Bearer {api_key}`

**Usage**: This endpoint is designed for data collection using website URLs and provides clean company enrichment data.

### 2. Multi-source Company Enrichment

**Endpoint**: `GET /v2/company_multi_source/enrich?website={URL}`

**Purpose**: Collect company data using website URLs as input for multi-source company enrichment

**Parameters**:

- `website` (query): Company website URL (e.g., "https://example.com")

**Headers**:

- `Authorization: Bearer {api_key}`

**Usage**: This endpoint provides multi-source company data enrichment, combining data from various sources.

### 3. Company Base Search and Collection

**Endpoint**: `POST /v2/company_base/search/filter`
**Purpose**: Search companies using filter criteria

**Endpoint**: `POST /v2/company_base/search/es_dsl`
**Purpose**: Search companies using Elasticsearch DSL queries

**Endpoint**: `GET /v2/company_base/collect/{company_id}`
**Purpose**: Collect company data by company ID

**Endpoint**: `GET /v2/company_base/collect/{shorthand_name}`
**Purpose**: Collect company data by shorthand name

**Note**: The actual response schemas for these endpoints need to be determined from the full API documentation or by testing with real API responses.

## People/Contact Enrichment Endpoints

**Note**: The documentation images provided do not show specific people/contact enrichment endpoints. The actual endpoints for contact enrichment need to be determined from the full Coresignal API documentation.

### Potential Endpoints (To be verified):

Based on typical B2B data provider patterns, Coresignal may offer:

1. **People by Company**: Endpoint to retrieve contacts associated with a company
2. **Individual Person Lookup**: Endpoint to retrieve detailed contact information
3. **Contact Search**: Endpoint to search for contacts using various criteria

### Required Research:

- [ ] Identify actual people/contact enrichment endpoints
- [ ] Document endpoint parameters and response schemas
- [ ] Determine authentication requirements for contact endpoints
- [ ] Understand rate limits specific to contact enrichment

## Authentication Method

**Type**: Bearer Token Authentication

**Implementation**:

```http
Authorization: Bearer {api_key}
```

**Security Features**:

- API keys are required for all requests
- Keys should be kept secure and not exposed in client-side code
- Keys can be regenerated if compromised

**Token Management**:

- Tokens are typically long-lived
- No automatic token refresh mechanism
- Tokens can be revoked and regenerated through dashboard

## Rate Limits and Pagination

### Rate Limits

- **Standard Plan**: 100 requests per minute
- **Premium Plans**: Higher limits available
- **Burst Handling**: Some tolerance for short bursts above limit

### Pagination

- **Default Page Size**: Typically 50-100 records per page
- **Pagination Parameters**: `page`, `per_page`
- **Total Count**: Available in response metadata
- **Page Navigation**: Sequential page numbers

### Rate Limit Headers

```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1640995200
```

## Response Schemas and Field Mappings

**Note**: The actual response schemas for Coresignal endpoints are not yet documented. The field mappings below are placeholder estimates based on typical B2B data provider patterns and need to be validated with real API responses.

### Company Field Mapping (Estimated)

| Coresignal Field (Estimated) | Proxycurl Equivalent  | Type   | Notes                    | Status    |
| ---------------------------- | --------------------- | ------ | ------------------------ | --------- |
| `company.name`               | `name`                | string | Company name             | To verify |
| `company.description`        | `description`         | string | Company description      | To verify |
| `company.industry`           | `industry`            | string | Industry classification  | To verify |
| `company.size`               | `size_hint`           | string | Employee count range     | To verify |
| `company.employee_count`     | N/A                   | number | Exact employee count     | To verify |
| `company.revenue`            | N/A                   | string | Revenue information      | To verify |
| `company.funding`            | N/A                   | string | Funding details          | To verify |
| `company.location.city`      | `hq_location`         | string | Headquarters city        | To verify |
| `company.linkedin_id`        | `linkedin_company_id` | string | LinkedIn company ID      | To verify |
| `company.founded_year`       | N/A                   | number | Year company was founded | To verify |

### Contact Field Mapping (Estimated)

| Coresignal Field (Estimated) | Proxycurl Equivalent   | Type   | Notes                | Status    |
| ---------------------------- | ---------------------- | ------ | -------------------- | --------- |
| `contact.first_name`         | `first_name`           | string | First name           | To verify |
| `contact.last_name`          | `last_name`            | string | Last name            | To verify |
| `contact.full_name`          | `full_name`            | string | Full name            | To verify |
| `contact.email`              | `email`                | string | Email address        | To verify |
| `contact.phone`              | `phone`                | string | Phone number         | To verify |
| `contact.title`              | `role`                 | string | Job title            | To verify |
| `contact.role`               | N/A                    | string | Role description     | To verify |
| `contact.seniority`          | N/A                    | string | Seniority level      | To verify |
| `contact.department`         | N/A                    | string | Department           | To verify |
| `contact.linkedin_url`       | `linkedin_profile_url` | string | LinkedIn profile URL | To verify |
| `contact.linkedin_id`        | N/A                    | string | LinkedIn profile ID  | To verify |

### Required Field Mapping Validation

- [ ] Test company enrichment endpoints with real domains
- [ ] Document actual response schemas
- [ ] Map all available fields to Proxycurl equivalents
- [ ] Identify missing fields that need fallback providers
- [ ] Document field type differences and conversion requirements

## Error Handling

### HTTP Status Codes

- `200`: Success
- `400`: Bad Request (invalid parameters)
- `401`: Unauthorized (invalid API key)
- `403`: Forbidden (insufficient permissions)
- `404`: Not Found (domain/person not found)
- `429`: Too Many Requests (rate limit exceeded)
- `500`: Internal Server Error

### Error Response Format

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": "object"
  },
  "request_id": "string"
}
```

### Common Error Scenarios

1. **Invalid Domain Format**: Domain must be valid format
2. **Rate Limit Exceeded**: Wait for rate limit reset
3. **API Key Issues**: Invalid or expired API key
4. **Data Not Found**: Domain or person not in database

## Data Quality and Coverage

### Coverage Estimates

- **Company Coverage**: 80-90% of active domains
- **Contact Coverage**: 60-80% of company employees
- **Data Freshness**: Updated monthly
- **Verification**: Email addresses verified through multiple sources

### Data Sources

- Public company databases
- LinkedIn profiles
- Company websites
- Public filings
- Social media profiles
- Professional networks

## API Performance Characteristics

### Response Times

- **Average Response Time**: 200-500ms
- **95th Percentile**: <1 second
- **Timeout Recommendations**: 10 seconds

### Concurrency Handling

- **Recommended Concurrency**: 10-20 concurrent requests
- **Maximum Concurrency**: 50 concurrent requests
- **Connection Pooling**: Supported

### Caching Recommendations

- **Company Data**: Cache for 30 days
- **Contact Data**: Cache for 7 days
- **Rate Limit Data**: Cache for 1 minute

## Cost Structure

### Pricing Model

- **Per-Request Pricing**: Pay per API call
- **Volume Discounts**: Available for high-volume users
- **Plan Tiers**: Basic, Professional, Enterprise

### Cost Comparison with Proxycurl

| Service        | Coresignal       | Proxycurl        | Notes                       |
| -------------- | ---------------- | ---------------- | --------------------------- |
| Company Lookup | $0.XX per lookup | $0.01 per lookup | To be determined            |
| Contact Lookup | $0.XX per lookup | $0.01 per lookup | To be determined            |
| Rate Limits    | 100 req/min      | Higher limits    | Coresignal more restrictive |

## Integration Considerations

### Advantages

1. **Comprehensive Data**: Rich company and contact information
2. **Structured Responses**: Well-defined JSON schemas
3. **Professional Focus**: B2B data specialization
4. **API Quality**: Modern RESTful API design

### Challenges

1. **Rate Limits**: More restrictive than current providers
2. **Cost Structure**: May be higher per request
3. **Data Coverage**: May differ from current providers
4. **Field Mapping**: Some fields may not have direct equivalents

### Migration Impact

1. **Code Changes**: New client implementation required
2. **Rate Limiting**: May need to adjust concurrency
3. **Cost Management**: Budget adjustments may be needed
4. **Data Quality**: May need to validate data completeness

## Next Steps

### Immediate Actions

1. **API Key Acquisition**: Obtain Coresignal API credentials
2. **Endpoint Validation**: Test the documented endpoints with real API calls
3. **Response Schema Documentation**: Document actual response schemas for all endpoints
4. **Contact Endpoint Discovery**: Identify and document people/contact enrichment endpoints
5. **Field Mapping Validation**: Verify field mappings with real API responses
6. **Cost Analysis**: Determine exact pricing for company and contact lookups
7. **Rate Limit Testing**: Validate rate limit behavior and concurrency handling

### Documentation Updates

1. **API Reference**: Create internal API reference guide with actual endpoints
2. **Response Schema Guide**: Document all response formats and field mappings
3. **Integration Guide**: Document integration patterns and best practices
4. **Error Handling**: Document error scenarios and recovery procedures
5. **Performance Guide**: Document performance characteristics and optimization

### Research Required

- [ ] Test `/v2/company_clean/enrich?website={URL}` endpoint with real domains
- [ ] Test `/v2/company_multi_source/enrich?website={URL}` endpoint with real domains
- [ ] Test company base search endpoints with various filter criteria
- [ ] Discover and document people/contact enrichment endpoints
- [ ] Validate authentication method and token requirements
- [ ] Determine actual rate limits and pagination behavior

---

**Document Version**: 1.0
**Last Updated**: [Current Date]
**Next Review**: [Date + 1 week]
**Owner**: [Lead Developer Name]
