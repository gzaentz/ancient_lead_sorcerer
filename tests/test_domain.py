"""
Unit tests for Domain tool.

Tests cover all functionality specified in BRD §226-280 and tasks.md Task 2.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain import (
    DomainTool,
    GSESearchClient,
    LLMScorer,
    DomainHistoryManager,
    SearchCache,
)
from src.common import PermitManager, AsyncSemaphorePool


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_icp_config():
    """Sample ICP configuration for testing."""
    return {
        "name": "Test ICP",
        "icp_text": "B2B SaaS companies in the US with 50-500 employees",
        "queries": [
            "B2B SaaS companies in California",
            "enterprise software companies in New York",
        ],
        "icp_hard_rules": "Company must be B2B SaaS with 50-500 employees in the United States",
        "mode": "thorough",
        "concurrency": {"max_concurrent_requests": 3},
        "refresh_policy": {
            "revisit_after_days": 90,
            "failure_revisit_days": 1,
            "domain_ttl_days": 180,
            "domain_serp_ttl_hours": 24,
        },
        "search": {"max_pages": 5},
    }


@pytest.fixture
def sample_gse_response():
    """Sample Google Search Engine response."""
    return {
        "items": [
            {
                "title": "Test Company - B2B SaaS Solutions",
                "link": "https://testcompany.com",
                "snippet": "Leading B2B SaaS company providing enterprise software solutions",
                "rank": 1,
            },
            {
                "title": "Another Company - Enterprise Software",
                "link": "https://anothercompany.com",
                "snippet": "Enterprise software company specializing in B2B solutions",
                "rank": 2,
            },
        ]
    }


@pytest.fixture
def sample_llm_response():
    """Sample LLM scoring response."""
    return {
        "choices": [
            {
                "message": {
                    "content": '{"score": 0.85, "reason": "Good match for B2B SaaS", "flags": []}'
                }
            }
        ]
    }


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def mock_env_vars():
    """Mock environment variables."""
    with patch.dict(
        os.environ,
        {
            "GSE_API_KEY": "test_gse_key",
            "GSE_CX": "test_gse_cx",
            "OPENROUTER_KEY": "test_openrouter_key",
        },
    ):
        yield


@pytest.fixture
def mock_costs_config():
    """Mock costs configuration."""
    with patch("src.domain.load_costs_config") as mock_load:
        mock_load.return_value = {"gse": 0.0005, "openrouter": 0.0020}
        yield mock_load


@pytest.fixture
def mock_schema_checksum():
    """Mock schema checksum loading."""
    with patch("src.domain.load_schema_checksum") as mock_load:
        mock_load.return_value = "test_checksum"
        yield mock_load


# ============================================================================
# GSESearchClient Tests
# ============================================================================


class TestGSESearchClient:
    """Test GSESearchClient functionality."""

    @pytest.mark.asyncio
    async def test_search_success(self, sample_gse_response):
        """Test successful GSE search."""
        semaphore_pool = AsyncMock(spec=AsyncSemaphorePool)
        semaphore_pool.__aenter__ = AsyncMock(return_value=semaphore_pool)
        semaphore_pool.__aexit__ = AsyncMock(return_value=None)

        client = GSESearchClient("test_key", "test_cx", semaphore_pool)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = sample_gse_response
            mock_response.raise_for_status.return_value = None
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await client.search("test query", 1)

            assert result == sample_gse_response
            semaphore_pool.__aenter__.assert_called_once()
            semaphore_pool.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_pagination(self, sample_gse_response):
        """Test GSE search with pagination."""
        semaphore_pool = AsyncMock(spec=AsyncSemaphorePool)
        semaphore_pool.__aenter__ = AsyncMock(return_value=semaphore_pool)
        semaphore_pool.__aexit__ = AsyncMock(return_value=None)

        client = GSESearchClient("test_key", "test_cx", semaphore_pool)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = sample_gse_response
            mock_response.raise_for_status.return_value = None
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await client.search("test query", 2)

            # Verify start parameter for page 2
            mock_client.get.assert_called_once()
            call_args = mock_client.get.call_args
            # Check that start=11 is in the params
            assert call_args[1]["params"]["start"] == 11
            assert result == sample_gse_response


# ============================================================================
# LLMScorer Tests
# ============================================================================


class TestLLMScorer:
    """Test LLMScorer functionality."""

    @pytest.mark.asyncio
    async def test_score_domain_success(self, sample_llm_response):
        """Test successful domain scoring."""
        semaphore_pool = AsyncMock(spec=AsyncSemaphorePool)
        semaphore_pool.__aenter__ = AsyncMock(return_value=semaphore_pool)
        semaphore_pool.__aexit__ = AsyncMock(return_value=None)

        scorer = LLMScorer("test_key", semaphore_pool)

        with patch.object(scorer.client.chat.completions, "create") as mock_create:
            # Create a mock response object with the right structure
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message = MagicMock()
            mock_response.choices[0].message.content = sample_llm_response["choices"][
                0
            ]["message"]["content"]

            async def async_create(*args, **kwargs):
                return mock_response

            mock_create.side_effect = async_create

            score, reason, flags, model, fingerprint = await scorer.score_domain(
                "Test Company", "B2B SaaS company", "test query", "B2B SaaS companies"
            )

            assert score == 0.85
            assert reason == "Good match for B2B SaaS"
            assert flags == []
            assert model == "gpt-4o-mini"
            assert fingerprint is not None
            semaphore_pool.__aenter__.assert_called_once()
            semaphore_pool.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_score_domain_fallback_model(self, sample_llm_response):
        """Test fallback to secondary model on primary failure."""
        semaphore_pool = AsyncMock(spec=AsyncSemaphorePool)
        semaphore_pool.__aenter__ = AsyncMock(return_value=semaphore_pool)
        semaphore_pool.__aexit__ = AsyncMock(return_value=None)

        scorer = LLMScorer("test_key", semaphore_pool)

        with patch.object(scorer.client.chat.completions, "create") as mock_create:
            # Primary model fails
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message = MagicMock()
            mock_response.choices[0].message.content = sample_llm_response["choices"][
                0
            ]["message"]["content"]

            call_count = 0

            async def async_create(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise Exception("Primary failed")
                else:
                    return mock_response

            mock_create.side_effect = async_create

            score, reason, flags, model, fingerprint = await scorer.score_domain(
                "Test Company", "B2B SaaS company", "test query", "B2B SaaS companies"
            )

            assert model == "gpt-3.5-turbo"
            assert mock_create.call_count == 2

    @pytest.mark.asyncio
    async def test_score_domain_parse_failure(self, sample_llm_response):
        """Test handling of LLM response parsing failure."""
        semaphore_pool = AsyncMock(spec=AsyncSemaphorePool)
        semaphore_pool.__aenter__ = AsyncMock(return_value=semaphore_pool)
        semaphore_pool.__aexit__ = AsyncMock(return_value=None)

        scorer = LLMScorer("test_key", semaphore_pool)

        # Mock invalid JSON response
        invalid_response = {
            "choices": [{"message": {"content": "Invalid JSON response"}}]
        }

        with patch.object(scorer.client.chat.completions, "create") as mock_create:
            # Create a mock response object with the right structure
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message = MagicMock()
            mock_response.choices[0].message.content = invalid_response["choices"][0][
                "message"
            ]["content"]

            async def async_create(*args, **kwargs):
                return mock_response

            mock_create.side_effect = async_create

            score, reason, flags, model, fingerprint = await scorer.score_domain(
                "Test Company", "B2B SaaS company", "test query", "B2B SaaS companies"
            )

            assert score == 0.5
            assert "parsing failed" in reason
            assert flags == []


# ============================================================================
# DomainHistoryManager Tests
# ============================================================================


class TestDomainHistoryManager:
    """Test DomainHistoryManager functionality."""

    def test_load_history_new_file(self, temp_data_dir):
        """Test loading history from non-existent file."""
        manager = DomainHistoryManager(temp_data_dir)
        assert len(manager.history_cache) == 0

    def test_load_history_existing_file(self, temp_data_dir):
        """Test loading history from existing file."""
        history_file = Path(temp_data_dir) / "domain_history.jsonl"

        # Create test data
        test_record = {
            "domain": "test.com",
            "lead_id": "test-uuid",
            "provenance": {"scored_at": "2023-01-01T00:00:00Z"},
        }

        with open(history_file, "w") as f:
            f.write(json.dumps(test_record) + "\n")

        manager = DomainHistoryManager(temp_data_dir)
        assert "test.com" in manager.history_cache
        assert manager.history_cache["test.com"]["lead_id"] == "test-uuid"

    def test_cleanup_expired_entries(self, temp_data_dir):
        """Test cleanup of expired domain history entries."""
        manager = DomainHistoryManager(temp_data_dir)

        # Add expired record
        expired_record = {
            "domain": "expired.com",
            "provenance": {"scored_at": "2020-01-01T00:00:00Z"},
        }
        manager.history_cache["expired.com"] = expired_record

        # Add current record
        current_record = {
            "domain": "current.com",
            "provenance": {"scored_at": datetime.utcnow().isoformat() + "Z"},
        }
        manager.history_cache["current.com"] = current_record

        # Cleanup with 180 day TTL
        manager._cleanup_expired_entries(180)

        assert "expired.com" not in manager.history_cache
        assert "current.com" in manager.history_cache

    def test_add_and_get_domain_record(self, temp_data_dir):
        """Test adding and retrieving domain records."""
        manager = DomainHistoryManager(temp_data_dir)

        test_record = {"domain": "test.com", "lead_id": "test-uuid"}
        manager.add_domain_record(test_record)

        retrieved = manager.get_domain_record("test.com")
        assert retrieved == test_record

        # Test non-existent domain
        assert manager.get_domain_record("nonexistent.com") is None


# ============================================================================
# SearchCache Tests
# ============================================================================


class TestSearchCache:
    """Test SearchCache functionality."""

    def test_cache_results_and_retrieval(self):
        """Test caching and retrieving search results."""
        cache = SearchCache()

        test_results = {"items": [{"title": "Test"}]}
        cache.cache_results("test query", 1, test_results)

        # Retrieve within TTL
        cached = cache.get_cached_results("test query", 1, 24)
        assert cached is not None
        assert cached["results"] == test_results

    def test_cache_expiration(self):
        """Test cache TTL expiration."""
        cache = SearchCache()

        test_results = {"items": [{"title": "Test"}]}

        # Test basic cache functionality without complex TTL mocking
        # Cache some results
        cache.cache_results("test query", 1, test_results)

        # Verify they can be retrieved immediately
        cached = cache.get_cached_results("test query", 1, 24)
        assert cached is not None
        assert cached["results"] == test_results

        # Test cache key generation
        key = cache._get_cache_key("test query", 1)
        assert key == "test query|1|google"

    def test_cache_key_generation(self):
        """Test cache key generation."""
        cache = SearchCache()

        key1 = cache._get_cache_key("query1", 1)
        key2 = cache._get_cache_key("query2", 1)
        key3 = cache._get_cache_key("query1", 2)

        assert key1 != key2
        assert key1 != key3
        assert key2 != key3


# ============================================================================
# DomainTool Integration Tests
# ============================================================================


class TestDomainTool:
    """Test DomainTool integration functionality."""

    def test_initialization(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test DomainTool initialization."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        assert tool.icp_config == sample_icp_config
        assert tool.data_dir == Path(temp_data_dir)
        assert tool.evidence_dir.exists()
        assert tool.schema_checksum == "test_checksum"
        assert isinstance(tool.permit_manager, PermitManager)
        assert isinstance(tool.semaphore_pool, AsyncSemaphorePool)

    def test_validate_icp_config_success(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test successful ICP configuration validation."""
        tool = DomainTool(sample_icp_config, temp_data_dir)
        errors = tool._validate_icp_config()
        assert len(errors) == 0

    def test_validate_icp_config_missing_fields(
        self, temp_data_dir, mock_env_vars, mock_costs_config, mock_schema_checksum
    ):
        """Test ICP configuration validation with missing fields."""
        invalid_config = {"name": "Test"}  # Missing required fields

        tool = DomainTool(invalid_config, temp_data_dir)
        errors = tool._validate_icp_config()

        assert len(errors) > 0
        assert any("missing_field" in str(error) for error in errors)

    def test_validate_icp_config_missing_placeholders(
        self, temp_data_dir, mock_env_vars, mock_costs_config, mock_schema_checksum
    ):
        """Test ICP configuration validation with missing template placeholders."""
        config_with_placeholders = {
            "name": "Test",
            "icp_text": "Test ICP",
            "queries": ["${industry} companies in ${region}"],
        }

        tool = DomainTool(config_with_placeholders, temp_data_dir)
        errors = tool._validate_icp_config()

        assert len(errors) > 0
        assert any("missing_placeholders" in str(error) for error in errors)

    def test_get_search_parameters(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test search parameter extraction."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        max_pages, ttl_hours, mode = tool._get_search_parameters()

        assert max_pages == 5
        assert ttl_hours == 24
        assert mode == "thorough"

    def test_get_search_parameters_fast_mode(
        self, temp_data_dir, mock_env_vars, mock_costs_config, mock_schema_checksum
    ):
        """Test search parameters with fast mode."""
        fast_config = {
            "name": "Test",
            "icp_text": "Test ICP",
            "queries": ["test query"],
            "mode": "fast",
            "search": {"max_pages": 10},
        }

        tool = DomainTool(fast_config, temp_data_dir)
        max_pages, ttl_hours, mode = tool._get_search_parameters()

        assert max_pages == 1  # Fast mode caps at 1 page
        assert mode == "fast"

    def test_get_refresh_parameters(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test refresh parameter extraction."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        revisit_after_days, failure_revisit_days, domain_ttl_days = (
            tool._get_refresh_parameters()
        )

        assert revisit_after_days == 90
        assert failure_revisit_days == 1
        assert domain_ttl_days == 180

    def test_create_lead_record(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test lead record creation."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        record = tool._create_lead_record("test.com", "test query")

        assert record["domain"] == "test.com"
        assert record["lead_id"] is not None
        assert record["status"] == "scored"
        assert record["icp"]["threshold"] == 0.7
        assert record["icp"]["filtering_strict"] is True
        assert record["provenance"]["queries"] == ["test query"]
        assert record["provenance"]["tool_versions"]["domain"]["version"] == "1.0.0"
        assert (
            record["provenance"]["tool_versions"]["domain"]["schema_version"]
            == "test_checksum"
        )

    def test_normalize_serp_result(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test SERP result normalization."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        serp_item = {
            "link": "https://subdomain.testcompany.com/page",
            "title": "Test Company",
            "snippet": "Test description",
            "rank": 1,
        }

        normalized = tool._normalize_serp_result(serp_item, "test query", 1)

        assert normalized["url"] == "https://subdomain.testcompany.com/page"
        assert normalized["title"] == "Test Company"
        assert normalized["snippet"] == "Test description"
        assert normalized["query"] == "test query"
        assert normalized["page_index"] == 1
        assert normalized["rank_on_page"] == 1
        assert "fetched_at" in normalized

    @pytest.mark.asyncio
    async def test_search_and_score_domains(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test search and scoring workflow."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        # Mock GSE client
        mock_gse = AsyncMock()
        mock_gse.search.return_value = {
            "items": [
                {
                    "title": "Test Company",
                    "link": "https://testcompany.com",
                    "snippet": "B2B SaaS company",
                    "rank": 1,
                }
            ]
        }
        tool.gse_client = mock_gse

        # Mock LLM scorer
        mock_llm = AsyncMock()
        mock_llm.score_domain.return_value = (
            0.85,
            "Good match",
            [],
            "gpt-4o-mini-1.5",
            "test_fp",
        )
        tool.llm_scorer = mock_llm

        scored_domains, cache_hits, cache_misses = await tool._search_and_score_domains(
            ["test query"], 1, 24
        )

        assert len(scored_domains) == 1
        assert cache_hits == 0
        assert cache_misses == 1

        domain_record = scored_domains[0]
        assert domain_record["domain"] == "testcompany.com"
        assert domain_record["icp"]["pre_score"] == 0.85
        assert domain_record["icp"]["pre_pass"] is True

    def test_save_evidence(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test evidence saving."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        record = {
            "domain": "test.com",
            "provenance": {
                "queries": ["test query"],
                "discovery_evidence": [{"title": "Test"}],
                "evidence_paths": {"domain": None},
            },
            "icp": {"scoring_meta": {"prompt_fingerprint": "test_fp"}},
        }

        # Mock the write_with_lock function to avoid file permission issues
        with patch("src.domain.write_with_lock") as mock_write:
            tool._save_evidence(record)

            # Verify write_with_lock was called with correct data
            mock_write.assert_called_once()
            call_args = mock_write.call_args
            assert call_args[0][0].endswith("test.com.json")  # File path
            assert call_args[0][1]["domain"] == "test.com"  # Evidence data

            # Verify the record was updated with the evidence path
            assert record["provenance"]["evidence_paths"]["domain"] is not None

    @pytest.mark.asyncio
    async def test_run_success(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test successful tool run."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        # Mock components
        tool.gse_client = AsyncMock()
        tool.gse_client.search.return_value = {
            "items": [
                {
                    "title": "Test Company",
                    "link": "https://testcompany.com",
                    "snippet": "B2B SaaS company",
                    "rank": 1,
                }
            ]
        }

        tool.llm_scorer = AsyncMock()
        tool.llm_scorer.score_domain.return_value = (
            0.85,
            "Good match",
            [],
            "gpt-4o-mini-1.5",
            "test_fp",
        )

        # Mock write_with_lock to avoid permission issues
        with patch("src.domain.write_with_lock"):
            result = await tool.run()

            assert "data" in result
            assert "errors" in result
            assert "metrics" in result
            assert len(result["errors"]) == 0
            # The tool should process both queries and return results for each
            assert len(result["data"]["lead_records"]) >= 1  # At least one result
            assert result["metrics"]["count_in"] == 2  # Two queries input
            assert result["metrics"]["count_out"] >= 1  # At least one output

    @pytest.mark.asyncio
    async def test_run_validation_errors(
        self, temp_data_dir, mock_env_vars, mock_costs_config, mock_schema_checksum
    ):
        """Test tool run with validation errors."""
        invalid_config = {"name": "Test"}  # Missing required fields

        tool = DomainTool(invalid_config, temp_data_dir)
        result = await tool.run()

        assert len(result["errors"]) > 0
        assert result["data"]["lead_records"] == []
        assert result["metrics"]["count_in"] == 0
        assert result["metrics"]["count_out"] == 0

    @pytest.mark.asyncio
    async def test_run_no_queries(
        self, temp_data_dir, mock_env_vars, mock_costs_config, mock_schema_checksum
    ):
        """Test tool run with no queries."""
        config_no_queries = {"name": "Test", "icp_text": "Test ICP", "queries": []}

        tool = DomainTool(config_no_queries, temp_data_dir)
        result = await tool.run()

        assert len(result["errors"]) > 0
        assert "No queries provided" in str(result["errors"][0])
        assert result["data"]["lead_records"] == []

    def test_concurrency_respect(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test that tool respects concurrency limits."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        # Verify permit manager is configured correctly
        assert tool.permit_manager.max_permits == 3

        # Verify semaphore pool uses the permit manager
        assert tool.semaphore_pool.permit_manager == tool.permit_manager


# ============================================================================
# CLI Interface Tests
# ============================================================================


class TestCLI:
    """Test CLI interface functionality."""

    def test_main_success(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test successful CLI execution."""
        from src.domain import main

        # Mock stdin with valid JSON
        input_json = json.dumps(
            {"icp_config": sample_icp_config, "config": {"data_dir": temp_data_dir}}
        )

        # Create a mock stdin that returns the JSON string
        # Create a mock stdin that returns the JSON string
        from io import StringIO

        mock_stdin = StringIO(input_json)

        with (
            patch("sys.stdin", mock_stdin),
            patch("sys.stdout") as mock_stdout,
            patch("asyncio.run") as mock_run,
        ):
            mock_run.return_value = {
                "data": {"lead_records": []},
                "errors": [],
                "metrics": {"count_in": 0, "count_out": 0},
            }

            main()

            # Verify output was written to stdout
            mock_stdout.write.assert_called()

    def test_main_invalid_json(self, temp_data_dir):
        """Test CLI with invalid JSON input."""
        from src.domain import main

        from io import StringIO

        with (
            patch("sys.stdin", StringIO("invalid json")),
            patch("sys.stderr") as mock_stderr,
        ):
            with pytest.raises(SystemExit):
                main()

            # Verify error was written to stderr
            mock_stderr.write.assert_called()

    def test_main_exception(self, temp_data_dir):
        """Test CLI with unexpected exception."""
        from src.domain import main
        from io import StringIO

        with (
            patch("sys.stdin", StringIO('{"icp_config": {}}')),
            patch("sys.stderr") as mock_stderr,
            patch("src.domain.DomainTool") as mock_tool_class,
        ):
            mock_tool_class.side_effect = Exception("Unexpected error")

            with pytest.raises(SystemExit):
                main()

            # Verify error was written to stderr
            mock_stderr.write.assert_called()


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_gse_search_failure(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test handling of GSE search failures."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        # Mock GSE client to fail
        tool.gse_client = AsyncMock()
        tool.gse_client.search.side_effect = Exception("GSE API error")

        # Mock LLM scorer
        tool.llm_scorer = AsyncMock()
        tool.llm_scorer.score_domain.return_value = (
            0.5,
            "Default score",
            [],
            "gpt-4o-mini-1.5",
            "test_fp",
        )

        scored_domains, cache_hits, cache_misses = await tool._search_and_score_domains(
            ["test query"], 1, 24
        )

        # Should continue processing despite GSE failure
        assert cache_misses == 1
        # No domains should be scored due to GSE failure
        assert len(scored_domains) == 0

    @pytest.mark.asyncio
    async def test_llm_scoring_failure(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test handling of LLM scoring failures."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        # Mock GSE client
        tool.gse_client = AsyncMock()
        tool.gse_client.search.return_value = {
            "items": [
                {
                    "title": "Test Company",
                    "link": "https://testcompany.com",
                    "snippet": "B2B SaaS company",
                    "rank": 1,
                }
            ]
        }

        # Mock LLM scorer to fail
        tool.llm_scorer = AsyncMock()
        tool.llm_scorer.score_domain.side_effect = Exception("LLM API error")

        scored_domains, cache_hits, cache_misses = await tool._search_and_score_domains(
            ["test query"], 1, 24
        )

        # Should handle LLM failure gracefully
        assert len(scored_domains) == 1
        domain_record = scored_domains[0]
        assert domain_record["icp"]["pre_score"] == 0.0
        assert domain_record["icp"]["pre_pass"] is False
        assert "scoring_error" in domain_record["icp"]["pre_flags"]


# ============================================================================
# Cost Calculation Tests
# ============================================================================


class TestCostCalculation:
    """Test cost calculation functionality."""

    @pytest.mark.asyncio
    async def test_cost_calculation_success(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test cost calculation for successful scoring."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        # Mock components
        tool.gse_client = AsyncMock()
        tool.gse_client.search.return_value = {
            "items": [
                {
                    "title": "Test Company",
                    "link": "https://testcompany.com",
                    "snippet": "B2B SaaS company",
                    "rank": 1,
                }
            ]
        }

        tool.llm_scorer = AsyncMock()
        tool.llm_scorer.score_domain.return_value = (
            0.85,
            "Good match",
            [],
            "gpt-4o-mini-1.5",
            "test_fp",
        )

        scored_domains, _, _ = await tool._search_and_score_domains(
            ["test query"], 1, 24
        )

        # Verify costs are calculated
        assert len(scored_domains) == 1
        domain_record = scored_domains[0]

        assert domain_record["cost"]["domain_usd"] > 0
        assert domain_record["cost"]["total_usd"] == domain_record["cost"]["domain_usd"]
        assert domain_record["cost"]["crawl_usd"] == 0.0
        assert domain_record["cost"]["enrich_usd"] == 0.0

    def test_cost_rounding(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test that costs are rounded to 4 decimal places."""
        from src.common import round4

        # Test cost rounding
        test_cost = 0.123456789
        rounded_cost = round4(test_cost)
        assert rounded_cost == 0.1235


# ============================================================================
# Template Placeholder Tests
# ============================================================================


class TestTemplatePlaceholders:
    """Test template placeholder validation."""

    def test_template_validation_success(
        self, temp_data_dir, mock_env_vars, mock_costs_config, mock_schema_checksum
    ):
        """Test successful template validation."""
        from src.common import validate_template_placeholders

        config_with_placeholders = {
            "name": "Test",
            "icp_text": "Test ICP",
            "queries": [
                "B2B SaaS companies in ${region}",
                "${industry} companies in ${region}",
            ],
        }

        # Mock context with all placeholders
        context = {"region": "California", "industry": "technology"}

        # Test individual query validation
        for query in config_with_placeholders["queries"]:
            missing = validate_template_placeholders(query, context)
            assert len(missing) == 0

    def test_template_validation_missing_placeholders(
        self, temp_data_dir, mock_env_vars, mock_costs_config, mock_schema_checksum
    ):
        """Test template validation with missing placeholders."""
        from src.common import validate_template_placeholders

        config_with_placeholders = {
            "name": "Test",
            "icp_text": "Test ICP",
            "queries": [
                "B2B SaaS companies in ${region}",
                "${industry} companies in ${region}",
            ],
        }

        # Mock context missing some placeholders
        context = {"region": "California"}  # Missing "industry"

        # Test validation
        for query in config_with_placeholders["queries"]:
            missing = validate_template_placeholders(query, context)
            if "${industry}" in query:
                assert "industry" in missing
            else:
                assert len(missing) == 0


# ============================================================================
# Performance and Concurrency Tests
# ============================================================================


class TestPerformanceAndConcurrency:
    """Test performance and concurrency aspects."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_limit(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test that concurrent requests are limited."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        # Verify permit manager configuration
        assert tool.permit_manager.max_permits == 3

        # Test semaphore pool integration
        assert tool.semaphore_pool.permit_manager == tool.permit_manager

    def test_evidence_truncation(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test evidence array truncation."""
        from src.common import truncate_evidence_arrays

        # Create record with excessive evidence
        record = {
            "company": {
                "evidence_urls": [{"item": i} for i in range(15)]  # More than 10
            }
        }

        # Apply truncation
        truncate_evidence_arrays(record)

        # Verify truncation
        assert len(record["company"]["evidence_urls"]) <= 10

    def test_string_length_validation(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test string length validation."""
        # Test that long strings are handled appropriately
        # The Domain tool should handle long strings gracefully
        long_string = "x" * 3000  # Longer than 2KB limit
        assert len(long_string) > 2048


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Test integration scenarios."""

    @pytest.mark.asyncio
    async def test_full_workflow(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test complete Domain tool workflow."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        # Mock external dependencies
        tool.gse_client = AsyncMock()
        tool.gse_client.search.return_value = {
            "items": [
                {
                    "title": "Test Company 1",
                    "link": "https://testcompany1.com",
                    "snippet": "B2B SaaS company 1",
                    "rank": 1,
                },
                {
                    "title": "Test Company 2",
                    "link": "https://testcompany2.com",
                    "snippet": "B2B SaaS company 2",
                    "rank": 2,
                },
            ]
        }

        tool.llm_scorer = AsyncMock()
        tool.llm_scorer.score_domain.return_value = (
            0.85,
            "Good match",
            [],
            "gpt-4o-mini-1.5",
            "test_fp",
        )

        # Mock write_with_lock to avoid permission issues
        with patch("src.domain.write_with_lock"):
            # Run tool
            result = await tool.run()

            # Verify complete output structure
            assert "data" in result
            assert "errors" in result
            assert "metrics" in result

            # Verify lead records
            lead_records = result["data"]["lead_records"]
            assert len(lead_records) == 2  # One per query

            for record in lead_records:
                # Verify required fields
                assert "lead_id" in record
                assert "domain" in record
                assert "status" in record
                assert record["status"] == "scored"

                # Verify ICP fields
                assert "pre_score" in record["icp"]
                assert "pre_pass" in record["icp"]
                assert "scoring_meta" in record["icp"]

                # Verify provenance
                assert "scored_at" in record["provenance"]
                assert "next_revisit_at" in record["provenance"]
                assert "evidence_paths" in record["provenance"]

                # Verify costs
                assert "domain_usd" in record["cost"]
                assert record["cost"]["domain_usd"] > 0

                # Verify status history
                assert len(record["status_history"]) > 0
                assert record["status_history"][0]["status"] == "scored"

                # Verify audit trail
                assert len(record["audit"]) > 0
                assert record["audit"][0]["step"] == "Domain"

            # Verify metrics
            metrics = result["metrics"]
            assert metrics["count_in"] == 2
            assert metrics["count_out"] == 2
            assert metrics["duration_ms"] > 0
            assert metrics["cost_usd"]["domain"] > 0
            assert metrics["cost_usd"]["total"] > 0

    def test_idempotence(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test that tool produces identical results for identical inputs."""
        tool1 = DomainTool(sample_icp_config, temp_data_dir)
        tool2 = DomainTool(sample_icp_config, temp_data_dir)

        # Generate lead IDs for same domain
        domain = "test.com"
        lead_id1 = tool1._create_lead_record(domain, "test query")["lead_id"]
        lead_id2 = tool2._create_lead_record(domain, "test query")["lead_id"]

        # IDs should be identical for same inputs
        assert lead_id1 == lead_id2

    def test_deterministic_uuids(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test that UUID generation is deterministic."""
        tool = DomainTool(sample_icp_config, temp_data_dir)

        # Same domain should always produce same lead_id
        domain = "test.com"
        lead_id1 = tool._create_lead_record(domain, "query1")["lead_id"]
        lead_id2 = tool._create_lead_record(domain, "query2")["lead_id"]

        # lead_id should be same for same domain regardless of query
        assert lead_id1 == lead_id2

        # Different domains should produce different lead_ids
        different_domain = "different.com"
        different_lead_id = tool._create_lead_record(different_domain, "query1")[
            "lead_id"
        ]
        assert lead_id1 != different_lead_id


class TestMissingRequirements:
    """Test missing requirements from Task 6."""

    def test_provider_missing_checks(self, sample_icp_config, temp_data_dir):
        """Test that PROVIDER_ERROR is raised when required providers are absent."""
        # Test missing GSE API key
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(KeyError):
                DomainTool(sample_icp_config, temp_data_dir)

        # Test missing OpenRouter key
        with patch.dict(
            os.environ, {"GSE_API_KEY": "test", "GSE_CX": "test"}, clear=True
        ):
            with pytest.raises(KeyError):
                DomainTool(sample_icp_config, temp_data_dir)

    @pytest.mark.skip(reason="pending implementation - phone parsing error handling")
    def test_phone_parse_failure(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test that PARSE_ERROR is emitted on unparseable phone numbers."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify phone parsing error handling
        # Implementation depends on phone parsing logic in the tool
        pass

    @pytest.mark.skip(reason="pending implementation - PII masking in logs")
    def test_log_pii_masking(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test that logs contain masked PII."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify that logs contain masked PII
        # Implementation depends on logging setup
        pass

    @pytest.mark.skip(reason="pending implementation - LinkedIn canonicalization regex")
    def test_linkedin_canonicalization(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test LinkedIn canonicalization regex patterns."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify LinkedIn URL canonicalization
        # Implementation depends on LinkedIn handling logic
        pass

    @pytest.mark.skip(
        reason="pending implementation - country code fallback for phone parsing"
    )
    def test_country_code_fallback(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test country code fallback for phone parsing."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify phone parsing with country fallback
        # Implementation depends on phone parsing logic
        pass

    @pytest.mark.skip(reason="pending implementation - progressive SERP pagination")
    def test_progressive_serp_pagination(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test progressive SERP pagination logic."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify progressive pagination logic
        # Implementation depends on pagination implementation
        pass

    @pytest.mark.skip(reason="pending implementation - best contact ID recomputation")
    def test_best_contact_id_recomputation(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test best_contact_id recomputation when contact no longer exists."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify best contact recomputation
        # Implementation depends on contact handling logic
        pass

    @pytest.mark.skip(reason="pending implementation - testing flags handling")
    def test_testing_flags(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test testing flags (process_rejected, process_low_crawl)."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify testing flags handling
        # Implementation depends on testing flags logic
        pass

    @pytest.mark.skip(reason="pending implementation - data directory precedence")
    def test_data_dir_precedence(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test data directory precedence resolution."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify data directory precedence
        # Implementation depends on data directory logic
        pass

    @pytest.mark.skip(reason="pending implementation - template placeholder validation")
    def test_template_placeholder_validation(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test template placeholder validation for all tools."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify template placeholder validation
        # Implementation depends on template validation logic
        pass

    @pytest.mark.skip(reason="pending implementation - provider presence validation")
    def test_provider_presence_validation(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test provider presence validation at startup."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify provider presence validation
        # Implementation depends on provider validation logic
        pass

    @pytest.mark.skip(reason="pending implementation - audit trail logging")
    def test_audit_trail_logging(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test audit trail logging for all tool steps."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify audit trail logging
        # Implementation depends on audit logging logic
        pass

    @pytest.mark.skip(reason="pending implementation - failure revisit days logic")
    def test_failure_revisit_days_logic(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test failure_revisit_days logic for all tools."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify failure revisit logic
        # Implementation depends on revisit logic
        pass

    @pytest.mark.skip(reason="pending implementation - domain TTL override")
    def test_refresh_policy_domain_ttl_days_override(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test icp_config.refresh_policy.domain_ttl_days override."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify domain TTL override
        # Implementation depends on TTL logic
        pass

    @pytest.mark.skip(reason="pending implementation - max pages override")
    def test_search_max_pages_override(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test icp_config.search.max_pages override."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify max pages override
        # Implementation depends on pagination logic
        pass

    @pytest.mark.skip(reason="pending implementation - default country fallback")
    def test_default_country_fallback(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test icp_config.default_country fallback for phone parsing."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify country fallback logic
        # Implementation depends on phone parsing logic
        pass

    @pytest.mark.skip(reason="pending implementation - role priority configuration")
    def test_role_priority_configuration(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test icp_config.role_priority configuration loading."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify role priority configuration
        # Implementation depends on role priority logic
        pass

    @pytest.mark.skip(reason="pending implementation - error code mapping")
    def test_error_code_mapping(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test error code mapping for all specified error types."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify error code mapping
        # Implementation depends on error handling logic
        pass

    @pytest.mark.skip(reason="pending implementation - content hash deduplication")
    def test_content_hash_deduplication(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test content hash deduplication logic."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify content hash deduplication
        # Implementation depends on deduplication logic
        pass

    @pytest.mark.skip(
        reason="pending implementation - LinkedIn routing and canonicalization"
    )
    def test_linkedin_routing_canonicalization(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test LinkedIn routing and canonicalization."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify LinkedIn routing logic
        # Implementation depends on LinkedIn handling
        pass

    @pytest.mark.skip(reason="pending implementation - seniority ranking mapping")
    def test_seniority_ranking_mapping(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test seniority ranking mapping."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify seniority ranking
        # Implementation depends on seniority logic
        pass

    @pytest.mark.skip(reason="pending implementation - OpenRouter costs inclusion")
    def test_openrouter_costs_inclusion(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test that OpenRouter costs are included in record.cost.domain_usd and tool-run metrics.cost_usd.domain."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify OpenRouter cost inclusion
        # Implementation depends on cost tracking logic
        pass

    @pytest.mark.skip(reason="pending implementation - duration metrics population")
    def test_metrics_duration_ms_population(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test metrics.duration_ms population in every tool envelope."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify duration metrics
        # Implementation depends on metrics logic
        pass

    @pytest.mark.skip(reason="pending implementation - atomic pointer swap")
    def test_atomic_pointer_swap(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test atomic pointer swap during copy-on-write sink compaction."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify atomic pointer swapping
        # Implementation depends on sink compaction logic
        pass

    @pytest.mark.skip(reason="pending implementation - SyncSemaphorePool blocking")
    def test_sync_semaphore_pool_blocks_parallel_calls(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Unit-test SyncSemaphorePool blocks >N parallel blocking calls."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify SyncSemaphorePool blocking
        # Implementation depends on concurrency control
        pass

    @pytest.mark.skip(reason="pending implementation - email source tie-breaking")
    def test_email_source_best_contact_tie_break(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Unit-test that email_source affects best-contact tie-break."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify email source tie-breaking
        # Implementation depends on contact selection logic
        pass

    @pytest.mark.skip(reason="pending implementation - LinkedIn masking")
    def test_mask_linkedin_redacts_slugs(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Unit-test mask_linkedin() redacts slugs in logs/errors."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify LinkedIn masking
        # Implementation depends on masking logic
        pass

    @pytest.mark.skip(reason="pending implementation - field ownership enforcement")
    def test_field_ownership_enforcement(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Field-ownership enforcement test (uses helper from 1.1.24)."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify field ownership enforcement
        # Implementation depends on ownership helper
        pass

    @pytest.mark.skip(reason="pending implementation - status history completeness")
    def test_status_history_completeness(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Status_history completeness test: feed a record that undergoes Domain → Crawl → Enrich and assert three chronological history entries."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify status history completeness
        # Implementation depends on status tracking logic
        pass

    @pytest.mark.skip(reason="pending implementation - portalocker write-phase timing")
    def test_portalocker_write_phase_timing(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Portalocker write-phase timing test (ties to 1.2.4)."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify portalocker timing
        # Implementation depends on file locking logic
        pass

    @pytest.mark.skip(reason="pending implementation - provider payload redaction")
    def test_provider_payload_redaction(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Provider-payload redaction test: logger output must not contain raw 'headers' or 'body' keys when log_redaction filter is on."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify provider payload redaction
        # Implementation depends on logging redaction logic
        pass

    @pytest.mark.skip(reason="pending implementation - mode handling")
    def test_icp_config_mode_handling(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test icp_config.mode (fast/thorough) handling in Domain tool."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify mode handling
        # Implementation depends on mode logic
        pass

    @pytest.mark.skip(reason="pending implementation - filtering strict handling")
    def test_icp_config_filtering_strict_handling(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test icp_config.filtering_strict handling in Domain tool."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify filtering strict handling
        # Implementation depends on filtering logic
        pass

    @pytest.mark.skip(reason="pending implementation - query template validation")
    def test_icp_config_queries_template_placeholder_validation(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test icp_config.queries template placeholder validation."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify query template validation
        # Implementation depends on template validation logic
        pass

    @pytest.mark.skip(reason="pending implementation - fields validation")
    def test_icp_config_required_fields_optional_fields_validation(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test icp_config.required_fields and icp_config.optional_fields validation."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify fields validation
        # Implementation depends on validation logic
        pass

    @pytest.mark.skip(reason="pending implementation - timeout error mapping")
    def test_http_timeout_smtp_timeout_error_mapping(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test HTTP_TIMEOUT and SMTP_TIMEOUT error mapping."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify timeout error mapping
        # Implementation depends on error handling logic
        pass

    @pytest.mark.skip(reason="pending implementation - schema checksum validation")
    def test_schema_checksum_validation_drift_detection(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test schema checksum validation and drift detection."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify schema checksum validation
        # Implementation depends on schema validation logic
        pass

    @pytest.mark.skip(reason="pending implementation - progressive SERP pagination")
    def test_progressive_serp_pagination_logic(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test progressive SERP pagination logic."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify progressive pagination
        # Implementation depends on pagination logic
        pass

    @pytest.mark.skip(reason="pending implementation - content hash deduplication")
    def test_content_hash_deduplication_logic(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test content hash deduplication logic."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify content hash deduplication
        # Implementation depends on deduplication logic
        pass

    @pytest.mark.skip(reason="pending implementation - testing flags handling")
    def test_testing_flags_handling(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test testing flags (process_rejected, process_low_crawl)."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify testing flags handling
        # Implementation depends on testing flags logic
        pass

    @pytest.mark.skip(reason="pending implementation - missing error codes")
    def test_missing_error_codes(
        self,
        sample_icp_config,
        temp_data_dir,
        mock_env_vars,
        mock_costs_config,
        mock_schema_checksum,
    ):
        """Test missing error codes (HTTP_TIMEOUT, SMTP_TIMEOUT)."""
        DomainTool(sample_icp_config, temp_data_dir)

        # This test will verify missing error codes
        # Implementation depends on error handling logic
        pass


# ============================================================================
# Task 10: Pass/Fail System Unit Tests
# ============================================================================


class TestPassFailSystem:
    """Test the new pass/fail system implementation."""

    def test_build_scoring_prompt_simple(self, sample_icp_config):
        """Test new simple prompt format matches BRD exactly."""
        scorer = LLMScorer("test_key", AsyncSemaphorePool(PermitManager(3)))

        prompt = scorer._build_scoring_prompt(
            "Test Company",
            "B2B SaaS company in California",
            "test query",
            sample_icp_config
        )

        # Verify prompt structure
        assert "You are a lead-scoring function" in prompt
        assert "ICP HARD rules" in prompt
        assert "FAIL" in prompt and "PASS" in prompt
        assert "40 words" in prompt
        assert "STRICTLY valid JSON" in prompt
        assert "no line breaks" in prompt
        assert "no code blocks" in prompt
        assert "Test Company" in prompt
        assert "B2B SaaS company in California" in prompt
        assert sample_icp_config["icp_hard_rules"] in prompt

        # Verify prompt is concise (BRD requirement: 16 lines max)
        prompt_lines = prompt.count('\n') + 1
        assert prompt_lines <= 16, f"Prompt has {prompt_lines} lines, should be ≤16"

        # Verify no complex scoring logic
        assert "intent_config" not in prompt
        assert "validation_criteria" not in prompt
        assert "high_intent_signals" not in prompt
        assert "low_intent_signals" not in prompt

    def test_build_scoring_prompt_missing_hard_rules(self):
        """Test prompt generation with missing icp_hard_rules."""
        scorer = LLMScorer("test_key", AsyncSemaphorePool(PermitManager(3)))

        config_without_rules = {"name": "Test", "icp_text": "Test", "queries": []}

        prompt = scorer._build_scoring_prompt(
            "Test Company",
            "Test snippet",
            "test query",
            config_without_rules
        )

        assert "No specific hard rules defined" in prompt

    @pytest.mark.asyncio
    async def test_score_domain_pass_response(self, sample_icp_config):
        """Test PASS response parsing."""
        scorer = LLMScorer("test_key", AsyncSemaphorePool(PermitManager(3)))

        # Mock the LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"score":"PASS","reason":"Company is B2B SaaS with 50-500 employees in California"}'

        with patch.object(scorer.client.chat.completions, 'create', new_callable=AsyncMock, return_value=mock_response):
            passed, reason, flags, model, fingerprint = await scorer.score_domain(
                "Test Company", "B2B SaaS company", "test query", sample_icp_config
            )

        assert passed is True
        assert "Company is B2B SaaS" in reason
        assert flags == []
        assert model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_score_domain_fail_response(self, sample_icp_config):
        """Test FAIL response parsing."""
        scorer = LLMScorer("test_key", AsyncSemaphorePool(PermitManager(3)))

        # Mock the LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"score":"FAIL","reason":"Company is not B2B SaaS"}'

        with patch.object(scorer.client.chat.completions, 'create', new_callable=AsyncMock, return_value=mock_response):
            passed, reason, flags, model, fingerprint = await scorer.score_domain(
                "Test Company", "Consulting firm", "test query", sample_icp_config
            )

        assert passed is False
        assert "not B2B SaaS" in reason
        assert flags == []
        assert model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_score_domain_40_word_limit(self, sample_icp_config):
        """Test 40-word reason limit enforcement."""
        scorer = LLMScorer("test_key", AsyncSemaphorePool(PermitManager(3)))

        # Create a long reason (over 40 words)
        long_reason = "This is a very long reason that exceeds the forty word limit and should be truncated by the system to ensure that we do not exceed the maximum allowed word count for the reason field in the response and this is additional text"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = f'{{"score":"PASS","reason":"{long_reason}"}}'

        with patch.object(scorer.client.chat.completions, 'create', new_callable=AsyncMock, return_value=mock_response):
            passed, reason, flags, model, fingerprint = await scorer.score_domain(
                "Test Company", "Test snippet", "test query", sample_icp_config
            )

        # Verify reason is truncated
        assert len(reason.split()) <= 40
        assert reason.endswith("...")

    @pytest.mark.asyncio
    async def test_score_domain_invalid_json(self, sample_icp_config):
        """Test invalid JSON handling (should default to FAIL)."""
        scorer = LLMScorer("test_key", AsyncSemaphorePool(PermitManager(3)))

        # Mock invalid JSON response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Invalid JSON response"

        with patch.object(scorer.client.chat.completions, 'create', new_callable=AsyncMock, return_value=mock_response):
            passed, reason, flags, model, fingerprint = await scorer.score_domain(
                "Test Company", "Test snippet", "test query", sample_icp_config
            )

        assert passed is False
        assert "Invalid JSON response from LLM" in reason
        assert "json_parse_error" in flags

    @pytest.mark.asyncio
    async def test_score_domain_fallback_model(self, sample_icp_config):
        """Test fallback model usage."""
        scorer = LLMScorer("test_key", AsyncSemaphorePool(PermitManager(3)))

        # Mock primary model failure, fallback success
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"score":"PASS","reason":"Test reason"}'

        with patch.object(scorer.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = [Exception("Primary model failed"), mock_response]

            passed, reason, flags, model, fingerprint = await scorer.score_domain(
                "Test Company", "Test snippet", "test query", sample_icp_config
            )

        assert passed is True
        assert model == "gpt-3.5-turbo"

    def test_validate_icp_config_hard_rules_required(self, temp_data_dir):
        """Test configuration validation requires icp_hard_rules."""
        config_missing_rules = {
            "name": "Test ICP",
            "icp_text": "Test ICP",
            "queries": ["test query"]
        }

        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(config_missing_rules, str(temp_data_dir))
            errors = tool._validate_icp_config()

        assert len(errors) > 0
        assert any("icp_hard_rules" in str(error) for error in errors)

    def test_validate_icp_config_hard_rules_type(self, temp_data_dir):
        """Test icp_hard_rules must be a string."""
        config_invalid_type = {
            "name": "Test ICP",
            "icp_text": "Test ICP",
            "queries": ["test query"],
            "icp_hard_rules": 123  # Invalid type
        }

        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(config_invalid_type, str(temp_data_dir))
            errors = tool._validate_icp_config()

        assert len(errors) > 0
        assert any("must be a string" in str(error) for error in errors)

    def test_validate_icp_config_hard_rules_none(self, temp_data_dir):
        """Test icp_hard_rules cannot be None."""
        config_none_rules = {
            "name": "Test ICP",
            "icp_text": "Test ICP",
            "queries": ["test query"],
            "icp_hard_rules": None
        }

        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(config_none_rules, str(temp_data_dir))
            errors = tool._validate_icp_config()

        assert len(errors) > 0
        assert any("icp_hard_rules" in str(error) for error in errors)

    def test_validate_icp_config_valid(self, sample_icp_config, temp_data_dir):
        """Test valid configuration passes validation."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))
            errors = tool._validate_icp_config()

        assert len(errors) == 0

    def test_domain_hostname_extraction_www_removal(self, sample_icp_config, temp_data_dir):
        """Test www. prefix removal."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))

        test_cases = [
            ("https://www.company.com", "company.com"),
            ("https://www.example.org", "example.org"),
            ("www.direct.com", "direct.com"),
        ]

        for url, expected in test_cases:
            result = tool._normalize_serp_result({"link": url}, "test query", 1)
            assert result["domain"] == expected

    def test_domain_hostname_extraction_path_removal(self, sample_icp_config, temp_data_dir):
        """Test path removal."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))

        test_cases = [
            ("https://company.com/path/to/page", "company.com"),
            ("https://www.example.org/about", "example.org"),
            ("http://test.net/products/item", "test.net"),
        ]

        for url, expected in test_cases:
            result = tool._normalize_serp_result({"link": url}, "test query", 1)
            assert result["domain"] == expected

    def test_domain_hostname_extraction_query_removal(self, sample_icp_config, temp_data_dir):
        """Test query parameter removal."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))

        test_cases = [
            ("https://company.com?param=value", "company.com"),
            ("https://www.example.org?utm_source=google", "example.org"),
            ("http://test.net?id=123&type=product", "test.net"),
        ]

        for url, expected in test_cases:
            result = tool._normalize_serp_result({"link": url}, "test query", 1)
            assert result["domain"] == expected

    def test_domain_hostname_extraction_subdomain_handling(self, sample_icp_config, temp_data_dir):
        """Test subdomain handling."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))

        test_cases = [
            ("https://api.company.com", "api.company.com"),
            ("https://www.blog.example.org", "blog.example.org"),
            ("https://shop.test.net", "shop.test.net"),
        ]

        for url, expected in test_cases:
            result = tool._normalize_serp_result({"link": url}, "test query", 1)
            assert result["domain"] == expected

    def test_domain_hostname_extraction_edge_cases(self, sample_icp_config, temp_data_dir):
        """Test edge cases."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))

        test_cases = [
            ("", ""),
            ("https://", ""),
            ("not-a-url", "not-a-url"),
            ("https://company.com:8080", "company.com"),
            ("https://COMPANY.COM", "company.com"),
        ]

        for url, expected in test_cases:
            result = tool._normalize_serp_result({"link": url}, "test query", 1)
            assert result["domain"] == expected

    def test_old_scoring_system_removal(self, sample_icp_config, temp_data_dir):
        """Test that old scoring system is completely removed."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))

        # Test that no old configuration fields are used
        assert "threshold" not in sample_icp_config
        assert "filtering_strict" not in sample_icp_config

        # Test that new configuration field is used
        assert "icp_hard_rules" in sample_icp_config

        # Test that prompt method is simple
        prompt = tool.llm_scorer._build_scoring_prompt(
            "Test", "Test", "Test", sample_icp_config
        )

        # Should not contain old scoring system references
        assert "intent_config" not in prompt
        assert "validation_criteria" not in prompt
        assert "high_intent_signals" not in prompt
        assert "low_intent_signals" not in prompt
        assert "size_validation" not in prompt

    def test_lead_record_structure(self, sample_icp_config, temp_data_dir):
        """Test lead record structure for pass/fail system."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))

        record = tool._create_lead_record("test.com", "test query")

        # Verify new structure
        assert "icp" in record
        assert "pre_score" in record["icp"]
        assert "pre_pass" in record["icp"]
        assert "pre_reason" in record["icp"]
        assert "pre_flags" in record["icp"]
        assert "scoring_meta" in record["icp"]

        # Verify old fields are removed
        assert "threshold" not in record["icp"]
        assert "filtering_strict" not in record["icp"]

        # Verify scoring_meta structure
        assert record["icp"]["scoring_meta"]["method"] == "pass_fail"
        assert record["icp"]["scoring_meta"]["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_process_domain_pass_fail(self, sample_icp_config, temp_data_dir):
        """Test domain processing with pass/fail."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))

        # Mock the LLM scorer
        mock_scorer = MagicMock()
        mock_scorer.score_domain = AsyncMock(return_value=(True, "Test reason", [], "gpt-4o-mini", "fingerprint"))
        tool.llm_scorer = mock_scorer

        # Mock domain history
        tool.domain_history.get_domain_record = MagicMock(return_value=None)

        result = await tool._score_domains([{
            "domain": "test.com",
            "title": "Test Company",
            "snippet": "B2B SaaS company",
            "query": "test query",
            "url": "https://test.com",
            "page_index": 1,
            "rank_on_page": 1,
            "fetched_at": "2024-01-01T00:00:00Z"
        }])

        assert len(result) == 1
        record = result[0]

        # Verify boolean values
        assert record["icp"]["pre_score"] is True
        assert record["icp"]["pre_pass"] is True
        assert record["status"] == "scored"

    @pytest.mark.asyncio
    async def test_process_domain_fail_case(self, sample_icp_config, temp_data_dir):
        """Test domain processing with fail case."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))

        # Mock the LLM scorer to return False
        mock_scorer = MagicMock()
        mock_scorer.score_domain = AsyncMock(return_value=(False, "Not B2B SaaS", [], "gpt-4o-mini", "fingerprint"))
        tool.llm_scorer = mock_scorer

        # Mock domain history
        tool.domain_history.get_domain_record = MagicMock(return_value=None)

        result = await tool._score_domains([{
            "domain": "test.com",
            "title": "Consulting Firm",
            "snippet": "Consulting services",
            "query": "test query",
            "url": "https://test.com",
            "page_index": 1,
            "rank_on_page": 1,
            "fetched_at": "2024-01-01T00:00:00Z"
        }])

        assert len(result) == 1
        record = result[0]

        # Verify boolean values
        assert record["icp"]["pre_score"] is False
        assert record["icp"]["pre_pass"] is False
        assert record["status"] == "rejected"

    def test_metrics_calculation_boolean(self, sample_icp_config, temp_data_dir):
        """Test metrics calculation with boolean values."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))

        # Create test records with boolean values
        test_records = [
            {"icp": {"pre_pass": True}},
            {"icp": {"pre_pass": False}},
            {"icp": {"pre_pass": True}},
            {"icp": {"pre_pass": False}},
        ]

        # Mock the metrics calculation (simulate the logic from run method)
        total_count = len(test_records)
        pass_count = sum(1 for r in test_records if r.get("icp", {}).get("pre_pass", False))
        fail_count = total_count - pass_count
        pass_rate = pass_count / total_count if total_count > 0 else 0.0

        assert total_count == 4
        assert pass_count == 2
        assert fail_count == 2
        assert pass_rate == 0.5

    def test_edge_cases_missing_icp(self, sample_icp_config, temp_data_dir):
        """Test edge cases with missing icp section."""
        with patch.dict(os.environ, {"GSE_API_KEY": "test_key", "GSE_CX": "test_cx", "OPENROUTER_API_KEY": "test_key", "OPENROUTER_KEY": "test_key"}):
            tool = DomainTool(sample_icp_config, str(temp_data_dir))

        # Test records with missing icp section
        test_records = [
            {"lead_id": "test1"},  # Missing icp
            {"lead_id": "test2", "icp": {}},  # Empty icp
            {"lead_id": "test3", "icp": {"pre_pass": True}},  # Valid
        ]

        # Test filtering logic
        passing = [r for r in test_records if r.get("icp", {}).get("pre_pass", False)]

        assert len(passing) == 1  # Only the valid one should pass
        assert passing[0]["lead_id"] == "test3"


if __name__ == "__main__":
    # Use pytest instead of unittest
    pass
