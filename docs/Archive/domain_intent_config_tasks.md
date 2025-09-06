# Domain.py Intent_Config Integration Tasks

**Objective**: Complete the integration of `intent_config` in `src/domain.py` to ensure all domains passed through are properly filtered using ICP configuration.

**File**: `src/domain.py` - `LLMScorer._build_scoring_prompt()`

---

## Phase 1: Fix Missing Intent_Config Elements

### Task 1.1: Add Medium Intent Signals Support
- **Current Issue**: Only reads `high_intent` and `low_intent`, missing `medium_intent`
- **Fix**: Add medium intent signals reading
```python
# Add medium intent signals reading
medium_intent_signals = intent_config.get("intent_signals", {}).get("medium_intent", [])
```
- [ ] Implement medium intent signals reading
- [ ] Test that medium intent signals are properly extracted from config

### Task 1.2: Make Scoring Weights Fully Dynamic
- **Current Issue**: Scoring weights are hardcoded (+0.8, -0.5)
- **Fix**: Read from `intent_config.scoring_rules`
```python
scoring_rules = intent_config.get("scoring_rules", {})
high_weight = scoring_rules.get("high_intent_weight", 0.8)
medium_weight = scoring_rules.get("medium_intent_weight", 0.3)
low_weight = scoring_rules.get("low_intent_weight", -0.5)
base_score = scoring_rules.get("base_score", 0.3)
```
- [ ] Replace hardcoded scoring weights with dynamic config reading
- [ ] Add fallback values for missing config elements
- [ ] Test that weights are properly applied from config

### Task 1.3: Add Medium Intent to Prompt Building
- **Current Issue**: Medium intent signals not included in prompt
- **Fix**: Add medium intent section to prompt building logic
- [ ] Add medium intent signals section to prompt
- [ ] Ensure medium intent signals are limited to top 5 (like high/low)
- [ ] Test that medium intent appears in generated prompts

---

## Phase 2: Remove Hardcoded Business Logic

### Task 2.1: Remove Hardcoded Focus Area
- **Current Issue**: Line "Focus on whether this company would be interested in investing in AI/crypto hedge funds"
- **Fix**: Make focus area dynamic from ICP config
```python
# Extract focus from ICP text instead of hardcoding
focus_area = icp_config.get("icp_text", "").split(".")[0]
"Focus on whether this company matches: {focus_area}"
```
- [ ] Remove hardcoded focus area text
- [ ] Implement dynamic focus area extraction from ICP text
- [ ] Test that focus area is properly extracted and displayed

### Task 2.2: Make Scoring Instructions Dynamic
- **Current Issue**: Scoring instructions reference hardcoded values
- **Fix**: Use dynamic weights from config
```python
f"""
SCORING INSTRUCTIONS:
1. Start with base score {base_score}
2. Add +{high_weight} for each HIGH INTENT signal found
3. Add +{medium_weight} for each MEDIUM INTENT signal found
4. Subtract {low_weight} for each LOW INTENT signal found
"""
```
- [ ] Replace hardcoded scoring instructions with dynamic values
- [ ] Ensure all scoring weights reference config values
- [ ] Test that scoring instructions display correct weights

---

## Phase 3: Enhance Validation Logic

### Task 3.1: Add Industry Validation
- **Current Issue**: Missing industry-specific validation from config
- **Fix**: Read and apply industry validation criteria
```python
industry_validation = validation_criteria.get("industry_validation", {})
primary_industries = industry_validation.get("primary", [])
secondary_industries = industry_validation.get("secondary", [])
excluded_industries = industry_validation.get("excluded", [])
```
- [ ] Implement industry validation reading from config
- [ ] Add industry validation to prompt building
- [ ] Test that industry requirements are properly displayed

### Task 3.2: Add Geographic Validation
- **Current Issue**: Missing location-based validation
- **Fix**: Read location requirements from config
```python
location_requirements = icp_config.get("targeting", {}).get("location_types", [])
geographic_focus = icp_config.get("targeting", {}).get("geographic_focus", [])
```
- [ ] Implement geographic validation reading from config
- [ ] Add location requirements to prompt building
- [ ] Test that geographic requirements are properly displayed

### Task 3.3: Add Ownership Model Validation
- **Current Issue**: Missing ownership structure validation
- **Fix**: Read ownership requirements from config
```python
ownership_models = icp_config.get("targeting", {}).get("ownership_models", [])
excluded_ownership = icp_config.get("exclusion_criteria", {}).get("ownership_types", [])
```
- [ ] Implement ownership model validation reading from config
- [ ] Add ownership requirements to prompt building
- [ ] Test that ownership requirements are properly displayed

---

## Phase 4: Implement Advanced Filtering

### Task 4.1: Add Exclusion Criteria Support
- **Current Issue**: Not using `exclusion_criteria` from config
- **Fix**: Implement exclusion logic
```python
exclusion_criteria = icp_config.get("exclusion_criteria", {})
excluded_keywords = exclusion_criteria.get("excluded_keywords", [])
excluded_company_names = exclusion_criteria.get("excluded_company_names", [])
excluded_domains = exclusion_criteria.get("news_media_exclusions", {}).get("excluded_domains", [])
```
- [ ] Implement exclusion criteria reading from config
- [ ] Add excluded keywords, company names, and domains to prompt
- [ ] Test that exclusion criteria are properly applied

### Task 4.2: Add Size and Revenue Validation
- **Current Issue**: Missing financial criteria validation
- **Fix**: Read and apply financial thresholds
```python
max_assets = exclusion_criteria.get("max_assets_under_management_usd")
max_revenue = exclusion_criteria.get("max_annual_revenue_usd")
```
- [ ] Implement financial criteria validation reading from config
- [ ] Add size and revenue requirements to prompt building
- [ ] Test that financial criteria are properly displayed

### Task 4.3: Add Technology Stack Validation
- **Current Issue**: Missing technology requirements validation
- **Fix**: Read technology requirements from Apollo config
```python
required_technologies = icp_config.get("apollo", {}).get("search", {}).get("company_filters", {}).get("technologies", [])
```
- [ ] Implement technology stack validation reading from config
- [ ] Add technology requirements to prompt building
- [ ] Test that technology requirements are properly displayed

---

## Phase 5: Enhanced Prompt Engineering

### Task 5.1: Build Comprehensive Validation Prompt
- **Current Issue**: Prompt doesn't cover all validation criteria
- **Fix**: Build comprehensive validation section
```python
# Build comprehensive validation prompt
if required_attributes or disqualified_attributes or industry_validation:
    prompt += "\nVALIDATION CRITERIA:\n"
    
    if required_attributes:
        prompt += f"REQUIRED ATTRIBUTES (Must have ALL):\n"
        for attr in required_attributes:
            prompt += f"- {attr}\n"
    
    if disqualified_attributes:
        prompt += f"DISQUALIFYING ATTRIBUTES (Must NOT have ANY):\n"
        for attr in disqualified_attributes:
            prompt += f"- {attr}\n"
    
    if industry_validation:
        prompt += f"INDUSTRY REQUIREMENTS:\n"
        if primary_industries:
            prompt += f"Primary industries: {', '.join(primary_industries)}\n"
        if excluded_industries:
            prompt += f"Excluded industries: {', '.join(excluded_industries)}\n"
```
- [ ] Implement comprehensive validation prompt building
- [ ] Ensure all validation criteria are included
- [ ] Test that validation prompt is comprehensive and clear

### Task 5.2: Add Intent Source Guidance
- **Current Issue**: LLM doesn't know where to look for signals
- **Fix**: Include intent sources from config
```python
intent_sources = intent_config.get("intent_sources", [])
if intent_sources:
    prompt += f"\nLOOK FOR INTENT SIGNALS IN:\n"
    for source in intent_sources[:10]:  # Limit to top 10
        prompt += f"- {source}\n"
```
- [ ] Implement intent source guidance in prompt building
- [ ] Limit intent sources to top 10 to avoid prompt bloat
- [ ] Test that intent sources are properly displayed

---

## Phase 6: Scoring Logic Enhancement

### Task 6.1: Implement Bonus Scoring
- **Current Issue**: Missing bonus scoring from config
- **Fix**: Add bonus scoring logic
```python
# Apply bonus scoring from config
bonuses = scoring_rules.get("bonuses", {})
if "crypto_focus_bonus" in bonuses and crypto_signals_found:
    score += bonuses["crypto_focus_bonus"]
if "ai_focus_bonus" in bonuses and ai_signals_found:
    score += bonuses["ai_focus_bonus"]
```
- [ ] Implement bonus scoring reading from config
- [ ] Add bonus scoring logic to scoring function
- [ ] Test that bonus scoring is properly applied

### Task 6.2: Add Validation Failure Handling
- **Current Issue**: No clear handling of validation failures
- **Fix**: Implement validation failure logic
```python
# Check for validation failures
if any_disqualified_attributes_found:
    score = 0.0
    flags.append("disqualified_attribute")
if not all_required_attributes_found:
    score = 0.0
    flags.append("missing_required_attribute")
```
- [ ] Implement validation failure handling
- [ ] Add appropriate flags for validation failures
- [ ] Test that validation failures result in score 0.0

---

## Phase 7: Testing and Validation

### Task 7.1: Test with Crypto AI ICP Config
- **Purpose**: Ensure investment firm filtering works
- **Test Cases**: 
  - Investment firms with crypto/AI focus → High score
  - News media companies → Score 0.0, rejected
  - Consulting firms → Score 0.0, rejected
- [ ] Test investment firms with crypto/AI focus
- [ ] Test news media companies (should be rejected)
- [ ] Test consulting firms (should be rejected)
- [ ] Verify scoring accuracy and rejection logic

### Task 7.2: Test with Dental Practice ICP Config
- **Purpose**: Ensure healthcare practice filtering works
- **Test Cases**:
  - Multi-location dental practices → High score
  - Private equity backed → Score 0.0, rejected
  - Large franchises → Score 0.0, rejected
- [ ] Test multi-location dental practices
- [ ] Test private equity backed practices (should be rejected)
- [ ] Test large franchises (should be rejected)
- [ ] Verify scoring accuracy and rejection logic

### Task 7.3: Test Edge Cases
- **Purpose**: Ensure robust filtering
- **Test Cases**:
  - Mixed signals (some high, some low)
  - Missing required attributes
  - Size mismatches
  - Geographic mismatches
- [ ] Test mixed signal scenarios
- [ ] Test missing required attributes
- [ ] Test size mismatches
- [ ] Test geographic mismatches
- [ ] Verify edge case handling

---

## Phase 8: Performance Optimization

### Task 8.1: Add Prompt Caching
- **Current Issue**: Rebuilding prompts for each domain
- **Fix**: Cache prompts per ICP config hash
```python
def _get_cached_prompt(self, icp_config_hash: str) -> Optional[str]:
    return self.prompt_cache.get(icp_config_hash)
```
- [ ] Implement prompt caching mechanism
- [ ] Add config hash generation
- [ ] Test that caching improves performance
- [ ] Verify cache invalidation on config changes

### Task 8.2: Optimize Validation Logic
- **Current Issue**: Multiple config lookups per domain
- **Fix**: Pre-process config at initialization
```python
def _preprocess_icp_config(self, icp_config: Dict[str, Any]) -> Dict[str, Any]:
    # Extract and cache all validation criteria
    return processed_config
```
- [ ] Implement config preprocessing
- [ ] Cache validation criteria at initialization
- [ ] Test that preprocessing improves performance
- [ ] Verify all criteria are properly cached

---

## Implementation Priority

### High Priority (Complete First)
- [ ] Phase 1: Fix missing intent config elements
- [ ] Phase 2: Remove hardcoded logic

### Medium Priority
- [ ] Phase 3: Add validation logic
- [ ] Phase 4: Advanced filtering

### Low Priority
- [ ] Phase 5: Enhanced prompts
- [ ] Phase 6: Scoring enhancement

### Required
- [ ] Phase 7: Testing and validation

### Optional
- [ ] Phase 8: Performance optimization

---

## Expected Outcome

After completing these tasks, the Domain tool will:
- ✅ Use ALL `intent_config` elements dynamically
- ✅ Apply comprehensive validation criteria
- ✅ Filter out non-ICP domains effectively
- ✅ Provide accurate scoring based on ICP requirements
- ✅ Maintain full ICP-agnostic design
- ✅ Ensure only qualified domains pass through to Crawl stage

This will significantly improve the quality of leads passed through the pipeline while maintaining the system's flexibility for different ICP types.

---

## Notes

- **File Location**: `src/domain.py`
- **Class**: `LLMScorer._build_scoring_prompt()`
- **Dependencies**: ICP configuration files with `intent_config` sections
- **Testing**: Use existing ICP configs (`crypto_ai_hedge_fund_investors_icp_quick.json`, `icp_config_dental_quick.json`)
- **Validation**: Ensure all domains passing through meet ICP criteria
