# ICP Configuration Guide

## Overview

This guide explains how to configure Ideal Customer Profile (ICP) settings for Lead Sorcerer. The system supports multiple lead generation modes while maintaining backward compatibility and following strict no-hardcoding principles.

## Lead Generation Modes

### Traditional Mode (Default)

- **Mode**: `"lead_generation_mode": "traditional"`
- **Flow**: Domain → Crawl → Enrich
- **Use Case**: Standard lead discovery and enrichment pipeline
- **Configuration**: Standard ICP configuration without Apollo-specific fields

### Apollo Mode

- **Mode**: `"lead_generation_mode": "apollo"`
- **Flow**: Apollo Search → Enrich (bypasses Domain + Crawl)
- **Use Case**: Direct lead generation using Apollo's comprehensive database
- **Configuration**: Requires complete Apollo configuration block

### Specific URLs Mode

- **Mode**: `"lead_generation_mode": "specific_urls"`
- **Flow**: Direct URL processing → Enrich
- **Use Case**: Processing known company URLs
- **Configuration**: Requires URL list in configuration

## Configuration Structure

### Basic Configuration (All Modes)

```json
{
  "name": "Your ICP Name",
  "icp_text": "Detailed description of your ideal customer profile",
  "lead_generation_mode": "traditional",
  "threshold": 0.7,
  "filtering_strict": true,
  "mode": "fast"
}
```

### Apollo-Specific Configuration

When using Apollo mode, you must include a complete Apollo configuration block:

```json
{
  "lead_generation_mode": "apollo",
  "apollo": {
    "enabled": true,
    "search": {
      "strategy": "company_first",
      "company_filters": {
        "industry": ["Technology", "Software"],
        "size": ["10-50", "51-200"],
        "location": ["San Francisco", "California"]
      },
      "person_filters": {
        "job_titles": ["CEO", "CTO", "VP Engineering"],
        "seniority": ["executive", "senior"]
      }
    },
    "enrich": {
      "enabled": true,
      "use_bulk": true,
      "batch_size": 25
    }
  }
}
```

## Critical Configuration Principles

### 1. No Hardcoding Business Parameters

**❌ FORBIDDEN**: Hardcoding business logic in source code

```python
# NEVER do this in source code
INDUSTRIES = ["technology", "healthcare", "finance"]
COMPANY_SIZES = ["1-10", "11-50", "51-200"]
JOB_TITLES = ["CEO", "CTO", "VP Engineering"]
```

**✅ REQUIRED**: Load all business parameters from configuration

```json
{
  "apollo": {
    "search": {
      "company_filters": {
        "industry": ["Technology", "Healthcare", "Finance"],
        "size": ["1-10", "11-50", "51-200"]
      },
      "person_filters": {
        "job_titles": ["CEO", "CTO", "VP Engineering"]
      }
    }
  }
}
```

### 2. Backward Compatibility

- All existing configurations continue to work without modification
- Traditional mode is the default when `lead_generation_mode` is missing
- Apollo mode requires explicit configuration and cannot be accidentally enabled

### 3. Configuration Validation

The system validates configuration integrity:

- Apollo mode requires complete Apollo configuration
- Business parameters must be loaded from ICP config, never from defaults
- Runtime assertions prevent partial or invalid configurations

## Field Mapping and Data Sources

### Company Filters

All company filter values must be loaded from your ICP configuration:

```json
{
  "apollo": {
    "search": {
      "company_filters": {
        "industry": [], // Load from your business requirements
        "size": [], // Load from your target company criteria
        "location": [], // Load from your geographic targeting
        "technologies": [], // Load from your tech stack requirements
        "funding_stage": [] // Load from your funding stage criteria
      }
    }
  }
}
```

### Person Filters

All person filter values must be loaded from your ICP configuration:

```json
{
  "apollo": {
    "search": {
      "person_filters": {
        "job_titles": [], // Load from role_priority keys
        "seniority": [], // Load from your seniority criteria
        "departments": [] // Load from your department criteria
      }
    }
  }
}
```

## Search Strategies

### Company-First Strategy

1. Search for companies matching criteria
2. Find contacts within those companies
3. Enrich both company and contact data

### Person-First Strategy

1. Search for individuals matching criteria
2. Group by company
3. Enrich company data for unique companies

## Enrichment Configuration

### Required Fields

Specify which fields must be present after enrichment:

```json
{
  "apollo": {
    "enrich": {
      "required_fields": ["email", "phone", "linkedin_url"]
    }
  }
}
```

### Bulk Operations

Enable bulk enrichment for better performance:

```json
{
  "apollo": {
    "enrich": {
      "use_bulk": true,
      "batch_size": 25
    }
  }
}
```

## Fallback Configuration

### Traditional Flow Fallback

Configure whether to fallback to traditional pipeline on Apollo failure:

```json
{
  "apollo": {
    "fallback": {
      "to_traditional_flow": false,
      "max_retries": 3
    }
  }
}
```

**Note**: Fallback to traditional flow is disabled by default to maintain clear separation between modes.

## Cost Management

### Cost Caps

Set maximum costs for different stages:

```json
{
  "caps": {
    "company_usd": 0.02,
    "contact_usd": 0.03,
    "run_usd_max": 10.0
  }
}
```

### Apollo Pricing

- 1 credit per search request
- 1 credit per enrichment request
- Bulk operations may have different pricing

## Configuration Examples

### Technology Companies

```json
{
  "name": "Tech Companies ICP",
  "lead_generation_mode": "apollo",
  "apollo": {
    "enabled": true,
    "search": {
      "strategy": "company_first",
      "company_filters": {
        "industry": ["Software", "Technology", "SaaS"],
        "size": ["10-50", "51-200", "201-1000"],
        "technologies": ["Python", "JavaScript", "Cloud"]
      }
    }
  }
}
```

### Healthcare Organizations

```json
{
  "name": "Healthcare ICP",
  "lead_generation_mode": "apollo",
  "apollo": {
    "enabled": true,
    "search": {
      "strategy": "company_first",
      "company_filters": {
        "industry": ["Healthcare", "Medical", "Pharmaceuticals"],
        "size": ["51-200", "201-1000", "1001-5000"]
      }
    }
  }
}
```

## Validation and Testing

### Configuration Validation

- Use the extended schema (`schemas/extended_icp_config.json`) for validation
- Ensure all required fields are present for your chosen mode
- Validate business parameters are appropriate for your ICP

### Testing Configuration

1. Test with small result sets first
2. Verify Apollo API access and rate limits
3. Monitor costs and adjust caps as needed
4. Validate data quality meets your requirements

## Troubleshooting

### Common Issues

1. **Missing Apollo Configuration**

   - Error: "Apollo mode enabled but apollo config missing"
   - Solution: Add complete Apollo configuration block

2. **Invalid Business Parameters**

   - Error: "Invalid filter values"
   - Solution: Ensure all filter values are loaded from your business requirements

3. **Rate Limiting**

   - Error: "Rate limit exceeded"
   - Solution: Adjust batch sizes and add delays between requests

4. **Cost Exceeded**
   - Error: "Cost cap exceeded"
   - Solution: Adjust cost caps or reduce result limits

## Best Practices

1. **Start Small**: Begin with conservative limits and expand
2. **Monitor Costs**: Track API usage and adjust accordingly
3. **Validate Data**: Ensure Apollo data meets your quality standards
4. **Test Thoroughly**: Validate configuration before production use
5. **Document Changes**: Keep track of configuration modifications

## Migration from Traditional Mode

To migrate from traditional to Apollo mode:

1. **Backup Configuration**: Save your current configuration
2. **Add Apollo Block**: Include complete Apollo configuration
3. **Set Mode**: Change `lead_generation_mode` to `"apollo"`
4. **Test Thoroughly**: Validate with small datasets first
5. **Monitor Performance**: Ensure results meet expectations

## Support and Resources

- **Schema Files**: `schemas/extended_icp_config.json`
- **Example Configs**: `config/apollo_example_icp.json`
- **Documentation**: This guide and related technical docs
- **Validation**: Use schema validation tools for configuration integrity

Remember: **Never hardcode business parameters in source code. All business logic must be loaded from configuration files.**
