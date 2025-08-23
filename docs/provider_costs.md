# Enrichment Provider Cost Guide

_Last updated: 2025-08-23_

This document provides comprehensive cost information for all enrichment providers used in the Lead Sorcerer system.

## Overview

The enrichment system uses a tier-based architecture to optimize costs while maintaining high-quality data. Primary providers (TIER_0) are used for most operations, with fallback to secondary (TIER_1) and legacy (TIER_2) providers when needed.

## Cost Structure

### Primary Providers (TIER_0)

#### CompanyEnrich

- **Company Enrichment**: $0.01 per company
- **Contact Enrichment**: $0.02 per contact list
- **Email Finding**: $0.015 per email lookup
- **Features**: Company data, contact discovery, email verification
- **Best For**: High-quality company and contact data

#### Anymail Finder

- **Company Enrichment**: $0.008 per company
- **Contact Enrichment**: $0.015 per contact list
- **Email Finding**: $0.012 per email lookup
- **Features**: Email discovery, contact verification, company data
- **Best For**: Email discovery and verification

### Legacy Providers (TIER_2)

#### Coresignal

- **Company Enrichment**: Free (limited data)
- **Contact Enrichment**: Not supported
- **Email Finding**: Not supported
- **Features**: Basic company information
- **Best For**: Fallback company data when budget is constrained

#### Snovio

- **Company Enrichment**: Not supported
- **Contact Enrichment**: $0.01 per contact
- **Email Finding**: Not supported
- **Features**: Contact discovery and enrichment
- **Best For**: Fallback contact data

## Cost Optimization Strategies

### 1. Tier-Based Routing

- Primary providers handle 80% of requests
- Legacy providers serve as cost-effective fallbacks
- Automatic failover reduces total cost per lead

### 2. Batch Processing

- Group enrichment requests to minimize API calls
- Use provider-specific batch limits for optimal pricing
- Implement intelligent caching to avoid duplicate requests

### 3. Provider Selection

- Route company enrichment to CompanyEnrich (best value)
- Use Anymail Finder for email discovery (specialized)
- Fall back to legacy providers only when necessary

## Cost Per Lead Calculation

### Typical Enrichment Pipeline

1. **Company Enrichment**: $0.01 (CompanyEnrich)
2. **Contact Discovery**: $0.02 (CompanyEnrich)
3. **Email Verification**: $0.015 (CompanyEnrich)
4. **Total per lead**: $0.045

### With Fallback Scenarios

- **Primary success**: $0.045 per lead
- **Primary + fallback**: $0.055 per lead
- **Legacy only**: $0.02 per lead (limited data)

## Budget Management

### Daily Cost Caps

- **Default**: $50.00 per day
- **High-volume**: $200.00 per day
- **Enterprise**: $500.00+ per day

### Monthly Budgets

- **Starter**: $500/month (≈11,000 leads)
- **Professional**: $2,000/month (≈44,000 leads)
- **Enterprise**: $10,000/month (≈220,000 leads)

## Provider Performance Metrics

### Success Rates

- **CompanyEnrich**: 95% success rate
- **Anymail Finder**: 92% success rate
- **Coresignal**: 85% success rate
- **Snovio**: 88% success rate

### Response Times

- **CompanyEnrich**: 200-500ms
- **Anymail Finder**: 300-800ms
- **Coresignal**: 1-3 seconds
- **Snovio**: 2-5 seconds

### Data Quality Scores

- **CompanyEnrich**: 9.2/10
- **Anymail Finder**: 8.8/10
- **Coresignal**: 7.5/10
- **Snovio**: 8.0/10

## Cost Monitoring

### Real-Time Tracking

- All enrichment costs are logged in real-time
- Cost breakdown by provider and operation type
- Budget alerts when approaching limits

### Reporting

- Daily cost summaries
- Monthly provider cost analysis
- Cost per lead trends
- ROI calculations

## Provider-Specific Considerations

### CompanyEnrich

- **Strengths**: Comprehensive company data, high accuracy
- **Limitations**: Rate limits (1000 requests/hour)
- **Best Use**: Primary company enrichment

### Anymail Finder

- **Strengths**: Email discovery, verification
- **Limitations**: Contact data may be limited
- **Best Use**: Email finding and verification

### Coresignal

- **Strengths**: Free, basic company data
- **Limitations**: Limited data depth, slower response
- **Best Use**: Budget-constrained fallback

### Snovio

- **Strengths**: Contact discovery, LinkedIn integration
- **Limitations**: No company data, slower response
- **Best Use**: Contact enrichment fallback

## Cost Reduction Tips

1. **Implement Smart Caching**

   - Cache company data for 30 days
   - Cache contact data for 14 days
   - Use domain-based deduplication

2. **Optimize Request Patterns**

   - Batch similar requests
   - Use provider-specific features efficiently
   - Implement intelligent retry logic

3. **Monitor and Adjust**
   - Track success rates by provider
   - Adjust tier assignments based on performance
   - Regular cost analysis and optimization

## Future Cost Considerations

### Planned Improvements

- **Bulk pricing**: Negotiate volume discounts
- **Provider consolidation**: Reduce redundant services
- **Automated optimization**: ML-based provider selection

### Cost Trends

- **API costs**: Generally decreasing over time
- **Data quality**: Improving, may justify higher costs
- **Competition**: New providers entering market

## Support and Billing

### Provider Support

- **CompanyEnrich**: 24/7 email support
- **Anymail Finder**: Business hours support
- **Coresignal**: Community support
- **Snovio**: Email support

### Billing Cycles

- **CompanyEnrich**: Monthly
- **Anymail Finder**: Monthly
- **Coresignal**: Free
- **Snovio**: Monthly

### Payment Methods

- Credit card (primary)
- ACH transfer (enterprise)
- Invoice billing (enterprise)

---

**Note**: All costs are in USD and subject to change. Check provider websites for current pricing.
