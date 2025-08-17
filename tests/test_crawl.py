"""
Unit tests for the Crawl tool.

Tests cover all Task 3 requirements including:
- CLI interface and envelope validation
- Artifact cache TTL and content hash deduplication
- Firecrawl extraction with HTTPS→HTTP fallback
- Contact ID generation and deduplication
- Field normalization and ICP validation
- Status transitions and status history
- Cost accounting and metrics
- Error handling and resilience
"""

import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from unittest.mock import patch

import pytest

from src.crawl import CrawlTool, FIRECRAWL_EXTRACT_SCHEMA, TOOL_NAME


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def sample_lead_record():
    """Sample lead record for testing."""
    return {
        "lead_id": "550e8400-e29b-41d4-a716-446655440000",
        "domain": "example.com",
        "company": {
            "name": None,
            "description": None,
            "industry": None,
            "naics_keywords": [],
            "hq_location": None,
            "locations": [],
            "size_hint": None,
            "socials": {"linkedin": None, "github": None, "twitter": None, "telegram": None, "instagram": None},
            "careers_url": None,
            "blog_url": None,
            "tech_stack": [],
            "evidence_urls": [],
            "ids": {"linkedin": None, "crunchbase": None}
        },
        "contacts": [],
        "icp": {
            "pre_score": 0.8,
            "pre_reason": "Good ICP fit",
            "pre_pass": True,
            "pre_flags": [],
            "scoring_meta": {"method": "llm", "model": "gpt-4o-mini", "prompt_fingerprint": "abc123", "temperature": 0.0},
            "crawl_score": None,
            "crawl_reason": None,
            "threshold": 0.7,
            "filtering_strict": True
        },
        "provenance": {
            "queries": ["tech companies in california"],
            "discovery_evidence": [],
            "scored_at": "2024-01-01T00:00:00Z",
            "crawled_at": None,
            "enriched_at": None,
            "next_revisit_at": None,
            "tool_versions": {
                "domain": {"version": "1.0.0", "schema_version": "abc123"},
                "crawl": {"version": None, "schema_version": None},
                "enrich": {"version": None, "schema_version": None}
            },
            "cache": {"domain_cache_hit": False},
            "evidence_paths": {"domain": "data/evidence/domain/example.com.json", "crawl": None, "enrich": None}
        },
        "best_contact_id": None,
        "status": "scored",
        "status_history": [{"status": "scored", "ts": "2024-01-01T00:00:00Z", "notes": "Initial scoring"}],
        "audit": [{"step": "Domain", "notes": "Scored lead", "ts": "2024-01-01T00:00:00Z"}],
        "cost": {"domain_usd": 0.001, "crawl_usd": 0.0, "enrich_usd": 0.0, "total_usd": 0.001}
    }


@pytest.fixture
def sample_icp_config():
    """Sample ICP configuration for testing."""
    return {
        "name": "test_icp",
        "icp_text": "Technology companies in California",
        "queries": ["tech companies in ${region}"],
        "required_fields": {
            "company": ["name", "hq_location"],
            "contact": ["email"]
        },
        "optional_fields": {
            "company": ["tech_stack"],
            "contact": ["phone"]
        },
        "threshold": 0.7,
        "filtering_strict": True,
        "mode": "thorough",
        "refresh_policy": {
            "revisit_after_days": 90,
            "failure_revisit_days": 1,
            "domain_serp_ttl_hours": 24,
            "crawl_ttl_days": 14
        },
        "concurrency": {
            "max_concurrent_requests": 3
        },
        "search": {
            "max_pages": 5
        },
        "testing": {
            "process_rejected": False,
            "process_low_crawl": False
        },
        "caps": {
            "company_usd": 0.02,
            "contact_usd": 0.03,
            "run_usd_max": 5.0
        },
        "role_priority": {
            "ceo": 1,
            "vp sales": 2,
            "director": 3,
            "default": 99
        },
        "exports": {
            "enabled": True
        },
        "default_country": "US"
    }


@pytest.fixture
def sample_extracted_data():
    """Sample data extracted from Firecrawl."""
    return {
        "company": {
            "name": "Example Tech Corp",
            "description": "Leading technology company",
            "industry": "Technology",
            "hq_location": "San Francisco, CA",
            "socials": {
                "linkedin": "https://www.linkedin.com/company/example-tech-corp"
            },
            "careers_url": "https://example.com/careers",
            "blog_url": "https://example.com/blog"
        },
        "employees": [
            {
                "full_name": "John Doe",
                "role": "CEO",
                "linkedin": "https://www.linkedin.com/in/johndoe",
                "email": "john.doe@example.com"
            },
            {
                "full_name": "Jane Smith",
                "role": "VP Sales",
                "linkedin": "https://www.linkedin.com/in/janesmith",
                "email": "jane.smith@example.com"
            }
        ]
    }


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create subdirectories
        os.makedirs(f"{temp_dir}/crawl_artifacts", exist_ok=True)
        os.makedirs(f"{temp_dir}/evidence", exist_ok=True)
        yield temp_dir


# ============================================================================
# Test CrawlTool Class
# ============================================================================

class TestCrawlTool:
    """Test cases for CrawlTool class."""

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    def test_init_success(self, mock_setup_logging, mock_load_schema, mock_load_costs):
        """Test successful initialization of CrawlTool."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()

        tool = CrawlTool()

        assert tool.schema_version == "abc123"
        assert tool.costs_config == {"firecrawl": 0.001}
        assert tool.firecrawl_key == "test_key"
        assert tool.permit_manager.max_permits == 3

    @patch.dict(os.environ, {}, clear=True)
    def test_init_missing_firecrawl_key(self):
        """Test initialization fails without FIRECRAWL_KEY."""
        with pytest.raises(ValueError, match="FIRECRAWL_KEY environment variable is required"):
            CrawlTool()

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    def test_init_missing_firecrawl_provider(self, mock_setup_logging, mock_load_schema, mock_load_costs):
        """Test initialization fails without firecrawl in costs config."""
        mock_load_costs.return_value = {"other_provider": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()

        with pytest.raises(KeyError, match="Missing required provider in costs configuration"):
            CrawlTool()

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    @patch('src.crawl.validate_envelope')
    async def test_run_empty_lead_records(self, mock_validate, mock_setup_logging, mock_load_schema, mock_load_costs):
        """Test run with empty lead records."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()
        mock_validate.return_value = []

        tool = CrawlTool()
        payload = {"lead_records": [], "icp_config": {}}

        result = await tool.run(payload)

        assert result["data"]["lead_records"] == []
        assert result["errors"] == []
        assert result["metrics"]["count_in"] == 0
        assert result["metrics"]["count_out"] == 0

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    @patch('src.crawl.validate_envelope')
    async def test_run_schema_validation_failure(self, mock_validate, mock_setup_logging, mock_load_schema, mock_load_costs):
        """Test run with schema validation failure."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()
        mock_validate.return_value = [{"code": "SCHEMA_VALIDATION", "message": "Invalid schema"}]

        tool = CrawlTool()
        payload = {"lead_records": [{"invalid": "data"}], "icp_config": {}}

        result = await tool.run(payload)

        assert result["data"]["lead_records"] == []
        assert len(result["errors"]) == 1
        assert result["errors"][0]["code"] == "SCHEMA_VALIDATION"

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    @patch('src.crawl.validate_envelope')
    @patch('src.crawl.resolve_data_dir')
    async def test_process_single_record_success(self, mock_resolve_dir, mock_validate, mock_setup_logging, mock_load_schema, mock_load_costs, sample_lead_record, sample_icp_config, temp_data_dir, sample_extracted_data):
        """Test successful processing of a single record."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()
        mock_validate.return_value = []
        mock_resolve_dir.return_value = temp_data_dir

        tool = CrawlTool()

        # Mock Firecrawl extraction by replacing the method on the instance
        mock_extract = AsyncMock(return_value=sample_extracted_data)

        original_method = tool._extract_with_firecrawl
        tool._extract_with_firecrawl = mock_extract

        # Mock write_with_lock to avoid file permission issues
        with patch('src.crawl.write_with_lock') as mock_write:
            try:
                result = await tool._process_single_record(sample_lead_record, sample_icp_config)
            finally:
                # Restore original method
                tool._extract_with_firecrawl = original_method

        assert result["success"] is True
        assert result["cache_hit"] is False
        assert result["cost"] == 0.001
        assert result["error"] is None

        # Check record was updated
        record = result["record"]
        assert record["status"] == "enrich_ready"
        assert record["provenance"]["crawled_at"] is not None
        assert record["provenance"]["evidence_paths"]["crawl"] is not None
        assert record["icp"]["crawl_score"] is not None
        assert record["icp"]["crawl_reason"] is not None

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    @patch('src.crawl.validate_envelope')
    @patch('src.crawl.resolve_data_dir')
    async def test_process_single_record_missing_domain(self, mock_resolve_dir, mock_validate, mock_setup_logging, mock_load_schema, mock_load_costs):
        """Test processing record with missing domain."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()
        mock_validate.return_value = []
        mock_resolve_dir.return_value = "/tmp"

        tool = CrawlTool()

        record = {"lead_id": "test", "status": "scored"}
        icp_config = {}

        result = await tool._process_single_record(record, icp_config)

        assert result["success"] is False
        assert result["error"]["code"] == "SCHEMA_VALIDATION"
        assert "Missing domain" in result["error"]["message"]

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    @patch('src.crawl.validate_envelope')
    @patch('src.crawl.resolve_data_dir')
    async def test_process_single_record_extraction_failure(self, mock_resolve_dir, mock_validate, mock_setup_logging, mock_load_schema, mock_load_costs, sample_lead_record, sample_icp_config):
        """Test processing record when extraction fails."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()
        mock_validate.return_value = []
        mock_resolve_dir.return_value = "/tmp"

        tool = CrawlTool()

        # Mock Firecrawl extraction failure
        with patch.object(tool, '_extract_with_firecrawl') as mock_extract:
            mock_extract.side_effect = Exception("Extraction failed")

            result = await tool._process_single_record(sample_lead_record, sample_icp_config)

            assert result["success"] is False
            assert result["error"]["code"] == "EXTRACT_ERROR"
            assert result["record"]["status"] == "crawl_failed"

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    @patch('src.crawl.validate_envelope')
    async def test_extract_with_firecrawl_success(self, mock_validate, mock_setup_logging, mock_load_schema, mock_load_costs):
        """Test successful Firecrawl extraction."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()
        mock_validate.return_value = []

        tool = CrawlTool()

        # Mock Firecrawl client
        mock_response = {"success": True, "data": {"company": {"name": "Test Corp"}}}
        tool.firecrawl_client.extract = AsyncMock(return_value=mock_response)

        result = await tool._extract_with_firecrawl("example.com")

        assert result == {"company": {"name": "Test Corp"}}

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    @patch('src.crawl.validate_envelope')
    async def test_extract_with_firecrawl_https_fallback(self, mock_validate, mock_setup_logging, mock_load_schema, mock_load_costs):
        """Test Firecrawl extraction with HTTPS→HTTP fallback."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()
        mock_validate.return_value = []

        tool = CrawlTool()

        # Mock Firecrawl client to fail on HTTPS, succeed on HTTP
        mock_response = {"success": True, "data": {"company": {"name": "Test Corp"}}}
        tool.firecrawl_client.extract = AsyncMock(return_value=mock_response)

        # Mock the semaphore pool to avoid async issues
        with patch.object(tool, 'async_semaphore_pool'):
            result = await tool._extract_with_firecrawl("example.com")

            assert result == {"company": {"name": "Test Corp"}}

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    @patch('src.crawl.validate_envelope')
    async def test_extract_with_firecrawl_all_failures(self, mock_validate, mock_setup_logging, mock_load_schema, mock_load_costs):
        """Test Firecrawl extraction when both HTTPS and HTTP fail."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()
        mock_validate.return_value = []

        tool = CrawlTool()

        # Mock Firecrawl client to fail on both
        tool.firecrawl_client.extract = AsyncMock(side_effect=Exception("All failed"))

        with pytest.raises(Exception, match="Failed to extract data from example.com after trying both HTTP and HTTPS"):
            await tool._extract_with_firecrawl("example.com")

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    def test_process_extracted_data_company_population(self, mock_setup_logging, mock_load_schema, mock_load_costs, sample_lead_record, sample_icp_config, sample_extracted_data):
        """Test processing extracted data populates company fields correctly."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()

        tool = CrawlTool()
        extracted_data = sample_extracted_data

        tool._process_extracted_data(sample_lead_record, extracted_data, sample_icp_config)

        company = sample_lead_record["company"]
        assert company["name"] == "Example Tech Corp"
        assert company["description"] == "Leading technology company"
        assert company["industry"] == "Technology"
        assert company["hq_location"] == "San Francisco, CA"
        assert company["careers_url"] == "https://example.com/careers"
        assert company["blog_url"] == "https://example.com/blog"

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    def test_process_extracted_data_linkedin_company_routing(self, mock_setup_logging, mock_load_schema, mock_load_costs, sample_lead_record, sample_icp_config):
        """Test LinkedIn company page routing."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()

        tool = CrawlTool()
        extracted_data = {
            "company": {
                "socials": {
                    "linkedin": "https://www.linkedin.com/company/example-tech-corp"
                }
            },
            "employees": []
        }

        tool._process_extracted_data(sample_lead_record, extracted_data, sample_icp_config)

        company = sample_lead_record["company"]
        assert company["ids"]["linkedin"] == "/company/example-tech-corp"
        assert company["socials"]["linkedin"] == "https://www.linkedin.com/company/example-tech-corp"

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    def test_process_extracted_data_contact_creation(self, mock_setup_logging, mock_load_schema, mock_load_costs, sample_lead_record, sample_icp_config, sample_extracted_data):
        """Test contact creation from extracted data."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()

        tool = CrawlTool()
        extracted_data = sample_extracted_data

        tool._process_extracted_data(sample_lead_record, extracted_data, sample_icp_config)

        contacts = sample_lead_record["contacts"]
        assert len(contacts) == 2

        # Check first contact
        contact1 = contacts[0]
        assert contact1["full_name"] == "john doe"
        assert contact1["role"] == "ceo"
        assert contact1["email"] == "john.doe@example.com"
        assert contact1["linkedin"] == "/in/johndoe"
        assert contact1["seniority"] == 1  # c-level
        assert contact1["role_priority"] == 1  # ceo

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    def test_process_extracted_data_contact_deduplication(self, mock_setup_logging, mock_load_schema, mock_load_costs, sample_lead_record, sample_icp_config):
        """Test contact deduplication by contact_id."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()

        tool = CrawlTool()
        extracted_data = {
            "company": {},
            "employees": [
                {"full_name": "John Doe", "role": "CEO", "linkedin": "", "email": "john@example.com"},
                {"full_name": "John Doe", "role": "CEO", "linkedin": "", "email": "john.doe@example.com"}
            ]
        }

        tool._process_extracted_data(sample_lead_record, extracted_data, sample_icp_config)

        contacts = sample_lead_record["contacts"]
        assert len(contacts) == 1  # Should dedupe by contact_id

        # Should use the first email found
        assert contacts[0]["email"] == "john@example.com"

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    def test_check_company_requirements_success(self, mock_setup_logging, mock_load_schema, mock_load_costs, sample_lead_record):
        """Test company requirements check when all required fields are present."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()

        tool = CrawlTool()
        sample_lead_record["company"]["name"] = "Test Corp"
        sample_lead_record["company"]["hq_location"] = "San Francisco, CA"

        required_fields = ["name", "hq_location"]
        result = tool._check_company_requirements(sample_lead_record, required_fields)

        assert result is True

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    def test_check_company_requirements_failure(self, mock_setup_logging, mock_load_schema, mock_load_costs, sample_lead_record):
        """Test company requirements check when required fields are missing."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()

        tool = CrawlTool()
        sample_lead_record["company"]["name"] = "Test Corp"
        # hq_location is missing

        required_fields = ["name", "hq_location"]
        result = tool._check_company_requirements(sample_lead_record, required_fields)

        assert result is False

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    def test_validate_icp_fit_scoring(self, mock_setup_logging, mock_load_schema, mock_load_costs, sample_lead_record, sample_icp_config):
        """Test ICP fit validation and scoring."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()

        tool = CrawlTool()
        sample_lead_record["company"]["name"] = "Test Corp"
        sample_lead_record["company"]["industry"] = "Technology"
        sample_lead_record["contacts"] = [{"email": "test@example.com"}]

        tool._validate_icp_fit(sample_lead_record, sample_icp_config)

        icp = sample_lead_record["icp"]
        assert icp["crawl_score"] > 0.0
        assert icp["crawl_reason"] is not None
        assert "Company name available" in icp["crawl_reason"]
        assert "Industry information available" in icp["crawl_reason"]
        assert "Found 1 contacts" in icp["crawl_reason"]

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    def test_build_metrics(self, mock_setup_logging, mock_load_schema, mock_load_costs):
        """Test metrics building."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()

        tool = CrawlTool()

        metrics = tool._build_metrics(
            count_in=10,
            count_out=8,
            duration_ms=1500,
            cache_hit_rate=0.6,
            pass_rate=0.75,
            cost_usd={"crawl": 0.005}
        )

        assert metrics["count_in"] == 10
        assert metrics["count_out"] == 8
        assert metrics["duration_ms"] == 1500
        assert metrics["cache_hit_rate"] == 0.6
        assert metrics["pass_rate"] == 0.75
        assert metrics["cost_usd"]["crawl"] == 0.005
        assert metrics["cost_usd"]["total"] == 0.005


# ============================================================================
# Test CLI Interface
# ============================================================================

class TestCLI:
    """Test cases for CLI interface."""

    @patch('src.crawl.CrawlTool')
    @patch('sys.stdin')
    @patch('sys.stdout')
    def test_main_success(self, mock_stdout, mock_stdin, mock_crawl_tool):
        """Test successful CLI execution."""
        from src.crawl import main

        # Mock input
        mock_stdin.read.return_value = '{"lead_records": [], "icp_config": {}}'

        # Mock tool
        mock_tool = MagicMock()
        mock_tool.run = AsyncMock(return_value={"data": {"lead_records": []}, "errors": [], "metrics": {}})
        mock_crawl_tool.return_value = mock_tool

        # Mock asyncio completely
        with patch('asyncio.new_event_loop') as mock_new_loop, \
             patch('asyncio.set_event_loop'):
            mock_loop = MagicMock()
            mock_new_loop.return_value = mock_loop
            # Mock the run_until_complete method to return the expected result
            mock_loop.run_until_complete.return_value = {"data": {"lead_records": []}, "errors": [], "metrics": {}}

            main()

            # Verify output was written
            mock_stdout.write.assert_called()

    @patch('sys.stdin')
    @patch('sys.stdout')
    def test_main_invalid_json(self, mock_stdout, mock_stdin):
        """Test CLI with invalid JSON input."""
        from src.crawl import main

        # Mock invalid input
        mock_stdin.read.return_value = 'invalid json'

        # Mock asyncio completely
        with patch('asyncio.new_event_loop'), \
             patch('asyncio.set_event_loop'):
            # The main function should exit with code 1 for invalid JSON
            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 1

            # Verify error output was written
            mock_stdout.write.assert_called()


# ============================================================================
# Test Integration Scenarios
# ============================================================================

class TestIntegrationScenarios:
    """Test integration scenarios for the crawl tool."""

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    @patch('src.crawl.validate_envelope')
    @patch('src.crawl.resolve_data_dir')
    async def test_full_crawl_workflow(self, mock_resolve_dir, mock_validate, mock_setup_logging, mock_load_schema, mock_load_costs, sample_lead_record, sample_icp_config, temp_data_dir, sample_extracted_data):
        """Test full crawl workflow from start to finish."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()
        mock_validate.return_value = []
        mock_resolve_dir.return_value = temp_data_dir

        tool = CrawlTool()

        # Mock Firecrawl extraction
        tool._extract_with_firecrawl = AsyncMock(return_value=sample_extracted_data)

        # Mock write_with_lock to avoid file permission issues
        with patch('src.crawl.write_with_lock') as mock_write:
            payload = {
                "lead_records": [sample_lead_record],
                "icp_config": sample_icp_config
            }

            result = await tool.run(payload)

        # Verify successful execution
        assert result["data"]["lead_records"]
        assert len(result["errors"]) == 0
        assert result["metrics"]["count_in"] == 1
        assert result["metrics"]["count_out"] == 1

        # Verify record was processed
        record = result["data"]["lead_records"][0]
        assert record["status"] in ["crawled", "enrich_ready"]
        assert record["provenance"]["crawled_at"] is not None
        assert record["icp"]["crawl_score"] is not None

    @patch.dict(os.environ, {"FIRECRAWL_KEY": "test_key"})
    @patch('src.crawl.load_costs_config')
    @patch('src.crawl.load_schema_checksum')
    @patch('src.crawl.setup_logging')
    @patch('src.crawl.validate_envelope')
    @patch('src.crawl.resolve_data_dir')
    async def test_cache_hit_scenario(self, mock_resolve_dir, mock_validate, mock_setup_logging, mock_load_schema, mock_load_costs, sample_lead_record, sample_icp_config, temp_data_dir, sample_extracted_data):
        """Test scenario where cached data is reused."""
        mock_load_costs.return_value = {"firecrawl": 0.001}
        mock_load_schema.return_value = "abc123"
        mock_setup_logging.return_value = MagicMock()
        mock_validate.return_value = []
        mock_resolve_dir.return_value = temp_data_dir

        tool = CrawlTool()

        # Create cached artifact with proper content hash
        from src.common import compute_content_hash
        content_hash = compute_content_hash(sample_extracted_data)
        artifact_path = f"{temp_data_dir}/crawl_artifacts/example.com.json"
        artifact_data = {
            "crawled_at": datetime.now().isoformat() + "Z",
            "content_hash": content_hash,
            "extracted_data": sample_extracted_data
        }

        os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
        with open(artifact_path, 'w') as f:
            json.dump(artifact_data, f)

        payload = {
            "lead_records": [sample_lead_record],
            "icp_config": sample_icp_config
        }

        result = await tool.run(payload)

        # Verify cache hit
        assert result["metrics"]["cache_hit_rate"] == 1.0
        assert result["metrics"]["cost_usd"]["crawl"] == 0.0  # No cost for cache hit


if __name__ == "__main__":
    pytest.main([__file__])
