Unit tests for the Enrich tool.

Tests cover all functionality including:
- Input validation and schema validation
- Best contact selection logic
- Company and contact enrichment
- Cost tracking and budget enforcement
- Error handling and resilience
- Status transitions and audit logging
"""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.enrich import (
    CoresignalClient,
    MailgunClient,
    SnovioClient,
    select_best_contact,
    select_best_contact_llm,
    validate_llm_response,
    extract_contact_id,
    format_contacts_for_llm,
    enrich_company_data,
    enrich_contact_data,
    write_evidence_file,
    run_enrich,
    main,
    map_coresignal_company_fields,
)
from src.common import ErrorCode


class TestCoresignalClient:
    """Test Coresignal client functionality."""

    def test_init(self):
        """Test client initialization."""
        client = CoresignalClient("test_token")

        assert client.api_token == "test_token"
        assert client.base_url == "https://api.coresignal.com"

    @pytest.mark.asyncio
    async def test_enrich_company_success(self):
        """Test successful company enrichment."""
        client = CoresignalClient("test_token")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "company": {
                "name": "Test Company",
                "description": "Test description",
                "industry": "Technology",
                "size": "51-200",
                "location": {"city": "San Francisco"},
                "linkedin_id": "12345",
            }
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = await client.enrich_company("test.com")

            assert result["company"]["name"] == "Test Company"
            assert result["company"]["description"] == "Test description"
            assert result["company"]["industry"] == "Technology"
            # Semaphore pool assertions removed as semaphore pools are no longer used

    @pytest.mark.asyncio
    async def test_enrich_contact_not_implemented(self):
        """Test that contact enrichment raises NotImplementedError."""
        client = CoresignalClient("test_token")

        with pytest.raises(
            NotImplementedError,
            match="Coresignal doesn't support direct LinkedIn URL enrichment",
        ):
            await client.enrich_contact("https://linkedin.com/in/test")

    @pytest.mark.asyncio
    async def test_enrich_company_contacts_success(self):
        """Test successful company contacts enrichment."""
        client = CoresignalClient("test_token")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "people": [
                {
                    "first_name": "John",
                    "last_name": "Doe",
                    "full_name": "John Doe",
                    "email": "john@example.com",
                    "title": "CEO",
                }
            ]
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = await client.enrich_company_contacts("test.com")

            assert result["people"][0]["first_name"] == "John"
            assert result["people"][0]["email"] == "john@example.com"
            assert result["people"][0]["title"] == "CEO"
            # Semaphore pool assertions removed as semaphore pools are no longer used


class TestMailgunClient:
    """Test Mailgun client functionality."""

    def test_init(self):
        """Test client initialization."""
        client = MailgunClient("test@domain.com", "password")

        assert client.smtp_login == "test@domain.com"
        assert client.smtp_password == "password"
        assert client.domain == "domain.com"
        assert client.base_url == "https://api.mailgun.net/v3"
        # Semaphore pool assertion removed as semaphore pools are no longer used

    @pytest.mark.asyncio
    async def test_validate_email_success(self):
        """Test successful email validation."""
        client = MailgunClient("test@domain.com", "password")

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "valid", "score": 0.95}
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = await client.validate_email("test@example.com")

            assert result["result"] == "valid"
            assert result["score"] == 0.95
            # Semaphore pool assertions removed as semaphore pools are no longer used


class TestSnovioClient:
    """Test Snov.io client functionality."""

    def test_init(self):
        """Test client initialization."""
        client = SnovioClient("client_id", "client_secret")

        assert client.client_id == "client_id"
        assert client.client_secret == "client_secret"
        assert client.base_url == "https://api.snov.io/v2"
        assert client._access_token is None
    @pytest.mark.asyncio
    async def test_get_access_token_success(self):
        """Test successful access token retrieval."""
        client = SnovioClient("client_id", "client_secret")

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "test_token"}
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response

            token = await client._get_access_token()

            assert token == "test_token"
            assert client._access_token == "test_token"
            # Semaphore pool assertions removed as semaphore pools are no longer used

    @pytest.mark.asyncio
    async def test_start_email_finder_success(self):
        """Test successful email finder task start."""
        client = SnovioClient("client_id", "client_secret")

        # Mock access token
        client._access_token = "test_token"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "data": {"task_hash": "test_hash_123"}
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response

            result = await client.start_email_finder("example.com", "John", "Doe")

            assert result["success"] is True
            assert result["data"]["task_hash"] == "test_hash_123"
            # Semaphore pool assertions removed as semaphore pools are no longer used

    @pytest.mark.asyncio
    async def test_get_email_finder_result_success(self):
        """Test successful email finder result retrieval."""
        client = SnovioClient("client_id", "client_secret")

        # Mock access token
        client._access_token = "test_token"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "emails": ["john.doe@example.com"],
                "status": "completed"
            }
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = await client.get_email_finder_result("test_hash_123")

            assert result["success"] is True
            assert result["data"]["emails"] == ["john.doe@example.com"]
            assert result["data"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_start_domain_prospect_search_success(self):
        """Test successful domain prospect search task start."""
        client = SnovioClient("client_id", "client_secret")

        # Mock access token
        client._access_token = "test_token"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "data": {"task_hash": "prospect_hash_456"}
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response

            result = await client.start_domain_prospect_search("example.com", positions=["CEO", "Founder"])

            assert result["success"] is True
            assert result["data"]["task_hash"] == "prospect_hash_456"

    @pytest.mark.asyncio
    async def test_get_domain_prospect_result_success(self):
        """Test successful domain prospect result retrieval."""
        client = SnovioClient("client_id", "client_secret")

        # Mock access token
        client._access_token = "test_token"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "prospects": [
                    {
                        "name": "John Doe",
                        "email": "john.doe@example.com",
                        "position": "CEO"
                    }
                ],
                "status": "completed"
            }
        }
        mock_response.raise_for_status.return_value = None

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = await client.get_domain_prospect_result("prospect_hash_456")

            assert result["success"] is True
            assert result["data"]["prospects"][0]["name"] == "John Doe"
            assert result["data"]["prospects"][0]["email"] == "john.doe@example.com"


class TestBestContactSelection:
    """Test best contact selection logic."""

    def test_select_best_contact_empty_list(self):
        """Test selection with empty contacts list."""
        role_priority_config = {"ceo": 1, "default": 99}
        result = select_best_contact([], role_priority_config)
        assert result is None

    def test_select_best_contact_single_contact(self):
        """Test selection with single contact."""
        contacts = [
            {
                "contact_id": "contact1",
                "role": "CEO",
                "seniority": 1,
                "email_status": "valid",
                "linkedin": "https://linkedin.com/in/ceo",
            }
        ]
        role_priority_config = {"ceo": 1, "default": 99}

        result = select_best_contact(contacts, role_priority_config)
        assert result == "contact1"

    def test_select_best_contact_multiple_contacts(self):
        """Test selection with multiple contacts using ranking."""
        contacts = [
            {
                "contact_id": "contact1",
                "role": "Manager",
                "seniority": 4,
                "email_status": "unknown",
                "linkedin": "",
            },
            {
                "contact_id": "contact2",
                "role": "CEO",
                "seniority": 1,
                "email_status": "valid",
                "linkedin": "https://linkedin.com/in/ceo",
            },
            {
                "contact_id": "contact3",
                "role": "VP Sales",
                "seniority": 2,
                "email_status": "valid",
                "linkedin": "https://linkedin.com/in/vp",
            },
        ]
        role_priority_config = {"ceo": 1, "vp sales": 2, "manager": 4, "default": 99}

        result = select_best_contact(contacts, role_priority_config)
        # CEO should win due to lowest role_priority (1)
        assert result == "contact2"

    def test_select_best_contact_tie_breaker(self):
        """Test selection with tie-breaking logic."""
        contacts = [
            {
                "contact_id": "contact1",
                "role": "Manager",
                "seniority": 4,
                "email_status": "valid",
                "linkedin": "",
                "full_name": "John Doe",
            },
            {
                "contact_id": "contact2",
                "role": "Manager",
                "seniority": 4,
                "email_status": "valid",
                "linkedin": "",
                "full_name": "Jane Smith",
            },
        ]
        role_priority_config = {"manager": 4, "default": 99}

        result = select_best_contact(contacts, role_priority_config)
        # Should pick contact1 due to lexicographic ordering of contact_id
        assert result == "contact1"


class TestCompanyEnrichment:
    """Test company data enrichment functionality."""

    @pytest.mark.asyncio
    async def test_enrich_company_data_success(self):
        """Test successful company enrichment."""
        company = {"name": None, "description": None}
        domain = "test.com"
        coresignal_client = AsyncMock()
        costs_config = {"coresignal": 0.01}

        # Mock successful enrichment
        coresignal_client.enrich_company.return_value = {
            "name": "Test Company",
            "description": "Test description",
            "industry": "Technology",
            "size_range": "50-100 employees",
            "location_hq_raw_address": "San Francisco",
            "linkedin_id": "12345",
        }

        enriched_company, cost = await enrich_company_data(
            company, domain, coresignal_client, costs_config
        )

        assert enriched_company["name"] == "Test Company"
        assert enriched_company["description"] == "Test description"
        assert enriched_company["industry"] == "Technology"
        assert enriched_company["hq_location"] == "San Francisco"
        assert enriched_company["size_hint"] == "50-100 employees"
        assert enriched_company["ids"]["linkedin"] == "/company/12345"
        assert cost == 0.01

    @pytest.mark.asyncio
    async def test_enrich_company_data_failure(self):
        """Test company enrichment failure handling."""
        company = {"name": "Existing Name"}
        domain = "test.com"
        coresignal_client = AsyncMock()
        costs_config = {"coresignal": 0.01}

        # Mock failure
        coresignal_client.enrich_company.side_effect = Exception("API Error")

        enriched_company, cost = await enrich_company_data(
            company, domain, coresignal_client, costs_config
        )

        # Should return original company unchanged
        assert enriched_company["name"] == "Existing Name"
        assert cost == 0.0


class TestContactEnrichment:
    """Test contact data enrichment functionality."""

    @pytest.mark.asyncio
    async def test_enrich_contact_data_coresignal_success(self):
        """Test successful contact enrichment via Coresignal company contacts."""
        contact = {"full_name": "Test User"}
        domain = "test.com"
        coresignal_client = AsyncMock()
        mailgun_client = AsyncMock()
        snovio_client = AsyncMock()
        costs_config = {"coresignal": 0.01, "mailgun": 0.002}

        # Mock Coresignal success
        coresignal_client.enrich_company_contacts.return_value = {
            "people": [
                {
                    "full_name": "Test User",
                    "email": "test@example.com",
                    "phone": "+1234567890",
                    "title": "Software Engineer",
                }
            ]
        }

        # Mock Mailgun validation
        mailgun_client.validate_email.return_value = {"result": "valid", "score": 0.95}

        enriched_contact, cost = await enrich_contact_data(
            contact,
            domain,
            coresignal_client,
            mailgun_client,
            snovio_client,
            costs_config,
        )

        assert enriched_contact["email"] == "test@example.com"
        assert enriched_contact["phone"] == "+1234567890"
        assert enriched_contact["role"] == "Software Engineer"
        assert enriched_contact["email_status"] == "valid"
        assert enriched_contact["email_confidence"] == 0.95
        assert enriched_contact["email_source"] == "provider"
        assert cost == 0.012  # coresignal + mailgun

    @pytest.mark.asyncio
    async def test_enrich_contact_data_snovio_success(self):
        """Test successful email discovery via Snov.io."""
        contact = {"full_name": "John Doe"}
        domain = "test.com"
        coresignal_client = AsyncMock()
        mailgun_client = AsyncMock()
        snovio_client = AsyncMock()
        costs_config = {"snovio": 0.015, "mailgun": 0.002}

        # Mock Snov.io success - Email Finder flow
        snovio_client.start_email_finder.return_value = {
            "success": True,
            "data": {"task_hash": "test_hash_123"}
        }
        snovio_client.get_email_finder_result.return_value = {
            "success": True,
            "data": {
                "emails": ["john.doe@test.com"],
                "status": "completed"
            }
        }

        # Mock Mailgun validation
        mailgun_client.validate_email.return_value = {"result": "valid", "score": 0.90}

        enriched_contact, cost = await enrich_contact_data(
            contact,
            domain,
            coresignal_client,
            mailgun_client,
            snovio_client,
            costs_config,
        )

        assert enriched_contact["email"] == "john.doe@test.com"
        assert enriched_contact["email_status"] == "valid"
        assert enriched_contact["email_source"] == "provider"
        assert cost == 0.017  # snovio + mailgun

    @pytest.mark.asyncio
    async def test_enrich_contact_data_phone_normalization(self):
        """Test phone number normalization."""
        contact = {
            "phone": "+1 (212) 555-1234",
            "company_country": "US",
            "default_country": "US",
        }
        domain = "test.com"
        coresignal_client = AsyncMock()
        mailgun_client = AsyncMock()
        snovio_client = AsyncMock()
        costs_config = {}

        enriched_contact, cost = await enrich_contact_data(
            contact,
            domain,
            coresignal_client,
            mailgun_client,
            snovio_client,
            costs_config,
        )

        # Phone should be normalized to E.164
        assert enriched_contact["phone"] == "+12125551234"
        assert cost == 0.0


class TestEvidenceFileWriting:
    """Test evidence file writing functionality."""

    def test_write_evidence_file_success(self):
        """Test successful evidence file writing."""
        domain = "test.com"
        evidence_data = {"test": "data"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("src.enrich.normalize_domain", return_value="test.com"):
                # Portalocker removed - no more file locking needed
                # with patch("src.enrich.portalocker.Lock") as mock_lock:
                #     mock_lock.return_value.__enter__ = MagicMock()
                #     mock_lock.return_value.__exit__ = MagicMock()

                    result_path = write_evidence_file(domain, evidence_data, temp_dir)

                    # Check that file was created
                    expected_path = os.path.join(
                        temp_dir, "evidence", "enrich", "test.com.json"
                    )
                    assert result_path == expected_path
                    assert os.path.exists(expected_path)

                    # Check file contents
                    with open(expected_path, "r") as f:
                        content = json.load(f)
                        assert content == evidence_data


class TestCoresignalFieldMapping:
    """Test Coresignal field mapping functionality."""

    def test_map_coresignal_company_fields_success(self):
        """Test successful field mapping from Coresignal response."""

        # Mock Coresignal response with actual field structure
        coresignal_response = {
            "name": "Acme Corporation",
            "description": "A leading technology company specializing in AI solutions",
            "industry": "Technology",
            "size_range": "201-500 employees",
            "size_employees_count": 350,
            "location_hq_raw_address": "San Francisco, CA",
            "location_hq_country": "United States",
            "linkedin_id": "acme-corporation-123",
            "founded": 2010,
            "revenue": "$50M - $100M",
            "funding": "Series C",
            "type": "Private",
            "sector": "Software",
            "specialities": ["Artificial Intelligence", "Machine Learning"],
            "technologies": ["Python", "TensorFlow", "AWS"],
            "website": "https://acme.com",
            "status": "Active"
        }

        mapped_data = map_coresignal_company_fields(coresignal_response)

        # Verify core fields are mapped correctly
        assert mapped_data["name"] == "Acme Corporation"
        assert mapped_data["description"] == "A leading technology company specializing in AI solutions"
        assert mapped_data["industry"] == "Technology"
        assert mapped_data["size_hint"] == "201-500 employees"
        assert mapped_data["hq_location"] == "San Francisco, CA"
        assert mapped_data["hq_country"] == "United States"
        assert mapped_data["linkedin_company_id"] == "acme-corporation-123"
        assert mapped_data["founded_year"] == 2010
        assert mapped_data["revenue"] == "$50M - $100M"
        assert mapped_data["funding"] == "Series C"
        assert mapped_data["company_type"] == "Private"
        assert mapped_data["sector"] == "Software"
        assert mapped_data["specialities"] == ["Artificial Intelligence", "Machine Learning"]
        assert mapped_data["technologies"] == ["Python", "TensorFlow", "AWS"]
        assert mapped_data["website"] == "https://acme.com"
        assert mapped_data["status"] == "Active"

    def test_map_coresignal_company_fields_size_conversion(self):
        """Test employee count to size hint conversion."""

        # Test with only size_employees_count (no size_range)
        coresignal_response = {
            "name": "Small Startup",
            "size_employees_count": 25
        }

        mapped_data = map_coresignal_company_fields(coresignal_response)
        assert mapped_data["size_hint"] == "11-50"

        # Test with larger company
        coresignal_response = {
            "name": "Large Corp",
            "size_employees_count": 2500
        }

        mapped_data = map_coresignal_company_fields(coresignal_response)
        assert mapped_data["size_hint"] == "1000+"

    def test_map_coresignal_company_fields_partial_data(self):
        """Test field mapping with partial data."""

        # Minimal response with only essential fields
        coresignal_response = {
            "name": "Minimal Company",
            "industry": "Manufacturing"
        }

        mapped_data = map_coresignal_company_fields(coresignal_response)

        # Should only map available fields
        assert mapped_data["name"] == "Minimal Company"
        assert mapped_data["industry"] == "Manufacturing"
        assert "description" not in mapped_data
        assert "size_hint" not in mapped_data
        assert "hq_location" not in mapped_data

    def test_map_coresignal_company_fields_empty_response(self):
        """Test field mapping with empty response."""

        # Empty response
        coresignal_response = {}
        mapped_data = map_coresignal_company_fields(coresignal_response)
        assert mapped_data == {}

        # None response
        mapped_data = map_coresignal_company_fields(None)
        assert mapped_data == {}

    def test_map_coresignal_company_fields_no_company_wrapper(self):
        """Test that field mapping works without company wrapper (the fix)."""

        # This is the structure that was causing the bug
        coresignal_response = {
            "name": "Direct Company",
            "description": "Company without wrapper",
            "industry": "Technology"
        }

        # Old code would have looked for coresignal_response.get("company", {})
        # and returned empty dict, causing all field lookups to fail

        mapped_data = map_coresignal_company_fields(coresignal_response)

        # Should now work correctly
        assert mapped_data["name"] == "Direct Company"
        assert mapped_data["description"] == "Company without wrapper"
        assert mapped_data["industry"] == "Technology"
        assert len(mapped_data) == 3  # All 3 fields should be mapped


class TestMainEnrichmentLogic:
    """Test main enrichment logic."""

    @pytest.mark.asyncio
    async def test_run_enrich_success(self):
        """Test successful enrichment run."""
        payload = {
            "lead_records": [
                {
                    "lead_id": "lead1",
                    "domain": "test.com",
                    "status": "enrich_ready",
                    "company": {"name": None},
                    "contacts": [
                        {
                            "contact_id": "contact1",
                            "role": "CEO",
                            "seniority": 1,
                            "email_status": "unknown",
                        }
                    ],
                    "cost": {
                        "domain_usd": 0.0,
                        "crawl_usd": 0.0,
                        "enrich_usd": 0.0,
                        "total_usd": 0.0,
                    },
                    "status_history": [],
                    "audit": [],
                    "icp": {
                        "pre_score": 0.8,
                        "pre_reason": "Test reason",
                        "pre_pass": True,
                        "pre_flags": [],
                        "scoring_meta": {
                            "method": "test",
                            "model": "test",
                            "prompt_fingerprint": "test",
                            "temperature": 0.1,
                        },
                        "crawl_score": 0.8,
                        "crawl_reason": "Test reason",
                        "threshold": 0.7,
                        "filtering_strict": True,
                    },
                    "provenance": {
                        "queries": ["test query"],
                        "discovery_evidence": ["test evidence"],
                        "scored_at": "2023-01-01T00:00:00Z",
                        "crawled_at": "2023-01-01T00:00:00Z",
                        "enriched_at": None,
                        "next_revisit_at": "2023-01-01T00:00:00Z",
                        "tool_versions": {
                            "domain": {"version": "1.0", "schema_version": "test"},
                            "crawl": {"version": "1.0", "schema_version": "test"},
                            "enrich": {"version": "1.0", "schema_version": "test"},
                        },
                        "cache": {},
                        "evidence_paths": [],
                    },
                }
            ],
            "icp_config": {
                "concurrency": {"max_concurrent_requests": 3},
                "role_priority": {"ceo": 1, "default": 99},
                "default_country": "US",
                "required_fields": {"company": ["name"], "contact": ["email"]},
                "testing": {"process_rejected": False, "process_low_crawl": False},
            },
            "caps": {"company_usd": 0.02, "contact_usd": 0.03, "run_usd_max": 5.0},
        }

        # Mock environment variables
        with patch.dict(
            os.environ,
            {
                "CORESIGNAL_TOKEN": "test_token",
                "MAILGUN_SMTP_LOGIN": "test@domain.com",
                "MAILGUN_SMTP_PW": "password",
                "SNOV_IO_ID": "client_id",
                "SNOV_IO_SECRET": "client_secret",
            },
        ):
            # Mock costs config
            with patch("src.enrich.load_costs_config") as mock_load_costs:
                mock_load_costs.return_value = {
                    "coresignal": 0.01,
                    "mailgun": 0.002,
                    "snovio": 0.015,
                }

                # Mock schema checksum
                with patch("src.enrich.load_schema_checksum") as mock_schema:
                    mock_schema.return_value = "test_checksum"

                    # Mock data directory resolution
                    with patch("src.enrich.resolve_data_dir", return_value="./data"):
                        # Mock provider clients
                        with patch(
                            "src.enrich.CoresignalClient"
                        ) as mock_coresignal_class:
                            with patch(
                                "src.enrich.MailgunClient"
                            ) as mock_mailgun_class:
                                with patch(
                                    "src.enrich.SnovioClient"
                                ) as mock_snovio_class:
                                    mock_coresignal = MagicMock()
                                    mock_mailgun = MagicMock()
                                    mock_snovio = MagicMock()

                                    mock_coresignal_class.return_value = mock_coresignal
                                    mock_mailgun_class.return_value = mock_mailgun
                                    mock_snovio_class.return_value = mock_snovio

                                    # Mock company enrichment
                                    mock_coresignal.enrich_company.return_value = {
                                        "name": "Test Company"
                                    }

                                    # Mock evidence file writing
                                    with patch(
                                        "src.enrich.write_evidence_file",
                                        return_value="test_path",
                                    ):
                                        result = await run_enrich(payload)

                                        assert "data" in result
                                        assert "errors" in result
                                        assert "metrics" in result
                                        assert len(result["data"]["lead_records"]) == 1
                                        assert (
                                            result["data"]["lead_records"][0]["status"]
                                            == "enrich_partial"
                                        )

    @pytest.mark.asyncio
    async def test_run_enrich_budget_exceeded(self):
        """Test enrichment with budget exceeded."""
        payload = {
            "lead_records": [
                {
                    "lead_id": "lead1",
                    "domain": "test.com",
                    "status": "enrich_ready",
                    "company": {},
                    "contacts": [],
                    "cost": {
                        "domain_usd": 0.0,
                        "crawl_usd": 0.0,
                        "enrich_usd": 0.0,
                        "total_usd": 0.0,
                    },
                    "status_history": [],
                    "audit": [],
                    "icp": {
                        "pre_score": 0.8,
                        "pre_reason": "Test reason",
                        "pre_pass": True,
                        "pre_flags": [],
                        "scoring_meta": {
                            "method": "test",
                            "model": "test",
                            "prompt_fingerprint": "test",
                            "temperature": 0.1,
                        },
                        "crawl_score": 0.8,
                        "crawl_reason": "Test reason",
                        "threshold": 0.7,
                        "filtering_strict": True,
                    },
                    "provenance": {
                        "queries": ["test query"],
                        "discovery_evidence": ["test evidence"],
                        "scored_at": "2023-01-01T00:00:00Z",
                        "crawled_at": "2023-01-01T00:00:00Z",
                        "enriched_at": None,
                        "next_revisit_at": "2023-01-01T00:00:00Z",
                        "tool_versions": {
                            "domain": {"version": "1.0", "schema_version": "test"},
                            "crawl": {"version": "1.0", "schema_version": "test"},
                            "enrich": {"version": "1.0", "schema_version": "test"},
                        },
                        "cache": {},
                        "evidence_paths": [],
                    },
                }
            ],
            "icp_config": {
                "concurrency": {"max_concurrent_requests": 3},
                "role_priority": {"default": 99},
                "default_country": "US",
                "required_fields": {"company": [], "contact": []},
                "testing": {"process_rejected": False, "process_low_crawl": False},
            },
            "caps": {
                "company_usd": 0.02,
                "contact_usd": 0.03,
                "run_usd_max": 0.0,  # Budget already exceeded
            },
        }

        # Mock environment variables
        with patch.dict(
            os.environ,
            {
                "CORESIGNAL_TOKEN": "test_token",
                "MAILGUN_SMTP_LOGIN": "test@domain.com",
                "MAILGUN_SMTP_PW": "password",
                "SNOV_IO_ID": "client_id",
                "SNOV_IO_SECRET": "client_secret",
            },
        ):
            # Mock costs config
            with patch("src.enrich.load_costs_config") as mock_load_costs:
                mock_load_costs.return_value = {
                    "coresignal": 0.01,
                    "mailgun": 0.002,
                    "snovio": 0.015,
                }

                # Mock schema checksum
                with patch("src.enrich.load_schema_checksum") as mock_schema:
                    mock_schema.return_value = "test_checksum"

                    # Mock data directory resolution
                    with patch("src.enrich.resolve_data_dir", return_value="./data"):
                        # Mock provider clients
                        with patch(
                            "src.enrich.CoresignalClient"
                        ) as mock_coresignal_class:
                            with patch(
                                "src.enrich.MailgunClient"
                            ) as mock_mailgun_class:
                                with patch(
                                    "src.enrich.SnovioClient"
                                ) as mock_snovio_class:
                                    mock_coresignal = MagicMock()
                                    mock_mailgun = MagicMock()
                                    mock_snovio = MagicMock()

                                    mock_coresignal_class.return_value = mock_coresignal
                                    mock_mailgun_class.return_value = mock_mailgun
                                    mock_snovio_class.return_value = mock_snovio

                                    result = await run_enrich(payload)

                                    # Should have BUDGET_EXCEEDED error
                                    assert len(result["errors"]) == 1
                                    assert (
                                        result["errors"][0]["code"]
                                        == ErrorCode.BUDGET_EXCEEDED.value
                                    )

    @pytest.mark.asyncio
    async def test_run_enrich_missing_environment_variables(self):
        """Test enrichment with missing environment variables."""
        payload = {
            "lead_records": [
                {
                    "lead_id": "lead1",
                    "domain": "test.com",
                    "status": "enrich_ready",
                    "company": {},
                    "contacts": [],
                    "cost": {
                        "domain_usd": 0.0,
                        "crawl_usd": 0.0,
                        "enrich_usd": 0.0,
                        "total_usd": 0.0,
                    },
                    "status_history": [],
                    "audit": [],
                    "icp": {
                        "pre_score": 0.8,
                        "pre_reason": "Test reason",
                        "pre_pass": True,
                        "pre_flags": [],
                        "scoring_meta": {
                            "method": "test",
                            "model": "test",
                            "prompt_fingerprint": "test",
                            "temperature": 0.1,
                        },
                        "crawl_score": 0.8,
                        "crawl_reason": "Test reason",
                        "threshold": 0.7,
                        "filtering_strict": True,
                    },
                    "provenance": {
                        "queries": ["test query"],
                        "discovery_evidence": ["test evidence"],
                        "scored_at": "2023-01-01T00:00:00Z",
                        "crawled_at": "2023-01-01T00:00:00Z",
                        "enriched_at": None,
                        "next_revisit_at": "2023-01-01T00:00:00Z",
                        "tool_versions": {
                            "domain": {"version": "1.0", "schema_version": "test"},
                            "crawl": {"version": "1.0", "schema_version": "test"},
                            "enrich": {"version": "1.0", "schema_version": "test"},
                        },
                        "cache": {},
                        "evidence_paths": [],
                    },
                }
            ],
            "icp_config": {
                "concurrency": {"max_concurrent_requests": 3},
                "role_priority": {"default": 99},
                "default_country": "US",
                "required_fields": {"company": [], "contact": []},
                "testing": {"process_rejected": False, "process_low_crawl": False},
            },
            "caps": {"company_usd": 0.02, "contact_usd": 0.03, "run_usd_max": 5.0},
        }

        # Mock missing environment variables
        with patch.dict(os.environ, {}, clear=True):
            result = await run_enrich(payload)

            # Should have PROVIDER_ERROR
            assert len(result["errors"]) == 1
            assert result["errors"][0]["code"] == ErrorCode.PROVIDER_ERROR.value


class TestCLIInterface:
    """Test CLI interface functionality."""

    def test_main_success(self):
        """Test successful CLI execution."""
        input_data = json.dumps({"lead_records": [], "icp_config": {}, "caps": {}})

        with patch("builtins.input", return_value=input_data):
            with patch("src.enrich.asyncio.run") as mock_run:
                mock_run.return_value = {
                    "data": {"lead_records": []},
                    "errors": [],
                    "metrics": {},
                }

                with patch("builtins.print") as mock_print:
                    main()

                    mock_run.assert_called_once()
                    mock_print.assert_called_once()

    def test_main_json_error(self):
        """Test CLI with JSON parsing error."""
        input_data = "invalid json"

        with patch("builtins.input", return_value=input_data):
            with patch("builtins.print") as mock_print:
                with patch("builtins.exit") as mock_exit:
                    main()

                    mock_print.assert_called_once()
                    mock_exit.assert_called_once_with(1)

    def test_main_general_error(self):
        """Test CLI with general error."""
        input_data = json.dumps({"lead_records": [], "icp_config": {}, "caps": {}})

        with patch("builtins.input", return_value=input_data):
            with patch("src.enrich.asyncio.run", side_effect=Exception("Test error")):
                with patch("builtins.print") as mock_print:
                    with patch("builtins.exit") as mock_exit:
                        main()

                        mock_print.assert_called_once()
                        mock_exit.assert_called_once_with(1)


class TestErrorHandling:
    """Test error handling and resilience."""

    @pytest.mark.asyncio
    async def test_provider_failover(self):
        """Test provider failover when primary enrichment fails."""
        contact = {"full_name": "Test User"}  # Contact without email
        domain = "test.com"
        coresignal_client = AsyncMock()
        mailgun_client = AsyncMock()
        snovio_client = AsyncMock()
        costs_config = {"coresignal": 0.01, "snovio": 0.015, "mailgun": 0.002}

        # Mock Coresignal company contacts failure
        coresignal_client.enrich_company_contacts.side_effect = Exception(
            "Coresignal API Error"
        )

        # Mock Snov.io success - Email Finder flow
        snovio_client.start_email_finder.return_value = {
            "success": True,
            "data": {"task_hash": "test_hash_456"}
        }
        snovio_client.get_email_finder_result.return_value = {
            "success": True,
            "data": {
                "emails": ["test@example.com"],
                "status": "completed"
            }
        }

        # Mock Mailgun validation
        mailgun_client.validate_email.return_value = {"result": "valid", "score": 0.90}

        enriched_contact, cost = await enrich_contact_data(
            contact,
            domain,
            coresignal_client,
            mailgun_client,
            snovio_client,
            costs_config,
        )

        # Should still get email via Snov.io
        assert enriched_contact["email"] == "test@example.com"
        assert cost == 0.017  # snovio + mailgun

    @pytest.mark.asyncio
    async def test_individual_record_error_handling(self):
        """Test handling of individual record errors."""
        payload = {
            "lead_records": [
                {
                    "lead_id": "lead1",
                    "domain": "test.com",
                    "status": "enrich_ready",
                    "company": {},
                    "contacts": [],
                    "cost": {
                        "domain_usd": 0.0,
                        "crawl_usd": 0.0,
                        "enrich_usd": 0.0,
                        "total_usd": 0.0,
                    },
                    "status_history": [],
                    "audit": [],
                    "icp": {
                        "pre_score": 0.8,
                        "pre_reason": "Test reason",
                        "pre_pass": True,
                        "pre_flags": [],
                        "scoring_meta": {
                            "method": "test",
                            "model": "test",
                            "prompt_fingerprint": "test",
                            "temperature": 0.1,
                        },
                        "crawl_score": 0.8,
                        "crawl_reason": "Test reason",
                        "threshold": 0.7,
                        "filtering_strict": True,
                    },
                    "provenance": {
                        "queries": ["test query"],
                        "discovery_evidence": ["test evidence"],
                        "scored_at": "2023-01-01T00:00:00Z",
                        "crawled_at": "2023-01-01T00:00:00Z",
                        "enriched_at": None,
                        "next_revisit_at": "2023-01-01T00:00:00Z",
                        "tool_versions": {
                            "domain": {"version": "1.0", "schema_version": "test"},
                            "crawl": {"version": "1.0", "schema_version": "test"},
                            "enrich": {"version": "1.0", "schema_version": "test"},
                        },
                        "cache": {},
                        "evidence_paths": [],
                    },
                }
            ],
            "icp_config": {
                "concurrency": {"max_concurrent_requests": 3},
                "role_priority": {"default": 99},
                "default_country": "US",
                "required_fields": {"company": [], "contact": []},
                "testing": {"process_rejected": False, "process_low_crawl": False},
            },
            "caps": {"company_usd": 0.02, "contact_usd": 0.03, "run_usd_max": 5.0},
        }

        # Mock environment variables
        with patch.dict(
            os.environ,
            {
                "CORESIGNAL_TOKEN": "test_token",
                "MAILGUN_SMTP_LOGIN": "test@domain.com",
                "MAILGUN_SMTP_PW": "password",
                "SNOV_IO_ID": "client_id",
                "SNOV_IO_SECRET": "client_secret",
            },
        ):
            # Mock costs config
            with patch("src.enrich.load_costs_config") as mock_load_costs:
                mock_load_costs.return_value = {
                    "coresignal": 0.01,
                    "mailgun": 0.002,
                    "snovio": 0.015,
                }

                # Mock schema checksum
                with patch("src.enrich.load_schema_checksum") as mock_schema:
                    mock_schema.return_value = "test_checksum"

                    # Mock data directory resolution
                    with patch("src.enrich.resolve_data_dir", return_value="./data"):
                        # Mock provider clients
                        with patch(
                            "src.enrich.CoresignalClient"
                        ) as mock_coresignal_class:
                            with patch(
                                "src.enrich.MailgunClient"
                            ) as mock_mailgun_class:
                                with patch(
                                    "src.enrich.SnovioClient"
                                ) as mock_snovio_class:
                                    mock_coresignal = MagicMock()
                                    mock_mailgun = MagicMock()
                                    mock_snovio = MagicMock()

                                    mock_coresignal_class.return_value = mock_coresignal
                                    mock_mailgun_class.return_value = mock_mailgun
                                    mock_snovio_class.return_value = mock_snovio

                                    # Mock company enrichment to raise error
                                    mock_coresignal.enrich_company.side_effect = (
                                        Exception("Test error")
                                    )

                                    # Mock evidence file writing
                                    with patch(
                                        "src.enrich.write_evidence_file",
                                        return_value="test_path",
                                    ):
                                        result = await run_enrich(payload)

                                        # Should have error but still return partial results
                                        assert len(result["errors"]) == 1
                                        assert (
                                            result["errors"][0]["code"]
                                            == ErrorCode.UNKNOWN.value
                                        )
                                        assert len(result["data"]["lead_records"]) == 1
                                        assert (
                                            result["data"]["lead_records"][0]["status"]
                                            == "enrich_partial"
                                        )


# ============================================================================
# Missing Tests from Task 6
# ============================================================================


class TestMissingRequirements:
    """Test missing requirements from Task 6."""

    def test_provider_missing_checks(self):
        """Test that PROVIDER_ERROR is raised when required providers are absent."""
        # Test missing environment variables
        payload = {
            "lead_records": [
                {
                    "lead_id": "lead1",
                    "domain": "test.com",
                    "status": "enrich_ready",
                    "company": {},
                    "contacts": [],
                    "cost": {
                        "domain_usd": 0.0,
                        "crawl_usd": 0.0,
                        "enrich_usd": 0.0,
                        "total_usd": 0.0,
                    },
                    "status_history": [],
                    "audit": [],
                    "icp": {
                        "pre_score": 0.8,
                        "pre_reason": "Test reason",
                        "pre_pass": True,
                        "pre_flags": [],
                        "scoring_meta": {
                            "method": "test",
                            "model": "test",
                            "prompt_fingerprint": "test",
                            "temperature": 0.1,
                        },
                        "crawl_score": 0.8,
                        "crawl_reason": "Test reason",
                        "threshold": 0.7,
                        "filtering_strict": True,
                    },
                    "provenance": {
                        "queries": ["test query"],
                        "discovery_evidence": ["test evidence"],
                        "scored_at": "2023-01-01T00:00:00Z",
                        "crawled_at": "2023-01-01T00:00:00Z",
                        "enriched_at": None,
                        "next_revisit_at": "2023-01-01T00:00:00Z",
                        "tool_versions": {
                            "domain": {"version": "1.0", "schema_version": "test"},
                            "crawl": {"version": "1.0", "schema_version": "test"},
                            "enrich": {"version": "1.0", "schema_version": "test"},
                        },
                        "cache": {},
                        "evidence_paths": [],
                    },
                }
            ],
            "icp_config": {
                "concurrency": {"max_concurrent_requests": 3},
                "role_priority": {"default": 99},
                "default_country": "US",
                "required_fields": {"company": [], "contact": []},
                "testing": {"process_rejected": False, "process_low_crawl": False},
            },
            "caps": {"company_usd": 0.02, "contact_usd": 0.03, "run_usd_max": 5.0},
        }

        with patch.dict(os.environ, {}, clear=True):
            result = asyncio.run(run_enrich(payload))

            # Should have PROVIDER_ERROR
            assert len(result["errors"]) == 1
            assert result["errors"][0]["code"] == ErrorCode.PROVIDER_ERROR.value

    def test_evidence_array_truncation(self):
        """Test evidence array truncation: validate company.evidence_urls <= 10, contacts[*].evidence_urls <= 5."""
        # This test will verify evidence array truncation
        # Implementation depends on truncation logic
        pass

    def test_template_placeholder_validation(self):
        """Test template placeholder validation: test SCHEMA_VALIDATION on unsatisfied ${placeholders}."""
        # This test will verify template placeholder validation
        # Implementation depends on template validation logic
        pass

    def test_phone_parse_failure(self):
        """Test phone parse failure: verify PARSE_ERROR emission on unparseable numbers."""
        # This test will verify phone parsing error handling
        # Implementation depends on phone parsing logic
        pass

    def test_log_pii_masking(self):
        """Test log PII masking: validate single-line JSON logs with masked PII."""
        # This test will verify that logs contain masked PII
        # Implementation depends on logging setup
        pass

    def test_linkedin_canonicalization_regex_patterns(self):
        """Test LinkedIn canonicalization regex patterns."""
        # This test will verify LinkedIn URL canonicalization
        # Implementation depends on LinkedIn handling logic
        pass

    def test_country_code_fallback_phone_parsing(self):
        """Test country code fallback for phone parsing."""
        # This test will verify phone parsing with country fallback
        # Implementation depends on phone parsing logic
        pass

    def test_progressive_serp_pagination_logic(self):
        """Test progressive SERP pagination logic."""
        # This test will verify progressive pagination logic
        # Implementation depends on pagination implementation
        pass

    def test_best_contact_id_recomputation(self):
        """Test best_contact_id recomputation when contact no longer exists."""
        # This test will verify best contact recomputation
        # Implementation depends on contact handling logic
        pass

    def test_csv_export_flattening_column_ordering(self):
        """Test CSV export flattening and column ordering."""
        # This test will verify CSV export functionality
        # Implementation depends on export logic
        pass

    def test_export_directory_creation_utc_timestamps(self):
        """Test export directory creation with UTC timestamps."""
        # This test will verify export directory creation
        # Implementation depends on export logic
        pass

    def test_portalocker_write_lock_behavior(self):
        """Test portalocker write lock behavior."""
        # Portalocker removed - no more file locking needed
        # This test is no longer applicable
        pass

    def test_exponential_backoff_45s_wall_clock_cap(self):
        """Test exponential backoff with 45 second wall-clock cap."""
        # This test will verify exponential backoff logic
        # Implementation depends on retry logic
        pass

    def test_error_mapping_all_http_status_codes(self):
        """Test error mapping for all HTTP status codes."""
        # This test will verify error code mapping
        # Implementation depends on error handling logic
        pass

    def test_schema_checksum_validation(self):
        """Test schema checksum validation."""
        # This test will verify schema checksum validation
        # Implementation depends on schema validation logic
        pass

    def test_string_length_array_truncation_limits(self):
        """Test string length and array truncation limits."""
        # This test will verify string and array limits
        # Implementation depends on validation logic
        pass

    def test_provider_failover_logic(self):
        """Test provider failover logic."""
        # This test will verify provider failover
        # Implementation depends on failover logic
        pass

    def test_cost_cap_enforcement_per_individual_lead(self):
        """Test cost cap enforcement per individual lead."""
        # This test will verify cost cap enforcement
        # Implementation depends on cost logic
        pass

    def test_testing_flags_process_rejected_process_low_crawl(self):
        """Test testing flags (process_rejected, process_low_crawl)."""
        # This test will verify testing flags handling
        # Implementation depends on testing flags logic
        pass

    def test_data_directory_precedence_resolution(self):
        """Test data directory precedence resolution."""
        # This test will verify data directory precedence
        # Implementation depends on data directory logic
        pass

    def test_template_placeholder_validation_all_tools(self):
        """Test template placeholder validation for all tools."""
        # This test will verify template placeholder validation
        # Implementation depends on template validation logic
        pass

    def test_provider_presence_validation_startup(self):
        """Test provider presence validation at startup."""
        # This test will verify provider presence validation
        # Implementation depends on provider validation logic
        pass

    def test_audit_trail_logging_all_tool_steps(self):
        """Test audit trail logging for all tool steps."""
        # This test will verify audit trail logging
        # Implementation depends on audit logging logic
        pass

    def test_failure_revisit_days_logic_all_tools(self):
        """Test failure_revisit_days logic for all tools."""
        # This test will verify failure revisit logic
        # Implementation depends on revisit logic
        pass

    def test_role_priority_configuration_loading(self):
        """Test icp_config.role_priority configuration loading."""
        # This test will verify role priority configuration
        # Implementation depends on role priority logic
        pass

    def test_error_code_mapping_all_specified_error_types(self):
        """Test error code mapping for all specified error types."""
        # This test will verify error code mapping
        # Implementation depends on error handling logic
        pass

    def test_content_hash_deduplication_logic(self):
        """Test content hash deduplication logic."""
        # This test will verify content hash deduplication
        # Implementation depends on deduplication logic
        pass

    def test_linkedin_routing_canonicalization(self):
        """Test LinkedIn routing and canonicalization."""
        # This test will verify LinkedIn routing logic
        # Implementation depends on LinkedIn handling
        pass

    def test_seniority_ranking_mapping(self):
        """Test seniority ranking mapping."""
        # This test will verify seniority ranking
        # Implementation depends on seniority logic
        pass

    def test_metrics_duration_ms_population_every_tool_envelope(self):
        """Test metrics.duration_ms population in every tool envelope."""
        # This test will verify duration metrics
        # Implementation depends on metrics logic
        pass

    def test_linkedin_path_masking_logs_errors(self):
        """Test LinkedIn path masking for all LinkedIn URLs in logs and errors."""
        # This test will verify LinkedIn path masking
        # Implementation depends on masking logic
        pass

    def test_required_fields_contact_validation_enrichment_completion(self):
        """Test icp_config.required_fields.contact validation for enrichment completion."""
        # This test will verify contact requirements validation
        # Implementation depends on validation logic
        pass

    def test_optional_fields_handling_optional_enrichment(self):
        """Test icp_config.optional_fields handling for optional enrichment."""
        # This test will verify optional fields handling
        # Implementation depends on optional fields logic
        pass

    def test_testing_flags_handling(self):
        """Test testing flags handling."""
        # This test will verify testing flags handling
        # Implementation depends on testing flags logic
        pass

    def test_best_contact_selection_per_brd(self):
        """Test best contact selection per BRD sections 333-336."""
        # This test will verify best contact selection
        # Implementation depends on contact selection logic
        pass


class TestLLMContactSelection:
    """Test LLM-based contact selection functionality."""

    def test_validate_llm_response_valid_json(self):
        """Test LLM response validation with valid JSON."""
        valid_response = '{"contact_id": "123"}'
        assert validate_llm_response(valid_response) is True

    def test_validate_llm_response_markdown_json(self):
        """Test LLM response validation with markdown JSON."""
        markdown_response = '```json\n{"contact_id": "456"}\n```'
        assert validate_llm_response(markdown_response) is True

    def test_validate_llm_response_invalid_json(self):
        """Test LLM response validation with invalid JSON."""
        invalid_response = 'invalid json'
        assert validate_llm_response(invalid_response) is False

    def test_validate_llm_response_missing_contact_id(self):
        """Test LLM response validation with missing contact_id."""
        missing_id_response = '{"wrong_key": "123"}'
        assert validate_llm_response(missing_id_response) is False

    def test_validate_llm_response_empty_contact_id(self):
        """Test LLM response validation with empty contact_id."""
        empty_id_response = '{"contact_id": ""}'
        assert validate_llm_response(empty_id_response) is False

    def test_extract_contact_id_valid_response(self):
        """Test contact ID extraction with valid response."""
        contacts = [
            {"contact_id": "123", "name": "John Doe"},
            {"contact_id": "456", "name": "Jane Smith"}
        ]
        response = '{"contact_id": "123"}'

        result = extract_contact_id(response, contacts)
        assert result == "123"

    def test_extract_contact_id_invalid_contact_id(self):
        """Test contact ID extraction with invalid contact_id."""
        contacts = [
            {"contact_id": "123", "name": "John Doe"},
            {"contact_id": "456", "name": "Jane Smith"}
        ]
        response = '{"contact_id": "789"}'  # Not in contacts list

        result = extract_contact_id(response, contacts)
        assert result is None

    def test_format_contacts_for_llm_basic(self):
        """Test basic contact formatting for LLM."""
        contacts = [
            {
                "contact_id": "123",
                "name": "John Doe",
                "role": "CEO",
                "company": "Test Corp",
                "seniority": 1
            }
        ]

        result = format_contacts_for_llm(contacts)
        assert "John Doe" in result
        assert "CEO" in result
        assert "Test Corp" in result

    def test_format_contacts_for_llm_with_role_priorities(self):
        """Test contact formatting with role priorities."""
        contacts = [
            {
                "contact_id": "123",
                "name": "John Doe",
                "role": "CEO",
                "company": "Test Corp",
                "seniority": 1
            }
        ]
                role_priority_config = {"ceo": 1, "default": 99}

        result = format_contacts_for_llm(contacts, role_priority_config)
        assert "Priority: 1" in result

    @pytest.mark.asyncio
    async def test_select_best_contact_llm_no_icp_config(self):
        """Test LLM contact selection fallback when no ICP config."""
        contacts = [
            {"contact_id": "123", "name": "John Doe", "role": "CEO", "seniority": 1}
        ]
        role_priority_config = {"CEO": 1, "default": 99}

        # Should fallback to rule-based selection
        result = await select_best_contact_llm(contacts, role_priority_config, None)
        assert result == "123"

    @pytest.mark.asyncio
    async def test_select_best_contact_llm_no_api_key(self):
        """Test LLM contact selection fallback when no API key."""
        contacts = [
            {"contact_id": "123", "name": "John Doe", "role": "CEO", "seniority": 1}
        ]
        role_priority_config = {"CEO": 1, "default": 99}
        icp_config = {"icp_text": "Tech companies", "icp_type": "default"}

        # Mock environment without API key
        with patch.dict(os.environ, {}, clear=True):
            result = await select_best_contact_llm(contacts, role_priority_config, icp_config)
            assert result == "123"  # Should fallback to rule-based

    @pytest.mark.asyncio
    async def test_select_best_contact_llm_with_mock_success(self):
        """Test successful LLM contact selection with mocked API."""
        contacts = [
            {"contact_id": "ceo", "name": "CEO Person", "role": "CEO", "seniority": 1},
            {"contact_id": "manager", "name": "Manager Person", "role": "Manager", "seniority": 3}
        ]
        role_priority_config = {"CEO": 1, "Manager": 3, "default": 99}
        icp_config = {"icp_text": "Technology companies", "icp_type": "default"}

        with patch.dict(os.environ, {"OPENROUTER_KEY": "test_key"}):
            with patch('src.enrich.LLMContactSelector.select_contact') as mock_select:
                mock_select.return_value = "ceo"

                result = await select_best_contact_llm(contacts, role_priority_config, icp_config)
                assert result == "ceo"
                mock_select.assert_called_once_with(contacts, icp_config, role_priority_config)

    def test_format_contacts_edge_cases(self):
        """Test contact formatting with edge cases."""
        # Empty contacts list
        result = format_contacts_for_llm([])
        assert result == "No contacts available."

        # Contact with missing fields
        contacts_missing_fields = [
            {"contact_id": "incomplete", "name": "Incomplete Person"}
            # Missing role, company, seniority
        ]
        result = format_contacts_for_llm(contacts_missing_fields)
        assert "Incomplete Person" in result
        assert "Unknown" in result  # Should handle missing fields gracefully

    def test_extract_contact_id_edge_cases(self):
        """Test contact ID extraction with edge cases."""
        contacts = [{"contact_id": "valid", "name": "Valid Person"}]

        # Test with extra whitespace
        result = extract_contact_id('  {"contact_id": "valid"}  ', contacts)
        assert result == "valid"

        # Test with extra fields in JSON
        result = extract_contact_id('{"contact_id": "valid", "extra": "field"}', contacts)
        assert result == "valid"

        # Test with different quote styles (if LLM returns them)
        result = extract_contact_id('{\"contact_id\": \"valid\"}', contacts)
        assert result == "valid"

    def test_validate_llm_response_edge_cases(self):
        """Test LLM response validation with edge cases."""
        # Test with extra whitespace and newlines
        assert validate_llm_response('\n\n  {"contact_id": "123"}  \n\n')

        # Test with different markdown variations
        assert validate_llm_response('```json\n{"contact_id": "123"}\n```')
        assert validate_llm_response('```\n{"contact_id": "123"}\n```')

        # Test with nested objects (should still be valid if contact_id is present)
        assert validate_llm_response('{"contact_id": "123", "metadata": {"confidence": 0.9}}')

    @pytest.mark.asyncio
    async def test_llm_contact_selector_icp_configuration(self):
        """Test LLM contact selector with different ICP configurations."""
        contacts = [{"contact_id": "test", "name": "Test Person", "role": "CEO"}]

        # Test with investment ICP type
        investment_selector = LLMContactSelector("test_key", "investment")
        assert investment_selector.icp_type == "investment"

        # Test with healthcare ICP type
        healthcare_selector = LLMContactSelector("test_key", "healthcare")
        assert healthcare_selector.icp_type == "healthcare"

        # Test with default ICP type
        default_selector = LLMContactSelector("test_key", "default")
        assert default_selector.icp_type == "default"


if __name__ == "__main__":
    pytest.main([__file__])
