"""
Enrich tool for Lead Sorcerer.

This tool enriches company and contact data using external APIs like Coresignal,
Snov.io, and Mailgun. It handles email validation, contact discovery, and
company data enrichment.

Authoritative specifications: BRD §333-336, §410-439
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from dotenv import load_dotenv

import httpx
from httpx import HTTPStatusError, TimeoutException
from openai import AsyncOpenAI
# import portalocker  # Removed due to Windows compatibility issues

from src.common import (
    ErrorCode,
    append_audit,
    append_status,
    build_error,
    build_metrics,
    get_email_status_rank,
    get_role_priority,
    get_seniority_rank,
    load_costs_config,
    load_schema_checksum,
    normalize_domain,
    now_z,
    parse_phone_number,
    recompute_total_cost,
    resolve_data_dir,
    setup_logging,
    truncate_evidence_arrays,
    validate_envelope,
    validate_testing_flags,
)

from src.enrich_provider_router import create_enrichment_router
from src.enrich_providers.base import EnrichmentRequest

# Load environment variables
load_dotenv()

# Debug: Show environment variable status without exposing sensitive data
# Note: This logging call is at module level and will use the default logger
# When called from orchestrator, it will use the shared logger
# ============================================================================
# Constants and Configuration
# ============================================================================

INTERNAL_VERSION = "1.0.0"
TOOL_NAME = "enrich"

# Email status ranking for best contact selection
EMAIL_STATUS_RANKS = {
    "valid": 0,
    "risky": 1,
    "catch_all": 2,
    "unknown": 3,
    "invalid": 4,
}

# Default timeout values
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 10.0
MAX_WALL_CLOCK = 45.0

# LLM Configuration for contact selection
LLM_MODEL = "gpt-4o-mini"
LLM_FALLBACK_MODEL = "gpt-3.5-turbo"
LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS = 500
LLM_TIMEOUT = 30.0
LLM_BASE_URL = "https://openrouter.ai/api/v1"

# Required fields for full enrichment (always enforced)
REQUIRED_COMPANY_FIELDS = [
    "name",
    "domain",
    "industry",
    "hq_location",
    "employee_count",
]

REQUIRED_CONTACT_FIELDS = [
    "full_name",  # or first_name + last_name
    "role",  # or job_title
    "email",
]

# LLM Configuration per ICP type (can be overridden in ICP config)
LLM_ICP_CONFIGS = {
    "default": {
        "model": LLM_MODEL,
        "fallback_model": LLM_FALLBACK_MODEL,
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_TOKENS,
        "timeout": LLM_TIMEOUT,
        "prompt_template": "base_contact_selection.txt",
    },
    "investment": {
        "model": "gpt-4o-mini",
        "fallback_model": "gpt-3.5-turbo",
        "temperature": 0.0,
        "max_tokens": 600,
        "timeout": 30.0,
        "prompt_template": "investment_contact_selection.txt",
    },
    "healthcare": {
        "model": "gpt-4o-mini",
        "fallback_model": "gpt-3.5-turbo",
        "temperature": 0.0,
        "max_tokens": 500,
        "timeout": 30.0,
        "prompt_template": "healthcare_contact_selection.txt",
    },
    "dental": {
        "model": "gpt-4o-mini",
        "fallback_model": "gpt-3.5-turbo",
        "temperature": 0.0,
        "max_tokens": 500,
        "timeout": 30.0,
        "prompt_template": "healthcare_contact_selection.txt",
    },
    "technology": {
        "model": "gpt-4o-mini",
        "fallback_model": "gpt-3.5-turbo",
        "temperature": 0.1,
        "max_tokens": 700,
        "timeout": 30.0,
        "prompt_template": "technology_contact_selection.txt",
    },
    "enterprise": {
        "model": "gpt-4o-mini",
        "fallback_model": "gpt-3.5-turbo",
        "temperature": 0.0,
        "max_tokens": 800,
        "timeout": 45.0,
        "prompt_template": "enterprise_contact_selection.txt",
    },
}

# Retry configuration
LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY = 1.0  # seconds

# Cache configuration
LLM_CACHE_TTL = 3600  # 1 hour in seconds
LLM_CACHE_MAX_SIZE = 1000  # Maximum number of cached responses
LLM_CACHE_MAX_CONTACT_LIST_SIZE = 20  # Maximum contact list size to cache

# Fallback monitoring configuration
FALLBACK_METRICS = {
    "llm_failures": 0,
    "llm_none_responses": 0,
    "invalid_contact_ids": 0,
    "total_fallbacks": 0,
}

# LLM performance monitoring
LLM_PERFORMANCE_METRICS = {
    "total_calls": 0,
    "successful_calls": 0,
    "failed_calls": 0,
    "timeout_errors": 0,
    "rate_limit_errors": 0,
    "server_errors": 0,
    "invalid_responses": 0,
    "fallback_to_rule_based": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "total_response_time_ms": 0,
    "average_response_time_ms": 0,
}


# ============================================================================
# Provider Clients
# ============================================================================


class LLMContactSelector:
    """LLM-based contact selection using OpenRouter."""

    def __init__(
        self,
        api_key: str,
        icp_type: str = "default",
        icp_config: Optional[Dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=LLM_BASE_URL)

        # Set up logger - use provided logger or get the enrich logger
        self.logger = logger or logging.getLogger("enrich")

        # Get configuration for this ICP type with potential overrides
        if icp_config:
            config = get_icp_llm_config(icp_type, icp_config)
        else:
            config = LLM_ICP_CONFIGS.get(icp_type, LLM_ICP_CONFIGS["default"])

        self.primary_model = config["model"]
        self.fallback_model = config["fallback_model"]
        self.temperature = config["temperature"]
        self.max_tokens = config["max_tokens"]
        self.timeout = config["timeout"]
        self.icp_type = icp_type
        self.prompt_template = config.get(
            "prompt_template", "base_contact_selection.txt"
        )

        # Initialize cache
        self._cache = {}
        self._cache_timestamps = {}

        # Initialize cost tracking
        self.total_cost = 0.0
        self.cost_details = []

    async def select_contact(
        self,
        contacts: List[Dict[str, Any]],
        icp_config: Dict[str, Any],
        role_priority_config: Optional[Dict[str, int]] = None,
    ) -> Optional[str]:
        """
        Select best contact using LLM.

        Args:
            contacts: List of contacts to choose from
            icp_config: ICP configuration with business context

        Returns:
            Contact ID of best contact or None if LLM fails
        """
        # Check cache first
        cache_key = self._generate_cache_key(contacts, icp_config)
        cached_result = self._get_cached_result(cache_key)
        if cached_result is not None:
            self.logger.info("💾 Using cached LLM result for contact selection")
            track_llm_performance_metric("cache_hits")
            return cached_result

        track_llm_performance_metric("cache_misses")

        prompt = self._build_contact_selection_prompt(
            contacts, icp_config, role_priority_config
        )

        # Try with retries
        for attempt in range(LLM_MAX_RETRIES):
            try:
                start_time = time.time()
                track_llm_performance_metric("total_calls")

                # Try primary model first
                try:
                    response = await self.client.chat.completions.create(
                        model=self.primary_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        timeout=self.timeout,
                    )
                    model_used = self.primary_model
                except Exception:
                    # Fallback to secondary model
                    response = await self.client.chat.completions.create(
                        model=self.fallback_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        timeout=self.timeout,
                    )
                    model_used = self.fallback_model

                content = response.choices[0].message.content.strip()

                # Track response time
                response_time_ms = int((time.time() - start_time) * 1000)
                track_llm_performance_metric("total_response_time_ms", response_time_ms)

                # Track LLM costs
                cost_info = self._track_llm_costs(response, model_used)
                self.total_cost += cost_info["cost_usd"]
                self.cost_details.append(cost_info)

                # Parse and validate response
                contact_id = extract_contact_id(content, contacts, self.logger)
                if contact_id:
                    # Track successful call
                    track_llm_performance_metric("successful_calls")

                    # Log successful LLM call
                    self._log_llm_call(prompt, content, model_used, True)
                    self.logger.info(
                        f"✅ LLM ({model_used}) selected contact {contact_id}"
                    )

                    # Cache the successful result
                    self._cache_result(cache_key, contact_id)

                    return contact_id
                else:
                    # Track invalid response
                    track_llm_performance_metric("invalid_responses")

                    # Log failed LLM call
                    self._log_llm_call(prompt, content, model_used, False)
                    self.logger.warning(
                        f"⚠️ LLM ({model_used}) returned invalid response, falling back to rule-based"
                    )
                    return None

            except TimeoutException:
                track_llm_performance_metric("timeout_errors")
                self.logger.warning(
                    f"⏰ LLM request timed out (attempt {attempt + 1}/{LLM_MAX_RETRIES})"
                )
                if attempt < LLM_MAX_RETRIES - 1:
                    await asyncio.sleep(
                        LLM_RETRY_DELAY * (2**attempt)
                    )  # Exponential backoff
                    continue
                else:
                    self.logger.error("⏰ LLM request timed out after all retries")
                    return None

            except HTTPStatusError as e:
                if e.response.status_code == 429:
                    track_llm_performance_metric("rate_limit_errors")
                    self.logger.warning(
                        f"🚫 LLM rate limit exceeded (attempt {attempt + 1}/{LLM_MAX_RETRIES})"
                    )
                    if attempt < LLM_MAX_RETRIES - 1:
                        await asyncio.sleep(
                            LLM_RETRY_DELAY * (2**attempt)
                        )  # Exponential backoff
                        continue
                    else:
                        self.logger.error(
                            "🚫 LLM rate limit exceeded after all retries"
                        )
                        return None
                elif e.response.status_code >= 500:
                    track_llm_performance_metric("server_errors")
                    self.logger.warning(
                        f"🔧 LLM server error: {e.response.status_code} (attempt {attempt + 1}/{LLM_MAX_RETRIES})"
                    )
                    if attempt < LLM_MAX_RETRIES - 1:
                        await asyncio.sleep(
                            LLM_RETRY_DELAY * (2**attempt)
                        )  # Exponential backoff
                        continue
                    else:
                        self.logger.error(
                            f"🔧 LLM server error after all retries: {e.response.status_code}"
                        )
                        return None
                else:
                    track_llm_performance_metric("failed_calls")
                    self.logger.error(f"❌ LLM HTTP error: {e.response.status_code}")
                    return None

            except Exception as e:
                track_llm_performance_metric("failed_calls")
                self.logger.warning(
                    f"❌ LLM contact selection failed (attempt {attempt + 1}/{LLM_MAX_RETRIES}): {str(e)}"
                )
                if attempt < LLM_MAX_RETRIES - 1:
                    await asyncio.sleep(
                        LLM_RETRY_DELAY * (2**attempt)
                    )  # Exponential backoff
                    continue
                else:
                    self.logger.error(
                        f"❌ LLM contact selection failed after all retries: {str(e)}"
                    )
                    return None

        return None

    def _track_llm_costs(self, response, model_used: str) -> Dict[str, Any]:
        """
        Track LLM costs for monitoring and billing.

        Args:
            response: OpenAI API response
            model_used: Model that was used

        Returns:
            Dictionary with cost and usage information
        """
        try:
            usage = response.usage
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            total_tokens = usage.total_tokens

            # Calculate cost based on OpenRouter pricing (configured in costs.yaml)
            # Standard rate: $0.002 per 1k tokens
            cost_per_1k_tokens = (
                0.002  # This should match costs.yaml openrouter.usd_per_unit
            )
            cost_usd = (total_tokens / 1000.0) * cost_per_1k_tokens

            # Build cost tracking information
            cost_info = {
                "model": model_used,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
            }

            # Log cost information
            self.logger.info(
                f"💰 LLM costs - Model: {model_used}, "
                f"Prompt: {prompt_tokens}, Completion: {completion_tokens}, "
                f"Total: {total_tokens} tokens, Cost: ${cost_usd:.4f}"
            )

            return cost_info

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to track LLM costs: {str(e)}")
            return {
                "model": model_used,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
            }

    def _log_llm_call(self, prompt: str, response: str, model_used: str, success: bool):
        """
        Log LLM call details for monitoring and debugging.

        Args:
            prompt: The prompt sent to LLM
            response: The response from LLM
            model_used: Model that was used
            success: Whether the call was successful
        """
        try:
            # Redact PII from prompt and response for logging
            redacted_prompt = self._redact_pii(prompt)
            redacted_response = self._redact_pii(response)

            # Analyze response quality for monitoring
            quality_metrics = analyze_llm_response_quality(response)

            log_data = {
                "model": model_used,
                "success": success,
                "prompt_length": len(prompt),
                "response_length": len(response),
                "quality_score": quality_metrics["format_compliance"],
                "quality_issues": quality_metrics["issues"],
                "timestamp": time.time(),
            }

            if success:
                self.logger.info(f"📝 LLM call successful - {log_data}")
                self.logger.debug(f"🔍 LLM prompt: {redacted_prompt}")
                self.logger.debug(f"🔍 LLM response: {redacted_response}")

                # Log quality metrics for successful calls
                if quality_metrics["format_compliance"] < 1.0:
                    self.logger.warning(
                        f"⚠️ LLM response quality issues: {quality_metrics['issues']}"
                    )
                else:
                    self.logger.info(
                        f"✅ LLM response quality: {quality_metrics['format_compliance']:.2f}"
                    )
            else:
                self.logger.warning(f"📝 LLM call failed - {log_data}")
                self.logger.debug(f"🔍 LLM prompt: {redacted_prompt}")

                # Log quality metrics for failed calls
                self.logger.warning(
                    f"❌ LLM response quality issues: {quality_metrics['issues']}"
                )

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to log LLM call: {str(e)}")

    def _generate_cache_key(
        self, contacts: List[Dict[str, Any]], icp_config: Dict[str, Any]
    ) -> str:
        """
        Generate cache key for contacts and ICP config.
        Guards against very large contact lists by not caching them.

        Args:
            contacts: List of contacts
            icp_config: ICP configuration

        Returns:
            Cache key string or empty string if list is too large
        """
        try:
            # Guard against very large contact lists
            if len(contacts) > LLM_CACHE_MAX_CONTACT_LIST_SIZE:
                self.logger.info(
                    f"📏 Contact list too large for caching ({len(contacts)} > {LLM_CACHE_MAX_CONTACT_LIST_SIZE}), skipping cache"
                )
                return ""

            # Create a hash of the contacts and ICP config
            import hashlib

            # Extract key fields for caching (limit to first 10 contacts)
            contact_data = []
            for contact in contacts[:10]:
                contact_data.append(
                    {
                        "contact_id": contact.get("contact_id"),
                        "role": contact.get("role") or contact.get("job_title"),
                        "seniority": contact.get("seniority"),
                        "company": contact.get("company"),
                    }
                )

            # Create cache key from contacts and ICP config
            cache_data = {
                "contacts": sorted(contact_data, key=lambda x: x.get("contact_id", "")),
                "icp_type": icp_config.get("icp_type", "default"),
                "icp_text_hash": hashlib.md5(
                    icp_config.get("icp_text", "").encode()
                ).hexdigest()[:8],
            }

            return hashlib.sha256(
                json.dumps(cache_data, sort_keys=True).encode()
            ).hexdigest()

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to generate cache key: {str(e)}")
            return ""

    def _get_cached_result(self, cache_key: str) -> Optional[str]:
        """
        Get cached result if available and not expired.

        Args:
            cache_key: Cache key

        Returns:
            Cached contact ID or None
        """
        if not cache_key:
            return None

        try:
            if cache_key in self._cache:
                timestamp = self._cache_timestamps.get(cache_key, 0)
                if time.time() - timestamp < LLM_CACHE_TTL:
                    return self._cache[cache_key]
                else:
                    # Remove expired cache entry
                    del self._cache[cache_key]
                    del self._cache_timestamps[cache_key]

            return None

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to get cached result: {str(e)}")
            return None

    def _cache_result(self, cache_key: str, contact_id: str):
        """
        Cache the result for future use.

        Args:
            cache_key: Cache key
            contact_id: Contact ID to cache
        """
        if not cache_key:
            return

        try:
            self._cache[cache_key] = contact_id
            self._cache_timestamps[cache_key] = time.time()

            # Clean up old cache entries
            self._cleanup_cache()

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to cache result: {str(e)}")

    def _cleanup_cache(self):
        """Clean up expired cache entries and enforce size limits."""
        try:
            current_time = time.time()

            # Remove expired entries
            expired_keys = [
                key
                for key, timestamp in self._cache_timestamps.items()
                if current_time - timestamp > LLM_CACHE_TTL
            ]

            for key in expired_keys:
                del self._cache[key]
                del self._cache_timestamps[key]

            # Enforce cache size limit (remove oldest entries if needed)
            if len(self._cache) > LLM_CACHE_MAX_SIZE:
                # Sort by timestamp and remove oldest entries
                sorted_items = sorted(
                    self._cache_timestamps.items(),
                    key=lambda x: x[1],  # Sort by timestamp
                )

                # Remove oldest entries until we're under the limit
                entries_to_remove = len(self._cache) - LLM_CACHE_MAX_SIZE
                for i in range(entries_to_remove):
                    key_to_remove = sorted_items[i][0]
                    del self._cache[key_to_remove]
                    del self._cache_timestamps[key_to_remove]

                self.logger.info(
                    f"🧹 Cache size limit enforced, removed {entries_to_remove} oldest entries"
                )

        except Exception as e:
            self.logger.warning(f"⚠️ Failed to cleanup cache: {str(e)}")

    def get_cost_info(self) -> Dict[str, Any]:
        """
        Get cost information for this LLM session.

        Returns:
            Dictionary with total cost and detailed breakdown
        """
        return {
            "total_cost_usd": self.total_cost,
            "cost_details": self.cost_details.copy(),
            "total_calls": len(self.cost_details),
            "total_tokens": sum(detail["total_tokens"] for detail in self.cost_details),
        }

    def _redact_pii(self, text: str) -> str:
        """
        Redact PII from text for safe logging.

        Args:
            text: Text to redact

        Returns:
            Redacted text
        """
        # Simple PII redaction - replace emails and phone numbers

        # Redact email addresses
        text = re.sub(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL]", text
        )

        # Redact phone numbers
        text = re.sub(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[PHONE]", text)

        # Redact names (simple heuristic)
        text = re.sub(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", "[NAME]", text)

        return text

    def _build_contact_selection_prompt(
        self,
        contacts: List[Dict[str, Any]],
        icp_config: Dict[str, Any],
        role_priority_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Build prompt for contact selection with role priorities and business context.

        Args:
            contacts: List of contacts
            icp_config: ICP configuration
            role_priority_config: Optional role priority configuration

        Returns:
            Formatted prompt string
        """
        icp_text = icp_config.get("icp_text", "General business contacts")
        icp_type = icp_config.get("icp_type", "default")

        # Format contacts for LLM consumption with role priorities
        formatted_contacts = format_contacts_for_llm(contacts, role_priority_config)

        # Add role priority context to the prompt if available
        role_context = ""
        if role_priority_config:
            high_priority_roles = [
                role for role, priority in role_priority_config.items() if priority <= 2
            ]
            if high_priority_roles:
                role_context = (
                    f"\nHigh Priority Roles: {', '.join(high_priority_roles[:5])}"
                )

        # Load and use prompt template from file
        try:
            template = load_prompt_template(self.prompt_template)
            prompt = template.replace("{icp_text}", icp_text)
            prompt = prompt.replace("{contacts}", formatted_contacts)
            prompt = prompt.replace("{role_context}", role_context)
            return prompt
        except Exception as e:
            self.logger.warning(
                f"⚠️ Failed to load prompt template, using fallback: {str(e)}"
            )
            return self._get_fallback_prompt(
                icp_text, formatted_contacts, icp_type, role_context
            )

    def _get_fallback_prompt(
        self,
        icp_text: str,
        formatted_contacts: str,
        icp_type: str,
        role_context: str = "",
    ) -> str:
        """
        Get fallback prompt when template loading fails.

        Args:
            icp_text: ICP description
            formatted_contacts: Formatted contact list
            icp_type: Type of ICP
            role_context: Role priority context

        Returns:
            Fallback prompt string
        """
        # Fallback to hardcoded prompts if template files are not available
        if icp_type == "investment":
            return f"""ICP: {icp_text}

Select the BEST contact who can actually allocate capital or make investment decisions. Prioritize:
- Family office decision makers
- Investment fund founders/managers
- Capital allocators with crypto exposure
- HNW individuals with investment capacity
- Portfolio managers and analysts

AVOID: Marketing executives, consultants, or people without investment decision-making power.
{role_context}

Contacts:
{formatted_contacts}

Return ONLY a JSON response in this exact format:
{{ "contact_id": "123" }}"""

        elif icp_type == "healthcare" or icp_type == "dental":
            return f"""ICP: {icp_text}

Select the BEST contact who can make healthcare business decisions or allocate resources. Prioritize:
- Practice owners and administrators
- Medical directors and CMOs
- Healthcare executives and managers
- Decision makers in healthcare organizations

AVOID: Marketing executives, consultants, or people without healthcare decision-making power.
{role_context}

Contacts:
{formatted_contacts}

Return ONLY a JSON response in this exact format:
{{ "contact_id": "123" }}"""

        else:
            # Default prompt for other ICP types
            return f"""ICP: {icp_text}

Select the BEST contact who can actually make business decisions or allocate resources. Prioritize:
- Decision makers and executives
- People with budget authority
- Senior managers and directors
- Business owners and founders

AVOID: Marketing executives, consultants, or people without decision-making power.
{role_context}

Contacts:
{formatted_contacts}

Return ONLY a JSON response in this exact format:
{{ "contact_id": "123" }}"""


class MailgunClient:
    """Client for Mailgun SMTP validation."""

    def __init__(self, smtp_login: str, smtp_password: str):
        self.smtp_login = smtp_login
        self.smtp_password = smtp_password
        self.base_url = "https://api.mailgun.net/v3"
        self.domain = smtp_login.split("@")[1] if "@" in smtp_login else None

    async def validate_email(self, email: str) -> Dict[str, Any]:
        """
        Validate email address using Mailgun.

        Args:
            email: Email address to validate

        Returns:
            Validation result with status and confidence
        """
        url = f"{self.base_url}/address/validate"
        params = {"address": email, "api_key": self.smtp_password}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=None, pool=None
            )
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()


class HunterIOClient:
    """Client for Hunter.io email verification with rate limiting, caching, comprehensive logging, and enhanced error handling."""

    def __init__(
        self, api_key: str, cache_ttl_hours: int = 24, max_cache_size: int = 10000
    ):
        self.api_key = api_key
        self.base_url = "https://api.hunter.io/v2"
        # Rate limit: 10 requests/second per Hunter.io docs
        self.rate_limiter = asyncio.Semaphore(10)
        self.request_count = 0
        self.total_cost = 0.0

        # Performance optimization: In-memory cache for verification results
        self.cache = {}
        self.cache_ttl_hours = cache_ttl_hours
        self.max_cache_size = max_cache_size
        self.cache_hits = 0
        self.cache_misses = 0

        # Performance monitoring
        self.total_response_time = 0.0
        self.avg_response_time = 0.0
        self.min_response_time = float("inf")
        self.max_response_time = 0.0

        # Enhanced error handling and retry configuration
        self.max_retries = 3
        self.base_delay = 1.0  # Base delay in seconds
        self.max_delay = 60.0  # Maximum delay in seconds
        self.retry_count = 0
        self.total_retries = 0
        self.failed_requests = 0
        self.rate_limit_hits = 0
        self.timeout_errors = 0
        self.authentication_errors = 0
        self.server_errors = 0

    def _calculate_backoff_delay(self, attempt: int) -> float:
        """
        Calculate exponential backoff delay with jitter.

        Args:
            attempt: Current retry attempt (0-based)

        Returns:
            Delay in seconds
        """
        if attempt == 0:
            return 0

        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_delay * (2 ** (attempt - 1))

        # Add jitter (±25% random variation)
        import random

        jitter = random.uniform(0.75, 1.25)
        delay *= jitter

        # Cap at maximum delay
        return min(delay, self.max_delay)

    def _should_retry(self, status_code: int, error: Exception) -> bool:
        """
        Determine if a request should be retried based on error type and status code.

        Args:
            status_code: HTTP status code
            error: Exception that occurred

        Returns:
            True if request should be retried
        """
        # Always retry on rate limits
        if status_code == 429:
            return True

        # Retry on server errors (5xx)
        if status_code >= 500:
            return True

        # Retry on timeouts
        if isinstance(error, httpx.TimeoutException):
            return True

        # Retry on connection errors
        if isinstance(error, (httpx.ConnectError, httpx.ReadError)):
            return True

        # Don't retry on client errors (4xx except 429)
        if 400 <= status_code < 500 and status_code != 429:
            return False

        # Don't retry on authentication errors
        if status_code == 401:
            return False

        # For errors with no status code, retry based on error type
        if status_code == 0 and error:
            if isinstance(error, httpx.TimeoutException):
                return True
            if isinstance(error, (httpx.ConnectError, httpx.ReadError)):
                return True

        return False

    async def verify_email(
        self, email: str, logger: Optional[logging.Logger] = None
    ) -> Dict[str, Any]:
        """
        Verify email using Hunter.io API with comprehensive error handling and caching.

        Args:
            email: Email address to verify
            logger: Optional logger instance

        Returns:
            {
                "score": 85,
                "status": "valid",
                "result": "deliverable",
                "sources": [...],
                "api_calls": 1,
                "error": None,
                "verified_at": "2025-08-27T19:01:20Z",
                "cost_usd": 0.002
            }
        """
        log = logger or logging.getLogger("enrich")

        if not email or not isinstance(email, str):
            return {
                "score": 0,
                "status": "invalid",
                "error": "Invalid email format",
                "api_calls": 0,
                "cost_usd": 0.0,
            }

        # Check cache first
        cache_key = self._get_cache_key(email)
        if cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if self._is_cache_valid(cache_entry):
                self.cache_hits += 1
                log.info(
                    f"🚀 Hunter.io: Cache HIT for {email} (score: {cache_entry['score']}%)"
                )
                return cache_entry
            else:
                # Remove expired cache entry
                del self.cache[cache_key]

        self.cache_misses += 1
        log.info(f"🔍 Hunter.io: Starting verification for {email}")

        start_time = time.time()

        # Enhanced retry logic with exponential backoff
        last_status_code = None

        for attempt in range(self.max_retries + 1):
            try:
                async with self.rate_limiter:
                    url = f"{self.base_url}/email-verifier"
                    params = {"email": email, "api_key": self.api_key}

                    # Add retry attempt info to log
                    if attempt > 0:
                        log.info(
                            f"🔄 Hunter.io: Retry attempt {attempt}/{self.max_retries} for {email}"
                        )
                        self.total_retries += 1

                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(
                            30.0, connect=3.0, read=10.0, write=5.0, pool=5.0
                        )
                    ) as client:
                        response = await client.get(url, params=params)
                        last_status_code = response.status_code

                        # Handle different HTTP status codes with appropriate error categorization
                        if response.status_code == 401:
                            self.authentication_errors += 1
                            log.error(
                                "🚨 Hunter.io authentication failed - check API key"
                            )
                            result = {
                                "email": email,
                                "score": 0,
                                "status": "error",
                                "error": "Authentication failed",
                                "api_calls": 1,
                                "cost_usd": 0.002,
                                "retry_attempts": attempt,
                                "http_status": response.status_code,
                            }
                            break  # Don't retry authentication errors

                        elif response.status_code == 429:
                            self.rate_limit_hits += 1
                            log.warning(
                                f"⚠️ Hunter.io rate limit exceeded for {email} (attempt {attempt + 1})"
                            )

                            # Calculate backoff delay for rate limits
                            if attempt < self.max_retries:
                                delay = self._calculate_backoff_delay(attempt + 1)
                                log.info(
                                    f"⏳ Hunter.io: Waiting {delay:.1f}s before retry due to rate limit"
                                )
                                await asyncio.sleep(delay)
                                continue
                            else:
                                result = {
                                    "email": email,
                                    "score": 0,
                                    "status": "rate_limited",
                                    "error": "Rate limit exceeded after all retries",
                                    "api_calls": 1,
                                    "cost_usd": 0.002,
                                    "retry_attempts": attempt,
                                    "http_status": response.status_code,
                                }
                                break

                        elif response.status_code >= 500:
                            self.server_errors += 1
                            log.warning(
                                f"🔧 Hunter.io server error {response.status_code} for {email} (attempt {attempt + 1})"
                            )

                            if attempt < self.max_retries and self._should_retry(
                                response.status_code, None
                            ):
                                delay = self._calculate_backoff_delay(attempt + 1)
                                log.info(
                                    f"⏳ Hunter.io: Waiting {delay:.1f}s before retry due to server error"
                                )
                                await asyncio.sleep(delay)
                                continue
                            else:
                                result = {
                                    "email": email,
                                    "score": 0,
                                    "status": "error",
                                    "error": f"Server error {response.status_code}",
                                    "api_calls": 1,
                                    "cost_usd": 0.002,
                                    "retry_attempts": attempt,
                                    "http_status": response.status_code,
                                }
                                break

                        else:
                            # Success case
                            response.raise_for_status()
                            data = response.json()
                            hunter_data = data.get("data", {})

                            # Extract Hunter.io response
                            result = {
                                "email": email,
                                "score": hunter_data.get("score", 0),
                                "status": hunter_data.get("status", "unknown"),
                                "result": hunter_data.get("result", "unknown"),
                                "sources": hunter_data.get("sources", []),
                                "api_calls": 1,
                                "error": None,
                                "verified_at": now_z(),
                                "cost_usd": 0.002,
                                "retry_attempts": attempt,
                                "http_status": response.status_code,
                            }

                            # Update performance metrics
                            response_time = time.time() - start_time
                            self.total_response_time += response_time
                            self.avg_response_time = self.total_response_time / max(
                                self.request_count, 1
                            )
                            self.min_response_time = min(
                                self.min_response_time, response_time
                            )
                            self.max_response_time = max(
                                self.max_response_time, response_time
                            )

                            # Cache the result
                            cache_entry = result.copy()
                            cache_entry["cached_at"] = now_z()
                            self.cache[cache_key] = cache_entry

                            # Cleanup cache if needed
                            if len(self.cache) > self.max_cache_size:
                                self._cleanup_cache()

                            self.request_count += 1
                            self.total_cost += result["cost_usd"]

                            log.info(
                                f"📊 Hunter.io Results for {email}: Score={result['score']}%, Status={result['status']}, Result={result['result']}, Response time: {response_time:.3f}s, Attempts: {attempt + 1}"
                            )

                            return result

            except httpx.TimeoutException as e:
                self.timeout_errors += 1
                log.warning(f"⏰ Hunter.io timeout for {email} (attempt {attempt + 1})")

                if attempt < self.max_retries and self._should_retry(0, e):
                    delay = self._calculate_backoff_delay(attempt + 1)
                    log.info(
                        f"⏳ Hunter.io: Waiting {delay:.1f}s before retry due to timeout"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    result = {
                        "email": email,
                        "score": 0,
                        "status": "timeout",
                        "error": "Request timeout after all retries",
                        "api_calls": 1,
                        "cost_usd": 0.002,
                        "retry_attempts": attempt,
                        "http_status": last_status_code,
                    }
                    break

            except httpx.HTTPStatusError as e:
                log.warning(
                    f"🌐 Hunter.io HTTP error {e.response.status_code} for {email} (attempt {attempt + 1})"
                )

                if attempt < self.max_retries and self._should_retry(
                    e.response.status_code, e
                ):
                    delay = self._calculate_backoff_delay(attempt + 1)
                    log.info(
                        f"⏳ Hunter.io: Waiting {delay:.1f}s before retry due to HTTP error"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    result = {
                        "email": email,
                        "score": 0,
                        "status": "error",
                        "error": f"HTTP error {e.response.status_code}: {str(e)}",
                        "api_calls": 1,
                        "cost_usd": 0.002,
                        "retry_attempts": attempt,
                        "http_status": e.response.status_code,
                    }
                    break

            except (httpx.ConnectError, httpx.ReadError) as e:
                log.warning(
                    f"🔌 Hunter.io connection error for {email} (attempt {attempt + 1}): {str(e)}"
                )

                if attempt < self.max_retries and self._should_retry(0, e):
                    delay = self._calculate_backoff_delay(attempt + 1)
                    log.info(
                        f"⏳ Hunter.io: Waiting {delay:.1f}s before retry due to connection error"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    result = {
                        "email": email,
                        "score": 0,
                        "status": "error",
                        "error": f"Connection error after all retries: {str(e)}",
                        "api_calls": 1,
                        "cost_usd": 0.002,
                        "retry_attempts": attempt,
                        "http_status": last_status_code,
                    }
                    break

            except Exception as e:
                self.failed_requests += 1
                log.error(
                    f"❌ Hunter.io verification failed for {email} (attempt {attempt + 1}): {str(e)}"
                )

                if attempt < self.max_retries and self._should_retry(0, e):
                    delay = self._calculate_backoff_delay(attempt + 1)
                    log.info(
                        f"⏳ Hunter.io: Waiting {delay:.1f}s before retry due to unexpected error"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    result = {
                        "email": email,
                        "score": 0,
                        "status": "error",
                        "error": f"Unexpected error after all retries: {str(e)}",
                        "api_calls": 1,
                        "cost_usd": 0.002,
                        "retry_attempts": attempt,
                        "http_status": last_status_code,
                    }
                    break

        # If we get here, all retries failed
        self.failed_requests += 1

        # Cache error results too (with shorter TTL)
        cache_entry = result.copy()
        cache_entry["cached_at"] = now_z()
        self.cache[cache_key] = cache_entry

        # Cleanup cache if needed
        if len(self.cache) > self.max_cache_size:
            self._cleanup_cache()

        return result

    async def verify_emails_batch(
        self,
        emails: List[str],
        logger: Optional[logging.Logger] = None,
        max_concurrent: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Verify multiple emails concurrently with controlled concurrency.

        Args:
            emails: List of email addresses to verify
            logger: Optional logger instance
            max_concurrent: Maximum concurrent requests (respects rate limits)

        Returns:
            List of verification results in same order as input emails
        """
        log = logger or logging.getLogger("enrich")

        if not emails:
            return []

        # Filter out invalid emails and check cache first
        valid_emails = []
        cached_results = {}
        uncached_emails = []

        for i, email in enumerate(emails):
            if not email or not isinstance(email, str):
                cached_results[i] = {
                    "email": email,
                    "score": 0,
                    "status": "invalid",
                    "error": "Invalid email format",
                    "api_calls": 0,
                    "cost_usd": 0.0,
                }
            else:
                cache_key = self._get_cache_key(email)
                if cache_key in self.cache and self._is_cache_valid(
                    self.cache[cache_key]
                ):
                    cached_results[i] = self.cache[cache_key]
                    self.cache_hits += 1
                else:
                    valid_emails.append((i, email))
                    uncached_emails.append(email)

        log.info(
            f"🚀 Hunter.io: Batch verification - {len(cached_results)} cached, {len(uncached_emails)} to verify"
        )

        # Verify uncached emails with controlled concurrency
        if uncached_emails:
            semaphore = asyncio.Semaphore(max_concurrent)

            async def verify_single(email_info):
                index, email = email_info
                async with semaphore:
                    return index, await self.verify_email(email, logger)

            # Create tasks for all emails
            tasks = [verify_single(email_info) for email_info in valid_emails]

            # Execute with controlled concurrency
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for result in results:
                if isinstance(result, Exception):
                    log.error(f"❌ Hunter.io: Batch verification error: {result}")
                    # Find the email that caused this error
                    for index, email in valid_emails:
                        if index not in cached_results:
                            cached_results[index] = {
                                "email": emails[index],
                                "score": 0,
                                "status": "error",
                                "error": str(result),
                                "api_calls": 1,
                                "cost_usd": 0.002,
                            }
                            break
                else:
                    index, verification_result = result
                    cached_results[index] = verification_result

        # Return results in original order
        return [
            cached_results.get(
                i,
                {
                    "email": emails[i],
                    "score": 0,
                    "status": "error",
                    "error": "Verification failed",
                    "api_calls": 0,
                    "cost_usd": 0.0,
                },
            )
            for i in range(len(emails))
        ]

    def _get_cache_key(self, email: str) -> str:
        """Generate cache key for email verification."""
        return f"hunter_verify_{email.lower().strip()}"

    def _is_cache_valid(self, cache_entry: Dict[str, Any]) -> bool:
        """Check if cache entry is still valid based on TTL."""
        if not cache_entry or "cached_at" not in cache_entry:
            return False

        try:
            from datetime import datetime, timezone

            cached_at = datetime.fromisoformat(
                cache_entry["cached_at"].replace("Z", "+00:00")
            )
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)

            current_time = datetime.now(timezone.utc)
            age_hours = (current_time - cached_at).total_seconds() / 3600

            return age_hours < self.cache_ttl_hours
        except Exception:
            return False

    def _cleanup_cache(self) -> None:
        """Remove expired entries and limit cache size."""
        # Remove expired entries
        expired_keys = []
        for key, entry in self.cache.items():
            if not self._is_cache_valid(entry):
                expired_keys.append(key)

        for key in expired_keys:
            del self.cache[key]

        # Limit cache size if still too large
        if len(self.cache) > self.max_cache_size:
            # Remove oldest entries (simple FIFO approach)
            keys_to_remove = len(self.cache) - self.max_cache_size
            oldest_keys = list(self.cache.keys())[:keys_to_remove]
            for key in oldest_keys:
                del self.cache[key]

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        self._cleanup_cache()
        return {
            "cache_size": len(self.cache),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": self.cache_hits / (self.cache_hits + self.cache_misses)
            if (self.cache_hits + self.cache_misses) > 0
            else 0.0,
            "max_cache_size": self.max_cache_size,
            "cache_ttl_hours": self.cache_ttl_hours,
        }

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics including error handling metrics."""
        return {
            "total_requests": self.request_count,
            "total_cost_usd": self.total_cost,
            "cost_per_request": 0.002,
            "avg_response_time_ms": self.avg_response_time * 1000,
            "min_response_time_ms": self.min_response_time * 1000
            if self.min_response_time != float("inf")
            else 0,
            "max_response_time_ms": self.max_response_time * 1000,
            "cache_stats": self.get_cache_stats(),
            "error_handling": {
                "total_retries": self.total_retries,
                "failed_requests": self.failed_requests,
                "rate_limit_hits": self.rate_limit_hits,
                "timeout_errors": self.timeout_errors,
                "authentication_errors": self.authentication_errors,
                "server_errors": self.server_errors,
                "retry_success_rate": (self.request_count - self.failed_requests)
                / max(self.request_count, 1)
                if self.request_count > 0
                else 0.0,
            },
        }

    def get_cost_info(self) -> Dict[str, Any]:
        """Get cost information for this client."""
        return {
            "total_requests": self.request_count,
            "total_cost_usd": self.total_cost,
            "cost_per_request": 0.002,
        }


async def verify_all_contact_emails_with_hunter(
    contacts: List[Dict[str, Any]],
    hunter_client: HunterIOClient,
    domain: str,
    logger: logging.Logger,
    costs_config: Dict[str, Any],
    min_score: int = 70,
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Verify ALL emails in contacts list with Hunter.io - from ANY source.

    This function handles emails from:
    - Crawl tool extraction
    - Apollo discovery
    - Any other provider
    - Manually provided emails

    Args:
        contacts: List of contact dictionaries
        hunter_client: Initialized Hunter.io client
        domain: Domain being processed
        logger: Logger instance
        costs_config: Costs configuration
        min_score: Minimum acceptable Hunter.io score

    Returns:
        (updated_contacts, total_hunter_cost)
    """
    logger.info(
        f"🔍 Hunter.io: Starting verification for {len(contacts)} contacts from {domain}"
    )

    # Check if Hunter.io client is available
    if not hunter_client:
        logger.warning(
            f"⚠️ Hunter.io client not available - skipping verification for {domain}"
        )
        return contacts, 0.0

    # Performance optimization: Use batch verification for multiple emails
    batch_threshold = 2  # Default threshold
    if hasattr(hunter_client, "get_performance_stats"):
        # Try to get batch threshold from ICP config if available
        try:
            # This is a bit of a hack - we'll need to pass this through from the calling function
            # For now, use default threshold
            pass
        except Exception:
            pass

    if len(contacts) >= batch_threshold:
        logger.info(
            f"🚀 Hunter.io: Using batch verification for {len(contacts)} contacts (threshold: {batch_threshold})"
        )

        # Extract emails and their indices
        emails_to_verify = []
        contact_indices = []

        for i, contact in enumerate(contacts):
            email = contact.get("email")
            if email:
                emails_to_verify.append(email)
                contact_indices.append(i)

        if emails_to_verify:
            # Use batch verification
            batch_results = await hunter_client.verify_emails_batch(
                emails_to_verify,
                logger,
                max_concurrent=5,  # Respect rate limits
            )

            # Apply results to contacts
            total_hunter_cost = 0.0
            verified_count = 0
            failed_count = 0

            for i, (contact_idx, hunter_result) in enumerate(
                zip(contact_indices, batch_results)
            ):
                contact = contacts[contact_idx]
                email = emails_to_verify[i]
                contact_name = contact.get("full_name", f"Contact {contact_idx + 1}")

                # Store Hunter.io results in contact data
                contact["hunter_verification"] = hunter_result
                contact["email_quality_score"] = hunter_result.get("score", 0)

                # Add Hunter.io to sources
                email_sources = contact.get("email_source", [])
                if "hunter_verified" not in email_sources:
                    email_sources.append("hunter_verified")
                contact["email_source"] = email_sources

                # Add cost
                total_hunter_cost += hunter_result.get("cost_usd", 0.0)

                # Decision logic based on Hunter.io score (BATCH VERIFICATION)
                score = hunter_result.get("score", 0)
                status = hunter_result.get("status", "unknown")
                result = hunter_result.get("result", "unknown")

                if score == 0:
                    # Enhanced logging for 0% score emails
                    logger.warning(
                        f"🗑️ Hunter.io: Discarding {email} (score 0%, status: {status}, result: {result})"
                    )

                    # Log additional context for debugging
                    if "error" in hunter_result:
                        logger.debug(f"   🔍 0% Score Reason: {hunter_result['error']}")
                    if "disposable" in hunter_result and hunter_result["disposable"]:
                        logger.debug("   📧 Email identified as disposable")
                    if "webmail" in hunter_result and hunter_result["webmail"]:
                        logger.debug("   🌐 Email identified as webmail")

                    contact["email"] = None  # hard remove
                    contact["email_source"] = []  # clear sources
                    contact["email_verified"] = False
                    contact["needs_email_discovery"] = True  # forces discovery step
                    failed_count += 1
                elif score >= min_score and status in ["valid", "deliverable"]:
                    # Enhanced logging for verified emails
                    logger.info(
                        f"✅ Hunter.io: Email {email} PASSED verification (score: {score}%, status: {status})"
                    )

                    # Log quality insights
                    if score >= 90:
                        logger.debug(
                            "   🏆 High-quality email (90%+) - excellent deliverability"
                        )
                    elif score >= 80:
                        logger.debug(
                            "   🥇 Good quality email (80-89%) - good deliverability"
                        )
                    elif score >= 70:
                        logger.debug(
                            "   🥈 Acceptable quality email (70-79%) - acceptable deliverability"
                        )

                    contact["email_verified"] = True
                    verified_count += 1
                else:
                    # Enhanced logging for failed verifications
                    logger.warning(
                        f"❌ Hunter.io: Email {email} FAILED verification (score: {score}%, status: {status})"
                    )

                    # Log specific failure reasons
                    if score < 50:
                        logger.debug(
                            "   🚨 Very low quality (0-49%) - high bounce risk"
                        )
                    elif score < 70:
                        logger.debug(
                            "   ⚠️ Below threshold (50-69%) - moderate bounce risk"
                        )

                    # Log specific status insights
                    if status == "risky":
                        logger.debug("   ⚡ Risky email status - proceed with caution")
                    elif status == "invalid":
                        logger.debug("   ❌ Invalid email format or domain")
                    elif status == "unknown":
                        logger.debug("   🤔 Unknown status - verification inconclusive")

                    contact["email_verified"] = False
                    failed_count += 1

                    # Mark for potential replacement during email discovery
                    contact["needs_email_replacement"] = True
        else:
            total_hunter_cost = 0.0
            verified_count = 0
            failed_count = 0
    else:
        # Single contact - use individual verification
        total_hunter_cost = 0.0
        verified_count = 0
        failed_count = 0

        for i, contact in enumerate(contacts):
            email = contact.get("email")
            contact_name = contact.get("full_name", f"Contact {i + 1}")

            if email:
                logger.info(
                    f"📧 Hunter.io: Verifying email {email} for {contact_name} (source: {contact.get('email_source', ['unknown'])})"
                )

                # Verify with Hunter.io
                hunter_result = await hunter_client.verify_email(email, logger)

                # Store Hunter.io results in contact data
                contact["hunter_verification"] = hunter_result
                contact["email_quality_score"] = hunter_result.get("score", 0)

                # Add Hunter.io to sources
                email_sources = contact.get("email_source", [])
                if "hunter_verified" not in email_sources:
                    email_sources.append("hunter_verified")
                contact["email_source"] = email_sources

                # Add cost
                total_hunter_cost += hunter_result.get("cost_usd", 0.0)

                # Decision logic based on Hunter.io score (INDIVIDUAL VERIFICATION)
                score = hunter_result.get("score", 0)
                status = hunter_result.get("status", "unknown")
                result = hunter_result.get("result", "unknown")

                if score == 0:
                    # Enhanced logging for 0% score emails
                    logger.warning(
                        f"🗑️ Hunter.io: Discarding {email} (score 0%, status: {status}, result: {result})"
                    )

                    # Log additional context for debugging
                    if "error" in hunter_result:
                        logger.debug(f"   🔍 0% Score Reason: {hunter_result['error']}")
                    if "disposable" in hunter_result and hunter_result["disposable"]:
                        logger.debug("   📧 Email identified as disposable")
                    if "webmail" in hunter_result and hunter_result["webmail"]:
                        logger.debug("   🌐 Email identified as webmail")

                    contact["email"] = None  # hard remove
                    contact["email_source"] = []  # clear sources
                    contact["email_verified"] = False
                    contact["needs_email_discovery"] = True  # forces discovery step
                    failed_count += 1
                elif score >= min_score and status in ["valid", "deliverable"]:
                    # Enhanced logging for verified emails
                    logger.info(
                        f"✅ Hunter.io: Email {email} PASSED verification (score: {score}%, status: {status})"
                    )

                    # Log quality insights
                    if score >= 90:
                        logger.debug(
                            "   🏆 High-quality email (90%+) - excellent deliverability"
                        )
                    elif score >= 80:
                        logger.debug(
                            "   🥇 Good quality email (80-89%) - good deliverability"
                        )
                    elif score >= 70:
                        logger.debug(
                            "   🥈 Acceptable quality email (70-79%) - acceptable deliverability"
                        )

                    contact["email_verified"] = True
                    verified_count += 1
                else:
                    # Enhanced logging for failed verifications
                    logger.warning(
                        f"❌ Hunter.io: Email {email} FAILED verification (score: {score}%, status: {status})"
                    )

                    # Log specific failure reasons
                    if score < 50:
                        logger.debug(
                            "   🚨 Very low quality (0-49%) - high bounce risk"
                        )
                    elif score < 70:
                        logger.debug(
                            "   ⚠️ Below threshold (50-69%) - moderate bounce risk"
                        )

                    # Log specific status insights
                    if status == "risky":
                        logger.debug("   ⚡ Risky email status - proceed with caution")
                    elif status == "invalid":
                        logger.debug("   ❌ Invalid email format or domain")
                    elif status == "unknown":
                        logger.debug("   🤔 Unknown status - verification inconclusive")

                    contact["email_verified"] = False
                    failed_count += 1

                    # Mark for potential replacement during email discovery
                    contact["needs_email_replacement"] = True
            else:
                logger.info(
                    f"📭 Hunter.io: No email found for {contact_name} - will attempt discovery"
                )
                contact["email_verified"] = False
                contact["needs_email_discovery"] = True

    # Count discarded emails (score 0)
    discarded_count = len([c for c in contacts if c.get("email") is None])

    # Enhanced logging with detailed insights
    if hasattr(hunter_client, "get_performance_stats"):
        perf_stats = hunter_client.get_performance_stats()
        logger.info(
            f"📊 Hunter.io Performance: Avg response: {perf_stats['avg_response_time_ms']:.1f}ms, Cache hit rate: {perf_stats['cache_stats']['cache_hit_rate']:.1%}"
        )

        # Log error handling statistics
        error_stats = perf_stats.get("error_handling", {})
        if error_stats:
            logger.info(
                f"🛡️ Hunter.io Error Handling: Retries: {error_stats.get('total_retries', 0)}, Failed: {error_stats.get('failed_requests', 0)}, Rate limits: {error_stats.get('rate_limit_hits', 0)}, Timeouts: {error_stats.get('timeout_errors', 0)}, Success rate: {error_stats.get('retry_success_rate', 0):.1%}"
            )

    # Enhanced cost and quality insights
    if verified_count > 0:
        avg_score = (
            sum(
                c.get("email_quality_score", 0)
                for c in contacts
                if c.get("email_quality_score")
            )
            / verified_count
        )
        logger.info(
            f"🎯 Email Quality Insights: Average score: {avg_score:.1f}%, {verified_count} high-quality emails verified"
        )

    if failed_count > 0:
        failed_scores = [
            c.get("email_quality_score", 0)
            for c in contacts
            if c.get("email_quality_score") and c.get("email_quality_score") < 70
        ]
        if failed_scores:
            avg_failed_score = sum(failed_scores) / len(failed_scores)
            logger.info(
                f"⚠️ Quality Issues: {failed_count} emails below threshold (avg score: {avg_failed_score:.1f}%) - marked for replacement"
            )

    if discarded_count > 0:
        logger.info(
            f"🗑️ Quality Control: {discarded_count} emails with 0% score discarded - triggering email discovery"
        )

    # Cost optimization insights
    if total_hunter_cost > 0:
        cost_per_verification = total_hunter_cost / (
            verified_count + failed_count + discarded_count
        )
        logger.info(
            f"💰 Cost Analysis: ${total_hunter_cost:.4f} total cost, ${cost_per_verification:.4f} per verification, {verified_count + failed_count + discarded_count} total verifications"
        )

        # Cache efficiency insights
        if hasattr(hunter_client, "get_performance_stats"):
            cache_stats = perf_stats.get("cache_stats", {})
            if cache_stats.get("cache_hits", 0) > 0:
                cache_savings = (
                    cache_stats["cache_hits"] * 0.002
                )  # $0.002 per cached hit
                logger.info(
                    f"💾 Cache Efficiency: {cache_stats['cache_hits']} cache hits saved ${cache_savings:.4f} in API costs"
                )

    logger.info(
        f"✅ Hunter.io verification completed for {domain}: {verified_count} verified, {failed_count} failed, {discarded_count} discarded (0% score), Total cost: ${total_hunter_cost:.4f}"
    )

    return contacts, total_hunter_cost


async def discover_and_verify_emails_with_hunter(
    contacts: List[Dict[str, Any]],
    domain: str,
    enrichment_router: Any,
    hunter_client: HunterIOClient,
    logger: logging.Logger,
    costs_config: Dict[str, Any],
    min_score: int = 70,
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Discover emails for contacts that need them and verify ALL emails with Hunter.io.

    This handles:
    1. Contacts with no email (discovery needed)
    2. Contacts with low-quality emails (replacement needed)
    """
    discovery_cost = 0.0
    hunter_cost = 0.0
    discovery_attempts = 0
    successful_discoveries = 0
    successful_replacements = 0

    logger.info(f"🔍 Hunter.io: Starting email discovery for {domain}")

    for contact in contacts:
        contact_name = contact.get("full_name", "Unknown Contact")

        # Check if we need to discover/replace email
        needs_discovery = contact.get("needs_email_discovery", False)
        needs_replacement = contact.get("needs_email_replacement", False)

        # Skip contacts that already have good emails
        if contact.get("email") and contact.get("email_verified"):
            continue

        if needs_discovery or needs_replacement:
            if contact.get("first_name") and contact.get("last_name"):
                original_email = contact.get("email")
                original_score = contact.get("email_quality_score", 0)

                logger.info(
                    f"🔍 Hunter.io: Attempting email discovery for {contact_name} at {domain}"
                )

                try:
                    request = EnrichmentRequest(
                        domain=domain,
                        first_name=contact["first_name"],
                        last_name=contact["last_name"],
                    )

                    result = await enrichment_router.find_email(request)
                    discovery_attempts += 1

                    if result.success and result.data and result.data.email:
                        new_email = result.data.email
                        discovery_cost += result.cost

                        logger.info(
                            f"✅ Hunter.io: New email discovered: {new_email} for {contact_name}"
                        )

                        # Verify the new email with Hunter.io
                        logger.info(
                            f"🔍 Hunter.io: Verifying discovered email {new_email}"
                        )
                        hunter_result = await hunter_client.verify_email(
                            new_email, logger
                        )
                        hunter_cost += hunter_result.get("cost_usd", 0.0)

                        score = hunter_result.get("score", 0)
                        status = hunter_result.get("status", "unknown")

                        logger.info(
                            f"📊 Hunter.io: Verification for discovered email {new_email}: Score={score}%, Status={status}"
                        )

                        # Decision: Use new email if it's better quality
                        if score >= min_score and status in ["valid", "deliverable"]:
                            # Update contact with new verified email
                            contact["email"] = new_email
                            contact["email_source"] = ["provider", "hunter_verified"]
                            contact["hunter_verification"] = hunter_result
                            contact["email_quality_score"] = score
                            contact["email_verified"] = True

                            # Track replacement
                            if original_email:
                                contact["replaced_email"] = original_email
                                contact["email_quality_improvement"] = (
                                    score - original_score
                                )
                                logger.info(
                                    f"📧 Hunter.io: Replaced email {original_email} with {new_email} (quality improvement: {original_score}% → {score}%)"
                                )
                                successful_replacements += 1
                            else:
                                successful_discoveries += 1

                            # Clear discovery flags since we now have a good email
                            contact.pop("needs_email_discovery", None)
                            contact.pop("needs_email_replacement", None)

                        else:
                            logger.warning(
                                f"❌ Hunter.io: Discovered email {new_email} also failed verification (score: {score}%)"
                            )
                            # Keep original email if new one is also bad, but mark for future discovery
                            if not original_email:
                                contact["email"] = new_email
                                contact["email_source"] = [
                                    "provider",
                                    "hunter_verified",
                                ]
                                contact["hunter_verification"] = hunter_result
                                contact["email_quality_score"] = score
                                contact["email_verified"] = False
                                # Keep discovery flag active for future attempts
                                contact["needs_email_discovery"] = True
                    else:
                        logger.warning(
                            f"❌ Hunter.io: Email discovery failed for {contact_name}"
                        )

                except Exception as exc:
                    logger.warning(
                        f"❌ Hunter.io: Email discovery failed for {contact_name}: {exc}"
                    )

    total_cost = discovery_cost + hunter_cost
    logger.info(
        f"💰 Hunter.io email discovery & verification completed for {domain}: {discovery_attempts} attempts, {successful_discoveries} discoveries, {successful_replacements} replacements, Total cost: ${total_cost:.4f}"
    )

    # Final summary of email status after discovery
    final_verified = [c for c in contacts if c.get("email_verified")]
    final_unverified = [
        c for c in contacts if c.get("email") and not c.get("email_verified")
    ]
    final_no_email = [c for c in contacts if c.get("email") is None]
    logger.info(
        f"📊 Final email status for {domain}: {len(final_verified)} verified, {len(final_unverified)} unverified, {len(final_no_email)} no email"
    )

    return contacts, total_cost


def select_best_contact_with_email_quality(
    contacts: List[Dict[str, Any]], role_priority_config: Dict[str, int]
) -> Optional[str]:
    """Enhanced contact selection prioritizing Hunter.io verified emails."""

    if not contacts:
        return None

    scored_contacts = []
    for contact in contacts:
        contact_id = contact.get("contact_id", "")
        role = contact.get("role") or contact.get("job_title", "")
        seniority = contact.get("seniority", 99)

        # NEW: Email quality scoring from Hunter.io
        email_quality_score = contact.get("email_quality_score", 0)
        email_verified = contact.get("email_verified", False)

        # Enhanced email status ranking that considers Hunter.io verification
        if email_verified and email_quality_score >= 70:
            email_quality_rank = 0  # Best: Hunter.io verified with good score
        elif contact.get("email") and email_quality_score >= 50:
            email_quality_rank = 1  # Good: Has email with decent Hunter.io score
        elif contact.get("email") and contact.get("email") is not None:
            email_quality_rank = 2  # Okay: Has email but low/no Hunter.io score
        else:
            email_quality_rank = 3  # Poor: No email (None or empty)

        # Get other rankings
        role_priority = get_role_priority(role, role_priority_config)
        seniority_rank = get_seniority_rank(role) if seniority is None else seniority
        linkedin = contact.get("linkedin") or contact.get("linkedin_url", "")
        has_linkedin = 0 if linkedin else 1

        # Enhanced sort tuple with email quality as high priority
        sort_tuple = (
            role_priority,  # 1st: Role priority
            email_quality_rank,  # 2nd: Email quality (NEW)
            seniority_rank,  # 3rd: Seniority
            has_linkedin,  # 4th: LinkedIn presence
            contact_id,  # 5th: Deterministic tiebreaker
        )

        scored_contacts.append((sort_tuple, contact_id))

    # Sort and return best contact
    scored_contacts.sort(key=lambda x: x[0])
    return scored_contacts[0][1] if scored_contacts else None


# ============================================================================
# Field Mapping Functions
# ============================================================================


# Field mapping now handled by router and providers


# Contact field mapping now handled by router and providers


def filter_contacts_with_emails(contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter contacts to only those with valid emails (not None)."""
    return [c for c in contacts if c.get("email") is not None]


def get_contact_email(contact: Dict[str, Any]) -> Optional[str]:
    """Safely get contact email, handling None values."""
    email = contact.get("email")
    return email if email is not None else None


def has_valid_email(contact: Dict[str, Any]) -> bool:
    """Check if contact has a valid (non-None) email."""
    return contact.get("email") is not None


def count_contacts_with_emails(contacts: List[Dict[str, Any]]) -> int:
    """Count contacts that have valid (non-None) emails."""
    return len([c for c in contacts if c.get("email") is not None])


def get_contacts_without_emails(contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Get contacts that have no email (None or missing)."""
    return [c for c in contacts if c.get("email") is None]


def parse_contact_names(
    contacts: List[Dict[str, Any]], logger: Optional[logging.Logger] = None
) -> List[Dict[str, Any]]:
    """
    Parse full names into first/last names for email discovery.

    Args:
        contacts: List of contacts with potential full_name fields
        logger: Optional logger instance

    Returns:
        List of contacts with parsed first_name and last_name fields
    """
    # Use provided logger or get default
    log = logger or logging.getLogger("enrich")

    for contact in contacts:
        if not isinstance(contact, dict):
            continue

        # If contact already has first_name and last_name, skip
        if contact.get("first_name") and contact.get("last_name"):
            continue

        # Check for full_name field
        full_name = contact.get("full_name") or contact.get("name")
        if not full_name:
            continue

        # Parse the full name
        first_name, last_name = parse_full_name(full_name)

        # Update the contact with parsed names
        contact["first_name"] = first_name
        contact["last_name"] = last_name

        log.info(
            f"✅ Parsed name: '{full_name}' -> first: '{first_name}', last: '{last_name}'"
        )

    return contacts


def parse_full_name(full_name: str) -> Tuple[str, str]:
    """
    Parse a full name into first and last names, handling prefixes and suffixes.

    Args:
        full_name: Full name string (e.g., "mr. david sable", "ms. barbara guggenheim")

    Returns:
        Tuple of (first_name, last_name)
    """
    if not full_name:
        return "", ""

    # Common name prefixes and suffixes to remove
    prefixes = [
        "mr.",
        "ms.",
        "mrs.",
        "dr.",
        "prof.",
        "professor",
        "sir",
        "madam",
        "captain",
        "general",
    ]
    suffixes = ["jr.", "sr.", "ii", "iii", "iv", "phd", "mba", "esq", "esquire"]

    # Convert to lowercase for comparison
    name_lower = full_name.lower().strip()

    # Remove prefixes
    for prefix in prefixes:
        if name_lower.startswith(prefix):
            full_name = full_name[len(prefix) :].strip()
            break

    # Remove suffixes
    for suffix in suffixes:
        if name_lower.endswith(suffix):
            full_name = full_name[: -len(suffix)].strip()
            break

    # Split remaining name into parts
    name_parts = full_name.strip().split()

    if len(name_parts) == 0:
        return "", ""
    elif len(name_parts) == 1:
        return name_parts[0], ""
    elif len(name_parts) == 2:
        return name_parts[0], name_parts[1]
    else:
        # For names with 3+ parts, first is first name, rest is last name
        return name_parts[0], " ".join(name_parts[1:])


# ============================================================================
# Core Enrichment Logic
# ============================================================================


def validate_llm_response(llm_response: str) -> bool:
    """
    Validate LLM response format before parsing.
    Handles various response formats gracefully.

    Args:
        llm_response: Raw LLM response string

    Returns:
        True if response format is valid, False otherwise
    """
    if not llm_response or not isinstance(llm_response, str):
        return False

    # Clean up the response - remove markdown formatting if present
    cleaned_response = llm_response.strip()

    # Handle various markdown formats
    if "```" in cleaned_response:
        # Find the start of the markdown block
        start_marker = cleaned_response.find("```")
        if start_marker != -1:
            # Find the end of the opening markdown block
            first_newline = cleaned_response.find("\n", start_marker)
            if first_newline != -1:
                # Remove everything before the content
                cleaned_response = cleaned_response[first_newline + 1 :]

        # Find the end of the markdown block
        end_marker = cleaned_response.rfind("```")
        if end_marker != -1:
            # Remove the closing ```
            cleaned_response = cleaned_response[:end_marker]

    cleaned_response = cleaned_response.strip()

    try:
        # Try to parse JSON response
        response_data = json.loads(cleaned_response)

        # Check if it's a dictionary
        if not isinstance(response_data, dict):
            return False

        # Check if contact_id key exists
        if "contact_id" not in response_data:
            return False

        # Check if contact_id is not empty
        contact_id = response_data["contact_id"]
        if not contact_id or not isinstance(contact_id, str):
            return False

        return True

    except (json.JSONDecodeError, KeyError, TypeError):
        return False


def extract_contact_id(
    llm_response: str,
    contacts: List[Dict[str, Any]],
    logger: Optional[logging.Logger] = None,
) -> Optional[str]:
    """
    Enhanced contact ID extraction with multiple fallback strategies.
    Handles various response formats gracefully with improved error recovery.

    Args:
        llm_response: Raw LLM response string
        contacts: List of contacts for validation
        logger: Optional logger instance

    Returns:
        Valid contact ID or None if invalid
    """
    # Use provided logger or get default
    log = logger or logging.getLogger("enrich")

    if not llm_response or not isinstance(llm_response, str):
        return None

    valid_contact_ids = [c.get("contact_id") for c in contacts if c.get("contact_id")]

    # Strategy 1: Direct JSON parsing
    contact_id = _try_direct_json_parsing(llm_response, valid_contact_ids, log)
    if contact_id:
        log.info(f"✅ Valid contact_id extracted via direct JSON: {contact_id}")
        return contact_id

    # Strategy 2: Markdown cleanup then JSON parsing
    contact_id = _try_markdown_cleanup_parsing(llm_response, valid_contact_ids, log)
    if contact_id:
        log.info(f"✅ Valid contact_id extracted via markdown cleanup: {contact_id}")
        return contact_id

    # Strategy 3: Regex extraction for contact_id
    contact_id = _try_regex_extraction(llm_response, valid_contact_ids, log)
    if contact_id:
        log.info(f"✅ Valid contact_id extracted via regex: {contact_id}")
        return contact_id

    # Strategy 4: JSON repair then parsing
    contact_id = _try_json_repair_parsing(llm_response, valid_contact_ids, log)
    if contact_id:
        log.info(f"✅ Valid contact_id extracted via JSON repair: {contact_id}")
        return contact_id

    # Strategy 5: Fuzzy matching for partial responses
    contact_id = _try_fuzzy_matching(llm_response, valid_contact_ids, log)
    if contact_id:
        log.info(f"✅ Valid contact_id extracted via fuzzy matching: {contact_id}")
        return contact_id

    log.warning(
        f"❌ All extraction strategies failed for response: {llm_response[:100]}..."
    )
    return None


def _try_direct_json_parsing(
    response: str, valid_ids: List[str], logger
) -> Optional[str]:
    """Strategy 1: Direct JSON parsing."""
    try:
        parsed = json.loads(response.strip())
        if isinstance(parsed, dict) and parsed.get("contact_id"):
            contact_id = parsed["contact_id"]
            if contact_id and contact_id in valid_ids:
                return contact_id
    except json.JSONDecodeError:
        pass
    return None


def _try_markdown_cleanup_parsing(
    response: str, valid_ids: List[str], logger
) -> Optional[str]:
    """Strategy 2: Clean markdown formatting then parse JSON."""
    try:
        cleaned = _clean_markdown_response(response)
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and parsed.get("contact_id"):
            contact_id = parsed["contact_id"]
            if contact_id and contact_id in valid_ids:
                return contact_id
    except json.JSONDecodeError:
        pass
    return None


def _try_regex_extraction(response: str, valid_ids: List[str], logger) -> Optional[str]:
    """Strategy 3: Regex extraction for contact_id."""
    patterns = [
        r'"contact_id"\s*:\s*"([^"]+)"',
        r"'contact_id'\s*:\s*'([^']+)'",
        r'contact_id:\s*"([^"]+)"',
        r"contact_id:\s*([a-zA-Z0-9_-]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, response)
        if match:
            contact_id = match.group(1)
            if contact_id in valid_ids:
                return contact_id
    return None


def _try_json_repair_parsing(
    response: str, valid_ids: List[str], logger
) -> Optional[str]:
    """Strategy 4: Attempt to fix common JSON issues."""
    try:
        fixed_response = _fix_common_json_issues(response)
        parsed = json.loads(fixed_response)
        if isinstance(parsed, dict) and parsed.get("contact_id"):
            contact_id = parsed["contact_id"]
            if contact_id and contact_id in valid_ids:
                return contact_id
    except json.JSONDecodeError:
        pass
    return None


def _try_fuzzy_matching(response: str, valid_ids: List[str], logger) -> Optional[str]:
    """Strategy 5: Fuzzy matching for partial contact IDs."""
    # Look for any valid contact ID mentioned in the response
    for contact_id in valid_ids:
        if contact_id in response:
            return contact_id
    return None


def _clean_markdown_response(response: str) -> str:
    """Clean markdown formatting from response."""
    if "```" in response:
        # Find the first complete code block
        start_markers = ["```json", "```JSON", "```"]
        end_marker = "```"

        for start_marker in start_markers:
            start_idx = response.find(start_marker)
            if start_idx != -1:
                content_start = start_idx + len(start_marker)
                end_idx = response.find(end_marker, content_start)
                if end_idx != -1:
                    content = response[content_start:end_idx].strip()
                    if content:
                        return content

        # Fallback: extract content between any ``` markers
        start = response.find("```")
        end = response.rfind("```")
        if start != -1 and end != -1 and end > start:
            content = response[start + 3 : end]
            # Remove language identifier if present
            lines = content.split("\n")
            if len(lines) > 0 and lines[0].strip().lower() in ["json", ""]:
                lines = lines[1:]
            return "\n".join(lines).strip()

    return response.strip()


def _fix_common_json_issues(response: str) -> str:
    """Fix common JSON formatting issues."""
    # Remove trailing commas
    response = re.sub(r",\s*}", "}", response)
    response = re.sub(r",\s*]", "]", response)

    # Fix unquoted keys (but be careful not to break already quoted ones)
    response = re.sub(r"(\w+)(?=\s*:)", r'"\1"', response)
    response = re.sub(r'""(\w+)""', r'"\1"', response)  # Fix double quotes

    # Fix missing closing braces/brackets
    open_braces = response.count("{")
    close_braces = response.count("}")
    if open_braces > close_braces:
        response += "}" * (open_braces - close_braces)

    open_brackets = response.count("[")
    close_brackets = response.count("]")
    if open_brackets > close_brackets:
        response += "]" * (open_brackets - close_brackets)

    return response


def format_contacts_for_llm(
    contacts: List[Dict[str, Any]],
    role_priority_config: Optional[Dict[str, int]] = None,
) -> str:
    """
    Format contacts for LLM consumption with role priorities and business context.

    Args:
        contacts: List of contacts
        role_priority_config: Optional role priority configuration for context

    Returns:
        Formatted string representation
    """
    if not contacts:
        return "No contacts available."

    formatted = []
    for i, contact in enumerate(
        contacts[:10]
    ):  # Cap at 10 contacts to avoid token limits
        contact_id = contact.get("contact_id", f"contact_{i}")
        name = contact.get("name", "Unknown")
        role = contact.get("role") or contact.get("job_title", "Unknown")
        company = contact.get("company", "Unknown")
        seniority = contact.get("seniority", "Unknown")

        # Handle decision maker status
        decision_maker = contact.get("decision_maker", False)
        decision_status = "Decision Maker" if decision_maker else "Non-Decision Maker"

        # Handle email status for contact quality
        email_status = contact.get("email_status", "unknown")
        if isinstance(email_status, list):
            email_status = email_status[0] if email_status else "unknown"

        # Handle LinkedIn presence
        linkedin = contact.get("linkedin") or contact.get("linkedin_url", "")
        linkedin_status = "Has LinkedIn" if linkedin else "No LinkedIn"

        # Get role priority if available
        role_priority = ""
        if role_priority_config:
            priority = get_role_priority(role, role_priority_config)
            role_priority = f" | Priority: {priority}"

        # Build comprehensive contact description
        contact_description = (
            f"{i + 1}. ID: {contact_id} | "
            f"Name: {name} | "
            f"Role: {role} | "
            f"Company: {company} | "
            f"Seniority: {seniority} | "
            f"Status: {decision_status} | "
            f"Email: {email_status} | "
            f"LinkedIn: {linkedin_status}"
            f"{role_priority}"
        )

        formatted.append(contact_description)

    if len(contacts) > 10:
        formatted.append(
            f"... and {len(contacts) - 10} more contacts (showing first 10)"
        )

    return "\n".join(formatted)


async def llm_with_fallback(
    fn_llm, fn_rule_based, *args, logger: Optional[logging.Logger] = None, **kwargs
) -> Any:
    """
    Execute LLM function with fallback to rule-based function.

    Args:
        fn_llm: LLM-based function to try first
        fn_rule_based: Rule-based fallback function
        *args: Arguments to pass to both functions
        logger: Optional logger instance
        **kwargs: Keyword arguments to pass to both functions

    Returns:
        Result from LLM function or fallback function
    """
    # Use provided logger or get default
    log = logger or logging.getLogger("enrich")

    try:
        result = await fn_llm(*args, **kwargs)
        if result is not None:
            log.info("✅ LLM function succeeded")
            return result
        else:
            # Note: This function doesn't have access to logger, so it will use default logging
            # The main enrich function will handle proper logging
            track_fallback_metric("llm_none_responses")
            return fn_rule_based(*args, **kwargs)
    except Exception:
        # Note: This function doesn't have access to logger, so it will use default logging
        # The main enrich function will handle proper logging
        track_fallback_metric("llm_failures")
        return fn_rule_based(*args, **kwargs)


async def select_best_contact_llm(
    contacts: List[Dict[str, Any]],
    role_priority_config: Dict[str, int],
    icp_config: Optional[Dict[str, Any]] = None,
    logger: Optional[logging.Logger] = None,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Select best contact using LLM with fallback to rule-based.

    Args:
        contacts: List of contacts
        role_priority_config: Role priority configuration
        icp_config: ICP configuration for business context
        logger: Optional logger instance

    Returns:
        Tuple of (Contact ID of best contact, Cost information)
    """
    # Use provided logger or get default
    log = logger or logging.getLogger("enrich")

    if not contacts:
        return None, {
            "total_cost_usd": 0.0,
            "cost_details": [],
            "total_calls": 0,
            "total_tokens": 0,
        }

    if not icp_config:
        log.info("ℹ️ No ICP config provided, using rule-based selection")
        return select_best_contact_with_email_quality(contacts, role_priority_config), {
            "total_cost_usd": 0.0,
            "cost_details": [],
            "total_calls": 0,
            "total_tokens": 0,
        }

    # Get OpenRouter API key from environment
    api_key = os.getenv("OPENROUTER_KEY")
    if not api_key:
        log.warning("⚠️ No OPENROUTER_KEY found, using rule-based selection")
        return select_best_contact_with_email_quality(contacts, role_priority_config), {
            "total_cost_usd": 0.0,
            "cost_details": [],
            "total_tokens": 0,
        }

    # Get ICP type for configuration
    icp_type = icp_config.get("icp_type", "default")

    # Create LLM client with ICP-specific configuration
    llm_selector = LLMContactSelector(api_key, icp_type, icp_config, logger)

    # Create wrapper functions for proper parameter passing
    async def llm_function(contacts_param, icp_param):
        result = await llm_selector.select_contact(
            contacts_param, icp_param, role_priority_config
        )
        return result, llm_selector.get_cost_info()

    def fallback_function(contacts_param, _):
        track_llm_performance_metric("fallback_to_rule_based")
        return select_best_contact_with_email_quality(
            contacts_param, role_priority_config
        ), {
            "total_cost_usd": 0.0,
            "cost_details": [],
            "total_calls": 0,
            "total_tokens": 0,
        }

    # Try LLM selection with fallback
    try:
        result = await llm_function(contacts, icp_config)
        if result[0] is not None:
            return result
        else:
            # Note: This function doesn't have access to logger, so it will use default logging
            # The main enrich function will handle proper logging
            track_fallback_metric("llm_none_responses")
            return fallback_function(contacts, icp_config)
    except Exception:
        # Note: This function doesn't have access to logger, so it will use default logging
        # The main enrich function will handle proper logging
        track_fallback_metric("llm_failures")
        return fallback_function(contacts, icp_config)


def track_fallback_metric(metric_type: str, logger: Optional[logging.Logger] = None):
    """
    Track fallback metrics for monitoring and analysis.

    Args:
        metric_type: Type of fallback metric to track
        logger: Optional logger instance
    """
    global FALLBACK_METRICS

    # Use provided logger or get default
    log = logger or logging.getLogger("enrich")

    if metric_type in FALLBACK_METRICS:
        FALLBACK_METRICS[metric_type] += 1
        FALLBACK_METRICS["total_fallbacks"] += 1

        # Log the metric for monitoring
        log.info(
            f"📊 FALLBACK_METRIC: {metric_type} - Total: {FALLBACK_METRICS[metric_type]}"
        )

    # Log current fallback statistics
    log.info(f"📊 FALLBACK_STATS: {FALLBACK_METRICS}")


def get_fallback_metrics() -> Dict[str, int]:
    """
    Get current fallback metrics for monitoring.

    Returns:
        Dictionary of fallback metrics
    """
    return FALLBACK_METRICS.copy()


def track_llm_performance_metric(
    metric_type: str, value: int = 1, logger: Optional[logging.Logger] = None
):
    """
    Track LLM performance metrics for monitoring.

    Args:
        metric_type: Type of performance metric to track
        value: Value to add (default: 1)
        logger: Optional logger instance
    """
    global LLM_PERFORMANCE_METRICS

    # Use provided logger or get default
    log = logger or logging.getLogger("enrich")

    if metric_type in LLM_PERFORMANCE_METRICS:
        LLM_PERFORMANCE_METRICS[metric_type] += value
        log.debug(
            f"📊 LLM_PERFORMANCE: {metric_type} - Total: {LLM_PERFORMANCE_METRICS[metric_type]}"
        )
    else:
        log.warning(f"⚠️ Unknown LLM performance metric type: {metric_type}")


def get_llm_performance_metrics() -> Dict[str, Any]:
    """
    Get current LLM performance metrics.

    Returns:
        Dictionary of LLM performance metrics with calculated averages
    """
    metrics = LLM_PERFORMANCE_METRICS.copy()
    # Calculate average response time
    if metrics["total_calls"] > 0:
        metrics["average_response_time_ms"] = (
            metrics["total_response_time_ms"] / metrics["total_calls"]
        )
    return metrics


def reset_llm_performance_metrics():
    """Reset LLM performance metrics (useful for testing)."""
    global LLM_PERFORMANCE_METRICS
    for key in LLM_PERFORMANCE_METRICS:
        LLM_PERFORMANCE_METRICS[key] = 0


def analyze_llm_response_quality(
    response: str,
    expected_format: str = "json",
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """
    Analyze the quality of LLM responses for monitoring and improvement.

    Args:
        response: The LLM response to analyze
        expected_format: Expected format (default: "json")
        logger: Optional logger instance

    Returns:
        Dictionary with quality metrics
    """
    # Use provided logger or get default
    log = logger or logging.getLogger("enrich")

    quality_metrics = {
        "length": len(response),
        "is_valid_json": False,
        "has_contact_id": False,
        "format_compliance": 0.0,
        "issues": [],
    }

    try:
        # Check if response is valid JSON
        if expected_format == "json":
            parsed = json.loads(response)
            quality_metrics["is_valid_json"] = True

            # Check for required fields
            if "contact_id" in parsed:
                quality_metrics["has_contact_id"] = True
                quality_metrics["format_compliance"] += 0.5
            else:
                quality_metrics["issues"].append("missing_contact_id")

            # Check if contact_id is not empty
            if parsed.get("contact_id"):
                quality_metrics["format_compliance"] += 0.5
            else:
                quality_metrics["issues"].append("empty_contact_id")

        else:
            quality_metrics["issues"].append("unexpected_format")

    except json.JSONDecodeError:
        quality_metrics["issues"].append("invalid_json")
    except Exception as e:
        quality_metrics["issues"].append(f"parsing_error: {str(e)}")

    # Log quality metrics for monitoring
    if quality_metrics["format_compliance"] < 1.0:
        log.warning(f"📊 LLM response quality issues: {quality_metrics['issues']}")
    else:
        log.debug(
            f"📊 LLM response quality: {quality_metrics['format_compliance']:.2f}"
        )

    return quality_metrics


def get_llm_monitoring_summary() -> Dict[str, Any]:
    """
    Get comprehensive LLM monitoring summary.

    Returns:
        Dictionary with fallback and performance metrics
    """
    fallback_metrics = get_fallback_metrics()
    performance_metrics = get_llm_performance_metrics()

    # Calculate success rate
    total_calls = performance_metrics.get("total_calls", 0)
    successful_calls = performance_metrics.get("successful_calls", 0)
    success_rate = (successful_calls / total_calls * 100) if total_calls > 0 else 0

    # Calculate cache hit rate
    cache_hits = performance_metrics.get("cache_hits", 0)
    cache_misses = performance_metrics.get("cache_misses", 0)
    cache_hit_rate = (
        (cache_hits / (cache_hits + cache_misses) * 100)
        if (cache_hits + cache_misses) > 0
        else 0
    )

    return {
        "fallback_metrics": fallback_metrics,
        "performance_metrics": performance_metrics,
        "calculated_metrics": {
            "success_rate_percent": round(success_rate, 2),
            "cache_hit_rate_percent": round(cache_hit_rate, 2),
            "fallback_rate_percent": round(
                (fallback_metrics.get("total_fallbacks", 0) / total_calls * 100)
                if total_calls > 0
                else 0,
                2,
            ),
        },
    }


def load_prompt_template(
    template_name: str, logger: Optional[logging.Logger] = None
) -> str:
    """
    Load prompt template from file.

    Args:
        template_name: Name of the template file
        logger: Optional logger instance

    Returns:
        Template content as string
    """
    # Use provided logger or get default
    log = logger or logging.getLogger("enrich")

    try:
        template_path = (
            Path(__file__).parent.parent / "config" / "prompts" / template_name
        )
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        log.warning(f"⚠️ Prompt template {template_name} not found, using default")
        # Return a basic fallback template to avoid recursion
        return """ICP: {icp_text}

Select the BEST contact who can actually make business decisions or allocate resources. Prioritize:
- Decision makers and executives
- People with budget authority
- Senior managers and directors
- Business owners and founders

AVOID: Marketing executives, consultants, or people without decision-making power.
{role_context}

Contacts:
{contacts}

Return ONLY a JSON response in this exact format:
{ "contact_id": "123" }"""
    except Exception as e:
        log.error(f"❌ Failed to load prompt template {template_name}: {str(e)}")
        # Return a basic fallback template to avoid recursion
        return """ICP: {icp_text}

Select the BEST contact who can actually make business decisions or allocate resources. Prioritize:
- Decision makers and executives
- People with budget authority
- Senior managers and directors
- Business owners and founders

AVOID: Marketing executives, consultants, or people without decision-making power.
{role_context}

Contacts:
{contacts}

Return ONLY a JSON response in this exact format:
{ "contact_id": "123" }"""


def get_icp_llm_config(icp_type: str, icp_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get LLM configuration for specific ICP, with overrides from ICP config.

    Args:
        icp_type: ICP type identifier
        icp_config: Full ICP configuration

    Returns:
        Merged LLM configuration
    """
    # Get base config for ICP type
    base_config = LLM_ICP_CONFIGS.get(icp_type, LLM_ICP_CONFIGS["default"]).copy()

    # Apply ICP-specific overrides if present
    if "llm_config" in icp_config:
        llm_overrides = icp_config["llm_config"]
        base_config.update(llm_overrides)

    # Ensure all required fields are present
    required_fields = [
        "model",
        "fallback_model",
        "temperature",
        "max_tokens",
        "timeout",
        "prompt_template",
    ]
    for field in required_fields:
        if field not in base_config:
            base_config[field] = LLM_ICP_CONFIGS["default"][field]

    return base_config


def test_llm_response_handling():
    """
    Test function to validate LLM response handling with various formats.
    This function tests the response validation and extraction logic.
    """
    # Test contacts
    test_contacts = [
        {"contact_id": "123", "name": "John Doe", "role": "CEO"},
        {"contact_id": "456", "name": "Jane Smith", "role": "CTO"},
    ]

    # Test various response formats
    test_responses = [
        '{"contact_id": "123"}',  # Valid JSON
        '```json\n{"contact_id": "456"}\n```',  # Markdown JSON
        '{"contact_id": "789"}',  # Invalid contact_id
        '{"wrong_key": "123"}',  # Missing contact_id
        "invalid json",  # Invalid JSON
        '{"contact_id": ""}',  # Empty contact_id
        '{"contact_id": null}',  # Null contact_id
    ]

    print("🧪 Testing LLM response handling...")

    for i, response in enumerate(test_responses):
        is_valid = validate_llm_response(response)
        contact_id = extract_contact_id(response, test_contacts)

        print(f"Test {i + 1}: {response[:30]}...")
        print(f"  Valid: {is_valid}")
        print(f"  Contact ID: {contact_id}")
        print()


def test_prompt_variations():
    """
    Test different prompt variations to ensure LLM understands business context.
    This function tests prompt engineering and business context understanding.
    """
    print("🧪 Testing Prompt Variations and Business Context...")

    # Test different ICP types
    icp_types = ["investment", "healthcare", "technology", "enterprise", "dental"]

    for icp_type in icp_types:
        print(f"\n📋 Testing {icp_type.upper()} ICP type:")

        # Get configuration for this ICP type
        config = LLM_ICP_CONFIGS.get(icp_type, LLM_ICP_CONFIGS["default"])

        print(f"  Model: {config['model']}")
        print(f"  Temperature: {config['temperature']}")
        print(f"  Max Tokens: {config['max_tokens']}")
        print(f"  Timeout: {config['timeout']}")
        print(f"  Prompt Template: {config['prompt_template']}")

        # Test prompt template loading
        try:
            template = load_prompt_template(config["prompt_template"])
            print(f"  ✅ Template loaded successfully ({len(template)} chars)")
        except Exception as e:
            print(f"  ❌ Template loading failed: {str(e)}")

    print("\n✅ Prompt variation testing completed!")


def test_icp_configuration_overrides():
    """
    Test ICP configuration overrides for LLM settings.
    This function tests the configurable LLM parameters per ICP.
    """
    print("🧪 Testing ICP Configuration Overrides...")

    # Test ICP config with LLM overrides
    test_icp_config = {
        "icp_type": "investment",
        "icp_text": "Test investment ICP",
        "llm_config": {"temperature": 0.2, "max_tokens": 800, "timeout": 60.0},
    }

    # Get merged configuration
    merged_config = get_icp_llm_config("investment", test_icp_config)

    print("📋 Base investment config:")
    print(f"  Temperature: {LLM_ICP_CONFIGS['investment']['temperature']}")
    print(f"  Max Tokens: {LLM_ICP_CONFIGS['investment']['max_tokens']}")
    print(f"  Timeout: {LLM_ICP_CONFIGS['investment']['timeout']}")

    print("\n📋 Merged config with overrides:")
    print(f"  Temperature: {merged_config['temperature']}")
    print(f"  Max Tokens: {merged_config['max_tokens']}")
    print(f"  Timeout: {merged_config['timeout']}")

    # Verify overrides are applied
    assert merged_config["temperature"] == 0.2, "Temperature override not applied"
    assert merged_config["max_tokens"] == 800, "Max tokens override not applied"
    assert merged_config["timeout"] == 60.0, "Timeout override not applied"

    print("✅ Configuration overrides working correctly!")


def select_best_contact(
    contacts: List[Dict[str, Any]], role_priority_config: Dict[str, int]
) -> Optional[str]:
    """
    Select best contact using deterministic ranking.

    Args:
        contacts: List of contacts
        role_priority_config: Role priority configuration

    Returns:
        Contact ID of best contact or None
    """
    if not contacts:
        return None

    # Score each contact
    scored_contacts = []
    for contact in contacts:
        contact_id = contact.get("contact_id", "")
        # Handle both old and new field names
        role = contact.get("role") or contact.get("job_title", "")
        seniority = contact.get("seniority", 99)
        email_status = (
            contact.get("email_status", ["unknown"])[0]
            if isinstance(contact.get("email_status"), list)
            else contact.get("email_status", "unknown")
        )
        # Handle both old and new field names
        linkedin = contact.get("linkedin") or contact.get("linkedin_url", "")

        # Get role priority
        role_priority = get_role_priority(role, role_priority_config)

        # Get seniority rank
        seniority_rank = get_seniority_rank(role) if seniority is None else seniority

        # Get email status rank
        email_status_rank = get_email_status_rank(email_status)

        # Check if has LinkedIn
        has_linkedin = 0 if linkedin else 1

        # Create sort tuple: (role_priority, seniority_rank, email_status_rank, has_linkedin, contact_id)
        sort_tuple = (
            role_priority,
            seniority_rank,
            email_status_rank,
            has_linkedin,
            contact_id,
        )
        scored_contacts.append((sort_tuple, contact_id))

    # Sort by tuple (ascending) and pick first
    scored_contacts.sort(key=lambda x: x[0])
    return scored_contacts[0][1] if scored_contacts else None


# Company enrichment now handled by router


# Contact enrichment now handled by router


# Contact discovery now handled by router


def write_evidence_file(
    domain: str, evidence_data: Dict[str, Any], data_dir: str
) -> str:
    """
    Write evidence to file and return path.

    Args:
        domain: Company domain
        evidence_data: Evidence data to write
        data_dir: Data directory

    Returns:
        Evidence file path
    """
    # Normalize domain for file path
    normalized_domain = normalize_domain(domain)

    # Create evidence directory
    evidence_dir = os.path.join(data_dir, "evidence", "enrich")
    os.makedirs(evidence_dir, exist_ok=True)

    # Write evidence file
    evidence_path = os.path.join(evidence_dir, f"{normalized_domain}.json")

    try:
        # Write directly without locking (Windows compatibility)
        with open(evidence_path, "w") as f:
            json.dump(evidence_data, f, indent=2)
    except Exception as e:
        raise RuntimeError(f"Failed to write evidence file {evidence_path}: {e}")

    return evidence_path


# ============================================================================
# Required Fields Validation
# ============================================================================


def _check_required_fields_complete(
    company: Dict[str, Any],
    contacts: List[Dict[str, Any]],
    best_contact_id: Optional[str],
    domain: Optional[str] = None,
    icp: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, bool, bool]:
    """
    Check if all required fields are complete for full enrichment.

    Args:
        company: Company data dictionary
        contacts: List of contact dictionaries
        best_contact_id: ID of the best contact
        domain: Domain field (at top level of record)
        icp: ICP data dictionary (at top level of record)

    Returns:
        Tuple of (company_complete, contact_complete, icp_match)
    """
    # Check company fields
    company_complete = True
    missing_company_fields = []

    for field in REQUIRED_COMPANY_FIELDS:
        if field == "domain":
            # Domain is at top level, not in company object
            if not domain:
                company_complete = False
                missing_company_fields.append(field)
        else:
            value = company.get(field)
            # Check if field is missing or contains "N/A" placeholder
            if (
                not value
                or value == "N/A"
                or (isinstance(value, str) and value.strip() == "N/A")
            ):
                company_complete = False
                missing_company_fields.append(field)

    # Check contact fields (best contact only)
    contact_complete = True
    missing_contact_fields = []

    if contacts and best_contact_id:
        best_contact = next(
            (c for c in contacts if c.get("contact_id") == best_contact_id), None
        )
        if best_contact:
            # Check full_name or first_name + last_name
            has_name = best_contact.get("full_name") or (
                best_contact.get("first_name") and best_contact.get("last_name")
            )
            if not has_name:
                missing_contact_fields.append("name")

            # Check role or job_title
            has_role = bool(best_contact.get("role") or best_contact.get("job_title"))
            if not has_role:
                missing_contact_fields.append("role")

            # Check email
            has_email = bool(best_contact.get("email"))
            if not has_email:
                missing_contact_fields.append("email")

            contact_complete = has_name and has_role and has_email
        else:
            contact_complete = False
            missing_contact_fields.append("best_contact_not_found")
    else:
        contact_complete = False
        missing_contact_fields.append("no_contacts")

    # Check ICP match
    icp_match = icp.get("pre_pass") if icp else False

    # Log missing fields for debugging
    if not company_complete or not contact_complete:
        missing_fields = {
            "company": missing_company_fields,
            "contact": missing_contact_fields,
            "icp_match": not icp_match,
        }
        logger = logging.getLogger("enrich")
        logger.info(f"Required fields missing: {missing_fields}")

    return company_complete, contact_complete, icp_match


# ============================================================================
# Main Tool Logic
# ============================================================================


async def run_enrich(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main enrichment function.

    Args:
        payload: Input payload with lead_records, icp_config, and caps

    Returns:
        Enrichment results with data, errors, and metrics
    """
    # Use the orchestrator's shared logger instead of creating a new one
    # The orchestrator sets LEADSORCERER_LOG_FILE environment variable
    data_dir = resolve_data_dir(payload)

    # Get the shared logger that the orchestrator set up
    logger = logging.getLogger("enrich")

    # If no handlers are set up, this means we're running standalone
    # In that case, set up logging properly
    if not logger.handlers:
        logger = setup_logging(TOOL_NAME, data_dir=data_dir)

    logger.info("🚀 Enrich tool run() started")
    start_time = time.time()

    try:
        # Validate input
        if not isinstance(payload, dict):
            return {
                "data": {"lead_records": []},
                "errors": [build_error(ErrorCode.SCHEMA_VALIDATION, tool=TOOL_NAME)],
                "metrics": build_metrics(0, 0, 0),
            }

        lead_records = payload.get("lead_records", [])
        icp_config = payload.get("icp_config", {})
        caps = payload.get("caps", {})

        if not lead_records or not icp_config:
            return {
                "data": {"lead_records": []},
                "errors": [build_error(ErrorCode.SCHEMA_VALIDATION, tool=TOOL_NAME)],
                "metrics": build_metrics(0, 0, 0),
            }

        # Validate testing flags
        try:
            logger.info("🔍 Validating testing flags...")
            logger.info(f"🔍 ICP config keys: {list(icp_config.keys())}")
            logger.info(f"🔍 Testing section: {icp_config.get('testing', 'NOT_FOUND')}")
            logger.info("🔍 About to call validate_testing_flags...")
            validate_testing_flags(icp_config)
            logger.info("🔍 validate_testing_flags returned successfully")
            logger.info("✅ Testing flags validation passed")
        except ValueError as exc:
            return {
                "data": {"lead_records": []},
                "errors": [
                    build_error(ErrorCode.SCHEMA_VALIDATION, exc=exc, tool=TOOL_NAME)
                ],
                "metrics": build_metrics(0, 0, 0),
            }

        # Load costs configuration
        try:
            logger.info("🔍 Loading costs configuration...")
            costs_config = load_costs_config()
            logger.info(f"✅ Costs config loaded: {list(costs_config.keys())}")

            # Provider validation now handled by router
            logger.info("✅ Provider configuration will be validated by router")
        except (FileNotFoundError, KeyError) as exc:
            return {
                "data": {"lead_records": []},
                "errors": [
                    build_error(ErrorCode.PROVIDER_ERROR, exc=exc, tool=TOOL_NAME)
                ],
                "metrics": build_metrics(0, 0, 0),
            }

        # Load schema checksum
        try:
            logger.info("🔍 Loading schema checksum...")
            schema_checksum = load_schema_checksum()
            logger.info(f"✅ Schema checksum loaded: {schema_checksum[:8]}...")
        except FileNotFoundError as exc:
            return {
                "data": {"lead_records": []},
                "errors": [
                    build_error(ErrorCode.SCHEMA_VALIDATION, exc=exc, tool=TOOL_NAME)
                ],
                "metrics": build_metrics(0, 0, 0),
            }

        # Data directory already resolved for logging setup above
        logger.info(f"✅ Using data directory: {data_dir}")

        # Note: Removed permit manager and semaphore pools since we no longer use file locking
        logger.info("🔍 Skipping concurrency controls (no file locking needed)")

        # Initialize provider clients
        logger.info("🔍 Checking environment variables...")
        mailgun_login = os.environ.get("MAILGUN_SMTP_LOGIN")
        mailgun_password = os.environ.get("MAILGUN_SMTP_PW")

        logger.info(
            f"🔑 Environment check - Mailgun: {'✅' if mailgun_login else '❌'}"
        )

        # Check which specific environment variables are missing
        missing_vars = []
        if not mailgun_login:
            missing_vars.append("MAILGUN_SMTP_LOGIN")
        if not mailgun_password:
            missing_vars.append("MAILGUN_SMTP_PW")

        if missing_vars:
            return {
                "data": {"lead_records": []},
                "errors": [
                    build_error(
                        ErrorCode.PROVIDER_ERROR,
                        tool=TOOL_NAME,
                        context={
                            "error": f"Missing required environment variables: {', '.join(missing_vars)}",
                            "missing_variables": missing_vars,
                            "expected_variables": [
                                "MAILGUN_SMTP_LOGIN",
                                "MAILGUN_SMTP_PW",
                            ],
                        },
                    )
                ],
                "metrics": build_metrics(0, 0, 0),
            }

        # Initialize enrichment provider router with shared logger
        enrichment_router = create_enrichment_router(icp_config, logger, costs_config)
        mailgun_client = MailgunClient(mailgun_login, mailgun_password)

        # Initialize Hunter.io client
        hunter_client = None
        hunter_api_key = os.environ.get("HUNTER_IO_API_KEY")
        if hunter_api_key:
            hunter_client = HunterIOClient(hunter_api_key)
            logger.info("✅ Hunter.io client initialized successfully")
        else:
            logger.warning(
                "⚠️ HUNTER_IO_API_KEY not configured - email verification will be limited to Mailgun"
            )

        # Get configuration values
        role_priority_config = icp_config.get("role_priority", {})
        # Ensure role_priority_config is a dictionary
        if not isinstance(role_priority_config, dict):
            logger.warning(
                f"⚠️ role_priority_config is not a dictionary: {type(role_priority_config)}, resetting to empty dict"
            )
            role_priority_config = {}

        default_country = icp_config.get("default_country", "US")
        run_usd_max = caps.get("run_usd_max", float("inf"))
        company_usd_cap = caps.get("company_usd", 0.02)
        contact_usd_cap = caps.get("contact_usd", 0.03)

        # Process each lead record
        processed_records = []
        errors = []
        total_cost = 0.0
        enriched_count = 0
        partial_count = 0

        logger.info(f"📋 About to process {len(lead_records)} lead records")
        for record in lead_records:
            try:
                # EARLY DEBUG: Log that we're starting to process a record
                logger.info(
                    f"🚀 Starting record processing for: {record.get('domain', 'UNKNOWN')}"
                )

                # Debug logging to see what record contains
                logger.info(
                    f"🔍 Processing record: type={type(record)}, content={record}"
                )

                # Check if we should process this record
                status = record.get("status", "")
                if status not in ["enrich_ready", "crawled"]:
                    # Skip records that aren't ready for enrichment
                    processed_records.append(record)
                    continue

                # Check if processing this lead would exceed run_usd_max
                if total_cost >= run_usd_max:
                    errors.append(
                        build_error(
                            ErrorCode.BUDGET_EXCEEDED,
                            tool=TOOL_NAME,
                            lead_id=record.get("lead_id"),
                            context={
                                "error": "Run budget exceeded",
                                "total_cost": total_cost,
                                "run_usd_max": run_usd_max,
                            },
                        )
                    )
                    # Skip this lead entirely
                    processed_records.append(record)
                    continue

                domain = record.get("domain", "")
                company = record.get("company", {})
                contacts = record.get("contacts", [])

                # Debug logging for contacts
                logger.info(f"🔍 Contacts field type for {domain}: {type(contacts)}")
                logger.info(f"🔍 Contacts field content for {domain}: {contacts}")

                # Ensure contacts is always a list
                if not isinstance(contacts, list):
                    logger.warning(
                        f"⚠️ Contacts field is not a list for {domain}, resetting to empty list"
                    )
                    contacts = []
                    record["contacts"] = contacts

                # Parse full names into first/last names for email discovery
                contacts = parse_contact_names(contacts, logger)

                # Normalize domain
                normalized_domain = normalize_domain(domain)
                record["domain"] = normalized_domain

                # Enrich company data first (cheaper)
                company_cost = 0.0
                if company_usd_cap > 0:
                    try:
                        logger.info(
                            f"🔍 About to call enrich_company_data for {normalized_domain}"
                        )
                        # Use router for company enrichment
                        request = EnrichmentRequest(domain=normalized_domain)
                        result = await enrichment_router.enrich_company(request)

                        if result.success and result.data:
                            # Map the enriched data to company fields
                            enriched_data = result.data
                            fields_updated = 0

                            # Handle both dataclass objects and dictionaries
                            if hasattr(enriched_data, "__dataclass_fields__"):
                                # It's a dataclass object, access attributes directly
                                # Don't override company name from AnymailFinder as it degrades data quality
                                # Only update name if we don't have one or if the enriched name is significantly better
                                if enriched_data.name and not company.get("name"):
                                    company["name"] = enriched_data.name
                                    fields_updated += 1
                                if enriched_data.description:
                                    company["description"] = enriched_data.description
                                    fields_updated += 1
                                if enriched_data.industry:
                                    company["industry"] = enriched_data.industry
                                    fields_updated += 1
                                if enriched_data.employee_count:
                                    company["employee_count"] = (
                                        enriched_data.employee_count
                                    )
                                    fields_updated += 1
                                if enriched_data.address:
                                    company["address"] = enriched_data.address
                                    fields_updated += 1
                                if enriched_data.technologies:
                                    company["technologies"] = enriched_data.technologies
                                    fields_updated += 1
                            else:
                                # It's a dictionary, use .get() method
                                # Don't override company name from AnymailFinder as it degrades data quality
                                # Only update name if we don't have one or if the enriched name is significantly better
                                if enriched_data.get("name") and not company.get(
                                    "name"
                                ):
                                    company["name"] = enriched_data["name"]
                                    fields_updated += 1
                                if enriched_data.get("description"):
                                    company["description"] = enriched_data[
                                        "description"
                                    ]
                                    fields_updated += 1
                                if enriched_data.get("industry"):
                                    company["industry"] = enriched_data["industry"]
                                    fields_updated += 1
                                if enriched_data.get("employee_count"):
                                    company["employee_count"] = enriched_data[
                                        "employee_count"
                                    ]
                                    fields_updated += 1
                                if enriched_data.get("address"):
                                    company["address"] = enriched_data["address"]
                                    fields_updated += 1
                                if enriched_data.get("technologies"):
                                    company["technologies"] = enriched_data[
                                        "technologies"
                                    ]
                                    fields_updated += 1

                            logger.info(
                                f"✅ Company enrichment completed for {normalized_domain}: {fields_updated} fields updated"
                            )
                            company_cost = result.cost
                        else:
                            logger.warning(
                                f"Company enrichment failed for {normalized_domain}: {result.error}"
                            )
                            company_cost = 0.0

                        enriched_company = company
                        logger.info(
                            f"🔍 enrich_company_data returned: type={type(enriched_company)}, content={enriched_company}"
                        )
                        company_cost = min(company_cost, company_usd_cap)
                        # Update the record's company data
                        record["company"] = enriched_company
                        company = enriched_company  # Update local company variable
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Company enrichment failed for {normalized_domain}: {e}"
                        )
                        # Continue with contact discovery even if company enrichment fails
                        company_cost = 0.0

                # Ensure company is always a dictionary for safety
                if not isinstance(company, dict):
                    logger.warning(
                        f"⚠️ Company data is not a dictionary for {normalized_domain}, resetting to empty dict"
                    )
                    company = {}
                    record["company"] = company

                # Debug logging to see what company contains
                logger.info(
                    f"🔍 Company data type for {normalized_domain}: {type(company)}"
                )
                logger.info(
                    f"🔍 Company data content for {normalized_domain}: {company}"
                )
                logger.info(
                    f"🔍 Record company field type: {type(record.get('company'))}"
                )
                logger.info(f"🔍 Record company field content: {record.get('company')}")

                # Normalize contact data from crawling to ensure consistent field names
                if contacts and len(contacts) > 0:
                    logger.info(
                        f"🔍 Normalizing {len(contacts)} contacts from crawling for {normalized_domain}"
                    )

                    normalized_contacts = []
                    for contact in contacts:
                        normalized_contact = contact.copy()

                        # Handle different field names from crawling
                        if "name" in normalized_contact and not (
                            "first_name" in normalized_contact
                            or "last_name" in normalized_contact
                        ):
                            # Split full name into first and last name
                            full_name = normalized_contact.pop("name", "")
                            if full_name and full_name != "null":
                                name_parts = full_name.split(" ", 1)
                                if len(name_parts) >= 2:
                                    normalized_contact["first_name"] = name_parts[0]
                                    normalized_contact["last_name"] = name_parts[1]
                                else:
                                    normalized_contact["first_name"] = full_name
                                    normalized_contact["last_name"] = ""

                        # Handle role field mapping
                        if (
                            "role" in normalized_contact
                            and "job_title" not in normalized_contact
                        ):
                            normalized_contact["job_title"] = normalized_contact.pop(
                                "role", ""
                            )

                        # Handle phone field mapping
                        if "phone" in normalized_contact:
                            phone = normalized_contact["phone"]
                            if phone and phone != "null":
                                normalized_contact["phone"] = phone

                        # Handle email field mapping (clean up "null" strings)
                        if "email" in normalized_contact:
                            email = normalized_contact["email"]
                            if email == "null" or not email:
                                normalized_contact["email"] = None

                        normalized_contacts.append(normalized_contact)

                    # Use normalized contacts for all subsequent processing
                    contacts = normalized_contacts
                    record["contacts"] = contacts
                    logger.info(
                        f"✅ Contact normalization completed for {normalized_domain}"
                    )

                # STEP 1: Verify ALL existing emails with Hunter.io (from crawl, apollo, etc.)
                if contacts and hunter_client:
                    logger.info(
                        f"🔍 Hunter.io: Step 1 - Verifying all existing emails for {normalized_domain}"
                    )
                    (
                        contacts,
                        hunter_cost_1,
                    ) = await verify_all_contact_emails_with_hunter(
                        contacts=contacts,
                        hunter_client=hunter_client,
                        domain=normalized_domain,
                        logger=logger,
                        costs_config=costs_config,
                        min_score=icp_config.get("hunter_min_score", 70),
                    )
                    record["contacts"] = contacts
                    total_cost += hunter_cost_1

                    # Log Hunter.io verification summary
                    verified_emails = [c for c in contacts if c.get("email_verified")]
                    failed_emails = [
                        c
                        for c in contacts
                        if c.get("email") and not c.get("email_verified")
                    ]
                    discarded_emails = [c for c in contacts if c.get("email") is None]
                    logger.info(
                        f"📊 Hunter.io Summary for {normalized_domain}: {len(verified_emails)} verified, {len(failed_emails)} failed, {len(discarded_emails)} discarded (0% score)"
                    )

                # STEP 2: Discover and verify emails for contacts that need them
                if contacts and hunter_client:
                    logger.info(
                        f"🔍 Hunter.io: Step 2 - Discovering and verifying missing/poor emails for {normalized_domain}"
                    )
                    (
                        contacts,
                        hunter_cost_2,
                    ) = await discover_and_verify_emails_with_hunter(
                        contacts=contacts,
                        domain=normalized_domain,
                        enrichment_router=enrichment_router,
                        hunter_client=hunter_client,
                        logger=logger,
                        costs_config=costs_config,
                        min_score=icp_config.get("hunter_min_score", 70),
                    )
                    record["contacts"] = contacts
                    total_cost += hunter_cost_2

                # Re-evaluate decision maker status for all contacts based on ICP configuration
                logger.info(
                    f"🔍 Re-evaluating decision maker status for {len(contacts)} contacts based on ICP configuration"
                )

                # Get decision maker configuration from ICP config
                decision_maker_config = icp_config.get("decision_makers", {})
                decision_maker_threshold = decision_maker_config.get(
                    "priority_threshold", 10
                )

                # Build decision maker titles from role_priority
                decision_maker_titles = []
                for role, priority in role_priority_config.items():
                    if priority <= decision_maker_threshold:
                        decision_maker_titles.append(role.title())

                decision_set = {t.lower() for t in decision_maker_titles}

                # Re-evaluate each contact's decision maker status
                for contact in contacts:
                    role = contact.get("role") or contact.get("job_title", "")
                    if role:
                        role_lower = role.lower()
                        is_decision_maker = False

                        # Check exact matches
                        if role_lower in decision_set:
                            is_decision_maker = True
                        else:
                            # Check partial matches
                            for decision_title in decision_set:
                                if (
                                    decision_title in role_lower
                                    or role_lower in decision_title
                                ):
                                    is_decision_maker = True
                                    break

                        # Update decision maker status
                        contact["decision_maker"] = is_decision_maker
                        logger.info(
                            f"🔍 Contact {contact.get('full_name', 'Unknown')} ({role}): decision_maker={is_decision_maker}"
                        )

                # Contact selection will happen after contact discovery
                llm_selection_cost = 0.0  # Initialize cost tracking

                # Enrich contacts (only if within budget)
                contact_cost = 0.0

                # Log the current state before contact discovery
                logger.info(
                    f"🔍 About to start contact discovery logic for {normalized_domain}"
                )
                logger.info(f"🔍 Current contacts list: {contacts}")
                logger.info(f"🔍 Contact USD cap: {contact_usd_cap}")
                logger.info(
                    f"🔍 Force contact discovery flag: {icp_config.get('testing', {}).get('force_contact_discovery', False)}"
                )

                # If no contacts exist, try to discover them using Snov.io
                if (
                    not contacts
                    or icp_config.get("testing", {}).get(
                        "force_contact_discovery", False
                    )
                ) and contact_usd_cap > 0:
                    # Debug logging to see what's happening
                    logger.info(f"🔍 DEBUG: contacts list length: {len(contacts)}")
                    logger.info(
                        f"🔍 DEBUG: force_contact_discovery flag: {icp_config.get('testing', {}).get('force_contact_discovery', False)}"
                    )
                    logger.info(f"🔍 DEBUG: contact_usd_cap: {contact_usd_cap}")

                    # If force_contact_discovery is enabled, preserve existing contacts and add discovered ones
                    existing_contacts = contacts.copy()  # Preserve crawled contacts
                    if icp_config.get("testing", {}).get(
                        "force_contact_discovery", False
                    ):
                        logger.info(
                            f"🔍 Force contact discovery enabled for {normalized_domain}, will attempt to discover additional contacts while preserving existing {len(existing_contacts)} contacts..."
                        )
                        logger.info(
                            f"🔍 DEBUG: Existing contacts preserved: {len(existing_contacts)}"
                        )

                    logger.info(
                        f"🔍 {'No contacts found' if not contacts else 'Force contact discovery enabled'} for {normalized_domain}, attempting contact discovery..."
                    )

                    # Check provider health before attempting contact discovery
                    health_summary = enrichment_router.get_provider_health_summary()
                    logger.info(f"🔍 Provider health status: {health_summary}")

                    if health_summary["available_providers"] == 0:
                        logger.warning(
                            f"⚠️ No healthy providers available for contact discovery on {normalized_domain}"
                        )
                        logger.warning(
                            f"⚠️ Unhealthy providers: {', '.join(health_summary['unhealthy_providers'])}"
                        )

                    try:
                        # Use router for contact discovery
                        try:
                            request = EnrichmentRequest(domain=normalized_domain)
                            result = await enrichment_router.get_all_domain_prospects(
                                request
                            )

                            if result.success and result.data:
                                prospects_data = result.data
                                discovered_contacts = []

                                # Process prospects data to extract contacts
                                if (
                                    isinstance(prospects_data, dict)
                                    and "data" in prospects_data
                                ):
                                    prospects = prospects_data["data"]
                                elif isinstance(prospects_data, list):
                                    prospects = prospects_data
                                else:
                                    prospects = []

                                # Build decision-maker titles from ICP config
                                # Configuration structure:
                                # "decision_makers": {
                                #   "priority_threshold": 10,  // Max priority to include
                                #   "include_variations": true,  // Whether to add title variations
                                #   "title_variations": {  // Custom variations per role
                                #     "ceo": ["CEO", "Founder & CEO", "CEO and Founder"],
                                #     "owner": ["Founder", "Proprietor"]
                                #   },
                                #   "common_variations": {  // Fallback variations for key roles
                                #     "ceo": ["Chief Executive Officer", "CEO"]
                                #   },
                                #   "manager_titles": ["Operations Manager", "General Manager"]
                                # }
                                role_priority = icp_config.get("role_priority", {})
                                decision_maker_titles = []

                                # Get decision maker configuration from ICP config
                                decision_maker_config = icp_config.get(
                                    "decision_makers", {}
                                )
                                decision_maker_threshold = decision_maker_config.get(
                                    "priority_threshold", 10
                                )
                                title_variations = decision_maker_config.get(
                                    "title_variations", {}
                                )
                                include_variations = decision_maker_config.get(
                                    "include_variations", True
                                )

                                for role, priority in role_priority.items():
                                    if priority <= decision_maker_threshold:
                                        decision_maker_titles.append(role.title())

                                        # Add title variations if enabled and configured
                                        if include_variations and title_variations:
                                            role_lower = role.lower()
                                            if role_lower in title_variations:
                                                decision_maker_titles.extend(
                                                    title_variations[role_lower]
                                                )

                                            # Fallback to common variations for key roles if not explicitly configured
                                            elif role_lower in [
                                                "ceo",
                                                "owner",
                                                "president",
                                                "vp",
                                                "director",
                                                "head",
                                            ]:
                                                common_variations = (
                                                    decision_maker_config.get(
                                                        "common_variations", {}
                                                    ).get(role_lower, [])
                                                )
                                                if common_variations:
                                                    decision_maker_titles.extend(
                                                        common_variations
                                                    )

                                        # Handle manager titles specifically
                                        elif role.lower() == "manager":
                                            manager_titles = decision_maker_config.get(
                                                "manager_titles", []
                                            )
                                            if manager_titles:
                                                decision_maker_titles.extend(
                                                    manager_titles
                                                )

                                decision_set = {
                                    t.lower() for t in decision_maker_titles
                                }

                                # Log decision maker configuration for debugging
                                logger.info(
                                    f"🔍 Decision maker configuration for {normalized_domain}:"
                                )
                                logger.info(
                                    f"   Priority threshold: {decision_maker_threshold}"
                                )
                                logger.info(
                                    f"   Include variations: {include_variations}"
                                )
                                logger.info(
                                    f"   Total decision maker titles: {len(decision_maker_titles)}"
                                )
                                if decision_maker_titles:
                                    logger.info(
                                        f"   Sample titles: {decision_maker_titles[:5]}"
                                    )
                                if title_variations:
                                    logger.info(
                                        f"   Custom variations configured for: {list(title_variations.keys())}"
                                    )

                                # Process prospects and build contacts
                                for profile in prospects[:5]:  # Limit to 5 contacts
                                    # Handle both ContactData objects and dictionaries
                                    if hasattr(profile, "__dataclass_fields__"):
                                        # It's a ContactData object, access attributes directly
                                        title_value = profile.job_title or ""
                                        first_name = profile.first_name or ""
                                        last_name = profile.last_name or ""
                                        company_name = profile.company_name or ""
                                        linkedin_url = profile.linkedin_url or ""
                                        location = profile.location or ""
                                    else:
                                        # It's a dictionary, use .get() method
                                        title_value = (
                                            profile.get("jobTitle")
                                            or profile.get("position")
                                            or profile.get("title")
                                            or ""
                                        )
                                        first_name = profile.get("firstName", "")
                                        last_name = profile.get("lastName", "")
                                        company_name = profile.get("company", "")
                                        linkedin_url = profile.get("linkedinUrl", "")
                                        location = profile.get("location", "")

                                    # Check if title matches any decision-maker role
                                    is_decision_maker = False
                                    if title_value:
                                        title_lower = title_value.lower()
                                        # Check for exact matches first
                                        if title_lower in decision_set:
                                            is_decision_maker = True
                                        else:
                                            # Check for partial matches (e.g., "Founder & CEO" contains "founder")
                                            for decision_title in decision_set:
                                                if (
                                                    decision_title in title_lower
                                                    or title_lower in decision_title
                                                ):
                                                    is_decision_maker = True
                                                    break

                                    if not is_decision_maker:
                                        logger.info(
                                            f"🔍 Skipping contact with non-decision-maker title: '{title_value}'"
                                        )
                                        continue

                                    contact = {
                                        "contact_id": f"discovered_{len(discovered_contacts)}",
                                        "first_name": first_name,
                                        "last_name": last_name,
                                        "email": "",
                                        "job_title": title_value,
                                        "company": company_name,
                                        "linkedin_url": linkedin_url,
                                        "location": location,
                                        "discovery_source": "router",
                                        "discovery_method": "domain_prospects",
                                    }

                                    # Try to discover email for this prospect
                                    if hasattr(profile, "__dataclass_fields__"):
                                        # ContactData object - check if email is already available
                                        if profile.email:
                                            contact["email"] = profile.email
                                            contact["email_source"] = ["provider"]
                                            contact["email_status"] = [
                                                profile.email_status or "unknown"
                                            ]
                                            logger.info(
                                                f"✅ Found email from ContactData: {contact['email']} for {contact['first_name']} {contact['last_name']}"
                                            )

                                            # IMMEDIATE Hunter.io verification
                                            if hunter_client:
                                                logger.info(
                                                    f"🔍 Hunter.io: Verifying ContactData email {contact['email']} for {contact['first_name']} {contact['last_name']}"
                                                )
                                                hunter_result = (
                                                    await hunter_client.verify_email(
                                                        contact["email"], logger
                                                    )
                                                )
                                                contact["hunter_verification"] = (
                                                    hunter_result
                                                )
                                                contact["email_quality_score"] = (
                                                    hunter_result.get("score", 0)
                                                )

                                                score = hunter_result.get("score", 0)
                                                min_score = icp_config.get(
                                                    "hunter_min_score", 70
                                                )

                                                if (
                                                    score >= min_score
                                                    and hunter_result.get("status")
                                                    in ["valid", "deliverable"]
                                                ):
                                                    contact["email_verified"] = True
                                                    contact["email_source"] = [
                                                        "provider",
                                                        "hunter_verified",
                                                    ]
                                                    logger.info(
                                                        f"✅ ContactData email verified: {contact['email']} (score: {score}%)"
                                                    )

                                                    # Enhanced quality insights logging
                                                    if score >= 90:
                                                        logger.info(
                                                            "   🏆 High-quality email (90%+) - excellent deliverability"
                                                        )
                                                    elif score >= 80:
                                                        logger.info(
                                                            "   🥇 Good quality email (80-89%) - good deliverability"
                                                        )
                                                    elif score >= 70:
                                                        logger.info(
                                                            "   🥈 Acceptable quality email (70-79%) - acceptable deliverability"
                                                        )
                                                else:
                                                    contact["email_verified"] = False
                                                    contact[
                                                        "needs_email_replacement"
                                                    ] = True
                                                    logger.warning(
                                                        f"❌ ContactData email failed verification: {contact['email']} (score: {score}%)"
                                                    )

                                                    # Enhanced failure insights logging
                                                    if score < 50:
                                                        logger.info(
                                                            "   🚨 Very low quality (0-49%) - high bounce risk"
                                                        )
                                                    elif score < 70:
                                                        logger.info(
                                                            "   ⚠️ Below threshold (50-69%) - moderate bounce risk"
                                                        )

                                                    # Log specific status insights
                                                    status = hunter_result.get(
                                                        "status", "unknown"
                                                    )
                                                    if status == "risky":
                                                        logger.info(
                                                            "   ⚡ Risky email status - proceed with caution"
                                                        )
                                                    elif status == "invalid":
                                                        logger.info(
                                                            "   ❌ Invalid email format or domain"
                                                        )
                                                    elif status == "unknown":
                                                        logger.info(
                                                            "   🤔 Unknown status - verification inconclusive"
                                                        )

                                                # Track Hunter.io cost
                                                if "costs" not in contact:
                                                    contact["costs"] = {}
                                                if "hunter_io" not in contact["costs"]:
                                                    contact["costs"]["hunter_io"] = 0.0
                                                contact["costs"]["hunter_io"] += (
                                                    hunter_result.get("cost_usd", 0.0)
                                                )
                                    else:
                                        # Dictionary - check for prospect hash
                                        if (
                                            profile.get("prospectHash")
                                            or profile.get("hash")
                                            or profile.get("id")
                                        ):
                                            try:
                                                prospect_request = EnrichmentRequest(
                                                    prospect_hash=profile.get(
                                                        "prospectHash"
                                                    )
                                                    or profile.get("hash")
                                                    or profile.get("id")
                                                )
                                                email_result = await enrichment_router.search_prospect_email(
                                                    prospect_request
                                                )

                                                if (
                                                    email_result.success
                                                    and email_result.data
                                                ):
                                                    email_data = email_result.data
                                                    if (
                                                        isinstance(email_data, list)
                                                        and len(email_data) > 0
                                                    ):
                                                        first_email = email_data[0]
                                                        if isinstance(
                                                            first_email, dict
                                                        ) and first_email.get("email"):
                                                            contact["email"] = (
                                                                first_email["email"]
                                                            )
                                                            logger.info(
                                                                f"✅ Found email for {contact['first_name']} {contact['last_name']}: {contact['email']}"
                                                            )

                                                            # IMMEDIATE Hunter.io verification
                                                            if hunter_client:
                                                                logger.info(
                                                                    f"🔍 Hunter.io: Verifying API response email {contact['email']} for {contact['first_name']} {contact['last_name']}"
                                                                )
                                                                hunter_result = await hunter_client.verify_email(
                                                                    contact["email"],
                                                                    logger,
                                                                )
                                                                contact[
                                                                    "hunter_verification"
                                                                ] = hunter_result
                                                                contact[
                                                                    "email_quality_score"
                                                                ] = hunter_result.get(
                                                                    "score", 0
                                                                )

                                                                score = (
                                                                    hunter_result.get(
                                                                        "score", 0
                                                                    )
                                                                )
                                                                min_score = icp_config.get(
                                                                    "hunter_min_score",
                                                                    70,
                                                                )

                                                                if (
                                                                    score >= min_score
                                                                    and hunter_result.get(
                                                                        "status"
                                                                    )
                                                                    in [
                                                                        "valid",
                                                                        "deliverable",
                                                                    ]
                                                                ):
                                                                    contact[
                                                                        "email_verified"
                                                                    ] = True
                                                                    contact[
                                                                        "email_source"
                                                                    ] = [
                                                                        "provider",
                                                                        "hunter_verified",
                                                                    ]
                                                                    logger.info(
                                                                        f"✅ API response email verified: {contact['email']} (score: {score}%)"
                                                                    )

                                                                    # Enhanced quality insights logging
                                                                    if score >= 90:
                                                                        logger.info(
                                                                            "   🏆 High-quality email (90%+) - excellent deliverability"
                                                                        )
                                                                    elif score >= 80:
                                                                        logger.info(
                                                                            "   🥇 Good quality email (80-89%) - good deliverability"
                                                                        )
                                                                    elif score >= 70:
                                                                        logger.info(
                                                                            "   🥈 Acceptable quality email (70-79%) - acceptable deliverability"
                                                                        )
                                                                else:
                                                                    contact[
                                                                        "email_verified"
                                                                    ] = False
                                                                    contact[
                                                                        "needs_email_replacement"
                                                                    ] = True
                                                                    logger.warning(
                                                                        f"❌ API response email failed verification: {contact['email']} (score: {score}%)"
                                                                    )

                                                                    # Enhanced failure insights logging
                                                                    if score < 50:
                                                                        logger.info(
                                                                            "   🚨 Very low quality (0-49%) - high bounce risk"
                                                                        )
                                                                    elif score < 70:
                                                                        logger.info(
                                                                            "   ⚠️ Below threshold (50-69%) - moderate bounce risk"
                                                                        )

                                                                    # Log specific status insights
                                                                    status = hunter_result.get(
                                                                        "status",
                                                                        "unknown",
                                                                    )
                                                                    if (
                                                                        status
                                                                        == "risky"
                                                                    ):
                                                                        logger.info(
                                                                            "   ⚡ Risky email status - proceed with caution"
                                                                        )
                                                                    elif (
                                                                        status
                                                                        == "invalid"
                                                                    ):
                                                                        logger.info(
                                                                            "   ❌ Invalid email format or domain"
                                                                        )
                                                                    elif (
                                                                        status
                                                                        == "unknown"
                                                                    ):
                                                                        logger.info(
                                                                            "   🤔 Unknown status - verification inconclusive"
                                                                        )

                                                                # Track Hunter.io cost
                                                                if (
                                                                    "costs"
                                                                    not in contact
                                                                ):
                                                                    contact[
                                                                        "costs"
                                                                    ] = {}
                                                                if (
                                                                    "hunter_io"
                                                                    not in contact[
                                                                        "costs"
                                                                    ]
                                                                ):
                                                                    contact["costs"][
                                                                        "hunter_io"
                                                                    ] = 0.0
                                                                contact["costs"][
                                                                    "hunter_io"
                                                                ] += hunter_result.get(
                                                                    "cost_usd", 0.0
                                                                )
                                            except Exception as exc:
                                                logger.warning(
                                                    f"Email discovery failed for prospect: {exc}"
                                                )

                                    # Only add if we have identifying info
                                    has_identifying_info = (
                                        (contact["first_name"] and contact["last_name"])
                                        or contact["email"]
                                        or contact["job_title"]
                                    )

                                    if has_identifying_info:
                                        # Check for duplicates
                                        is_duplicate = any(
                                            c.get("email") == contact["email"]
                                            and contact["email"]
                                            or (
                                                c.get("first_name")
                                                == contact["first_name"]
                                                and c.get("last_name")
                                                == contact["last_name"]
                                                and contact["first_name"]
                                                and contact["last_name"]
                                            )
                                            for c in discovered_contacts
                                        )

                                        if not is_duplicate:
                                            discovered_contacts.append(contact)
                                            logger.info(
                                                f"✅ Discovered contact: {contact['first_name']} {contact['last_name']} - {contact['job_title']} - {contact['email']}"
                                            )

                                if discovered_contacts:
                                    logger.info(
                                        f"🎯 Successfully discovered {len(discovered_contacts)} contacts for {normalized_domain}"
                                    )
                                else:
                                    logger.warning(
                                        f"❌ No contacts discovered for {normalized_domain}"
                                    )
                            else:
                                discovered_contacts = []
                                logger.warning(
                                    f"Contact discovery failed for {normalized_domain}: {result.error}"
                                )
                        except Exception as exc:
                            discovered_contacts = []
                            logger.warning(
                                f"Contact discovery failed for {normalized_domain}: {exc}"
                            )

                        if discovered_contacts:
                            # Merge discovered contacts with existing ones, avoiding duplicates
                            merged_contacts = existing_contacts.copy()
                            for discovered_contact in discovered_contacts:
                                # Check for duplicates based on email or name
                                is_duplicate = any(
                                    (
                                        existing.get("email")
                                        == discovered_contact.get("email")
                                        and discovered_contact.get("email")
                                    )
                                    or (
                                        existing.get("full_name")
                                        == discovered_contact.get("full_name")
                                        and discovered_contact.get("full_name")
                                    )
                                    for existing in merged_contacts
                                )
                                if not is_duplicate:
                                    merged_contacts.append(discovered_contact)

                            contacts = merged_contacts
                            record["contacts"] = contacts
                            logger.info(
                                f"✅ Merged {len(discovered_contacts)} discovered contacts with {len(existing_contacts)} existing contacts = {len(contacts)} total for {normalized_domain}"
                            )
                        else:
                            logger.warning(
                                f"⚠️ No contacts discovered for {normalized_domain}"
                            )
                    except Exception as contact_discovery_error:
                        # Check if it's a credit exhaustion error
                        if "402 Payment Required" in str(contact_discovery_error):
                            logger.warning(
                                f"⚠️ Snov.io API credits exhausted for {normalized_domain} - skipping contact discovery"
                            )
                        else:
                            logger.warning(
                                f"⚠️ Contact discovery failed for {normalized_domain}: {contact_discovery_error}"
                            )
                        # Continue without contacts rather than failing the entire enrichment

                # NEW: Enrich existing contacts with emails (when contacts already exist from crawling)
                if contacts and len(contacts) > 0 and contact_usd_cap > 0:
                    logger.info(
                        f"🔍 Enriching {len(contacts)} existing contacts for {normalized_domain} with email discovery"
                    )

                    # Find the best contact for ICP (prioritize by role priority and decision maker status)
                    best_contact = None
                    best_contact_score = -1

                    for contact in contacts:
                        contact_score = 0

                        # Check if contact is a decision maker
                        if contact.get("decision_maker"):
                            contact_score += 100

                        # Check role priority
                        job_title = (contact.get("job_title") or "").lower()
                        role_priority = icp_config.get("role_priority", {})

                        for role, priority in role_priority.items():
                            if role.lower() in job_title:
                                contact_score += (
                                    10 - priority
                                ) * 10  # Higher priority = higher score
                                break

                        # Check if contact has a name
                        if contact.get("first_name") and contact.get("last_name"):
                            contact_score += 10

                        # Check if contact already has email
                        if contact.get("email"):
                            contact_score -= 50  # Prefer contacts without emails

                        if contact_score > best_contact_score:
                            best_contact_score = contact_score
                            best_contact = contact

                    if best_contact and not best_contact.get("email"):
                        first_name = best_contact.get("first_name", "")
                        last_name = best_contact.get("last_name", "")
                        job_title = best_contact.get("job_title", "")

                        logger.info(
                            f"🎯 Enriching best contact for ICP: {first_name} {last_name} ({job_title}) at {normalized_domain}"
                        )

                        try:
                            # Try to discover email for the best contact
                            email_request = EnrichmentRequest(
                                domain=normalized_domain,
                                first_name=first_name,
                                last_name=last_name,
                            )
                            email_result = await enrichment_router.find_email(
                                email_request
                            )

                            if email_result.success and email_result.data:
                                # Update the existing contact with the discovered email
                                email_data = email_result.data
                                if hasattr(email_data, "__dataclass_fields__"):
                                    # It's a ContactData object
                                    discovered_email = email_data.email
                                else:
                                    # It's a dictionary
                                    discovered_email = email_data.get("email", "")

                                if discovered_email:
                                    best_contact["email"] = discovered_email
                                    best_contact["email_source"] = ["provider"]
                                    best_contact["email_status"] = ["unknown"]
                                    best_contact["email_confidence"] = 0.0

                                    # IMMEDIATE Hunter.io verification
                                    if hunter_client:
                                        logger.info(
                                            f"🔍 Hunter.io: Verifying best contact email {discovered_email} for {first_name} {last_name}"
                                        )
                                        hunter_result = (
                                            await hunter_client.verify_email(
                                                discovered_email, logger
                                            )
                                        )
                                        best_contact["hunter_verification"] = (
                                            hunter_result
                                        )
                                        best_contact["email_quality_score"] = (
                                            hunter_result.get("score", 0)
                                        )

                                        score = hunter_result.get("score", 0)
                                        min_score = icp_config.get(
                                            "hunter_min_score", 70
                                        )

                                        if score >= min_score and hunter_result.get(
                                            "status"
                                        ) in ["valid", "deliverable"]:
                                            best_contact["email_verified"] = True
                                            best_contact["email_source"] = [
                                                "provider",
                                                "hunter_verified",
                                            ]
                                            logger.info(
                                                f"✅ Best contact email verified: {discovered_email} (score: {score}%)"
                                            )
                                        else:
                                            best_contact["email_verified"] = False
                                            best_contact["needs_email_replacement"] = (
                                                True
                                            )
                                            logger.warning(
                                                f"❌ Best contact email failed verification: {discovered_email} (score: {score}%)"
                                            )

                                        # Track Hunter.io cost
                                        if "costs" not in best_contact:
                                            best_contact["costs"] = {}
                                        if "hunter_io" not in best_contact["costs"]:
                                            best_contact["costs"]["hunter_io"] = 0.0
                                        best_contact["costs"]["hunter_io"] += (
                                            hunter_result.get("cost_usd", 0.0)
                                        )

                                    logger.info(
                                        f"✅ Email enrichment successful for {first_name} {last_name}: {discovered_email}"
                                    )

                                    # Add to cost tracking
                                    contact_cost += email_result.cost

                                    # Update the record with enriched contact
                                    record["contacts"] = contacts
                                else:
                                    logger.warning(
                                        f"⚠️ Email discovery returned no email for {first_name} {last_name}"
                                    )
                            else:
                                logger.warning(
                                    f"⚠️ Email discovery failed for {first_name} {last_name}: {email_result.error}"
                                )

                        except Exception as exc:
                            logger.warning(
                                f"⚠️ Email enrichment failed for {first_name} {last_name}: {exc}"
                            )
                    elif best_contact and best_contact.get("email"):
                        logger.info(
                            f"✅ Best contact {best_contact.get('first_name')} {best_contact.get('last_name')} already has email: {best_contact.get('email')}"
                        )
                    else:
                        logger.info(
                            f"⚠️ No suitable contact found for email enrichment in {normalized_domain}"
                        )

                # WORKFLOW COORDINATION: Coordinated email discovery with proper fallback logic
                if contacts and len(contacts) > 0:
                    # Find the best contact for email discovery
                    best_contact = None
                    for contact in contacts:
                        if contact.get("first_name") and contact.get("last_name"):
                            best_contact = contact
                            break

                    if best_contact:
                        first_name = best_contact.get("first_name", "")
                        last_name = best_contact.get("last_name", "")
                        logger.info(
                            f"🔄 WORKFLOW: Starting coordinated email discovery for {first_name} {last_name} at {normalized_domain}..."
                        )

                        # STEP 1: Standalone Email Discovery → Hunter.io verification → Create contact if valid
                        standalone_success = False
                        try:
                            logger.info(
                                f"🔍 STEP 1: Attempting standalone email discovery for {first_name} {last_name}"
                            )
                            email_request = EnrichmentRequest(
                                domain=normalized_domain,
                                first_name=first_name,
                                last_name=last_name,
                            )
                            email_result = await enrichment_router.find_email(
                                email_request
                            )

                            if email_result.success and email_result.data:
                                # Create a contact entry for the discovered email
                                email_data = email_result.data
                                if hasattr(email_data, "__dataclass_fields__"):
                                    # It's a ContactData object
                                    discovered_email = email_data.email
                                    email_first_name = email_data.first_name or ""
                                    email_last_name = email_data.last_name or ""
                                    job_title = email_data.job_title or ""
                                else:
                                    # It's a dictionary
                                    discovered_email = email_data.get("email", "")
                                    email_first_name = email_data.get("first_name", "")
                                    email_last_name = email_data.get("last_name", "")
                                    job_title = email_data.get("job_title", "")

                                if discovered_email:
                                    # STEP 1: Verify email with Hunter.io BEFORE creating contact
                                    if hunter_client:
                                        logger.info(
                                            f"🔍 Hunter.io: Verifying discovered email {discovered_email} before creating contact"
                                        )
                                        hunter_result = (
                                            await hunter_client.verify_email(
                                                discovered_email, logger
                                            )
                                        )

                                        score = hunter_result.get("score", 0)
                                        status = hunter_result.get("status", "unknown")
                                        min_score = icp_config.get(
                                            "hunter_min_score", 70
                                        )

                                        # STEP 2: Only create contact if email passes verification
                                        if score >= min_score and status in [
                                            "valid",
                                            "deliverable",
                                        ]:
                                            # Create contact with verified email
                                            email_contact = {
                                                "contact_id": f"email_discovery_{len(contacts)}",
                                                "first_name": email_first_name,
                                                "last_name": email_last_name,
                                                "email": discovered_email,
                                                "job_title": job_title,
                                                "company": company.get("name", ""),
                                                "discovery_source": "email_discovery",
                                                "discovery_method": "domain_email_search",
                                                "email_source": [
                                                    "provider",
                                                    "hunter_verified",
                                                ],
                                                "email_status": ["unknown"],
                                                "hunter_verification": hunter_result,
                                                "email_quality_score": score,
                                                "email_verified": True,
                                            }

                                            # Add to contacts list
                                            contacts.append(email_contact)
                                            standalone_success = True
                                            logger.info(
                                                f"✅ STEP 1 SUCCESS: Created contact with verified email: {discovered_email} (score: {score}%)"
                                            )

                                            # Enhanced quality insights logging
                                            if score >= 90:
                                                logger.info(
                                                    "   🏆 High-quality email (90%+) - excellent deliverability"
                                                )
                                            elif score >= 80:
                                                logger.info(
                                                    "   🥇 Good quality email (80-89%) - good deliverability"
                                                )
                                            elif score >= 70:
                                                logger.info(
                                                    "   🥈 Acceptable quality email (70-79%) - acceptable deliverability"
                                                )
                                        else:
                                            # STEP 3: Email failed verification - don't create contact
                                            logger.warning(
                                                f"❌ STEP 1 FAILED: Discovered email {discovered_email} failed verification (score: {score}%) - proceeding to STEP 2"
                                            )

                                            # Enhanced failure insights logging
                                            if score < 50:
                                                logger.info(
                                                    "   🚨 Very low quality (0-49%) - high bounce risk"
                                                )
                                            elif score < 70:
                                                logger.info(
                                                    "   ⚠️ Below threshold (50-69%) - moderate bounce risk"
                                                )

                                            # Log specific status insights
                                            if status == "risky":
                                                logger.info(
                                                    "   ⚡ Risky email status - proceed with caution"
                                                )
                                            elif status == "invalid":
                                                logger.info(
                                                    "   ❌ Invalid email format or domain"
                                                )
                                            elif status == "unknown":
                                                logger.info(
                                                    "   🤔 Unknown status - verification inconclusive"
                                                )

                                        # Always track Hunter.io cost
                                        total_cost += hunter_result.get("cost_usd", 0.0)
                                    else:
                                        # No Hunter.io client - create contact without verification (fallback)
                                        email_contact = {
                                            "contact_id": f"email_discovery_{len(contacts)}",
                                            "first_name": email_first_name,
                                            "last_name": email_last_name,
                                            "email": discovered_email,
                                            "job_title": job_title,
                                            "company": company.get("name", ""),
                                            "discovery_source": "email_discovery",
                                            "discovery_method": "domain_email_search",
                                            "email_source": ["provider"],
                                            "email_status": ["unknown"],
                                        }

                                        # Add to contacts list
                                        contacts.append(email_contact)
                                        standalone_success = True
                                        logger.info(
                                            f"✅ STEP 1 SUCCESS: Email discovery found (no Hunter.io): {discovered_email} for {normalized_domain}"
                                        )

                                    # Add to cost tracking
                                    single_contact_cost = email_result.cost
                                    contact_cost += single_contact_cost

                        except Exception as exc:
                            logger.warning(
                                f"❌ STEP 1 FAILED: Standalone email discovery failed for {normalized_domain}: {exc}"
                            )

                        # STEP 2: If standalone fails → Best Contact Enrichment → Hunter.io verification → Update contact if valid
                        if (
                            not standalone_success
                            and best_contact
                            and not best_contact.get("email")
                        ):
                            try:
                                logger.info(
                                    f"🔄 STEP 2: Attempting best contact enrichment for {first_name} {last_name}"
                                )
                                email_request = EnrichmentRequest(
                                    domain=normalized_domain,
                                    first_name=first_name,
                                    last_name=last_name,
                                )
                                email_result = await enrichment_router.find_email(
                                    email_request
                                )

                                if email_result.success and email_result.data:
                                    # Update the existing contact with the discovered email
                                    email_data = email_result.data
                                    if hasattr(email_data, "__dataclass_fields__"):
                                        # It's a ContactData object
                                        discovered_email = email_data.email
                                    else:
                                        # It's a dictionary
                                        discovered_email = email_data.get("email", "")

                                    if discovered_email:
                                        best_contact["email"] = discovered_email
                                        best_contact["email_source"] = ["provider"]
                                        best_contact["email_status"] = ["unknown"]
                                        best_contact["email_confidence"] = 0.0

                                        # IMMEDIATE Hunter.io verification
                                        if hunter_client:
                                            logger.info(
                                                f"🔍 Hunter.io: Verifying best contact email {discovered_email} for {first_name} {last_name}"
                                            )
                                            hunter_result = (
                                                await hunter_client.verify_email(
                                                    discovered_email, logger
                                                )
                                            )
                                            best_contact["hunter_verification"] = (
                                                hunter_result
                                            )
                                            best_contact["email_quality_score"] = (
                                                hunter_result.get("score", 0)
                                            )

                                            score = hunter_result.get("score", 0)
                                            min_score = icp_config.get(
                                                "hunter_min_score", 70
                                            )

                                            if score >= min_score and hunter_result.get(
                                                "status"
                                            ) in ["valid", "deliverable"]:
                                                best_contact["email_verified"] = True
                                                best_contact["email_source"] = [
                                                    "provider",
                                                    "hunter_verified",
                                                ]
                                                logger.info(
                                                    f"✅ STEP 2 SUCCESS: Best contact email verified: {discovered_email} (score: {score}%)"
                                                )

                                                # Enhanced quality insights logging
                                                if score >= 90:
                                                    logger.info(
                                                        "   🏆 High-quality email (90%+) - excellent deliverability"
                                                    )
                                                elif score >= 80:
                                                    logger.info(
                                                        "   🥇 Good quality email (80-89%) - good deliverability"
                                                    )
                                                elif score >= 70:
                                                    logger.info(
                                                        "   🥈 Acceptable quality email (70-79%) - acceptable deliverability"
                                                    )
                                            else:
                                                best_contact["email_verified"] = False
                                                best_contact[
                                                    "needs_email_replacement"
                                                ] = True
                                                logger.warning(
                                                    f"❌ STEP 2 FAILED: Best contact email failed verification: {discovered_email} (score: {score}%) - proceeding to STEP 3"
                                                )

                                                # Enhanced failure insights logging
                                                if score < 50:
                                                    logger.info(
                                                        "   🚨 Very low quality (0-49%) - high bounce risk"
                                                    )
                                                elif score < 70:
                                                    logger.info(
                                                        "   ⚠️ Below threshold (50-69%) - moderate bounce risk"
                                                    )

                                                # Log specific status insights
                                                status = hunter_result.get(
                                                    "status", "unknown"
                                                )
                                                if status == "risky":
                                                    logger.info(
                                                        "   ⚡ Risky email status - proceed with caution"
                                                    )
                                                elif status == "invalid":
                                                    logger.info(
                                                        "   ❌ Invalid email format or domain"
                                                    )
                                                elif status == "unknown":
                                                    logger.info(
                                                        "   🤔 Unknown status - verification inconclusive"
                                                    )

                                            # Track Hunter.io cost
                                            if "costs" not in best_contact:
                                                best_contact["costs"] = {}
                                            if "hunter_io" not in best_contact["costs"]:
                                                best_contact["costs"]["hunter_io"] = 0.0
                                            best_contact["costs"]["hunter_io"] += (
                                                hunter_result.get("cost_usd", 0.0)
                                            )

                                        logger.info(
                                            f"✅ STEP 2 SUCCESS: Email enrichment successful for {first_name} {last_name}: {discovered_email}"
                                        )

                                        # Add to cost tracking
                                        contact_cost += email_result.cost

                                        # Update the record with enriched contact
                                        record["contacts"] = contacts
                                    else:
                                        logger.warning(
                                            f"⚠️ STEP 2 FAILED: Email discovery returned no email for {first_name} {last_name}"
                                        )
                                else:
                                    logger.warning(
                                        f"⚠️ STEP 2 FAILED: Email discovery failed for {first_name} {last_name}: {email_result.error}"
                                    )

                            except Exception as exc:
                                logger.warning(
                                    f"⚠️ STEP 2 FAILED: Email enrichment failed for {first_name} {last_name}: {exc}"
                                )

                        # STEP 3: If both fail → Fallback Discovery will be handled by existing fallback logic
                        if not standalone_success and (
                            not best_contact
                            or not best_contact.get("email")
                            or not best_contact.get("email_verified")
                        ):
                            logger.info(
                                "🔄 STEP 3: Both standalone discovery and best contact enrichment failed - fallback discovery will be attempted next"
                            )

                # FALLBACK EMAIL DISCOVERY: Additional discovery for contacts with failed verifications
                if contacts and hunter_client:
                    contacts_needing_emails = [
                        c
                        for c in contacts
                        if not c.get("email")
                        or not c.get("email_verified")
                        or c.get("needs_email_replacement")
                    ]

                    if contacts_needing_emails:
                        logger.info(
                            f"🔄 Attempting additional email discovery for {len(contacts_needing_emails)} contacts with failed/missing emails"
                        )

                        # Use the existing discover_and_verify_emails_with_hunter function
                        (
                            contacts,
                            additional_hunter_cost,
                        ) = await discover_and_verify_emails_with_hunter(
                            contacts=contacts,
                            domain=normalized_domain,
                            enrichment_router=enrichment_router,
                            hunter_client=hunter_client,
                            logger=logger,
                            costs_config=costs_config,
                            min_score=icp_config.get("hunter_min_score", 70),
                        )
                        total_cost += additional_hunter_cost

                        logger.info(
                            f"🔄 Fallback email discovery completed for {normalized_domain} - additional cost: ${additional_hunter_cost:.4f}"
                        )

                # Enrich existing or discovered contacts
                if contacts and contact_usd_cap > 0:
                    logger.info(
                        f"🔍 About to enrich {len(contacts)} contacts for {normalized_domain}"
                    )
                    for i, contact in enumerate(contacts):
                        logger.info(
                            f"🔍 Contact {i}: type={type(contact)}, content={contact}"
                        )

                        # Check if contact is a dictionary (defensive programming)
                        if not isinstance(contact, dict):
                            logger.warning(
                                f"⚠️ Contact {i} is not a dictionary (type: {type(contact)}), skipping: {contact}"
                            )
                            continue

                        if contact_cost >= contact_usd_cap:
                            break

                        # Add company country and default country for phone parsing
                        contact["company_country"] = company.get("hq_location")
                        contact["default_country"] = default_country

                        # Use router for contact enrichment
                        single_contact_cost = 0.0

                        # Try to enrich contact via router if no email
                        if not contact.get("email"):
                            try:
                                request = EnrichmentRequest(domain=normalized_domain)
                                result = await enrichment_router.enrich_contacts(
                                    request
                                )

                                if result.success and result.data:
                                    # Update contact with enriched data
                                    enriched_contact_data = result.data

                                    # Handle both dataclass objects and dictionaries
                                    if hasattr(
                                        enriched_contact_data, "__dataclass_fields__"
                                    ):
                                        # It's a ContactData object, access attributes directly
                                        if (
                                            enriched_contact_data.email
                                            and not contact.get("email")
                                        ):
                                            contact["email"] = (
                                                enriched_contact_data.email
                                            )
                                            contact["email_source"] = ["provider"]
                                            contact["email_status"] = ["unknown"]

                                            # IMMEDIATE Hunter.io verification
                                            if hunter_client:
                                                logger.info(
                                                    f"🔍 Hunter.io: Verifying enriched ContactData email {contact['email']} for {normalized_domain}"
                                                )
                                                hunter_result = (
                                                    await hunter_client.verify_email(
                                                        contact["email"], logger
                                                    )
                                                )
                                                contact["hunter_verification"] = (
                                                    hunter_result
                                                )
                                                contact["email_quality_score"] = (
                                                    hunter_result.get("score", 0)
                                                )

                                                score = hunter_result.get("score", 0)
                                                min_score = icp_config.get(
                                                    "hunter_min_score", 70
                                                )

                                                if (
                                                    score >= min_score
                                                    and hunter_result.get("status")
                                                    in ["valid", "deliverable"]
                                                ):
                                                    contact["email_verified"] = True
                                                    contact["email_source"] = [
                                                        "provider",
                                                        "hunter_verified",
                                                    ]
                                                    logger.info(
                                                        f"✅ Enriched ContactData email verified: {contact['email']} (score: {score}%)"
                                                    )
                                                else:
                                                    contact["email_verified"] = False
                                                    contact[
                                                        "needs_email_replacement"
                                                    ] = True
                                                    logger.warning(
                                                        f"❌ Enriched ContactData email failed verification: {contact['email']} (score: {score}%)"
                                                    )

                                                # Track Hunter.io cost
                                                if "costs" not in contact:
                                                    contact["costs"] = {}
                                                if "hunter_io" not in contact["costs"]:
                                                    contact["costs"]["hunter_io"] = 0.0
                                                contact["costs"]["hunter_io"] += (
                                                    hunter_result.get("cost_usd", 0.0)
                                                )
                                        if (
                                            enriched_contact_data.phone
                                            and not contact.get("phone")
                                        ):
                                            contact["phone"] = (
                                                enriched_contact_data.phone
                                            )
                                        if (
                                            enriched_contact_data.job_title
                                            and not contact.get("job_title")
                                        ):
                                            contact["job_title"] = (
                                                enriched_contact_data.job_title
                                            )
                                    else:
                                        # It's a dictionary, use .get() method
                                        if enriched_contact_data.get(
                                            "email"
                                        ) and not contact.get("email"):
                                            contact["email"] = enriched_contact_data[
                                                "email"
                                            ]
                                            contact["email_source"] = ["provider"]
                                            contact["email_status"] = ["unknown"]

                                            # IMMEDIATE Hunter.io verification
                                            if hunter_client:
                                                logger.info(
                                                    f"🔍 Hunter.io: Verifying enriched dictionary email {contact['email']} for {normalized_domain}"
                                                )
                                                hunter_result = (
                                                    await hunter_client.verify_email(
                                                        contact["email"], logger
                                                    )
                                                )
                                                contact["hunter_verification"] = (
                                                    hunter_result
                                                )
                                                contact["email_quality_score"] = (
                                                    hunter_result.get("score", 0)
                                                )

                                                score = hunter_result.get("score", 0)
                                                min_score = icp_config.get(
                                                    "hunter_min_score", 70
                                                )

                                                if (
                                                    score >= min_score
                                                    and hunter_result.get("status")
                                                    in ["valid", "deliverable"]
                                                ):
                                                    contact["email_verified"] = True
                                                    contact["email_source"] = [
                                                        "provider",
                                                        "hunter_verified",
                                                    ]
                                                    logger.info(
                                                        f"✅ Enriched dictionary email verified: {contact['email']} (score: {score}%)"
                                                    )
                                                else:
                                                    contact["email_verified"] = False
                                                    contact[
                                                        "needs_email_replacement"
                                                    ] = True
                                                    logger.warning(
                                                        f"❌ Enriched dictionary email failed verification: {contact['email']} (score: {score}%)"
                                                    )

                                                # Track Hunter.io cost
                                                if "costs" not in contact:
                                                    contact["costs"] = {}
                                                if "hunter_io" not in contact["costs"]:
                                                    contact["costs"]["hunter_io"] = 0.0
                                                contact["costs"]["hunter_io"] += (
                                                    hunter_result.get("cost_usd", 0.0)
                                                )
                                        if enriched_contact_data.get(
                                            "phone"
                                        ) and not contact.get("phone"):
                                            contact["phone"] = enriched_contact_data[
                                                "phone"
                                            ]
                                        if enriched_contact_data.get(
                                            "role"
                                        ) and not contact.get("role"):
                                            contact["role"] = enriched_contact_data[
                                                "role"
                                            ]

                                    single_contact_cost += result.cost
                                    logger.info(
                                        f"✅ Contact enrichment completed for {normalized_domain}"
                                    )
                            except Exception as exc:
                                logger.warning(
                                    f"Contact enrichment failed for {normalized_domain}: {exc}"
                                )

                        # Try to find email if still missing (null-safe)
                        if (
                            contact.get("email") is None
                            and contact.get("first_name")
                            and contact.get("last_name")
                        ):
                            try:
                                request = EnrichmentRequest(
                                    domain=normalized_domain,
                                    first_name=contact["first_name"],
                                    last_name=contact["last_name"],
                                )
                                result = await enrichment_router.find_email(request)

                                if result.success and result.data and result.data.email:
                                    contact["email"] = result.data.email
                                    contact["email_source"] = ["provider"]
                                    contact["email_status"] = ["unknown"]

                                    # IMMEDIATE Hunter.io verification
                                    if hunter_client:
                                        logger.info(
                                            f"🔍 Hunter.io: Verifying discovered email {contact['email']} for {normalized_domain}"
                                        )
                                        hunter_result = (
                                            await hunter_client.verify_email(
                                                contact["email"], logger
                                            )
                                        )
                                        contact["hunter_verification"] = hunter_result
                                        contact["email_quality_score"] = (
                                            hunter_result.get("score", 0)
                                        )

                                        score = hunter_result.get("score", 0)
                                        min_score = icp_config.get(
                                            "hunter_min_score", 70
                                        )

                                        if score >= min_score and hunter_result.get(
                                            "status"
                                        ) in ["valid", "deliverable"]:
                                            contact["email_verified"] = True
                                            contact["email_source"] = [
                                                "provider",
                                                "hunter_verified",
                                            ]
                                            logger.info(
                                                f"✅ Discovered email verified: {contact['email']} (score: {score}%)"
                                            )
                                        else:
                                            contact["email_verified"] = False
                                            contact["needs_email_replacement"] = True
                                            logger.warning(
                                                f"❌ Discovered email failed verification: {contact['email']} (score: {score}%)"
                                            )

                                        # Track Hunter.io cost
                                        if "costs" not in contact:
                                            contact["costs"] = {}
                                        if "hunter_io" not in contact["costs"]:
                                            contact["costs"]["hunter_io"] = 0.0
                                        contact["costs"]["hunter_io"] += (
                                            hunter_result.get("cost_usd", 0.0)
                                        )

                                    single_contact_cost += result.cost
                                    logger.info(
                                        f"✅ Email discovery completed for {normalized_domain}"
                                    )
                            except Exception as exc:
                                logger.warning(
                                    f"Email discovery failed for {normalized_domain}: {exc}"
                                )

                        # Validate email if present (null-safe)
                        if contact.get("email") is not None:
                            try:
                                validation_result = await mailgun_client.validate_email(
                                    contact["email"]
                                )

                                # Map Mailgun status to our email_status
                                mailgun_status = validation_result.get(
                                    "result", "unknown"
                                )
                                if mailgun_status == "valid":
                                    contact["email_status"] = ["valid"]
                                    contact["email_confidence"] = validation_result.get(
                                        "score", 0.0
                                    )
                                elif mailgun_status == "catch_all":
                                    contact["email_status"] = ["catch_all"]
                                    contact["email_confidence"] = 0.5
                                elif mailgun_status == "invalid":
                                    contact["email_status"] = ["invalid"]
                                    contact["email_confidence"] = 0.0
                                else:
                                    contact["email_status"] = ["unknown"]
                                    contact["email_confidence"] = 0.5

                                single_contact_cost += costs_config.get("mailgun", 0.0)

                            except Exception as exc:
                                logger.warning(f"Failed to validate email: {exc}")
                                contact["email_status"] = ["unknown"]
                                contact["email_confidence"] = 0.0
                        else:
                            # Contact has no email (Hunter.io discarded it)
                            contact["email_status"] = ["no_email"]
                            contact["email_confidence"] = 0.0
                            logger.info(
                                f"📭 Skipping Mailgun validation for contact {contact.get('full_name', 'Unknown')} - no email available"
                            )

                        # Normalize phone number if present
                        if contact.get("phone"):
                            try:
                                normalized_phone = parse_phone_number(
                                    contact["phone"],
                                    country_code=contact.get("company_country"),
                                    default_country=contact.get(
                                        "default_country", "US"
                                    ),
                                )
                                contact["phone"] = normalized_phone
                            except ValueError:
                                # Keep original phone if parsing fails
                                pass

                        # Cap individual contact cost
                        single_contact_cost = min(
                            single_contact_cost, contact_usd_cap - contact_cost
                        )
                        contact_cost += single_contact_cost

                # Update costs including LLM costs
                if "cost" not in record:
                    record["cost"] = {
                        "domain_usd": 0.0,
                        "crawl_usd": 0.0,
                        "enrich_usd": 0.0,
                        "llm_usd": 0.0,
                        "total_usd": 0.0,
                    }
                record["cost"]["enrich_usd"] = company_cost + contact_cost
                record["cost"]["llm_usd"] = llm_selection_cost
                recompute_total_cost(record)  # Update total cost
                total_cost += company_cost + contact_cost + llm_selection_cost

                # CRITICAL FIX: Update record with final merged contacts array
                # This ensures the CSV export can find the best contact
                record["contacts"] = contacts
                logger.info(
                    f"✅ Final contacts array updated for {normalized_domain}: {len(contacts)} contacts"
                )

                # Select best contact using LLM-based selection with fallback to rule-based
                # This happens AFTER contact discovery to ensure all contacts are available
                logger.info(
                    f"🔍 Contacts type before contact selection: {type(contacts)}"
                )
                logger.info(f"🔍 Contacts content before contact selection: {contacts}")
                logger.info(f"🔍 Role priority config: {role_priority_config}")
                logger.info(
                    f"🔍 ICP config available for LLM selection: {bool(icp_config)}"
                )

                # Use LLM-based contact selection with fallback to rule-based
                best_contact_id, llm_cost_info = await select_best_contact_llm(
                    contacts, role_priority_config, icp_config
                )
                record["best_contact_id"] = best_contact_id

                # Track LLM costs for contact selection
                llm_selection_cost = llm_cost_info.get("total_cost_usd", 0.0)

                # CRITICAL FIX: Ensure best_contact_id matches an actual contact in the contacts array
                if best_contact_id and contacts:
                    # Check if best_contact_id exists in contacts array
                    contact_exists = any(
                        c.get("contact_id") == best_contact_id for c in contacts
                    )
                    if not contact_exists:
                        # If best_contact_id doesn't match any contact, use the first contact's ID
                        if contacts:
                            record["best_contact_id"] = contacts[0]["contact_id"]
                            logger.info(
                                f"🔄 Updated best_contact_id to match actual contact: {contacts[0]['contact_id']} for {normalized_domain}"
                            )
                        else:
                            record["best_contact_id"] = None
                            logger.info(
                                f"🔄 Set best_contact_id to None (no contacts) for {normalized_domain}"
                            )
                elif not best_contact_id and contacts:
                    # If no best_contact_id was set but we have contacts, use the first one
                    record["best_contact_id"] = contacts[0]["contact_id"]
                    logger.info(
                        f"🔄 Set best_contact_id to first contact: {contacts[0]['contact_id']} for {normalized_domain}"
                    )
                elif not contacts:
                    # If no contacts, ensure best_contact_id is None
                    record["best_contact_id"] = None
                    logger.info(
                        f"🔄 Set best_contact_id to None (no contacts) for {normalized_domain}"
                    )

                # Update provenance
                if "provenance" not in record:
                    record["provenance"] = {}

                record["provenance"]["enriched_at"] = now_z()
                record["provenance"]["tool_versions"] = record["provenance"].get(
                    "tool_versions", {}
                )
                record["provenance"]["tool_versions"]["enrich"] = {
                    "version": INTERNAL_VERSION,
                    "schema_version": schema_checksum,
                }

                # Set evidence path
                evidence_data = {
                    "domain": normalized_domain,
                    "enriched_at": now_z(),
                    "company_enrichment": company,
                    "contacts_enrichment": contacts,
                    "llm_contact_selection": {
                        "best_contact_id": best_contact_id,
                        "llm_cost_info": llm_cost_info,
                        "selection_method": "llm"
                        if llm_cost_info.get("total_calls", 0) > 0
                        else "rule_based",
                    },
                    "costs": {
                        "company_usd": company_cost,
                        "contact_usd": contact_cost,
                        "llm_usd": llm_selection_cost,
                        "total_usd": company_cost + contact_cost + llm_selection_cost,
                    },
                }

                evidence_path = write_evidence_file(
                    normalized_domain, evidence_data, data_dir
                )
                record["provenance"]["evidence_paths"] = record["provenance"].get(
                    "evidence_paths", {}
                )
                record["provenance"]["evidence_paths"]["enrich"] = evidence_path

                # Update status

                # Check if all required fields are filled using new validation
                company_complete, contact_complete, icp_match = (
                    _check_required_fields_complete(
                        company, contacts, best_contact_id, domain, record.get("icp")
                    )
                )

                if company_complete and contact_complete and icp_match:
                    new_status = "enriched"
                    enriched_count += 1
                else:
                    new_status = "enrich_partial"
                    partial_count += 1

                # Update status and append to history
                record["status"] = new_status
                append_status(
                    record["status_history"],
                    new_status,
                    f"Enrichment completed. Company: {company_complete}, Contact: {contact_complete}, ICP: {icp_match}",
                )

                # Append audit entry
                append_audit(
                    record,
                    "Enrich",
                    f"Enriched company and contacts. Cost: ${company_cost + contact_cost:.4f}",
                )

                # Add Hunter.io costs to final cost calculation
                if hunter_client:
                    hunter_cost_info = hunter_client.get_cost_info()
                    logger.info(
                        f"💰 Hunter.io cost summary: {hunter_cost_info['total_requests']} requests, ${hunter_cost_info['total_cost_usd']:.4f}"
                    )

                # Truncate evidence arrays
                truncate_evidence_arrays(record)

                # Validate schema
                validation_errors = validate_envelope(record, TOOL_NAME)
                if validation_errors:
                    errors.extend(validation_errors)

                processed_records.append(record)

            except Exception as exc:
                # Handle individual record errors

                # Create a more specific error message based on the actual error
                if "'list' object has no attribute 'get'" in str(exc):
                    if "402" in str(exc) or "credits" in str(exc).lower():
                        error_msg = "API credits exhausted - some enrichment features unavailable"
                    else:
                        error_msg = "API response format issue - contact discovery may be unavailable"
                elif "402" in str(exc) or "Payment Required" in str(exc):
                    if "Snov.io" in str(exc) or "contact" in str(exc).lower():
                        error_msg = (
                            "Snov.io API credits exhausted - contact discovery skipped"
                        )
                    else:
                        error_msg = "CoreSignal API credits exhausted - company enrichment limited"
                else:
                    error_msg = f"Enrichment failed: {str(exc)}"

                # Ensure record is a dictionary
                if not isinstance(record, dict):
                    logger.error(
                        f"⚠️ Record is not a dictionary: {type(record)}, content: {record}"
                    )
                    # Create a minimal error without trying to access record fields
                    error = build_error(
                        ErrorCode.UNKNOWN,
                        exc=exc,
                        tool=TOOL_NAME,
                        lead_id="unknown",
                        context={
                            "error": "Record is not a dictionary",
                            "record_type": str(type(record)),
                        },
                    )
                else:
                    error = build_error(
                        ErrorCode.UNKNOWN,
                        exc=exc,
                        tool=TOOL_NAME,
                        lead_id=record.get("lead_id"),
                        context={"domain": record.get("domain", "")},
                    )
                errors.append(error)

                # Keep the record but mark as failed
                record["status"] = "enrich_partial"

                # Ensure status_history exists and is a list
                if "status_history" not in record:
                    record["status_history"] = []
                elif not isinstance(record["status_history"], list):
                    logger.warning(
                        f"⚠️ status_history is not a list for {record.get('domain', 'unknown')}, resetting to empty list"
                    )
                    record["status_history"] = []

                try:
                    append_status(
                        record["status_history"],
                        "enrich_partial",
                        error_msg,
                    )
                except Exception as append_error:
                    logger.error(
                        f"⚠️ Failed to append status for {record.get('domain', 'unknown')}: {append_error}"
                    )
                    # Create a minimal status entry manually
                    record["status_history"].append(
                        {
                            "status": "enrich_partial",
                            "ts": now_z(),
                            "notes": f"Enrichment failed: {str(exc)} (status append also failed: {append_error})",
                        }
                    )

                processed_records.append(record)

        # Calculate metrics
        duration_ms = int((time.time() - start_time) * 1000)
        pass_rate = enriched_count / len(lead_records) if lead_records else 0.0

        metrics = build_metrics(
            count_in=len(lead_records),
            count_out=len(processed_records),
            duration_ms=duration_ms,
            cache_hit_rate=None,  # Enrich doesn't have cache hits
            pass_rate=pass_rate,
            cost_usd={
                "domain": 0.0,
                "crawl": 0.0,
                "enrich": total_cost,
                "llm": sum(
                    record.get("cost", {}).get("llm_usd", 0.0)
                    for record in processed_records
                ),
                "total": total_cost,
            },
        )

        return {
            "data": {"lead_records": processed_records},
            "errors": errors,
            "metrics": metrics,
        }

    except Exception as exc:
        # Handle tool-level errors
        error = build_error(ErrorCode.UNKNOWN, exc=exc, tool=TOOL_NAME)
        duration_ms = int((time.time() - start_time) * 1000)

        return {
            "data": {"lead_records": []},
            "errors": [error],
            "metrics": build_metrics(0, 0, duration_ms),
        }


# ============================================================================
# CLI Interface
# ============================================================================


def main():
    """CLI entry point for the Enrich tool."""
    try:
        # Read JSON from stdin
        input_data = input()
        payload = json.loads(input_data)

        # Run enrichment
        result = asyncio.run(run_enrich(payload))

        # Write JSON to stdout
        print(json.dumps(result))

    except json.JSONDecodeError as exc:
        # Handle JSON parsing errors
        error_result = {
            "data": {"lead_records": []},
            "errors": [
                build_error(ErrorCode.SCHEMA_VALIDATION, exc=exc, tool=TOOL_NAME)
            ],
            "metrics": build_metrics(0, 0, 0),
        }
        print(json.dumps(error_result))
        exit(1)

    except Exception as exc:
        # Handle other errors
        error_result = {
            "data": {"lead_records": []},
            "errors": [build_error(ErrorCode.UNKNOWN, exc=exc, tool=TOOL_NAME)],
            "metrics": build_metrics(0, 0, 0),
        }
        print(json.dumps(error_result))
        exit(1)


if __name__ == "__main__":
    main()
