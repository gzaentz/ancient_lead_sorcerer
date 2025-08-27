#!/usr/bin/env python3
"""
Simplified Debugging Test for Lead Sorcerer Enrichment System

This script tests the three key issues identified:
1. LLM response parsing (JSON validation issues)
2. Email validation service authentication
3. Contact discovery success rate optimization
"""

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# Test 1: LLM Response Parsing Issues
# ============================================================================

class LLMParsingTester:
    """Test LLM response parsing and JSON validation issues."""
    
    def __init__(self):
        self.test_responses = [
            # Valid responses
            '{"contact_id": "test_001"}',
            '```json\n{"contact_id": "test_002"}\n```',
            '{"contact_id": "test_003", "reason": "Best decision maker"}',
            
            # Problematic responses (from actual logs)
            '{"contact_id": "test_001"',  # Missing closing brace
            '{"contact_id": ""}',  # Empty contact_id
            '{"contact_id": null}',  # Null contact_id
            '{"wrong_key": "test_001"}',  # Missing contact_id
            'Invalid response format',  # Not JSON
            '```\n{"contact_id": "test_001"}\n```',  # Incomplete markdown
            '{"contact_id": "test_001",}',  # Trailing comma
        ]
        
        self.valid_contact_ids = ["test_001", "test_002", "test_003"]
    
    def test_parsing_issues(self):
        """Test current parsing issues and demonstrate fixes."""
        logger.info("🔍 Testing LLM Response Parsing Issues")
        logger.info("=" * 50)
        
        results = []
        for i, response in enumerate(self.test_responses):
            logger.info(f"\nTest {i+1}: {response[:50]}...")
            
            # Test current (basic) parsing
            basic_result = self._basic_parse(response)
            
            # Test enhanced parsing
            enhanced_result = self._enhanced_parse(response)
            
            result = {
                "response": response,
                "basic_success": basic_result is not None,
                "basic_contact_id": basic_result,
                "enhanced_success": enhanced_result is not None,
                "enhanced_contact_id": enhanced_result,
                "improvement": enhanced_result is not None and basic_result is None
            }
            
            results.append(result)
            
            logger.info(f"  Basic: {'✅' if basic_result else '❌'} {basic_result}")
            logger.info(f"  Enhanced: {'✅' if enhanced_result else '❌'} {enhanced_result}")
            if result["improvement"]:
                logger.info(f"  🚀 IMPROVEMENT: Enhanced parsing fixed this case!")
        
        # Summary
        basic_success = sum(1 for r in results if r["basic_success"])
        enhanced_success = sum(1 for r in results if r["enhanced_success"])
        improvements = sum(1 for r in results if r["improvement"])
        
        logger.info(f"\n📊 SUMMARY:")
        logger.info(f"  Basic parsing: {basic_success}/{len(results)} ({basic_success/len(results):.1%})")
        logger.info(f"  Enhanced parsing: {enhanced_success}/{len(results)} ({enhanced_success/len(results):.1%})")
        logger.info(f"  Improvements: {improvements} cases fixed")
        
        return results
    
    def _basic_parse(self, response: str) -> Optional[str]:
        """Basic JSON parsing (current implementation)."""
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict) and parsed.get("contact_id"):
                contact_id = parsed["contact_id"]
                if contact_id in self.valid_contact_ids:
                    return contact_id
        except json.JSONDecodeError:
            pass
        return None
    
    def _enhanced_parse(self, response: str) -> Optional[str]:
        """Enhanced parsing with multiple fallback strategies."""
        if not response or not isinstance(response, str):
            return None
            
        # Strategy 1: Direct JSON parsing
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict) and parsed.get("contact_id"):
                contact_id = parsed["contact_id"]
                if contact_id and contact_id in self.valid_contact_ids:
                    return contact_id
        except json.JSONDecodeError:
            pass
        
        # Strategy 2: Markdown cleanup then JSON parsing
        try:
            cleaned = self._clean_markdown(response)
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and parsed.get("contact_id"):
                contact_id = parsed["contact_id"]
                if contact_id and contact_id in self.valid_contact_ids:
                    return contact_id
        except json.JSONDecodeError:
            pass
        
        # Strategy 3: Regex extraction for contact_id
        contact_id_match = re.search(r'"contact_id"\s*:\s*"([^"]+)"', response)
        if contact_id_match:
            contact_id = contact_id_match.group(1)
            if contact_id in self.valid_contact_ids:
                return contact_id
        
        # Strategy 4: Try to fix common JSON issues
        try:
            fixed_response = self._fix_common_json_issues(response)
            parsed = json.loads(fixed_response)
            if isinstance(parsed, dict) and parsed.get("contact_id"):
                contact_id = parsed["contact_id"]
                if contact_id and contact_id in self.valid_contact_ids:
                    return contact_id
        except json.JSONDecodeError:
            pass
        
        return None
    
    def _clean_markdown(self, response: str) -> str:
        """Clean markdown formatting from response."""
        if "```" in response:
            start = response.find("```")
            end = response.rfind("```")
            if start != -1 and end != -1 and end > start:
                content = response[start+3:end]
                # Remove language identifier if present
                lines = content.split('\n')
                if len(lines) > 1 and lines[0].strip() in ['json', 'JSON']:
                    lines = lines[1:]
                content = '\n'.join(lines)
                return content.strip()
        return response.strip()
    
    def _fix_common_json_issues(self, response: str) -> str:
        """Fix common JSON formatting issues."""
        # Remove trailing commas
        response = re.sub(r',\s*}', '}', response)
        response = re.sub(r',\s*]', ']', response)
        
        # Fix missing closing braces
        open_braces = response.count('{')
        close_braces = response.count('}')
        if open_braces > close_braces:
            response += '}' * (open_braces - close_braces)
        
        return response

# ============================================================================
# Test 2: Email Validation Authentication Issues
# ============================================================================

class EmailValidationTester:
    """Test email validation authentication issues."""
    
    def __init__(self):
        self.test_emails = [
            "test@example.com",
            "invalid-email",
            "user@nonexistent-domain.xyz"
        ]
    
    def test_authentication(self):
        """Test email validation authentication."""
        logger.info("\n🔍 Testing Email Validation Authentication")
        logger.info("=" * 50)
        
        # Check environment variables
        smtp_login = os.getenv("MAILGUN_SMTP_LOGIN")
        smtp_password = os.getenv("MAILGUN_SMTP_PW")
        
        logger.info(f"MAILGUN_SMTP_LOGIN: {'✅ Set' if smtp_login else '❌ Missing'}")
        logger.info(f"MAILGUN_SMTP_PW: {'✅ Set' if smtp_password else '❌ Missing'}")
        
        if not smtp_login or not smtp_password:
            logger.error("❌ Missing Mailgun environment variables")
            return {
                "status": "failed",
                "error": "Missing MAILGUN_SMTP_LOGIN or MAILGUN_SMTP_PW",
                "fix_required": True
            }
        
        # Test basic connectivity (without actual API calls)
        logger.info("📡 Mailgun credentials configured")
        
        return {
            "status": "configured",
            "smtp_login_set": bool(smtp_login),
            "smtp_password_set": bool(smtp_password),
            "fix_required": not (smtp_login and smtp_password)
        }
    
    def generate_fix_instructions(self, result: Dict[str, Any]) -> str:
        """Generate fix instructions for email validation."""
        if not result.get("fix_required"):
            return "✅ Email validation authentication is properly configured."
        
        return """
🔧 Email Validation Fix Instructions:

1. Add Mailgun credentials to your .env file:
   MAILGUN_SMTP_LOGIN=your_mailgun_smtp_login
   MAILGUN_SMTP_PW=your_mailgun_api_key

2. Or set environment variables:
   export MAILGUN_SMTP_LOGIN="your_mailgun_smtp_login"
   export MAILGUN_SMTP_PW="your_mailgun_api_key"

3. Verify your Mailgun account:
   - Check account is active and verified
   - Ensure you have email validation permissions
   - Check billing status

4. Test the API key format:
   - Should start with 'key-' for private API keys
   - Or use your SMTP username for SMTP authentication
"""

# ============================================================================
# Test 3: Contact Discovery Success Rate Analysis
# ============================================================================

class ContactDiscoveryTester:
    """Analyze contact discovery patterns from logs."""
    
    def __init__(self):
        # Data from the actual log analysis
        self.log_analysis = {
            "wintergardensmiles.com": {"success": True, "contacts_found": 1, "contact": "Rob Gil"},
            "serenitydentalflorida.com": {"success": False, "contacts_found": 0, "error": "No contacts discovered"},
            "atadental.com": {"success": True, "contacts_found": 1, "contact": "Joseph Ata"},
            "thesmiledesign.com": {"success": True, "contacts_found": 1, "contact": "Sachin Patel"},
            "drmisch.com": {"success": True, "contacts_found": 1, "contact": "Craig M. Misch"},
        }
    
    def analyze_success_patterns(self):
        """Analyze contact discovery success patterns."""
        logger.info("\n🔍 Analyzing Contact Discovery Success Patterns")
        logger.info("=" * 50)
        
        total_domains = len(self.log_analysis)
        successful_domains = sum(1 for data in self.log_analysis.values() if data["success"])
        failed_domains = total_domains - successful_domains
        success_rate = successful_domains / total_domains if total_domains > 0 else 0
        
        logger.info(f"Total domains tested: {total_domains}")
        logger.info(f"Successful discoveries: {successful_domains}")
        logger.info(f"Failed discoveries: {failed_domains}")
        logger.info(f"Success rate: {success_rate:.1%}")
        
        # Analyze each domain
        for domain, data in self.log_analysis.items():
            status = "✅" if data["success"] else "❌"
            if data["success"]:
                logger.info(f"  {status} {domain}: Found {data['contact']}")
            else:
                logger.info(f"  {status} {domain}: {data.get('error', 'Failed')}")
        
        # Generate recommendations
        recommendations = self._generate_recommendations(success_rate, failed_domains)
        
        return {
            "total_domains": total_domains,
            "successful_domains": successful_domains,
            "failed_domains": failed_domains,
            "success_rate": success_rate,
            "recommendations": recommendations
        }
    
    def _generate_recommendations(self, success_rate: float, failed_count: int) -> List[str]:
        """Generate optimization recommendations."""
        recommendations = []
        
        if success_rate < 0.5:
            recommendations.append("🔴 CRITICAL: Very low success rate - Review provider configuration")
        elif success_rate < 0.8:
            recommendations.append("🟡 LOW: Improve provider fallback logic and error handling")
        else:
            recommendations.append("🟢 GOOD: Success rate is acceptable")
        
        if failed_count > 0:
            recommendations.extend([
                "🔧 Implement retry logic with exponential backoff",
                "🔧 Add multiple provider fallbacks for redundancy",
                "🔧 Improve error handling and logging for failed attempts",
                "🔧 Consider caching successful provider patterns per domain"
            ])
        
        recommendations.extend([
            "📊 Monitor provider health in real-time",
            "🔄 Implement automatic provider failover",
            "⚡ Optimize provider selection based on success rates"
        ])
        
        return recommendations

# ============================================================================
# Main Debugger
# ============================================================================

class EnrichmentDebugger:
    """Main debugger that runs all tests."""
    
    def __init__(self):
        self.llm_tester = LLMParsingTester()
        self.email_tester = EmailValidationTester()
        self.contact_tester = ContactDiscoveryTester()
    
    def run_all_tests(self):
        """Run all debugging tests."""
        logger.info("🚀 Lead Sorcerer Enrichment System Debugging")
        logger.info("=" * 80)
        
        # Test 1: LLM Response Parsing
        llm_results = self.llm_tester.test_parsing_issues()
        
        # Test 2: Email Validation Authentication
        email_results = self.email_tester.test_authentication()
        email_fix = self.email_tester.generate_fix_instructions(email_results)
        
        # Test 3: Contact Discovery Analysis
        contact_results = self.contact_tester.analyze_success_patterns()
        
        # Generate comprehensive fix plan
        self._generate_fix_plan(llm_results, email_results, contact_results, email_fix)
    
    def _generate_fix_plan(self, llm_results, email_results, contact_results, email_fix):
        """Generate comprehensive fix plan."""
        logger.info("\n🔧 COMPREHENSIVE FIX PLAN")
        logger.info("=" * 80)
        
        # Priority 1: Email Validation
        logger.info("\n📧 PRIORITY 1: Email Validation Authentication")
        logger.info("-" * 50)
        logger.info(email_fix)
        
        # Priority 2: LLM Response Parsing
        logger.info("\n🤖 PRIORITY 2: LLM Response Parsing")
        logger.info("-" * 50)
        improvements = sum(1 for r in llm_results if r["improvement"])
        if improvements > 0:
            logger.info(f"✅ Enhanced parsing can fix {improvements} additional cases")
            logger.info("🔧 Implement enhanced parsing with:")
            logger.info("   - Markdown cleanup")
            logger.info("   - Regex fallback extraction")
            logger.info("   - Common JSON issue fixes")
            logger.info("   - Better error handling")
        
        # Priority 3: Contact Discovery
        logger.info("\n🔍 PRIORITY 3: Contact Discovery Optimization")
        logger.info("-" * 50)
        for rec in contact_results["recommendations"]:
            logger.info(f"   {rec}")

def main():
    """Main function."""
    debugger = EnrichmentDebugger()
    debugger.run_all_tests()

if __name__ == "__main__":
    main()
