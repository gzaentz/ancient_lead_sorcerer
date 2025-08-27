#!/usr/bin/env python3
"""
Contact Discovery Success Rate Optimization

This script implements optimizations to improve contact discovery
success rates from 80% to 90%+ through better error handling,
retry logic, and provider fallback strategies.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import random

logger = logging.getLogger(__name__)

class ProviderStatus(Enum):
    """Provider health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"

@dataclass
class ProviderHealth:
    """Track provider health metrics."""
    name: str
    status: ProviderStatus = ProviderStatus.HEALTHY
    success_count: int = 0
    failure_count: int = 0
    last_success: Optional[float] = None
    last_failure: Optional[float] = None
    consecutive_failures: int = 0
    rate_limit_reset: Optional[float] = None
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0
    
    @property
    def is_available(self) -> bool:
        """Check if provider is available for use."""
        if self.status == ProviderStatus.RATE_LIMITED:
            return self.rate_limit_reset is None or time.time() > self.rate_limit_reset
        return self.status in [ProviderStatus.HEALTHY, ProviderStatus.DEGRADED]

@dataclass  
class RetryConfig:
    """Configuration for retry logic."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True

class EnhancedContactDiscovery:
    """Enhanced contact discovery with optimized success rates."""
    
    def __init__(self):
        self.provider_health: Dict[str, ProviderHealth] = {}
        self.retry_config = RetryConfig()
        self.discovery_stats = {
            "total_attempts": 0,
            "successful_discoveries": 0,
            "failed_discoveries": 0,
            "retries_used": 0
        }
    
    def register_provider(self, provider_name: str):
        """Register a provider for health tracking."""
        if provider_name not in self.provider_health:
            self.provider_health[provider_name] = ProviderHealth(name=provider_name)
    
    async def discover_contacts_with_optimization(
        self, 
        domain: str, 
        providers: List[str],
        request_data: Dict[str, Any]
    ) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Discover contacts with optimized retry and fallback logic.
        
        Args:
            domain: Domain to discover contacts for
            providers: List of available provider names
            request_data: Request parameters
            
        Returns:
            Tuple of (success, contacts, provider_used)
        """
        self.discovery_stats["total_attempts"] += 1
        
        # Sort providers by health and success rate
        available_providers = self._get_optimal_provider_order(providers)
        
        if not available_providers:
            logger.error(f"No healthy providers available for {domain}")
            self.discovery_stats["failed_discoveries"] += 1
            return False, [], "no_providers_available"
        
        # Try each provider with retry logic
        for provider_name in available_providers:
            logger.info(f"Trying provider {provider_name} for {domain}")
            
            success, contacts, error = await self._try_provider_with_retry(
                provider_name, domain, request_data
            )
            
            if success:
                self._record_provider_success(provider_name)
                self.discovery_stats["successful_discoveries"] += 1
                logger.info(f"✅ Successfully discovered {len(contacts)} contacts for {domain} using {provider_name}")
                return True, contacts, provider_name
            else:
                self._record_provider_failure(provider_name, error)
                logger.warning(f"❌ Provider {provider_name} failed for {domain}: {error}")
                
                # Check if we should continue to next provider
                if self._should_continue_to_next_provider(error):
                    continue
                else:
                    break
        
        self.discovery_stats["failed_discoveries"] += 1
        logger.error(f"All providers failed for {domain}")
        return False, [], "all_providers_failed"
    
    async def _try_provider_with_retry(
        self, 
        provider_name: str, 
        domain: str, 
        request_data: Dict[str, Any]
    ) -> Tuple[bool, List[Dict[str, Any]], Optional[str]]:
        """Try a provider with retry logic."""
        for attempt in range(self.retry_config.max_attempts):
            try:
                # Simulate provider call (replace with actual implementation)
                result = await self._call_provider(provider_name, domain, request_data)
                
                if result["success"]:
                    if attempt > 0:
                        self.discovery_stats["retries_used"] += 1
                        logger.info(f"Provider {provider_name} succeeded on attempt {attempt + 1}")
                    return True, result["contacts"], None
                else:
                    error = result["error"]
                    if self._is_retryable_error(error):
                        if attempt < self.retry_config.max_attempts - 1:
                            delay = self._calculate_retry_delay(attempt)
                            logger.info(f"Retrying {provider_name} in {delay:.1f}s (attempt {attempt + 1})")
                            await asyncio.sleep(delay)
                            continue
                    return False, [], error
                    
            except Exception as e:
                error = str(e)
                if self._is_retryable_error(error) and attempt < self.retry_config.max_attempts - 1:
                    delay = self._calculate_retry_delay(attempt)
                    logger.info(f"Retrying {provider_name} after exception in {delay:.1f}s: {error}")
                    await asyncio.sleep(delay)
                    continue
                else:
                    return False, [], error
        
        return False, [], f"Max retries ({self.retry_config.max_attempts}) exceeded"
    
    async def _call_provider(self, provider_name: str, domain: str, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simulate provider call (replace with actual provider implementation).
        This is a mock implementation for testing.
        """
        # Simulate different provider behaviors
        provider_behaviors = {
            "apollo": {"success_rate": 0.9, "contact_count": 2},
            "anymail_finder": {"success_rate": 0.7, "contact_count": 1},
            "company_enrich": {"success_rate": 0.8, "contact_count": 3},
            "snovio": {"success_rate": 0.6, "contact_count": 1}
        }
        
        behavior = provider_behaviors.get(provider_name, {"success_rate": 0.5, "contact_count": 1})
        
        # Simulate network delay
        await asyncio.sleep(random.uniform(0.1, 0.5))
        
        # Simulate success/failure based on provider behavior
        if random.random() < behavior["success_rate"]:
            contacts = [
                {
                    "contact_id": f"{domain}_{provider_name}_{i}",
                    "full_name": f"Contact {i}",
                    "email": f"contact{i}@{domain}",
                    "role": "Manager"
                }
                for i in range(behavior["contact_count"])
            ]
            return {"success": True, "contacts": contacts}
        else:
            # Simulate different types of errors
            error_types = ["rate_limit", "network_error", "auth_error", "no_contacts"]
            error = random.choice(error_types)
            return {"success": False, "error": error, "contacts": []}
    
    def _get_optimal_provider_order(self, providers: List[str]) -> List[str]:
        """Sort providers by health and success rate."""
        # Register providers if not already registered
        for provider in providers:
            self.register_provider(provider)
        
        # Filter available providers and sort by success rate
        available = [
            (provider, self.provider_health[provider])
            for provider in providers
            if self.provider_health[provider].is_available
        ]
        
        # Sort by success rate (descending), then by consecutive failures (ascending)
        available.sort(
            key=lambda x: (x[1].success_rate, -x[1].consecutive_failures),
            reverse=True
        )
        
        return [provider for provider, _ in available]
    
    def _record_provider_success(self, provider_name: str):
        """Record a successful provider call."""
        health = self.provider_health[provider_name]
        health.success_count += 1
        health.last_success = time.time()
        health.consecutive_failures = 0
        
        # Update status based on success rate
        if health.success_rate >= 0.8:
            health.status = ProviderStatus.HEALTHY
        elif health.success_rate >= 0.5:
            health.status = ProviderStatus.DEGRADED
    
    def _record_provider_failure(self, provider_name: str, error: str):
        """Record a failed provider call."""
        health = self.provider_health[provider_name]
        health.failure_count += 1
        health.last_failure = time.time()
        health.consecutive_failures += 1
        
        # Update status based on error type and failure count
        if "rate_limit" in error.lower():
            health.status = ProviderStatus.RATE_LIMITED
            health.rate_limit_reset = time.time() + 300  # 5 minute cooldown
        elif health.consecutive_failures >= 3:
            health.status = ProviderStatus.FAILED
        elif health.success_rate < 0.5:
            health.status = ProviderStatus.DEGRADED
    
    def _is_retryable_error(self, error: str) -> bool:
        """Determine if an error is retryable."""
        retryable_errors = [
            "network_error",
            "timeout",
            "connection_error",
            "server_error",
            "rate_limit"  # After delay
        ]
        return any(retryable in error.lower() for retryable in retryable_errors)
    
    def _should_continue_to_next_provider(self, error: str) -> bool:
        """Determine if we should try the next provider."""
        # Don't try other providers for certain errors
        non_continuable_errors = [
            "auth_error",
            "invalid_domain",
            "blocked_domain"
        ]
        return not any(err in error.lower() for err in non_continuable_errors)
    
    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter."""
        delay = min(
            self.retry_config.base_delay * (self.retry_config.exponential_base ** attempt),
            self.retry_config.max_delay
        )
        
        if self.retry_config.jitter:
            delay = delay * (0.5 + random.random() * 0.5)  # Add 0-50% jitter
        
        return delay
    
    def get_provider_health_summary(self) -> Dict[str, Any]:
        """Get summary of provider health."""
        summary = {}
        for name, health in self.provider_health.items():
            summary[name] = {
                "status": health.status.value,
                "success_rate": health.success_rate,
                "consecutive_failures": health.consecutive_failures,
                "is_available": health.is_available,
                "total_calls": health.success_count + health.failure_count
            }
        return summary
    
    def get_discovery_stats(self) -> Dict[str, Any]:
        """Get discovery statistics."""
        total = self.discovery_stats["total_attempts"]
        success_rate = (
            self.discovery_stats["successful_discoveries"] / total
            if total > 0 else 0
        )
        
        return {
            **self.discovery_stats,
            "success_rate": success_rate,
            "average_retries": (
                self.discovery_stats["retries_used"] / total
                if total > 0 else 0
            )
        }

# Implementation patch for enrich_provider_router.py
def create_contact_discovery_patch():
    """
    Returns the patch to optimize contact discovery in enrich_provider_router.py
    """
    return '''
# Enhanced Contact Discovery Implementation
# Add this to the EnrichmentProviderRouter class:

def __init__(self, icp_config: Dict[str, Any], logger: logging.Logger):
    # ... existing initialization ...
    self.contact_discovery = EnhancedContactDiscovery()
    # Register all available providers
    for provider_name in self.providers.keys():
        self.contact_discovery.register_provider(provider_name)

async def get_all_domain_prospects_optimized(self, request: EnrichmentRequest) -> EnrichmentResult:
    """
    Optimized contact discovery with retry logic and provider health monitoring.
    """
    provider_names = list(self.providers.keys())
    
    success, contacts, provider_used = await self.contact_discovery.discover_contacts_with_optimization(
        domain=request.domain,
        providers=provider_names,
        request_data=request.__dict__
    )
    
    if success:
        return EnrichmentResult(
            success=True,
            data=contacts,
            provider=provider_used,
            error=None
        )
    else:
        return EnrichmentResult(
            success=False,
            data=[],
            provider=provider_used,
            error=f"All providers failed for {request.domain}"
        )

def get_provider_health_summary(self) -> Dict[str, Any]:
    """Get provider health summary."""
    return self.contact_discovery.get_provider_health_summary()

def get_discovery_stats(self) -> Dict[str, Any]:
    """Get discovery statistics."""
    return self.contact_discovery.get_discovery_stats()
'''

async def test_contact_discovery_optimization():
    """Test the enhanced contact discovery."""
    discovery = EnhancedContactDiscovery()
    
    # Test domains
    test_domains = [
        "example1.com",
        "example2.com",
        "example3.com",
        "example4.com",
        "example5.com"
    ]
    
    providers = ["apollo", "anymail_finder", "company_enrich", "snovio"]
    
    print("🧪 Testing Enhanced Contact Discovery")
    print("=" * 50)
    
    for domain in test_domains:
        print(f"\nTesting {domain}...")
        
        success, contacts, provider = await discovery.discover_contacts_with_optimization(
            domain=domain,
            providers=providers,
            request_data={"domain": domain}
        )
        
        status = "✅" if success else "❌"
        print(f"{status} {domain}: {len(contacts)} contacts via {provider}")
    
    # Print summary statistics
    print(f"\n📊 Discovery Statistics:")
    stats = discovery.get_discovery_stats()
    for key, value in stats.items():
        if key == "success_rate":
            print(f"   {key}: {value:.1%}")
        else:
            print(f"   {key}: {value}")
    
    print(f"\n🏥 Provider Health:")
    health = discovery.get_provider_health_summary()
    for provider, info in health.items():
        status_emoji = {"healthy": "🟢", "degraded": "🟡", "failed": "🔴", "rate_limited": "⏳"}
        emoji = status_emoji.get(info["status"], "❓")
        print(f"   {emoji} {provider}: {info['success_rate']:.1%} success, {info['total_calls']} calls")

if __name__ == "__main__":
    asyncio.run(test_contact_discovery_optimization())
