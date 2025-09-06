# Apollo Integration Deployment Checklist

## Pre-Deployment Requirements

### 1. Apollo API Access

- [ ] **Apollo Account**: Create account at [apollo.io](https://apollo.io)
- [ ] **API Key**: Generate API key from Apollo dashboard
- [ ] **API Permissions**: Verify API key has required permissions
- [ ] **Rate Limits**: Understand current plan's rate limits
- [ ] **Credits**: Ensure sufficient credits for testing and production

### 2. System Requirements

- [ ] **Python Version**: Python 3.8+ installed
- [ ] **Dependencies**: All required packages installed via Poetry
- [ ] **Environment**: Development/staging environment available
- [ ] **Data Directory**: Sufficient disk space for data storage
- [ ] **Network Access**: Outbound HTTPS access to Apollo API

### 3. Configuration Files

- [ ] **Environment Variables**: `.env` file with Apollo credentials
- [ ] **Cost Configuration**: `config/costs.yaml` updated with Apollo pricing
- [ ] **Apollo Defaults**: `config/apollo_defaults.yaml` configured
- [ ] **ICP Configuration**: Sample Apollo ICP config ready

## Environment Setup

### 1. Environment Variables

```bash
# Required
APOLLO_API_KEY=your_api_key_here

# Optional (for OAuth flows)
APOLLO_REFRESH_TOKEN=your_refresh_token_here

# Verify environment variables are loaded
echo $APOLLO_API_KEY
```

### 2. Configuration Files

```bash
# Copy and configure Apollo defaults
cp config/apollo_defaults.yaml config/apollo_defaults_local.yaml

# Update cost configuration
# Edit config/costs.yaml to include Apollo pricing

# Prepare ICP configuration
# Copy config/apollo_example_icp.json and customize
```

### 3. Dependencies Installation

```bash
# Install via Poetry
poetry install

# Verify httpx is available
poetry run python -c "import httpx; print('httpx available')"

# Check all imports work
poetry run python -c "from src.apollo_client import ApolloClient; print('Apollo client import successful')"
```

## Configuration Validation

### 1. Apollo Client Configuration

```python
# Test Apollo client configuration
from src.apollo_client import ApolloClient
import os

client = ApolloClient(
    api_key=os.getenv('APOLLO_API_KEY'),
    base_url="https://api.apollo.io/v1"
)

# Verify configuration loads
print(f"Base URL: {client.base_url}")
print(f"API Key configured: {'Yes' if client.api_key else 'No'}")
```

### 2. ICP Configuration Validation

```bash
# Validate ICP configuration
poetry run python -c "
import json
from src.apollo_lead_gen import ApolloLeadGen

with open('config/apollo_example_icp.json') as f:
    config = json.load(f)

# This should not raise validation errors
print('ICP configuration is valid')
"
```

### 3. Schema Validation

```bash
# Verify unified schema compatibility
poetry run python -c "
import json
from schemas.unified_lead_record import validate_lead_record

# Test with sample Apollo data
sample_data = {
    'lead_id': 'test-123',
    'domain': 'example.com',
    'company': {'name': 'Test Company'},
    'contacts': []
}

try:
    validate_lead_record(sample_data)
    print('Schema validation successful')
except Exception as e:
    print(f'Schema validation failed: {e}')
"
```

## Testing & Validation

### 1. Unit Tests

```bash
# Run Apollo unit tests
poetry run pytest tests/apollo/ -v

# Expected: All tests pass
# Coverage should be ≥90%
```

### 2. Integration Tests

```bash
# Run Apollo integration tests
poetry run pytest tests/test_integration.py::TestApolloIntegration -v

# Expected: All integration tests pass
```

### 3. End-to-End Testing

```bash
# Test Apollo pipeline with sample configuration
poetry run python -m src.orchestrator --config config/apollo_example_icp.json

# Expected: Pipeline runs successfully
# Check logs for any errors or warnings
```

### 4. API Connectivity Test

```bash
# Test Apollo API connectivity
poetry run python -c "
import asyncio
from src.apollo_client import ApolloClient
import os

async def test_connectivity():
    client = ApolloClient(api_key=os.getenv('APOLLO_API_KEY'))

    try:
        # Test basic connectivity
        response = await client.search_companies({'per_page': 1})
        print('✅ Apollo API connectivity successful')
        print(f'Response status: {response.status_code}')
    except Exception as e:
        print(f'❌ Apollo API connectivity failed: {e}')

asyncio.run(test_connectivity())
"
```

## Production Deployment

### 1. Environment Configuration

```bash
# Production environment variables
export APOLLO_API_KEY="prod_api_key_here"
export APOLLO_REFRESH_TOKEN="prod_refresh_token_here"  # if using OAuth

# Verify production credentials
echo "API Key configured: ${APOLLO_API_KEY:0:8}..."
```

### 2. Configuration Files

```bash
# Production Apollo defaults
cp config/apollo_defaults.yaml config/apollo_production.yaml

# Update with production settings:
# - Higher rate limits
# - Production timeouts
# - Production retry settings
```

### 3. Monitoring Setup

```bash
# Verify logging configuration
# Check logs/apollo_*.log files are created

# Monitor rate limiting
# Check for 429 responses in logs

# Monitor credit usage
# Track cost metrics in orchestrator output
```

### 4. Performance Testing

```bash
# Test with realistic batch sizes
poetry run python -m src.orchestrator --config config/apollo_example_icp.json --batch-size 50

# Monitor:
# - Response times
# - Rate limiting
# - Credit consumption
# - Error rates
```

## Post-Deployment Verification

### 1. Functionality Verification

- [ ] **Apollo Pipeline**: Runs successfully with Apollo configuration
- [ ] **Traditional Pipeline**: Still works with traditional configuration
- [ ] **Hybrid Mode**: Apollo enrichment works within traditional pipeline
- [ ] **Fallback Logic**: Traditional fallback works when Apollo fails
- [ ] **Data Quality**: Generated leads meet quality thresholds

### 2. Performance Verification

- [ ] **Response Times**: API calls complete within expected timeframes
- [ ] **Rate Limiting**: No excessive 429 responses
- [ ] **Credit Usage**: Credits consumed as expected
- [ ] **Error Rates**: Error rates within acceptable thresholds
- [ ] **Throughput**: Can process expected batch sizes

### 3. Data Quality Verification

- [ ] **Schema Compliance**: All data conforms to unified schema
- [ ] **Field Completion**: Required fields are populated
- [ ] **Data Accuracy**: Information matches expected quality standards
- [ ] **Duplicate Handling**: No duplicate leads generated
- [ ] **ID Consistency**: Lead and contact IDs are deterministic

### 4. Integration Verification

- [ ] **Orchestrator**: Correctly switches between Apollo and traditional modes
- [ ] **Enrichment Router**: Apollo provider is properly integrated
- [ ] **Data Persistence**: Results are correctly saved to data directory
- [ ] **Export Functionality**: Apollo data is included in exports
- [ ] **Metrics**: Apollo metrics are properly tracked

## Troubleshooting

### 1. Common Issues

#### Authentication Errors

```bash
# Check environment variables
env | grep APOLLO

# Verify API key format
# Should be a valid string, not empty or malformed
```

#### Rate Limiting

```bash
# Check logs for 429 responses
grep "429" logs/apollo_*.log

# Verify rate limit configuration
cat config/apollo_defaults.yaml | grep rate_limiting
```

#### Configuration Errors

```bash
# Validate ICP configuration
poetry run python -c "
import json
from src.apollo_lead_gen import ApolloLeadGen

with open('config/apollo_example_icp.json') as f:
    config = json.load(f)

try:
    ApolloLeadGen._validate_apollo_config(config)
    print('Configuration is valid')
except Exception as e:
    print(f'Configuration error: {e}')
"
```

### 2. Debug Commands

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Test specific Apollo functionality
poetry run python -c "
import asyncio
from src.apollo_lead_gen import ApolloLeadGen
import json

async def debug_apollo():
    with open('config/apollo_example_icp.json') as f:
        config = json.load(f)

    lead_gen = ApolloLeadGen(config)
    print('ApolloLeadGen initialized successfully')

asyncio.run(debug_apollo())
"
```

### 3. Support Resources

- [Apollo API Documentation](docs/apollapidocs.md)
- [Configuration Guide](docs/icp_configuration_guide.md)
- [Troubleshooting Guide](docs/apollo_config_validation.md)
- [Apollo Support](https://apollo.io/support)

## Rollback Plan

### 1. Quick Rollback

```bash
# Disable Apollo integration
# Edit icp_config.json and set:
# "lead_generation_mode": "traditional"
# "apollo": {"enabled": false}

# Restart orchestrator
poetry run python -m src.orchestrator --config icp_config.json
```

### 2. Full Rollback

```bash
# Revert to previous version
git checkout HEAD~1

# Restore previous configuration
cp config/icp_config_backup.json icp_config.json

# Restart system
poetry run python -m src.orchestrator --config icp_config.json
```

## Maintenance & Monitoring

### 1. Regular Checks

- [ ] **Daily**: Monitor error rates and API performance
- [ ] **Weekly**: Review credit usage and cost trends
- [ ] **Monthly**: Analyze lead quality metrics
- [ ] **Quarterly**: Review and optimize search strategies

### 2. Performance Optimization

- [ ] **Rate Limiting**: Adjust based on API performance
- [ ] **Batch Sizes**: Optimize for throughput vs. rate limits
- [ ] **Search Strategies**: Refine based on lead quality results
- [ ] **Quality Thresholds**: Adjust based on business requirements

### 3. Cost Optimization

- [ ] **Credit Usage**: Monitor and optimize credit consumption
- [ ] **Search Efficiency**: Reduce unnecessary API calls
- [ ] **Quality vs. Cost**: Balance lead quality with cost
- [ ] **Provider Mix**: Use Apollo strategically with other providers

## Success Criteria

### 1. Functional Requirements

- [ ] Apollo pipeline generates high-quality leads
- [ ] Traditional pipeline remains unchanged
- [ ] Hybrid mode works correctly
- [ ] All data conforms to unified schema
- [ ] Error handling works as expected

### 2. Performance Requirements

- [ ] Response times under 2 seconds for single requests
- [ ] Rate limiting handled gracefully
- [ ] Credit usage tracked accurately
- [ ] Error rates under 5%
- [ ] Throughput meets business requirements

### 3. Quality Requirements

- [ ] Lead quality meets or exceeds traditional pipeline
- [ ] Data accuracy validated
- [ ] Required fields populated
- [ ] No duplicate leads generated
- [ ] Quality thresholds enforced

## Completion Checklist

- [ ] **Pre-deployment**: All requirements met
- [ ] **Environment**: Setup complete and validated
- [ ] **Configuration**: All configs validated
- [ ] **Testing**: All tests pass
- [ ] **Deployment**: Production deployment complete
- [ ] **Verification**: All functionality verified
- [ ] **Monitoring**: Monitoring and alerting active
- [ ] **Documentation**: User documentation updated
- [ ] **Training**: Team trained on new functionality

**Deployment Status**: ⏳ In Progress / ✅ Complete / ❌ Failed

**Deployment Date**: ******\_\_\_******

**Deployed By**: ******\_\_\_******

**Notes**: ******\_\_\_******
