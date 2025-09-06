# Apollo Monitoring Dashboard

## Overview

This document provides guidance for setting up a comprehensive monitoring dashboard for Apollo integration usage, performance, and costs.

## Key Metrics Dashboard

### 1. Real-Time Performance Metrics

**Response Time Monitoring**:

```python
# Real-time response time tracking
import time
import asyncio
from src.apollo_client import ApolloClient

async def monitor_response_times():
    client = ApolloClient(api_key=os.getenv('APOLLO_API_KEY'))

    while True:
        start_time = time.time()
        try:
            response = await client.search_companies({'per_page': 1})
            duration = time.time() - start_time

            # Send to monitoring system
            record_metric('apollo.response_time', duration)
            record_metric('apollo.status_code', response.status_code)

        except Exception as e:
            record_metric('apollo.errors', 1)

        await asyncio.sleep(60)  # Check every minute
```

**Dashboard Widgets**:

- Response Time (p50, p95, p99)
- Success Rate Percentage
- Error Rate by Type
- Active API Calls

### 2. Rate Limiting Dashboard

**Rate Limit Monitoring**:

```python
# Track rate limiting events
def monitor_rate_limits():
    # Monitor 429 responses
    rate_limit_count = count_429_responses()

    # Calculate current usage
    current_usage = get_current_api_usage()
    limit = get_rate_limit()

    # Send to dashboard
    record_metric('apollo.rate_limit_events', rate_limit_count)
    record_metric('apollo.usage_percentage', (current_usage / limit) * 100)
```

**Dashboard Widgets**:

- Rate Limit Events per Hour
- Current Usage vs. Limit
- Backoff Delays
- Burst Traffic Alerts

### 3. Credit Usage Dashboard

**Credit Tracking**:

```python
# Monitor credit consumption
def track_credits():
    daily_credits = get_daily_credit_usage()
    monthly_credits = get_monthly_credit_usage()
    remaining_credits = get_remaining_credits()

    # Calculate costs
    daily_cost = daily_credits * 0.015  # $0.015 per credit
    monthly_cost = monthly_credits * 0.015

    # Send to dashboard
    record_metric('apollo.daily_credits', daily_credits)
    record_metric('apollo.monthly_credits', monthly_credits)
    record_metric('apollo.remaining_credits', remaining_credits)
    record_metric('apollo.daily_cost_usd', daily_cost)
    record_metric('apollo.monthly_cost_usd', monthly_cost)
```

**Dashboard Widgets**:

- Daily Credit Usage
- Monthly Credit Usage
- Cost per Lead
- Budget Utilization
- Credit Burn Rate

### 4. Data Quality Dashboard

**Quality Metrics**:

```python
# Monitor lead quality
def track_quality():
    recent_leads = get_recent_leads()

    quality_scores = [lead.get('quality_score', 0) for lead in recent_leads]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0

    high_quality_count = len([s for s in quality_scores if s >= 0.8])
    low_quality_count = len([s for s in quality_scores if s < 0.6])

    # Send to dashboard
    record_metric('apollo.avg_quality_score', avg_quality)
    record_metric('apollo.high_quality_leads', high_quality_count)
    record_metric('apollo.low_quality_leads', low_quality_count)
    record_metric('apollo.quality_distribution', {
        'high': high_quality_count,
        'medium': len(quality_scores) - high_quality_count - low_quality_count,
        'low': low_quality_count
    })
```

**Dashboard Widgets**:

- Average Quality Score
- Quality Distribution Chart
- High-Quality Lead Count
- Quality Trend Over Time

## Alert Configuration

### 1. Critical Alerts

**High Error Rate**:

```yaml
alert: apollo_high_error_rate
expr: rate(apollo_errors_total[5m]) > 0.1
for: 2m
labels:
  severity: critical
annotations:
  summary: 'Apollo API error rate is {{ $value }} errors per second'
  description: 'High error rate detected in Apollo integration'
```

**Rate Limit Exceeded**:

```yaml
alert: apollo_rate_limit_exceeded
expr: apollo_rate_limit_events_total > 50
for: 1m
labels:
  severity: warning
annotations:
  summary: 'Apollo rate limit exceeded'
  description: 'Rate limiting events detected in the last hour'
```

**Credit Limit Warning**:

```yaml
alert: apollo_credit_limit_warning
expr: apollo_remaining_credits < 100
for: 5m
labels:
  severity: warning
annotations:
  summary: 'Apollo credits running low'
  description: 'Only {{ $value }} credits remaining'
```

### 2. Performance Alerts

**High Response Time**:

```yaml
alert: apollo_high_response_time
expr: histogram_quantile(0.95, apollo_response_time_seconds) > 5
for: 5m
labels:
  severity: warning
annotations:
  summary: 'Apollo API response time is high'
  description: '95th percentile response time is {{ $value }} seconds'
```

**Low Success Rate**:

```yaml
alert: apollo_low_success_rate
expr: (apollo_successful_requests_total / apollo_total_requests_total) < 0.9
for: 10m
labels:
  severity: warning
annotations:
  summary: 'Apollo API success rate is low'
  description: 'Success rate is {{ $value | humanizePercentage }}'
```

## Dashboard Implementation

### 1. Grafana Dashboard

**Dashboard JSON Configuration**:

```json
{
  "dashboard": {
    "title": "Apollo Integration Monitoring",
    "panels": [
      {
        "title": "Response Time",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, apollo_response_time_seconds)",
            "legendFormat": "95th Percentile"
          },
          {
            "expr": "histogram_quantile(0.50, apollo_response_time_seconds)",
            "legendFormat": "Median"
          }
        ]
      },
      {
        "title": "Credit Usage",
        "type": "stat",
        "targets": [
          {
            "expr": "apollo_daily_credits_total",
            "legendFormat": "Daily Credits"
          }
        ]
      },
      {
        "title": "Error Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(apollo_errors_total[5m])",
            "legendFormat": "Errors per Second"
          }
        ]
      }
    ]
  }
}
```

### 2. Prometheus Metrics

**Custom Metrics Definition**:

```python
# Define Prometheus metrics
from prometheus_client import Counter, Histogram, Gauge

# Counters
apollo_requests_total = Counter('apollo_requests_total', 'Total Apollo API requests', ['operation', 'status'])
apollo_errors_total = Counter('apollo_errors_total', 'Total Apollo API errors', ['error_type'])
apollo_credits_used_total = Counter('apollo_credits_used_total', 'Total Apollo credits used')

# Histograms
apollo_response_time_seconds = Histogram('apollo_response_time_seconds', 'Apollo API response time', ['operation'])

# Gauges
apollo_remaining_credits = Gauge('apollo_remaining_credits', 'Remaining Apollo credits')
apollo_current_quality_score = Gauge('apollo_current_quality_score', 'Current lead quality score')
```

### 3. Log Aggregation

**Structured Logging**:

```python
import logging
import json

def log_apollo_metric(operation, duration, status, credits_used=None):
    log_data = {
        'timestamp': datetime.now().isoformat(),
        'operation': operation,
        'duration_seconds': duration,
        'status': status,
        'credits_used': credits_used,
        'component': 'apollo'
    }

    logging.info(json.dumps(log_data))
```

## Cost Optimization Dashboard

### 1. Cost Analysis Widgets

**Cost per Lead Tracking**:

```python
def calculate_cost_per_lead():
    total_cost = get_total_apollo_cost()
    total_leads = get_total_leads_generated()

    cost_per_lead = total_cost / total_leads if total_leads > 0 else 0

    # Send to dashboard
    record_metric('apollo.cost_per_lead_usd', cost_per_lead)

    return cost_per_lead
```

**Budget Utilization**:

```python
def track_budget_utilization():
    monthly_budget = get_monthly_budget()
    monthly_spent = get_monthly_apollo_cost()

    utilization_percentage = (monthly_spent / monthly_budget) * 100

    # Send to dashboard
    record_metric('apollo.budget_utilization_percent', utilization_percentage)

    return utilization_percentage
```

### 2. Optimization Recommendations

**Automated Recommendations**:

```python
def generate_optimization_recommendations():
    recommendations = []

    # Check cost per lead
    cost_per_lead = get_current_cost_per_lead()
    if cost_per_lead > 0.05:  # >$0.05 per lead
        recommendations.append({
            'type': 'cost_optimization',
            'priority': 'high',
            'message': 'High cost per lead - consider adjusting quality thresholds',
            'action': 'Review and adjust quality thresholds in ICP configuration'
        })

    # Check error rate
    error_rate = get_current_error_rate()
    if error_rate > 0.1:  # >10% errors
        recommendations.append({
            'type': 'performance_optimization',
            'priority': 'high',
            'message': 'High error rate - review API configuration',
            'action': 'Check API key validity and rate limit settings'
        })

    # Check rate limiting
    rate_limit_events = get_rate_limit_events_last_hour()
    if rate_limit_events > 20:
        recommendations.append({
            'type': 'performance_optimization',
            'priority': 'medium',
            'message': 'Frequent rate limiting - optimize batch sizes',
            'action': 'Reduce batch sizes in configuration'
        })

    return recommendations
```

## Maintenance Dashboard

### 1. Health Check Widgets

**System Health Status**:

```python
def check_apollo_health():
    health_checks = {
        'api_connectivity': check_api_connectivity(),
        'configuration_validity': check_configuration_validity(),
        'rate_limit_status': check_rate_limit_status(),
        'credit_availability': check_credit_availability()
    }

    overall_health = all(health_checks.values())

    # Send to dashboard
    record_metric('apollo.health_status', 1 if overall_health else 0)

    for check_name, status in health_checks.items():
        record_metric(f'apollo.health.{check_name}', 1 if status else 0)

    return overall_health
```

**Configuration Validation**:

```python
def validate_apollo_config():
    try:
        with open('icp_config.json') as f:
            config = json.load(f)

        # Validate Apollo configuration
        apollo_config = config.get('apollo', {})
        required_fields = ['enabled', 'search', 'enrich']

        missing_fields = [field for field in required_fields if field not in apollo_config]

        if missing_fields:
            return False, f"Missing required fields: {missing_fields}"

        return True, "Configuration is valid"

    except Exception as e:
        return False, f"Configuration error: {e}"
```

## Dashboard Access

### 1. User Roles

**Administrators**:

- Full access to all metrics
- Configuration management
- Alert management
- Cost analysis

**Developers**:

- Performance metrics
- Error monitoring
- Quality metrics
- Limited cost visibility

**Business Users**:

- Lead generation metrics
- Quality scores
- Cost per lead
- Budget utilization

### 2. Dashboard URLs

**Main Dashboard**: `/grafana/d/apollo-monitoring`
**Cost Dashboard**: `/grafana/d/apollo-costs`
**Performance Dashboard**: `/grafana/d/apollo-performance`
**Quality Dashboard**: `/grafana/d/apollo-quality`

## Integration with Existing Systems

### 1. Prometheus Integration

**Metrics Endpoint**: `/metrics`
**Scrape Interval**: 15 seconds
**Retention**: 30 days

### 2. Grafana Integration

**Data Source**: Prometheus
**Refresh Interval**: 30 seconds
**Time Range**: Last 24 hours (default)

### 3. Alert Manager Integration

**Alert Endpoint**: `/api/v1/alerts`
**Grouping**: By severity and component
**Silencing**: Via web interface or API

## Summary

This monitoring dashboard provides comprehensive visibility into Apollo integration performance, costs, and quality. Key features include:

- Real-time performance monitoring
- Cost tracking and optimization
- Quality metrics and trends
- Automated alerting
- Optimization recommendations
- Health status monitoring

The dashboard enables proactive management of the Apollo integration, ensuring optimal performance and cost efficiency while maintaining high lead quality standards.
