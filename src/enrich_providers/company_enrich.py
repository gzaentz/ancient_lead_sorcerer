"""
CompanyEnrich enrichment provider implementation.

This module implements the CompanyEnrich API client as an enrichment provider
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


class CompanyEnrichProvider(BaseEnrichmentProvider):
    """CompanyEnrich API enrichment provider."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize CompanyEnrich provider.

        Args:
            api_key: CompanyEnrich API key (defaults to env var COMPANY_ENRICH_API_KEY)
        """
        super().__init__(name="CompanyEnrich", tier=ProviderTier.TIER_0)
        self.api_key = api_key or os.getenv("COMPANY_ENRICH_API_KEY")
        if not self.api_key:
            raise AuthenticationError("CompanyEnrich API key not provided")

        self.base_url = "https://api.companyenrich.com/v1"
        self._last_request_time = 0.0
        self._min_request_interval = 0.1  # 100ms between requests (10 RPS limit)

        logging.info("CompanyEnrich provider initialized")

    async def _rate_limit(self):
        """Ensure we don't exceed CompanyEnrich's rate limits."""
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
            response: HTTP response from CompanyEnrich API
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
                f"CompanyEnrich API authentication failed for {operation}"
            )
        elif response.status_code == 429:
            retry_after = response.headers.get("retry-after", "60")
            raise RateLimitError(
                f"CompanyEnrich API rate limit exceeded for {operation}. Retry after {retry_after} seconds"
            )
        elif response.status_code == 503:
            raise ServiceUnavailableError(
                f"CompanyEnrich API service unavailable for {operation}"
            )
        else:
            error_msg = f"CompanyEnrich API error {response.status_code} for {operation}: {response.text}"
            raise CompanyEnrichmentError(error_msg)

    async def enrich_company(self, request: EnrichmentRequest) -> EnrichmentResult:
        """
        Enrich company information using CompanyEnrich.

        Args:
            request: Enrichment request with domain

        Returns:
            Enrichment result with company data
        """
        domain = request.domain
        try:
            await self._rate_limit()

            url = f"{self.base_url}/company/enrich"
            params = {"domain": domain, "api_key": self.api_key}

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                data = await self._handle_response(response, "company enrichment")

                # Map CompanyEnrich response to CompanyData
                company_data = self._map_company_response(data, domain)

                return EnrichmentResult(
                    success=True,
                    data=company_data,
                    provider="company_enrich",
                    cost=0.01,  # CompanyEnrich cost per company lookup
                )

        except Exception as exc:
            logging.error(
                f"CompanyEnrich company enrichment failed for {domain}: {exc}"
            )
            return EnrichmentResult(
                success=False, error=str(exc), provider="company_enrich"
            )

    async def enrich_contacts(self, request: EnrichmentRequest) -> EnrichmentResult:
        """
        Enrich company contacts using CompanyEnrich.

        Args:
            request: Enrichment request with domain

        Returns:
            Enrichment result with contact data
        """
        domain = request.domain
        try:
            await self._rate_limit()

            url = f"{self.base_url}/company/contacts"
            params = {"domain": domain, "api_key": self.api_key}

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                data = await self._handle_response(response, "contact enrichment")

                # Map CompanyEnrich response to ContactData list
                contacts_data = self._map_contacts_response(data)

                return EnrichmentResult(
                    success=True,
                    data=contacts_data,
                    provider="company_enrich",
                    cost=0.02,  # CompanyEnrich cost per contact lookup
                )

        except Exception as exc:
            logging.error(
                f"CompanyEnrich contact enrichment failed for {domain}: {exc}"
            )
            return EnrichmentResult(
                success=False, error=str(exc), provider="company_enrich"
            )

    async def find_email(self, request: EnrichmentRequest) -> EnrichmentResult:
        """
        Find email address using CompanyEnrich.

        Args:
            request: Enrichment request with domain, first_name, last_name

        Returns:
            Enrichment result with email data
        """
        domain = request.domain
        try:
            await self._rate_limit()

            url = f"{self.base_url}/email/find"
            params = {
                "domain": domain,
                "first_name": request.first_name,
                "last_name": request.last_name,
                "api_key": self.api_key,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                data = await self._handle_response(response, "email discovery")

                # Map CompanyEnrich response to ContactData
                contact_data = self._map_email_response(data)

                return EnrichmentResult(
                    success=True,
                    data=contact_data,
                    provider="company_enrich",
                    cost=0.015,  # CompanyEnrich cost per email lookup
                )

        except Exception as exc:
            logging.error(f"CompanyEnrich email discovery failed for {domain}: {exc}")
            return EnrichmentResult(
                success=False, error=str(exc), provider="company_enrich"
            )

    def _map_company_response(
        self, response_data: Dict[str, Any], domain: str
    ) -> CompanyData:
        """
        Map CompanyEnrich company response to CompanyData.

        Args:
            response_data: Raw response from CompanyEnrich API
            domain: Domain for the company

        Returns:
            Mapped company data
        """
        company = CompanyData(domain=domain)

        # Map core company fields
        if response_data.get("company_name"):
            company.name = response_data["company_name"]

        if response_data.get("description"):
            company.description = response_data["description"]

        if response_data.get("industry"):
            company.industry = response_data["industry"]

        if response_data.get("size"):
            company.size = response_data["size"]

        if response_data.get("location"):
            company.address = {"city": response_data["location"]}

        if response_data.get("country"):
            company.address = company.address or {}
            company.address["country"] = response_data["country"]

        if response_data.get("founded"):
            company.founded_year = response_data["founded"]

        if response_data.get("website"):
            company.website = response_data["website"]

        if response_data.get("linkedin_url"):
            company.linkedin_url = response_data["linkedin_url"]

        if response_data.get("technologies"):
            company.technologies = response_data["technologies"]

        return company

    def _map_contacts_response(
        self, response_data: Dict[str, Any]
    ) -> List[ContactData]:
        """
        Map CompanyEnrich contacts response to ContactData list.

        Args:
            response_data: Raw response from CompanyEnrich API

        Returns:
            List of mapped contact data
        """
        contacts = []

        # Extract contacts from response
        contacts_list = response_data.get("contacts", [])
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
                contact.job_title = contact_data["title"]

            if contact_data.get("linkedin_url"):
                contact.linkedin_url = contact_data["linkedin_url"]

            if contact_data.get("department"):
                contact.department = contact_data["department"]

            if contact_data.get("seniority"):
                contact.seniority = contact_data["seniority"]

            contacts.append(contact)

        return contacts

    def _map_email_response(self, response_data: Dict[str, Any]) -> ContactData:
        """
        Map CompanyEnrich email response to ContactData.

        Args:
            response_data: Raw response from CompanyEnrich API

        Returns:
            Mapped contact data with email
        """
        contact = ContactData()

        # Map email-specific fields
        if response_data.get("email"):
            contact.email = response_data["email"]
            contact.email_source = ["provider"]
            contact.email_status = ["unknown"]

        if response_data.get("confidence"):
            contact.email_confidence = response_data["confidence"]

        if response_data.get("first_name"):
            contact.first_name = response_data["first_name"]

        if response_data.get("last_name"):
            contact.last_name = response_data["last_name"]

        if response_data.get("full_name"):
            contact.full_name = response_data["full_name"]

        return contact

    async def get_all_domain_prospects(
        self, request: EnrichmentRequest
    ) -> EnrichmentResult:
        """
        Get all domain prospects using CompanyEnrich.

        Args:
            request: Enrichment request with domain

        Returns:
            Enrichment result with prospects data
        """
        # CompanyEnrich doesn't have a prospects endpoint, so we'll use contacts instead
        return await self.enrich_contacts(request)

    async def search_prospect_email(
        self, request: EnrichmentRequest
    ) -> EnrichmentResult:
        """
        Search for prospect email using CompanyEnrich.

        Args:
            request: Enrichment request with prospect_hash

        Returns:
            Enrichment result with email data
        """
        # CompanyEnrich doesn't support prospect hash lookups
        # Return error indicating this method is not supported
        return EnrichmentResult(
            success=False,
            error="CompanyEnrich doesn't support prospect hash email searches",
            provider="company_enrich",
        )

    async def validate_email(self, email: str) -> EnrichmentResult:
        """
        Validate email address.

        This method is not supported by CompanyEnrich API.
        """
        return EnrichmentResult(
            success=False,
            error="Email validation not supported by CompanyEnrich API",
            provider="company_enrich",
        )
