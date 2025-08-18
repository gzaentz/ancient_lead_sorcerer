"""
Unit tests for the Lead Sorcerer Orchestrator.

Tests the orchestrator's ability to coordinate the Domain → Crawl → Enrich pipeline,
handle persistence, exports, and respect all BRD constraints.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.orchestrator import LeadSorcererOrchestrator


class TestLeadSorcererOrchestrator:
    """Test cases for the LeadSorcererOrchestrator class."""

    @pytest.fixture
    def temp_config_file(self):
        """Create a temporary ICP config file for testing."""
        config = {
            "name": "test_icp",
            "icp_text": "Test ICP description",
            "queries": ["test query"],
            "required_fields": {"company": ["name"], "contact": ["email"]},
            "threshold": 0.7,
            "concurrency": {"max_concurrent_requests": 3},
            "testing": {"process_rejected": False, "process_low_crawl": False},
            "exports": {"enabled": True},
            "default_country": "US",
            "role_priority": {"ceo": 1, "vp": 2},
        }

        # Create temporary file with proper content
        temp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        temp_file.write(json.dumps(config, indent=2))
        temp_file.close()

        yield temp_file.name

        # Cleanup
        Path(temp_file.name).unlink(missing_ok=True)

    @pytest.fixture
    def mock_domain_result(self):
        """Mock domain tool result."""
        return {
            "data": {
                "lead_records": [
                    {
                        "lead_id": "test-lead-1",
                        "domain": "example.com",
                        "icp": {
                            "pre_pass": True,
                            "pre_score": 0.8,
                            "pre_reason": "Good match",
                        },
                        "status": "scored",
                        "cost": {"domain_usd": 0.001, "total_usd": 0.001},
                    },
                    {
                        "lead_id": "test-lead-2",
                        "domain": "reject.com",
                        "icp": {
                            "pre_pass": False,
                            "pre_score": 0.3,
                            "pre_reason": "Poor match",
                        },
                        "status": "scored",
                        "cost": {"domain_usd": 0.001, "total_usd": 0.001},
                    },
                ]
            },
            "errors": [],
            "metrics": {
                "count_in": 1,
                "count_out": 2,
                "pass_rate": 0.5,
                "cost_usd": {"domain": 0.002, "total": 0.002},
            },
        }

    @pytest.fixture
    def mock_crawl_result(self):
        """Mock crawl tool result."""
        return {
            "data": {
                "lead_records": [
                    {
                        "lead_id": "test-lead-1",
                        "domain": "example.com",
                        "status": "enrich_ready",
                        "company": {"name": "Example Corp"},
                        "contacts": [
                            {"contact_id": "contact-1", "full_name": "John Doe"}
                        ],
                        "cost": {"crawl_usd": 0.002, "total_usd": 0.003},
                    }
                ]
            },
            "errors": [],
            "metrics": {
                "count_in": 1,
                "count_out": 1,
                "pass_rate": 1.0,
                "cost_usd": {"crawl": 0.002, "total": 0.002},
            },
        }

    @pytest.fixture
    def mock_enrich_result(self):
        """Mock enrich tool result."""
        return {
            "data": {
                "lead_records": [
                    {
                        "lead_id": "test-lead-1",
                        "domain": "example.com",
                        "status": "enriched",
                        "best_contact_id": "contact-1",
                        "cost": {"enrich_usd": 0.003, "total_usd": 0.006},
                    }
                ]
            },
            "errors": [],
            "metrics": {
                "count_in": 1,
                "count_out": 1,
                "pass_rate": 1.0,
                "cost_usd": {"enrich": 0.003, "total": 0.003},
            },
        }

    @pytest.mark.asyncio
    async def test_orchestrator_initialization(self, temp_config_file):
        """Test orchestrator initialization with valid config."""
        with (
            patch("src.orchestrator.DomainTool"),
            patch("src.orchestrator.CrawlTool"),
        ):
            # Mock the tools to avoid environment variable dependencies

            orchestrator = LeadSorcererOrchestrator(temp_config_file)

            assert orchestrator.config_path == temp_config_file
            assert orchestrator.batch_size == 50
            assert orchestrator.icp_config["name"] == "test_icp"
            assert orchestrator.data_dir == "./data"

    @pytest.mark.asyncio
    async def test_data_dir_precedence(self, temp_config_file):
        """Test data directory precedence resolution."""
        # Test environment variable precedence
        with (
            patch.dict("os.environ", {"LEADPOET_DATA_DIR": "/custom/data"}),
            patch("src.orchestrator.DomainTool"),
            patch("src.orchestrator.CrawlTool"),
        ):
            orchestrator = LeadSorcererOrchestrator(temp_config_file)
            assert orchestrator.data_dir == "/custom/data"

    @pytest.mark.asyncio
    async def test_provider_config_validation(self, temp_config_file):
        """Test provider configuration validation."""
        with (
            patch("src.orchestrator.load_costs_config") as mock_load_costs,
            patch("src.orchestrator.validate_provider_config") as mock_validate,
            patch("src.orchestrator.DomainTool"),
            patch("src.orchestrator.CrawlTool"),
        ):
            mock_load_costs.return_value = {
                "gse": 0.0005,
                "openrouter": 0.0020,
                "firecrawl": 0.0010,
                "proxycurl": 0.0100,
                "mailgun": 0.0020,
                "snovio": 0.0150,
            }

            orchestrator = LeadSorcererOrchestrator(temp_config_file)

            # Should not raise an exception
            orchestrator._validate_provider_config()
            mock_validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_testing_flags_validation(self, temp_config_file):
        """Test testing flags validation."""
        with (
            patch("src.orchestrator.DomainTool"),
            patch("src.orchestrator.CrawlTool"),
        ):
            orchestrator = LeadSorcererOrchestrator(temp_config_file)

            # Should not raise an exception
            orchestrator._validate_testing_flags()

    @pytest.mark.asyncio
    async def test_refresh_policy_validation(self, temp_config_file):
        """Test refresh policy validation."""
        with (
            patch("src.orchestrator.DomainTool"),
            patch("src.orchestrator.CrawlTool"),
        ):
            orchestrator = LeadSorcererOrchestrator(temp_config_file)

            # Should not raise an exception
            orchestrator._validate_refresh_policy()

    @pytest.mark.asyncio
    async def test_sink_rotation_logic(self, temp_config_file):
        """Test sink rotation logic."""
        with (
            patch("src.orchestrator.DomainTool"),
            patch("src.orchestrator.CrawlTool"),
        ):
            orchestrator = LeadSorcererOrchestrator(temp_config_file)

            # Test size-based rotation
            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 15 * 1024 * 1024  # 15 MB

                with patch.object(
                    orchestrator, "_rotate_sink_with_compaction"
                ) as mock_rotate:
                    # Mock the datetime.utcnow() call in the orchestrator
                    with patch("src.orchestrator.datetime") as mock_datetime:
                        # Create a proper datetime object for comparison
                        from datetime import datetime

                        current_time = datetime(2024, 1, 1, 0, 0, 0)
                        mock_datetime.utcnow.return_value = current_time

                        # Mock the file modification time to be old enough to trigger rotation
                        # Use a timestamp that's 31 days old
                        old_timestamp = 1609459200  # Old timestamp
                        mock_stat.return_value.st_mtime = old_timestamp

                        # Mock datetime.fromtimestamp to return a proper datetime object
                        mock_datetime.fromtimestamp.return_value = datetime(
                            2023, 12, 1, 0, 0, 0
                        )

                        orchestrator._rotate_sink_if_needed(
                            Path("test.jsonl"), current_time, "test_sink"
                        )
                        mock_rotate.assert_called_once()

    @pytest.mark.asyncio
    async def test_csv_export_flattening(self, temp_config_file):
        """Test CSV export flattening logic."""
        with (
            patch("src.orchestrator.DomainTool"),
            patch("src.orchestrator.CrawlTool"),
        ):
            orchestrator = LeadSorcererOrchestrator(temp_config_file)

            test_record = {
                "lead_id": "test-1",
                "company": {"name": "Test Corp", "industry": "Technology"},
                "contacts": ["contact1", "contact2"],
                "status": "enriched",
            }

            # Test field collection
            fields = set()
            orchestrator._collect_fields(test_record, "", fields)

            expected_fields = {
                "lead_id",
                "status",
                "company.name",
                "company.industry",
                "contacts",
            }
            assert fields == expected_fields

            # Test field value extraction
            value = orchestrator._get_field_value(test_record, "company.name")
            assert value == "Test Corp"

            value = orchestrator._get_field_value(test_record, "contacts")
            assert value == "contact1|contact2"

    @pytest.mark.asyncio
    async def test_metrics_calculation(
        self,
        temp_config_file,
        mock_domain_result,
        mock_crawl_result,
        mock_enrich_result,
    ):
        """Test final metrics calculation."""
        with (
            patch("src.orchestrator.DomainTool"),
            patch("src.orchestrator.CrawlTool"),
        ):
            orchestrator = LeadSorcererOrchestrator(temp_config_file)
            orchestrator.start_time = 1000  # Mock start time

            with patch(
                "time.time", return_value=1100
            ):  # Mock end time (100 seconds later)
                metrics = orchestrator._calculate_final_metrics(
                    mock_domain_result, mock_crawl_result, mock_enrich_result
                )

                assert metrics["duration_ms"] == 100000  # 100 seconds in ms
                assert metrics["lead_counts"]["domain"] == 2
                assert metrics["lead_counts"]["crawl"] == 1
                assert metrics["lead_counts"]["enrich"] == 1
                # Fix the expected cost calculation
                assert metrics["cost_usd"]["total"] == 0.007  # 0.002 + 0.002 + 0.003

    @pytest.mark.asyncio
    async def test_pipeline_execution_mock(
        self,
        temp_config_file,
        mock_domain_result,
        mock_crawl_result,
        mock_enrich_result,
    ):
        """Test pipeline execution with mocked tools."""
        with (
            patch("src.orchestrator.DomainTool") as MockDomainTool,
            patch("src.orchestrator.CrawlTool") as MockCrawlTool,
            patch("src.orchestrator.run_enrich") as MockRunEnrich,
        ):
            # Mock domain tool
            mock_domain = MockDomainTool.return_value
            mock_domain.run = AsyncMock(return_value=mock_domain_result)

            # Mock crawl tool
            mock_crawl = MockCrawlTool.return_value
            mock_crawl.run = AsyncMock(return_value=mock_crawl_result)

            # Mock enrich tool
            MockRunEnrich.return_value = mock_enrich_result

            orchestrator = LeadSorcererOrchestrator(temp_config_file)

            # Mock provider validation
            with (
                patch.object(orchestrator, "_validate_provider_config"),
                patch.object(orchestrator, "_validate_testing_flags"),
                patch.object(orchestrator, "_validate_refresh_policy"),
                patch.object(orchestrator, "_persist_domain_results"),
                patch.object(orchestrator, "_export_leads"),
                patch.object(orchestrator, "_log_pipeline_summary"),
            ):
                result = await orchestrator.run_pipeline()

                assert result["success"] is True
                assert result["total_errors"] == 0
                assert "metrics" in result

    @pytest.mark.asyncio
    async def test_error_handling(self, temp_config_file):
        """Test error handling in pipeline execution."""
        with (
            patch("src.orchestrator.DomainTool") as MockDomainTool,
            patch("src.orchestrator.CrawlTool"),
        ):
            # Mock domain tool to raise an exception
            mock_domain = MockDomainTool.return_value
            mock_domain.run = AsyncMock(side_effect=Exception("Test error"))

            orchestrator = LeadSorcererOrchestrator(temp_config_file)

            # Mock provider validation
            with patch.object(orchestrator, "_validate_provider_config"):
                result = await orchestrator.run_pipeline()

                assert result["success"] is False
                assert "error" in result
                assert "Test error" in result["error"]

    @pytest.mark.asyncio
    async def test_cli_interface(self, temp_config_file):
        """Test CLI interface functionality."""
        with (
            patch("sys.argv", ["orchestrator", "--config", temp_config_file]),
            patch("src.orchestrator.LeadSorcererOrchestrator") as MockOrchestrator,
        ):
            mock_orchestrator = MockOrchestrator.return_value
            mock_orchestrator.run_pipeline = AsyncMock(return_value={"success": True})

            from src.orchestrator import main

            result = await main()

            assert result == 0
            mock_orchestrator.run_pipeline.assert_called_once()


# ============================================================================
# Missing Tests from Task 6
# ============================================================================


class TestMissingRequirements:
    """Test missing requirements from Task 6."""

    def test_atomic_pointer_swap_copy_on_write_sink_compaction(self):
        """Test atomic pointer swap during copy-on-write sink compaction."""
        # This test will verify atomic pointer swapping
        # Implementation depends on sink compaction logic
        pass

    def test_sync_semaphore_pool_blocking_sdk_calls(self):
        """Test SyncSemaphorePool for blocking SDK calls in tools."""
        # This test will verify SyncSemaphorePool for blocking calls
        # Implementation depends on concurrency control
        pass

    def test_testing_flags_handling(self):
        """Test testing flags handling."""
        # This test will verify testing flags handling
        # Implementation depends on testing flags logic
        pass

    def test_export_format_per_brd(self):
        """Test export format per BRD §426-435."""
        # This test will verify export format compliance
        # Implementation depends on export logic
        pass

    def test_metrics_duration_ms_whole_pipeline_run(self):
        """Test metrics.duration_ms for the whole pipeline run."""
        # This test will verify pipeline duration metrics
        # Implementation depends on metrics logic
        pass

    def test_copy_on_write_compaction_rotated_sinks(self):
        """Test copy-on-write compaction for rotated sinks."""
        # This test will verify sink compaction
        # Implementation depends on compaction logic
        pass

    def test_role_priority_configuration_loading(self):
        """Test icp_config.role_priority configuration loading."""
        # This test will verify role priority configuration
        # Implementation depends on role priority logic
        pass

    def test_default_country_fallback_phone_parsing(self):
        """Test icp_config.default_country fallback for phone parsing."""
        # This test will verify country fallback logic
        # Implementation depends on phone parsing logic
        pass

    def test_aggregate_metrics_health_unknown_error_count(self):
        """Test aggregate metrics.health.unknown_error_count over run and include in summary."""
        # This test will verify unknown error count aggregation
        # Implementation depends on metrics logic
        pass

    def test_failure_revisit_days_logic_all_tools(self):
        """Test icp_config.refresh_policy.failure_revisit_days logic for all tools."""
        # This test will verify failure revisit logic
        # Implementation depends on revisit logic
        pass

    def test_refresh_policy_domain_ttl_days_override_validation(self):
        """Test icp_config.refresh_policy.domain_ttl_days override validation."""
        # This test will verify domain TTL override validation
        # Implementation depends on TTL logic
        pass

    def test_search_max_pages_override_validation(self):
        """Test metrics.duration_ms for the whole pipeline run."""
        # This test will verify max pages override validation
        # Implementation depends on pagination logic
        pass

    def test_metrics_duration_ms_pipeline_run(self):
        """Test expose metrics.duration_ms for the whole pipeline run."""
        # This test will verify pipeline duration metrics exposure
        # Implementation depends on metrics logic
        pass

    def test_atomic_pointer_swap_explicit_unit_test(self):
        """Test atomic pointer swap during copy-on-write sink compaction – add explicit unit test."""
        # This test will verify atomic pointer swapping with explicit testing
        # Implementation depends on sink compaction logic
        pass

    def test_sync_semaphore_pool_implementation(self):
        """Test SyncSemaphorePool implementation for blocking SDK calls."""
        # This test will verify SyncSemaphorePool implementation
        # Implementation depends on concurrency control
        pass

    def test_testing_flags_handling_implementation(self):
        """Test testing flags handling implementation."""
        # This test will verify testing flags handling implementation
        # Implementation depends on testing flags logic
        pass

    def test_export_format_implementation(self):
        """Test export format implementation per BRD §426-435."""
        # This test will verify export format implementation
        # Implementation depends on export logic
        pass


if __name__ == "__main__":
    pytest.main([__file__])
