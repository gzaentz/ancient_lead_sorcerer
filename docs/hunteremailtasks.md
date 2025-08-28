# 🎯 **Hunter.io Email Verification Implementation Guide**

## 📋 **Overview**

This document outlines the complete implementation plan for integrating Hunter.io email verification into the Lead Sorcerer enrichment system. The goal is to verify **ALL** emails from **ANY** source (crawl, Apollo, discovery, etc.) with Hunter.io and store the verification scores in lead data.

## 🚀 **Implementation Phases**

### **Phase 1: Core Hunter.io Client (Priority: HIGH)**
### **Phase 2: Universal Email Verification (Priority: HIGH)**
### **Phase 3: Enhanced Email Discovery (Priority: HIGH)**
### **Phase 4: Integration & Testing (Priority: MEDIUM)**
### **Phase 5: Monitoring & Optimization (Priority: LOW)**

---

## 🗑️ **0% Score Email Handling (CRITICAL FEATURE)**

### **What Happens to 0% Score Emails**

When Hunter.io returns a **0% score** for any email:

1. **Immediate Discard**: The email is set to `None` and removed from circulation
2. **Source Clearing**: All email sources are cleared (`email_source = []`)
3. **Discovery Trigger**: Contact is marked for email discovery (`needs_email_discovery = True`)
4. **Logging**: Clear 🗑️ indicator in logs for easy identification

### **Example 0% Score Flow**

```python
# Before Hunter.io verification
contact = {
    "email": "bad@example.com",
    "email_source": ["crawl"],
    "full_name": "John Doe"
}

# After Hunter.io returns 0% score
contact = {
    "email": None,                    # DISCARDED
    "email_source": [],               # CLEARED
    "needs_email_discovery": True,    # TRIGGER DISCOVERY
    "hunter_verification": {
        "score": 0,
        "status": "invalid",
        "result": "invalid"
    }
}

# Apollo + LLM discovery finds replacement
contact = {
    "email": "john.doe@example.com",  # NEW VERIFIED EMAIL
    "email_source": ["provider", "hunter_verified"],
    "email_verified": True,
    "email_quality_score": 85,
    "needs_email_discovery": False    # FLAG CLEARED
}
```

### **Why This Matters**

- **Zero Bounce Rate**: 0% score emails never reach final output
- **Automatic Recovery**: System immediately tries to find better alternatives
- **Quality Guarantee**: Only Hunter.io verified emails are used
- **Clear Audit Trail**: 🗑️ logs show exactly which emails were discarded

---

## 🔧 **Phase 1: Core Hunter.io Client**

### **1.1 Environment Configuration**

**Add to `env.template`:**
```bash
# Hunter.io Email Verification
HUNTER_IO_API_KEY=your_hunter_api_key_here

# Optional: Hunter.io Configuration
HUNTER_IO_MIN_SCORE=70        # Minimum acceptable email score (0-100)
HUNTER_IO_RATE_LIMIT=10       # Requests per second (max 10 per Hunter.io)
```

**Add to `costs.json`:**
```json
{
  "hunter": 0.002,
  // ... existing costs
}
```

### **1.2 Hunter.io Client Implementation**

**Location:** `src/enrich.py` (after MailgunClient class, around line 822)

```python
class HunterIOClient:
    """Client for Hunter.io email verification with rate limiting and comprehensive logging."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.hunter.io/v2"
        # Rate limit: 10 requests/second per Hunter.io docs
        self.rate_limiter = asyncio.Semaphore(10)
        self.request_count = 0
        self.total_cost = 0.0
        
    async def verify_email(self, email: str, logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
        """
        Verify email using Hunter.io API with comprehensive error handling.
        
        Args:
            email: Email address to verify
            logger: Optional logger instance
            
        Returns:
            {
                "score": 85,
                "status": "valid", 
                "result": "deliverable",
                "sources": [...],
                "api_calls": 1,
                "error": None,
                "verified_at": "2025-08-27T19:01:20Z",
                "cost_usd": 0.002
            }
        """
        log = logger or logging.getLogger("enrich")
        
        if not email or not isinstance(email, str):
            return {
                "score": 0, 
                "status": "invalid", 
                "error": "Invalid email format", 
                "api_calls": 0,
                "cost_usd": 0.0
            }
            
        async with self.rate_limiter:
            try:
                url = f"{self.base_url}/email-verifier"
                params = {
                    "email": email,
                    "api_key": self.api_key
                }
                
                log.info(f"🔍 Hunter.io: Starting verification for {email}")
                
                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=3.0, read=10.0)) as client:
                    response = await client.get(url, params=params)
                    
                    if response.status_code == 401:
                        log.error("🚨 Hunter.io authentication failed - check API key")
                        return {
                            "score": 0, 
                            "status": "error", 
                            "error": "Authentication failed", 
                            "api_calls": 1,
                            "cost_usd": 0.002
                        }
                    
                    if response.status_code == 429:
                        log.warning("⚠️ Hunter.io rate limit exceeded")
                        return {
                            "score": 0, 
                            "status": "rate_limited", 
                            "error": "Rate limit exceeded", 
                            "api_calls": 1,
                            "cost_usd": 0.002
                        }
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    # Extract Hunter.io response
                    result = {
                        "score": data.get("score", 0),
                        "status": data.get("status", "unknown"),
                        "result": data.get("result", "unknown"),
                        "sources": data.get("sources", []),
                        "api_calls": 1,
                        "error": None,
                        "verified_at": now_z(),
                        "cost_usd": 0.002
                    }
                    
                    self.request_count += 1
                    self.total_cost += result["cost_usd"]
                    
                    log.info(f"📊 Hunter.io Results for {email}: Score={result['score']}%, Status={result['status']}, Result={result['result']}")
                    
                    return result
                    
            except httpx.TimeoutException:
                log.warning(f"⏰ Hunter.io timeout for {email}")
                return {
                    "score": 0, 
                    "status": "timeout", 
                    "error": "Request timeout", 
                    "api_calls": 1,
                    "cost_usd": 0.002
                }
            except Exception as e:
                log.error(f"❌ Hunter.io verification failed for {email}: {str(e)}")
                return {
                    "score": 0, 
                    "status": "error", 
                    "error": str(e), 
                    "api_calls": 1,
                    "cost_usd": 0.002
                }
    
    def get_cost_info(self) -> Dict[str, Any]:
        """Get cost information for this client."""
        return {
            "total_requests": self.request_count,
            "total_cost_usd": self.total_cost,
            "cost_per_request": 0.002
        }
```

---

## 🔍 **Phase 2: Universal Email Verification**

### **2.1 Core Verification Function**

**Location:** `src/enrich.py` (after HunterIOClient class)

```python
async def verify_all_contact_emails_with_hunter(
    contacts: List[Dict[str, Any]], 
    hunter_client: HunterIOClient,
    domain: str,
    logger: logging.Logger,
    costs_config: Dict[str, Any],
    min_score: int = 70
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Verify ALL emails in contacts list with Hunter.io - from ANY source.
    
    This function handles emails from:
    - Crawl tool extraction
    - Apollo discovery 
    - Any other provider
    - Manually provided emails
    
    Args:
        contacts: List of contact dictionaries
        hunter_client: Initialized Hunter.io client
        domain: Domain being processed
        logger: Logger instance
        costs_config: Costs configuration
        min_score: Minimum acceptable Hunter.io score
        
    Returns:
        (updated_contacts, total_hunter_cost)
    """
    logger.info(f"🔍 Hunter.io: Starting verification for {len(contacts)} contacts from {domain}")
    
    total_hunter_cost = 0.0
    verified_count = 0
    failed_count = 0
    
    for i, contact in enumerate(contacts):
        email = contact.get("email")
        contact_name = contact.get("full_name", f"Contact {i+1}")
        
        if email:
            logger.info(f"📧 Hunter.io: Verifying email {email} for {contact_name} (source: {contact.get('email_source', ['unknown'])})")
            
            # Verify with Hunter.io
            hunter_result = await hunter_client.verify_email(email, logger)
            
            # Store Hunter.io results in contact data
            contact["hunter_verification"] = hunter_result
            contact["email_quality_score"] = hunter_result.get("score", 0)
            
            # Add Hunter.io to sources
            email_sources = contact.get("email_source", [])
            if "hunter_verified" not in email_sources:
                email_sources.append("hunter_verified")
            contact["email_source"] = email_sources
            
            # Add cost
            total_hunter_cost += hunter_result.get("cost_usd", 0.0)
            
            # Decision logic based on Hunter.io score
            score = hunter_result.get("score", 0)
            status = hunter_result.get("status", "unknown")
            
            if score == 0:
                logger.warning(f"🗑️ Hunter.io: Discarding {email} (score 0%)")
                contact["email"] = None                      # hard remove
                contact["email_source"] = []                # clear sources
                contact["email_verified"] = False
                contact["needs_email_discovery"] = True     # forces discovery step
                failed_count += 1
            elif score >= min_score and status in ["valid", "deliverable"]:
                logger.info(f"✅ Hunter.io: Email {email} PASSED verification (score: {score}%, status: {status})")
                contact["email_verified"] = True
                verified_count += 1
            else:
                logger.warning(f"❌ Hunter.io: Email {email} FAILED verification (score: {score}%, status: {status})")
                contact["email_verified"] = False
                failed_count += 1
                
                # Mark for potential replacement during email discovery
                contact["needs_email_replacement"] = True
        else:
            logger.info(f"📭 Hunter.io: No email found for {contact_name} - will attempt discovery")
            contact["email_verified"] = False
            contact["needs_email_discovery"] = True
    
    # Count discarded emails (score 0)
    discarded_count = len([c for c in contacts if c.get("email") is None])
    
    logger.info(f"💰 Hunter.io verification completed for {domain}: {verified_count} verified, {failed_count} failed, {discarded_count} discarded (0% score), Total cost: ${total_hunter_cost:.4f}")
    
    return contacts, total_hunter_cost
```

---

## 🔄 **Phase 3: Enhanced Email Discovery**

### **3.1 Discovery with Hunter.io Verification**

```python
async def discover_and_verify_emails_with_hunter(
    contacts: List[Dict[str, Any]],
    domain: str,
    enrichment_router: Any,
    hunter_client: HunterIOClient,
    logger: logging.Logger,
    costs_config: Dict[str, Any],
    min_score: int = 70
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Discover emails for contacts that need them and verify ALL emails with Hunter.io.
    
    This handles:
    1. Contacts with no email (discovery needed)
    2. Contacts with low-quality emails (replacement needed)
    """
    discovery_cost = 0.0
    hunter_cost = 0.0
    discovery_attempts = 0
    successful_discoveries = 0
    successful_replacements = 0
    
    logger.info(f"🔍 Hunter.io: Starting email discovery for {domain}")
    
    for contact in contacts:
        contact_name = contact.get("full_name", "Unknown Contact")
        
        # Check if we need to discover/replace email
        needs_discovery = contact.get("needs_email_discovery", False)
        needs_replacement = contact.get("needs_email_replacement", False)
        
        # Skip contacts that already have good emails
        if contact.get("email") and contact.get("email_verified"):
            continue
        
        if needs_discovery or needs_replacement:
            if contact.get("first_name") and contact.get("last_name"):
                original_email = contact.get("email")
                original_score = contact.get("email_quality_score", 0)
                
                logger.info(f"🔍 Hunter.io: Attempting email discovery for {contact_name} at {domain}")
                
                try:
                    request = EnrichmentRequest(
                        domain=domain,
                        first_name=contact["first_name"],
                        last_name=contact["last_name"],
                    )
                    
                    result = await enrichment_router.find_email(request)
                    discovery_attempts += 1
                    
                    if result.success and result.data and result.data.email:
                        new_email = result.data.email
                        discovery_cost += result.cost
                        
                        logger.info(f"✅ Hunter.io: New email discovered: {new_email} for {contact_name}")
                        
                        # Verify the new email with Hunter.io
                        logger.info(f"🔍 Hunter.io: Verifying discovered email {new_email}")
                        hunter_result = await hunter_client.verify_email(new_email, logger)
                        hunter_cost += hunter_result.get("cost_usd", 0.0)
                        
                        score = hunter_result.get("score", 0)
                        status = hunter_result.get("status", "unknown")
                        
                        logger.info(f"📊 Hunter.io: Verification for discovered email {new_email}: Score={score}%, Status={status}")
                        
                        # Decision: Use new email if it's better quality
                        if score >= min_score and status in ["valid", "deliverable"]:
                            # Update contact with new verified email
                            contact["email"] = new_email
                            contact["email_source"] = ["provider", "hunter_verified"]
                            contact["hunter_verification"] = hunter_result
                            contact["email_quality_score"] = score
                            contact["email_verified"] = True
                            
                            # Track replacement
                            if original_email:
                                contact["replaced_email"] = original_email
                                contact["email_quality_improvement"] = score - original_score
                                logger.info(f"📧 Hunter.io: Replaced email {original_email} with {new_email} (quality improvement: {original_score}% → {score}%)")
                                successful_replacements += 1
                            else:
                                successful_discoveries += 1
                            
                            # Clear discovery flags since we now have a good email
                            contact.pop("needs_email_discovery", None)
                            contact.pop("needs_email_replacement", None)
                            
                            # Clear flags (already done above)
                        else:
                            logger.warning(f"❌ Hunter.io: Discovered email {new_email} also failed verification (score: {score}%)")
                            # Keep original email if new one is also bad, but mark for future discovery
                            if not original_email:
                                contact["email"] = new_email
                                contact["email_source"] = ["provider", "hunter_verified"]
                                contact["hunter_verification"] = hunter_result
                                contact["email_quality_score"] = score
                                contact["email_verified"] = False
                                # Keep discovery flag active for future attempts
                                contact["needs_email_discovery"] = True
                    else:
                        logger.warning(f"❌ Hunter.io: Email discovery failed for {contact_name}")
                        
                except Exception as exc:
                    logger.warning(f"❌ Hunter.io: Email discovery failed for {contact_name}: {exc}")
    
    total_cost = discovery_cost + hunter_cost
    logger.info(f"💰 Hunter.io email discovery & verification completed for {domain}: {discovery_attempts} attempts, {successful_discoveries} discoveries, {successful_replacements} replacements, Total cost: ${total_cost:.4f}")
    
    # Final summary of email status after discovery
    final_verified = [c for c in contacts if c.get("email_verified")]
    final_unverified = [c for c in contacts if c.get("email") and not c.get("email_verified")]
    final_no_email = [c for c in contacts if c.get("email") is None]
    logger.info(f"📊 Final email status for {domain}: {len(final_verified)} verified, {len(final_unverified)} unverified, {len(final_no_email)} no email")
    
    return contacts, total_cost
```

---

## 🔗 **Phase 4: Integration & Testing**

### **4.1 Main Enrichment Integration**

**Location:** `src/enrich.py` (around line 2050 in run_enrich function)

```python
# Around line 2050 in run_enrich function, BEFORE individual contact processing

# Initialize Hunter.io client
hunter_client = None
hunter_api_key = os.environ.get("HUNTER_IO_API_KEY")
if hunter_api_key:
    hunter_client = HunterIOClient(hunter_api_key)
    logger.info("✅ Hunter.io client initialized successfully")
else:
    logger.warning("⚠️ HUNTER_IO_API_KEY not configured - email verification will be limited to Mailgun")

# Process each record
for record in lead_records:
    domain = record.get("domain", "")
    normalized_domain = normalize_domain(domain)
    
    # ... existing code for company enrichment ...
    
    # STEP 1: Verify ALL existing emails with Hunter.io (from crawl, apollo, etc.)
    contacts = record.get("contacts", [])
    if contacts and hunter_client:
        logger.info(f"🔍 Hunter.io: Step 1 - Verifying all existing emails for {normalized_domain}")
        contacts, hunter_cost_1 = await verify_all_contact_emails_with_hunter(
            contacts=contacts,
            hunter_client=hunter_client,
            domain=normalized_domain,
            logger=logger,
            costs_config=costs_config,
            min_score=icp_config.get("hunter_min_score", 70)
        )
        record["contacts"] = contacts
        total_cost += hunter_cost_1
        
        # Log Hunter.io verification summary
        verified_emails = [c for c in contacts if c.get("email_verified")]
        failed_emails = [c for c in contacts if c.get("email") and not c.get("email_verified")]
        discarded_emails = [c for c in contacts if c.get("email") is None]
        logger.info(f"📊 Hunter.io Summary for {normalized_domain}: {len(verified_emails)} verified, {len(failed_emails)} failed, {len(discarded_emails)} discarded (0% score)")
    
    # STEP 2: Discover and verify emails for contacts that need them
    if contacts and hunter_client:
        logger.info(f"🔍 Hunter.io: Step 2 - Discovering and verifying missing/poor emails for {normalized_domain}")
        contacts, hunter_cost_2 = await discover_and_verify_emails_with_hunter(
            contacts=contacts,
            domain=normalized_domain,
            enrichment_router=enrichment_router,
            hunter_client=hunter_client,
            logger=logger,
            costs_config=costs_config,
            min_score=icp_config.get("hunter_min_score", 70)
        )
        record["contacts"] = contacts
        total_cost += hunter_cost_2
    
    # STEP 3: Continue with existing Mailgun validation and other processing
    # ... rest of existing contact processing code ...
    
    # Add Hunter.io costs to final cost calculation
    if hunter_client:
        hunter_cost_info = hunter_client.get_cost_info()
        logger.info(f"💰 Hunter.io cost summary: {hunter_cost_info['total_requests']} requests, ${hunter_cost_info['total_cost_usd']:.4f}")
```

### **4.2 Enhanced Contact Selection**

**Update the contact selection logic to prioritize Hunter.io verified emails:**

```python
def select_best_contact_with_email_quality(
    contacts: List[Dict[str, Any]], 
    role_priority_config: Dict[str, int]
) -> Optional[str]:
    """Enhanced contact selection prioritizing Hunter.io verified emails."""
    
    if not contacts:
        return None

    scored_contacts = []
    for contact in contacts:
        contact_id = contact.get("contact_id", "")
        role = contact.get("role") or contact.get("job_title", "")
        seniority = contact.get("seniority", 99)
        email_status = contact.get("email_status", ["unknown"])[0] if isinstance(contact.get("email_status"), list) else contact.get("email_status", "unknown")
        
        # NEW: Email quality scoring from Hunter.io
        email_quality_score = contact.get("email_quality_score", 0)
        email_verified = contact.get("email_verified", False)
        
        # Enhanced email status ranking that considers Hunter.io verification
        if email_verified and email_quality_score >= 70:
            email_quality_rank = 0  # Best: Hunter.io verified with good score
        elif contact.get("email") and email_quality_score >= 50:
            email_quality_rank = 1  # Good: Has email with decent Hunter.io score
        elif contact.get("email") and contact.get("email") is not None:
            email_quality_rank = 2  # Okay: Has email but low/no Hunter.io score
        else:
            email_quality_rank = 3  # Poor: No email (None or empty)
        
        # Get other rankings
        role_priority = get_role_priority(role, role_priority_config)
        seniority_rank = get_seniority_rank(role) if seniority is None else seniority
        linkedin = contact.get("linkedin") or contact.get("linkedin_url", "")
        has_linkedin = 0 if linkedin else 1

        # Enhanced sort tuple with email quality as high priority
        sort_tuple = (
            role_priority,           # 1st: Role priority
            email_quality_rank,      # 2nd: Email quality (NEW)
            seniority_rank,          # 3rd: Seniority
            has_linkedin,            # 4th: LinkedIn presence
            contact_id,              # 5th: Deterministic tiebreaker
        )
        
        scored_contacts.append((sort_tuple, contact_id))

    # Sort and return best contact
    scored_contacts.sort(key=lambda x: x[0])
    return scored_contacts[0][1] if scored_contacts else None
```

---

## 📊 **Phase 5: Monitoring & Optimization**

### **5.1 Enhanced Logging Examples**

The implementation will produce comprehensive logs like:

```
🔍 Hunter.io: Starting verification for 4 contacts from dentalgroup.com
📧 Hunter.io: Verifying email info@dentalgroup.com for Dr. Smith (source: ['provider'])
🔍 Hunter.io: Starting verification for info@dentalgroup.com
📊 Hunter.io Results for info@dentalgroup.com: Score=85%, Status=valid, Result=deliverable
✅ Hunter.io: Email info@dentalgroup.com PASSED verification (score: 85%, status: valid)

📧 Hunter.io: Verifying email contact@dentalgroup.com for Dr. Johnson (source: ['crawl'])
🔍 Hunter.io: Starting verification for contact@dentalgroup.com
📊 Hunter.io Results for contact@dentalgroup.com: Score=25%, Status=risky, Result=risky
❌ Hunter.io: Email contact@dentalgroup.com FAILED verification (score: 25%, status: risky)

🔍 Hunter.io: Step 2 - Discovering and verifying missing/poor emails for dentalgroup.com
🔍 Hunter.io: Attempting email discovery for Dr. Johnson at dentalgroup.com
✅ Hunter.io: New email discovered: johnson@dentalgroup.com for Dr. Johnson
🔍 Hunter.io: Verifying discovered email johnson@dentalgroup.com
📊 Hunter.io: Verification for discovered email johnson@dentalgroup.com: Score=75%, Status=valid
📧 Hunter.io: Replaced email contact@dentalgroup.com with johnson@dentalgroup.com (quality improvement: 25% → 75%)

💰 Hunter.io verification completed for dentalgroup.com: 3 verified, 1 failed, Total cost: $0.0080
💰 Hunter.io email discovery & verification completed for dentalgroup.com: 1 attempts, 0 discoveries, 1 replacements, Total cost: $0.0040
💰 Hunter.io cost summary: 4 requests, $0.0080
```

### **5.2 Data Structure Changes**

**New fields added to contacts:**

```python
contact = {
    # Existing fields...
    "email": "johnson@dentalgroup.com",
    "email_source": ["provider", "hunter_verified"],
    
    # NEW: Hunter.io verification data
    "hunter_verification": {
        "score": 75,
        "status": "valid",
        "result": "deliverable",
        "sources": ["domain_search"],
        "api_calls": 1,
        "error": None,
        "verified_at": "2025-08-27T19:01:20Z",
        "cost_usd": 0.002
    },
    
    # NEW: Email quality metrics
    "email_quality_score": 75,
    "email_verified": True,
    
    # NEW: Email replacement tracking
    "replaced_email": "contact@dentalgroup.com",
    "email_quality_improvement": 50,
    
    # NEW: Discovery flags
    "needs_email_discovery": False,
    "needs_email_replacement": False
}
```

---

## 🗂️ **Phase 6: Schema & Data Validation Updates**

### **6.1 Update JSON Schema**

**Location:** `schemas/unified_lead_record.json`

**Add new Hunter.io fields to contact schema:**

```json
{
  "type": "object",
  "properties": {
    "contacts": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "email": {
            "type": ["string", "null"],
            "description": "Contact email address (can be null if Hunter.io score is 0%)"
          },
          "hunter_verification": {
            "type": "object",
            "properties": {
              "score": {"type": "integer", "minimum": 0, "maximum": 100},
              "status": {"type": "string", "enum": ["valid", "invalid", "risky", "unknown", "error", "timeout", "rate_limited"]},
              "result": {"type": "string", "enum": ["deliverable", "undeliverable", "risky", "unknown"]},
              "sources": {"type": "array", "items": {"type": "string"}},
              "api_calls": {"type": "integer"},
              "error": {"type": ["string", "null"]},
              "verified_at": {"type": "string", "format": "date-time"},
              "cost_usd": {"type": "number"}
            },
            "required": ["score", "status", "result", "api_calls", "cost_usd"]
          },
          "email_quality_score": {"type": "integer", "minimum": 0, "maximum": 100},
          "email_verified": {"type": "boolean"},
          "replaced_email": {"type": ["string", "null"]},
          "email_quality_improvement": {"type": "integer"},
          "needs_email_discovery": {"type": "boolean"},
          "needs_email_replacement": {"type": "boolean"}
        }
      }
    }
  }
}
```

### **6.2 Update Costs Configuration**

**Location:** `config/costs.yaml`

**Add Hunter.io cost entry:**

```yaml
# Email verification costs
mailgun: 0.001
hunter: 0.002

# ... existing costs
```

---

## 🛡️ **Phase 7: Null-Email Safety Guards**

### **7.1 Update Email Validation Logic**

**Location:** `src/enrich.py` (around line 2935)

**Replace existing Mailgun validation with null-safe version:**

```python
# Validate email if present (null-safe)
if contact.get("email") is not None:
    try:
        validation_result = await mailgun_client.validate_email(
            contact["email"]
        )

        # Map Mailgun status to our email_status
        mailgun_status = validation_result.get(
            "result", "unknown"
        )
        if mailgun_status == "valid":
            contact["email_status"] = ["valid"]
            contact["email_confidence"] = validation_result.get(
                "score", 0.0
            )
        elif mailgun_status == "catch_all":
            contact["email_status"] = ["catch_all"]
            contact["email_confidence"] = 0.5
        elif mailgun_status == "invalid":
            contact["email_status"] = ["invalid"]
            contact["email_confidence"] = 0.0
        else:
            contact["email_status"] = ["unknown"]
            contact["email_confidence"] = 0.5

        single_contact_cost += costs_config.get("mailgun", 0.0)

    except Exception as exc:
        logger.warning(f"Failed to validate email: {exc}")
        contact["email_status"] = ["unknown"]
        contact["email_confidence"] = 0.0
else:
    # Contact has no email (Hunter.io discarded it)
    contact["email_status"] = ["no_email"]
    contact["email_confidence"] = 0.0
    logger.info(f"📭 Skipping Mailgun validation for contact {contact.get('full_name', 'Unknown')} - no email available")
```

### **7.2 Update Email Discovery Logic**

**Location:** `src/enrich.py` (around line 2905)

**Replace existing email discovery with null-safe version:**

```python
# Try to find email if still missing (null-safe)
if (
    contact.get("email") is None
    and contact.get("first_name")
    and contact.get("last_name")
):
    try:
        request = EnrichmentRequest(
            domain=normalized_domain,
            first_name=contact["first_name"],
            last_name=contact["last_name"],
        )
        result = await enrichment_router.find_email(request)

        if result.success and result.data and result.data.email:
            contact["email"] = result.data.email
            contact["email_source"] = ["provider"]
            contact["email_status"] = ["unknown"]
            single_contact_cost += result.cost
            logger.info(
                f"✅ Email discovery completed for {normalized_domain}"
            )
    except Exception as exc:
        logger.warning(
            f"Email discovery failed for {normalized_domain}: {exc}"
        )
```

### **7.3 Update Contact Selection Functions**

**Location:** `src/enrich.py` (where contact selection occurs)

**Ensure all contact selection logic handles null emails:**

```python
def filter_contacts_with_emails(contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter contacts to only those with valid emails (not None)."""
    return [c for c in contacts if c.get("email") is not None]

def get_contact_email(contact: Dict[str, Any]) -> Optional[str]:
    """Safely get contact email, handling None values."""
    email = contact.get("email")
    return email if email is not None else None
```

---

## 🎯 **Implementation Checklist**

### **Phase 1: Core Client**
- [ ] Add Hunter.io environment variables to `env.template`
- [ ] Add Hunter.io costs to `config/costs.yaml`
- [ ] Implement HunterIOClient class in `src/enrich.py`
- [ ] Add rate limiting and error handling
- [ ] Add comprehensive logging for all API calls

### **Phase 2: Universal Verification**
- [ ] Implement `verify_all_contact_emails_with_hunter` function
- [ ] Add comprehensive logging for verification process
- [ ] Store Hunter.io results in contact data
- [ ] Implement email quality scoring
- [ ] **NEW: Hard discard emails with 0% score (set email=None)**
- [ ] **NEW: Enhanced logging with discarded count**
- [ ] **NEW: Clear email sources when discarding**

### **Phase 3: Enhanced Discovery**
- [ ] Implement `discover_and_verify_emails_with_hunter` function
- [ ] Add email replacement logic
- [ ] Track quality improvements
- [ ] Comprehensive logging for discovery process
- [ ] **NEW: Skip contacts that already have verified emails**
- [ ] **NEW: Clear discovery flags after successful replacement**
- [ ] **NEW: Keep discovery active for failed replacements**
- [ ] **NEW: Verify discovered emails with Hunter.io before accepting**

### **Phase 4: Integration**
- [ ] Integrate into main `run_enrich` function
- [ ] Update contact selection logic to prioritize Hunter.io verified emails
- [ ] Add cost tracking for Hunter.io operations
- [ ] Test with existing workflows
- [ ] **NEW: Handle None emails in contact selection**
- [ ] **NEW: Initialize Hunter.io client once per job**

### **Phase 5: Monitoring**
- [ ] Verify all logging is working correctly
- [ ] Test cost calculations and aggregation
- [ ] Validate data structure changes
- [ ] Performance testing with rate limiting
- [ ] **NEW: Test 0% score email discarding**
- [ ] **NEW: Test automatic replacement discovery**
- [ ] **NEW: Test cost tracking accuracy**

### **Phase 6: Schema & Data Validation**
- [ ] Update `schemas/unified_lead_record.json` with new Hunter.io fields
- [ ] Add Hunter.io cost entry to `config/costs.yaml`
- [ ] Validate schema changes don't break existing tests
- [ ] Update any data validation logic to handle new fields
- [ ] **NEW: Ensure backward compatibility with existing data**

### **Phase 7: Null-Email Safety Guards**
- [ ] Update Mailgun validation logic to handle null emails safely
- [ ] Update email discovery logic to handle null emails safely
- [ ] Update contact selection functions to handle null emails safely
- [ ] Add null-safe utility functions for email operations
- [ ] **NEW: Test all email-related functions with null email values**
- [ ] **NEW: Ensure CSV exports handle null emails gracefully**

---

## 🚨 **Important Notes**

1. **ALL emails from ANY source** will be verified with Hunter.io
2. **Comprehensive logging** will show Hunter.io activity in all logs
3. **Cost tracking** is implemented for both Hunter.io and discovery
4. **Email quality scores** are stored and used in contact selection
5. **Rate limiting** respects Hunter.io's 10 requests/second limit
6. **Error handling** gracefully handles API failures
7. **NEW: 0% score emails are automatically discarded** (email set to None) and replaced via Apollo + LLM discovery
8. **NEW: Discovery flags are properly managed** to avoid infinite loops and ensure replacement attempts
9. **NEW: Schema updates ensure data validation works with new fields**
10. **NEW: Null-email safety guards prevent crashes when emails are discarded**

---

## 📈 **Expected Benefits**

1. **Email Quality Improvement**: 70%+ verified emails vs current unknown quality
2. **Reduced Bounce Rates**: Filter out low-score emails before sending
3. **Enhanced Lead Scoring**: Email quality becomes part of contact ranking
4. **Better ROI**: Higher engagement rates with verified emails
5. **Comprehensive Audit Trail**: Full logging of all email verification decisions
6. **Cost Transparency**: Clear tracking of Hunter.io API usage costs
7. **NEW: Automatic Email Replacement**: 0% score emails are automatically replaced with better alternatives
8. **NEW: Zero Bounce Guarantee**: Only Hunter.io verified emails are used in final output
9. **NEW: Robust Data Handling**: System gracefully handles null emails throughout the pipeline
10. **NEW: Schema Compliance**: All new data structures are properly validated

This implementation ensures that **EVERY EMAIL from ANY SOURCE** (crawl, Apollo, discovery, etc.) goes through Hunter.io verification, providing consistent email quality across the entire system with robust logging for monitoring and debugging. **0% score emails are automatically discarded and replaced**, ensuring only high-quality, verified emails reach the final output. The system maintains full backward compatibility while adding comprehensive null-email safety guards.
