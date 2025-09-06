# Apollo Integration Troubleshooting Guide

## Quick Diagnostic Commands

### 1. Environment Check

```bash
# Check Apollo environment variables
env | grep APOLLO

# Verify Python environment
poetry env info

# Check httpx availability
poetry run python -c "import httpx; print(f'httpx version: {httpx.__version__}')"
```

### 2. Configuration Validation

```bash
# Validate ICP configuration
poetry run python -c "
import json
from src.apollo_lead_gen import ApolloLeadGen

try:
    with open('config/apollo_example_icp.json') as f:
        config = json.load(f)
    ApolloLeadGen._validate_apollo_config(config)
    print('✅ ICP configuration is valid')
except Exception as e:
    print(f'❌ Configuration error: {e}')
"

# Check Apollo defaults
cat config/apollo_defaults.yaml

# Verify cost configuration
cat config/costs.yaml | grep -A 5 apollo
```

### 3. Import Test

```bash
# Test all Apollo imports
poetry run python -c "
try:
    from src.apollo_client import ApolloClient
    from src.apollo_lead_gen import ApolloLeadGen
    from src.enrich_providers.apollo import ApolloEnrichProvider
    print('✅ All Apollo imports successful')
except ImportError as e:
    print(f'❌ Import error: {e}')
"
```

## Common Issues & Solutions

### 1. Authentication Errors

#### Issue: "APOLLO_API_KEY environment variable is required"

**Symptoms**:

- Error during ApolloLeadGen initialization
- "Missing required Apollo field: enabled" error

**Causes**:

- Environment variable not set
- Environment variable not loaded
- Wrong variable name

**Solutions**:

```bash
# 1. Check environment variable
echo $APOLLO_API_KEY

# 2. Set environment variable
export APOLLO_API_KEY="your_api_key_here"

# 3. Verify in Python
poetry run python -c "
import os
print(f'API Key: {os.getenv(\"APOLLO_API_KEY\", \"NOT SET\")}')
"

# 4. Check .env file
cat .env | grep APOLLO
```

#### Issue: "Invalid API key" or 401 Unauthorized

**Symptoms**:

- 401 responses from Apollo API
- Authentication failures in logs

**Causes**:

- Expired API key
- Invalid API key format
- Insufficient permissions

**Solutions**:

```bash
# 1. Regenerate API key in Apollo dashboard
# 2. Verify key format (should be a string)
# 3. Check API key permissions
# 4. Test with minimal request

poetry run python -c "
import asyncio
import os
from src.apollo_client import ApolloClient

async def test_auth():
    client = ApolloClient(api_key=os.getenv('APOLLO_API_KEY'))
    try:
        response = await client.search_companies({'per_page': 1})
        print(f'✅ Auth successful: {response.status_code}')
    except Exception as e:
        print(f'❌ Auth failed: {e}')

asyncio.run(test_auth())
"
```

### 2. Configuration Errors

#### Issue: "Missing required Apollo field: search"

**Symptoms**:

- Configuration validation errors
- Missing nested configuration fields

**Causes**:

- Incomplete Apollo configuration
- Wrong configuration structure
- Missing required nested fields

**Solutions**:

```bash
# 1. Check configuration structure
poetry run python -c "
import json
with open('config/apollo_example_icp.json') as f:
    config = json.load(f)

print('Apollo config structure:')
if 'apollo' in config:
    print(f'  - apollo.enabled: {config[\"apollo\"].get(\"enabled\", \"MISSING\")}')
    print(f'  - apollo.search: {\"PRESENT\" if \"search\" in config[\"apollo\"] else \"MISSING\"}')
    print(f'  - apollo.enrich: {\"PRESENT\" if \"enrich\" in config[\"apollo\"] else \"MISSING\"}')
else:
    print('  - apollo: MISSING')
"

# 2. Use sample configuration as template
cp config/apollo_example_icp.json icp_config.json

# 3. Validate configuration
poetry run python -c "
from src.apollo_lead_gen import ApolloLeadGen
import json

with open('icp_config.json') as f:
    config = json.load(f)

try:
    ApolloLeadGen._validate_apollo_config(config)
    print('✅ Configuration is valid')
except Exception as e:
    print(f'❌ Configuration error: {e}')
"
```

#### Issue: "Hardcoded business parameters detected"

**Symptoms**:

- Validation errors during initialization
- Specific field names flagged as hardcoded

**Causes**:

- Business parameters not loaded from config
- Hardcoded values in source code
- Configuration not properly structured

**Solutions**:

```bash
# 1. Check configuration loading
poetry run python -c "
import json
from src.apollo_lead_gen import ApolloLeadGen

with open('icp_config.json') as f:
    config = json.load(f)

# Check if business parameters are loaded
apollo_config = config.get('apollo', {})
search_config = apollo_config.get('search', {})
company_filters = search_config.get('company_filters', {})

print('Business parameters loaded:')
print(f'  - Industries: {company_filters.get(\"industry\", [])}')
print(f'  - Sizes: {company_filters.get(\"size\", [])}')
print(f'  - Technologies: {company_filters.get(\"technologies\", [])}')
"

# 2. Ensure all business parameters are in config
# 3. Remove any hardcoded values from source code
# 4. Use configuration-driven approach
```

### 3. Rate Limiting Issues

#### Issue: 429 Too Many Requests

**Symptoms**:

- Slow performance
- 429 responses in logs
- Exponential backoff delays

**Causes**:

- Exceeding rate limits
- Burst traffic
- Insufficient backoff logic

**Solutions**:

```bash
# 1. Check current rate limits
cat config/apollo_defaults.yaml | grep -A 10 rate_limiting

# 2. Monitor rate limiting in logs
grep "429" logs/*.log | tail -10

# 3. Adjust batch sizes
poetry run python -c "
import json
with open('icp_config.json') as f:
    config = json.load(f)

apollo_config = config.get('apollo', {})
search_config = apollo_config.get('search', {})
max_results = search_config.get('max_results', 'NOT SET')

print(f'Current max_results: {max_results}')
print('Consider reducing if hitting rate limits')
"

# 4. Implement proper backoff
# 5. Monitor credit usage
```

#### Issue: Slow Performance

**Symptoms**:

- Long response times
- Pipeline taking longer than expected
- High latency

**Causes**:

- Rate limiting delays
- Large batch sizes
- Network issues
- Inefficient search strategies

**Solutions**:

```bash
# 1. Check response times
poetry run python -c "
import asyncio
import time
from src.apollo_client import ApolloClient
import os

async def benchmark():
    client = ApolloClient(api_key=os.getenv('APOLLO_API_KEY'))

    start_time = time.time()
    try:
        response = await client.search_companies({'per_page': 1})
        duration = time.time() - start_time
        print(f'Response time: {duration:.2f}s')
        print(f'Status: {response.status_code}')
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(benchmark())
"

# 2. Optimize batch sizes
# 3. Use appropriate search strategy
# 4. Implement caching
# 5. Monitor network performance
```

### 4. Data Quality Issues

#### Issue: "Schema validation failed"

**Symptoms**:

- Data mapping errors
- Invalid field types
- Missing required fields

**Causes**:

- Apollo data doesn't match expected format
- Schema mismatch
- Data transformation errors

**Solutions**:

```bash
# 1. Check Apollo response format
poetry run python -c "
import asyncio
import json
from src.apollo_client import ApolloClient
import os

async def check_data_format():
    client = ApolloClient(api_key=os.getenv('APOLLO_API_KEY'))

    try:
        response = await client.search_companies({'per_page': 1})
        if response.status_code == 200:
            data = response.json()
            print('Apollo response structure:')
            print(json.dumps(data, indent=2)[:500] + '...')
        else:
            print(f'API error: {response.status_code}')
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(check_data_format())
"

# 2. Validate data mapping
# 3. Check schema compatibility
# 4. Review transformation logic
```

#### Issue: Low Lead Quality

**Symptoms**:

- Many leads filtered out
- Low scores
- Poor data completeness

**Causes**:

- Quality thresholds too high
- Search criteria too restrictive
- Poor data from Apollo

**Solutions**:

```bash
# 1. Check quality thresholds
poetry run python -c "
import json
with open('icp_config.json') as f:
    config = json.load(f)

apollo_config = config.get('apollo', {})
enrich_config = apollo_config.get('enrich', {})
quality_thresholds = enrich_config.get('quality_thresholds', {})

print('Quality thresholds:')
for key, value in quality_thresholds.items():
    print(f'  - {key}: {value}')
"

# 2. Adjust search criteria
# 3. Review quality scoring logic
# 4. Monitor quality metrics
```

### 5. Integration Issues

#### Issue: "Apollo mode enabled but apollo config missing"

**Symptoms**:

- Orchestrator initialization errors
- Configuration mismatch errors

**Causes**:

- `lead_generation_mode: "apollo"` but no Apollo config
- Incomplete configuration
- Configuration loading issues

**Solutions**:

```bash
# 1. Check lead generation mode
poetry run python -c "
import json
with open('icp_config.json') as f:
    config = json.load(f)

mode = config.get('lead_generation_mode', 'NOT SET')
apollo_enabled = config.get('apollo', {}).get('enabled', False)

print(f'Lead generation mode: {mode}')
print(f'Apollo enabled: {apollo_enabled}')

if mode == 'apollo' and not apollo_enabled:
    print('❌ Apollo mode enabled but Apollo config missing')
    print('Fix: Set apollo.enabled: true or change mode to traditional')
"

# 2. Ensure configuration consistency
# 3. Check configuration loading
# 4. Validate all required fields
```

#### Issue: "Module not found" errors

**Symptoms**:

- Import errors during testing
- Module resolution failures

**Causes**:

- Incorrect import paths
- Missing `__init__.py` files
- Python path issues

**Solutions**:

```bash
# 1. Check module structure
find src/ -name "*.py" | head -10
find tests/ -name "*.py" | head -10

# 2. Verify __init__.py files
find src/ -name "__init__.py"
find tests/ -name "__init__.py"

# 3. Test imports
poetry run python -c "
import sys
print('Python path:')
for path in sys.path:
    print(f'  {path}')
"

# 4. Fix import paths
# 5. Ensure proper module structure
```

## Advanced Diagnostics

### 1. Performance Profiling

```bash
# Profile Apollo operations
poetry run python -c "
import asyncio
import time
import cProfile
import pstats
from src.apollo_lead_gen import ApolloLeadGen
import json

async def profile_apollo():
    with open('icp_config.json') as f:
        config = json.load(f)

    lead_gen = ApolloLeadGen(config)

    # Profile search operation
    profiler = cProfile.Profile()
    profiler.enable()

    start_time = time.time()
    try:
        result = await lead_gen.run()
        duration = time.time() - start_time
        print(f'Operation completed in {duration:.2f}s')
    except Exception as e:
        print(f'Operation failed: {e}')

    profiler.disable()
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats(10)

asyncio.run(profile_apollo())
"
```

### 2. Memory Usage Analysis

```bash
# Check memory usage
poetry run python -c "
import psutil
import os

process = psutil.Process(os.getpid())
memory_info = process.memory_info()

print(f'Memory usage: {memory_info.rss / 1024 / 1024:.2f} MB')
print(f'Virtual memory: {memory_info.vms / 1024 / 1024:.2f} MB')
"
```

### 3. Network Diagnostics

```bash
# Test network connectivity
poetry run python -c "
import asyncio
import aiohttp
import time

async def test_network():
    urls = [
        'https://api.apollo.io/v1',
        'https://httpbin.org/delay/1',
        'https://httpbin.org/delay/2'
    ]

    async with aiohttp.ClientSession() as session:
        for url in urls:
            start_time = time.time()
            try:
                async with session.get(url) as response:
                    duration = time.time() - start_time
                    print(f'{url}: {response.status} in {duration:.2f}s')
            except Exception as e:
                print(f'{url}: Error - {e}')

asyncio.run(test_network())
"
```

## Recovery Procedures

### 1. Quick Recovery

```bash
# Disable Apollo temporarily
poetry run python -c "
import json

with open('icp_config.json', 'r') as f:
    config = json.load(f)

config['lead_generation_mode'] = 'traditional'
config['apollo']['enabled'] = False

with open('icp_config.json', 'w') as f:
    json.dump(config, f, indent=2)

print('Apollo disabled, switched to traditional mode')
"

# Restart orchestrator
poetry run python -m src.orchestrator --config icp_config.json
```

### 2. Full Reset

```bash
# Reset to working configuration
git checkout HEAD -- config/apollo_example_icp.json
git checkout HEAD -- config/costs.yaml

# Clear any temporary files
rm -rf data/apollo_*
rm -f logs/apollo_*.log

# Restart system
poetry run python -m src.orchestrator --config icp_config.json
```

### 3. Configuration Recovery

```bash
# Restore from backup
cp config/icp_config_backup.json icp_config.json

# Validate configuration
poetry run python -c "
import json
from src.apollo_lead_gen import ApolloLeadGen

with open('icp_config.json') as f:
    config = json.load(f)

try:
    ApolloLeadGen._validate_apollo_config(config)
    print('✅ Configuration restored and valid')
except Exception as e:
    print(f'❌ Configuration still invalid: {e}')
"
```

## Monitoring & Alerting

### 1. Health Checks

```bash
# Create health check script
cat > health_check.sh << 'EOF'
#!/bin/bash

# Check Apollo integration health
echo "=== Apollo Integration Health Check ==="

# Environment variables
echo "Environment:"
echo "  APOLLO_API_KEY: ${APOLLO_API_KEY:0:8}..."
echo "  APOLLO_REFRESH_TOKEN: ${APOLLO_REFRESH_TOKEN:0:8}..."

# Configuration
echo "Configuration:"
if [ -f "icp_config.json" ]; then
    echo "  ✅ icp_config.json exists"
    python3 -c "
import json
with open('icp_config.json') as f:
    config = json.load(f)
mode = config.get('lead_generation_mode', 'NOT SET')
apollo_enabled = config.get('apollo', {}).get('enabled', False)
print(f'    Lead generation mode: {mode}')
print(f'    Apollo enabled: {apollo_enabled}')
"
else
    echo "  ❌ icp_config.json missing"
fi

# Tests
echo "Tests:"
poetry run pytest tests/apollo/ -q --tb=no
if [ $? -eq 0 ]; then
    echo "  ✅ Apollo tests pass"
else
    echo "  ❌ Apollo tests fail"
fi

echo "=== Health Check Complete ==="
EOF

chmod +x health_check.sh
./health_check.sh
```

### 2. Log Monitoring

```bash
# Monitor Apollo logs
tail -f logs/apollo_*.log | grep -E "(ERROR|WARN|429|timeout)"

# Check for specific errors
grep -r "Apollo" logs/ | grep -E "(ERROR|Exception)" | tail -10

# Monitor rate limiting
grep -r "429" logs/ | wc -l
```

### 3. Performance Metrics

```bash
# Track response times
poetry run python -c "
import json
import time
from src.apollo_client import ApolloClient
import os

async def measure_performance():
    client = ApolloClient(api_key=os.getenv('APOLLO_API_KEY'))

    operations = [
        ('search_companies', {'per_page': 1}),
        ('search_persons', {'per_page': 1}),
    ]

    results = {}
    for op_name, params in operations:
        start_time = time.time()
        try:
            response = await getattr(client, op_name)(params)
            duration = time.time() - start_time
            results[op_name] = {
                'duration': duration,
                'status': response.status_code,
                'success': response.status_code == 200
            }
        except Exception as e:
            results[op_name] = {
                'duration': time.time() - start_time,
                'error': str(e),
                'success': False
            }

    print('Performance Metrics:')
    for op_name, result in results.items():
        if result['success']:
            print(f'  {op_name}: {result[\"duration\"]:.2f}s ({result[\"status\"]})')
        else:
            print(f'  {op_name}: FAILED - {result.get(\"error\", \"Unknown error\")}')

asyncio.run(measure_performance())
"
```

## Getting Help

### 1. Self-Service Resources

- [Apollo API Documentation](docs/apollapidocs.md)
- [Configuration Guide](docs/icp_configuration_guide.md)
- [Deployment Checklist](docs/apollo_deployment_checklist.md)
- [Configuration Validation](docs/apollo_config_validation.md)

### 2. Diagnostic Information to Collect

When seeking help, collect the following information:

```bash
# System information
echo "=== System Info ==="
python --version
poetry --version
uname -a

# Environment
echo "=== Environment ==="
env | grep APOLLO
poetry env info

# Configuration
echo "=== Configuration ==="
ls -la config/
cat icp_config.json | head -20

# Logs
echo "=== Recent Logs ==="
tail -20 logs/apollo_*.log 2>/dev/null || echo "No Apollo logs found"

# Test results
echo "=== Test Results ==="
poetry run pytest tests/apollo/ -q --tb=no 2>&1 | tail -10
```

### 3. Escalation Path

1. **Check this troubleshooting guide first**
2. **Review logs and error messages**
3. **Test with minimal configuration**
4. **Contact development team**
5. **Escalate to Apollo support if needed**

### 4. Support Contacts

- **Development Team**: [Internal contact]
- **Apollo Support**: [https://apollo.io/support](https://apollo.io/support)
- **Documentation**: [docs/](docs/) directory
- **GitHub Issues**: [Repository issues](https://github.com/your-repo/issues)
