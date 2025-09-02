"""
Orchestrator for Lead Sorcerer.

This orchestrator coordinates the three main tools (Domain, Crawl, Enrich) to process
leads through the complete pipeline. It handles data flow, persistence, exports,
and respects all BRD constraints.

Authoritative specifications: BRD §410-439
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

from src.common import (
    PermitManager,
    setup_logging,
    validate_provider_config,
    load_costs_config,
    round4,
    now_z,
    normalize_role_priority,
    build_error,
    ErrorCode,
)
from src.domain import DomainTool
from src.crawl import CrawlTool
from src.enrich import run_enrich, HunterIOClient
from src.enrich_provider_router import create_enrichment_router

# ============================================================================
# Constants and Configuration
# ============================================================================

INTERNAL_VERSION = "1.0.0"
DEFAULT_BATCH_SIZE = 50
DEFAULT_MAX_CONCURRENT_REQUESTS = 3

# ============================================================================
# Orchestrator Class
# ============================================================================


class LeadSorcererOrchestrator:
    """
    Main orchestrator that coordinates Domain → Crawl → Enrich pipeline.

    Responsibilities:
    - Load icp_config.json and resolve data directory
    - Call tools in sequence with proper filtering
    - Persist results to JSONL files
    - Handle exports when enabled
    - Manage concurrency and batch processing
    - Support both traditional and Apollo lead generation modes
    """

    def __init__(self, config_path: str, batch_size: int = DEFAULT_BATCH_SIZE):
        """
        Initialize the orchestrator.

        Args:
            config_path: Path to icp_config.json
            batch_size: Number of leads to process per batch
        """
        self.config_path = config_path
        self.batch_size = batch_size

        # Load configuration first
        self.icp_config = self._load_icp_config()

        # Resolve data directory
        self.data_dir = self._resolve_data_dir()

        # Establish a single shared log file for this run
        logs_dir = Path(self.data_dir) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        run_timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
        shared_log_file = str(logs_dir / f"run_{run_timestamp}.log")
        # Expose to child tools via env so all use the same file
        os.environ["LEADSORCERER_LOG_FILE"] = shared_log_file

        # Setup logging after data_dir is resolved, using the shared log file
        self.logger = setup_logging(
            "orchestrator", data_dir=self.data_dir, log_file_path=shared_log_file
        )

        # Initialize permit manager for global concurrency control
        max_concurrent = self.icp_config.get("concurrency", {}).get(
            "max_concurrent_requests", DEFAULT_MAX_CONCURRENT_REQUESTS
        )
        self.permit_manager = PermitManager(max_concurrent)

        # Load costs configuration for Hunter.io
        self.costs_config = load_costs_config()

        # Initialize Hunter.io client with performance optimization settings
        self.hunter_client = None
        hunter_api_key = os.environ.get("HUNTER_IO_API_KEY")
        if hunter_api_key:
            # Get performance optimization settings from ICP config
            hunter_config = self.icp_config.get("hunter_io", {})
            perf_config = hunter_config.get("performance_optimization", {})
            
            # Caching settings
            cache_config = perf_config.get("caching", {})
            cache_enabled = cache_config.get("enabled", True)
            cache_ttl_hours = cache_config.get("ttl_hours", 24) if cache_enabled else 0
            max_cache_size = cache_config.get("max_size", 10000) if cache_enabled else 0
            
            # Initialize Hunter.io client with performance and error handling settings
            if cache_enabled:
                # Get error handling configuration
                error_config = perf_config.get("error_handling", {})
                error_enabled = error_config.get("enabled", True)
                
                if error_enabled:
                    max_retries = error_config.get("max_retries", 3)
                    base_delay = error_config.get("base_delay", 1.0)
                    max_delay = error_config.get("max_delay", 60.0)
                    
                    self.hunter_client = HunterIOClient(
                        api_key=hunter_api_key,
                        cache_ttl_hours=cache_ttl_hours,
                        max_cache_size=max_cache_size
                    )
                    
                    # Apply error handling configuration
                    self.hunter_client.max_retries = max_retries
                    self.hunter_client.base_delay = base_delay
                    self.hunter_client.max_delay = max_delay
                    
                    self.logger.info(f"✅ Hunter.io client initialized with caching and error handling (TTL: {cache_ttl_hours}h, Max size: {max_cache_size}, Retries: {max_retries}, Base delay: {base_delay}s, Max delay: {max_delay}s)")
                else:
                    self.hunter_client = HunterIOClient(
                        api_key=hunter_api_key,
                        cache_ttl_hours=cache_ttl_hours,
                        max_cache_size=max_cache_size
                    )
                    self.logger.info(f"✅ Hunter.io client initialized with caching only (TTL: {cache_ttl_hours}h, Max size: {max_cache_size})")
            else:
                self.hunter_client = HunterIOClient(hunter_api_key)
                self.logger.info("✅ Hunter.io client initialized without caching")
        else:
            self.logger.warning("⚠️ HUNTER_IO_API_KEY not configured - email verification will be limited")

        # Initialize tools based on lead generation mode
        self._initialize_tools()

        # Track metrics
        self.start_time = None
        self.total_errors = []
        self.total_unknown_errors = 0

    async def cleanup(self):
        """Properly cleanup resources, especially async Apollo client."""
        if hasattr(self, "apollo_tool") and self.apollo_tool is not None:
            try:
                if hasattr(self.apollo_tool, "close"):
                    if asyncio.iscoroutinefunction(self.apollo_tool.close):
                        await self.apollo_tool.close()
                    else:
                        self.apollo_tool.close()
                self.apollo_tool = None
            except Exception as e:
                self.logger.warning(f"Error during Apollo tool cleanup: {e}")

    def __del__(self):
        """Cleanup method - fallback for sync cleanup only."""
        if hasattr(self, "apollo_tool") and self.apollo_tool is not None:
            try:
                # Only attempt sync cleanup as fallback
                if hasattr(
                    self.apollo_tool, "close"
                ) and not asyncio.iscoroutinefunction(self.apollo_tool.close):
                    self.apollo_tool.close()
                elif hasattr(self.apollo_tool, "close") and asyncio.iscoroutinefunction(
                    self.apollo_tool.close
                ):
                    # Schedule async cleanup as last resort
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(self.apollo_tool.close())
                    except RuntimeError:
                        pass  # No loop available
            except Exception:
                pass  # Ignore cleanup errors

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - ensure cleanup."""
        await self.cleanup()

    def _initialize_tools(self) -> None:
        """Initialize tools based on lead generation mode."""
        mode = self._detect_lead_generation_mode()

        if mode == "apollo":
            # Apollo mode: Initialize Apollo lead generation tool
            try:
                from src.apollo.lead_gen import ApolloLeadGen

                self.apollo_tool = ApolloLeadGen(
                    self.icp_config, 
                    self.data_dir,
                    hunter_client=self.hunter_client,
                    logger=self.logger,
                    costs_config=self.costs_config
                )
                self.logger.info("✅ Apollo lead generation tool initialized")
            except ModuleNotFoundError as e:
                self.logger.error(f"Apollo package not installed: {e}")
                raise ValueError(
                    "Apollo mode requires Apollo lead generation tool to be available"
                ) from e
            except ImportError as e:
                import traceback

                self.logger.error(f"Failed to import Apollo lead generation tool: {e}")
                self.logger.error(f"Full traceback: {traceback.format_exc()}")
                raise ValueError(f"Apollo mode import error: {e}")

            # Still initialize traditional tools for fallback if needed
            self.domain_tool = DomainTool(self.icp_config, self.data_dir)
            self.crawl_tool = CrawlTool(self.data_dir)

        elif mode == "database":
            # Database mode: Initialize crawl tool only (skip domain discovery)
            self.apollo_tool = None
            self.domain_tool = None  # Skip domain discovery
            self.crawl_tool = CrawlTool(self.data_dir)
            self.logger.info(
                "✅ Database mode: Crawl tool initialized, domain discovery skipped"
            )

        else:
            # Search/URL mode: Initialize traditional tools
            self.domain_tool = DomainTool(self.icp_config, self.data_dir)
            self.crawl_tool = CrawlTool(self.data_dir)
            self.apollo_tool = None
            self.logger.info(
                f"✅ {mode.capitalize()} mode: Traditional tools initialized"
            )

    def _detect_database_mode(self, icp_config: Dict[str, Any]) -> bool:
        """
        Detect if this should run as database mode.

        Args:
            icp_config: ICP configuration dictionary

        Returns:
            True if database mode should be used
        """
        # Explicit mode declaration takes precedence
        if icp_config.get("lead_generation_mode") == "database":
            return True

        # Legacy support: site_type=information_database
        if icp_config.get("site_type") == "information_database":
            self.logger.warning(
                "⚠️ Using legacy site_type. Consider using lead_generation_mode='database'"
            )
            return True

        # Auto-detection: Multiple URLs with database patterns
        specific_urls = icp_config.get("specific_urls", [])
        if len(specific_urls) > 5 and self._has_database_url_patterns(specific_urls):
            self.logger.info("🔍 Auto-detected database mode from URL patterns")
            return True

        return False

    def _has_database_url_patterns(self, urls: List[str]) -> bool:
        """
        Detect if URLs follow database/directory patterns.

        Args:
            urls: List of URLs to analyze

        Returns:
            True if URLs appear to be database/directory patterns
        """
        database_patterns = [
            "yellowpages.com/search",
            "yelp.com/search",
            "google.com/maps/search",
            "/directory/",
            "/listings/",
            "/search?",
            "page=",
            "offset=",
            "start=",  # Pagination indicators
        ]

        matches = 0
        for url in urls:
            if any(pattern in url.lower() for pattern in database_patterns):
                matches += 1

        # If >60% of URLs match database patterns, likely a database extraction
        return matches / len(urls) > 0.6

    def _detect_lead_generation_mode(self) -> str:
        """
        Enhanced mode detection with auto-detection support.

        Returns:
            Lead generation mode: "search", "url", "apollo", or "database"
        """
        # Check explicit mode first
        explicit_mode = self.icp_config.get("lead_generation_mode")
        self.logger.info(f"🔍 DEBUG: Raw lead_generation_mode from config: {explicit_mode}")
        
        if explicit_mode:
            # Handle legacy mode names for backward compatibility
            if explicit_mode == "traditional":
                self.logger.warning(
                    "⚠️ Using legacy mode 'traditional'. Consider using 'search' instead."
                )
                explicit_mode = "search"
            elif explicit_mode == "specific_urls":
                self.logger.warning(
                    "⚠️ Using legacy mode 'specific_urls'. Consider using 'url' instead."
                )
                explicit_mode = "url"

            # Validate explicit mode
            if explicit_mode not in ["search", "url", "apollo", "database"]:
                self.logger.warning(
                    f"Invalid lead_generation_mode: {explicit_mode}, defaulting to 'search'"
                )
                explicit_mode = "search"

            self.logger.info(
                f"🔍 Lead generation mode detected (explicit): {explicit_mode}"
            )
            return explicit_mode

        # Auto-detection logic when no explicit mode is set
        if self._detect_database_mode(self.icp_config):
            self.logger.info(
                "🔍 Auto-detected database mode from configuration patterns"
            )
            return "database"

        # Default to search mode
        self.logger.info("🔍 Lead generation mode detected (default): search")
        return "search"

    def _warn_legacy_configuration(self) -> None:
        """
        Warn about legacy configuration patterns.
        """
        if self.icp_config.get("site_type") == "information_database":
            self.logger.warning(
                "⚠️ Using legacy site_type='information_database'. "
                "Consider using lead_generation_mode='database' for better discoverability."
            )

        if "mode" in self.icp_config:
            self.logger.warning(
                "⚠️ Legacy 'mode' field detected. "
                "This field is deprecated and should be removed. "
                "Use lead_generation_mode instead."
            )

    def _should_run_apollo_pipeline(self) -> bool:
        """
        Determine if we should run the Apollo pipeline.

        Returns:
            True if Apollo mode is enabled and Apollo tool is available
        """
        mode = self._detect_lead_generation_mode()
        should_run = mode == "apollo" and self.apollo_tool is not None

        if should_run:
            self.logger.info("🚀 Apollo pipeline mode enabled")

        return should_run

    def _should_run_database_pipeline(self) -> bool:
        """
        Determine if we should run the database pipeline.

        Returns:
            True if database mode is enabled
        """
        mode = self._detect_lead_generation_mode()
        should_run = mode == "database"

        if should_run:
            self.logger.info("🗄️ Database pipeline mode enabled")

        return should_run

    def _load_icp_config(self) -> Dict[str, Any]:
        """Load and validate ICP configuration."""
        try:
            with open(self.config_path, "r") as f:
                config = json.load(f)

            # Validate required fields
            required_fields = [
                "name",
                "icp_text",
                "queries",
                "required_fields",
                "threshold",
            ]
            for field in required_fields:
                if field not in config:
                    raise ValueError(f"Missing required field: {field}")

            # Normalize role_priority configuration
            if "role_priority" in config:
                config["role_priority"] = normalize_role_priority(
                    config["role_priority"]
                )

            return config
        except Exception as e:
            self.logger.error(f"Failed to load ICP config: {e}")
            raise

    def _resolve_data_dir(self) -> str:
        """Resolve data directory with precedence."""
        # Check environment variable first
        env_data_dir = os.environ.get("LEADPOET_DATA_DIR")
        if env_data_dir:
            return env_data_dir

        # Default to ./data
        return "./data"

    def _validate_provider_config(self) -> None:
        """Validate that all required providers are configured."""
        try:
            costs_config = load_costs_config()
            required_providers = [
                "gse",
                "openrouter",
                "firecrawl",
                "coresignal",
                "mailgun",
                "snovio",
            ]
            validate_provider_config(required_providers, costs_config)
        except Exception as e:
            self.logger.error(f"Provider configuration validation failed: {e}")
            raise

    def _validate_configuration_schema(self) -> None:
        """Validate the ICP configuration against the schema."""
        mode = self._detect_lead_generation_mode()

        # Check for legacy configuration patterns and warn
        self._warn_legacy_configuration()

        # Validate lead generation mode specific requirements
        if mode == "apollo":
            self._validate_apollo_configuration()
        elif mode == "database":
            self._validate_database_configuration()
        elif mode in ["search", "url"]:
            self._validate_traditional_configuration()

        # Validate enrichment providers configuration
        self._validate_enrichment_providers_configuration()

        self.logger.info(f"✅ Configuration validation passed for mode: {mode}")

    def _validate_apollo_configuration(self) -> None:
        """Validate Apollo mode configuration."""
        apollo_config = self.icp_config.get("apollo", {})
        if not apollo_config:
            raise ValueError("Apollo mode requires 'apollo' configuration section")

        if not apollo_config.get("enabled", False):
            raise ValueError("Apollo mode requires apollo.enabled to be true")

    def _validate_traditional_configuration(self) -> None:
        """Validate search/url mode configuration."""
        mode = self._detect_lead_generation_mode()

        if mode == "search":
            # Search mode requires queries
            queries = self.icp_config.get("queries", [])
            if not queries:
                raise ValueError(
                    "Search mode requires at least one query in 'queries' array"
                )
        elif mode == "url":
            # URL mode requires specific_urls
            specific_urls = self.icp_config.get("specific_urls", [])
            if not specific_urls:
                raise ValueError(
                    "URL mode requires at least one URL in 'specific_urls' array"
                )

    def _validate_enrichment_providers_configuration(self) -> None:
        """Validate enrichment providers configuration."""
        enrichment_providers = self.icp_config.get("enrichment_providers", {})

        # Check if at least one enrichment provider is enabled
        enabled_providers = []
        for provider_name, provider_config in enrichment_providers.items():
            if provider_config.get("enabled", False):
                enabled_providers.append(provider_name)

        if not enabled_providers:
            self.logger.warning(
                "⚠️ No enrichment providers explicitly enabled. Using default providers."
            )
        else:
            self.logger.info(
                f"✅ Enabled enrichment providers: {', '.join(enabled_providers)}"
            )

    def _validate_testing_flags(self) -> None:
        """Validate testing configuration flags."""
        testing = self.icp_config.get("testing", {})

        # Validate process_rejected flag
        if not isinstance(testing.get("process_rejected", False), bool):
            raise ValueError("testing.process_rejected must be a boolean")

        # Validate process_low_crawl flag
        if not isinstance(testing.get("process_low_crawl", False), bool):
            raise ValueError("testing.process_low_crawl must be a boolean")

        self.logger.info(
            f"Testing flags: process_rejected={testing.get('process_rejected', False)}, process_low_crawl={testing.get('process_low_crawl', False)}"
        )

    def _validate_refresh_policy(self) -> None:
        """Validate refresh policy configuration."""
        refresh_policy = self.icp_config.get("refresh_policy", {})

        # Validate domain_ttl_days override
        domain_ttl_days = refresh_policy.get("domain_ttl_days")
        if domain_ttl_days is not None and not isinstance(domain_ttl_days, int):
            raise ValueError("refresh_policy.domain_ttl_days must be an integer")

        # Validate search.max_pages override
        search_config = self.icp_config.get("search", {})
        max_pages = search_config.get("max_pages")
        if max_pages is not None and not isinstance(max_pages, int):
            raise ValueError("search.max_pages must be an integer")

        # Validate default_country
        default_country = self.icp_config.get("default_country")
        if default_country and not isinstance(default_country, str):
            raise ValueError("default_country must be a string")

        # Validate role_priority configuration
        role_priority = self.icp_config.get("role_priority", {})
        if not isinstance(role_priority, dict):
            raise ValueError("role_priority must be a dictionary")

        self.logger.info(
            f"Refresh policy validated: domain_ttl_days={domain_ttl_days}, max_pages={max_pages}, default_country={default_country}"
        )

    def should_bypass_domain_discovery(self) -> bool:
        """
        Check if we should bypass domain discovery and go directly to crawling specific URLs.
        This saves API costs and enables rapid iteration on known targets.

        Returns:
            True if we should bypass domain discovery and crawl specific URLs directly
        """
        specific_urls = self.icp_config.get("specific_urls", [])
        lead_generation_mode = self.icp_config.get("lead_generation_mode", "search")
        
        # Only bypass domain discovery when lead_generation_mode is explicitly "url"
        # This respects the user's mode choice and allows search mode to work with test URLs
        should_bypass = lead_generation_mode == "url" and len(specific_urls) > 0

        if should_bypass:
            self.logger.info(
                f"🚀 BYPASSING DOMAIN DISCOVERY: {len(specific_urls)} specific URLs provided (URL mode)"
            )
            self.logger.info(
                "💰 Cost optimization: Skipping search queries, going directly to crawl"
            )
            self.logger.info(
                f"📊 Specific URLs: {specific_urls[:3]}{'...' if len(specific_urls) > 3 else ''}"
            )
        elif len(specific_urls) > 0 and lead_generation_mode == "search":
            self.logger.info(
                f"📊 Specific URLs provided in SEARCH mode - will use for validation/testing, running full domain discovery"
            )
        elif len(specific_urls) > 0 and lead_generation_mode not in ["url", "search"]:
            self.logger.info(
                f"📊 Specific URLs provided but running in {lead_generation_mode} mode - will use for validation"
            )

        return should_bypass

    def create_lead_records_from_specific_urls(self) -> List[Dict[str, Any]]:
        """
        Create lead records directly from specific URLs, bypassing domain discovery.
        This enables rapid iteration and cost optimization.

        Returns:
            List of lead records ready for crawling
        """
        specific_urls = self.icp_config.get("specific_urls", [])
        lead_records = []

        for i, url in enumerate(specific_urls):
            # Extract domain from URL
            from urllib.parse import urlparse

            parsed = urlparse(url)
            domain = parsed.netloc

            # Create lead record with complete schema compliance
            lead_record = {
                "lead_id": f"specific-url-{i + 1:03d}",
                "domain": domain,
                "status": "scored",  # Ready for crawl - skip domain scoring
                "status_history": [],  # Initialize status history for enrich tool
                "company": {
                    "name": f"{self.icp_config.get('company_name_template', 'Company from {domain}').format(domain=domain)}",
                    "description": f"Direct crawl from specific URL: {url}",
                },
                "contacts": [],  # Will be populated by enrich tool
                "provenance": {
                    "source": "specific_urls",
                    "specific_url": url,
                    "bypassed_domain_discovery": True,
                    "created_at": now_z(),
                    # Add missing schema fields for specific URL mode
                    "queries": [],  # No search queries used
                    "discovery_evidence": [],  # No discovery performed
                    "scored_at": now_z(),  # Set to creation time
                    "crawled_at": None,  # Will be set by crawl tool
                    "enriched_at": None,  # Will be set by enrich tool
                    "next_revisit_at": None,  # Will be set by enrich tool
                    "tool_versions": {
                        "domain": "bypassed",
                        "crawl": None,  # Will be set by crawl tool
                        "enrich": None,  # Will be set by enrich tool
                    },
                    "cache": {"hit": False, "key": None},  # No domain cache used
                    "evidence_paths": {},  # Will be populated by tools
                },
                "icp": {
                    "pre_score": 1.0,  # Assume high value since it's a specific target
                    "pre_pass": True,
                    "pre_reason": "Specific URL target - bypassing domain scoring",
                    "threshold": self.icp_config.get("threshold", 0.1),
                    "filtering_strict": self.icp_config.get("filtering_strict", False),
                    # Add missing schema fields for specific URL mode
                    "pre_flags": [],  # No pre-analysis flags
                    "scoring_meta": {
                        "method": "bypass",
                        "model": "none",
                        "prompt_fingerprint": "specific-url-bypass",
                        "temperature": 0.0,
                    },
                    "crawl_score": None,  # Will be set by crawl tool
                    "crawl_reason": None,  # Will be set by crawl tool
                },
                "audit": [],  # Will be populated by tools
                "cost": {
                    "domain_usd": 0.0,
                    "crawl_usd": 0.0,
                    "enrich_usd": 0.0,
                    "total_usd": 0.0,
                },
            }

            lead_records.append(lead_record)

        self.logger.info(
            f"📋 Created {len(lead_records)} lead records from specific URLs"
        )
        self.logger.info("💰 Cost optimization: Bypassed domain discovery phase")

        return lead_records

    async def run_pipeline(self) -> Dict[str, Any]:
        """
        Run the complete lead generation pipeline.

        Returns:
            Pipeline results with metrics and summary
        """
        self.start_time = time.time()
        self.logger.info(
            f"Starting Lead Sorcerer pipeline with config: {self.icp_config['name']}"
        )

        try:
            # Validate provider configuration
            self._validate_provider_config()

            # Validate configuration schema
            self._validate_configuration_schema()

            # Validate testing flags and refresh policy
            self._validate_testing_flags()
            self._validate_refresh_policy()

            # Determine pipeline mode and execute accordingly
            if self._should_run_apollo_pipeline():
                return await self._run_apollo_pipeline()
            elif self._should_run_database_pipeline():
                return await self._run_database_pipeline()
            else:
                return await self._run_traditional_pipeline()

        except Exception as e:
            self.logger.error(f"Pipeline failed: {e}")
            return {
                "success": False,
                "errors": [build_error(ErrorCode.UNKNOWN, exc=e, tool="orchestrator")],
                "metrics": self._build_error_metrics(),
            }

    async def _run_apollo_pipeline(self) -> Dict[str, Any]:
        """
        Run the Apollo lead generation pipeline.

        Returns:
            Pipeline results with metrics and summary
        """
        self.logger.info("🚀 Running Apollo lead generation pipeline")

        try:
            # Step 1: Apollo lead generation
            self.logger.info(
                f"About to call Apollo tool.run() - apollo_tool: {self.apollo_tool}"
            )
            self.logger.info(f"Apollo tool type: {type(self.apollo_tool)}")

            apollo_result = await self.apollo_tool.run(
                hunter_client=self.hunter_client,
                logger=self.logger,
                costs_config=self.costs_config
            )
            self.logger.info(f"Apollo tool.run() completed, result: {apollo_result}")

            if apollo_result.get("errors"):
                self.total_errors.extend(apollo_result["errors"])

            lead_records = apollo_result.get("data", {}).get("lead_records", [])
            self.logger.info(f"Apollo tool processed {len(lead_records)} leads")

            # Persist Apollo results
            self._persist_apollo_results(lead_records)

            # Filter to passing leads for next stage
            passing_leads = [
                r for r in lead_records if r.get("icp", {}).get("pre_pass")
            ]
            self.logger.info(f"Filtered to {len(passing_leads)} passing leads")

            # Step 2: Crawl tool - extract company and contact data
            crawl_result = None
            enrich_result = None

            if passing_leads:
                self.logger.info("Running Crawl tool...")
                crawl_payload = {
                    "lead_records": passing_leads,
                    "icp_config": self.icp_config,
                }
                crawl_result = await self.crawl_tool.run(
                    crawl_payload, 
                    hunter_client=self.hunter_client, 
                    logger=self.logger, 
                    costs_config=self.costs_config
                )

                if crawl_result.get("errors"):
                    self.total_errors.extend(crawl_result["errors"])

                crawled_leads = crawl_result.get("data", {}).get("lead_records", [])
                self.logger.info(f"Crawl tool processed {len(crawled_leads)} leads")

                # Filter to enrich_ready leads
                enrich_ready_leads = [
                    r for r in crawled_leads if r.get("status") == "enrich_ready"
                ]
                self.logger.info(f"Found {len(enrich_ready_leads)} enrich_ready leads")

                # Check testing flags for additional processing
                testing = self.icp_config.get("testing", {})
                process_low_crawl = testing.get("process_low_crawl", False)

                if process_low_crawl:
                    # Include crawled leads that don't meet threshold
                    low_crawl_leads = [
                        r for r in crawled_leads if r.get("status") == "crawled"
                    ]
                    enrich_ready_leads.extend(low_crawl_leads)
                    self.logger.info(
                        f"Including {len(low_crawl_leads)} low-crawl leads due to testing flag"
                    )

                # Step 3: Enrich tool - fill missing data and verify contacts
                if enrich_ready_leads:
                    self.logger.info(
                        f"Running Enrich tool with {len(enrich_ready_leads)} leads..."
                    )

                    # Initialize enrichment provider router (includes Apollo provider)
                    enrichment_router = create_enrichment_router(self.icp_config)

                    enrich_payload = {
                        "lead_records": enrich_ready_leads,
                        "icp_config": self.icp_config,
                        "caps": self.icp_config.get("caps", {}),
                        "router": enrichment_router,
                    }

                    enrich_result = await run_enrich(enrich_payload)

                    if enrich_result.get("errors"):
                        self.total_errors.extend(enrich_result["errors"])

                    enriched_leads = enrich_result.get("data", {}).get(
                        "lead_records", []
                    )
                    self.logger.info(
                        f"Enrich tool processed {len(enriched_leads)} leads"
                    )

                    # Update the main lead records with enriched data
                    self._update_lead_records_with_enriched_data(
                        lead_records, enriched_leads
                    )
                else:
                    self.logger.info("No leads ready for enrichment")
            else:
                self.logger.info("No passing leads to crawl")

            # Handle exports if enabled
            if self.icp_config.get("exports", {}).get("enabled", False):
                self._export_leads(lead_records)

            # Calculate final metrics
            final_metrics = self._calculate_final_metrics(
                apollo_result, crawl_result, enrich_result
            )

            # Log summary
            self._log_pipeline_summary(final_metrics)

            return {
                "success": True,
                "metrics": final_metrics,
                "total_errors": len(self.total_errors),
                "unknown_error_count": self.total_unknown_errors,
                "errors": self.total_errors,
            }

        except Exception as e:
            self.logger.error(f"Apollo pipeline failed: {e}")

            # Check if fallback to traditional flow is enabled
            apollo_config = self.icp_config.get("apollo", {})
            fallback_enabled = apollo_config.get("fallback", {}).get(
                "to_traditional_flow", False
            )

            if fallback_enabled:
                self.logger.info(
                    "🔄 Apollo pipeline failed, falling back to traditional flow"
                )
                return await self._run_traditional_pipeline()
            else:
                raise

    async def _run_database_pipeline(self) -> Dict[str, Any]:
        """
        Run database extraction pipeline.

        Pipeline Flow:
        1. Validate database configuration
        2. Create lead records from database sites
        3. Skip domain discovery (like url mode)
        4. Run crawl tool with database extraction
        5. Run enrich tool on discovered companies

        Returns:
            Pipeline results with extracted companies from database sites
        """
        self.logger.info("🗄️ Running Database extraction pipeline")

        try:
            # Step 1: Validate database configuration
            self._validate_database_configuration()

            # Step 2: Create lead records from database sites
            lead_records = self._create_lead_records_from_database_sites()

            # Step 3: Skip domain discovery (similar to url mode)
            self.logger.info("💰 Cost optimization: Bypassed domain discovery phase")

            # Step 4: Run crawl tool with database extraction
            crawl_payload = {
                "lead_records": lead_records,
                "icp_config": self.icp_config,
                "extraction_mode": "database",  # Signal to crawl tool
            }
            crawl_result = await self.crawl_tool.run(
                crawl_payload, 
                hunter_client=self.hunter_client, 
                logger=self.logger, 
                costs_config=self.costs_config
            )

            if crawl_result.get("errors"):
                self.total_errors.extend(crawl_result["errors"])

            # Step 5: Run enrich tool
            enrich_ready_leads = self._filter_enrich_ready_leads(crawl_result)
            enrich_result = None

            if enrich_ready_leads:
                self.logger.info(
                    f"Running Enrich tool on {len(enrich_ready_leads)} leads..."
                )
                enrich_result = await self._run_enrich_tool(enrich_ready_leads)

                if enrich_result.get("errors"):
                    self.total_errors.extend(enrich_result["errors"])
            else:
                self.logger.info("No leads ready for enrichment")

            return self._build_database_pipeline_results(crawl_result, enrich_result)

        except Exception as e:
            self.logger.error(f"Database pipeline failed: {e}")
            return {
                "success": False,
                "pipeline_mode": "database",
                "errors": [
                    {"code": "UNKNOWN", "message": str(e), "tool": "orchestrator"}
                ],
                "metrics": self._build_error_metrics(),
            }

    async def _run_traditional_pipeline(self) -> Dict[str, Any]:
        """
        Run the traditional Domain → Crawl → Enrich pipeline.

        Returns:
            Pipeline results with metrics and summary
        """
        self.logger.info("📊 Running traditional lead generation pipeline")

        # Check if we should bypass domain discovery for specific URLs
        if self.should_bypass_domain_discovery():
            # BYPASS MODE: Create lead records directly from specific URLs
            self.logger.info("🚀 BYPASS MODE: Creating lead records from specific URLs")
            lead_records = self.create_lead_records_from_specific_urls()

            # Create mock domain result for consistency
            domain_result = {
                "data": {"lead_records": lead_records},
                "errors": [],
                "metrics": {
                    "count_in": 0,
                    "count_out": len(lead_records),
                    "duration_ms": 0,
                    "cost_usd": {
                        "domain": 0.0,
                        "crawl": 0.0,
                        "enrich": 0.0,
                        "total": 0.0,
                    },
                },
            }

            # All records from specific URLs are considered "passing"
            passing_leads = lead_records
            self.logger.info(
                f"💰 Cost savings: Skipped domain discovery for {len(passing_leads)} specific URL targets"
            )
        else:
            # NORMAL MODE: Run domain discovery as usual
            self.logger.info("📊 NORMAL MODE: Running domain discovery")
            
            # Check if we have specific URLs in search mode for validation
            specific_urls = self.icp_config.get("specific_urls", [])
            lead_generation_mode = self.icp_config.get("lead_generation_mode", "search")
            
            if specific_urls and lead_generation_mode == "search":
                self.logger.info(f"🔍 SEARCH MODE: {len(specific_urls)} specific URLs will be used for validation/testing")
                self.logger.info(f"📊 Running full domain discovery with queries: {self.icp_config.get('queries', [])}")
            
            domain_result = await self.domain_tool.run()

            if domain_result.get("errors"):
                self.total_errors.extend(domain_result["errors"])

            lead_records = domain_result.get("data", {}).get("lead_records", [])
            self.logger.info(f"Domain tool processed {len(lead_records)} leads")

            # Filter to passing leads for next stage
            passing_leads = [
                r for r in lead_records if r.get("icp", {}).get("pre_pass")
            ]
            self.logger.info(f"Filtered to {len(passing_leads)} passing leads")

        # Persist domain results (pass + rejects) - works for both modes
        self._persist_domain_results(lead_records)

        # Check testing flags for additional processing
        testing = self.icp_config.get("testing", {})

        # Step 2: Crawl tool - extract company and contact data
        crawl_result = None
        enrich_result = None

        if passing_leads:
            self.logger.info("Running Crawl tool...")
            crawl_payload = {
                "lead_records": passing_leads,
                "icp_config": self.icp_config,
            }
            crawl_result = await self.crawl_tool.run(
                crawl_payload, 
                hunter_client=self.hunter_client, 
                logger=self.logger, 
                costs_config=self.costs_config
            )

            if crawl_result.get("errors"):
                self.total_errors.extend(crawl_result["errors"])

            crawled_leads = crawl_result.get("data", {}).get("lead_records", [])
            self.logger.info(f"Crawl tool processed {len(crawled_leads)} leads")

            # Add detailed logging for pipeline flow
            self.logger.info(
                f"🔍 Pipeline Debug: Found {len(crawled_leads)} crawled leads"
            )
            status_counts = {}
            for lead in crawled_leads:
                status = lead.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
            self.logger.info(f"📊 Crawled leads status breakdown: {status_counts}")

            # Filter to enrich_ready leads
            enrich_ready_leads = [
                r for r in crawled_leads if r.get("status") == "enrich_ready"
            ]
            self.logger.info(
                f"🔍 Pipeline Debug: Found {len(enrich_ready_leads)} enrich_ready leads"
            )

            # Check testing flags for additional processing
            process_low_crawl = testing.get("process_low_crawl", False)

            if process_low_crawl:
                # Include crawled leads that don't meet threshold
                low_crawl_leads = [
                    r for r in crawled_leads if r.get("status") == "crawled"
                ]
                enrich_ready_leads.extend(low_crawl_leads)
                self.logger.info(
                    f"Including {len(low_crawl_leads)} low-crawl leads due to testing flag"
                )

            # Step 3: Enrich tool - fill missing data and verify contacts
            if enrich_ready_leads:
                self.logger.info(
                    f"🚀 Running Enrich tool with {len(enrich_ready_leads)} leads..."
                )
                # Initialize enrichment provider router
                enrichment_router = create_enrichment_router(self.icp_config)

                enrich_payload = {
                    "lead_records": enrich_ready_leads,
                    "icp_config": self.icp_config,
                    "caps": self.icp_config.get("caps", {}),
                    "router": enrichment_router,  # Pass router to enrich function
                }
                self.logger.info(
                    f"🔍 Enrich payload structure: {len(enrich_payload.get('lead_records', []))} leads, {len(enrich_payload.get('icp_config', {}))} config items"
                )

                # Call enrich with router (will be updated in Task 4)
                enrich_result = await run_enrich(enrich_payload)

                if enrich_result.get("errors"):
                    self.total_errors.extend(enrich_result["errors"])

                enriched_leads = enrich_result.get("data", {}).get("lead_records", [])
                self.logger.info(f"Enrich tool processed {len(enriched_leads)} leads")

                # Update the main lead records with enriched data
                self._update_lead_records_with_enriched_data(
                    lead_records, enriched_leads
                )
            else:
                self.logger.info("No leads ready for enrichment")
        else:
            self.logger.info("No passing leads to crawl")

        # Handle exports if enabled
        if self.icp_config.get("exports", {}).get("enabled", False):
            self._export_leads(lead_records)

        # Calculate final metrics
        final_metrics = self._calculate_final_metrics(
            domain_result, crawl_result, enrich_result
        )

        # Log summary
        self._log_pipeline_summary(final_metrics)

        return {
            "success": True,
            "metrics": final_metrics,
            "total_errors": len(self.total_errors),
            "unknown_error_count": self.total_unknown_errors,
            "errors": self.total_errors,  # Include actual error details
        }

    def _persist_domain_results(self, lead_records: List[Dict[str, Any]]) -> None:
        """Persist domain results to JSONL files."""
        try:
            # Ensure data directory exists
            Path(self.data_dir).mkdir(parents=True, exist_ok=True)

            # Write all results (pass + rejects)
            all_file = Path(self.data_dir) / "domain_all.jsonl"
            with open(all_file, "a", encoding="utf-8") as f:
                for record in lead_records:
                    f.write(json.dumps(record) + "\n")

            # Write only passing results
            pass_file = Path(self.data_dir) / "domain_pass.jsonl"
            passing_records = [
                r for r in lead_records if r.get("icp", {}).get("pre_pass")
            ]
            with open(pass_file, "a", encoding="utf-8") as f:
                for record in passing_records:
                    f.write(json.dumps(record) + "\n")

            self.logger.info(
                f"Persisted {len(lead_records)} total leads, {len(passing_records)} passing leads"
            )

            # Check if rotation is needed
            self._check_and_rotate_sinks(all_file, pass_file)

        except Exception as e:
            self.logger.error(f"Failed to persist domain results: {e}")

    def _persist_apollo_results(self, lead_records: List[Dict[str, Any]]) -> None:
        """Persist Apollo results to JSONL files."""
        try:
            # Ensure data directory exists
            Path(self.data_dir).mkdir(parents=True, exist_ok=True)

            # Write all Apollo results
            all_file = Path(self.data_dir) / "apollo_all.jsonl"
            with open(all_file, "a", encoding="utf-8") as f:
                for record in lead_records:
                    f.write(json.dumps(record) + "\n")

            # Write only passing results
            pass_file = Path(self.data_dir) / "apollo_pass.jsonl"
            passing_records = [
                r for r in lead_records if r.get("icp", {}).get("pre_pass")
            ]
            with open(pass_file, "a", encoding="utf-8") as f:
                for record in passing_records:
                    f.write(json.dumps(record) + "\n")

            self.logger.info(
                f"Persisted {len(lead_records)} total Apollo leads, {len(passing_records)} passing leads"
            )

            # Check if rotation is needed
            self._check_and_rotate_sinks(all_file, pass_file)

        except Exception as e:
            self.logger.error(f"Failed to persist Apollo results: {e}")

    def _check_and_rotate_sinks(self, all_file: Path, pass_file: Path) -> None:
        """
        Check if sinks need rotation (>10 MB or >30 days) and rotate if needed.

        Uses copy-on-write compaction to ensure atomic pointer swaps.
        """
        try:
            current_time = datetime.utcnow()

            # Check domain_all.jsonl
            if all_file.exists():
                self._rotate_sink_if_needed(all_file, current_time, "domain_all")

            # Check domain_pass.jsonl
            if pass_file.exists():
                self._rotate_sink_if_needed(pass_file, current_time, "domain_pass")

        except Exception as e:
            self.logger.error(f"Failed to check/rotate sinks: {e}")

    def _rotate_sink_if_needed(
        self, sink_file: Path, current_time: datetime, sink_name: str
    ) -> None:
        """
        Rotate a sink file if it exceeds size or time limits.

        Args:
            sink_file: Path to the sink file
            current_time: Current UTC time
            sink_name: Name of the sink for logging
        """
        try:
            # Check file size (>10 MB)
            file_size_mb = sink_file.stat().st_size / (1024 * 1024)
            size_exceeded = file_size_mb > 10

            # Check file age (>30 days)
            file_mtime = datetime.fromtimestamp(sink_file.stat().st_mtime)
            age_days = (current_time - file_mtime).days
            age_exceeded = age_days > 30

            if size_exceeded or age_exceeded:
                self.logger.info(
                    f"Rotating {sink_name}: size={file_size_mb:.1f}MB, age={age_days} days"
                )
                self._rotate_sink_with_compaction(sink_file, sink_name)

        except Exception as e:
            self.logger.error(f"Failed to check rotation for {sink_name}: {e}")

    def _rotate_sink_with_compaction(self, sink_file: Path, sink_name: str) -> None:
        """
        Rotate sink using copy-on-write compaction for atomic pointer swap.

        Args:
            sink_file: Path to the sink file
            sink_name: Name of the sink for logging
        """
        try:
            # Create timestamped archive name
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
            archive_name = f"{sink_name}_{timestamp}.jsonl"
            archive_path = sink_file.parent / archive_name

            # Copy current content to archive (copy-on-write)
            if sink_file.exists():
                with (
                    open(sink_file, "r", encoding="utf-8") as src,
                    open(archive_path, "w", encoding="utf-8") as dst,
                ):
                    dst.write(src.read())

                self.logger.info(f"Archived {sink_name} to {archive_name}")

            # Truncate the original file (atomic operation)
            sink_file.write_text("", encoding="utf-8")

            self.logger.info(f"Rotated {sink_name} - file truncated")

        except Exception as e:
            self.logger.error(f"Failed to rotate {sink_name}: {e}")

    def _update_lead_records_with_enriched_data(
        self, lead_records: List[Dict[str, Any]], enriched_leads: List[Dict[str, Any]]
    ) -> None:
        """Update lead records with enriched data from the enrich tool."""
        enriched_by_id = {r.get("lead_id"): r for r in enriched_leads}

        for record in lead_records:
            lead_id = record.get("lead_id")
            if lead_id in enriched_by_id:
                enriched_record = enriched_by_id[lead_id]
                # Update only the fields that Enrich tool is allowed to modify
                record.update(
                    {
                        "best_contact_id": enriched_record.get("best_contact_id"),
                        "status": enriched_record.get("status"),
                        "provenance": enriched_record.get("provenance", {}),
                        "cost": enriched_record.get("cost", {}),
                        "audit": enriched_record.get("audit", []),
                    }
                )

                # Update contacts with enriched data
                if "contacts" in enriched_record:
                    record["contacts"] = enriched_record["contacts"]

    def _export_leads(self, lead_records: List[Dict[str, Any]]) -> None:
        """Export leads to JSONL and CSV formats."""
        try:
            exports_config = self.icp_config.get("exports", {})
            if not exports_config.get("enabled", False):
                return

            # Create export directory with UTC timestamp
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
            export_dir = (
                Path(self.data_dir) / "exports" / self.icp_config["name"] / timestamp
            )
            export_dir.mkdir(parents=True, exist_ok=True)

            # Export to JSONL
            jsonl_file = export_dir / "leads.jsonl"
            with open(jsonl_file, "w", encoding="utf-8") as f:
                for record in lead_records:
                    f.write(json.dumps(record) + "\n")

            # Export to CSV
            csv_file = export_dir / "leads.csv"
            self._export_to_csv(lead_records, csv_file)

            self.logger.info(f"Exported {len(lead_records)} leads to {export_dir}")

        except Exception as e:
            self.logger.error(f"Failed to export leads: {e}")
            self.total_errors.append(f"Export failed: {e}")

    def _export_to_csv(
        self, lead_records: List[Dict[str, Any]], csv_file: Path
    ) -> None:
        """Export leads to CSV format with proper flattening rules."""
        if not lead_records:
            return

        # Get all possible fields for CSV headers
        all_fields = set()
        for record in lead_records:
            self._collect_fields(record, "", all_fields)

        # Sort fields lexicographically for stability
        sorted_fields = sorted(all_fields)

        # Write CSV header
        with open(csv_file, "w", encoding="utf-8", newline="") as f:
            f.write(",".join(f'"{field}"' for field in sorted_fields) + "\n")

            # Write data rows
            for record in lead_records:
                row_data = []
                for field in sorted_fields:
                    value = self._get_field_value(record, field)
                    row_data.append(f'"{value}"')
                f.write(",".join(row_data) + "\n")

    def _collect_fields(self, obj: Any, prefix: str, fields: set) -> None:
        """Recursively collect all field paths for CSV flattening."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                field_path = f"{prefix}.{key}" if prefix else key

                # Special handling for contacts array - include best contact fields and Hunter.io fields
                if key == "contacts" and isinstance(value, list) and value:
                    self._add_best_contact_fields(fields)
                    # Also add Hunter.io fields for all contacts
                    self._add_hunter_io_fields(fields)
                elif isinstance(value, (dict, list)):
                    self._collect_fields(value, field_path, fields)
                else:
                    fields.add(field_path)
        elif isinstance(obj, list):
            # For arrays, join with "|" separator
            if (
                obj
                and len(obj) > 0
                and isinstance(obj[0], (str, int, float, bool))
                or (obj and len(obj) > 0 and obj[0] is None)
            ):
                field_path = prefix
                fields.add(field_path)

    def _add_best_contact_fields(self, fields: set) -> None:
        """Add best contact fields to CSV export."""
        contact_fields = [
            "best_contact.full_name",
            "best_contact.job_title",  # Changed from role to job_title
            "best_contact.email",
            "best_contact.phone",
            "best_contact.decision_maker",
            "best_contact.linkedin_url",  # Changed from linkedin to linkedin_url
            "best_contact.department",
            "best_contact.seniority",
            "best_contact.location",
            # Hunter.io verification fields
            "best_contact.hunter_verification.score",
            "best_contact.hunter_verification.status",
            "best_contact.hunter_verification.result",
            "best_contact.email_quality_score",
            "best_contact.email_verified",
            "best_contact.needs_email_replacement",
            "best_contact.replaced_email",
            "best_contact.email_quality_improvement",
        ]
        fields.update(contact_fields)

    def _add_hunter_io_fields(self, fields: set) -> None:
        """Add Hunter.io verification fields to CSV export."""
        hunter_io_fields = [
            "hunter_verification.score",
            "hunter_verification.status", 
            "hunter_verification.result",
            "hunter_verification.disposable",
            "hunter_verification.webmail",
            "hunter_verification.mx_record",
            "hunter_verification.smtp_server",
            "hunter_verification.smtp_check",
            "hunter_verification.cost_usd",
            "email_quality_score",
            "email_verified",
            "needs_email_replacement",
            "replaced_email",
            "email_quality_improvement",
            "needs_email_discovery",
        ]
        fields.update(hunter_io_fields)

    def _get_best_contact_field(self, record: Dict[str, Any], field_name: str) -> str:
        """Get field value from the best contact."""
        try:
            # Get best contact ID
            best_contact_id = record.get("best_contact_id")
            contacts = record.get("contacts", [])

            if not contacts:
                return ""

            # If no best_contact_id is set, use the first contact
            if not best_contact_id and contacts:
                best_contact = contacts[0]
            else:
                # Find the best contact in contacts array by ID
                best_contact = None
                for contact in contacts:
                    if contact.get("contact_id") == best_contact_id:
                        best_contact = contact
                        break

                if not best_contact:
                    return ""

            # Get the requested field value
            # Handle field name mapping for backward compatibility
            if field_name == "role":
                value = best_contact.get("role") or best_contact.get("job_title")
            elif field_name == "linkedin":
                value = best_contact.get("linkedin") or best_contact.get("linkedin_url")
            elif field_name == "full_name":
                # Construct full name from first_name and last_name if not present
                value = best_contact.get("full_name")
                if not value:
                    first_name = best_contact.get("first_name", "")
                    last_name = best_contact.get("last_name", "")
                    if first_name or last_name:
                        value = f"{first_name} {last_name}".strip()
            elif field_name.startswith("hunter_verification."):
                # Handle nested Hunter.io verification fields
                hunter_verification = best_contact.get("hunter_verification", {})
                sub_field = field_name.split(".", 1)[1]
                value = hunter_verification.get(sub_field)
            else:
                value = best_contact.get(field_name)

            # Debug logging for job_title field
            if field_name == "job_title":
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"🔍 DEBUG: _get_best_contact_field called with field_name='{field_name}'")
                logger.info(f"🔍 DEBUG: best_contact_id='{best_contact_id}'")
                logger.info(f"🔍 DEBUG: contacts count={len(contacts)}")
                logger.info(f"🔍 DEBUG: best_contact found={best_contact is not None}")
                if best_contact:
                    logger.info(f"🔍 DEBUG: best_contact keys={list(best_contact.keys())}")
                    logger.info(f"🔍 DEBUG: best_contact.job_title={best_contact.get('job_title')}")
                    logger.info(f"🔍 DEBUG: best_contact.role={best_contact.get('role')}")
                logger.info(f"🔍 DEBUG: final value='{value}'")

            if value is None:
                return ""
            elif isinstance(value, bool):
                return str(value).lower()
            elif isinstance(value, list):
                return "|".join(str(v) if v is not None else "" for v in value)
            else:
                return str(value)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"❌ Error in _get_best_contact_field: {e}")
            return ""

    def _get_field_value(self, record: Dict[str, Any], field_path: str) -> str:
        """Get field value from record using dot notation."""
        try:
            keys = field_path.split(".")

            # Special handling for best_contact fields
            if keys[0] == "best_contact" and len(keys) > 1:
                return self._get_best_contact_field(record, keys[1])

            value = record
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return ""

            if value is None:
                return ""
            elif isinstance(value, bool):
                return str(value).lower()
            elif isinstance(value, list):
                # Join arrays with "|" separator
                if (
                    value
                    and len(value) > 0
                    and isinstance(value[0], (str, int, float, bool))
                    or (value and len(value) > 0 and value[0] is None)
                ):
                    return "|".join(str(v) if v is not None else "" for v in value)
                else:
                    return ""  # Skip arrays of objects
            else:
                return str(value)
        except Exception:
            return ""

    def _calculate_final_metrics(
        self,
        domain_result: Dict[str, Any],
        crawl_result: Optional[Dict[str, Any]],
        enrich_result: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Calculate final pipeline metrics."""
        duration_ms = (
            int((time.time() - self.start_time) * 1000) if self.start_time else 0
        )

        # Determine if this is Apollo or traditional mode
        lead_generation_mode = self._detect_lead_generation_mode()
        is_apollo_mode = lead_generation_mode == "apollo"

        if is_apollo_mode:
            # Apollo mode: domain_result is actually apollo_result
            apollo_result = domain_result

            # Aggregate cost metrics for Apollo mode
            total_apollo_cost = (
                apollo_result.get("metrics", {}).get("cost_usd", {}).get("apollo", 0.0)
            )
            total_crawl_cost = (
                crawl_result.get("metrics", {}).get("cost_usd", {}).get("crawl", 0.0)
                if crawl_result
                else 0.0
            )
            total_enrich_cost = (
                enrich_result.get("metrics", {}).get("cost_usd", {}).get("enrich", 0.0)
                if enrich_result
                else 0.0
            )

            # Count leads at each stage for Apollo mode
            apollo_count = len(apollo_result.get("data", {}).get("lead_records", []))
            crawl_count = (
                len(crawl_result.get("data", {}).get("lead_records", []))
                if crawl_result
                else 0
            )
            enrich_count = (
                len(enrich_result.get("data", {}).get("lead_records", []))
                if enrich_result
                else 0
            )

            # Calculate pass rates for Apollo mode
            apollo_pass_rate = apollo_result.get("metrics", {}).get("pass_rate")
            crawl_pass_rate = (
                crawl_result.get("metrics", {}).get("pass_rate")
                if crawl_result
                else None
            )
            enrich_pass_rate = (
                enrich_result.get("metrics", {}).get("pass_rate")
                if enrich_result
                else None
            )

            return {
                "duration_ms": duration_ms,
                "lead_counts": {
                    "apollo": apollo_count,
                    "crawl": crawl_count,
                    "enrich": enrich_count,
                },
                "pass_rates": {
                    "apollo": apollo_pass_rate,
                    "crawl": crawl_pass_rate,
                    "enrich": enrich_pass_rate,
                },
                "cost_usd": {
                    "apollo": round4(total_apollo_cost),
                    "crawl": round4(total_crawl_cost),
                    "enrich": round4(total_enrich_cost),
                    "total": round4(
                        total_apollo_cost + total_crawl_cost + total_enrich_cost
                    ),
                },
                "health": {"unknown_error_count": self.total_unknown_errors},
            }
        else:
            # Traditional mode: domain_result is actually domain_result
            # Aggregate cost metrics
            total_domain_cost = (
                domain_result.get("metrics", {}).get("cost_usd", {}).get("domain", 0.0)
            )
            total_crawl_cost = (
                crawl_result.get("metrics", {}).get("cost_usd", {}).get("crawl", 0.0)
                if crawl_result
                else 0.0
            )
            total_enrich_cost = (
                enrich_result.get("metrics", {}).get("cost_usd", {}).get("enrich", 0.0)
                if enrich_result
                else 0.0
            )

            # Count leads at each stage
            domain_count = len(domain_result.get("data", {}).get("lead_records", []))
            crawl_count = (
                len(crawl_result.get("data", {}).get("lead_records", []))
                if crawl_result
                else 0
            )
            enrich_count = (
                len(enrich_result.get("data", {}).get("lead_records", []))
                if enrich_result
                else 0
            )

            # Calculate pass rates
            domain_pass_rate = domain_result.get("metrics", {}).get("pass_rate")
            crawl_pass_rate = (
                crawl_result.get("metrics", {}).get("pass_rate")
                if crawl_result
                else None
            )
            enrich_pass_rate = (
                enrich_result.get("metrics", {}).get("pass_rate")
                if enrich_result
                else None
            )

            return {
                "duration_ms": duration_ms,
                "lead_counts": {
                    "domain": domain_count,
                    "crawl": crawl_count,
                    "enrich": enrich_count,
                },
                "pass_rates": {
                    "domain": domain_pass_rate,
                    "crawl": crawl_pass_rate,
                    "enrich": enrich_pass_rate,
                },
                "cost_usd": {
                    "domain": round4(total_domain_cost),
                    "crawl": round4(total_crawl_cost),
                    "enrich": round4(total_enrich_cost),
                    "total": round4(
                        total_domain_cost + total_crawl_cost + total_enrich_cost
                    ),
                },
                "health": {"unknown_error_count": self.total_unknown_errors},
            }

    def _build_error_metrics(self) -> Dict[str, Any]:
        """Build metrics for error cases."""
        duration_ms = (
            int((time.time() - self.start_time) * 1000) if self.start_time else 0
        )
        return {
            "duration_ms": duration_ms,
            "lead_counts": {"domain": 0, "crawl": 0, "enrich": 0},
            "pass_rates": {"domain": None, "crawl": None, "enrich": None},
            "cost_usd": {"domain": 0.0, "crawl": 0.0, "enrich": 0.0, "total": 0.0},
            "health": {"unknown_error_count": self.total_unknown_errors},
        }

    def _log_pipeline_summary(self, metrics: Dict[str, Any]) -> None:
        """Log pipeline completion summary."""
        duration_seconds = metrics["duration_ms"] / 1000

        # Determine if this is Apollo or traditional mode
        lead_generation_mode = self._detect_lead_generation_mode()
        is_apollo_mode = lead_generation_mode == "apollo"

        if is_apollo_mode:
            # Apollo mode summary
            apollo_per_hour = (
                (metrics["lead_counts"]["apollo"] / duration_seconds * 3600)
                if duration_seconds > 0
                else 0
            )
            cost_per_qualified = (
                (metrics["cost_usd"]["total"] / metrics["lead_counts"]["enrich"])
                if metrics["lead_counts"]["enrich"] > 0
                else 0
            )

            self.logger.info(f"Apollo pipeline completed in {duration_seconds:.2f}s")
            self.logger.info(
                f"Processed {metrics['lead_counts']['apollo']} Apollo leads, {metrics['lead_counts']['enrich']} enriched"
            )
            self.logger.info(f"Performance: {apollo_per_hour:.1f} Apollo leads/hour")
            self.logger.info(
                f"Cost: ${metrics['cost_usd']['total']:.4f} (${cost_per_qualified:.4f}/qualified lead)"
            )
            self.logger.info(
                f"Errors: {len(self.total_errors)} total, {self.total_unknown_errors} unknown"
            )
        else:
            # Traditional mode summary
            domains_per_hour = (
                (metrics["lead_counts"]["domain"] / duration_seconds * 3600)
                if duration_seconds > 0
                else 0
            )
            cost_per_qualified = (
                (metrics["cost_usd"]["total"] / metrics["lead_counts"]["enrich"])
                if metrics["lead_counts"]["enrich"] > 0
                else 0
            )

            self.logger.info(
                f"Traditional pipeline completed in {duration_seconds:.2f}s"
            )
            self.logger.info(
                f"Processed {metrics['lead_counts']['domain']} domains, {metrics['lead_counts']['enrich']} enriched"
            )
            self.logger.info(f"Performance: {domains_per_hour:.1f} domains/hour")
            self.logger.info(
                f"Cost: ${metrics['cost_usd']['total']:.4f} (${cost_per_qualified:.4f}/qualified lead)"
            )
            self.logger.info(
                f"Errors: {len(self.total_errors)} total, {self.total_unknown_errors} unknown"
            )

    def _validate_database_configuration(self) -> None:
        """Validate database mode configuration."""
        # Check if using new database configuration structure
        database_config = self.icp_config.get("database", {})

        if database_config:
            # New database configuration structure
            sites = database_config.get("sites", [])
            if not sites:
                raise ValueError(
                    "Database mode requires at least one site in 'database.sites'"
                )

            for i, site in enumerate(sites):
                if not site.get("base_domain"):
                    raise ValueError(f"Site {i} missing required 'base_domain'")
                if not site.get("specific_urls"):
                    raise ValueError(f"Site {i} missing required 'specific_urls'")
        else:
            # Legacy configuration structure - check for site_type and specific_urls
            site_type = self.icp_config.get("site_type")
            specific_urls = self.icp_config.get("specific_urls", [])

            if site_type == "information_database":
                if not specific_urls:
                    raise ValueError(
                        "Legacy database mode requires 'specific_urls' to be provided"
                    )
                self.logger.warning(
                    "⚠️ Using legacy database configuration. Consider migrating to lead_generation_mode='database' with database config section."
                )
            else:
                # Database mode detected but no proper configuration
                raise ValueError(
                    "Database mode requires either 'database' configuration section or legacy 'site_type=information_database' with 'specific_urls'"
                )

    def _create_lead_records_from_database_sites(self) -> List[Dict[str, Any]]:
        """Create lead records from database site configuration."""
        from src.common import now_z
        from urllib.parse import urlparse

        database_config = self.icp_config.get("database", {})
        lead_records = []

        if database_config:
            # New database configuration structure
            sites = database_config.get("sites", [])

            for site in sites:
                base_domain = site["base_domain"]
                specific_urls = site["specific_urls"]

                # Create one lead record per site (crawl tool will extract multiple companies)
                lead_record = {
                    "lead_id": f"database-site-{base_domain}",
                    "domain": base_domain,
                    "status": "scored",
                    "company": {"name": f"Database Site: {base_domain}"},
                    "contacts": [],
                    "provenance": {
                        "source": "database_mode",
                        "site_name": site["name"],
                        "discovery_mode": site.get("discovery_mode", "url_list"),
                        "created_at": now_z(),
                    },
                }
                lead_records.append(lead_record)
        else:
            # Legacy configuration structure - extract domain from specific_urls
            specific_urls = self.icp_config.get("specific_urls", [])

            if specific_urls:
                # Extract unique domains from specific URLs
                domains = set()
                for url in specific_urls:
                    parsed = urlparse(url)
                    domain = parsed.netloc.replace("www.", "")
                    domains.add(domain)

                # Create one lead record per unique domain
                for domain in domains:
                    lead_record = {
                        "lead_id": f"legacy-database-site-{domain}",
                        "domain": domain,
                        "status": "scored",
                        "company": {"name": f"Legacy Database Site: {domain}"},
                        "contacts": [],
                        "provenance": {
                            "source": "legacy_database_mode",
                            "site_name": f"Legacy Site: {domain}",
                            "discovery_mode": "url_list",
                            "created_at": now_z(),
                        },
                    }
                    lead_records.append(lead_record)

        self.logger.info(
            f"Created {len(lead_records)} lead records from database sites"
        )
        return lead_records

    def _filter_enrich_ready_leads(
        self, crawl_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Filter leads that are ready for enrichment."""
        lead_records = crawl_result.get("data", {}).get("lead_records", [])
        enrich_ready = [r for r in lead_records if r.get("status") == "enrich_ready"]
        self.logger.info(
            f"Filtered {len(enrich_ready)} leads ready for enrichment from {len(lead_records)} total"
        )
        return enrich_ready

    async def _run_enrich_tool(
        self, enrich_ready_leads: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Run enrichment tool on ready leads."""
        from src.enrich import run_enrich

        enrich_payload = {
            "lead_records": enrich_ready_leads,
            "icp_config": self.icp_config,
        }
        return await run_enrich(enrich_payload)

    def _build_database_pipeline_results(
        self, crawl_result: Dict[str, Any], enrich_result: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build final database pipeline results."""
        duration_seconds = time.time() - self.start_time if self.start_time else 0

        # Count extracted companies
        crawled_leads = crawl_result.get("data", {}).get("lead_records", [])
        companies_extracted = len(crawled_leads)
        companies_enriched = (
            len(enrich_result.get("data", {}).get("lead_records", []))
            if enrich_result
            else 0
        )

        # Build metrics
        metrics = {
            "pipeline_mode": "database",
            "duration_seconds": duration_seconds,
            "companies_extracted": companies_extracted,
            "companies_enriched": companies_enriched,
            "success_rate": (companies_enriched / companies_extracted)
            if companies_extracted > 0
            else 0,
            "lead_counts": {
                "database": companies_extracted,
                "enrich": companies_enriched,
            },
            "cost_usd": {
                "crawl": crawl_result.get("metrics", {})
                .get("cost_usd", {})
                .get("crawl", 0.0),
                "enrich": enrich_result.get("metrics", {})
                .get("cost_usd", {})
                .get("enrich", 0.0)
                if enrich_result
                else 0.0,
                "total": 0.0,
            },
        }
        metrics["cost_usd"]["total"] = (
            metrics["cost_usd"]["crawl"] + metrics["cost_usd"]["enrich"]
        )

        # Log summary
        self.logger.info(f"Database pipeline completed in {duration_seconds:.2f}s")
        self.logger.info(
            f"Extracted {companies_extracted} companies, enriched {companies_enriched}"
        )
        self.logger.info(f"Cost: ${metrics['cost_usd']['total']:.4f}")

        return {
            "success": True,
            "pipeline_mode": "database",
            "metrics": metrics,
            "data": {"crawl_result": crawl_result, "enrich_result": enrich_result},
            "errors": self.total_errors,
        }


# ============================================================================
# CLI Interface
# ============================================================================


async def main():
    """Main CLI entry point."""
    # Load environment variables from .env file
    load_dotenv()

    parser = argparse.ArgumentParser(description="Lead Sorcerer Orchestrator")
    parser.add_argument("--config", required=True, help="Path to icp_config.json")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Batch size for processing",
    )
    parser.add_argument("--data-dir", help="Override data directory")

    args = parser.parse_args()

    # Set data directory if provided
    if args.data_dir:
        os.environ["LEADPOET_DATA_DIR"] = args.data_dir

    try:
        # Initialize and run orchestrator
        orchestrator = LeadSorcererOrchestrator(args.config, args.batch_size)
        result = await orchestrator.run_pipeline()

        if result["success"]:
            print(json.dumps(result, indent=2))
            return 0
        else:
            print(json.dumps(result, indent=2))
            return 1
    except Exception as e:
        print(
            json.dumps({"error": str(e), "success": False}, indent=2), file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(asyncio.run(main()))
