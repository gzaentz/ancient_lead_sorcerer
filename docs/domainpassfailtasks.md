# Domain Pass/Fail Prompt System Implementation Tasks

## 🎯 **Project Overview**

Replace the complex scoring system in the domain tool with a simple, evidence-based pass/fail prompt that works across all ICPs. This change will improve consistency, reduce false positives, and make the system more maintainable.

**Current System**: Complex scoring with multiple tiers, intent signals, validation criteria
**New System**: Binary pass/fail with clear, hard rules based on evidence

**⚠️ CRITICAL: This is a SYSTEM-WIDE ARCHITECTURAL CHANGE that affects the entire lead processing pipeline**

### **System-Wide Impact Analysis**

#### **Pipeline Flow Changes**

- **Domain Tool**: Float scoring (0.0-1.0) → Boolean pass/fail (True/False)
- **Orchestrator**: Threshold-based filtering → Direct boolean filtering
- **Crawl Tool**: No changes (already uses pre_pass boolean)
- **Enrich Tool**: No changes (already uses pre_pass boolean)

#### **Data Structure Changes**

- **Lead Records**: Remove threshold/filtering_strict fields from ICP section
- **Configuration**: Replace complex intent_config with simple icp_hard_rules string
- **Metrics**: Float-based statistics → Boolean pass/fail counts
- **Exports**: Boolean values in CSV/JSONL output

#### **Breaking Changes**

- **Configuration Migration**: All existing configs need icp_hard_rules field
- **API Changes**: score_domain returns boolean instead of float
- **Validation Changes**: New required field validation for icp_hard_rules

#### **Compatibility Impact**

- **Orchestrator**: ✅ Already uses pre_pass boolean (lines 769, 1019, 1154, 1185)
- **Apollo Mode**: ✅ Already uses pre_pass boolean
- **Database Mode**: ✅ Already uses pre_pass boolean
- **Export Functions**: ✅ Already handles boolean values

---

## **Task 1: Update `_build_scoring_prompt` Method**

**File**: `src/domain.py` (lines 117-209)
**Priority**: High
**Estimated Time**: 1 hour

### **System Impact**

- **Core Change**: Replaces 80+ lines of complex dynamic prompt building with 16-line static prompt
- **Configuration Dependency**: Switches from complex `intent_config` to simple `icp_hard_rules` string
- **Token Usage**: Reduces prompt complexity, potentially lowering LLM costs
- **Maintainability**: Eliminates complex conditional logic for different ICP types

### **Current Implementation**

```python
def _build_scoring_prompt(self, title: str, snippet: str, query: str, icp_config: Dict[str, Any]) -> str:
    # Complex dynamic prompt with intent signals, validation criteria, scoring instructions
    # 80+ lines of complex logic
```

**New Implementation**:

```python
def _build_scoring_prompt(self, title: str, snippet: str, query: str, icp_config: Dict[str, Any]) -> str:
    """Build simple pass/fail prompt using hard rules from ICP config."""
    icp_hard_rules = icp_config.get("icp_hard_rules", "No specific hard rules defined")

    return f"""You are a lead-scoring function. Analyze each domain against the ICP HARD rules using ONLY the provided inputs: (domain, snippet).

Do not use outside knowledge, assumptions, or inferred details. If evidence is absent or unclear, default to FAIL.

Output STRICTLY valid JSON (no line breaks, no code blocks, no extra fields):
{{"score":"<FAIL|PASS>","reason":"<≤40 words, explicitly cite snippet or domain evidence>"}}

Definitions:
FAIL – one or more HARD rules are not clearly satisfied based on domain/snippet.
PASS – all HARD rules are clearly satisfied.

ICP HARD rules:
{icp_hard_rules}

Domain: {title}
Snippet: {snippet}"""
```

### **Testing Requirements**

- [x] Test with valid `icp_hard_rules` configuration
- [x] Test with missing `icp_hard_rules` (should use default)
- [x] Verify prompt structure matches BRD exactly (16 lines max)
- [x] Test prompt generation for different ICP types

**Acceptance Criteria**:

- [x] Prompt matches BRD exactly (16 lines max)
- [x] Uses simple `icp_hard_rules` string from config
- [x] No complex scoring logic
- [x] Enforces 40-word reason limit
- [x] Strict JSON validation (no line breaks, no code blocks)

---

## **Task 2: Update `score_domain` Method**

**File**: `src/domain.py` (lines 211-280)
**Priority**: High
**Estimated Time**: 1 hour

### **System Impact**

- **API Change**: Changes return type from `Tuple[float, str, List[str], str, str]` to `Tuple[bool, str, List[str], str, str]`
- **Downstream Impact**: All callers must handle boolean instead of float score
- **Token Usage**: Reduces max_tokens from 500 to 100 (cost optimization)
- **Error Handling**: Simplified error handling with default to FAIL
- **JSON Parsing**: Changes from float score parsing to PASS/FAIL string parsing

### **Current Implementation**

```python
async def score_domain(self, title: str, snippet: str, query: str, icp_config: Dict[str, Any]) -> Tuple[float, str, List[str], str, str]:
    # Complex JSON parsing with score, reason, flags
    # Returns: (score, reason, flags, model_used, prompt_fingerprint)
```

**New Implementation**:

```python
async def score_domain(self, title: str, snippet: str, query: str, icp_config: Dict[str, Any]) -> Tuple[bool, str, List[str], str, str]:
    """Score a domain using simple pass/fail prompt."""
    async with self.semaphore_pool:
        prompt = self._build_scoring_prompt(title, snippet, query, icp_config)
        prompt_fingerprint = hashlib.sha256(prompt.encode()).hexdigest()

        try:
            response = await self.client.chat.completions.create(
                model=self.primary_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=100,
            )
            model_used = self.primary_model
        except Exception:
            response = await self.client.chat.completions.create(
                model=self.fallback_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=100,
            )
            model_used = self.fallback_model

        content = response.choices[0].message.content.strip()

        try:
            result = json.loads(content)
            score_str = result.get("score", "FAIL").upper()
            reason = result.get("reason", "No reason provided")

            # Enforce 40-word limit on reason
            if len(reason.split()) > 40:
                reason = " ".join(reason.split()[:40]) + "..."

            passed = score_str == "PASS"
            return passed, reason, [], model_used, prompt_fingerprint

        except json.JSONDecodeError:
            self.logger.warning(f"Failed to parse LLM response as JSON: {content}")
            return False, "Invalid JSON response from LLM", ["json_parse_error"], model_used, prompt_fingerprint
```

### **Testing Requirements**

- [x] Test PASS response parsing
- [x] Test FAIL response parsing
- [x] Test 40-word reason limit enforcement
- [x] Test invalid JSON handling (should default to FAIL)
- [x] Test boolean return type validation
- [x] Test reduced token usage (verify 100 max_tokens)

**Acceptance Criteria**:

- [x] Returns boolean instead of float score
- [x] Handles PASS/FAIL string responses
- [x] Enforces 40-word reason limit
- [x] Reduced token usage (100 vs 500)
- [x] Simplified error handling (matches BRD approach)
- [x] Defaults to FAIL on any parsing errors

---

## **Task 3: Update Domain Processing Logic**

**File**: `src/domain.py` (lines 700-900)
**Priority**: High
**Estimated Time**: 1 hour

### **System Impact**

- **Core Change**: Removes threshold-based logic, uses direct boolean assignment
- **Data Flow**: Changes from `score >= threshold` to direct `passed` boolean
- **Lead Record Updates**: Direct assignment of boolean values to `pre_pass` field
- **Status Updates**: Simplified status logic based on pass/fail result
- **Orchestrator Compatibility**: Ensures boolean values work with existing filtering logic

### **Current Implementation**

```python
def _process_domain(self, domain: str, query: str) -> Dict[str, Any]:
    # Complex scoring with threshold checking
    # score, reason, flags, model_used, prompt_fingerprint = await self.llm_scorer.score_domain(...)
    # passed = score >= threshold
```

**New Implementation**:

```python
def _process_domain(self, domain: str, query: str) -> Dict[str, Any]:
    # Simple pass/fail processing - no threshold logic needed
    passed, reason, flags, model_used, prompt_fingerprint = await self.llm_scorer.score_domain(...)

    # Create lead record
    lead_record = self._create_lead_record(domain, query)

    # Update with scoring results - DIRECT assignment, no threshold calculations
    lead_record["icp"]["pre_score"] = passed  # Boolean instead of float
    lead_record["icp"]["pre_reason"] = reason
    lead_record["icp"]["pre_pass"] = passed   # Direct assignment from LLM response
    lead_record["icp"]["pre_flags"] = flags
    lead_record["icp"]["scoring_meta"]["model"] = model_used
    lead_record["icp"]["scoring_meta"]["prompt_fingerprint"] = prompt_fingerprint

    # Update status based on pass/fail result
    if passed:
        lead_record["status"] = "scored"
        append_status(lead_record, "scored", "Passed hard rules validation")
    else:
        lead_record["status"] = "rejected"
        append_status(lead_record, "rejected", f"Failed hard rules: {reason}")

    return lead_record
```

### **Testing Requirements**

- [x] Test pass case (should set status to "scored")
- [x] Test fail case (should set status to "rejected")
- [x] Test boolean assignment to `pre_pass` field
- [x] Test status history updates
- [x] Test orchestrator filtering compatibility

**Acceptance Criteria**:

- [x] Simplified processing logic
- [x] Direct pass/fail assignment (no threshold calculations)
- [x] Clear status updates based on boolean result
- [x] Removed all threshold logic
- [x] Status reflects pass/fail decision directly

---

## **Task 4: Update Lead Record Creation**

**File**: `src/domain.py` (lines 557-650)
**Priority**: Medium
**Estimated Time**: 30 minutes

### **System Impact**

- **Data Structure**: Removes `threshold` and `filtering_strict` fields from ICP section
- **Schema Change**: Updates lead record structure to remove threshold-based fields
- **Configuration Dependency**: No longer depends on threshold configuration
- **Backward Compatibility**: Existing lead records will need migration for removed fields
- **Export Compatibility**: CSV/JSONL exports will reflect simplified structure

### **Current Implementation**

```python
def _create_lead_record(self, domain: str, query: str) -> Dict[str, Any]:
    return {
        "icp": {
            "pre_score": None,  # Float score
            "pre_reason": None,
            "pre_pass": None,   # Boolean
            "pre_flags": [],
            "scoring_meta": {
                "method": None,
                "model": None,
                "prompt_fingerprint": None,
                "temperature": None,
            },
            "threshold": self.icp_config.get("threshold", 0.7),
            "filtering_strict": self.icp_config.get("filtering_strict", True),
        }
    }
```

**New Implementation**:

```python
def _create_lead_record(self, domain: str, query: str) -> Dict[str, Any]:
    return {
        "icp": {
            "pre_score": None,  # Will be set to boolean (True/False)
            "pre_reason": None,
            "pre_pass": None,   # Boolean - main decision field
            "pre_flags": [],
            "scoring_meta": {
                "method": "pass_fail",
                "model": None,
                "prompt_fingerprint": None,
                "temperature": 0.0,
            },
            # REMOVED: threshold and filtering_strict - not needed for pass/fail system
        }
    }
```

### **Testing Requirements**

- [x] Test lead record creation with new structure
- [x] Verify removed fields are not present
- [x] Test boolean field assignments
- [x] Test export compatibility with simplified structure

**Acceptance Criteria**:

- [x] Simplified ICP structure
- [x] Removed threshold and filtering_strict fields completely
- [x] Set method to "pass_fail"
- [x] Boolean pre_score field ready for pass/fail values

---

## **Task 5: Add Configuration Validation**

**File**: `src/domain.py` (lines 480-516)
**Priority**: High
**Estimated Time**: 30 minutes

### **System Impact**

- **Configuration Breaking Change**: Makes `icp_hard_rules` a required field
- **Validation Enhancement**: Adds validation for new required field
- **Error Handling**: Provides clear error messages for missing configuration
- **Migration Requirement**: All existing configs must be updated with `icp_hard_rules`
- **Backward Compatibility**: Old configs without `icp_hard_rules` will fail validation

### **New Implementation**

```python
def _validate_icp_config(self) -> List[Dict[str, Any]]:
    """Validate ICP configuration including icp_hard_rules."""
    errors = []

    # Check required fields
    required_fields = ["name", "icp_text", "queries", "icp_hard_rules"]
    for field in required_fields:
        if field not in self.icp_config:
            errors.append(
                build_error(
                    ErrorCode.SCHEMA_VALIDATION,
                    context={"missing_field": field, "stage": TOOL_NAME},
                )
            )

    # Validate icp_hard_rules field
    icp_hard_rules = self.icp_config.get("icp_hard_rules")
    if icp_hard_rules and not isinstance(icp_hard_rules, str):
        errors.append(
            build_error(
                ErrorCode.SCHEMA_VALIDATION,
                context={
                    "invalid_field": "icp_hard_rules",
                    "stage": TOOL_NAME,
                    "message": "icp_hard_rules must be a string"
                },
            )
        )

    return errors
```

### **Testing Requirements**

- [x] Test with valid `icp_hard_rules` configuration
- [x] Test with missing `icp_hard_rules` (should fail validation)
- [x] Test with invalid `icp_hard_rules` type (should fail validation)
- [x] Test error message clarity and specificity

**Acceptance Criteria**:

- [x] Validates icp_hard_rules field is present and required
- [x] Validates icp_hard_rules is a string
- [x] Provides clear error messages for missing configuration
- [x] Simplified validation (removed complex template placeholder logic)

---

## **Task 6: Update Metrics Calculation**

**File**: `src/domain.py` (lines 1000-1100)
**Priority**: Medium
**Estimated Time**: 30 minutes

### **System Impact**

- **Metrics Simplification**: Changes from float-based statistics to boolean pass/fail counts
- **Performance**: Simplified calculation logic (boolean counting vs float comparisons)
- **Reporting**: Updates pass rate calculation to use boolean `pre_pass` field
- **Export Compatibility**: Metrics will reflect boolean-based counts in exports
- **Dashboard Impact**: Any monitoring dashboards will see simplified metrics

### **Current Implementation**

```python
def _calculate_metrics(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Complex scoring statistics
    # pass_rate = sum(1 for r in results if r["icp"]["pre_score"] >= threshold) / len(results)
```

**New Implementation**:

```python
def _calculate_metrics(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate simple pass/fail metrics."""
    total_count = len(results)
    pass_count = sum(1 for r in results if r.get("icp", {}).get("pre_pass", False))
    fail_count = total_count - pass_count

    return {
        "count_in": total_count,
        "count_out": pass_count,
        "pass_rate": pass_count / total_count if total_count > 0 else 0.0,
        "fail_count": fail_count,
        "duration_ms": self.duration_ms,
        "cost_usd": {
            "domain": self.total_domain_cost,
            "total": self.total_domain_cost,
        }
    }
```

### **Testing Requirements**

- [x] Test pass/fail count calculations
- [x] Test pass rate calculation accuracy
- [x] Test metrics with empty results
- [x] Test metrics with mixed pass/fail results
- [x] Verify cost calculations remain accurate

**Acceptance Criteria**:

- [x] Simple pass/fail counts (boolean-based)
- [x] Clear pass rate calculation using pre_pass field
- [x] Removed all complex scoring statistics
- [x] Added fail count metric for better visibility
- [x] Metrics align with BRD's simple approach

---

## **Task 7: Add Domain Hostname Extraction Validation**

**File**: `src/domain.py` (lines 641-668)
**Priority**: High
**Estimated Time**: 15 minutes

### **System Impact**

- **Data Quality**: Ensures consistent hostname-only domain extraction
- **BRD Compliance**: Matches BRD requirement for "Domain (hostname only, e.g., company.com)"
- **Input Validation**: Prevents path/query parameters from being included in domain field
- **Downstream Impact**: Ensures clean domain data for scoring and processing
- **Export Quality**: Clean domain names in CSV/JSONL exports

### **Current Implementation**

```python
def _normalize_serp_result(self, item: Dict[str, Any], query: str, page_index: int) -> Dict[str, Any]:
    # Extract domain from URL
    url = item.get("link", "")
    domain = normalize_domain(url)
```

**New Implementation**:

```python
def _normalize_serp_result(self, item: Dict[str, Any], query: str, page_index: int) -> Dict[str, Any]:
    """Normalize SERP result and extract hostname only."""
    # Extract domain from URL - ensure hostname only (no www, no paths)
    url = item.get("link", "")
    domain = normalize_domain(url)

    # Additional validation to ensure hostname only
    if domain and "." in domain:
        # Remove www. prefix if present
        if domain.startswith("www."):
            domain = domain[4:]
        # Ensure no paths or subdomains beyond www
        domain = domain.split("/")[0].split("?")[0]

    return {
        "url": url,
        "title": item.get("title", ""),
        "snippet": item.get("snippet", ""),
        "query": query,
        "page_index": page_index,
        "rank_on_page": item.get("rank", 0),
        "fetched_at": now_z(),
        "domain": domain,  # Hostname only as per BRD
    }
```

### **Testing Requirements**

- [x] Test <www>. prefix removal
- [x] Test path removal (e.g., /path/to/page)
- [x] Test query parameter removal (e.g., ?param=value)
- [x] Test subdomain handling
- [x] Test edge cases (empty URLs, malformed URLs)

**Acceptance Criteria**:

- [x] Extracts hostname only (no www, no paths)
- [x] Validates domain format
- [x] Matches BRD requirement: "Domain (hostname only, e.g., company.com)"

---

## **Task 8: Remove All Old Scoring System Remnants**

**File**: `src/domain.py` (lines 117-209, 768-911)
**Priority**: High
**Estimated Time**: 1 hour

### **System Impact**

- **Code Cleanup**: Removes 80+ lines of complex scoring logic
- **Maintainability**: Eliminates complex conditional logic and configuration dependencies
- **Performance**: Reduces code complexity and potential for bugs
- **Configuration Simplification**: Removes dependency on complex intent_config structure
- **Testing Simplification**: Reduces test complexity by removing edge cases

### **Current Implementation**

```python
def _build_scoring_prompt(self, title: str, snippet: str, query: str, icp_config: Dict[str, Any]) -> str:
    # Complex dynamic prompt with intent signals, validation criteria, scoring instructions
    # 80+ lines of complex logic with intent_config, validation_criteria, etc.
```

**New Implementation**:

```python
def _build_scoring_prompt(self, title: str, snippet: str, query: str, icp_config: Dict[str, Any]) -> str:
    """Build simple pass/fail prompt using hard rules from ICP config."""
    icp_hard_rules = icp_config.get("icp_hard_rules", "No specific hard rules defined")

    return f"""You are a lead-scoring function. Analyze each domain against the ICP HARD rules using ONLY the provided inputs: (domain, snippet).

Do not use outside knowledge, assumptions, or inferred details. If evidence is absent or unclear, default to FAIL.

Output STRICTLY valid JSON (no line breaks, no code blocks, no extra fields):
{{"score":"<FAIL|PASS>","reason":"<≤40 words, explicitly cite snippet or domain evidence>"}}

Definitions:
FAIL – one or more HARD rules are not clearly satisfied based on domain/snippet.
PASS – all HARD rules are clearly satisfied.

ICP HARD rules:
{icp_hard_rules}

Domain: {title}
Snippet: {snippet}"""
```

**Files to Clean Up**:

- Remove all `intent_config` references
- Remove all `validation_criteria` references
- Remove all `high_intent_signals` and `low_intent_signals` logic
- Remove all `size_validation` logic
- Remove all complex scoring instructions
- Remove all threshold-based processing in `_score_domains`

### **Testing Requirements**

- [x] Test that no old scoring references remain
- [x] Test that all complex logic is removed
- [x] Test that new simple logic works correctly
- [x] Test configuration compatibility (should work with simple icp_hard_rules)

**Acceptance Criteria**:

- [x] Completely removed old scoring system
- [x] No references to intent_config, validation_criteria, or size_validation
- [x] No threshold-based processing
- [x] Simple pass/fail logic only
- [x] Matches BRD exactly (16 lines max)

---

## **Task 9: Workflow Integration Verification**

**File**: `src/orchestrator.py` (lines 1017-1021)
**Priority**: High
**Estimated Time**: 15 minutes

### **System Impact**

- **Pipeline Compatibility**: Ensures boolean pass/fail values work with existing orchestrator filtering
- **Mode Compatibility**: Verifies Apollo, Database, and Search modes all work with new system
- **Data Flow**: Confirms lead records flow correctly through entire pipeline
- **Export Compatibility**: Ensures boolean values work in CSV/JSONL exports
- **Metrics Compatibility**: Verifies metrics calculation works with boolean values

### **Verification Points**

```python
# Orchestrator filtering logic (already compatible)
passing_leads = [
    r for r in lead_records if r.get("icp", {}).get("pre_pass")
]

# Metrics calculation (already compatible)
pass_rate = pass_count / count_out if count_out > 0 else 0.0
```

### **Testing Requirements**

- [x] Test orchestrator filtering with boolean values
- [x] Test metrics calculation with boolean values
- [x] Test Apollo mode compatibility
- [x] Test Database mode compatibility
- [x] Test Search mode compatibility
- [x] Test export functionality with boolean values

**Acceptance Criteria**:

- [x] Orchestrator filtering works with boolean `pre_pass` values
- [x] Metrics calculation works with boolean `pre_pass` values
- [x] No changes needed to orchestrator.py
- [x] Full pipeline compatibility verified
- [x] Apollo mode filtering also works with boolean values
- [x] Database mode filtering also works with boolean values

---

## **Task 10: Add Basic Unit Tests**

**File**: `tests/test_domain.py`
**Priority**: High
**Estimated Time**: 2 hours

### **System Impact**

- **Quality Assurance**: Ensures new pass/fail system works correctly
- **Regression Prevention**: Prevents old scoring system from being reintroduced
- **Configuration Testing**: Validates icp_hard_rules configuration works
- **Integration Testing**: Tests system-wide compatibility
- **Maintenance**: Provides test coverage for simplified system

### **Test Cases to Add**

```python
def test_build_scoring_prompt_simple():
    """Test new simple prompt format matches BRD exactly."""
    # Test with icp_hard_rules configuration
    # Test with no configuration
    # Verify prompt structure matches BRD exactly (15 lines max)
    # Verify no complex scoring logic

def test_score_domain_pass_fail():
    """Test pass/fail scoring with 40-word limit."""
    # Test PASS response parsing
    # Test FAIL response parsing
    # Test 40-word reason limit enforcement
    # Test invalid JSON handling
    # Test default to FAIL behavior

def test_process_domain_pass_fail():
    """Test domain processing with pass/fail."""
    # Test pass case
    # Test fail case
    # Test status updates
    # Test boolean assignment
    # Test no threshold logic

def test_validate_icp_config_hard_rules():
    """Test configuration validation."""
    # Test missing icp_hard_rules (required field)
    # Test invalid icp_hard_rules type
    # Test valid configuration
    # Test simplified validation

def test_domain_hostname_extraction():
    """Test domain hostname extraction validation."""
    # Test www. prefix removal
    # Test path removal
    # Test query parameter removal
    # Test hostname-only extraction

def test_old_scoring_system_removal():
    """Test that old scoring system is completely removed."""
    # Test no intent_config references
    # Test no validation_criteria references
    # Test no threshold-based processing
    # Test simple pass/fail only
```

### **Testing Requirements**

- [x] Test all new methods with valid inputs
- [x] Test all new methods with invalid inputs
- [x] Test edge cases and error conditions
- [x] Test configuration validation
- [x] Test system integration
- [x] Test BRD compliance

**Acceptance Criteria**:

- [x] All new methods have unit tests
- [x] 40-word reason limit is tested
- [x] Domain hostname extraction is tested
- [x] Edge cases are covered (missing config, invalid JSON, etc.)
- [x] Error handling is tested
- [x] BRD compliance is verified in tests
- [x] Old scoring system removal is verified

---

## **Task 11: Update ICP Configuration Examples**

**File**: `config/` directory
**Priority**: Low
**Estimated Time**: 30 minutes

### **System Impact**

- **Configuration Migration**: Updates all existing configs to use new icp_hard_rules format
- **Backward Compatibility**: Ensures all configs work with new validation requirements
- **Documentation**: Provides examples of proper icp_hard_rules format
- **Testing**: Enables testing with updated configurations
- **User Adoption**: Shows users how to migrate their configs

### **Files to Update**

- `config/crypto_ai_hedge_fund_investors_icp_quick.json`
- `config/dental_example_icp.json`
- `config/test_*.json`

**Add to each config**:

```json
{
  "icp_hard_rules": "Industry must be Investment Management, Venture Capital, or Private Equity. Company size must be 1-10 or 11-50 employees. Location must be United States, United Kingdom, or Hong Kong. Must NOT contain keywords: consulting, agency, news, media."
}
```

### **Testing Requirements**

- [x] Test all updated configs with domain tool
- [x] Verify icp_hard_rules validation works
- [x] Test different ICP types with appropriate rules
- [x] Verify rules are clear and actionable

**Acceptance Criteria**:

- [x] All test configs have `icp_hard_rules` field
- [x] Rules are appropriate for each ICP type
- [x] Simple string format (no complex objects)
- [x] Clear, actionable hard rules that can be validated from domain/snippet
- [x] Rules are concise and specific (≤100 words)

---

## **📋 Summary of Files to Modify**

| File | Priority | Estimated Time |
|------|----------|----------------|
| `src/domain.py` | High | 5.5 hours |
| `tests/test_domain.py` | High | 2 hours |
| `config/*.json` | Low | 30 minutes |
| `src/orchestrator.py` | High | 15 minutes (verification only) |

**Total Estimated Time**: 8 hours (1 day)

---

## **⏱️ Timeline**

| Task | Duration | Dependencies |
|------|----------|--------------|
| Task 1: Update prompt method | 1 hour | None |
| Task 2: Update score method | 1 hour | Task 1 |
| Task 3: Update processing logic | 1 hour | Task 2 |
| Task 4: Update lead record | 30 min | Task 3 |
| Task 5: Add configuration validation | 30 min | None |
| Task 6: Update metrics | 30 min | Task 4 |
| Task 7: Add domain hostname extraction | 15 min | None |
| Task 8: Remove old scoring system | 1 hour | Task 1-7 |
| Task 9: Workflow integration verification | 15 min | Task 1-8 |
| Task 10: Add unit tests | 2 hours | Task 1-9 |
| Task 11: Update configs | 30 min | None |

**Total**: 8 hours (1 day)

---

## **🎯 Success Criteria**

- [ ] New prompt generates consistent pass/fail results
- [ ] Works with simple `icp_hard_rules` string configuration
- [ ] Reduces false positives and improves accuracy
- [ ] Matches BRD requirements exactly (15 lines max, 40-word reason limit)
- [ ] Reduces token usage and processing time
- [ ] All tests pass with new system
- [ ] Simple to maintain and extend
- [ ] Full orchestrator workflow compatibility verified
- [ ] No threshold logic remaining in codebase
- [ ] Boolean pass/fail system working end-to-end
- [ ] Clear error messages for missing configuration
- [ ] Domain hostname extraction working correctly
- [ ] Old scoring system completely removed
- [ ] Strict JSON validation (no line breaks, no code blocks)

---

## **🔧 Key Improvements Made**

### **BRD Alignment**

- ✅ Simplified prompt to match BRD exactly (15 lines max)
- ✅ Removed complex scoring logic and intent signals
- ✅ Uses simple `icp_hard_rules` string configuration
- ✅ Defaults to FAIL when evidence is unclear
- ✅ Outputs strict JSON format as specified
- ✅ Enforces 40-word reason limit
- ✅ Extracts hostname only (no www, no paths)
- ✅ Strict JSON validation (no line breaks, no code blocks)

### **Workflow Integration**

- ✅ Boolean return types work with orchestrator filtering
- ✅ Direct pass/fail assignment (no threshold calculations)
- ✅ Metrics calculation compatible with boolean values
- ✅ Status updates work with pass/fail results
- ✅ Lead record structure remains compatible
- ✅ Apollo and Database mode compatibility verified

### **Code Simplification**

- ✅ Removed all threshold logic from domain processing
- ✅ Eliminated complex scoring calculations
- ✅ Reduced token usage from 500 to 100
- ✅ Simplified error handling (matches BRD approach)
- ✅ Clear separation of concerns
- ✅ Added configuration validation for `icp_hard_rules`
- ✅ Completely removed old scoring system
- ✅ Simplified domain hostname extraction
- ✅ Removed template variable complexity

---

## **🚨 Risk Mitigation**

| Risk | Mitigation |
|------|------------|
| Breaking existing functionality | Simple implementation, minimal changes |
| Inconsistent results | Follow BRD exactly, comprehensive testing |
| Configuration complexity | Use simple string field, no complex objects |
| Missing configuration | Add validation with clear error messages |
| Workflow incompatibility | Verify orchestrator filtering works with boolean values |
| Old system remnants | Complete removal with comprehensive testing |
| Domain extraction issues | Add validation and testing for hostname extraction |

---

## **🧪 System-Wide Testing Strategy**

### **Integration Testing Requirements**

- [ ] **Full Pipeline Test**: Domain → Orchestrator → Crawl → Enrich
- [ ] **Mode Compatibility**: Test Search, Apollo, and Database modes
- [ ] **Configuration Migration**: Test with old and new config formats
- [ ] **Export Testing**: Verify CSV/JSONL exports work with boolean values
- [ ] **Metrics Testing**: Verify all metrics calculations work correctly

### **End-to-End Test Scenarios**

1. **Search Mode**: Test with queries and icp_hard_rules
2. **Apollo Mode**: Test with Apollo lead generation and boolean filtering
3. **Database Mode**: Test with database extraction and boolean processing
4. **URL Mode**: Test with specific URLs and boolean scoring

### **Performance Testing**

- [ ] **Token Usage**: Verify reduced token consumption (100 vs 500)
- [ ] **Processing Speed**: Test domain processing performance
- [ ] **Memory Usage**: Verify reduced memory footprint
- [ ] **Cost Analysis**: Measure cost reduction from simplified prompts

### **Regression Testing**

- [ ] **Old System Removal**: Verify no old scoring logic remains
- [ ] **Configuration Validation**: Test all validation scenarios
- [ ] **Error Handling**: Test all error conditions
- [ ] **Edge Cases**: Test malformed inputs and edge cases

---

## **📞 Support and Questions**

For questions about this implementation plan, contact the development team.

**Last Updated**: 2025-09-06
**Version**: 4.0 (BRD-Aligned with Complete System Replacement)
**Status**: Ready for Implementation
