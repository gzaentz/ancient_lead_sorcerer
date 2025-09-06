"""
Enrichment Provider Router for Lead Sorcerer.

This module implements intelligent routing and fallback logic between enrichment providers
based on their tier assignments and availability. The router ensures high availability
and optimal cost management by automatically falling back to lower-tier providers
when higher-tier ones fail.

Authoritative specifications: BRD §333-336, §410-439
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from .enrich_providers.base import (
    BaseEnrichmentProvider,
    EnrichmentRequest,
    EnrichmentResult,
    ProviderTier,
)
from .enrich_providers import (
    CompanyEnrichProvider,
    AnymailFinderProvider,
    CoresignalProvider,
    SnovioProvider,
    ApolloEnrichProvider,
)


class EnrichmentProviderRouter:
    """
    Intelligent router for enrichment providers with automatic fallback logic.

    The router manages provider selection based on:
    - Provider tiers (TIER_0 = primary, TIER_1 = secondary, TIER_2 = legacy)
    - Provider availability and health status
    - Cost optimization and rate limiting
    - Automatic fallback on failures
    """

    def __init__(
        self,
        icp_config: Optional[Dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the enrichment provider router.

        Args:
            icp_config: ICP-specific configuration for provider tiers and preferences
                        (No ICP hard-coding - loaded from config files)
            logger: Optional logger instance to use for consistent logging
        """
        self.icp_config = icp_config or {}
        self.logger = logger or logging.getLogger("enrich")
        self.providers: Dict[ProviderTier, List[BaseEnrichmentProvider]] = {
            ProviderTier.TIER_0: [],
            ProviderTier.TIER_1: [],
            ProviderTier.TIER_2: [],
        }

        # Validate environment variables before initializing providers
        self._validate_environment_variables()

        # Initialize providers based on configuration
        self._initialize_providers()

        # Track provider health and performance
        self.provider_health: Dict[str, Dict[str, Any]] = {}
        self._update_health_tracking()

        self.logger.info("🔧 Enrichment provider router initialized")

    def _validate_environment_variables(self):
        """Validate that required environment variables are present."""
        required_vars = {
            "ANYMAIL_FINDER_API_KEY": "AnymailFinder contact discovery",
            "COMPANY_ENRICH_API_KEY": "CompanyEnrich company enrichment",
            "CORESIGNAL_API_TOKEN": "Coresignal fallback provider",
            "SNOVIO_CLIENT_ID": "Snov.io email discovery",
            "SNOVIO_CLIENT_SECRET": "Snov.io email discovery",
        }

        self.logger.info("🔍 Validating enrichment provider environment variables...")

        missing_vars = []
        available_providers = []

        for var, purpose in required_vars.items():
            if os.getenv(var):
                provider_name = purpose.split(" ")[0].lower()
                available_providers.append(provider_name)
                self.logger.info(f"✅ {var} is configured for {purpose}")
            else:
                missing_vars.append(f"{var} ({purpose})")
                self.logger.warning(
                    f"⚠️ {var} not configured - {purpose} will be unavailable"
                )

        if missing_vars:
            self.logger.warning(
                f"⚠️ Missing environment variables: {', '.join(missing_vars)}"
            )
            self.logger.warning("⚠️ Some enrichment providers will be unavailable")

        self.logger.info(
            f"✅ Available provider APIs: {', '.join(available_providers) if available_providers else 'None'}"
        )

    def _initialize_providers(self):
        """Initialize and categorize enrichment providers by tier."""
        self.logger.info("🔧 Initializing enrichment providers...")
        self.logger.info(f"📋 ICP config keys: {list(self.icp_config.keys())}")

        initialized_providers = {"tier_0": [], "tier_1": [], "tier_2": []}
        failed_providers = []

        # TIER_0: Primary providers (new, high-quality)
        # Note: Anymail Finder is initialized first for contact/email discovery priority
        if self._should_use_provider("anymail_finder", ProviderTier.TIER_0):
            try:
                self.providers[ProviderTier.TIER_0].append(AnymailFinderProvider())
                initialized_providers["tier_0"].append("AnymailFinder")
                self.logger.info("✅ AnymailFinder provider initialized successfully")
            except Exception as exc:
                failed_providers.append(f"AnymailFinder: {exc}")
                self.logger.warning(
                    f"⚠️ Failed to initialize AnymailFinder provider: {exc}"
                )

        if self._should_use_provider("company_enrich", ProviderTier.TIER_0):
            try:
                self.providers[ProviderTier.TIER_0].append(CompanyEnrichProvider())
                initialized_providers["tier_0"].append("CompanyEnrich")
                self.logger.info("✅ CompanyEnrich provider initialized successfully")
            except Exception as exc:
                failed_providers.append(f"CompanyEnrich: {exc}")
                self.logger.warning(
                    f"⚠️ Failed to initialize CompanyEnrich provider: {exc}"
                )

        # Apollo provider - only initialize if Apollo provider is enabled
        if self._should_use_apollo_provider():
            try:
                # Get Apollo provider configuration from enrichment_providers section
                enrichment_providers = self.icp_config.get("enrichment_providers", {})
                apollo_provider_config = enrichment_providers.get("apollo", {})

                # Fallback to apollo.enrich if enrichment_providers.apollo not configured
                if not apollo_provider_config:
                    apollo_provider_config = self.icp_config.get("apollo", {}).get(
                        "enrich", {}
                    )

                self.providers[ProviderTier.TIER_0].append(
                    ApolloEnrichProvider(apollo_provider_config)
                )
                initialized_providers["tier_0"].append("Apollo")
                self.logger.info(
                    "✅ Apollo enrichment provider initialized successfully"
                )
            except Exception as exc:
                failed_providers.append(f"Apollo: {exc}")
                self.logger.warning(
                    f"⚠️ Failed to initialize Apollo enrichment provider: {exc}"
                )

        # TIER_1: Secondary providers (legacy, reliable)
        if self._should_use_provider("coresignal", ProviderTier.TIER_1):
            try:
                self.providers[ProviderTier.TIER_1].append(CoresignalProvider())
                initialized_providers["tier_1"].append("Coresignal")
                self.logger.info("✅ Coresignal provider initialized successfully")
            except Exception as exc:
                failed_providers.append(f"Coresignal: {exc}")
                self.logger.warning(
                    f"⚠️ Failed to initialize Coresignal provider: {exc}"
                )

        if self._should_use_provider("snovio", ProviderTier.TIER_1):
            try:
                self.providers[ProviderTier.TIER_1].append(SnovioProvider())
                initialized_providers["tier_1"].append("Snov.io")
                self.logger.info("✅ Snov.io provider initialized successfully")
            except Exception as exc:
                failed_providers.append(f"Snov.io: {exc}")
                self.logger.warning(f"⚠️ Failed to initialize Snov.io provider: {exc}")

        # TIER_2: Legacy providers (last resort)
        # Currently no TIER_2 providers, but structure is ready for future use

        # Log initialization summary
        self.logger.info("📊 Provider initialization summary:")
        self.logger.info(
            f"   TIER_0: {len(self.providers[ProviderTier.TIER_0])} providers ({', '.join(initialized_providers['tier_0']) if initialized_providers['tier_0'] else 'None'})"
        )
        self.logger.info(
            f"   TIER_1: {len(self.providers[ProviderTier.TIER_1])} providers ({', '.join(initialized_providers['tier_1']) if initialized_providers['tier_1'] else 'None'})"
        )

        if failed_providers:
            self.logger.warning(
                f"⚠️ Failed to initialize {len(failed_providers)} providers: {'; '.join(failed_providers)}"
            )

        # Ensure we have at least one provider available
        total_providers = sum(len(providers) for providers in self.providers.values())
        if total_providers == 0:
            self.logger.warning(
                "❌ No providers available, attempting Coresignal fallback"
            )
            try:
                self.providers[ProviderTier.TIER_1].append(CoresignalProvider())
                self.logger.info(
                    "✅ Coresignal fallback provider initialized successfully"
                )
            except Exception as exc:
                self.logger.error(
                    f"❌ Failed to initialize Coresignal fallback provider: {exc}"
                )
                self.logger.error(
                    "❌ CRITICAL: No enrichment providers available - all enrichment operations will fail"
                )
        else:
            self.logger.info(
                f"✅ Router initialized with {total_providers} total providers across all tiers"
            )

    def _should_use_provider(self, provider_name: str, tier: ProviderTier) -> bool:
        """
        Determine if a provider should be used based on ICP configuration.

        Args:
            provider_name: Name of the provider to check
            tier: Tier level for the provider

        Returns:
            True if provider should be used, False otherwise
        """
        # Check ICP-specific provider preferences
        provider_config = self.icp_config.get("enrichment_providers", {})
        provider_settings = provider_config.get(provider_name, {})

        # Default to enabled unless explicitly disabled
        if "enabled" in provider_settings:
            return provider_settings["enabled"]

        # Check tier-specific settings
        tier_config = provider_config.get(f"tier_{tier.value}", {})
        if "enabled" in tier_config:
            return tier_config["enabled"]

        # Default behavior based on tier
        if tier == ProviderTier.TIER_0:
            return True  # Primary providers enabled by default
        elif tier == ProviderTier.TIER_1:
            return True  # Secondary providers enabled by default
        else:
            return False  # Legacy providers disabled by default

    def _should_use_apollo_provider(self) -> bool:
        """
        Determine if Apollo enrichment provider should be used.

        Apollo provider is enabled when:
        1. Apollo enrichment provider is explicitly enabled in enrichment_providers, OR
        2. Apollo-first mode is active (inherits Apollo capability)

        Returns:
            True if Apollo provider should be used, False otherwise
        """
        # Check explicit enrichment provider config (works in any mode)
        enrichment_providers = self.icp_config.get("enrichment_providers", {})
        apollo_enrichment_enabled = enrichment_providers.get("apollo", {}).get(
            "enabled", False
        )

        if apollo_enrichment_enabled:
            self.logger.info(
                "✅ Apollo enrichment provider enabled via enrichment_providers.apollo.enabled"
            )
            return True

        # Check Apollo-first mode (inherits Apollo enrichment capability)
        lead_generation_mode = self.icp_config.get("lead_generation_mode", "search")
        if lead_generation_mode == "apollo":
            apollo_config = self.icp_config.get("apollo", {})
            enrich_enabled = apollo_config.get("enrich", {}).get("enabled", False)
            if enrich_enabled:
                self.logger.info(
                    "✅ Apollo enrichment provider enabled via Apollo-first mode"
                )
                return True
            else:
                self.logger.warning(
                    "⚠️ Apollo-first mode enabled but apollo.enrich.enabled is False"
                )

        return False

    def _update_health_tracking(self):
        """Initialize health tracking for all providers."""
        for tier in self.providers:
            for provider in self.providers[tier]:
                self.provider_health[provider.name] = {
                    "is_available": True,
                    "error_count": 0,
                    "success_count": 0,
                    "last_error": None,
                    "last_success": None,
                    "average_latency": 0.0,
                    "total_cost": 0.0,
                }

    async def enrich_company(self, request: EnrichmentRequest) -> EnrichmentResult:
        """
        Enrich company information using provider fallback logic.

        Args:
            request: Enrichment request with domain

        Returns:
            Enrichment result with company data from best available provider
        """
        return await self._execute_with_fallback(
            "enrich_company", request, "company enrichment"
        )

    async def enrich_contacts(self, request: EnrichmentRequest) -> EnrichmentResult:
        """
        Enrich company contacts using provider fallback logic.

        Args:
            request: Enrichment request with domain

        Returns:
            Enrichment result with contact data from best available provider
        """
        return await self._execute_with_fallback(
            "enrich_contacts", request, "contact enrichment"
        )

    async def find_email(self, request: EnrichmentRequest) -> EnrichmentResult:
        """
        Find email address using provider fallback logic.

        Args:
            request: Enrichment request with domain, first_name, last_name

        Returns:
            Enrichment result with email data from best available provider
        """
        return await self._execute_with_fallback(
            "find_email", request, "email discovery"
        )

    async def validate_email(self, email: str) -> EnrichmentResult:
        """
        Validate email address using provider fallback logic.

        Args:
            email: Email address to validate

        Returns:
            Enrichment result with validation status from best available provider
        """
        # Create a request object for validation
        request = EnrichmentRequest(domain="", email=email)
        return await self._execute_with_fallback(
            "validate_email", request, "email validation"
        )

    async def get_all_domain_prospects(
        self, request: EnrichmentRequest
    ) -> EnrichmentResult:
        """
        Get all domain prospects using provider fallback logic.

        Args:
            request: Enrichment request with domain

        Returns:
            Enrichment result with prospects data from best available provider
        """
        return await self._execute_with_fallback(
            "discover_contacts", request, "contact discovery"
        )

    async def discover_contacts(self, request: EnrichmentRequest) -> EnrichmentResult:
        """
        Discover contacts for a domain using optimized provider methods.

        Args:
            request: Enrichment request with domain

        Returns:
            Enrichment result with discovered contacts from best available provider
        """
        return await self._execute_with_fallback(
            "discover_contacts", request, "contact discovery"
        )

    async def search_prospect_email(
        self, request: EnrichmentRequest
    ) -> EnrichmentResult:
        """
        Search for prospect email using provider fallback logic.

        Args:
            request: Enrichment request with prospect_hash

        Returns:
            Enrichment result with email data from best available provider
        """
        return await self._execute_with_fallback(
            "search_prospect_email", request, "prospect email search"
        )

    async def _execute_with_fallback(
        self, method_name: str, request: EnrichmentRequest, operation_description: str
    ) -> EnrichmentResult:
        """
        Execute enrichment operation with automatic provider fallback.

        Args:
            method_name: Name of the method to call on providers
            request: Enrichment request
            operation_description: Human-readable description of the operation

        Returns:
            Enrichment result from the first successful provider
        """
        errors = []

        # Try TIER_0 providers first (primary)
        for provider in self.providers[ProviderTier.TIER_0]:
            if not self._is_provider_healthy(provider):
                continue

            try:
                result = await getattr(provider, method_name)(request)
                if result.success:
                    self._record_success(provider, result)
                    # CRITICAL: Log which provider succeeded
                    self.logger.info(
                        f"✅ {provider.name} provider succeeded for {operation_description}"
                    )
                    self.logger.info(
                        f"📊 Provider response: {result.provider}, Cost: ${result.cost:.4f}"
                    )
                    if hasattr(result, "data") and result.data:
                        if isinstance(result.data, list):
                            self.logger.info(
                                f"📋 Data returned: {len(result.data)} items from {provider.name}"
                            )
                        elif hasattr(result.data, "email") and result.data.email:
                            self.logger.info(
                                f"📧 Email found via {provider.name}: {result.data.email}"
                            )
                        else:
                            self.logger.info(
                                f"📋 Data returned from {provider.name}: {type(result.data)}"
                            )
                    return result
                else:
                    self._record_error(provider, result.error)
                    errors.append(f"{provider.name}: {result.error}")
            except Exception as exc:
                self._record_error(provider, str(exc))
                errors.append(f"{provider.name}: {exc}")

        # Try TIER_1 providers (secondary/legacy)
        for provider in self.providers[ProviderTier.TIER_1]:
            if not self._is_provider_healthy(provider):
                continue

            try:
                result = await getattr(provider, method_name)(request)
                if result.success:
                    self._record_success(provider, result)
                    return result
                else:
                    self._record_error(provider, result.error)
                    errors.append(f"{provider.name}: {result.error}")
            except Exception as exc:
                self._record_error(provider, str(exc))
                errors.append(f"{provider.name}: {exc}")

        # Try TIER_2 providers (last resort)
        for provider in self.providers[ProviderTier.TIER_2]:
            if not self._is_provider_healthy(provider):
                continue

            try:
                result = await getattr(provider, method_name)(request)
                if result.success:
                    self._record_success(provider, result)
                    return result
                else:
                    self._record_error(provider, result.error)
                    errors.append(f"{provider.name}: {result.error}")
            except Exception as exc:
                self._record_error(provider, str(exc))
                errors.append(f"{provider.name}: {exc}")

        # All providers failed - ensure we have detailed error information
        if not errors:
            error_msg = f"No available providers for {operation_description} (all providers unavailable or failed health checks)"
        else:
            error_msg = f"All enrichment providers failed for {operation_description}: {'; '.join(errors)}"

        # Log detailed error information
        self.logger.error(f"❌ {error_msg}")

        # Log provider health status for debugging
        health_summary = self.get_provider_health_summary()
        self.logger.error(f"❌ Provider health summary: {health_summary}")

        return EnrichmentResult(
            success=False,
            error=error_msg,  # Ensure this is never None
            provider="router",
            cost=0.0,
        )

    def _is_provider_healthy(self, provider: BaseEnrichmentProvider) -> bool:
        """
        Check if a provider is healthy and available.

        Args:
            provider: Provider to check

        Returns:
            True if provider is healthy, False otherwise
        """
        health = self.provider_health.get(provider.name, {})

        # Check if provider is marked as unavailable
        if not health.get("is_available", True):
            return False

        # Check error threshold (mark as unavailable if too many errors)
        error_count = health.get("error_count", 0)
        success_count = health.get("success_count", 0)
        total_attempts = error_count + success_count

        if total_attempts > 10 and error_count / total_attempts > 0.8:
            self._mark_provider_unavailable(provider, "High error rate")
            return False

        return True

    def _record_success(
        self, provider: BaseEnrichmentProvider, result: EnrichmentResult
    ):
        """Record successful operation for a provider."""
        if provider.name not in self.provider_health:
            self.provider_health[provider.name] = {}

        health = self.provider_health[provider.name]
        health["success_count"] = health.get("success_count", 0) + 1
        health["last_success"] = asyncio.get_event_loop().time()
        health["is_available"] = True

        # Update cost tracking
        if result.cost:
            health["total_cost"] = health.get("total_cost", 0.0) + result.cost

    def _record_error(self, provider: BaseEnrichmentProvider, error: str):
        """Record failed operation for a provider."""
        if provider.name not in self.provider_health:
            self.provider_health[provider.name] = {}

        health = self.provider_health[provider.name]
        health["error_count"] = health.get("error_count", 0) + 1
        health["last_error"] = error

    def _mark_provider_unavailable(self, provider: BaseEnrichmentProvider, reason: str):
        """Mark a provider as temporarily unavailable."""
        if provider.name not in self.provider_health:
            self.provider_health[provider.name] = {}

        health = self.provider_health[provider.name]
        health["is_available"] = False
        health["last_error"] = f"Marked unavailable: {reason}"

        self.logger.warning(
            f"⚠️ Provider {provider.name} marked as unavailable: {reason}"
        )

    def get_provider_status(self) -> Dict[str, Any]:
        """
        Get current status of all providers.

        Returns:
            Dictionary with provider health and performance metrics
        """
        status = {
            "tier_0_providers": [],
            "tier_1_providers": [],
            "tier_2_providers": [],
            "overall_health": "healthy",
        }

        # Collect provider status by tier
        for tier in [ProviderTier.TIER_0, ProviderTier.TIER_1, ProviderTier.TIER_2]:
            tier_name = f"tier_{tier.value}_providers"
            for provider in self.providers[tier]:
                provider_status = {
                    "name": provider.name,
                    "tier": tier.value,
                    "is_available": self.provider_health.get(provider.name, {}).get(
                        "is_available", True
                    ),
                    "success_count": self.provider_health.get(provider.name, {}).get(
                        "success_count", 0
                    ),
                    "error_count": self.provider_health.get(provider.name, {}).get(
                        "error_count", 0
                    ),
                    "total_cost": self.provider_health.get(provider.name, {}).get(
                        "total_cost", 0.0
                    ),
                    "last_error": self.provider_health.get(provider.name, {}).get(
                        "last_error"
                    ),
                }
                status[tier_name].append(provider_status)

        # Determine overall health
        total_providers = sum(len(providers) for providers in self.providers.values())
        available_providers = sum(
            len([p for p in providers if self._is_provider_healthy(p)])
            for providers in self.providers.values()
        )

        if available_providers == 0:
            status["overall_health"] = "critical"
        elif available_providers < total_providers * 0.5:
            status["overall_health"] = "degraded"
        elif available_providers < total_providers:
            status["overall_health"] = "warning"
        else:
            status["overall_health"] = "healthy"

        return status

    def get_provider_health_summary(self) -> Dict[str, Any]:
        """Get comprehensive provider health summary for debugging."""
        summary = {
            "total_providers": 0,
            "available_providers": 0,
            "unhealthy_providers": [],
            "tier_status": {},
            "overall_status": "unknown",
        }

        for tier in self.providers:
            tier_name = f"tier_{tier.value}"
            tier_providers = self.providers[tier]
            summary["total_providers"] += len(tier_providers)

            healthy_count = sum(
                1 for p in tier_providers if self._is_provider_healthy(p)
            )
            unhealthy_providers = [
                p.name for p in tier_providers if not self._is_provider_healthy(p)
            ]

            summary["tier_status"][tier_name] = {
                "total": len(tier_providers),
                "healthy": healthy_count,
                "unhealthy": len(tier_providers) - healthy_count,
                "unhealthy_providers": unhealthy_providers,
            }
            summary["available_providers"] += healthy_count
            summary["unhealthy_providers"].extend(unhealthy_providers)

        # Determine overall status
        if summary["available_providers"] == 0:
            summary["overall_status"] = "critical"
        elif summary["available_providers"] < summary["total_providers"] * 0.5:
            summary["overall_status"] = "degraded"
        elif summary["available_providers"] < summary["total_providers"]:
            summary["overall_status"] = "warning"
        else:
            summary["overall_status"] = "healthy"

        return summary

    def reset_provider_health(self, provider_name: Optional[str] = None):
        """
        Reset health tracking for providers.

        Args:
            provider_name: Specific provider to reset, or None for all providers
        """
        if provider_name:
            if provider_name in self.provider_health:
                self.provider_health[provider_name] = {
                    "is_available": True,
                    "error_count": 0,
                    "success_count": 0,
                    "last_error": None,
                    "last_success": None,
                    "average_latency": 0.0,
                    "total_cost": 0.0,
                }
                self.logger.info(
                    f"🔄 Reset health tracking for provider: {provider_name}"
                )
        else:
            self._update_health_tracking()
            self.logger.info("🔄 Reset health tracking for all providers")


# Factory function for creating router instances
def create_enrichment_router(
    icp_config: Optional[Dict[str, Any]] = None, logger: Optional[logging.Logger] = None
) -> EnrichmentProviderRouter:
    """
    Factory function to create enrichment provider router instances.

    Args:
        icp_config: ICP-specific configuration for provider tiers and preferences
        logger: Optional logger instance for consistent logging

    Returns:
        Configured EnrichmentProviderRouter instance
    """
    return EnrichmentProviderRouter(icp_config, logger)
