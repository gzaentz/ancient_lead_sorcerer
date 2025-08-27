# Lead Generation Modes Implementation Tasks

## Overview

This document outlines the comprehensive implementation tasks for establishing four distinct lead generation modes in Lead Sorcerer, including the new database mode and proper Apollo provider integration.

## Architecture Summary

### Four Lead Generation Modes

#### 1. Search Mode (`"lead_generation_mode": "search"`)

- **Pipeline**: `Domain Discovery → Crawl → Enrich`
- **Purpose**: Query-based lead discovery with search engines
- **Use Case**: "Find dental practices in California"

#### 2. Apollo Mode (`"lead_generation_mode": "apollo"`)

- **Pipeline**: `Apollo Search → Enrich → Export`
- **Purpose**: Pure Apollo-based lead discovery and enrichment
- **Use Case**: "Use Apollo's database for lead generation"

#### 3. URL Mode (`"lead_generation_mode": "url"`)

- **Pipeline**: `Bypass Domain → Crawl Single Companies → Enrich`
- **Purpose**: Target known specific companies/websites
- **Use Case**: "Analyze pacificdental.com and 3 other known targets"

#### 4. Database Mode (`"lead_generation_mode": "database"`) **[NEW]**

- **Pipeline**: `Bypass Domain → Extract Multiple Companies from Database Sites → Enrich`
- **Purpose**: Extract multiple companies from directory/listing websites
- **Use Case**: "Extract all dental practices from yellowpages.com/dentists"

### Mode Transition Matrix

| Mode | Domain Discovery | Crawl Type | Enrich Providers | Use Case |
|------|-----------------|------------|------------------|----------|
| **search** | ✅ Search queries | Single company | All enabled | Query-based discovery |
| **apollo** | ❌ Use Apollo | Skip (Apollo has data) | Apollo primary | Pure Apollo pipeline |
| **url** | ❌ Bypass | Single company per URL | All enabled | Known target companies |
| **database** | ❌ Bypass | Multiple companies per URL | All enabled | Directory/listing extraction |

## Implementation Tasks

### 🔧 Task 6: Fix Apollo Provider Routing (HIGH PRIORITY)

**Status**: Pending
**File**: `src/enrich_provider_router.py`
**Issue**: Apollo provider not being used for contact discovery in non-Apollo modes

- [ ] Fix Apollo provider routing logic in `_should_use_apollo_provider()`
- [ ] Fix constructor parameter mismatch in `ApolloEnrichProvider`
- [ ] Implement missing `enrich_contacts()` method
- [ ] Implement missing `find_email()` method
- [ ] Implement missing `validate_email()` method
- [ ] Add Apollo provider initialization logging
- [ ] Test Apollo contact discovery in all modes

#### Current Problem

```python
def _should_use_apollo_provider(self) -> bool:
    # Check if Apollo mode is enabled
    lead_generation_mode = self.icp_config.get("lead_generation_mode", "search")
    if lead_generation_mode != "apollo":  # ❌ THIS IS WRONG
        return False
```

#### Required Fix

```python
def _should_use_apollo_provider(self) -> bool:
    """
    Apollo provider is enabled when:
    1. Apollo enrichment provider is explicitly enabled, OR
    2. Apollo-first mode is active (inherits Apollo capability)
    """
    # Check explicit enrichment provider config (works in any mode)
    enrichment_providers = self.icp_config.get("enrichment_providers", {})
    apollo_enrichment_enabled = enrichment_providers.get("apollo", {}).get("enabled", False)

    if apollo_enrichment_enabled:
        return True

    # Check Apollo-first mode (inherits Apollo enrichment capability)
    lead_generation_mode = self.icp_config.get("lead_generation_mode", "search")
    if lead_generation_mode == "apollo":
        apollo_config = self.icp_config.get("apollo", {})
        return apollo_config.get("enrich", {}).get("enabled", False)

    return False
```



### 🏗️ Task 1: Update Orchestrator Mode Detection (MEDIUM PRIORITY)

**Status**: Pending
**File**: `src/orchestrator.py`

- [ ] Add "database" to valid modes list in `_detect_lead_generation_mode()`
- [ ] Update `_detect_lead_generation_mode()` method to handle database mode
- [ ] Add database mode pipeline routing in `run_pipeline()` method
- [ ] Update `_initialize_tools()` method to handle database mode tool initialization

#### Current Issue

```python
# Line 193-199
if mode not in ["search", "url", "apollo"]:
    self.logger.warning(f"Invalid lead_generation_mode: {mode}, defaulting to 'search'")
    mode = "search"
```

#### Required Changes

Update the valid modes list to include database mode and implement proper routing logic.

### 📝 Task 2: Enhance Configuration Schema (MEDIUM PRIORITY)

**Status**: Pending
**Files**: Configuration validation, schema files

- [ ] Update JSON schema to include "database" in `lead_generation_mode` enum
- [ ] Add new `database` configuration section to schema
- [ ] Add new `enrichment_providers` section to schema
- [ ] Update configuration validation logic
- [ ] Test schema backward compatibility with existing configs

#### Current Problem

Database functionality hidden inside `site_type` configuration, not elevated to proper lead generation mode.

#### New Configuration Structure

##### Existing Database Configuration Reference

The database mode configuration is already well-designed in `icp_config_database_mode.json`:
- Uses existing `site_type: "information_database"`
- Comprehensive `database_config` section with field mappings
- Custom extraction fields and instructions
- This existing pattern should be preserved and enhanced, not replaced

##### Database Mode Config Example

```json
{
  "name": "Dental Directory Extraction",
  "lead_generation_mode": "database",
  "database": {
    "sites": [
      {
        "name": "YellowPages Dental Directory",
        "base_domain": "yellowpages.com",
        "specific_urls": [
          "https://www.yellowpages.com/search?search_terms=dentist&geo_location_terms=California",
          "https://www.yellowpages.com/search?search_terms=dentist&geo_location_terms=Texas"
        ],
        "discovery_mode": "url_list"
      }
    ],
    "extraction": {
      "max_listings_per_site": 100,
      "parallel_extractions": 3,
      "use_pagination": true
    }
  },
  "enrichment_providers": {
    "apollo": { "enabled": true },
    "anymail_finder": { "enabled": true }
  }
}
```

##### Search Mode with Apollo Enrichment

```json
{
  "name": "Search with Apollo Backup",
  "lead_generation_mode": "search",
  "queries": ["dental practices California"],
  "enrichment_providers": {
    "apollo": { "enabled": true },
    "anymail_finder": { "enabled": true }
  }
}
```

##### Complete Configuration Architecture

```json
{
  "name": "Your ICP Name",

  // PRIMARY: Controls the main pipeline flow
  "lead_generation_mode": "search" | "apollo" | "url" | "database",

  // LEGACY: Remove this field (causes confusion)
  // "mode": "fast" ← DELETE THIS

  // APOLLO: Two separate configuration sections for different purposes
  "apollo": {
    // FOR APOLLO-FIRST MODE: When lead_generation_mode = "apollo"
    "enabled": true,
    "search": {
      "strategy": "company_first" | "person_first"
    },
    "enrich": {
      "enabled": true  // Required for Apollo-first mode
    }
  },

  "enrichment_providers": {
    // FOR APOLLO-AS-ENRICHMENT: Works in any pipeline mode
    "apollo": {
      "enabled": true  // Enables Apollo as contact discovery provider
    },
    "anymail_finder": { "enabled": true },
    "company_enrich": { "enabled": true }
  },

  // FOR DATABASE MODE: When lead_generation_mode = "database"
  "database": {
    "sites": [
      {
        "name": "Site Name",
        "base_domain": "example.com",
        "specific_urls": ["https://..."],
        "discovery_mode": "url_list" | "domain_crawl"
      }
    ],
    "extraction": {
      "max_listings_per_site": 100,
      "parallel_extractions": 3,
      "use_pagination": true
    }
  }
}
```

#### Configuration Precedence Rules

1. **`lead_generation_mode`** determines the **primary pipeline flow**
2. **`enrichment_providers.apollo.enabled`** enables Apollo as a **contact discovery provider** in any mode
3. **`apollo.enrich.enabled`** is **only required** for Apollo-first mode
4. **`"mode": "fast"`** should be **removed entirely** (legacy field causing confusion)

### 🚀 Task 3: Create Database Pipeline Logic (MEDIUM PRIORITY)

**Status**: Pending
**File**: `src/orchestrator.py`

- [ ] Implement `_run_database_pipeline()` method
- [ ] Implement `_create_lead_records_from_database_sites()` supporting method
- [ ] Implement `_validate_database_configuration()` supporting method
- [ ] Integrate database pipeline with existing crawl tool
- [ ] Test database pipeline end-to-end

#### New Method Required

```python
async def _run_database_pipeline(self) -> Dict[str, Any]:
    """
    Run database extraction pipeline.

    Pipeline Flow:
    1. Validate database configuration
    2. Create lead records from database sites
    3. Skip domain discovery (like url mode)
    4. Run crawl tool with database extraction
    5. Run enrich tool on discovered companies

    Returns:
        Pipeline results with extracted companies from database sites
    """
    self.logger.info("🚀 Running Database extraction pipeline")

    # Step 1: Validate database configuration
    database_config = self.icp_config.get("database", {})
    if not database_config or not database_config.get("sites"):
        raise ValueError("Database mode requires 'database.sites' configuration")

    # Step 2: Create lead records from database sites
    lead_records = self._create_lead_records_from_database_sites()

    # Step 3: Skip domain discovery (similar to url mode)
    self.logger.info("💰 Cost optimization: Bypassed domain discovery phase")

    # Step 4: Run crawl tool with database extraction
    # ... (implementation details)

    # Step 5: Run enrich tool
    # ... (implementation details)

    return pipeline_results
```

#### Supporting Methods Needed

The implementation requires several supporting methods and integration points as listed in the checkboxes above.

### 🔄 Task 4: Update Crawl Tool Integration (MEDIUM PRIORITY)

**Status**: Pending
**File**: `src/crawl.py`

- [ ] Update `_detect_site_type()` method to handle database lead generation mode
- [ ] Ensure database extraction runs when `lead_generation_mode == "database"`
- [ ] Preserve existing `site_type="information_database"` for backward compatibility
- [ ] Update extraction prompts and schemas for database mode
- [ ] Test crawl tool integration with database mode

#### Current State

Database extraction exists but is triggered by `site_type="information_database"`

#### Required Changes

The crawl tool needs updates to detect and handle database mode while preserving backward compatibility.

### 🎯 Task 5: Implement Database Mode Detection Logic (LOWER PRIORITY)

**Status**: Pending
**File**: `src/orchestrator.py`

- [ ] Implement `_detect_database_mode()` method
- [ ] Implement `_has_database_url_patterns()` supporting method
- [ ] Add auto-detection logic for database URL patterns
- [ ] Add legacy support warnings for `site_type="information_database"`
- [ ] Test database mode detection with various URL patterns

#### Detection Logic Flow

```python
def _detect_database_mode(self, icp_config: Dict[str, Any]) -> bool:
    """Detect if this should run as database mode"""
    # Explicit mode declaration takes precedence
    if icp_config.get("lead_generation_mode") == "database":
        return True

    # Legacy support: site_type=information_database
    if icp_config.get("site_type") == "information_database":
        self.logger.warning("⚠️ Using legacy site_type. Consider using lead_generation_mode='database'")
        return True

    # Auto-detection: Multiple URLs with database patterns
    specific_urls = icp_config.get("specific_urls", [])
    if len(specific_urls) > 5 and self._has_database_url_patterns(specific_urls):
        self.logger.info("🔍 Auto-detected database mode from URL patterns")
        return True

    return False

def _has_database_url_patterns(self, urls: List[str]) -> bool:
    """Detect if URLs follow database/directory patterns"""
    database_patterns = [
        "yellowpages.com/search",
        "yelp.com/search",
        "google.com/maps/search",
        "/directory/",
        "/listings/",
        "/search?",
        "page=", "offset=", "start="  # Pagination indicators
    ]

    matches = 0
    for url in urls:
        if any(pattern in url.lower() for pattern in database_patterns):
            matches += 1

    # If >60% of URLs match database patterns, likely a database extraction
    return matches / len(urls) > 0.6
```

### ✅ Task 7: Testing All Four Lead Generation Modes (FINAL PRIORITY)

**Status**: Pending

- [ ] Create and test Search Mode configuration
- [ ] Create and test Apollo Mode configuration
- [ ] Create and test URL Mode configuration
- [ ] Create and test Database Mode configuration
- [ ] Validate mode detection works correctly
- [ ] Validate pipeline routes to correct flow
- [ ] Validate Apollo provider availability in all modes
- [ ] Validate contact discovery works with Apollo in search/url/database modes
- [ ] Validate configuration validation catches invalid setups
- [ ] Validate backward compatibility is maintained

#### Test Cases Required

##### 1. Search Mode Test

```json
{
  "name": "Search Mode Test",
  "lead_generation_mode": "search",
  "queries": ["dental practices California"],
  "enrichment_providers": {
    "apollo": { "enabled": true },
    "anymail_finder": { "enabled": true }
  }
}
```

**Expected**: Domain discovery → crawl → enrich with Apollo contact discovery

##### 2. Apollo Mode Test

```json
{
  "name": "Apollo Mode Test",
  "lead_generation_mode": "apollo",
  "apollo": {
    "enabled": true,
    "search": { "strategy": "company_first" },
    "enrich": { "enabled": true }
  }
}
```

**Expected**: Pure Apollo pipeline, bypass domain/crawl

##### 3. URL Mode Test

```json
{
  "name": "Specific URLs Test",
  "lead_generation_mode": "specific_urls",
  "specific_urls": ["https://www.pacificdental.com/"],
  "enrichment_providers": {
    "apollo": { "enabled": true }
  }
}
```

**Expected**: Bypass domain → crawl single companies → enrich with Apollo

##### 4. Database Mode Test

```json
{
  "name": "Database Mode Test",
  "lead_generation_mode": "database",
  "database": {
    "sites": [{
      "name": "Test Directory",
      "base_domain": "yellowpages.com",
      "specific_urls": ["https://www.yellowpages.com/search?search_terms=dentist"]
    }]
  },
  "enrichment_providers": {
    "apollo": { "enabled": true }
  }
}
```

**Expected**: Bypass domain → extract multiple companies → enrich

#### Testing Validation Points

1. **Mode detection works correctly**
2. **Pipeline routes to correct flow**
3. **Apollo provider is available in all modes when enabled**
4. **Contact discovery works with Apollo in searc/url/database modes**
5. **Configuration validation catches invalid setups**
6. **Backward compatibility maintained**

## Implementation Priority Order

1. **🔧 Task 6: Fix Apollo Provider Routing** (High Priority)
   - Addresses immediate Apollo contact discovery issue
   - Required for current functionality

2. **🏗️ Task 1: Update Orchestrator Mode Detection** (Medium Priority)
   - Foundation for database mode support
   - Updates core pipeline routing

3. **📝 Task 2: Configuration Schema** (Medium Priority)
   - Defines database mode configuration structure
   - Updates schema validation

4. **🚀 Task 3: Database Pipeline Logic** (Medium Priority)
   - Creates database-specific pipeline flow
   - Integrates with existing orchestrator

5. **🔄 Task 4-5: Integration & Detection** (Lower Priority)
   - Updates crawl tool integration
   - Improves mode detection logic

6. **✅ Task 7: Testing** (Final Priority)
   - Validates all four modes thoroughly
   - Ensures configuration transitions work

## Benefits of This Architecture

1. **Clear Separation**: Each mode has distinct pipeline and configuration
2. **Backward Compatible**: Existing configs continue to work
3. **Flexible Enrichment**: Apollo can be used as enrichment provider in any mode
4. **Cost Optimized**: Each mode optimizes for its specific use case
5. **Scalable**: Easy to add new modes in the future
6. **Database Mode**: Elevates existing information database functionality to first-class lead generation mode

## Notes

- The database mode essentially elevates the existing information database functionality to a first-class lead generation mode
- Configuration becomes more discoverable and easier to use for directory/listing extraction
- Apollo provider routing fix is critical for immediate functionality
- All modes maintain existing enrichment provider flexibility
