# LLM Contact Selection - Maintenance Procedures

_Last updated: 2025-01-27_

## Overview

This document provides comprehensive maintenance procedures for the LLM-based contact selection system. It covers monitoring, optimization, troubleshooting, and update procedures to ensure optimal system performance.

## Table of Contents

1. [Daily Monitoring](#daily-monitoring)
2. [Weekly Performance Review](#weekly-performance-review)
3. [Monthly Optimization](#monthly-optimization)
4. [Incident Response](#incident-response)
5. [Prompt Updates](#prompt-updates)
6. [API Change Management](#api-change-management)
7. [Cost Management](#cost-management)
8. [Quality Assurance](#quality-assurance)

## Daily Monitoring

### Automated Health Checks

**Frequency**: Every hour during business hours

**Metrics to Monitor**:

```bash
# Check LLM system health
python -c "
from src.enrich import get_llm_monitoring_summary
summary = get_llm_monitoring_summary()
print(f'Success Rate: {summary[\"calculated_metrics\"][\"success_rate_percent\"]}%')
print(f'Fallback Rate: {summary[\"calculated_metrics\"][\"fallback_rate_percent\"]}%')
print(f'Cache Hit Rate: {summary[\"calculated_metrics\"][\"cache_hit_rate_percent\"]}%')
"
```

**Alert Thresholds**:

- Success Rate < 90%: **WARNING**
- Success Rate < 80%: **CRITICAL**
- Fallback Rate > 15%: **WARNING**
- Fallback Rate > 25%: **CRITICAL**
- Cache Hit Rate < 20%: **OPTIMIZATION NEEDED**

### Daily Checklist

- [ ] Verify LLM service availability
- [ ] Check error logs for patterns
- [ ] Review cost accumulation
- [ ] Monitor response times
- [ ] Validate selection quality (sample review)

### Log Analysis

**Check for common error patterns**:

```bash
# Check recent LLM errors
grep -i "llm.*error\|failed to load prompt\|invalid response" data/logs/enrich_$(date +%Y%m%d).log | tail -20

# Check fallback frequency
grep -i "fallback.*rule.based" data/logs/enrich_$(date +%Y%m%d).log | wc -l
```

**Key Log Patterns to Watch**:

- `"❌ Failed to load prompt template"`: Template loading issues
- `"⚠️ LLM selection failed, using fallback"`: LLM API issues
- `"Invalid JSON response from LLM"`: Response parsing problems
- `"Contact ID not found in contacts list"`: Selection quality issues

## Weekly Performance Review

### Performance Analysis

**Run weekly performance report**:

```python
#!/usr/bin/env python3
"""Weekly LLM Performance Report"""

import json
from datetime import datetime, timedelta
from src.enrich import get_llm_performance_metrics, get_llm_monitoring_summary

def generate_weekly_report():
    summary = get_llm_monitoring_summary()
    performance = summary['performance_metrics']
    calculated = summary['calculated_metrics']

    report = {
        "report_date": datetime.now().isoformat(),
        "period": "7 days",
        "key_metrics": {
            "total_selections": performance['total_calls'],
            "success_rate": f"{calculated['success_rate_percent']}%",
            "fallback_rate": f"{calculated['fallback_rate_percent']}%",
            "cache_efficiency": f"{calculated['cache_hit_rate_percent']}%",
            "avg_response_time": f"{performance['average_response_time_ms']}ms"
        },
        "error_breakdown": {
            "timeout_errors": performance['timeout_errors'],
            "rate_limit_errors": performance['rate_limit_errors'],
            "server_errors": performance['server_errors'],
            "invalid_responses": performance['invalid_responses']
        },
        "recommendations": []
    }

    # Add recommendations based on metrics
    if calculated['success_rate_percent'] < 95:
        report['recommendations'].append("Investigate and address LLM reliability issues")

    if calculated['fallback_rate_percent'] > 10:
        report['recommendations'].append("Review prompt templates and LLM configuration")

    if calculated['cache_hit_rate_percent'] < 30:
        report['recommendations'].append("Analyze caching patterns and consider TTL adjustment")

    if performance['average_response_time_ms'] > 3000:
        report['recommendations'].append("Optimize prompts or consider model change for better performance")

    return report

# Generate and save report
report = generate_weekly_report()
with open(f"reports/llm_weekly_report_{datetime.now().strftime('%Y%m%d')}.json", 'w') as f:
    json.dump(report, f, indent=2)

print("Weekly report generated:", json.dumps(report, indent=2))
```

### Review Checklist

- [ ] Analyze success/failure trends
- [ ] Review cost trends and budget impact
- [ ] Examine selection quality samples
- [ ] Check for new error patterns
- [ ] Evaluate cache efficiency
- [ ] Review model performance
- [ ] Document any issues or improvements

### Quality Sampling

**Weekly quality review procedure**:

1. **Extract sample selections**:

```bash
# Get recent enrichment results with LLM selections
grep -A 5 -B 5 "llm_contact_selection" data/exports/*/leads.jsonl | head -50 > weekly_llm_samples.txt
```

2. **Manual review criteria**:

   - Does selected contact match ICP criteria?
   - Is the selection better than rule-based alternative?
   - Are there obvious better choices in the contact list?
   - Is the business context properly understood?

3. **Quality scoring**:
   - **Excellent** (5): Perfect selection, clearly best choice
   - **Good** (4): Appropriate selection, minor issues
   - **Acceptable** (3): Reasonable selection, some questions
   - **Poor** (2): Questionable selection, better alternatives
   - **Bad** (1): Wrong selection, misunderstood criteria

## Monthly Optimization

### Performance Optimization Review

**Monthly optimization checklist**:

1. **Model Performance Analysis**

   ```python
   # Analyze model performance by ICP type
   def analyze_icp_performance():
       # Group metrics by ICP type
       # Compare success rates across ICP types
       # Identify underperforming configurations
       pass
   ```

2. **Prompt Effectiveness Review**

   - Compare selection quality across different prompt templates
   - A/B test prompt variations for specific ICP types
   - Update prompts based on quality feedback

3. **Configuration Optimization**

   - Review temperature settings for each ICP type
   - Optimize max_tokens based on actual usage
   - Adjust timeout values based on response time data

4. **Cache Optimization**
   - Analyze cache hit patterns
   - Adjust TTL based on data freshness requirements
   - Review cache size limits

### Cost Optimization

**Monthly cost review**:

```python
#!/usr/bin/env python3
"""Monthly Cost Analysis"""

def monthly_cost_analysis():
    # Analyze cost trends
    # Cost per selection by ICP type
    # Cache savings calculation
    # ROI analysis vs rule-based system
    # Budget variance analysis
    pass
```

**Cost optimization strategies**:

- Increase cache TTL if data freshness allows
- Optimize prompt length to reduce token usage
- Consider model alternatives for cost-sensitive ICPs
- Implement request batching where possible

## Incident Response

### LLM Service Outage

**Immediate Actions** (0-15 minutes):

1. Verify fallback system is functioning
2. Check OpenRouter service status
3. Confirm API key validity
4. Monitor fallback success rates

**Short-term Actions** (15-60 minutes):

1. Investigate root cause
2. Contact OpenRouter support if needed
3. Consider alternative models if available
4. Communicate status to stakeholders

**Recovery Actions**:

1. Validate service restoration
2. Reset metrics for clean monitoring
3. Analyze incident impact
4. Document lessons learned

### High Fallback Rate

**Investigation steps**:

1. Check recent error patterns in logs
2. Verify prompt template integrity
3. Test with sample contact lists
4. Review recent configuration changes

**Common causes and solutions**:

- **Rate limiting**: Implement request throttling
- **Invalid prompts**: Validate template format
- **Model issues**: Switch to fallback model temporarily
- **Network issues**: Check connectivity and DNS

### Poor Selection Quality

**Investigation process**:

1. Sample recent selections for manual review
2. Compare with rule-based selections
3. Analyze prompt effectiveness
4. Check ICP configuration alignment

**Remediation steps**:

1. Update prompt templates if needed
2. Adjust model parameters (temperature, tokens)
3. Improve ICP text descriptions
4. Consider additional training examples

## Prompt Updates

### Update Process

**1. Development Phase**:

```bash
# Create prompt variant
cp config/prompts/investment_contact_selection.txt config/prompts/investment_contact_selection_v2.txt

# Edit new version
vim config/prompts/investment_contact_selection_v2.txt
```

**2. Testing Phase**:

```python
# Test new prompt with sample data
from src.enrich import LLMContactSelector

# Compare old vs new prompt performance
selector_old = LLMContactSelector("api_key", "investment")
selector_new = LLMContactSelector("api_key", "investment", {
    "llm_config": {"prompt_template": "investment_contact_selection_v2.txt"}
})

# Run A/B tests with sample contact lists
```

**3. Validation Phase**:

- Test with representative contact samples
- Verify JSON response format
- Validate business logic alignment
- Check for improved selection quality

**4. Deployment Phase**:

```bash
# Backup current version
cp config/prompts/investment_contact_selection.txt config/prompts/investment_contact_selection_backup.txt

# Deploy new version
mv config/prompts/investment_contact_selection_v2.txt config/prompts/investment_contact_selection.txt
```

**5. Monitoring Phase**:

- Monitor selection quality for 48 hours
- Track success rates and fallback frequency
- Gather user feedback
- Be ready to rollback if needed

### Version Control

**Prompt versioning system**:

```bash
# Version control for prompts
git add config/prompts/
git commit -m "Update investment prompt: improve criteria clarity"
git tag llm-prompts-v1.2.0
```

### Rollback Procedure

**If new prompt performs poorly**:

```bash
# Immediate rollback
cp config/prompts/investment_contact_selection_backup.txt config/prompts/investment_contact_selection.txt

# Reset metrics for clean monitoring
python -c "from src.enrich import reset_llm_performance_metrics; reset_llm_performance_metrics()"
```

## API Change Management

### OpenRouter API Updates

**Monitoring for changes**:

- Subscribe to OpenRouter changelog
- Monitor API response format changes
- Track new model availability
- Watch for deprecation notices

**Impact assessment**:

- Test API changes in staging environment
- Validate response format compatibility
- Check cost implications
- Assess performance impact

**Update procedure**:

1. **Staging validation**
2. **Gradual rollout** (A/B testing)
3. **Full deployment**
4. **Monitoring and validation**

### Model Updates

**When new models become available**:

1. **Evaluation phase**:

   - Test with sample contact lists
   - Compare selection quality
   - Analyze cost differences
   - Measure response times

2. **Configuration updates**:

   ```python
   # Update model configurations
   LLM_ICP_CONFIGS["investment"]["model"] = "new-model-name"
   ```

3. **Gradual adoption**:
   - Start with non-critical ICP types
   - Monitor performance closely
   - Expand to all ICP types gradually

### Deprecation Management

**When models are deprecated**:

1. **Identify affected configurations**
2. **Select replacement models**
3. **Update configurations**
4. **Test thoroughly**
5. **Monitor transition**

## Cost Management

### Budget Monitoring

**Daily cost tracking**:

```python
def daily_cost_check():
    # Calculate daily LLM costs
    # Compare against budget
    # Alert if approaching limits
    # Project monthly costs
    pass
```

**Cost optimization actions**:

- Increase cache TTL if appropriate
- Optimize prompt templates for token efficiency
- Consider less expensive models for non-critical ICPs
- Implement request throttling during high-usage periods

### Budget Alerts

**Set up cost monitoring**:

```python
# Cost alert thresholds
DAILY_COST_WARNING = 5.00  # USD
DAILY_COST_CRITICAL = 10.00  # USD
MONTHLY_BUDGET_LIMIT = 100.00  # USD

def check_cost_thresholds():
    daily_cost = get_daily_llm_cost()
    monthly_cost = get_monthly_llm_cost()

    if daily_cost > DAILY_COST_CRITICAL:
        send_alert("CRITICAL: Daily LLM cost exceeded")
    elif daily_cost > DAILY_COST_WARNING:
        send_alert("WARNING: Daily LLM cost high")

    if monthly_cost > MONTHLY_BUDGET_LIMIT * 0.8:
        send_alert("WARNING: Approaching monthly budget limit")
```

## Quality Assurance

### Selection Quality Metrics

**Define quality scoring**:

```python
def score_selection_quality(selected_contact, all_contacts, icp_criteria):
    """Score LLM selection quality from 0.0 to 1.0"""
    score = 0.0

    # Role relevance (40%)
    if contact_matches_role_criteria(selected_contact, icp_criteria):
        score += 0.4

    # Seniority appropriateness (30%)
    if contact_has_appropriate_seniority(selected_contact, icp_criteria):
        score += 0.3

    # Decision-making authority (20%)
    if contact_has_decision_authority(selected_contact, icp_criteria):
        score += 0.2

    # Best among options (10%)
    if selected_contact == get_best_manual_choice(all_contacts, icp_criteria):
        score += 0.1

    return score
```

### Quality Improvement Process

**Monthly quality review**:

1. **Sample 100 recent selections**
2. **Manual quality scoring**
3. **Identify patterns in poor selections**
4. **Update prompts or configuration**
5. **Re-test with same samples**
6. **Measure improvement**

### Feedback Integration

**User feedback collection**:

- Manual override tracking
- Quality rating system
- User comments on selections
- Business outcome correlation

**Feedback integration**:

- Use feedback to improve prompts
- Adjust ICP-specific configurations
- Update selection criteria
- Train better prompt engineering

---

## Emergency Contacts

**For LLM system issues**:

- Primary: Development Team
- Secondary: OpenRouter Support
- Emergency: System Administrator

**Escalation procedure**:

1. **Level 1**: Developer investigation (0-2 hours)
2. **Level 2**: Team lead involvement (2-4 hours)
3. **Level 3**: Vendor support engagement (4+ hours)

---

**Last updated**: 2025-01-27
**Next review**: 2025-02-27
**Version**: 1.0
