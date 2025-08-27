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

### 🔧 Task 0: Fix Apollo Provider Routing (HIGH PRIORITY)

**Status**: ✅ COMPLETED
**File**: `src/enrich_provider_router.py`
**Issue**: Apollo provider not being used for contact discovery in non-Apollo modes

- [x] Fix Apollo provider routing logic in `_should_use_apollo_provider()`
- [x] Fix constructor parameter mismatch in `ApolloEnrichProvider`
- [x] Implement missing `enrich_contacts()` method
- [x] Implement missing `find_email()` method
- [x] Implement missing `validate_email()` method
- [x] Add Apollo provider initialization logging
- [x] Test Apollo contact discovery in all modes

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

#### Codebase Analysis Findings

**✅ What Exists:**
- `ApolloEnrichProvider` class is fully implemented
- Has `enrich_company()`, `enrich_contact()`, `bulk_enrich_contacts()` methods
- Constructor expects `apollo_config` parameter from `icp_config.get("apollo", {}).get("enrich", {})`

**❌ Critical Issues Found:**
1. **Routing Logic Broken**: Apollo provider only enabled in Apollo mode, preventing contact discovery in search/url modes
2. **Missing Methods**: `enrich_contacts()`, `find_email()`, `validate_email()` methods not implemented
3. **Constructor Mismatch**: Current initialization passes wrong config structure
4. **Provider Initialization**: Apollo provider not being initialized in non-Apollo modes

**🔍 Current Implementation Status:**
- **File**: `src/enrich_provider_router.py` lines 265-268
- **Impact**: Apollo contact discovery completely broken for search/url modes
- **Priority**: CRITICAL - affects current functionality, not just future database mode

**📋 Implementation Steps:**
1. **Fix routing logic** to enable Apollo provider in any mode when `enrichment_providers.apollo.enabled = true`
2. **Implement missing methods** following the pattern used by other providers
3. **Fix constructor parameter** to use correct config structure
4. **Add initialization logging** for debugging
5. **Test contact discovery** in all lead generation modes

**✅ Implementation Completed:**

**1. Fixed Apollo Provider Routing Logic:**
- Updated `_should_use_apollo_provider()` method to check both `enrichment_providers.apollo.enabled` and Apollo-first mode
- Apollo provider now works in search, url, and database modes when explicitly enabled
- Maintains backward compatibility with Apollo-first mode

**2. Fixed Constructor Parameter Mismatch:**
- Updated provider initialization to use correct configuration structure
- Added fallback logic for backward compatibility
- Improved error handling and logging

**3. Implemented Missing Methods:**
- `enrich_contacts()`: Discovers all contacts for a domain using Apollo API
- `find_email()`: Finds email for specific person using name and domain
- `validate_email()`: Validates email addresses using Apollo enrichment

**4. Enhanced Logging and Error Handling:**
- Added detailed logging for Apollo provider initialization
- Improved error messages and debugging information
- Added provider availability tracking

**5. Verified Functionality:**
- All 6 test cases passed successfully
- Apollo provider routing works correctly in all lead generation modes
- Contact discovery functionality restored for search/url/database modes



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

#### Required Code Changes

**1. Update `_detect_lead_generation_mode()` method:**
```python
def _detect_lead_generation_mode(self) -> str:
    mode = self.icp_config.get("lead_generation_mode", "search")
    
    # Add database to valid modes
    if mode not in ["search", "url", "apollo", "database"]:
        self.logger.warning(f"Invalid lead_generation_mode: {mode}, defaulting to 'search'")
        mode = "search"
    
    self.logger.info(f"🔍 Lead generation mode detected: {mode}")
    return mode
```

**2. Add database mode routing in `run_pipeline()`:**
```python
async def run_pipeline(self) -> Dict[str, Any]:
    # ... existing validation code ...
    
    # Determine pipeline mode and execute accordingly
    if self._should_run_apollo_pipeline():
        return await self._run_apollo_pipeline()
    elif self._should_run_database_pipeline():  # NEW
        return await self._run_database_pipeline()
    else:
        return await self._run_traditional_pipeline()

def _should_run_database_pipeline(self) -> bool:
    """Check if database mode is enabled."""
    mode = self._detect_lead_generation_mode()
    return mode == "database"
```

**3. Update `_initialize_tools()` method:**
```python
def _initialize_tools(self):
    mode = self._detect_lead_generation_mode()
    
    if mode == "apollo":
        # Apollo mode initialization
        self.apollo_tool = ApolloTool(self.icp_config, self.data_dir)
        self.domain_tool = None
        self.crawl_tool = CrawlTool(self.data_dir)
    elif mode == "database":  # NEW
        # Database mode initialization
        self.apollo_tool = None
        self.domain_tool = None  # Skip domain discovery
        self.crawl_tool = CrawlTool(self.data_dir)
    else:
        # Traditional/search/url mode initialization
        self.domain_tool = DomainTool(self.icp_config, self.data_dir)
        self.crawl_tool = CrawlTool(self.data_dir)
        self.apollo_tool = None
```

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

#### Required Schema Changes

**1. Update `schemas/extended_icp_config.json`:**
```json
{
  "lead_generation_mode": {
    "type": "string",
    "enum": ["search", "url", "apollo", "database"],
    "default": "search",
    "description": "Lead generation strategy: 'search' = Domain→Crawl→Enrich, 'url' = Specific URLs, 'apollo' = Apollo-first, 'database' = Directory extraction"
  },
  "enrichment_providers": {
    "type": "object",
    "properties": {
      "apollo": {
        "type": "object",
        "properties": {
          "enabled": { "type": "boolean", "default": false },
          "batch_size": { "type": "integer", "minimum": 1, "maximum": 100, "default": 25 }
        }
      },
      "anymail_finder": { "type": "object", "properties": { "enabled": { "type": "boolean", "default": true } } },
      "company_enrich": { "type": "object", "properties": { "enabled": { "type": "boolean", "default": true } } }
    }
  },
  "database": {
    "type": "object",
    "properties": {
      "sites": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": { "type": "string" },
            "base_domain": { "type": "string" },
            "specific_urls": { "type": "array", "items": { "type": "string" } },
            "discovery_mode": { "type": "string", "enum": ["url_list", "domain_crawl"] }
          }
        }
      },
      "extraction": {
        "type": "object",
        "properties": {
          "max_listings_per_site": { "type": "integer", "minimum": 1, "default": 100 },
          "parallel_extractions": { "type": "integer", "minimum": 1, "default": 3 },
          "use_pagination": { "type": "boolean", "default": true }
        }
      }
    }
  }
}
```

**2. Add validation logic in orchestrator:**
```python
def _validate_database_configuration(self) -> None:
    """Validate database mode configuration."""
    if self._detect_lead_generation_mode() != "database":
        return
    
    database_config = self.icp_config.get("database", {})
    if not database_config:
        raise ValueError("Database mode requires 'database' configuration section")
    
    sites = database_config.get("sites", [])
    if not sites:
        raise ValueError("Database mode requires at least one site in 'database.sites'")
    
    for i, site in enumerate(sites):
        if not site.get("base_domain"):
            raise ValueError(f"Site {i} missing required 'base_domain'")
        if not site.get("specific_urls"):
            raise ValueError(f"Site {i} missing required 'specific_urls'")
```

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

#### Required Method Implementations

**1. Main database pipeline method:**
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
    self._validate_database_configuration()
    
    # Step 2: Create lead records from database sites
    lead_records = self._create_lead_records_from_database_sites()
    
    # Step 3: Skip domain discovery (similar to url mode)
    self.logger.info("💰 Cost optimization: Bypassed domain discovery phase")
    
    # Step 4: Run crawl tool with database extraction
    crawl_payload = {
        "lead_records": lead_records,
        "icp_config": self.icp_config,
        "extraction_mode": "database"  # Signal to crawl tool
    }
    crawl_result = await self.crawl_tool.run(crawl_payload)
    
    # Step 5: Run enrich tool
    enrich_ready_leads = self._filter_enrich_ready_leads(crawl_result)
    if enrich_ready_leads:
        enrich_result = await self._run_enrich_tool(enrich_ready_leads)
    else:
        enrich_result = None
    
    return self._build_pipeline_results(crawl_result, enrich_result)
```

**2. Supporting methods:**
```python
def _create_lead_records_from_database_sites(self) -> List[Dict[str, Any]]:
    """Create lead records from database site configuration."""
    database_config = self.icp_config.get("database", {})
    sites = database_config.get("sites", [])
    lead_records = []
    
    for site in sites:
        base_domain = site["base_domain"]
        specific_urls = site["specific_urls"]
        
        # Create one lead record per site (crawl tool will extract multiple companies)
        lead_record = {
            "lead_id": f"database-site-{base_domain}",
            "domain": base_domain,
            "status": "scored",
            "company": {"name": f"Database Site: {base_domain}"},
            "contacts": [],
            "provenance": {
                "source": "database_mode",
                "site_name": site["name"],
                "discovery_mode": site.get("discovery_mode", "url_list"),
                "created_at": now_z()
            }
        }
        lead_records.append(lead_record)
    
    return lead_records

def _filter_enrich_ready_leads(self, crawl_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Filter leads that are ready for enrichment."""
    lead_records = crawl_result.get("data", {}).get("lead_records", [])
    return [r for r in lead_records if r.get("status") == "enrich_ready"]

async def _run_enrich_tool(self, enrich_ready_leads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run enrichment tool on ready leads."""
    enrich_payload = {
        "lead_records": enrich_ready_leads,
        "icp_config": self.icp_config,
    }
    return await run_enrich(enrich_payload)

def _build_pipeline_results(self, crawl_result: Dict[str, Any], enrich_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build final pipeline results."""
    return {
        "success": True,
        "pipeline_mode": "database",
        "metrics": {
            "companies_extracted": len(crawl_result.get("data", {}).get("lead_records", [])),
            "companies_enriched": len(enrich_result.get("data", {}).get("lead_records", [])) if enrich_result else 0
        },
        "data": {
            "crawl_result": crawl_result,
            "enrich_result": enrich_result
        }
    }
```

### 🔄 Task 4: Update Crawl Tool Integration (MEDIUM PRIORITY)

**Status**: Pending
**File**: `src/crawl.py`

- [ ] Update `_detect_site_type()` method to handle database lead generation mode
- [ ] Ensure database extraction runs when `lead_generation_mode == "database"`
- [ ] Preserve existing `site_type="information_database"` for backward compatibility
- [ ] Update extraction prompts and schemas for database mode
- [ ] Test crawl tool integration with database mode

#### Required Crawl Tool Updates

**1. Update `_detect_site_type()` method:**
```python
def _detect_site_type(self, icp_config: Dict[str, Any]) -> str:
    """Detect site type for extraction strategy."""
    
    # NEW: Check lead generation mode first
    lead_generation_mode = icp_config.get("lead_generation_mode", "search")
    if lead_generation_mode == "database":
        self.logger.info("🔍 Database mode detected - using database extraction strategy")
        return "information_database"
    
    # Legacy: Check explicit site_type flag
    site_type = icp_config.get("site_type")
    if site_type == "information_database":
        self.logger.warning("⚠️ Using legacy site_type. Consider using lead_generation_mode='database'")
        return "information_database"
    
    # Default: Single company extraction
    return "single_company"
```

**2. Add database mode extraction logic:**
```python
def _extract_from_database_site(self, domain: str, urls: List[str], icp_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract multiple companies from database/directory site."""
    database_config = icp_config.get("database", {})
    extraction_config = database_config.get("extraction", {})
    
    max_listings = extraction_config.get("max_listings_per_site", 100)
    parallel_extractions = extraction_config.get("parallel_extractions", 3)
    
    self.logger.info(f"🔍 Extracting up to {max_listings} companies from {domain}")
    
    # Use existing database extraction logic
    extracted_companies = []
    for url in urls[:max_listings]:
        company_data = await self._extract_company_from_url(url, icp_config)
        if company_data:
            extracted_companies.append(company_data)
    
    return extracted_companies
```

**3. Update extraction payload handling:**
```python
def _process_extraction_payload(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Process extraction payload based on mode."""
    icp_config = payload.get("icp_config", {})
    extraction_mode = payload.get("extraction_mode", "auto")
    
    if extraction_mode == "database" or self._detect_site_type(icp_config) == "information_database":
        return self._extract_database_companies(payload)
    else:
        return self._extract_single_company(payload)
```

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

#### Required Implementation

**1. Add database mode detection to orchestrator:**
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

**2. Integrate with mode detection:**
```python
def _detect_lead_generation_mode(self) -> str:
    """Enhanced mode detection with auto-detection support."""
    # Check explicit mode first
    explicit_mode = self.icp_config.get("lead_generation_mode")
    if explicit_mode:
        if explicit_mode not in ["search", "url", "apollo", "database"]:
            self.logger.warning(f"Invalid lead_generation_mode: {explicit_mode}, defaulting to 'search'")
            return "search"
        return explicit_mode
    
    # Auto-detection logic
    if self._detect_database_mode(self.icp_config):
        self.logger.info("🔍 Auto-detected database mode from configuration patterns")
        return "database"
    
    # Default to search mode
    return "search"
```

**3. Add legacy support warnings:**
```python
def _warn_legacy_configuration(self) -> None:
    """Warn about legacy configuration patterns."""
    if self.icp_config.get("site_type") == "information_database":
        self.logger.warning(
            "⚠️ Using legacy site_type='information_database'. "
            "Consider using lead_generation_mode='database' for better discoverability."
        )
    
    if "mode" in self.icp_config:
        self.logger.warning(
            "⚠️ Legacy 'mode' field detected. "
            "This field is deprecated and should be removed. "
            "Use lead_generation_mode instead."
        )
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

1. **🔧 Task 0: Fix Apollo Provider Routing** (High Priority)
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
