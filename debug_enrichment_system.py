#!/usr/bin/env python3
"""
Debugging Test Scenario for Lead Sorcerer Enrichment System

This script creates comprehensive tests to identify and fix:
1. LLM response parsing (JSON validation issues)
2. Email validation service authentication
3. Contact discovery success rate optimization

Usage:
    python scripts/debug_enrichment_system.py
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.enrich import (
    LLMContactSelector,
    MailgunClient,
)
from src.enrich_provider_router import EnrichmentProviderRouter
from src.enrich_providers.base import EnrichmentRequest, EnrichmentResult
from src.enrich_providers.anymail_finder import AnymailFinderProvider
from src.enrich_providers.company_enrich import CompanyEnrichProvider

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# Test Data and Fixtures
# ============================================================================

SAMPLE_CONTACTS = [
    {
        "contact_id": "test_001",
        "full_name": "Dr. John Smith",
        "role": "CEO & Founder",
        "department": "Executive",
        "seniority": 1,
        "role_priority": 1,
        "email": "john.smith@testdental.com",
        "decision_maker": True,
        "location": "Florida, USA"
    },
    {
        "contact_id": "test_002", 
        "full_name": "Dr. Sarah Johnson",
        "role": "Chief Dental Officer",
        "department": "Clinical",
        "seniority": 2,
        "role_priority": 2,
        "email": "sarah.johnson@testdental.com",
        "decision_maker": True,
        "location": "Florida, USA"
    },
    {
        "contact_id": "test_003",
        "full_name": "Mike Wilson",
        "role": "Office Manager",
        "department": "Administration", 
        "seniority": 5,
        "role_priority": 4,
        "email": "mike.wilson@testdental.com",
        "decision_maker": False,
        "location": "Florida, USA"
    }
]

SAMPLE_ICP_CONFIG = {
    "icp_type": "dental",
    "icp_text": "Family-owned dental practices with multiple offices in Florida",
    "name": "Dental Practice Acquisition - Test ICP",
    "threshold": 0.5,
    "filtering_strict": False,
    "role_priority": {
        "ceo": 1,
        "owner": 1,
        "founder": 1,
        "president": 1,
        "vp operations": 2,
        "practice administrator": 3,
        "office manager": 4,
        "director": 5,
        "default": 99
    }
}

# ============================================================================
# Test 1: LLM Response Parsing (JSON Validation Issues)
# ============================================================================

class LLMResponseParsingTester:
    """Test and fix LLM response parsing issues."""
    
    def __init__(self):
        self.test_responses = [
            # Valid responses
            '{"contact_id": "test_001"}',
            '```json\n{"contact_id": "test_002"}\n```',
            '{"contact_id": "test_003", "reason": "Best decision maker"}',
            
            # Problematic responses (from logs)
            '{"contact_id": "test_001"',  # Missing closing brace
            '{"contact_id": ""}',  # Empty contact_id
            '{"contact_id": null}',  # Null contact_id
            '{"wrong_key": "test_001"}',  # Missing contact_id
            'Invalid response format',  # Not JSON
            '```\n{"contact_id": "test_001"}\n```',  # Incomplete markdown
            '{"contact_id": "test_001",}',  # Trailing comma
        ]
        
    def test_current_validation(self):
        """Test current validation logic."""
        logger.info("�� Testing current LLM response validation...")
        
        results = []
        for i, response in enumerate(self.test_responses):
            is_valid = validate_llm_response(response)
            contact_id = extract_contact_id(response, SAMPLE_CONTACTS)
            quality = analyze_llm_response_quality(response)
            
            results.append({
                "response": response[:50] + "..." if len(response) > 50 else response,
                "is_valid": is_valid,
                "contact_id": contact_id,
                "quality_score": quality["format_compliance"],
                "issues": quality["issues"]
            })
            
            logger.info(f"Test {i+1}: Valid={is_valid}, Contact ID={contact_id}, Quality={quality['format_compliance']:.2f}")
        
        return results
    
    def test_enhanced_validation(self):
        """Test enhanced validation with better error handling."""
        logger.info("🧪 Testing enhanced LLM response validation...")
        
        # Test the enhanced validation function
        enhanced_results = []
        for i, response in enumerate(self.test_responses):
            try:
                # Enhanced parsing with multiple fallback strategies
                contact_id = self._enhanced_extract_contact_id(response, SAMPLE_CONTACTS)
                enhanced_results.append({
                    "response": response[:50] + "..." if len(response) > 50 else response,
                    "contact_id": contact_id,
                    "success": contact_id is not None
                })
            except Exception as e:
                enhanced_results.append({
                    "response": response[:50] + "..." if len(response) > 50 else response,
                    "contact_id": None,
                    "success": False,
                    "error": str(e)
                })
        
        return enhanced_results
    
    def _enhanced_extract_contact_id(self, response: str, contacts: List[Dict[str, Any]]) -> Optional[str]:
        """Enhanced contact ID extraction with multiple fallback strategies."""
        if not response or not isinstance(response, str):
            return None
            
        # Strategy 1: Direct JSON parsing
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict) and parsed.get("contact_id"):
                contact_id = parsed["contact_id"]
                if contact_id and contact_id in [c.get("contact_id") for c in contacts]:
                    return contact_id
        except json.JSONDecodeError:
            pass
        
        # Strategy 2: Markdown cleanup then JSON parsing
        try:
            cleaned = self._clean_markdown(response)
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and parsed.get("contact_id"):
                contact_id = parsed["contact_id"]
                if contact_id and contact_id in [c.get("contact_id") for c in contacts]:
                    return contact_id
        except json.JSONDecodeError:
            pass
        
        # Strategy 3: Regex extraction for contact_id
        import re
        contact_id_match = re.search(r'"contact_id"\s*:\s*"([^"]+)"', response)
        if contact_id_match:
            contact_id = contact_id_match.group(1)
            if contact_id in [c.get("contact_id") for c in contacts]:
                return contact_id
        
        # Strategy 4: Try to fix common JSON issues
        try:
            fixed_response = self._fix_common_json_issues(response)
            parsed = json.loads(fixed_response)
            if isinstance(parsed, dict) and parsed.get("contact_id"):
                contact_id = parsed["contact_id"]
                if contact_id and contact_id in [c.get("contact_id") for c in contacts]:
                    return contact_id
        except json.JSONDecodeError:
            pass
        
        return None
    
    def _clean_markdown(self, response: str) -> str:
        """Clean markdown formatting from response."""
        # Remove markdown code blocks
        if "```" in response:
            start = response.find("```")
            end = response.rfind("```")
            if start != -1 and end != -1 and end > start:
                # Extract content between code blocks
                content = response[start:end]
                # Remove language identifier if present
                lines = content.split('\n')
                if len(lines) > 1 and lines[1].strip():
                    lines = lines[1:]
                content = '\n'.join(lines)
                return content.strip()
        return response.strip()
    
    def _fix_common_json_issues(self, response: str) -> str:
        """Fix common JSON formatting issues."""
        # Remove trailing commas
        response = re.sub(r',\s*}', '}', response)
        response = re.sub(r',\s*]', ']', response)
        
        # Fix missing quotes around keys
        response = re.sub(r'(\w+):', r'"\1":', response)
        
        # Fix missing closing braces
        open_braces = response.count('{')
        close_braces = response.count('}')
        if open_braces > close_braces:
            response += '}' * (open_braces - close_braces)
        
        return response

# ============================================================================
# Test 2: Email Validation Service Authentication
# ============================================================================

class EmailValidationTester:
    """Test and fix email validation service authentication issues."""
    
    def __init__(self):
        self.test_emails = [
            "john.smith@testdental.com",
            "sarah.johnson@testdental.com", 
            "mike.wilson@testdental.com",
            "invalid-email",
            "test@nonexistentdomain.xyz"
        ]
        
    async def test_mailgun_authentication(self):
        """Test Mailgun authentication and identify issues."""
        logger.info("🧪 Testing Mailgun email validation authentication...")
        
        # Check environment variables
        smtp_login = os.getenv("MAILGUN_SMTP_LOGIN")
        smtp_password = os.getenv("MAILGUN_SMTP_PW")
        
        if not smtp_login or not smtp_password:
            logger.error("❌ Missing Mailgun environment variables")
            return {
                "status": "failed",
                "error": "Missing MAILGUN_SMTP_LOGIN or MAILGUN_SMTP_PW",
                "fix_required": True
            }
        
        # Test authentication
        try:
            client = MailgunClient(smtp_login, smtp_password)
            
            # Test with a simple email
            test_email = "test@example.com"
            result = await client.validate_email(test_email)
            
            logger.info(f"✅ Mailgun authentication successful: {result}")
            return {
                "status": "success",
                "result": result,
                "fix_required": False
            }
            
        except Exception as e:
            logger.error(f"❌ Mailgun authentication failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "fix_required": True
            }
    
    async def test_alternative_email_validation(self):
        """Test alternative email validation methods."""
        logger.info("🧪 Testing alternative email validation methods...")
        
        results = []
        
        # Test 1: Basic regex validation
        for email in self.test_emails:
            is_valid_regex = self._validate_email_regex(email)
            results.append({
                "email": email,
                "regex_valid": is_valid_regex,
                "method": "regex"
            })
        
        # Test 2: DNS MX record validation
        for email in self.test_emails:
            if "@" in email:
                domain = email.split("@")[1]
                has_mx = await self._check_mx_record(domain)
                results.append({
                    "email": email,
                    "mx_valid": has_mx,
                    "method": "dns_mx"
                })
        
        return results
    
    def _validate_email_regex(self, email: str) -> bool:
        """Basic email validation using regex."""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    async def _check_mx_record(self, domain: str) -> bool:
        """Check if domain has MX records."""
        try:
            import dns.resolver
            mx_records = dns.resolver.resolve(domain, 'MX')
            return len(mx_records) > 0
        except Exception:
            return False
    
    def generate_fix_instructions(self, auth_result: Dict[str, Any]) -> str:
        """Generate fix instructions for authentication issues."""
        if not auth_result.get("fix_required"):
            return "✅ No fixes required for email validation authentication."
        
        error = auth_result.get("error", "")
        
        if "Missing" in error:
            return """
🔧 Fix Required: Missing Mailgun Environment Variables

1. Add to your .env file:
   MAILGUN_SMTP_LOGIN=your_mailgun_login_here
   MAILGUN_SMTP_PW=your_mailgun_password_here

2. Or set environment variables:
   export MAILGUN_SMTP_LOGIN="your_mailgun_login_here"
   export MAILGUN_SMTP_PW="your_mailgun_password_here"

3. Verify your Mailgun account has SMTP access enabled
"""
        
        elif "401 Unauthorized" in error:
            return """
�� Fix Required: Mailgun Authentication Failed

1. Verify your Mailgun API key is correct
2. Check if your Mailgun account is active
3. Ensure you have SMTP validation permissions
4. Try regenerating your API key
5. Check Mailgun account status and billing
"""
        
        else:
            return f"""
🔧 Fix Required: Email Validation Error

Error: {error}

1. Check Mailgun service status
2. Verify network connectivity
3. Check firewall/proxy settings
4. Review Mailgun API documentation
"""

# ============================================================================
# Test 3: Contact Discovery Success Rate Optimization
# ============================================================================

class ContactDiscoveryTester:
    """Test and optimize contact discovery success rates."""
    
    def __init__(self):
        self.test_domains = [
            "testdental.com",
            "serenitydentalflorida.com",  # From logs - failed discovery
            "wintergardensmiles.com",     # From logs - successful discovery
            "atadental.com",              # From logs - successful discovery
            "thesmiledesign.com"          # From logs - successful discovery
        ]
        
    async def test_provider_health(self):
        """Test provider health and availability."""
        logger.info("�� Testing enrichment provider health...")
        
        try:
            # Initialize router
            router = EnrichmentProviderRouter(
                icp_config=SAMPLE_ICP_CONFIG,
                logger=logger
            )
            
            # Get health summary
            health_summary = router.get_provider_health_summary()
            
            logger.info(f"Provider Health Summary: {health_summary}")
            
            return health_summary
            
        except Exception as e:
            logger.error(f"❌ Failed to test provider health: {e}")
            return {"error": str(e)}
    
    async def test_contact_discovery_success_rates(self):
        """Test contact discovery success rates across providers."""
        logger.info("🧪 Testing contact discovery success rates...")
        
        results = []
        
        for domain in self.test_domains:
            logger.info(f"Testing domain: {domain}")
            
            try:
                # Test with router
                router = EnrichmentProviderRouter(
                    icp_config=SAMPLE_ICP_CONFIG,
                    logger=logger
                )
                
                request = EnrichmentRequest(domain=domain)
                result = await router.get_all_domain_prospects(request)
                
                results.append({
                    "domain": domain,
                    "success": result.success,
                    "contacts_found": len(result.data) if result.data else 0,
                    "provider_used": result.provider,
                    "error": result.error if not result.success else None
                })
                
                logger.info(f"  {domain}: Success={result.success}, Contacts={len(result.data) if result.data else 0}")
                
            except Exception as e:
                logger.error(f"  {domain}: Error={e}")
                results.append({
                    "domain": domain,
                    "success": False,
                    "contacts_found": 0,
                    "provider_used": None,
                    "error": str(e)
                })
        
        return results
    
    def analyze_failure_patterns(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze patterns in contact discovery failures."""
        logger.info("🧪 Analyzing contact discovery failure patterns...")
        
        total_tests = len(results)
        successful_tests = sum(1 for r in results if r["success"])
        failed_tests = total_tests - successful_tests
        
        # Group by provider
        provider_stats = {}
        for result in results:
            provider = result["provider_used"] or "unknown"
            if provider not in provider_stats:
                provider_stats[provider] = {"success": 0, "failure": 0, "total": 0}
            
            provider_stats[provider]["total"] += 1
            if result["success"]:
                provider_stats[provider]["success"] += 1
            else:
                provider_stats[provider]["failure"] += 1
        
        # Calculate success rates
        for provider, stats in provider_stats.items():
            if stats["total"] > 0:
                stats["success_rate"] = stats["success"] / stats["total"]
            else:
                stats["success_rate"] = 0.0
        
        analysis = {
            "overall_success_rate": successful_tests / total_tests if total_tests > 0 else 0.0,
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "failed_tests": failed_tests,
            "provider_stats": provider_stats,
            "recommendations": self._generate_recommendations(provider_stats)
        }
        
        return analysis
    
    def _generate_recommendations(self, provider_stats: Dict[str, Any]) -> List[str]:
        """Generate optimization recommendations based on failure patterns."""
        recommendations = []
        
        for provider, stats in provider_stats.items():
            if stats["total"] > 0:
                success_rate = stats["success_rate"]
                
                if success_rate < 0.5:
                    recommendations.append(f"🔴 {provider}: Very low success rate ({success_rate:.1%}) - Consider disabling or investigating")
                elif success_rate < 0.8:
                    recommendations.append(f"🟡 {provider}: Low success rate ({success_rate:.1%}) - Review configuration and fallback logic")
                elif success_rate >= 0.9:
                    recommendations.append(f"🟢 {provider}: Excellent success rate ({success_rate:.1%}) - Consider promoting to primary provider")
        
        # General recommendations
        if any(stats["success_rate"] < 0.5 for stats in provider_stats.values() if stats["total"] > 0):
            recommendations.append("🔧 Implement better error handling and retry logic for failing providers")
            recommendations.append("🔧 Add provider health monitoring and automatic failover")
        
        if len([p for p, stats in provider_stats.items() if stats["total"] > 0]) < 2:
            recommendations.append("🔧 Ensure multiple providers are available for redundancy")
        
        return recommendations

# ============================================================================
# Main Test Runner
# ============================================================================

class EnrichmentSystemDebugger:
    """Main debugger class that runs all tests."""
    
    def __init__(self):
        self.llm_tester = LLMResponseParsingTester()
        self.email_tester = EmailValidationTester()
        self.contact_tester = ContactDiscoveryTester()
        
    async def run_all_tests(self):
        """Run all debugging tests."""
        logger.info("🚀 Starting Lead Sorcerer Enrichment System Debugging...")
        logger.info("=" * 80)
        
        # Test 1: LLM Response Parsing
        logger.info("\n🔍 TEST 1: LLM Response Parsing (JSON Validation Issues)")
        logger.info("-" * 60)
        
        current_results = self.llm_tester.test_current_validation()
        enhanced_results = self.llm_tester.test_enhanced_validation()
        
        # Test 2: Email Validation Authentication
        logger.info("\n🔍 TEST 2: Email Validation Service Authentication")
        logger.info("-" * 60)
        
        mailgun_auth = await self.email_tester.test_mailgun_authentication()
        alt_validation = await self.email_tester.test_alternative_email_validation()
        
        # Test 3: Contact Discovery Success Rates
        logger.info("\n🔍 TEST 3: Contact Discovery Success Rate Optimization")
        logger.info("-" * 60)
        
        provider_health = await self.contact_tester.test_provider_health()
        discovery_results = await self.contact_tester.test_contact_discovery_success_rates()
        failure_analysis = self.contact_tester.analyze_failure_patterns(discovery_results)
        
        # Generate comprehensive report
        self._generate_report(
            current_results, enhanced_results,
            mailgun_auth, alt_validation,
            provider_health, discovery_results, failure_analysis
        )
        
        # Generate fix recommendations
        self._generate_fix_recommendations(
            current_results, enhanced_results,
            mailgun_auth, alt_validation,
            failure_analysis
        )
    
    def _generate_report(self, *args):
        """Generate comprehensive debugging report."""
        logger.info("\n📊 COMPREHENSIVE DEBUGGING REPORT")
        logger.info("=" * 80)
        
        # This would generate a detailed report file
        # For now, just log the key findings
        pass
    
    def _generate_fix_recommendations(self, *args):
        """Generate specific fix recommendations."""
        logger.info("\n🔧 FIX RECOMMENDATIONS")
        logger.info("=" * 80)
        
        # Generate email validation fix instructions
        if len(args) > 2 and args[2]:  # mailgun_auth
            fix_instructions = self.email_tester.generate_fix_instructions(args[2])
            logger.info(fix_instructions)

# ============================================================================
# Main Execution
# ============================================================================

async def main():
    """Main function to run the debugging tests."""
    debugger = EnrichmentSystemDebugger()
    await debugger.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())