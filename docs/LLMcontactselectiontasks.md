# LLM-Based Contact Selection Implementation Tasks

## 🎯 **Main Objective**

Replace the current rule-based `select_best_contact()` function with an intelligent LLM-based approach that understands ICP context and business relevance.

## 📋 **Phase-by-Phase Task Breakdown**

### **Phase 1: Infrastructure & Dependencies**

- [ ] **Import LLM Client**

  - Add import for existing LLM client (from domain.py)
  - Ensure consistent model configuration (gpt-4o-mini)
  - Set up error handling for LLM failures

- [ ] **Create LLM Configuration**
  - Define model parameters (temperature, max_tokens, timeout)
  - Set up fallback behavior if LLM fails
  - Configure cost tracking for LLM calls

**Files to modify:** `src/enrich.py`, `src/common.py`

---

### **Phase 2: Core LLM Function Development**

- [ ] **Create New LLM-Based Function**

  - `async def select_best_contact_llm(contacts, icp_config) -> Optional[str]`
  - Handle async/await properly
  - Return contact_id of best contact

- [ ] **Build Dynamic Prompt Construction**

  - Extract ICP text from config
  - Format contact list for LLM consumption
  - Include role priorities and business context
  - Make prompt ICP-specific and actionable
  - Store base prompt template in `config/` or `docs/prompts/`

- [ ] **Implement Contact Formatting**
  - `def format_contacts_for_llm(contacts) -> str`
  - Convert contact dictionaries to readable text
  - Include key fields: name, role, company, seniority, decision_maker status
  - Handle missing/empty fields gracefully
  - Cap at reasonable number of contacts to avoid token limits

**Files to modify:** `src/enrich.py`

---

### **Phase 3: LLM Integration & Response Handling**

- [ ] **Implement Response Schema & Validation**

  - Require LLM to respond with JSON: `{ "contact_id": "123" }`
  - `def validate_llm_response(llm_response: str) -> bool`
  - Validate response format before parsing
  - Ensure returned contact_id exists in contacts list

- [ ] **Make LLM API Call**

  - Use existing LLM client infrastructure
  - Handle API rate limits and timeouts
  - Implement retry logic for failed calls

- [ ] **Parse LLM Response**

  - `def extract_contact_id(llm_response: str) -> Optional[str]`
  - Extract contact_id from LLM JSON response
  - Handle various response formats gracefully
  - Validate that returned contact_id exists in contacts list

- [ ] **Implement Fallback Logic**
  - If LLM fails → use existing rule-based function
  - If LLM returns invalid contact_id → use existing rule-based function
  - Log fallback usage for monitoring

**Files to modify:** `src/enrich.py`

---

### **Phase 4: Fallback Helper & Integration**

- [ ] **Create Fallback Helper Function**

  - `async def llm_with_fallback(fn_llm, fn_rule_based, *args, **kw)`
  - Centralizes fallback logic
  - Simplifies error handling across the system
  - Logs all fallback events consistently

- [ ] **Update Main Enrichment Logic**

  - Replace calls to `select_best_contact()` with `select_best_contact_llm()`
  - Pass ICP config to the new function
  - Maintain existing function signature for compatibility

- [ ] **Update Contact Selection Calls**
  - Find all places where `select_best_contact()` is called
  - Update to use new LLM-based function
  - Ensure ICP config is available at call sites

**Files to modify:** `src/enrich.py`, `src/orchestrator.py`

---

### **Phase 5: Testing & Validation**

- [ ] **Create Test Cases**

  - Test with DSVfund ICP (should prioritize family office/VC contacts)
  - Test with dental practice ICP (should prioritize practice owners)
  - Test with various contact combinations
  - Test fallback to rule-based when LLM fails
  - Mock httpx.AsyncClient to force timeouts/429s for retry coverage
  - Add property-based tests for `format_contacts_for_llm()` with random missing fields
  - Use golden-file tests for prompt generation to detect prompt drift

- [ ] **Validate LLM Responses**
  - Ensure LLM consistently returns valid contact_ids
  - Test prompt variations and edge cases
  - Validate that LLM understands ICP context
  - Test schema validation with malformed responses

**Files to modify:** `tests/test_enrich.py`, `tests/test_llm_contact_selection.py`

---

### **Phase 6: Performance & Cost Optimization**

- [ ] **Implement Caching**

  - Cache LLM responses for same contact sets + ICP id
  - Avoid repeated LLM calls for identical data
  - Set appropriate cache TTL
  - Guard against very large contact lists

- [ ] **Cost Tracking Integration**
  - Track LLM costs in existing cost system using `build_metrics` and `recompute_total_cost()`
  - Add LLM cost to contact enrichment costs
  - Monitor cost per contact selection
  - Add `model`, `prompt_tokens`, `completion_tokens`, `cost_usd` fields to evidence JSON

**Files to modify:** `src/enrich.py`, `src/common.py`

---

### **Phase 7: Error Handling & Monitoring**

- [ ] **Comprehensive Error Handling**

  - LLM API failures
  - Invalid responses
  - Timeout scenarios
  - Rate limiting

- [ ] **Logging & Monitoring**
  - Log LLM calls and responses (redact PII by default)
  - Track success/failure rates
  - Monitor response quality
  - Log fallback usage

**Files to modify:** `src/enrich.py`

---

### **Phase 8: Configuration & Tuning**

- [ ] **Make LLM Configurable**

  - Allow different models per ICP
  - Configurable temperature and token limits
  - Customizable prompts per ICP type

- [ ] **Prompt Engineering**
  - Optimize prompt for consistent responses
  - Test different prompt variations
  - Ensure LLM understands business context

**Files to modify:** `src/enrich.py`, ICP config files

---

### **Phase 9: Documentation & Maintenance**

- [ ] **Update Documentation**

  - Document new LLM-based approach
  - Explain fallback behavior
  - Document configuration options
  - Add section to `docs/enrichment_architecture.md` describing new selection flow

- [ ] **Create Maintenance Procedures**
  - Monitor LLM performance
  - Update prompts based on results
  - Handle LLM API changes

**Files to modify:** `docs/`, `README.md`

---

## 🔧 **Technical Implementation Details**

### **New Functions to Create:**

```python
async def select_best_contact_llm(contacts, icp_config)
def format_contacts_for_llm(contacts)
def extract_contact_id(llm_response)
def build_icp_specific_prompt(icp_config, contacts)
def validate_llm_response(llm_response)
async def llm_with_fallback(fn_llm, fn_rule_based, *args, **kw)
```

### **Configuration Updates:**

- Add LLM model selection to ICP configs
- Add prompt customization options
- Add cost tracking for LLM calls
- Store base prompt templates in config/docs

### **Example LLM Prompt for DSVfund:**

```
ICP: "Accredited, crypto-savvy capital allocators, HNW individuals, family offices, and digital-asset fund-of-funds, able to write $100-500k checks and seeking asymmetric exposure to decentralized-AI tokens like Bittensor/TAO"

Select the BEST contact who can actually allocate capital or make investment decisions. Prioritize:
- Family office decision makers
- Investment fund founders/managers
- Capital allocators with crypto exposure
- HNW individuals with investment capacity

AVOID: Marketing executives, consultants, or people without investment decision-making power.

Contacts: [formatted list with roles, companies, seniority]

Return ONLY a JSON response in this exact format:
{ "contact_id": "123" }
```

---

## ⏱️ **Estimated Effort & Timeline**

### **Phase Breakdown:**

- **Phase 1-3**: 2-3 hours (core development)
- **Phase 4-5**: 1-2 hours (integration & testing)
- **Phase 6-8**: 1-2 hours (optimization & monitoring)
- **Phase 9**: 1 hour (documentation)

### **Total Estimated Time:** 5-8 hours

### **Dependencies:**

- Existing LLM client infrastructure from domain.py
- ICP config structure
- Contact data format consistency

---

## 🎯 **Success Criteria**

### **Functional Requirements:**

- [ ] LLM successfully selects best contact based on ICP context
- [ ] Fallback to rule-based system when LLM fails
- [ ] Cost tracking includes LLM calls
- [ ] Performance meets existing system requirements

### **Quality Requirements:**

- [ ] LLM consistently returns valid contact_ids
- [ ] Contact selection aligns with ICP business goals
- [ ] System gracefully handles LLM failures
- [ ] Cost per contact selection remains reasonable

### **Testing Requirements:**

- [ ] Unit tests for all new functions
- [ ] Integration tests with real ICP configs
- [ ] Performance tests for LLM response times
- [ ] Fallback behavior validation
- [ ] Schema validation testing
- [ ] Property-based testing for edge cases

---

## 🚀 **Next Steps**

1. **Start with Phase 1**: Set up LLM client infrastructure
2. **Implement core function**: Create `select_best_contact_llm()`
3. **Test with DSVfund ICP**: Validate contact selection quality
4. **Integrate gradually**: Replace rule-based system incrementally
5. **Monitor and optimize**: Tune prompts and performance

---

## 📝 **Notes**

- Maintain backward compatibility during transition
- Document all LLM prompts for future optimization
- Consider A/B testing between rule-based and LLM-based approaches
- Monitor LLM costs and adjust model selection as needed
- Ensure PII in prompts is minimized and logging redacts sensitive data
- Use JSON response format to eliminate brittle string parsing
- Implement centralized fallback helper for cleaner error handling
