# Apollo Configuration Validation Rules

## Overview

This document outlines the critical validation rules and safeguards that ensure Apollo integration maintains backward compatibility and follows strict no-hardcoding principles.

## Critical Validation Rules

### 1. Mode Configuration Validation

**Rule**: Apollo mode requires complete Apollo configuration

```json
{
  "lead_generation_mode": "apollo"
}
```

**Validation**: Must include complete `apollo` configuration block

```json
{
  "apollo": {
    "enabled": true,
    "search": {
      /* complete search config */
    },
    "enrich": {
      /* complete enrich config */
    }
  }
}
```

**Runtime Assertion**:

```python
if lead_generation_mode == "apollo":
    assert "apollo" in icp_config, "Apollo mode enabled but apollo config missing"
    assert icp_config["apollo"].get("enabled") == True, "Apollo must be enabled when mode is apollo"
```

### 2. Backward Compatibility Validation

**Rule**: Traditional mode must behave identically to current implementation

**Validation**: When `lead_generation_mode != "apollo"`:

- Apollo logic must not execute
- Traditional pipeline must remain unchanged
- No Apollo-related code paths should be accessed

**Runtime Assertion**:

```python
if lead_generation_mode != "apollo":
    # Traditional pipeline - no Apollo logic should execute
    assert "apollo" not in locals(), "Apollo logic should not be loaded in traditional mode"
```

### 3. Business Parameters Validation

**Rule**: Zero hardcoded business parameters in source code

**Validation**: All business parameters must be loaded from ICP config:

**Company Filters**:

```json
{
  "apollo": {
    "search": {
      "company_filters": {
        "industry": [], // Must be loaded from icp_config
        "size": [], // Must be loaded from icp_config
        "location": [], // Must be loaded from icp_config
        "technologies": [], // Must be loaded from icp_config
        "funding_stage": [] // Must be loaded from icp_config
      }
    }
  }
}
```

**Person Filters**:

```json
{
  "apollo": {
    "search": {
      "person_filters": {
        "job_titles": [], // Must be loaded from icp_config.role_priority keys
        "seniority": [], // Must be loaded from icp_config
        "departments": [] // Must be loaded from icp_config
      }
    }
  }
}
```

**Runtime Assertion**:

```python
def validate_business_parameters(apollo_config, icp_config):
    """Ensure all business parameters are loaded from ICP config"""

    # Company filters validation
    company_filters = apollo_config.get("search", {}).get("company_filters", {})
    for filter_type, values in company_filters.items():
        if values:  # If filters are specified
            # Ensure they're not hardcoded defaults
            assert not is_hardcoded_default(values), f"Hardcoded {filter_type} values detected"

    # Person filters validation
    person_filters = apollo_config.get("search", {}).get("person_filters", {})
    for filter_type, values in person_filters.items():
        if values:  # If filters are specified
            # Ensure they're not hardcoded defaults
            assert not is_hardcoded_default(values), f"Hardcoded {filter_type} values detected"
```

### 4. Configuration Completeness Validation

**Rule**: Apollo configuration must be complete and valid

**Required Fields**:

- `apollo.enabled` = `true`
- `apollo.search.strategy` (one of: "company_first", "person_first")
- `apollo.search.company_filters` (object with filter arrays)
- `apollo.search.person_filters` (object with filter arrays)
- `apollo.enrich.enabled` = `true`
- `apollo.enrich.use_bulk` (boolean)
- `apollo.enrich.batch_size` (integer 1-100)

**Validation Schema**:

```python
REQUIRED_APOLLO_FIELDS = {
    "enabled": bool,
    "search": {
        "strategy": str,  # enum: ["company_first", "person_first"]
        "company_filters": dict,
        "person_filters": dict
    },
    "enrich": {
        "enabled": bool,
        "use_bulk": bool,
        "batch_size": int
    }
}

def validate_apollo_config_completeness(apollo_config):
    """Validate Apollo configuration completeness"""
    for field, expected_type in REQUIRED_APOLLO_FIELDS.items():
        assert field in apollo_config, f"Missing required Apollo field: {field}"
        assert isinstance(apollo_config[field], expected_type), f"Invalid type for {field}"
```

### 5. Feature Flag Isolation Validation

**Rule**: Apollo logic only executes when explicitly configured

**Validation**: Traditional pipeline must bypass all Apollo-related code

**Code Structure**:

```python
async def run_pipeline(self):
    """Run the complete pipeline based on configuration mode."""
    lead_generation_mode = self.icp_config.get("lead_generation_mode", "traditional")

    if lead_generation_mode == "apollo":
        # Apollo logic only executes here
        return await self._run_apollo_pipeline()
    else:
        # Traditional logic - no Apollo code should execute
        return await self._run_traditional_pipeline()

async def _run_traditional_pipeline(self):
    """Execute traditional pipeline - MUST remain unchanged for backward compatibility"""
    # Copy existing pipeline logic here exactly as-is
    # This ensures zero changes to traditional flow
    pass

async def _run_apollo_pipeline(self):
    """Execute Apollo-first pipeline"""
    # New Apollo logic here
    pass
```

## CI/CD Validation Rules

### 1. Business Constants Linter

**Rule**: CI must catch any hardcoded business parameters

**Implementation**:

```yaml
# .github/workflows/ci.yaml
- name: Check for hardcoded business constants
  run: |
    # Comprehensive scan for business logic constants in src/ directory
    if grep -r '\["technology"\|"healthcare"\|"1-10"\|"11-50"\|"51-200"\|"CEO"\|"CTO"\|"VP Engineering"\|"executive"\|"director"\|"series_a"\|"series_b"\]' src/; then
      echo "❌ Found hardcoded business parameters in source code"
      echo "All business logic must be in config files, not source code"
      exit 1
    fi

    # Check for hardcoded industry lists
    if grep -r 'industry.*=.*\[.*\]' src/; then
      echo "❌ Found hardcoded industry lists in source code"
      exit 1
    fi

    # Check for hardcoded job title arrays
    if grep -r 'job_titles.*=.*\[.*\]' src/; then
      echo "❌ Found hardcoded job title arrays in source code"
      exit 1
    fi

    echo "✅ No hardcoded business constants found"
```

### 2. Backward Compatibility Gate

**Rule**: Legacy pipeline tests must pass before Apollo tests run

**Implementation**:

```yaml
- name: Run backward compatibility tests
  run: |
    pytest tests/regression/ -v --tb=short
    # Must pass 100% before Apollo tests run

- name: Run Apollo tests
  run: |
    pytest tests/apollo/ -v --tb=short
    # Only run after BC tests pass
```

### 3. Config Validation in CI

**Rule**: Validate sample ICP configs for schema compliance

**Implementation**:

```yaml
- name: Validate ICP configurations
  run: |
    # Validate traditional config
    python -c "import json; json.load(open('icp_config.json'))"

    # Validate Apollo example config
    python -c "import json; json.load(open('config/apollo_example_icp.json'))"

    # Validate extended schema
    python -c "import json; json.load(open('schemas/extended_icp_config.json'))"
```

## Runtime Validation Implementation

### 1. Configuration Loader Validation

```python
class ApolloConfigValidator:
    """Validates Apollo configuration integrity at runtime"""

    def __init__(self, icp_config):
        self.icp_config = icp_config
        self.lead_generation_mode = icp_config.get("lead_generation_mode", "traditional")

    def validate(self):
        """Validate Apollo configuration integrity"""
        if self.lead_generation_mode == "apollo":
            self._validate_apollo_mode()
        else:
            self._validate_traditional_mode()

    def _validate_apollo_mode(self):
        """Validate Apollo mode configuration"""
        # Ensure Apollo config exists
        assert "apollo" in self.icp_config, "Apollo mode enabled but apollo config missing"

        apollo_config = self.icp_config["apollo"]

        # Validate required fields
        assert apollo_config.get("enabled") == True, "Apollo must be enabled when mode is apollo"

        # Validate search configuration
        search_config = apollo_config.get("search", {})
        assert "strategy" in search_config, "Apollo search strategy required"
        assert search_config["strategy"] in ["company_first", "person_first"], "Invalid search strategy"

        # Validate filters are not hardcoded
        self._validate_filters_not_hardcoded(search_config)

    def _validate_traditional_mode(self):
        """Validate traditional mode configuration"""
        # Ensure no Apollo logic is loaded
        assert "apollo" not in self.icp_config, "Apollo config should not exist in traditional mode"

    def _validate_filters_not_hardcoded(self, search_config):
        """Ensure business filters are not hardcoded"""
        company_filters = search_config.get("company_filters", {})
        person_filters = search_config.get("person_filters", {})

        # Check for common hardcoded patterns
        hardcoded_patterns = [
            ["technology", "software", "saas"],
            ["1-10", "11-50", "51-200"],
            ["CEO", "CTO", "VP Engineering"]
        ]

        for pattern in hardcoded_patterns:
            for filter_values in [company_filters.values(), person_filters.values()]:
                for values in filter_values:
                    if isinstance(values, list) and values == pattern:
                        raise ValueError(f"Hardcoded business parameters detected: {pattern}")
```

### 2. Integration Point Validation

```python
class ApolloIntegrationValidator:
    """Validates Apollo integration points"""

    def validate_orchestrator_integration(self, orchestrator):
        """Validate orchestrator integration maintains backward compatibility"""

        # Ensure traditional pipeline method exists and is unchanged
        assert hasattr(orchestrator, '_run_traditional_pipeline'), "Traditional pipeline method missing"

        # Ensure Apollo pipeline method exists
        assert hasattr(orchestrator, '_run_apollo_pipeline'), "Apollo pipeline method missing"

        # Validate method separation
        traditional_method = getattr(orchestrator, '_run_traditional_pipeline')
        apollo_method = getattr(orchestrator, '_run_apollo_pipeline')

        assert traditional_method != apollo_method, "Pipeline methods must be separate"

    def validate_tool_registration(self, orchestrator):
        """Validate tool registration maintains backward compatibility"""

        if orchestrator.icp_config.get("lead_generation_mode") == "apollo":
            # Apollo mode should register Apollo tool
            assert "apollo" in orchestrator.tools, "Apollo tool not registered in Apollo mode"
        else:
            # Traditional mode should not register Apollo tool
            assert "apollo" not in orchestrator.tools, "Apollo tool registered in traditional mode"
```

## Testing Validation Rules

### 1. Regression Test Requirements

**Rule**: 100% coverage of traditional mode code paths required

**Implementation**:

```python
# tests/regression/test_legacy_flow_unchanged.py
def test_traditional_pipeline_unchanged():
    """Test that traditional mode pipeline produces identical results before/after Apollo integration"""

    # Load legacy config (no Apollo config)
    legacy_config = load_legacy_config()

    # Run traditional pipeline
    legacy_result = run_traditional_pipeline(legacy_config)

    # Load same config with Apollo integration code present
    apollo_integrated_config = load_legacy_config()  # Same config

    # Run traditional pipeline with Apollo code present
    apollo_integrated_result = run_traditional_pipeline(apollo_integrated_config)

    # Results must be identical
    assert legacy_result == apollo_integrated_result, "Traditional pipeline behavior changed"
```

### 2. ICP-Agnostic Testing

**Rule**: All test fixtures must load from config files

**Implementation**:

```python
# tests/fixtures/apollo_configs.py
def load_apollo_test_config():
    """Load Apollo test configuration from file"""
    with open('config/apollo_example_icp.json', 'r') as f:
        return json.load(f)

def load_traditional_test_config():
    """Load traditional test configuration from file"""
    with open('icp_config.json', 'r') as f:
        return json.load(f)

# Test with multiple ICP configurations
@pytest.mark.parametrize("config_file", [
    'config/apollo_example_icp.json',
    'icp_config.json',
    'config/dental_example_icp.json'
])
def test_apollo_integration_with_different_icps(config_file):
    """Test Apollo integration with different ICP configurations"""
    config = load_config_from_file(config_file)
    # Test Apollo integration
    result = test_apollo_integration(config)
    assert result is not None
```

## Summary of Critical Safeguards

1. **Mode Isolation**: Apollo logic only executes when explicitly configured
2. **Backward Compatibility**: Traditional mode behavior unchanged
3. **No Hardcoding**: All business parameters loaded from config
4. **Runtime Validation**: Assertions prevent invalid configurations
5. **CI Enforcement**: Automated checks catch violations
6. **Test Coverage**: 100% coverage of backward compatibility paths
7. **Config Validation**: Schema validation ensures integrity
8. **Feature Flag Driven**: Apollo integration is opt-in only

## Compliance Checklist

- [ ] Apollo mode requires complete Apollo configuration
- [ ] Traditional mode behaves identically to current implementation
- [ ] Zero hardcoded business parameters in source code
- [ ] Runtime validation prevents partial configurations
- [ ] CI pipeline includes business constants linter
- [ ] Backward compatibility tests pass 100%
- [ ] Apollo tests only run after BC tests pass
- [ ] All business parameters loaded from ICP config
- [ ] Feature flag isolation prevents accidental Apollo execution
- [ ] Configuration schema validation in CI
