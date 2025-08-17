"""
Unit tests for common utilities module.

Tests all cross-cutting functionality including data normalization, concurrency,
error handling, schema validation, and other common utilities.
"""

import asyncio
import json
import logging
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, mock_open
from pathlib import Path

import pytest
import pytest_asyncio

# Import the common utilities
from src.common import (
    ErrorCode, normalize_domain, normalize_text, generate_lead_id,
    generate_contact_id, now_z, mask_email, mask_phone, mask_linkedin,
    canonicalize_linkedin, parse_phone_number, resolve_data_dir,
    compute_next_revisit, append_status, append_audit, recompute_total_cost,
    round4, truncate_evidence_arrays, PermitManager, AsyncSemaphorePool,
    SyncSemaphorePool, build_error, wrap_unknown_errors,
    exponential_backoff_with_timeout, load_schema_checksum,
    validate_envelope, validate_template_placeholders, build_metrics,
    load_costs_config, PIIMaskingFormatter, setup_logging,
    write_with_lock, append_jsonl_with_lock, compute_content_hash,
    should_fetch_next_page, validate_provider_config, validate_testing_flags,
    get_role_priority, get_seniority_rank, get_email_status_rank
)


class TestErrorCode(unittest.TestCase):
    """Test ErrorCode enum values."""

    def test_error_codes_exist(self):
        """Test that all required error codes are present."""
        expected_codes = [
            "SCHEMA_VALIDATION", "HTTP_429", "HTTP_TIMEOUT", "SMTP_TIMEOUT",
            "DNS_FAILURE", "PROVIDER_ERROR", "EXTRACT_ERROR", "BUDGET_EXCEEDED",
            "PARSE_ERROR", "UNKNOWN", "NO_RESULTS"
        ]

        for code in expected_codes:
            self.assertTrue(hasattr(ErrorCode, code))
            self.assertEqual(getattr(ErrorCode, code).value, code)


class TestDataFileConventions(unittest.TestCase):
    """Test data and file convention utilities."""

    def test_normalize_domain(self):
        """Test domain normalization to eTLD+1."""
        test_cases = [
            ("example.com", "example.com"),
            ("sub.example.com", "example.com"),
            ("sub.foo.co.uk", "foo.co.uk"),
            ("https://example.com", "example.com"),
            ("http://sub.example.com:8080", "example.com"),
            ("", ""),
            (None, None),
        ]

        for input_domain, expected in test_cases:
            with self.subTest(input_domain=input_domain):
                result = normalize_domain(input_domain)
                self.assertEqual(result, expected)

    def test_normalize_text(self):
        """Test text normalization with Unicode NFKD and whitespace."""
        test_cases = [
            ("  Hello   World  ", "hello world"),
            ("Café", "cafe"),
            ("CEO & CTO", "ceo & cto"),
            ("", ""),
            (None, ""),
            ("   ", ""),
        ]

        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = normalize_text(input_text)
                self.assertEqual(result, expected)

    def test_generate_lead_id(self):
        """Test deterministic lead_id generation."""
        domain1 = "example.com"
        domain2 = "sub.example.com"

        # Same eTLD+1 should generate same ID
        id1 = generate_lead_id(domain1)
        id2 = generate_lead_id(domain2)
        self.assertEqual(id1, id2)

        # Different domains should generate different IDs
        id3 = generate_lead_id("different.com")
        self.assertNotEqual(id1, id3)

        # IDs should be valid UUIDs
        import uuid
        self.assertTrue(uuid.UUID(id1))

    def test_generate_contact_id(self):
        """Test deterministic contact_id generation."""
        domain = "example.com"
        name1 = "John Doe"
        role1 = "CEO"
        linkedin1 = "/in/johndoe"

        name2 = "John   Doe"  # Extra whitespace
        role2 = "  CEO  "      # Extra whitespace

        # Same normalized values should generate same ID
        id1 = generate_contact_id(domain, name1, role1, linkedin1)
        id2 = generate_contact_id(domain, name2, role2, linkedin1)
        self.assertEqual(id1, id2)

        # Different values should generate different IDs
        id3 = generate_contact_id(domain, "Jane Doe", role1, linkedin1)
        self.assertNotEqual(id1, id3)

        # IDs should be valid UUIDs
        import uuid
        self.assertTrue(uuid.UUID(id1))

    def test_now_z(self):
        """Test ISO-8601 UTC timestamp generation."""
        timestamp = now_z()

        # Should end with Z
        self.assertTrue(timestamp.endswith('Z'))

        # Should be parseable as ISO-8601
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        self.assertIsInstance(dt, datetime)

        # Should be recent
        now = datetime.utcnow().replace(tzinfo=None)
        diff = abs((now - dt.replace(tzinfo=None)).total_seconds())
        self.assertLess(diff, 5)  # Within 5 seconds

    def test_mask_email(self):
        """Test email masking for PII protection."""
        test_cases = [
            ("john@example.com", "j***@example.com"),
            ("j@example.com", "j***@example.com"),
            ("", ""),
            ("not-an-email", "not-an-email"),
        ]

        for input_email, expected in test_cases:
            with self.subTest(input_email=input_email):
                result = mask_email(input_email)
                self.assertEqual(result, expected)

    def test_mask_phone(self):
        """Test phone number masking for PII protection."""
        test_cases = [
            ("+1234567890", "+XXXXXXXX7890"),
            ("1234567890", "XXXXXXXX7890"),
            ("+1-234-567-8900", "+XXXXXXXX8900"),
            ("", ""),
            ("123", "123"),  # Too short to mask
        ]

        for input_phone, expected in test_cases:
            with self.subTest(input_phone=input_phone):
                result = mask_phone(input_phone)
                self.assertEqual(result, expected)

    def test_mask_linkedin(self):
        """Test LinkedIn path masking for PII protection."""
        test_cases = [
            ("/in/johndoe", "/in/***"),
            ("/company/example-corp", "/company/***"),
            ("https://linkedin.com/in/johndoe", "/in/***"),
            ("", ""),
            ("/other/path", "/other/path"),
        ]

        for input_path, expected in test_cases:
            with self.subTest(input_path=input_path):
                result = mask_linkedin(input_path)
                self.assertEqual(result, expected)

    def test_canonicalize_linkedin(self):
        """Test LinkedIn URL canonicalization."""
        test_cases = [
            ("https://linkedin.com/in/johndoe", ("in", "johndoe")),
            ("https://www.linkedin.com/company/example-corp", ("company", "example-corp")),
            ("/in/johndoe", ("in", "johndoe")),
            ("", ("", "")),
            ("https://other.com/path", ("", "")),
        ]

        for input_url, expected in test_cases:
            with self.subTest(input_url=input_url):
                result = canonicalize_linkedin(input_url)
                self.assertEqual(result, expected)

    def test_parse_phone_number(self):
        """Test phone number parsing and normalization."""
        # Test with explicit country code
        result = parse_phone_number("4155552671", country_code="US")
        self.assertEqual(result, "+14155552671")

        # Test with default country
        result = parse_phone_number("4155552671", default_country="US")
        self.assertEqual(result, "+14155552671")

        # Test invalid number
        with self.assertRaises(ValueError):
            parse_phone_number("invalid")

    def test_resolve_data_dir(self):
        """Test data directory resolution with precedence."""
        # Test default fallback
        payload = {}
        result = resolve_data_dir(payload)
        self.assertEqual(result, "./data")

        # Test environment variable
        with patch.dict(os.environ, {'LEADPOUT_DATA_DIR': '/custom/data'}):
            result = resolve_data_dir(payload)
            self.assertEqual(result, "/custom/data")

        # Test payload config (highest precedence)
        payload = {'config': {'data_dir': '/payload/data'}}
        result = resolve_data_dir(payload)
        self.assertEqual(result, "/payload/data")

    def test_compute_next_revisit(self):
        """Test next_revisit_at computation with max-rule."""
        # Test new revisit time
        result = compute_next_revisit(None, 90)
        self.assertTrue(result.endswith('Z'))

        # Test max-rule: existing time should be preserved if later
        existing = (datetime.utcnow() + timedelta(days=100)).isoformat() + 'Z'
        result = compute_next_revisit(existing, 90)
        self.assertEqual(result, existing)

        # Test failure revisit
        result = compute_next_revisit(None, 90, failure_revisit_days=1, is_failure=True)
        self.assertTrue(result.endswith('Z'))

    def test_append_status(self):
        """Test status history appending."""
        history = []
        append_status(history, "scored", "Initial scoring completed")

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "scored")
        self.assertEqual(history[0]["notes"], "Initial scoring completed")
        self.assertTrue(history[0]["ts"].endswith('Z'))

    def test_append_audit(self):
        """Test audit trail appending."""
        record = {}
        append_audit(record, "Domain", "Scoring completed")

        self.assertEqual(len(record["audit"]), 1)
        self.assertEqual(record["audit"][0]["step"], "Domain")
        self.assertEqual(record["audit"][0]["notes"], "Scoring completed")
        self.assertTrue(record["audit"][0]["ts"].endswith('Z'))

    def test_recompute_total_cost(self):
        """Test total cost recomputation."""
        record = {
            'cost': {
                'domain_usd': 0.1,
                'crawl_usd': 0.2,
                'enrich_usd': 0.3
            }
        }

        recompute_total_cost(record)
        self.assertEqual(record['cost']['total_usd'], 0.6)

    def test_round4(self):
        """Test float rounding to 4 decimal places."""
        test_cases = [
            (3.14159, 3.1416),
            (2.5, 2.5),
            (1.234567, 1.2346),
            (0.0, 0.0),
        ]

        for input_val, expected in test_cases:
            with self.subTest(input_val=input_val):
                result = round4(input_val)
                self.assertEqual(result, expected)

    def test_truncate_evidence_arrays(self):
        """Test evidence array truncation limits."""
        record = {
            'company': {
                'evidence_urls': ['url' + str(i) for i in range(15)]
            },
            'contacts': [
                {'evidence_urls': ['url' + str(i) for i in range(10)]}
            ]
        }

        truncate_evidence_arrays(record)

        # Company evidence_urls should be ≤ 10
        self.assertEqual(len(record['company']['evidence_urls']), 10)

        # Contact evidence_urls should be ≤ 5
        self.assertEqual(len(record['contacts'][0]['evidence_urls']), 5)


class TestConcurrencyGuard(unittest.TestCase):
    """Test concurrency management utilities."""

    def test_permit_manager_initialization(self):
        """Test PermitManager initialization."""
        manager = PermitManager(max_permits=5)
        self.assertEqual(manager.max_permits, 5)
        self.assertEqual(manager.active_count, 0)

    def test_blocking_acquire_release(self):
        """Test blocking permit acquisition and release."""
        manager = PermitManager(max_permits=2)

        # Acquire permits
        self.assertTrue(manager.blocking_acquire())
        self.assertEqual(manager.active_count, 1)

        self.assertTrue(manager.blocking_acquire())
        self.assertEqual(manager.active_count, 2)

        # Should block when no permits available
        self.assertFalse(manager.blocking_acquire(timeout=0.1))

        # Release permits
        manager.blocking_release()
        self.assertEqual(manager.active_count, 1)

        manager.blocking_release()
        self.assertEqual(manager.active_count, 0)

    def test_sync_semaphore_pool(self):
        """Test SyncSemaphorePool context manager."""
        manager = PermitManager(max_permits=1)
        pool = SyncSemaphorePool(manager)

        with pool:
            self.assertEqual(manager.active_count, 1)

        self.assertEqual(manager.active_count, 0)

    @pytest.mark.asyncio
    async def test_async_semaphore_pool(self):
        """Test AsyncSemaphorePool context manager."""
        manager = PermitManager(max_permits=1)
        pool = AsyncSemaphorePool(manager)

        async with pool:
            self.assertEqual(manager.active_count, 1)

        self.assertEqual(manager.active_count, 0)


class TestErrorHandling(unittest.TestCase):
    """Test error handling and retry utilities."""

    def test_build_error(self):
        """Test error object building with PII masking."""
        error = build_error(
            ErrorCode.PROVIDER_ERROR,
            Exception("Test error"),
            "test_tool",
            "test_lead_id",
            {"email": "test@example.com", "phone": "+1234567890"}
        )

        self.assertEqual(error["code"], "PROVIDER_ERROR")
        self.assertEqual(error["tool"], "test_tool")
        self.assertEqual(error["lead_id"], "test_lead_id")
        self.assertTrue(error["retryable"])

        # PII should be masked in context
        self.assertEqual(error["context"]["email"], "t***@example.com")
        self.assertEqual(error["context"]["phone"], "+XXXXXXXX7890")

    def test_wrap_unknown_errors(self):
        """Test unknown error wrapper decorator."""
        @wrap_unknown_errors
        def failing_function():
            raise ValueError("Test error")

        result = failing_function()

        self.assertIn("errors", result)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], "UNKNOWN")
        self.assertFalse(result["errors"][0]["retryable"])

    @pytest.mark.asyncio
    async def test_exponential_backoff_async(self):
        """Test exponential backoff with async function."""
        @exponential_backoff_with_timeout(max_attempts=3, base_delay=0.01)
        async def failing_async_function():
            raise Exception("Test error")

        start_time = time.time()
        with self.assertRaises(Exception):
            await failing_async_function()

        # Should have taken some time due to backoff
        elapsed = time.time() - start_time
        self.assertGreater(elapsed, 0.01)

    def test_exponential_backoff_sync(self):
        """Test exponential backoff with sync function."""
        @exponential_backoff_with_timeout(max_attempts=3, base_delay=0.01)
        def failing_sync_function():
            raise Exception("Test error")

        start_time = time.time()
        with self.assertRaises(Exception):
            failing_sync_function()

        # Should have taken some time due to backoff
        elapsed = time.time() - start_time
        self.assertGreater(elapsed, 0.01)


class TestSchemaValidation(unittest.TestCase):
    """Test schema validation and versioning utilities."""

    @patch('builtins.open', new_callable=mock_open, read_data=b'{"test": "schema"}')
    @patch('pathlib.Path.exists', return_value=True)
    def test_load_schema_checksum(self, mock_exists, mock_file):
        """Test schema checksum loading."""
        checksum = load_schema_checksum()
        self.assertIsInstance(checksum, str)
        self.assertEqual(len(checksum), 64)  # SHA256 hex length

    def test_validate_template_placeholders(self):
        """Test template placeholder validation."""
        template = "Find ${industry} companies in ${region}"
        context = {"industry": "tech"}

        missing = validate_template_placeholders(template, context)
        self.assertEqual(missing, ["region"])

        # All placeholders satisfied
        context["region"] = "California"
        missing = validate_template_placeholders(template, context)
        self.assertEqual(missing, [])


class TestMetrics(unittest.TestCase):
    """Test metrics building utilities."""

    def test_build_metrics(self):
        """Test metrics structure building."""
        metrics = build_metrics(
            count_in=10,
            count_out=8,
            duration_ms=1500,
            cache_hit_rate=0.8,
            pass_rate=0.8,
            cost_usd={"domain": 0.1, "crawl": 0.2, "enrich": 0.3, "total": 0.6}
        )

        self.assertEqual(metrics["count_in"], 10)
        self.assertEqual(metrics["count_out"], 8)
        self.assertEqual(metrics["duration_ms"], 1500)
        self.assertEqual(metrics["cache_hit_rate"], 0.8)
        self.assertEqual(metrics["pass_rate"], 0.8)
        self.assertEqual(metrics["cost_usd"]["total"], 0.6)

    @patch('builtins.open', new_callable=mock_open, read_data='''
proxycurl:
  unit: 'lookup'
  usd_per_unit: 0.0100
mailgun:
  unit: 'smtp_validation'
  usd_per_unit: 0.0020
    ''')
    def test_load_costs_config(self, mock_file):
        """Test costs configuration loading."""
        costs = load_costs_config("test_path")

        self.assertEqual(costs["proxycurl"], 0.01)
        self.assertEqual(costs["mailgun"], 0.002)


class TestLogging(unittest.TestCase):
    """Test logging and PII masking utilities."""

    def test_pii_masking_formatter(self):
        """Test PII masking in log formatter."""
        formatter = PIIMaskingFormatter()

        # Test email masking
        record = Mock()
        record.getMessage.return_value = '{"email": "test@example.com"}'
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.usesTime.return_value = False
        record.formatMessage.return_value = '{"email": "t***@example.com"}'
        result = formatter.format(record)

        # The formatter should have modified the record.msg
        self.assertIn("t***@example.com", record.msg)

        # Test secret masking
        record.getMessage.return_value = '{"api_key": "secret123"}'
        record.formatMessage.return_value = '{"api_key": "***REDACTED***"}'
        result = formatter.format(record)

        # The formatter should have modified the record.msg
        self.assertIn("***REDACTED***", record.msg)

    def test_setup_logging(self):
        """Test logging setup."""
        logger = setup_logging("test_tool")

        self.assertEqual(logger.name, "test_tool")
        self.assertEqual(logger.level, logging.INFO)

        # Should have a handler
        self.assertTrue(logger.handlers)


class TestFileOperations(unittest.TestCase):
    """Test file operations with portalocker."""

    @patch('portalocker.Lock')
    def test_write_with_lock(self, mock_lock):
        """Test file writing with portalocker lock."""
        temp_path = tempfile.mktemp()

        try:
            test_data = {"test": "data"}
            write_with_lock(temp_path, test_data)

            with open(temp_path, 'r') as f:
                result = json.load(f)

            self.assertEqual(result, test_data)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    @patch('portalocker.Lock')
    def test_append_jsonl_with_lock(self, mock_lock):
        """Test JSONL appending with portalocker lock."""
        temp_path = tempfile.mktemp()

        try:
            records = [{"id": 1}, {"id": 2}]
            append_jsonl_with_lock(temp_path, records)

            with open(temp_path, 'r') as f:
                lines = f.readlines()

            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0]), {"id": 1})
            self.assertEqual(json.loads(lines[1]), {"id": 2})
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


class TestContentHash(unittest.TestCase):
    """Test content hash deduplication utilities."""

    def test_compute_content_hash(self):
        """Test content hash computation."""
        data1 = {"a": 1, "b": 2}
        data2 = {"b": 2, "a": 1}  # Same data, different key order

        hash1 = compute_content_hash(data1)
        hash2 = compute_content_hash(data2)

        # Should be deterministic regardless of key order
        self.assertEqual(hash1, hash2)

        # Different data should have different hashes
        data3 = {"a": 1, "b": 3}
        hash3 = compute_content_hash(data3)
        self.assertNotEqual(hash1, hash3)


class TestProgressiveSERP(unittest.TestCase):
    """Test progressive SERP pagination utilities."""

    def test_should_fetch_next_page(self):
        """Test next page fetching logic."""
        # Fast mode should never fetch next page
        self.assertFalse(should_fetch_next_page(1, 5, False, "fast"))

        # Thorough mode should fetch if conditions met
        self.assertTrue(should_fetch_next_page(1, 5, False, "thorough"))

        # Should not fetch if at max pages
        self.assertFalse(should_fetch_next_page(5, 5, False, "thorough"))

        # Should not fetch if current page was cached
        self.assertFalse(should_fetch_next_page(1, 5, True, "thorough"))


class TestProviderValidation(unittest.TestCase):
    """Test provider configuration validation."""

    def test_validate_provider_config(self):
        """Test provider configuration validation."""
        costs_config = {"provider1": 0.1, "provider2": 0.2}

        # Should not raise for valid config
        validate_provider_config(["provider1"], costs_config)

        # Should raise for missing provider
        with self.assertRaises(KeyError):
            validate_provider_config(["provider3"], costs_config)


class TestTestingFlags(unittest.TestCase):
    """Test testing flags validation."""

    def test_validate_testing_flags(self):
        """Test testing flags validation."""
        # Valid config
        valid_config = {"testing": {"process_rejected": False, "process_low_crawl": True}}
        validate_testing_flags(valid_config)

        # Invalid config
        invalid_config = {"testing": {"process_rejected": "not_boolean"}}
        with self.assertRaises(ValueError):
            validate_testing_flags(invalid_config)


class TestRolePriority(unittest.TestCase):
    """Test role priority and seniority utilities."""

    def test_get_role_priority(self):
        """Test role priority calculation."""
        config = {"ceo": 1, "vp": 2, "default": 99}

        self.assertEqual(get_role_priority("CEO", config), 1)
        self.assertEqual(get_role_priority("VP Sales", config), 2)
        self.assertEqual(get_role_priority("Developer", config), 99)
        self.assertEqual(get_role_priority("", config), 99)

    def test_get_seniority_rank(self):
        """Test seniority ranking."""
        self.assertEqual(get_seniority_rank("C-Level Executive"), 1)
        self.assertEqual(get_seniority_rank("VP Engineering"), 2)
        self.assertEqual(get_seniority_rank("Director of Sales"), 3)
        self.assertEqual(get_seniority_rank("Software Engineer"), 99)
        self.assertEqual(get_seniority_rank(""), 99)

    def test_get_email_status_rank(self):
        """Test email status ranking."""
        self.assertEqual(get_email_status_rank("valid"), 0)
        self.assertEqual(get_email_status_rank("risky"), 1)
        self.assertEqual(get_email_status_rank("catch_all"), 2)
        self.assertEqual(get_email_status_rank("unknown"), 3)
        self.assertEqual(get_email_status_rank("invalid"), 4)
        self.assertEqual(get_email_status_rank("nonexistent"), 4)


if __name__ == '__main__':
    unittest.main()
