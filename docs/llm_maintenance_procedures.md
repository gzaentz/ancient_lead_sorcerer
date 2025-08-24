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

## Apollo Integration Maintenance

### Daily Apollo Monitoring

**Frequency**: Every hour during business hours

**Metrics to Monitor**:

```bash
# Check Apollo system health
python -c "
from src.orchestrator import LeadSorcererOrchestrator
import json

# Load configuration
with open('icp_config.json') as f:
    config = json.load(f)

# Check if Apollo is enabled
apollo_enabled = config.get('lead_generation_mode') == 'apollo' and config.get('apollo', {}).get('enabled', False)
print(f'Apollo Mode: {\"Enabled\" if apollo_enabled else \"Disabled\"}')

if apollo_enabled:
    print('Apollo Configuration:')
    apollo_config = config.get('apollo', {})
    print(f'  - Search Strategy: {apollo_config.get(\"search\", {}).get(\"strategy\", \"NOT SET\")}')
    print(f'  - Max Results: {apollo_config.get(\"search\", {}).get(\"max_results\", \"NOT SET\")}')
    print(f'  - Quality Thresholds: {apollo_config.get(\"enrich\", {}).get(\"quality_thresholds\", {})}')
"
```

**Alert Thresholds**:

- API Error Rate > 5%: **WARNING**
- API Error Rate > 10%: **CRITICAL**
- Rate Limiting > 10 per hour: **WARNING**
- Rate Limiting > 50 per hour: **CRITICAL**
- Credit Usage > 80% of daily limit: **WARNING**

### Apollo API Key Rotation

**Frequency**: Every 90 days or when compromised

**Procedure**:

```bash
# 1. Generate new API key in Apollo dashboard
# 2. Update environment variables
export APOLLO_API_KEY="new_api_key_here"

# 3. Test new key
poetry run python -c "
import asyncio
import os
from src.apollo_client import ApolloClient

async def test_new_key():
    client = ApolloClient(api_key=os.getenv('APOLLO_API_KEY'))
    try:
        response = await client.search_companies({'per_page': 1})
        print(f'✅ New API key working: {response.status_code}')
    except Exception as e:
        print(f'❌ New API key failed: {e}')

asyncio.run(test_new_key())
"

# 4. Update .env file
sed -i 's/APOLLO_API_KEY=.*/APOLLO_API_KEY=new_api_key_here/' .env

# 5. Restart services
poetry run python -m src.orchestrator --config icp_config.json
```

**Rollback Plan**:

- Keep old key active for 24 hours
- Monitor for any issues with new key
- Revert to old key if problems occur

### Rate Limit Monitoring

**Real-time monitoring**:

```bash
# Monitor rate limiting in logs
tail -f logs/*.log | grep -E "(429|rate.limit|too.many.requests)"

# Check current rate limit status
poetry run python -c "
import asyncio
import os
from src.apollo_client import ApolloClient

async def check_rate_limits():
    client = ApolloClient(api_key=os.getenv('APOLLO_API_KEY'))

    # Make test requests to check current limits
    for i in range(5):
        try:
            response = await client.search_companies({'per_page': 1})
            print(f'Request {i+1}: {response.status_code}')
            if response.status_code == 429:
                print('⚠️ Rate limit hit!')
                break
        except Exception as e:
            print(f'Request {i+1} failed: {e}')
        await asyncio.sleep(1)

asyncio.run(check_rate_limits())
"
```

**Rate Limit Optimization**:

```python
# Adjust batch sizes based on rate limits
def optimize_batch_size(current_error_rate):
    if current_error_rate > 0.1:  # >10% errors
        return max(10, current_batch_size // 2)
    elif current_error_rate < 0.02:  # <2% errors
        return min(100, current_batch_size * 1.2)
    else:
        return current_batch_size
```

### Credit Usage Tracking

**Daily credit monitoring**:

```bash
# Check daily credit usage
poetry run python -c "
import json
from datetime import datetime, timedelta

# Load cost tracking data
try:
    with open('data/costs/apollo_credits.json') as f:
        credit_data = json.load(f)

    today = datetime.now().strftime('%Y-%m-%d')
    daily_usage = credit_data.get(today, 0)

    print(f'Today\'s Apollo credit usage: {daily_usage}')

    if daily_usage > 800:
        print('⚠️ WARNING: High credit usage today')
    elif daily_usage > 950:
        print('🚨 CRITICAL: Approaching daily credit limit')

except FileNotFoundError:
    print('No credit tracking data found')
"
```

**Credit Optimization Strategies**:

```python
# Implement credit-aware routing
def optimize_credit_usage(remaining_credits, daily_limit):
    if remaining_credits < daily_limit * 0.1:  # <10% remaining
        return {
            'batch_size': 10,  # Reduce batch size
            'quality_threshold': 0.9,  # Increase quality threshold
            'skip_optional_enrichment': True
        }
    elif remaining_credits < daily_limit * 0.3:  # <30% remaining
        return {
            'batch_size': 25,
            'quality_threshold': 0.8,
            'skip_optional_enrichment': False
        }
    else:
        return {
            'batch_size': 50,
            'quality_threshold': 0.7,
            'skip_optional_enrichment': False
        }
```

### Error Rate Monitoring

**Error tracking and analysis**:

```bash
# Monitor Apollo-specific errors
grep -r "Apollo.*error\|apollo.*failed\|429.*apollo" logs/ | tail -20

# Check error patterns
poetry run python -c "
import json
from collections import Counter

# Analyze recent error logs
error_patterns = []
with open('logs/apollo_errors.log', 'r') as f:
    for line in f:
        if 'ERROR' in line:
            error_patterns.append(line.strip())

# Count error types
error_counts = Counter()
for error in error_patterns:
    if '429' in error:
        error_counts['rate_limit'] += 1
    elif '401' in error:
        error_counts['auth_error'] += 1
    elif '500' in error:
        error_counts['server_error'] += 1
    else:
        error_counts['other'] += 1

print('Error Distribution:')
for error_type, count in error_counts.most_common():
    print(f'  {error_type}: {count}')
"
```

**Error Response Procedures**:

1. **Rate Limiting (429)**:

   - Implement exponential backoff
   - Reduce batch sizes
   - Monitor for patterns

2. **Authentication Errors (401)**:

   - Verify API key validity
   - Check key permissions
   - Rotate API key if needed

3. **Server Errors (5xx)**:
   - Log error details
   - Implement retry logic
   - Contact Apollo support if persistent

### Performance Monitoring

**Response time tracking**:

```bash
# Monitor API response times
poetry run python -c "
import asyncio
import time
import statistics
from src.apollo_client import ApolloClient
import os

async def benchmark_performance():
    client = ApolloClient(api_key=os.getenv('APOLLO_API_KEY'))

    response_times = []
    operations = [
        ('search_companies', {'per_page': 1}),
        ('search_persons', {'per_page': 1}),
        ('enrich_company', {'domain': 'example.com'}),
        ('enrich_person', {'email': 'test@example.com'})
    ]

    for op_name, params in operations:
        times = []
        for _ in range(3):  # 3 test runs
            start_time = time.time()
            try:
                response = await getattr(client, op_name)(params)
                duration = time.time() - start_time
                times.append(duration)
            except Exception as e:
                print(f'{op_name} failed: {e}')

        if times:
            avg_time = statistics.mean(times)
            response_times.append((op_name, avg_time))

    print('Performance Benchmark:')
    for op_name, avg_time in response_times:
        status = '✅' if avg_time < 2.0 else '⚠️' if avg_time < 5.0 else '❌'
        print(f'{status} {op_name}: {avg_time:.2f}s')

asyncio.run(benchmark_performance())
"
```

**Performance Optimization**:

```python
# Implement performance-based routing
def optimize_performance(current_response_time):
    if current_response_time > 5.0:  # >5 seconds
        return {
            'use_caching': True,
            'reduce_batch_size': True,
            'implement_backoff': True
        }
    elif current_response_time > 2.0:  # >2 seconds
        return {
            'use_caching': True,
            'reduce_batch_size': False,
            'implement_backoff': False
        }
    else:
        return {
            'use_caching': False,
            'reduce_batch_size': False,
            'implement_backoff': False
        }
```

### Data Quality Monitoring

**Quality metrics tracking**:

```bash
# Monitor lead quality metrics
poetry run python -c "
import json
from datetime import datetime, timedelta

# Load recent results
try:
    with open('data/apollo_results.json') as f:
        results = json.load(f)

    # Calculate quality metrics
    total_leads = len(results.get('leads', []))
    quality_scores = [lead.get('quality_score', 0) for lead in results.get('leads', [])]

    if quality_scores:
        avg_quality = sum(quality_scores) / len(quality_scores)
        high_quality = len([s for s in quality_scores if s >= 0.8])

        print(f'Data Quality Metrics:')
        print(f'  - Total Leads: {total_leads}')
        print(f'  - Average Quality: {avg_quality:.2f}')
        print(f'  - High Quality (≥0.8): {high_quality}/{total_leads}')

        if avg_quality < 0.7:
            print('⚠️ WARNING: Low average quality score')

except FileNotFoundError:
    print('No Apollo results data found')
"
```

**Quality Improvement Process**:

1. **Weekly Quality Review**:

   - Sample 50 recent leads
   - Manual quality assessment
   - Identify quality patterns
   - Adjust thresholds if needed

2. **Threshold Optimization**:
   - Review quality thresholds monthly
   - Adjust based on business requirements
   - Monitor impact on lead volume

### Weekly Apollo Report

**Generate comprehensive report**:

```python
#!/usr/bin/env python3
"""Weekly Apollo Performance Report"""

import json
from datetime import datetime, timedelta

def generate_apollo_weekly_report():
    report = {
        "report_date": datetime.now().isoformat(),
        "period": "7 days",
        "apollo_metrics": {
            "total_leads_generated": 0,
            "total_credits_used": 0,
            "average_quality_score": 0.0,
            "error_rate": 0.0,
            "rate_limit_events": 0
        },
        "performance_metrics": {
            "average_response_time": 0.0,
            "cache_hit_rate": 0.0,
            "batch_efficiency": 0.0
        },
        "cost_analysis": {
            "cost_per_lead": 0.0,
            "daily_cost_trend": [],
            "budget_utilization": 0.0
        },
        "recommendations": []
    }

    # Generate recommendations based on metrics
    if report["apollo_metrics"]["error_rate"] > 0.05:
        report["recommendations"].append("High error rate detected - review API configuration")

    if report["apollo_metrics"]["rate_limit_events"] > 10:
        report["recommendations"].append("Frequent rate limiting - optimize batch sizes")

    if report["cost_analysis"]["cost_per_lead"] > 0.05:
        report["recommendations"].append("High cost per lead - review quality thresholds")

    return report

# Generate and save report
if __name__ == "__main__":
    report = generate_apollo_weekly_report()
    with open(f'reports/apollo_weekly_{datetime.now().strftime("%Y%m%d")}.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("Weekly Apollo report generated successfully")
```

## Quality Assurance

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
