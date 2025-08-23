"""
Anymail Finder enrichment provider implementation.

This module implements the Anymail Finder API client as an enrichment provider
following the BaseEnrichmentProvider interface.

Authoritative specifications: BRD §333-336, §410-439
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from .base import (
    BaseEnrichmentProvider,
    EnrichmentRequest,
    EnrichmentResult,
    CompanyData,
    ContactData,
    ProviderTier,
    CompanyEnrichmentError,
    RateLimitError,
    AuthenticationError,
    ServiceUnavailableError,
)


class AnymailFinderProvider(BaseEnrichmentProvider):
    """Anymail Finder API enrichment provider."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Anymail Finder provider.

        Args:
            api_key: Anymail Finder API key (defaults to env var ANYMAIL_FINDER_API_KEY)
        """
        super().__init__(name="AnymailFinder", tier=ProviderTier.TIER_0)
        self.api_key = api_key or os.getenv("ANYMAIL_FINDER_API_KEY")
        if not self.api_key:
            raise AuthenticationError("Anymail Finder API key not provided")

        self.base_url = "https://api.anymailfinder.com/v5.0"
        self._last_request_time = 0.0
        self._min_request_interval = 0.2  # 200ms between requests (5 RPS limit)

        logging.info("Anymail Finder provider initialized")

    async def _rate_limit(self):
        """Ensure we don't exceed Anymail Finder's rate limits."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._min_request_interval:
            sleep_time = self._min_request_interval - time_since_last
            await asyncio.sleep(sleep_time)
        self._last_request_time = time.time()

    async def _handle_response(
        self, response: httpx.Response, operation: str
    ) -> Dict[str, Any]:
        """
        Handle API response and extract data.

        Args:
            response: HTTP response from Anymail Finder API
            operation: Description of the operation being performed

        Returns:
            Extracted data from response

        Raises:
            RateLimitError: If rate limit exceeded
            AuthenticationError: If authentication failed
            ServiceUnavailableError: If service is unavailable
            CompanyEnrichmentError: For other API errors
        """
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 401:
            raise AuthenticationError(
                f"Anymail Finder API authentication failed for {operation}"
            )
        elif response.status_code == 429:
            retry_after = response.headers.get("retry-after", "60")
            raise RateLimitError(
                f"Anymail Finder API rate limit exceeded for {operation}. Retry after {retry_after} seconds"
            )
        elif response.status_code == 503:
            raise ServiceUnavailableError(
                f"Anymail Finder API service unavailable for {operation}"
            )
        else:
            error_msg = f"Anymail Finder API error {response.status_code} for {operation}: {response.text}"
            raise CompanyEnrichmentError(error_msg)

    async def enrich_company(self, request: EnrichmentRequest) -> EnrichmentResult:
        """
        Enrich company information using Anymail Finder.

        Args:
            request: Enrichment request with domain

        Returns:
            Enrichment result with company data
        """
        domain = request.domain
        try:
            await self._rate_limit()

            url = f"{self.base_url}/company/search"
            params = {"domain": domain, "api_key": self.api_key}

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                data = await self._handle_response(response, "company enrichment")

                # Map Anymail Finder response to CompanyData
                company_data = self._map_company_response(data, domain)

                return EnrichmentResult(
                    success=True,
                    data=company_data,
                    provider="anymail_finder",
                    cost=0.008,  # Anymail Finder cost per company lookup
                )

        except Exception as exc:
            logging.error(
                f"Anymail Finder company enrichment failed for {domain}: {exc}"
            )
            return EnrichmentResult(
                success=False, error=str(exc), provider="anymail_finder"
            )

    async def enrich_contacts(self, request: EnrichmentRequest) -> EnrichmentResult:
        """
        Enrich company contacts using Anymail Finder.

        Args:
            request: Enrichment request with domain

        Returns:
            Enrichment result with contact data
        """
        domain = request.domain
        try:
            await self._rate_limit()

            url = f"{self.base_url}/search/company"
            params = {"domain": domain, "api_key": self.api_key}

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                data = await self._handle_response(response, "contact enrichment")

                # Map Anymail Finder response to ContactData list
                contacts_data = self._map_contacts_response(data)

                return EnrichmentResult(
                    success=True,
                    data=contacts_data,
                    provider="anymail_finder",
                    cost=0.015,  # Anymail Finder cost per contact lookup
                )

        except Exception as exc:
            logging.error(
                f"Anymail Finder contact enrichment failed for {domain}: {exc}"
            )
            return EnrichmentResult(
                success=False, error=str(exc), provider="anymail_finder"
            )

    async def find_email(self, request: EnrichmentRequest) -> EnrichmentResult:
        """
        Find email address using Anymail Finder.

        Args:
            request: Enrichment request with domain, first_name, last_name

        Returns:
            Enrichment result with email data
        """
        domain = request.domain
        try:
            await self._rate_limit()

            url = f"{self.base_url}/search/name"
            params = {
                "domain": domain,
                "first_name": request.first_name,
                "last_name": request.last_name,
                "api_key": self.api_key,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                data = await self._handle_response(response, "email discovery")

                # Map Anymail Finder response to ContactData
                contact_data = self._map_email_response(data)

                return EnrichmentResult(
                    success=True,
                    data=contact_data,
                    provider="anymail_finder",
                    cost=0.012,  # Anymail Finder cost per email lookup
                )

        except Exception as exc:
            logging.error(f"Anymail Finder email discovery failed for {domain}: {exc}")
            return EnrichmentResult(
                success=False, error=str(exc), provider="anymail_finder"
            )

    def _map_company_response(
        self, response_data: Dict[str, Any], domain: str
    ) -> CompanyData:
        """
        Map Anymail Finder company response to CompanyData.

        Args:
            response_data: Raw response from Anymail Finder API
            domain: Domain for the company

        Returns:
            Mapped company data
        """
        company = CompanyData(domain=domain)

        # Extract company data from response
        company_info = response_data.get("company", {})
        if not isinstance(company_info, dict):
            return company

        # Map core company fields
        if company_info.get("name"):
            company.name = company_info["name"]

        if company_info.get("description"):
            company.description = company_info["description"]

        if company_info.get("industry"):
            company.industry = company_info["industry"]

        if company_info.get("size"):
            company.size = company_info["size"]

        if company_info.get("location"):
            company.address = {"city": company_info["location"]}

        if company_info.get("country"):
            company.address = company.address or {}
            company.address["country"] = company_info["country"]

        if company_info.get("website"):
            company.website = company_info["website"]

        if company_info.get("linkedin_url"):
            company.linkedin_url = company_info["linkedin_url"]

        return company

    def _map_contacts_response(
        self, response_data: Dict[str, Any]
    ) -> List[ContactData]:
        """
        Map Anymail Finder contacts response to ContactData list.

        Args:
            response_data: Raw response from Anymail Finder API

        Returns:
            List of mapped contact data
        """
        contacts = []

        # Extract contacts from response
        contacts_list = response_data.get("emails", [])
        if not isinstance(contacts_list, list):
            return contacts

        for contact_data in contacts_list:
            contact = ContactData()

            # Map core contact fields
            if contact_data.get("first_name"):
                contact.first_name = contact_data["first_name"]

            if contact_data.get("last_name"):
                contact.last_name = contact_data["last_name"]

            if contact_data.get("full_name"):
                contact.full_name = contact_data["full_name"]

            if contact_data.get("email"):
                contact.email = contact_data["email"]
                contact.email_source = ["provider"]
                contact.email_status = ["unknown"]

            if contact_data.get("phone"):
                contact.phone = contact_data["phone"]

            if contact_data.get("title"):
                contact.role = contact_data["title"]

            if contact_data.get("linkedin_url"):
                contact.linkedin_url = contact_data["linkedin_url"]

            if contact_data.get("department"):
                contact.department = contact_data["department"]

            if contact_data.get("seniority"):
                contact.seniority = contact_data["seniority"]

            # Add confidence score if available
            if contact_data.get("confidence"):
                contact.email_confidence = contact_data["confidence"]

            contacts.append(contact)

        return contacts

    def _map_email_response(self, response_data: Dict[str, Any]) -> ContactData:
        """
        Map Anymail Finder email response to ContactData.

        Args:
            response_data: Raw response from Anymail Finder API

        Returns:
            Mapped contact data with email
        """
        contact = ContactData()

        # Extract email data from response
        email_info = response_data.get("email", {})
        if not isinstance(email_info, dict):
            return contact

        # Map email-specific fields
        if email_info.get("email"):
            contact.email = email_info["email"]
            contact.email_source = ["provider"]
            contact.email_status = ["unknown"]

        if email_info.get("confidence"):
            contact.email_confidence = email_info["confidence"]

        if email_info.get("first_name"):
            contact.first_name = email_info["first_name"]

        if email_info.get("last_name"):
            contact.last_name = email_info["last_name"]

        if email_info.get("full_name"):
            contact.full_name = email_info["full_name"]

        if email_info.get("title"):
            contact.role = email_info["title"]

        return contact

    async def get_all_domain_prospects(
        self, request: EnrichmentRequest
    ) -> EnrichmentResult:
        """
        Get all domain prospects using Anymail Finder.

        Args:
            request: Enrichment request with domain

        Returns:
            Enrichment result with prospects data
        """
        # Anymail Finder doesn't have a prospects endpoint, so we'll use contacts instead
        return await self.enrich_contacts(request)

    async def search_prospect_email(
        self, request: EnrichmentRequest
    ) -> EnrichmentResult:
        """
        Search for prospect email using Anymail Finder.

        Args:
            request: Enrichment request with prospect_hash

        Returns:
            Enrichment result with email data
        """
        # Anymail Finder doesn't support prospect hash lookups
        # Return error indicating this method is not supported
        return EnrichmentResult(
            success=False,
            error="Anymail Finder doesn't support prospect hash email searches",
            provider="anymail_finder",
        )

    async def validate_email(self, email: str) -> EnrichmentResult:
        """
        Validate email address.

        This method is not supported by Anymail Finder API.
        """
        return EnrichmentResult(
            success=False,
            error="Email validation not supported by Anymail Finder API",
            provider="anymail_finder",
        )
