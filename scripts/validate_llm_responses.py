#!/usr/bin/env python3
"""
LLM Response Validation Script

This script validates LLM responses and tests the contact selection functionality
to ensure it works correctly with various ICP configurations and contact scenarios.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.enrich import (
    select_best_contact_llm,
    validate_llm_response,
    extract_contact_id,
    format_contacts_for_llm,
    LLMContactSelector,
    test_llm_response_handling,
    get_fallback_metrics,
)


class LLMValidationTester:
    """Comprehensive LLM validation testing."""

    def __init__(self):
        self.test_results = []
        self.passed = 0
        self.failed = 0

    def log_test(self, test_name: str, passed: bool, details: str = ""):
        """Log test result."""
        status = "✅ PASS" if passed else "❌ FAIL"
        self.test_results.append(f"{status}: {test_name}")
        if details:
            self.test_results.append(f"    {details}")

        if passed:
            self.passed += 1
        else:
            self.failed += 1

    def test_response_validation(self):
        """Test LLM response validation with various formats."""
        print("🧪 Testing LLM Response Validation...")

        # Valid responses
        valid_tests = [
            ('{"contact_id": "123"}', "Basic JSON"),
            ('```json\n{"contact_id": "456"}\n```', "Markdown JSON"),
            ('  {"contact_id": "789"}  ', "JSON with whitespace"),
            ('{"contact_id": "abc", "extra": "field"}', "JSON with extra fields"),
        ]

        for response, description in valid_tests:
            result = validate_llm_response(response)
            self.log_test(f"Valid response - {description}", result)

        # Invalid responses
        invalid_tests = [
            ("invalid json", "Invalid JSON"),
            ('{"wrong_key": "123"}', "Missing contact_id"),
            ('{"contact_id": ""}', "Empty contact_id"),
            ('{"contact_id": null}', "Null contact_id"),
            ("{}", "Empty object"),
            ("", "Empty string"),
            ('{"contact_id": 123}', "Non-string contact_id"),
        ]

        for response, description in invalid_tests:
            result = not validate_llm_response(response)  # Should be False
            self.log_test(f"Invalid response - {description}", result)

    def test_contact_id_extraction(self):
        """Test contact ID extraction with validation."""
        print("🧪 Testing Contact ID Extraction...")

        contacts = [
            {"contact_id": "valid_1", "name": "Person 1"},
            {"contact_id": "valid_2", "name": "Person 2"},
        ]

        # Valid extractions
        valid_tests = [
            ('{"contact_id": "valid_1"}', "valid_1", "Basic extraction"),
            (
                '```json\n{"contact_id": "valid_2"}\n```',
                "valid_2",
                "Markdown extraction",
            ),
        ]

        for response, expected, description in valid_tests:
            result = extract_contact_id(response, contacts)
            passed = result == expected
            self.log_test(
                f"Extract contact ID - {description}",
                passed,
                f"Expected: {expected}, Got: {result}",
            )

        # Invalid extractions
        invalid_tests = [
            ('{"contact_id": "nonexistent"}', "Nonexistent ID"),
            ("invalid json", "Invalid JSON"),
            ('{"wrong_key": "valid_1"}', "Wrong key"),
        ]

        for response, description in invalid_tests:
            result = extract_contact_id(response, contacts)
            passed = result is None
            self.log_test(
                f"Invalid extraction - {description}",
                passed,
                f"Expected: None, Got: {result}",
            )

    def test_contact_formatting(self):
        """Test contact formatting for LLM consumption."""
        print("🧪 Testing Contact Formatting...")

        # Basic formatting test
        contacts = [
            {
                "contact_id": "test_1",
                "name": "John Doe",
                "role": "CEO",
                "company": "TestCorp",
                "seniority": 1,
            }
        ]

        result = format_contacts_for_llm(contacts)

        # Check if all expected elements are present
        checks = [
            ("John Doe" in result, "Name present"),
            ("CEO" in result, "Role present"),
            ("TestCorp" in result, "Company present"),
            ("1." in result, "Numbering present"),
        ]

        for check, description in checks:
            self.log_test(f"Contact formatting - {description}", check)

        # Test with role priorities
        role_priority_config = {"ceo": 1, "default": 99}
        result_with_priority = format_contacts_for_llm(contacts, role_priority_config)

        priority_check = "Priority: 1" in result_with_priority
        self.log_test("Contact formatting - Role priority", priority_check)

        # Test with empty contacts
        empty_result = format_contacts_for_llm([])
        empty_check = empty_result == "No contacts available."
        self.log_test("Contact formatting - Empty list", empty_check)

    async def test_dsv_fund_scenario(self):
        """Test DSVfund ICP scenario."""
        print("🧪 Testing DSVfund ICP Scenario...")

        # DSVfund ICP configuration
        icp_config = {
            "icp_text": "Accredited, crypto-savvy capital allocators, HNW individuals, family offices, and digital-asset fund-of-funds",
            "icp_type": "investment",
        }

        # Investment-focused contacts
        contacts = [
            {
                "contact_id": "marketing_person",
                "name": "Marketing Person",
                "role": "Marketing Director",
                "company": "TechCorp",
                "seniority": 3,
                "decision_maker": False,
            },
            {
                "contact_id": "family_office_manager",
                "name": "Investment Manager",
                "role": "Portfolio Manager",
                "company": "Family Office",
                "seniority": 2,
                "decision_maker": True,
            },
        ]

        role_priority_config = {
            "Portfolio Manager": 1,
            "Marketing Director": 8,
            "default": 99,
        }

        # Test without API key (should fallback to rule-based)
        with_fallback = await select_best_contact_llm(
            contacts, role_priority_config, icp_config
        )
        fallback_check = with_fallback is not None
        self.log_test("DSVfund scenario - Fallback works", fallback_check)

    async def test_healthcare_scenario(self):
        """Test healthcare practice ICP scenario."""
        print("🧪 Testing Healthcare ICP Scenario...")

        # Healthcare ICP configuration
        icp_config = {
            "icp_text": "Dental practices and orthodontic clinics seeking modern practice management software",
            "icp_type": "healthcare",
        }

        # Healthcare-focused contacts
        contacts = [
            {
                "contact_id": "hygienist",
                "name": "Dental Hygienist",
                "role": "Hygienist",
                "company": "Dental Practice",
                "seniority": 5,
                "decision_maker": False,
            },
            {
                "contact_id": "practice_owner",
                "name": "Dr. Smith",
                "role": "Practice Owner",
                "company": "Smith Dental",
                "seniority": 1,
                "decision_maker": True,
            },
        ]

        role_priority_config = {"Practice Owner": 1, "Hygienist": 8, "default": 99}

        # Test without API key (should fallback to rule-based)
        with_fallback = await select_best_contact_llm(
            contacts, role_priority_config, icp_config
        )
        fallback_check = with_fallback is not None
        self.log_test("Healthcare scenario - Fallback works", fallback_check)

    def test_llm_selector_configurations(self):
        """Test LLM selector with different configurations."""
        print("🧪 Testing LLM Selector Configurations...")

        # Test different ICP types
        configs = ["default", "investment", "healthcare"]

        for icp_type in configs:
            try:
                selector = LLMContactSelector("test_key", icp_type)
                type_check = selector.icp_type == icp_type
                self.log_test(f"LLM selector config - {icp_type}", type_check)
            except Exception as e:
                self.log_test(f"LLM selector config - {icp_type}", False, str(e))

    def test_prompt_generation(self):
        """Test prompt generation consistency and content."""
        print("🧪 Testing Prompt Generation...")

        contacts = [
            {
                "contact_id": "test_contact",
                "name": "Test Person",
                "role": "Test Role",
                "company": "Test Company",
                "seniority": 1,
            }
        ]

        icp_config = {"icp_text": "Test ICP description", "icp_type": "default"}

        try:
            selector = LLMContactSelector("test_key")

            # Test prompt generation consistency
            prompt1 = selector._build_contact_selection_prompt(contacts, icp_config)
            prompt2 = selector._build_contact_selection_prompt(contacts, icp_config)

            consistency_check = prompt1 == prompt2
            self.log_test("Prompt generation - Consistency", consistency_check)

            # Test prompt content
            content_checks = [
                ("Test ICP description" in prompt1, "ICP text included"),
                ("Test Person" in prompt1, "Contact name included"),
                ("Test Role" in prompt1, "Contact role included"),
                ("contact_id" in prompt1, "Response format specified"),
            ]

            for check, description in content_checks:
                self.log_test(f"Prompt content - {description}", check)

        except Exception as e:
            self.log_test("Prompt generation", False, str(e))

    def run_all_tests(self):
        """Run all validation tests."""
        print("🚀 Starting LLM Validation Tests...")
        print("=" * 50)

        # Reset metrics
        global FALLBACK_METRICS
        FALLBACK_METRICS = {
            "llm_failures": 0,
            "llm_none_responses": 0,
            "invalid_contact_ids": 0,
            "total_fallbacks": 0,
        }

        # Run all test categories
        self.test_response_validation()
        self.test_contact_id_extraction()
        self.test_contact_formatting()

        # Run async tests
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.test_dsv_fund_scenario())
            loop.run_until_complete(self.test_healthcare_scenario())
        finally:
            loop.close()

        self.test_llm_selector_configurations()
        self.test_prompt_generation()

        # Run the built-in test function
        print("🧪 Running Built-in Response Handling Tests...")
        try:
            test_llm_response_handling()
            self.log_test("Built-in response handling tests", True)
        except Exception as e:
            self.log_test("Built-in response handling tests", False, str(e))

        # Print results
        print("\n" + "=" * 50)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 50)

        for result in self.test_results:
            print(result)

        print(f"\n📈 TOTAL: {self.passed + self.failed} tests")
        print(f"✅ PASSED: {self.passed}")
        print(f"❌ FAILED: {self.failed}")

        # Show fallback metrics
        metrics = get_fallback_metrics()
        print(f"\n📊 FALLBACK METRICS: {metrics}")

        success_rate = (
            (self.passed / (self.passed + self.failed)) * 100
            if (self.passed + self.failed) > 0
            else 0
        )
        print(f"🎯 SUCCESS RATE: {success_rate:.1f}%")

        if self.failed == 0:
            print("\n🎉 ALL TESTS PASSED!")
            return True
        else:
            print(f"\n⚠️  {self.failed} TESTS FAILED")
            return False


def main():
    """Main validation script."""
    print("🧪 LLM Contact Selection Validation")
    print(
        "This script validates LLM response handling and contact selection functionality."
    )
    print()

    # Check if we're in the right directory
    if not Path("src/enrich.py").exists():
        print("❌ Error: Please run this script from the Lead Sorcerer root directory")
        sys.exit(1)

    # Run validation tests
    tester = LLMValidationTester()
    success = tester.run_all_tests()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
