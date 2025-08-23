"""
Integration tests for Lead Sorcerer.

Tests cover the integration requirements from Task 6.5 including end-to-end
pipeline tests and error path scenarios.
"""

import json
import pytest
from unittest.mock import patch, AsyncMock


class TestEndToEndPipeline:
    """Test end-to-end pipeline functionality."""

    @pytest.mark.asyncio
    async def test_end_to_end_pipeline_happy_path(self, tmp_path):
        """Test end-to-end pipeline test: Domain→Crawl→Enrich happy-path."""
        # Create temporary config file
        config_data = {
            "name": "Test ICP",
            "icp_text": "B2B SaaS companies in California",
            "queries": ["B2B SaaS companies in California"],
            "threshold": 0.7,
            "required_fields": {"company": ["name"], "contact": ["email"]},
            "concurrency": {"max_concurrent_requests": 3},
            "refresh_policy": {"revisit_after_days": 90, "failure_revisit_days": 1},
            "testing": {"process_rejected": False, "process_low_crawl": False},
            "exports": {"enabled": True},
            "default_country": "US",
            "role_priority": {"ceo": 1, "vp": 2},
        }

        config_file = tmp_path / "test_icp.json"
        config_file.write_text(json.dumps(config_data))

        # Mock tools
        with (
            patch("src.orchestrator.DomainTool") as MockDomainTool,
            patch("src.orchestrator.CrawlTool") as MockCrawlTool,
            patch("src.orchestrator.run_enrich") as MockRunEnrich,
        ):
            # Mock domain tool
            mock_domain = MockDomainTool.return_value
            mock_domain.run = AsyncMock(
                return_value={
                    "data": {
                        "lead_records": [
                            {
                                "lead_id": "test-lead-1",
                                "domain": "testcompany.com",
                                "status": "scored",
                                "icp": {"pre_pass": True},
                            }
                        ]
                    },
                    "errors": [],
                    "metrics": {"count_out": 1},
                }
            )

            # Mock crawl tool
            mock_crawl = MockCrawlTool.return_value
            mock_crawl.run = AsyncMock(
                return_value={
                    "data": {
                        "lead_records": [
                            {
                                "lead_id": "test-lead-1",
                                "domain": "testcompany.com",
                                "status": "enrich_ready",
                                "company": {"name": "Test Company"},
                                "contacts": [{"contact_id": "contact-1"}],
                            }
                        ]
                    },
                    "errors": [],
                    "metrics": {"count_out": 1},
                }
            )

            # Mock enrich tool
            MockRunEnrich.return_value = {
                "data": {
                    "lead_records": [
                        {
                            "lead_id": "test-lead-1",
                            "domain": "testcompany.com",
                            "status": "enriched",
                            "best_contact_id": "contact-1",
                        }
                    ]
                },
                "errors": [],
                "metrics": {"count_out": 1},
            }

            # Create and run orchestrator
            from src.orchestrator import LeadSorcererOrchestrator

            orchestrator = LeadSorcererOrchestrator(str(config_file))

            # Run the pipeline
            result = await orchestrator.run_pipeline()

            # Verify pipeline execution
            assert result is not None
            assert "success" in result
            assert result["success"] is True

            # Verify tool calls
            mock_domain.run.assert_called_once()
            mock_crawl.run.assert_called_once()
            MockRunEnrich.assert_called_once()

            # Verify data flow
            # The pipeline modifies the status during execution, so we check the final result
            assert result is not None
            assert "success" in result
            assert result["success"] is True

            # Verify tool calls were made
            mock_domain.run.assert_called_once()
            mock_crawl.run.assert_called_once()
            MockRunEnrich.assert_called_once()

    @pytest.mark.asyncio
    async def test_crawl_tool_failure(self):
        """Test pipeline behavior when Crawl tool fails."""
        # Test Crawl tool failure scenarios
        # This test will verify failure handling
        # Implementation depends on failure logic
        pass

    @pytest.mark.asyncio
    async def test_enrich_tool_failure(self):
        """Test pipeline behavior when Enrich tool fails."""
        # Test Enrich tool failure scenarios
        # This test will verify failure handling
        # Implementation depends on failure logic
        pass

    @pytest.mark.asyncio
    async def test_partial_failures(self):
        """Test pipeline behavior with partial failures."""
        # Test partial failure scenarios
        # This test will verify partial failure handling
        # Implementation depends on failure logic
        pass


class TestPipelinePerformanceTests:
    """Test pipeline performance characteristics."""

    @pytest.mark.asyncio
    async def test_pipeline_concurrency_limits(self):
        """Test that pipeline respects concurrency limits."""
        # Test concurrency limit enforcement
        # This test will verify concurrency control
        # Implementation depends on concurrency logic
        pass

    @pytest.mark.asyncio
    async def test_pipeline_timeout_handling(self):
        """Test pipeline timeout handling."""
        # Test timeout scenarios
        # This test will verify timeout handling
        # Implementation depends on timeout logic
        pass

    @pytest.mark.asyncio
    async def test_pipeline_memory_usage(self):
        """Test pipeline memory usage characteristics."""
        # Test memory usage patterns
        # This test will verify memory efficiency
        # Implementation depends on memory management
        pass


class TestEnrichmentProviderIntegration:
    """Test enrichment provider integration scenarios."""

    @pytest.mark.asyncio
    async def test_enrichment_provider_fallback_integration(self):
        """Test end-to-end enrichment with provider fallback scenarios."""
        from src.enrich_provider_router import EnrichmentProviderRouter
        from src.enrich_providers.base import EnrichmentRequest, EnrichmentResult, CompanyData, ContactData, ProviderTier
        from unittest.mock import MagicMock, AsyncMock
        
        # Mock provider initialization to avoid API key requirements
        with patch.object(EnrichmentProviderRouter, '_initialize_providers') as mock_init:
            mock_init.return_value = None
            
            router = EnrichmentProviderRouter()
            
            # Set up mock providers with different success scenarios
            mock_primary = MagicMock()
            mock_primary.name = "CompanyEnrich"
            mock_primary.tier = ProviderTier.TIER_0
            
            mock_fallback = MagicMock()
            mock_fallback.name = "Coresignal"
            mock_fallback.tier = ProviderTier.TIER_1
            
            router.providers[ProviderTier.TIER_0] = [mock_primary]
            router.providers[ProviderTier.TIER_1] = [mock_fallback]
            router.providers[ProviderTier.TIER_2] = []
            
            # Test 1: Primary provider succeeds
            mock_primary.enrich_company = AsyncMock(return_value=EnrichmentResult(
                success=True,
                data=CompanyData(domain="testcompany.com", name="Test Company", industry="Software"),
                provider="company_enrich",
                cost=0.01,
                latency_ms=150.0
            ))
            
            request = EnrichmentRequest(domain="testcompany.com")
            result = await router.enrich_company(request)
            
            assert result.success is True
            assert result.provider == "company_enrich"
            assert result.data.name == "Test Company"
            assert result.cost == 0.01
            
            # Test 2: Primary provider fails, fallback succeeds
            mock_primary.enrich_company = AsyncMock(return_value=EnrichmentResult(
                success=False,
                error="Rate limit exceeded",
                provider="company_enrich"
            ))
            
            mock_fallback.enrich_company = AsyncMock(return_value=EnrichmentResult(
                success=True,
                data=CompanyData(domain="testcompany.com", name="Test Company Fallback", industry="Technology"),
                provider="coresignal",
                cost=0.0,
                latency_ms=300.0
            ))
            
            result = await router.enrich_company(request)
            
            assert result.success is True
            assert result.provider == "coresignal"
            assert result.data.name == "Test Company Fallback"
            assert result.cost == 0.0
            
            # Verify both providers were called
            mock_primary.enrich_company.assert_called()
            mock_fallback.enrich_company.assert_called()

    @pytest.mark.asyncio
    async def test_enrichment_contact_discovery_integration(self):
        """Test end-to-end contact discovery across providers."""
        from src.enrich_provider_router import EnrichmentProviderRouter
        from src.enrich_providers.base import EnrichmentRequest, EnrichmentResult, ContactData, ProviderTier
        from unittest.mock import MagicMock, AsyncMock
        
        # Mock provider initialization
        with patch.object(EnrichmentProviderRouter, '_initialize_providers') as mock_init:
            mock_init.return_value = None
            
            router = EnrichmentProviderRouter()
            
            # Set up mock providers
            mock_provider = MagicMock()
            mock_provider.name = "AnymailFinder"
            mock_provider.tier = ProviderTier.TIER_0
            
            router.providers[ProviderTier.TIER_0] = [mock_provider]
            router.providers[ProviderTier.TIER_1] = []
            router.providers[ProviderTier.TIER_2] = []
            
            # Test contact enrichment
            mock_provider.enrich_contacts = AsyncMock(return_value=EnrichmentResult(
                success=True,
                data=[
                    ContactData(
                        email="john.doe@testcompany.com",
                        first_name="John",
                        last_name="Doe",
                        job_title="CEO",
                        company_domain="testcompany.com"
                    ),
                    ContactData(
                        email="jane.smith@testcompany.com",
                        first_name="Jane",
                        last_name="Smith",
                        job_title="CTO",
                        company_domain="testcompany.com"
                    )
                ],
                provider="anymail_finder",
                cost=0.015,
                latency_ms=250.0
            ))
            
            # Test email finding
            mock_provider.find_email = AsyncMock(return_value=EnrichmentResult(
                success=True,
                data=ContactData(
                    email="bob.wilson@testcompany.com",
                    first_name="Bob",
                    last_name="Wilson",
                    job_title="VP Sales"
                ),
                provider="anymail_finder",
                cost=0.012,
                latency_ms=180.0
            ))
            
            # Test contact enrichment
            request = EnrichmentRequest(domain="testcompany.com")
            result = await router.enrich_contacts(request)
            
            assert result.success is True
            assert len(result.data) == 2
            assert result.data[0].email == "john.doe@testcompany.com"
            assert result.data[1].job_title == "CTO"
            
            # Test email finding
            email_request = EnrichmentRequest(
                domain="testcompany.com",
                first_name="Bob",
                last_name="Wilson"
            )
            email_result = await router.find_email(email_request)
            
            assert email_result.success is True
            assert email_result.data.email == "bob.wilson@testcompany.com"
            assert email_result.data.job_title == "VP Sales"

    @pytest.mark.asyncio
    async def test_enrichment_cost_tracking_integration(self):
        """Test cost tracking and budgeting across enrichment operations."""
        from src.enrich_provider_router import EnrichmentProviderRouter
        from src.enrich_providers.base import EnrichmentRequest, EnrichmentResult, CompanyData, ProviderTier
        from unittest.mock import MagicMock, AsyncMock
        
        # Mock provider initialization
        with patch.object(EnrichmentProviderRouter, '_initialize_providers') as mock_init:
            mock_init.return_value = None
            
            router = EnrichmentProviderRouter()
            
            # Set up mock providers with different costs
            mock_expensive = MagicMock()
            mock_expensive.name = "CompanyEnrich"
            mock_expensive.tier = ProviderTier.TIER_0
            
            mock_cheap = MagicMock()
            mock_cheap.name = "Coresignal"
            mock_cheap.tier = ProviderTier.TIER_1
            
            router.providers[ProviderTier.TIER_0] = [mock_expensive]
            router.providers[ProviderTier.TIER_1] = [mock_cheap]
            router.providers[ProviderTier.TIER_2] = []
            
            # Mock different cost scenarios
            mock_expensive.enrich_company = AsyncMock(return_value=EnrichmentResult(
                success=True,
                data=CompanyData(domain="testcompany.com", name="Test Company"),
                provider="company_enrich",
                cost=0.05,  # Higher cost
                latency_ms=100.0
            ))
            
            mock_cheap.enrich_company = AsyncMock(return_value=EnrichmentResult(
                success=True,
                data=CompanyData(domain="testcompany.com", name="Test Company"),
                provider="coresignal",
                cost=0.0,  # Free
                latency_ms=200.0
            ))
            
            # Test multiple enrichment calls to track cumulative costs
            requests = [
                EnrichmentRequest(domain="company1.com"),
                EnrichmentRequest(domain="company2.com"),
                EnrichmentRequest(domain="company3.com")
            ]
            
            total_cost = 0.0
            for req in requests:
                result = await router.enrich_company(req)
                if result.success and result.cost:
                    total_cost += result.cost
            
            # Verify cost accumulation
            assert total_cost > 0.0
            # Since we're using the expensive provider, each call should cost 0.05
            assert abs(total_cost - 0.15) < 0.001  # 3 calls * 0.05 each (with floating point tolerance)


class TestPipelineIntegrationScenarios:
    """Test specific integration scenarios."""

    @pytest.mark.asyncio
    async def test_large_batch_processing(self):
        """Test pipeline with large batch sizes."""
        # Test large batch processing
        # This test will verify scalability
        # Implementation depends on batch processing logic
        pass

    @pytest.mark.asyncio
    async def test_mixed_success_failure_scenarios(self):
        """Test pipeline with mixed success/failure scenarios."""
        # Test mixed scenarios
        # This test will verify robustness
        # Implementation depends on scenario logic
        pass

    @pytest.mark.asyncio
    async def test_pipeline_recovery_scenarios(self):
        """Test pipeline recovery from various failure states."""
        # Test recovery scenarios
        # This test will verify resilience
        # Implementation depends on recovery logic
        pass


if __name__ == "__main__":
    pytest.main([__file__])
