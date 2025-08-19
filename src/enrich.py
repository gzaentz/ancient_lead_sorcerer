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
import time
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

import httpx
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
    validate_provider_config,
    validate_testing_flags,
)

# Load environment variables
load_dotenv()

# Debug: Show environment variable status without exposing sensitive data
coresignal_token = os.getenv("CORESIGNAL_API_TOKEN")
logging.info(
    f"🔑 Environment CORESIGNAL_API_TOKEN status: {'SET' if coresignal_token else 'NOT SET'}"
)
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


# ============================================================================
# Provider Clients
# ============================================================================


class CoresignalClient:
    """Client for Coresignal API."""

    def __init__(self, api_token: str):
        self.api_token = api_token
        self.base_url = "https://api.coresignal.com"

    async def enrich_company(self, domain: str) -> Dict[str, Any]:
        """
        Enrich company information using Coresignal.

        Args:
            domain: Company domain

        Returns:
            Enriched company data
        """
        # Use the exact working configuration from the minimal test script
        website_param = domain.strip()
        if not website_param.startswith("http://") and not website_param.startswith(
            "https://"
        ):
            website_param = f"https://{website_param}"

        url = f"{self.base_url}/cdapi/v2/company_clean/enrich"
        params = {"website": website_param}
        headers = {
            "accept": "application/json",
            "apikey": self.api_token,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                logging.debug(
                    f"Calling Coresignal API: {url} with website={website_param}"
                )
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logging.warning(
                        f"Coresignal: Company not found for {domain} (404) - this is normal for smaller companies"
                    )
                    return {}  # Return empty dict instead of raising
                elif exc.response.status_code == 401:
                    logging.error(f"Coresignal API authentication failed for {domain}")
                    raise  # Re-raise authentication errors
                elif exc.response.status_code == 429:
                    logging.error(f"Coresignal API rate limit exceeded for {domain}")
                    raise  # Re-raise rate limit errors
                else:
                    logging.error(
                        f"Coresignal API error for {domain}: {exc.response.status_code} - {exc.response.text}"
                    )
                    return {}  # Return empty dict instead of raising
            except Exception as exc:
                logging.error(f"Coresignal API exception for {domain}: {exc}")
                # Re-raise unexpected exceptions that indicate configuration issues
                if "connection" in str(exc).lower() or "timeout" in str(exc).lower():
                    raise
                return {}

    async def enrich_contact(self, linkedin_url: str) -> Dict[str, Any]:
        """
        Enrich contact information using Coresignal.

        Note: Coresignal doesn't support direct LinkedIn URL enrichment.
        This method is maintained for backward compatibility but will raise
        an error. Use enrich_company_contacts() for contact enrichment.

        Args:
            linkedin_url: LinkedIn profile URL (not supported by Coresignal)

        Returns:
            Enriched contact data
        """
        raise NotImplementedError(
            "Coresignal doesn't support direct LinkedIn URL enrichment. "
            "Use enrich_company_contacts() method instead."
        )

    async def enrich_company_contacts(self, domain: str) -> Dict[str, Any]:
        """
        Enrich company contacts using Coresignal.

        Args:
            domain: Company domain

        Returns:
            Enriched company contacts data
        """
        url = f"{self.base_url}/v2/people/by-company-domain/{domain}"
        headers = {"apikey": self.api_token}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=MAX_WALL_CLOCK,
                connect=CONNECT_TIMEOUT,
                read=READ_TIMEOUT,
                write=None,
                pool=None,
            )
        ) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()


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


class SnovioClient:
    """Client for Snov.io email enrichment."""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://api.snov.io/v2"
        self._access_token = None

    async def _get_access_token(self) -> str:
        """Get access token for Snov.io API."""
        if self._access_token:
            return self._access_token

        url = "https://api.snov.io/v1/oauth/access_token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=MAX_WALL_CLOCK,
                connect=CONNECT_TIMEOUT,
                read=READ_TIMEOUT,
                write=None,
                pool=None,
            )
        ) as client:
            response = await client.post(url, data=data)
            response.raise_for_status()
            token_data = response.json()
            self._access_token = token_data["access_token"]
            return self._access_token

    async def find_email(
        self, domain: str, first_name: str, last_name: str
    ) -> Dict[str, Any]:
        """
        Find email address using Snov.io.

        Args:
            domain: Company domain
            first_name: Contact's first name
            last_name: Contact's last name

        Returns:
            Email discovery result
        """
        token = await self._get_access_token()
        url = f"{self.base_url}/search-profile"
        params = {
            "access_token": token,
            "domain": domain,
            "firstName": first_name,
            "lastName": last_name,
        }

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=MAX_WALL_CLOCK,
                connect=CONNECT_TIMEOUT,
                read=READ_TIMEOUT,
                write=None,
                pool=None,
            )
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def search_profiles(
        self, domain: str, job_title: str = None
    ) -> Dict[str, Any]:
        """
        Search for profiles in a domain using Snov.io v2 API.

        Args:
            domain: Company domain
            job_title: Optional job title to filter by

        Returns:
            Search results with profile data
        """
        token = await self._get_access_token()
        url = f"{self.base_url}/domain-search/prospects/start"

        # Based on our testing, v2 API accepts 'position' (singular) not 'positions' array
        data = {
            "access_token": token,
            "domain": domain,
        }

        if job_title:
            # Use 'position' (singular) as the v2 API expects this format
            data["position"] = job_title

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=MAX_WALL_CLOCK,
                connect=CONNECT_TIMEOUT,
                read=READ_TIMEOUT,
                write=None,
                pool=None,
            )
        ) as client:
            response = await client.post(url, data=data)
            response.raise_for_status()
            return response.json()

    async def get_prospect_results(self, task_hash: str) -> Dict[str, Any]:
        """
        Get results from a domain prospect search task using Snov.io v2 API.

        Args:
            task_hash: Task hash from search_profiles

        Returns:
            Domain prospect search results
        """
        token = await self._get_access_token()
        url = f"{self.base_url}/domain-search/prospects/result/{task_hash}"
        params = {"access_token": token}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=MAX_WALL_CLOCK,
                connect=CONNECT_TIMEOUT,
                read=READ_TIMEOUT,
                write=None,
                pool=None,
            )
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def get_all_domain_prospects(
        self, domain: str, max_retries: int = 10, poll_delay_seconds: float = 2.0
    ) -> Dict[str, Any]:
        """
        Start a domain prospect search task without role filtering and poll for results.

        Args:
            domain: Company domain
            max_retries: Maximum number of polling attempts
            poll_delay_seconds: Delay between polling attempts

        Returns:
            The raw API response from the result endpoint when available, or an
            empty result structure if not available within retry budget.
        """
        token = await self._get_access_token()
        start_url = f"{self.base_url}/domain-search/prospects/start"
        start_data = {
            "access_token": token,
            "domain": domain,
        }

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=MAX_WALL_CLOCK,
                connect=CONNECT_TIMEOUT,
                read=READ_TIMEOUT,
                write=None,
                pool=None,
            )
        ) as client:
            # Kick off the async task
            start_response = await client.post(start_url, data=start_data)
            start_response.raise_for_status()
            start_payload = start_response.json() or {}

        # Extract task hash from either meta.task_hash or data.task_hash
        task_hash = None
        if isinstance(start_payload.get("meta"), dict):
            task_hash = start_payload["meta"].get("task_hash")
        if not task_hash and isinstance(start_payload.get("data"), dict):
            task_hash = start_payload["data"].get("task_hash")

        if not task_hash:
            return {"data": [], "meta": {"domain": domain}, "error": "no_task_hash"}

        # Poll for results
        for _ in range(max_retries):
            try:
                result = await self.get_prospect_results(task_hash)
                # When ready, the result typically contains a populated data list
                data_field = result.get("data")
                if isinstance(data_field, list) and len(data_field) > 0:
                    return result
                # Some variants may nest prospects differently; if success flag exists, still return
                if result.get("success") and data_field is not None:
                    return result
            except Exception:
                # Ignore transient errors while polling
                pass
            await asyncio.sleep(poll_delay_seconds)

        # Timed out; return the latest known empty-style structure
        return {
            "data": [],
            "meta": {"domain": domain, "task_hash": task_hash},
            "error": "timeout",
        }


# ============================================================================
# Field Mapping Functions
# ============================================================================


def map_coresignal_company_fields(
    coresignal_response: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Map Coresignal company response to unified schema.

    Args:
        coresignal_response: Raw response from Coresignal company API

    Returns:
        Mapped company data in unified format
    """
    if not coresignal_response:
        logging.warning("Coresignal response is empty or None")
        return {}

    # Log the actual response structure for debugging
    logging.debug(f"Coresignal response keys: {list(coresignal_response.keys())}")

    # Coresignal response has fields directly at root level, no company wrapper
    mapped_data = {}

    # Map core fields directly from response root
    if coresignal_response.get("name"):
        mapped_data["name"] = coresignal_response["name"]
        logging.debug(f"Mapped company name: {coresignal_response['name']}")

    if coresignal_response.get("description"):
        mapped_data["description"] = coresignal_response["description"]
        logging.debug(
            f"Mapped company description: {coresignal_response['description'][:100]}..."
        )

    if coresignal_response.get("industry"):
        mapped_data["industry"] = coresignal_response["industry"]
        logging.debug(f"Mapped company industry: {coresignal_response['industry']}")

    # Map size information - Coresignal uses size_range and size_employees_count
    if coresignal_response.get("size_range"):
        mapped_data["size_hint"] = coresignal_response["size_range"]
        logging.debug(
            f"Mapped company size from size_range: {coresignal_response['size_range']}"
        )
    elif coresignal_response.get("size_employees_count"):
        # Convert exact count to size hint if size_range not available
        count = coresignal_response["size_employees_count"]
        if count <= 10:
            mapped_data["size_hint"] = "1-10"
        elif count <= 50:
            mapped_data["size_hint"] = "11-50"
        elif count <= 200:
            mapped_data["size_hint"] = "51-200"
        elif count <= 500:
            mapped_data["size_hint"] = "201-500"
        elif count <= 1000:
            mapped_data["size_hint"] = "501-1000"
        else:
            mapped_data["size_hint"] = "1000+"
        logging.debug(
            f"Converted employee count {count} to size_hint: {mapped_data['size_hint']}"
        )

    # Map location information - Coresignal uses location_hq_raw_address and location_hq_country
    if coresignal_response.get("location_hq_raw_address"):
        mapped_data["hq_location"] = coresignal_response["location_hq_raw_address"]
        logging.debug(
            f"Mapped HQ location: {coresignal_response['location_hq_raw_address']}"
        )

    if coresignal_response.get("location_hq_country"):
        mapped_data["hq_country"] = coresignal_response["location_hq_country"]
        logging.debug(
            f"Mapped HQ country: {coresignal_response['location_hq_country']}"
        )

    if coresignal_response.get("location_hq_regions"):
        mapped_data["hq_regions"] = coresignal_response["location_hq_regions"]
        logging.debug(
            f"Mapped HQ regions: {coresignal_response['location_hq_regions']}"
        )

    # Map LinkedIn ID to the correct schema field
    linkedin_id = coresignal_response.get("linkedin_id")
    if linkedin_id:
        mapped_data["ids"] = {"linkedin": linkedin_id, "crunchbase": None}
        logging.debug(f"Mapped LinkedIn company ID: {linkedin_id}")

    # Map additional fields that Coresignal provides to schema-compliant fields
    if coresignal_response.get("founded"):
        # Convert founded year to integer if it's a string
        founded_year = coresignal_response["founded"]
        try:
            if isinstance(founded_year, str):
                mapped_data["founded_year"] = int(founded_year)
            else:
                mapped_data["founded_year"] = founded_year
            logging.debug(f"Mapped founded year: {mapped_data['founded_year']}")
        except (ValueError, TypeError):
            logging.warning(
                f"Could not convert founded year to integer: {founded_year}"
            )

    # Map company type to both ownership_type and company_type for flexibility
    if coresignal_response.get("type"):
        mapped_data["ownership_type"] = coresignal_response["type"]
        mapped_data["company_type"] = coresignal_response["type"]
        logging.debug(
            f"Mapped company type to ownership_type and company_type: {coresignal_response['type']}"
        )

    # Map sector to industry if industry not already set
    if coresignal_response.get("sector") and not mapped_data.get("industry"):
        mapped_data["industry"] = coresignal_response["sector"]
        logging.debug(f"Mapped sector to industry: {coresignal_response['sector']}")

    # Map specialities to naics_keywords if they exist
    if coresignal_response.get("specialities"):
        if isinstance(coresignal_response["specialities"], list):
            mapped_data["naics_keywords"] = coresignal_response["specialities"]
        else:
            mapped_data["naics_keywords"] = [coresignal_response["specialities"]]
        logging.debug(
            f"Mapped specialities to naics_keywords: {coresignal_response['specialities']}"
        )

    # Map technologies to tech_stack if they exist
    if coresignal_response.get("technologies"):
        if isinstance(coresignal_response["technologies"], list):
            # Extract technology names from the technology objects
            tech_names = []
            for tech in coresignal_response["technologies"]:
                if isinstance(tech, dict) and tech.get("technology"):
                    tech_names.append(tech["technology"])
                elif isinstance(tech, str):
                    tech_names.append(tech)
            if tech_names:
                mapped_data["tech_stack"] = tech_names
                logging.debug(f"Mapped technologies to tech_stack: {tech_names}")
        elif isinstance(coresignal_response["technologies"], str):
            mapped_data["tech_stack"] = [coresignal_response["technologies"]]
            logging.debug(
                f"Mapped technologies to tech_stack: {coresignal_response['technologies']}"
            )

    # Map website to evidence_urls if it's different from the domain
    if coresignal_response.get("website"):
        website = coresignal_response["website"]
        if website and website not in mapped_data.get("evidence_urls", []):
            if "evidence_urls" not in mapped_data:
                mapped_data["evidence_urls"] = []
            mapped_data["evidence_urls"].append(website)
        logging.debug(f"Mapped website to evidence_urls: {website}")

    # Map all website variations
    website_fields = [
        "websites_main_original",
        "websites_main",
        "websites_resolved",
        "websites_facebook",
        "websites_twitter",
        "websites_professional_network",
    ]
    for field in website_fields:
        if coresignal_response.get(field):
            if "evidence_urls" not in mapped_data:
                mapped_data["evidence_urls"] = []
            mapped_data["evidence_urls"].append(coresignal_response[field])
            logging.debug(
                f"Mapped {field} to evidence_urls: {coresignal_response[field]}"
            )

    # Map social media URLs
    social_fields = [
        "social_discord_urls",
        "social_facebook_urls",
        "social_instagram_urls",
        "social_professional_network_urls",
        "social_pinterest_urls",
        "social_tiktok_urls",
        "social_twitter_urls",
        "social_x_urls",
        "social_youtube_urls",
        "social_github_urls",
        "social_reddit_urls",
    ]

    socials = {}
    for field in social_fields:
        if coresignal_response.get(field):
            urls = coresignal_response[field]
            if isinstance(urls, list) and urls:
                # Extract platform name from field name
                platform = field.replace("social_", "").replace("_urls", "")
                if platform == "professional_network":
                    platform = "linkedin"  # Map to LinkedIn
                elif platform == "x":
                    platform = "twitter"  # Map X to Twitter for consistency

                socials[platform] = urls[0] if urls else None
                logging.debug(
                    f"Mapped {field} to socials.{platform}: {urls[0] if urls else None}"
                )

    if socials:
        mapped_data["socials"] = socials

    # Map status if it's a meaningful business status
    if coresignal_response.get("status"):
        # Only map if it's a business-relevant status
        status = coresignal_response["status"]
        if status.lower() in ["active", "operating", "inactive", "closed", "acquired"]:
            mapped_data["business_status"] = status
            logging.debug(f"Mapped business status: {status}")

    # Map additional valuable fields
    if coresignal_response.get("followers"):
        mapped_data["followers_count"] = coresignal_response["followers"]
        logging.debug(f"Mapped followers count: {coresignal_response['followers']}")

    if coresignal_response.get("ticker"):
        mapped_data["ticker"] = coresignal_response["ticker"]
        logging.debug(f"Mapped ticker: {coresignal_response['ticker']}")

    if coresignal_response.get("exchange"):
        mapped_data["exchange"] = coresignal_response["exchange"]
        logging.debug(f"Mapped exchange: {coresignal_response['exchange']}")

    if coresignal_response.get("enriched_summary"):
        mapped_data["enriched_summary"] = coresignal_response["enriched_summary"]
        logging.debug(
            f"Mapped enriched summary: {coresignal_response['enriched_summary'][:100]}..."
        )

    if coresignal_response.get("enriched_keywords"):
        mapped_data["enriched_keywords"] = coresignal_response["enriched_keywords"]
        logging.debug(
            f"Mapped enriched keywords: {coresignal_response['enriched_keywords']}"
        )

    if coresignal_response.get("enriched_b2b"):
        mapped_data["enriched_b2b_score"] = coresignal_response["enriched_b2b"]
        logging.debug(f"Mapped B2B score: {coresignal_response['enriched_b2b']}")

    if coresignal_response.get("enriched_category"):
        mapped_data["enriched_category"] = coresignal_response["enriched_category"]
        logging.debug(
            f"Mapped enriched category: {coresignal_response['enriched_category']}"
        )

    # Map phone numbers and emails
    if coresignal_response.get("phone_numbers"):
        mapped_data["phone_numbers"] = coresignal_response["phone_numbers"]
        logging.debug(f"Mapped phone numbers: {coresignal_response['phone_numbers']}")

    if coresignal_response.get("emails"):
        mapped_data["company_emails"] = coresignal_response["emails"]
        logging.debug(f"Mapped company emails: {coresignal_response['emails']}")

    # Map funding information
    if coresignal_response.get("funding_rounds"):
        funding_rounds = coresignal_response["funding_rounds"]
        if isinstance(funding_rounds, list) and funding_rounds:
            # Take the most recent funding round
            latest_round = funding_rounds[0]
            mapped_data["funding"] = {
                "last_round_type": latest_round.get("last_round_type"),
                "last_round_date": latest_round.get("last_round_date"),
                "last_round_amount": latest_round.get("last_round_money_raised"),
                "total_rounds": latest_round.get("total_rounds_count"),
                "last_round_investors": latest_round.get("last_round_investors_count"),
            }
            logging.debug(f"Mapped funding information: {mapped_data['funding']}")

    # Map locations information
    if coresignal_response.get("locations_full"):
        locations = coresignal_response["locations_full"]
        if isinstance(locations, list):
            mapped_data["locations"] = []
            for loc in locations:
                if isinstance(loc, dict):
                    location_data = {
                        "address": loc.get("location_address"),
                        "is_primary": loc.get("is_primary", False),
                    }
                    mapped_data["locations"].append(location_data)
            logging.debug(f"Mapped {len(mapped_data['locations'])} locations")

    # Map business features
    business_features = {}
    feature_fields = [
        "pricing_available",
        "free_trial_available",
        "demo_available",
        "is_downloadable",
        "mobile_apps_exist",
        "online_reviews_exist",
        "api_docs_exist",
    ]

    for field in feature_fields:
        if coresignal_response.get(field) is not None:
            business_features[field] = coresignal_response[field]

    if business_features:
        mapped_data["business_features"] = business_features
        logging.debug(f"Mapped business features: {business_features}")

    # Map metadata
    if coresignal_response.get("metadata_title"):
        mapped_data["metadata_title"] = coresignal_response["metadata_title"]
        logging.debug(f"Mapped metadata title: {coresignal_response['metadata_title']}")

    if coresignal_response.get("metadata_description"):
        mapped_data["metadata_description"] = coresignal_response[
            "metadata_description"
        ]
        logging.debug(
            f"Mapped metadata description: {coresignal_response['metadata_description'][:100]}..."
        )

    # Map timestamps
    if coresignal_response.get("created_at"):
        mapped_data["created_at"] = coresignal_response["created_at"]
        logging.debug(f"Mapped created at: {coresignal_response['created_at']}")

    if coresignal_response.get("last_updated"):
        mapped_data["last_updated"] = coresignal_response["last_updated"]
        logging.debug(f"Mapped last updated: {coresignal_response['last_updated']}")

    # Map logo if available
    if coresignal_response.get("logo"):
        mapped_data["logo"] = coresignal_response["logo"]
        logging.debug("Mapped company logo")

    # Map domain information
    if coresignal_response.get("expired_domain") is not None:
        mapped_data["expired_domain"] = bool(coresignal_response["expired_domain"])
        logging.debug(f"Mapped expired domain: {mapped_data['expired_domain']}")

    if coresignal_response.get("unique_domain") is not None:
        mapped_data["unique_domain"] = bool(coresignal_response["unique_domain"])
        logging.debug(f"Mapped unique domain: {mapped_data['unique_domain']}")

    # Map professional network source ID
    if coresignal_response.get("professional_network_source_id"):
        mapped_data["professional_network_id"] = coresignal_response[
            "professional_network_source_id"
        ]
        logging.debug(
            f"Mapped professional network ID: {coresignal_response['professional_network_source_id']}"
        )

    logging.info(
        f"Successfully mapped {len(mapped_data)} fields from Coresignal response"
    )
    return mapped_data


def map_coresignal_contact_fields(
    coresignal_response: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Map Coresignal contact response to unified schema.

    Args:
        coresignal_response: Raw response from Coresignal people API

    Returns:
        Mapped contact data in unified format
    """
    if not coresignal_response:
        return {}

    # Extract people data from response
    people_data = coresignal_response.get("people", [])
    if not people_data:
        return {}

    # For now, return the first person found
    # In a full implementation, this would need to handle multiple contacts
    person = people_data[0] if people_data else {}

    mapped_data = {}

    # Map core fields
    if person.get("first_name"):
        mapped_data["first_name"] = person["first_name"]

    if person.get("last_name"):
        mapped_data["last_name"] = person["last_name"]

    if person.get("full_name"):
        mapped_data["full_name"] = person["full_name"]

    if person.get("email"):
        mapped_data["email"] = person["email"]
        mapped_data["email_source"] = ["provider"]
        mapped_data["email_status"] = ["unknown"]  # Will be validated by Mailgun

    if person.get("phone"):
        mapped_data["phone"] = person["phone"]

    if person.get("title"):
        mapped_data["role"] = person["title"]

    if person.get("linkedin_url"):
        mapped_data["linkedin"] = person["linkedin_url"]

    # Map additional fields that Coresignal provides
    if person.get("role"):
        mapped_data["role_description"] = person["role"]

    if person.get("seniority"):
        mapped_data["seniority"] = person["seniority"]

    if person.get("department"):
        mapped_data["department"] = person["department"]

    if person.get("location"):
        mapped_data["location"] = person["location"]

    if person.get("experience_years"):
        mapped_data["experience_years"] = person["experience_years"]

    if person.get("skills"):
        mapped_data["skills"] = person["skills"]

    return mapped_data


# ============================================================================
# Core Enrichment Logic
# ============================================================================


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
        role = contact.get("role", "")
        seniority = contact.get("seniority", 99)
        email_status = (
            contact.get("email_status", ["unknown"])[0]
            if isinstance(contact.get("email_status"), list)
            else contact.get("email_status", "unknown")
        )
        linkedin = contact.get("linkedin", "")

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


async def enrich_company_data(
    company: Dict[str, Any],
    domain: str,
    coresignal_client: CoresignalClient,
    costs_config: Dict[str, float],
) -> tuple[Dict[str, Any], float]:
    """
    Enrich company data using Coresignal.

    Args:
        company: Company data to enrich
        domain: Company domain
        coresignal_client: Coresignal client
        costs_config: Costs configuration

    Returns:
        Tuple of (enriched_company, cost_usd)
    """
    try:
        # Enrich company information
        try:
            enriched_data = await coresignal_client.enrich_company(domain)
        except Exception as exc:
            logging.warning(f"Failed to enrich company data for {domain}: {exc}")
            return company, 0.0

        # Log the raw response for debugging
        logging.info(f"🔍 CoreSignal raw response for {domain}: {enriched_data}")

        if not enriched_data:
            logging.info(
                f"Coresignal returned empty response for domain: {domain} - this is normal for smaller companies"
            )
            return company, 0.0

        # Map Coresignal response to unified schema
        mapped_data = map_coresignal_company_fields(enriched_data)

        # Log mapping results
        logging.info(
            f"✅ CoreSignal field mapping for {domain}: {len(mapped_data)} fields mapped"
        )
        logging.info(f"🔍 Mapped fields: {list(mapped_data.keys())}")
        if not mapped_data:
            logging.warning(
                f"No fields were mapped for domain: {domain}. Response keys: {list(enriched_data.keys())}"
            )
            return company, 0.0

        # Update company fields - enhance existing data with CoreSignal insights
        fields_updated = 0

        # Always enhance name if CoreSignal provides it (more authoritative)
        if mapped_data.get("name"):
            company["name"] = mapped_data["name"]
            fields_updated += 1

        # Always enhance description if CoreSignal provides it (more comprehensive)
        if mapped_data.get("description"):
            company["description"] = mapped_data["description"]
            fields_updated += 1

        # Always enhance industry if CoreSignal provides it (more accurate classification)
        if mapped_data.get("industry"):
            company["industry"] = mapped_data["industry"]
            fields_updated += 1

        # Always enhance location if CoreSignal provides it (more detailed address)
        if mapped_data.get("hq_location"):
            company["hq_location"] = mapped_data["hq_location"]
            fields_updated += 1

        # Always enhance size information if CoreSignal provides it (more accurate)
        if mapped_data.get("size_hint"):
            company["size_hint"] = mapped_data["size_hint"]
            fields_updated += 1

        # Add new location fields
        if mapped_data.get("hq_country"):
            company["hq_country"] = mapped_data["hq_country"]
            fields_updated += 1

        if mapped_data.get("hq_regions"):
            company["hq_regions"] = mapped_data["hq_regions"]
            fields_updated += 1

        # Add social media information
        if mapped_data.get("socials"):
            company["socials"] = mapped_data["socials"]
            fields_updated += 1

        # Add additional CoreSignal fields
        if mapped_data.get("founded_year") and not company.get("founded_year"):
            company["founded_year"] = mapped_data["founded_year"]
            fields_updated += 1

        if mapped_data.get("company_type") and not company.get("company_type"):
            company["company_type"] = mapped_data["company_type"]
            fields_updated += 1

        if mapped_data.get("ownership_type") and not company.get("ownership_type"):
            company["ownership_type"] = mapped_data["ownership_type"]
            fields_updated += 1

        if mapped_data.get("sector") and not company.get("sector"):
            company["sector"] = mapped_data["sector"]
            fields_updated += 1

        # Add new fields that weren't in the original schema
        if mapped_data.get("followers_count"):
            company["followers_count"] = mapped_data["followers_count"]
            fields_updated += 1

        if mapped_data.get("ticker"):
            company["ticker"] = mapped_data["ticker"]
            fields_updated += 1

        if mapped_data.get("exchange"):
            company["exchange"] = mapped_data["exchange"]
            fields_updated += 1

        if mapped_data.get("enriched_summary"):
            company["enriched_summary"] = mapped_data["enriched_summary"]
            fields_updated += 1

        if mapped_data.get("enriched_keywords"):
            company["enriched_keywords"] = mapped_data["enriched_keywords"]
            fields_updated += 1

        if mapped_data.get("enriched_b2b_score"):
            company["enriched_b2b_score"] = mapped_data["enriched_b2b_score"]
            fields_updated += 1

        if mapped_data.get("enriched_category"):
            company["enriched_category"] = mapped_data["enriched_category"]
            fields_updated += 1

        if mapped_data.get("phone_numbers"):
            company["phone_numbers"] = mapped_data["phone_numbers"]
            fields_updated += 1

        if mapped_data.get("company_emails"):
            company["company_emails"] = mapped_data["company_emails"]
            fields_updated += 1

        if mapped_data.get("funding"):
            company["funding"] = mapped_data["funding"]
            fields_updated += 1

        if mapped_data.get("locations"):
            company["locations"] = mapped_data["locations"]
            fields_updated += 1

        if mapped_data.get("business_features"):
            company["business_features"] = mapped_data["business_features"]
            fields_updated += 1

        if mapped_data.get("metadata_title"):
            company["metadata_title"] = mapped_data["metadata_title"]
            fields_updated += 1

        if mapped_data.get("metadata_description"):
            company["metadata_description"] = mapped_data["metadata_description"]
            fields_updated += 1

        if mapped_data.get("created_at"):
            company["created_at"] = mapped_data["created_at"]
            fields_updated += 1

        if mapped_data.get("last_updated"):
            company["last_updated"] = mapped_data["last_updated"]
            fields_updated += 1

        if mapped_data.get("logo"):
            company["logo"] = mapped_data["logo"]
            fields_updated += 1

        if mapped_data.get("expired_domain") is not None:
            company["expired_domain"] = mapped_data["expired_domain"]
            fields_updated += 1

        if mapped_data.get("unique_domain") is not None:
            company["unique_domain"] = mapped_data["unique_domain"]
            fields_updated += 1

        if mapped_data.get("professional_network_id"):
            company["professional_network_id"] = mapped_data["professional_network_id"]
            fields_updated += 1

        # Backfill company.ids if missing
        if mapped_data.get("ids") and not company.get("ids"):
            company["ids"] = mapped_data["ids"]
            fields_updated += 1

        # Add evidence URLs (websites)
        if mapped_data.get("evidence_urls"):
            if "evidence_urls" not in company:
                company["evidence_urls"] = []
            # Add new URLs that aren't already present
            for url in mapped_data["evidence_urls"]:
                if url and url not in company["evidence_urls"]:
                    company["evidence_urls"].append(url)
                    fields_updated += 1

        # Add tech stack
        if mapped_data.get("tech_stack"):
            company["tech_stack"] = mapped_data["tech_stack"]
            fields_updated += 1

        # Add NAICS keywords
        if mapped_data.get("naics_keywords"):
            company["naics_keywords"] = mapped_data["naics_keywords"]
            fields_updated += 1

        # Add business status
        if mapped_data.get("business_status"):
            company["business_status"] = mapped_data["business_status"]
            fields_updated += 1

        # Log enrichment results
        logging.info(
            f"🎯 CoreSignal enrichment completed for {domain}: {fields_updated} fields updated"
        )
        if fields_updated > 0:
            logging.info(
                f"📊 Updated fields: {[k for k, v in mapped_data.items() if company.get(k) == v]}"
            )

        # Calculate cost
        cost_usd = costs_config.get("coresignal", 0.0)

        return company, cost_usd

    except Exception as exc:
        logging.error(
            f"Failed to enrich company data for {domain}: {exc}", exc_info=True
        )
        return company, 0.0


async def enrich_contact_data(
    contact: Dict[str, Any],
    domain: str,
    coresignal_client: CoresignalClient,
    mailgun_client: MailgunClient,
    snovio_client: SnovioClient,
    costs_config: Dict[str, float],
) -> tuple[Dict[str, Any], float]:
    """
    Enrich contact data using multiple providers.

    Args:
        contact: Contact data to enrich
        domain: Company domain
        coresignal_client: Coresignal client
        mailgun_client: Mailgun client
        snovio_client: Snov.io client
        costs_config: Costs configuration

    Returns:
        Tuple of (enriched_contact, cost_usd)
    """
    total_cost = 0.0

    try:
        # Enrich via Coresignal company contacts if no email
        if not contact.get("email"):
            try:
                # Try to get company contacts from Coresignal
                company_contacts = await coresignal_client.enrich_company_contacts(
                    domain
                )

                # Increment cost for Coresignal API call regardless of outcome
                total_cost += costs_config.get("coresignal", 0.0)

                # Map Coresignal response to unified schema
                mapped_contact = map_coresignal_contact_fields(company_contacts)

                # Try to find a matching contact by name
                if mapped_contact.get("full_name") and contact.get("full_name"):
                    if (
                        mapped_contact["full_name"].lower()
                        == contact["full_name"].lower()
                    ):
                        # Update contact fields
                        if mapped_contact.get("email") and not contact.get("email"):
                            contact["email"] = mapped_contact["email"]
                            contact["email_source"] = ["provider"]
                            contact["email_status"] = [
                                "unknown"
                            ]  # Will be validated by Mailgun

                        if mapped_contact.get("phone") and not contact.get("phone"):
                            contact["phone"] = mapped_contact["phone"]

                        if mapped_contact.get("role") and not contact.get("role"):
                            contact["role"] = mapped_contact["role"]

            except Exception as exc:
                logging.warning(
                    f"Failed to enrich contact via Coresignal company contacts: {exc}"
                )

        # Try Snov.io for email discovery if no email
        if not contact.get("email"):
            try:
                full_name = contact.get("full_name", "")
                if full_name and " " in full_name:
                    first_name, last_name = full_name.split(" ", 1)

                    email_data = await snovio_client.find_email(
                        domain, first_name, last_name
                    )

                    if email_data.get("email"):
                        contact["email"] = email_data["email"]
                        contact["email_source"] = ["provider"]
                        contact["email_status"] = [
                            "unknown"
                        ]  # Will be validated by Mailgun
                        total_cost += costs_config.get("snovio", 0.0)

            except Exception as exc:
                if "402 Payment Required" in str(exc):
                    logging.warning(
                        "Snov.io API credits exhausted - skipping email discovery"
                    )
                else:
                    logging.warning(f"Failed to discover email via Snov.io: {exc}")

        # Validate email if present
        if contact.get("email"):
            try:
                validation_result = await mailgun_client.validate_email(
                    contact["email"]
                )

                # Map Mailgun status to our email_status
                mailgun_status = validation_result.get("result", "unknown")
                if mailgun_status == "valid":
                    contact["email_status"] = ["valid"]
                    contact["email_confidence"] = validation_result.get("score", 0.0)
                elif mailgun_status == "catch_all":
                    contact["email_status"] = ["catch_all"]
                    contact["email_confidence"] = 0.5
                elif mailgun_status == "invalid":
                    contact["email_status"] = ["invalid"]
                    contact["email_confidence"] = 0.0
                else:
                    contact["email_status"] = ["unknown"]
                    contact["email_confidence"] = 0.5

                total_cost += costs_config.get("mailgun", 0.0)

            except Exception as exc:
                logging.warning(f"Failed to validate email: {exc}")
                contact["email_status"] = ["unknown"]
                contact["email_confidence"] = 0.0

        # Normalize phone number if present
        if contact.get("phone"):
            try:
                normalized_phone = parse_phone_number(
                    contact["phone"],
                    country_code=contact.get("company_country"),
                    default_country=contact.get("default_country", "US"),
                )
                contact["phone"] = normalized_phone
            except ValueError:
                # Keep original phone if parsing fails
                pass

        return contact, total_cost

    except Exception as exc:
        logging.warning(f"Failed to enrich contact data: {exc}")
        return contact, total_cost


async def discover_contacts_for_domain(
    domain: str,
    snovio_client: SnovioClient,
    costs_config: Dict[str, float],
    contact_usd_cap: float,
) -> List[Dict[str, Any]]:
    """
    Discover contacts for a domain using Snov.io.

    Args:
        domain: Company domain
        snovio_client: Snov.io client
        costs_config: Costs configuration
        contact_usd_cap: Maximum cost allowed for contact discovery

    Returns:
        List of discovered contacts
    """
    try:
        logging.info(f"🔍 Discovering contacts for domain: {domain}")

        # 1) Start by fetching all prospects Snov.io has for the domain (no role filtering)
        discovered_contacts = []
        try:
            all_prospects_result = await snovio_client.get_all_domain_prospects(domain)
        except Exception as exc:
            if "402 Payment Required" in str(exc):
                logging.warning(
                    f"⚠️ Snov.io API credits exhausted for {domain} - skipping contact discovery"
                )
            else:
                logging.warning(
                    f"⚠️ Failed to fetch Snov.io prospects for {domain}: {exc}"
                )
            all_prospects_result = {"data": []}

        raw_profiles = []
        data_field = all_prospects_result.get("data")
        if isinstance(data_field, list):
            raw_profiles = data_field
        elif isinstance(data_field, dict) and "prospects" in data_field:
            raw_profiles = data_field.get("prospects") or []

        # 2) Filter locally for decision-maker titles
        decision_maker_titles = [
            "CEO",
            "Chief Executive Officer",
            "President",
            "Owner",
            "Founder",
            "Managing Director",
            "General Manager",
            "Practice Manager",
            "Dental Director",
            "Clinical Director",
            "Operations Manager",
        ]

        # Lower-cased set for matching
        decision_set = {t.lower() for t in decision_maker_titles}

        total_cost = 0.0
        snovio_cost_per_search = costs_config.get("snovio", 0.0)

        for profile in raw_profiles:
            if len(discovered_contacts) >= 5:
                break

            # Title fields vary by endpoint; check several candidates
            title_value = (
                profile.get("jobTitle")
                or profile.get("position")
                or profile.get("title")
                or ""
            )

            if title_value and title_value.lower() not in decision_set:
                continue

            contact = {
                "contact_id": f"discovered_{len(discovered_contacts)}",
                "first_name": profile.get("firstName", ""),
                "last_name": profile.get("lastName", ""),
                "email": profile.get("email", ""),
                "job_title": title_value,
                "company": profile.get("company", ""),
                "linkedin_url": profile.get("linkedinUrl", ""),
                "location": profile.get("location", ""),
                "discovery_source": "snovio",
                "discovery_method": "domain_prospects",
            }

            # Only add if unique by name/email
            if not any(
                c.get("email") == contact["email"]
                and c.get("first_name") == contact["first_name"]
                and c.get("last_name") == contact["last_name"]
                for c in discovered_contacts
            ):
                discovered_contacts.append(contact)
                total_cost += snovio_cost_per_search
                logging.info(
                    f"✅ Discovered contact: {contact['first_name']} {contact['last_name']} - {contact['job_title']}"
                )

        if discovered_contacts:
            logging.info(
                f"🎯 Successfully discovered {len(discovered_contacts)} contacts for {domain}"
            )
        else:
            logging.warning(f"❌ No contacts discovered for {domain}")

        return discovered_contacts

    except Exception as exc:
        logging.error(f"❌ Failed to discover contacts for {domain}: {exc}")
        return []


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
    start_time = time.time()

    # Resolve data directory first for logging setup. Child tool will use shared
    # run log path from env if orchestrator provided one.
    data_dir = resolve_data_dir(payload)
    setup_logging(TOOL_NAME, data_dir=data_dir)

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
            logging.info("🔍 Validating testing flags...")
            logging.info(f"🔍 ICP config keys: {list(icp_config.keys())}")
            logging.info(
                f"🔍 Testing section: {icp_config.get('testing', 'NOT_FOUND')}"
            )
            logging.info("🔍 About to call validate_testing_flags...")
            validate_testing_flags(icp_config)
            logging.info("🔍 validate_testing_flags returned successfully")
            logging.info("✅ Testing flags validation passed")
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
            logging.info("🔍 Loading costs configuration...")
            costs_config = load_costs_config()
            logging.info(f"✅ Costs config loaded: {list(costs_config.keys())}")

            required_providers = ["coresignal", "mailgun", "snovio"]
            logging.info(f"🔍 Validating provider config for: {required_providers}")
            validate_provider_config(required_providers, costs_config)
            logging.info("✅ Provider config validation passed")
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
            logging.info("🔍 Loading schema checksum...")
            schema_checksum = load_schema_checksum()
            logging.info(f"✅ Schema checksum loaded: {schema_checksum[:8]}...")
        except FileNotFoundError as exc:
            return {
                "data": {"lead_records": []},
                "errors": [
                    build_error(ErrorCode.SCHEMA_VALIDATION, exc=exc, tool=TOOL_NAME)
                ],
                "metrics": build_metrics(0, 0, 0),
            }

        # Data directory already resolved for logging setup above
        logging.info(f"✅ Using data directory: {data_dir}")

        # Note: Removed permit manager and semaphore pools since we no longer use file locking
        logging.info("🔍 Skipping concurrency controls (no file locking needed)")

        # Initialize provider clients
        logging.info("🔍 Checking environment variables...")
        coresignal_token = os.environ.get("CORESIGNAL_API_TOKEN")
        mailgun_login = os.environ.get("MAILGUN_SMTP_LOGIN")
        mailgun_password = os.environ.get("MAILGUN_SMTP_PW")
        snovio_id = os.environ.get("SNOV_IO_ID")
        snovio_secret = os.environ.get("SNOV_IO_SECRET")

        logging.info(
            f"🔑 Environment check - Coresignal: {'✅' if coresignal_token else '❌'}, Mailgun: {'✅' if mailgun_login else '❌'}, Snov.io: {'✅' if snovio_id else '❌'}"
        )

        # Check which specific environment variables are missing
        missing_vars = []
        if not coresignal_token:
            missing_vars.append("CORESIGNAL_API_TOKEN")
        if not mailgun_login:
            missing_vars.append("MAILGUN_SMTP_LOGIN")
        if not mailgun_password:
            missing_vars.append("MAILGUN_SMTP_PW")
        if not snovio_id:
            missing_vars.append("SNOV_IO_ID")
        if not snovio_secret:
            missing_vars.append("SNOV_IO_SECRET")

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
                                "CORESIGNAL_API_TOKEN",
                                "MAILGUN_SMTP_LOGIN",
                                "MAILGUN_SMTP_PW",
                                "SNOV_IO_ID",
                                "SNOV_IO_SECRET",
                            ],
                        },
                    )
                ],
                "metrics": build_metrics(0, 0, 0),
            }

        coresignal_client = CoresignalClient(coresignal_token)
        mailgun_client = MailgunClient(mailgun_login, mailgun_password)
        snovio_client = SnovioClient(snovio_id, snovio_secret)

        # Get configuration values
        role_priority_config = icp_config.get("role_priority", {})
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

        for record in lead_records:
            try:
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

                # Normalize domain
                normalized_domain = normalize_domain(domain)
                record["domain"] = normalized_domain

                # Enrich company data first (cheaper)
                company_cost = 0.0
                if company_usd_cap > 0:
                    try:
                        enriched_company, company_cost = await enrich_company_data(
                            company, normalized_domain, coresignal_client, costs_config
                        )
                        company_cost = min(company_cost, company_usd_cap)
                        # Update the record's company data
                        record["company"] = enriched_company
                    except Exception as e:
                        logging.warning(
                            f"⚠️ Company enrichment failed for {normalized_domain}: {e}"
                        )
                        # Continue with contact discovery even if company enrichment fails
                        company_cost = 0.0

                # Select best contact
                best_contact_id = select_best_contact(contacts, role_priority_config)
                record["best_contact_id"] = best_contact_id

                # Enrich contacts (only if within budget)
                contact_cost = 0.0

                # If no contacts exist, try to discover them using Snov.io
                if not contacts and contact_usd_cap > 0:
                    logging.info(
                        f"🔍 No contacts found for {normalized_domain}, attempting contact discovery..."
                    )
                    discovered_contacts = await discover_contacts_for_domain(
                        normalized_domain, snovio_client, costs_config, contact_usd_cap
                    )

                    if discovered_contacts:
                        contacts = discovered_contacts
                        record["contacts"] = contacts
                        logging.info(
                            f"✅ Discovered {len(contacts)} contacts for {normalized_domain}"
                        )
                    else:
                        logging.warning(
                            f"⚠️ No contacts discovered for {normalized_domain}"
                        )

                # Enrich existing or discovered contacts
                if contacts and contact_usd_cap > 0:
                    for contact in contacts:
                        if contact_cost >= contact_usd_cap:
                            break

                        # Add company country and default country for phone parsing
                        contact["company_country"] = company.get("hq_location")
                        contact["default_country"] = default_country

                        (
                            enriched_contact,
                            single_contact_cost,
                        ) = await enrich_contact_data(
                            contact,
                            normalized_domain,
                            coresignal_client,
                            mailgun_client,
                            snovio_client,
                            costs_config,
                        )

                        # Cap individual contact cost
                        single_contact_cost = min(
                            single_contact_cost, contact_usd_cap - contact_cost
                        )
                        contact_cost += single_contact_cost

                # Update costs
                # Update costs
                if "cost" not in record:
                    record["cost"] = {
                        "domain_usd": 0.0,
                        "crawl_usd": 0.0,
                        "enrich_usd": 0.0,
                        "total_usd": 0.0,
                    }
                record["cost"]["enrich_usd"] = company_cost + contact_cost
                recompute_total_cost(record)  # Update total cost
                total_cost += company_cost + contact_cost

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
                    "costs": {
                        "company_usd": company_cost,
                        "contact_usd": contact_cost,
                        "total_usd": company_cost + contact_cost,
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

                # Check if all required fields are filled
                required_company_fields = icp_config.get("required_fields", {}).get(
                    "company", []
                )
                required_contact_fields = icp_config.get("required_fields", {}).get(
                    "contact", []
                )

                company_complete = all(
                    company.get(field) for field in required_company_fields
                )

                contact_complete = True
                if required_contact_fields and contacts:
                    best_contact = next(
                        (c for c in contacts if c.get("contact_id") == best_contact_id),
                        None,
                    )
                    if best_contact:
                        contact_complete = all(
                            best_contact.get(field) for field in required_contact_fields
                        )
                    else:
                        contact_complete = False

                if company_complete and contact_complete:
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
                    f"Enrichment completed. Company: {company_complete}, Contact: {contact_complete}",
                )

                # Append audit entry
                append_audit(
                    record,
                    "Enrich",
                    f"Enriched company and contacts. Cost: ${company_cost + contact_cost:.4f}",
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
                append_status(
                    record["status_history"],
                    "enrich_partial",
                    f"Enrichment failed: {str(exc)}",
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
