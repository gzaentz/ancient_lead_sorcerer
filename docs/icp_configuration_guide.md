# ICP Configuration Guide

## Overview

This guide explains how to configure ICP-specific settings in Lead Sorcerer. The system has been updated to be completely ICP-agnostic, removing all hardcoded industry-specific logic and replacing it with configurable options.

## What Changed

Previously, the system contained hardcoded dental-specific logic that would automatically inject keywords and patterns. This has been removed and replaced with a configuration-driven approach.

### Removed Hardcoded Elements

1. **Automatic dental keyword injection** - No more automatic addition of "dental", "healthcare", "medical" keywords
2. **Hardcoded URL patterns** - No more "dental-practice-for-sale" patterns
3. **Domain-specific shortcuts** - No more hardcoded usdentalpractices.com logic
4. **Fixed path keywords** - No more hardcoded "oral-surgeon", "endodontic" mappings

### New Configuration Options

All previously hardcoded values are now configurable through the ICP configuration JSON file.

## Configuration Structure

### Basic ICP Configuration

```json
{
  "name": "Your ICP Name",
  "icp_text": "Description of your ideal customer profile",
  "site_type": "information_database",
  "specific_urls": [
    "https://example.com/listing1",
    "https://example.com/listing2"
  ]
}
```

### Validation Configuration

```json
{
  "validation_config": {
    "industry_keywords": ["your", "industry", "keywords"],
    "company_name_keywords": ["company", "type", "keywords"]
  }
}
```

### Domain Discovery Configuration

```json
{
  "domain_discovery": {
    "url_patterns": ["/listing/", "/practice-for-sale/", "/property/"],
    "exclude_patterns": ["/admin", "/login", "/search"],
    "url_templates": [
      "https://{domain}/your-pattern/location-{n}",
      "https://{domain}/listings/item-{n}"
    ]
  }
}
```

### Path Keyword Mappings

```json
{
  "path_keyword_mappings": {
    "northwest-washington": ["northwest", "washington"],
    "philadelphia": ["philadelphia"],
    "your-pattern": ["keyword1", "keyword2"]
  }
}
```

### Demo URLs (Optional)

```json
{
  "demo_urls": {
    "example.com": [
      "https://example.com/listing1",
      "https://example.com/listing2"
    ]
  }
}
```

## Migration from Hardcoded Dental Configuration

If you were using the previous dental configuration, here's how to migrate:

### Before (Hardcoded)

The system automatically detected dental configurations and injected:

- Industry keywords: `["dental", "healthcare", "medical"]`
- Company name keywords: `["dentist", "orthodont", "oral"]`
- URL patterns: `["/dental-practice-for-sale/"]`

### After (Configurable)

Add this to your ICP configuration:

```json
{
  "validation_config": {
    "industry_keywords": ["dental", "healthcare", "medical"],
    "company_name_keywords": ["dentist", "orthodont", "oral"]
  },
  "domain_discovery": {
    "url_patterns": ["/listing/", "/practice-for-sale/", "/property/"],
    "url_templates": [
      "https://{domain}/dental-practice-for-sale/location-{n}",
      "https://{domain}/listings/practice-{n}"
    ]
  },
  "path_keyword_mappings": {
    "northwest-washington": ["northwest", "washington"],
    "philadelphia": ["philadelphia"],
    "oral-surgeon": ["oral", "surgeon"],
    "endodontic": ["endodont"],
    "south-central-pennsylvania": ["south", "central", "pennsylvania"]
  },
  "demo_urls": {
    "usdentalpractices.com": [
      "https://www.usdentalpractices.com/dental-practice-for-sale/northwest-washington-general-dentist-practice",
      "https://www.usdentalpractices.com/dental-practice-for-sale/greater-philadelphia-pa-endodontic-practice",
      "https://www.usdentalpractices.com/dental-practice-for-sale/oral-surgeon-practice-philadelphia"
    ]
  }
}
```

## Example Configurations

### SaaS Companies

```json
{
  "validation_config": {
    "industry_keywords": ["saas", "software", "technology", "cloud"],
    "company_name_keywords": ["tech", "software", "platform", "solution"]
  },
  "domain_discovery": {
    "url_patterns": ["/customers/", "/case-studies/", "/pricing/"],
    "url_templates": [
      "https://{domain}/customers/customer-{n}",
      "https://{domain}/case-studies/case-{n}"
    ]
  }
}
```

### Manufacturing Companies

```json
{
  "validation_config": {
    "industry_keywords": [
      "manufacturing",
      "industrial",
      "production",
      "factory"
    ],
    "company_name_keywords": ["manufacturing", "industrial", "factory", "plant"]
  },
  "domain_discovery": {
    "url_patterns": ["/products/", "/services/", "/locations/"],
    "url_templates": [
      "https://{domain}/products/product-{n}",
      "https://{domain}/locations/location-{n}"
    ]
  }
}
```

### E-commerce Companies

```json
{
  "validation_config": {
    "industry_keywords": ["ecommerce", "retail", "online", "shopping"],
    "company_name_keywords": ["store", "shop", "retail", "commerce"]
  },
  "domain_discovery": {
    "url_patterns": ["/products/", "/categories/", "/brands/"],
    "url_templates": [
      "https://{domain}/products/product-{n}",
      "https://{domain}/categories/category-{n}"
    ]
  }
}
```

## Benefits of the New System

1. **Flexibility**: Support any industry or business type
2. **Maintainability**: No need to modify code for new ICPs
3. **Consistency**: All ICP-specific logic is in one place
4. **Testability**: Easy to test different configurations
5. **Scalability**: Add new ICPs without code changes

## Testing Your Configuration

Use the provided test to ensure no hardcoded ICP exists:

```bash
pytest tests/test_no_hardcoded_icp.py -v
```

This test will scan your codebase and fail if any hardcoded ICP keywords are found.

## Best Practices

1. **Always use configuration files** for ICP-specific settings
2. **Never hardcode industry terms** in the source code
3. **Use descriptive names** for configuration keys
4. **Document your configuration** for team members
5. **Test with multiple ICPs** to ensure flexibility

## Troubleshooting

### Common Issues

1. **Missing validation keywords**: Add `industry_keywords` or `company_name_keywords` to `validation_config`
2. **URL patterns not working**: Check `url_patterns` and `exclude_patterns` in `domain_discovery`
3. **Path matching failing**: Configure `path_keyword_mappings` for your specific URL patterns

### Getting Help

If you encounter issues:

1. Check the configuration structure matches the examples
2. Verify all required fields are present
3. Use the test suite to catch hardcoded ICP
4. Review the sample configurations in `/config/`
