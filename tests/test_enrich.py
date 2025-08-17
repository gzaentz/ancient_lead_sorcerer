"""
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
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

from src.enrich import (
    ProxycurlClient, MailgunClient, SnovioClient, select_best_contact,
    enrich_company_data, enrich_contact_data, write_evidence_file,
    run_enrich, main, INTERNAL_VERSION, TOOL_NAME
)
from src.common import ErrorCode


class TestProxycurlClient:
    """Test Proxycurl client functionality."""

    def test_init(self):
        """Test client initialization."""
        semaphore_pool = MagicMock()
        client = ProxycurlClient("test_key", semaphore_pool)

        assert client.api_key == "test_key"
        assert client.base_url == "https://nubela.co/proxycurl/api/v2"
        assert client.semaphore_pool == semaphore_pool

    @pytest.mark.asyncio
    async def test_enrich_company_success(self):
        """Test successful company enrichment."""
        semaphore_pool = AsyncMock()
        client = ProxycurlClient("test_key", semaphore_pool)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "name": "Test Company",
            "description": "Test description",
            "industry": "Technology"
        }
        mock_response.raise_for_status.return_value = None

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = await client.enrich_company("test.com")

            assert result["name"] == "Test Company"
            assert result["description"] == "Test description"
            assert result["industry"] == "Technology"
            semaphore_pool.__aenter__.assert_called_once()
            semaphore_pool.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_enrich_contact_success(self):
        """Test successful contact enrichment."""
        semaphore_pool = AsyncMock()
        client = ProxycurlClient("test_key", semaphore_pool)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "email": "test@example.com",
            "phone": "+1234567890"
        }
        mock_response.raise_for_status.return_value = None

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = await client.enrich_contact("https://linkedin.com/in/test")

            assert result["email"] == "test@example.com"
            assert result["phone"] == "+1234567890"
            semaphore_pool.__aenter__.assert_called_once()
            semaphore_pool.__aexit__.assert_called_once()


class TestMailgunClient:
    """Test Mailgun client functionality."""

    def test_init(self):
        """Test client initialization."""
        semaphore_pool = MagicMock()
        client = MailgunClient("test@domain.com", "password", semaphore_pool)

        assert client.smtp_login == "test@domain.com"
        assert client.smtp_password == "password"
        assert client.domain == "domain.com"
        assert client.base_url == "https://api.mailgun.net/v3"

    @pytest.mark.asyncio
    async def test_validate_email_success(self):
        """Test successful email validation."""
        semaphore_pool = AsyncMock()
        client = MailgunClient("test@domain.com", "password", semaphore_pool)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": "valid",
            "score": 0.95
        }
        mock_response.raise_for_status.return_value = None

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = await client.validate_email("test@example.com")

            assert result["result"] == "valid"
            assert result["score"] == 0.95
            semaphore_pool.__aenter__.assert_called_once()
            semaphore_pool.__aexit__.assert_called_once()


class TestSnovioClient:
    """Test Snov.io client functionality."""

    def test_init(self):
        """Test client initialization."""
        semaphore_pool = MagicMock()
        client = SnovioClient("client_id", "client_secret", semaphore_pool)

        assert client.client_id == "client_id"
        assert client.client_secret == "client_secret"
        assert client.base_url == "https://api.snov.io/v1"
        assert client._access_token is None

    @pytest.mark.asyncio
    async def test_get_access_token_success(self):
        """Test successful access token retrieval."""
        semaphore_pool = AsyncMock()
        client = SnovioClient("client_id", "client_secret", semaphore_pool)

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "test_token"}
        mock_response.raise_for_status.return_value = None

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response

            token = await client._get_access_token()

            assert token == "test_token"
            assert client._access_token == "test_token"
            semaphore_pool.__aenter__.assert_called_once()
            semaphore_pool.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_email_success(self):
        """Test successful email discovery."""
        semaphore_pool = AsyncMock()
        client = SnovioClient("client_id", "client_secret", semaphore_pool)

        # Mock access token
        client._access_token = "test_token"

        mock_response = MagicMock()
        mock_response.json.return_value = {"email": "john.doe@example.com"}
        mock_response.raise_for_status.return_value = None

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = await client.find_email("example.com", "John", "Doe")

            assert result["email"] == "john.doe@example.com"
            semaphore_pool.__aenter__.assert_called_once()
            semaphore_pool.__aexit__.assert_called_once()


class TestBestContactSelection:
    """Test best contact selection logic."""

    def test_select_best_contact_empty_list(self):
        """Test selection with empty contacts list."""
        role_priority_config = {"ceo": 1, "default": 99}
        result = select_best_contact([], role_priority_config)
        assert result is None

    def test_select_best_contact_single_contact(self):
        """Test selection with single contact."""
        contacts = [{
            "contact_id": "contact1",
            "role": "CEO",
            "seniority": 1,
            "email_status": "valid",
            "linkedin": "https://linkedin.com/in/ceo"
        }]
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
                "linkedin": ""
            },
            {
                "contact_id": "contact2",
                "role": "CEO",
                "seniority": 1,
                "email_status": "valid",
                "linkedin": "https://linkedin.com/in/ceo"
            },
            {
                "contact_id": "contact3",
                "role": "VP Sales",
                "seniority": 2,
                "email_status": "valid",
                "linkedin": "https://linkedin.com/in/vp"
            }
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
                "full_name": "John Doe"
            },
            {
                "contact_id": "contact2",
                "role": "Manager",
                "seniority": 4,
                "email_status": "valid",
                "linkedin": "",
                "full_name": "Jane Smith"
            }
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
        proxycurl_client = MagicMock()
        costs_config = {"proxycurl": 0.01}

        # Mock successful enrichment
        proxycurl_client.enrich_company.return_value = {
            "name": "Test Company",
            "description": "Test description",
            "industry": "Technology",
            "hq_location": "San Francisco",
            "size_hint": "50-100 employees",
            "linkedin_company_id": "12345",
            "crunchbase_id": "67890"
        }

        enriched_company, cost = await enrich_company_data(
            company, domain, proxycurl_client, costs_config
        )

        assert enriched_company["name"] == "Test Company"
        assert enriched_company["description"] == "Test description"
        assert enriched_company["industry"] == "Technology"
        assert enriched_company["hq_location"] == "San Francisco"
        assert enriched_company["size_hint"] == "50-100 employees"
        assert enriched_company["ids"]["linkedin"] == "/company/12345"
        assert enriched_company["ids"]["crunchbase"] == "67890"
        assert cost == 0.01

    @pytest.mark.asyncio
    async def test_enrich_company_data_failure(self):
        """Test company enrichment failure handling."""
        company = {"name": "Existing Name"}
        domain = "test.com"
        proxycurl_client = MagicMock()
        costs_config = {"proxycurl": 0.01}

        # Mock failure
        proxycurl_client.enrich_company.side_effect = Exception("API Error")

        enriched_company, cost = await enrich_company_data(
            company, domain, proxycurl_client, costs_config
        )

        # Should return original company unchanged
        assert enriched_company["name"] == "Existing Name"
        assert cost == 0.0


class TestContactEnrichment:
    """Test contact data enrichment functionality."""

    @pytest.mark.asyncio
    async def test_enrich_contact_data_proxycurl_success(self):
        """Test successful contact enrichment via Proxycurl."""
        contact = {"linkedin": "https://linkedin.com/in/test"}
        domain = "test.com"
        proxycurl_client = MagicMock()
        mailgun_client = MagicMock()
        snovio_client = MagicMock()
        costs_config = {"proxycurl": 0.01, "mailgun": 0.002}

        # Mock Proxycurl success
        proxycurl_client.enrich_contact.return_value = {
            "email": "test@example.com",
            "phone": "+1234567890",
            "role": "Software Engineer"
        }

        # Mock Mailgun validation
        mailgun_client.validate_email.return_value = {
            "result": "valid",
            "score": 0.95
        }

        enriched_contact, cost = await enrich_contact_data(
            contact, domain, proxycurl_client, mailgun_client, snovio_client, costs_config
        )

        assert enriched_contact["email"] == "test@example.com"
        assert enriched_contact["phone"] == "+1234567890"
        assert enriched_contact["role"] == "Software Engineer"
        assert enriched_contact["email_status"] == "valid"
        assert enriched_contact["email_confidence"] == 0.95
        assert enriched_contact["email_source"] == "provider"
        assert cost == 0.012  # proxycurl + mailgun

    @pytest.mark.asyncio
    async def test_enrich_contact_data_snovio_success(self):
        """Test successful email discovery via Snov.io."""
        contact = {"full_name": "John Doe"}
        domain = "test.com"
        proxycurl_client = MagicMock()
        mailgun_client = MagicMock()
        snovio_client = MagicMock()
        costs_config = {"snovio": 0.015, "mailgun": 0.002}

        # Mock Snov.io success
        snovio_client.find_email.return_value = {"email": "john.doe@test.com"}

        # Mock Mailgun validation
        mailgun_client.validate_email.return_value = {
            "result": "valid",
            "score": 0.90
        }

        enriched_contact, cost = await enrich_contact_data(
            contact, domain, proxycurl_client, mailgun_client, snovio_client, costs_config
        )

        assert enriched_contact["email"] == "john.doe@test.com"
        assert enriched_contact["email_status"] == "valid"
        assert enriched_contact["email_source"] == "provider"
        assert cost == 0.017  # snovio + mailgun

    @pytest.mark.asyncio
    async def test_enrich_contact_data_phone_normalization(self):
        """Test phone number normalization."""
        contact = {
            "phone": "+1 (555) 123-4567",
            "company_country": "US",
            "default_country": "US"
        }
        domain = "test.com"
        proxycurl_client = MagicMock()
        mailgun_client = MagicMock()
        snovio_client = MagicMock()
        costs_config = {"proxycurl": 0.01}

        enriched_contact, cost = await enrich_contact_data(
            contact, domain, proxycurl_client, mailgun_client, snovio_client, costs_config
        )

        # Phone should be normalized to E.164
        assert enriched_contact["phone"] == "+15551234567"
        assert cost == 0.0


class TestEvidenceFileWriting:
    """Test evidence file writing functionality."""

    def test_write_evidence_file_success(self):
        """Test successful evidence file writing."""
        domain = "test.com"
        evidence_data = {"test": "data"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch('src.enrich.normalize_domain', return_value="test.com"):
                with patch('src.enrich.os.path.join') as mock_join:
                    mock_join.side_effect = lambda *args: os.path.join(temp_dir, *args)

                    with patch('src.enrich.portalocker.Lock') as mock_lock:
                        mock_lock.return_value.__enter__ = MagicMock()
                        mock_lock.return_value.__exit__ = MagicMock()

                        result_path = write_evidence_file(domain, evidence_data, temp_dir)

                        # Check that file was created
                        expected_path = os.path.join(temp_dir, "evidence", "enrich", "test.com.json")
                        assert result_path == expected_path
                        assert os.path.exists(expected_path)

                        # Check file contents
                        with open(expected_path, 'r') as f:
                            content = json.load(f)
                            assert content == evidence_data


class TestMainEnrichmentLogic:
    """Test main enrichment logic."""

    @pytest.mark.asyncio
    async def test_run_enrich_success(self):
        """Test successful enrichment run."""
        payload = {
            "lead_records": [{
                "lead_id": "lead1",
                "domain": "test.com",
                "status": "enrich_ready",
                "company": {"name": None},
                "contacts": [{
                    "contact_id": "contact1",
                    "role": "CEO",
                    "seniority": 1,
                    "email_status": "unknown"
                }],
                "cost": {"domain_usd": 0.0, "crawl_usd": 0.0, "enrich_usd": 0.0, "total_usd": 0.0},
                "status_history": [],
                "audit": []
            }],
            "icp_config": {
                "concurrency": {"max_concurrent_requests": 3},
                "role_priority": {"ceo": 1, "default": 99},
                "default_country": "US",
                "required_fields": {"company": ["name"], "contact": ["email"]},
                "testing": {"process_rejected": False, "process_low_crawl": False}
            },
            "caps": {
                "company_usd": 0.02,
                "contact_usd": 0.03,
                "run_usd_max": 5.0
            }
        }

        # Mock environment variables
        with patch.dict(os.environ, {
            'PROXYCURL_KEY': 'test_key',
            'MAILGUN_SMTP_LOGIN': 'test@domain.com',
            'MAILGUN_SMTP_PW': 'password',
            'SNOV_IO_ID': 'client_id',
            'SNOV_IO_SECRET': 'client_secret'
        }):
            # Mock costs config
            with patch('src.enrich.load_costs_config') as mock_load_costs:
                mock_load_costs.return_value = {
                    'proxycurl': 0.01,
                    'mailgun': 0.002,
                    'snovio': 0.015
                }

                # Mock schema checksum
                with patch('src.enrich.load_schema_checksum') as mock_schema:
                    mock_schema.return_value = "test_checksum"

                    # Mock data directory resolution
                    with patch('src.enrich.resolve_data_dir', return_value="./data"):
                        # Mock provider clients
                        with patch('src.enrich.ProxycurlClient') as mock_proxycurl_class:
                            with patch('src.enrich.MailgunClient') as mock_mailgun_class:
                                with patch('src.enrich.SnovioClient') as mock_snovio_class:
                                    mock_proxycurl = MagicMock()
                                    mock_mailgun = MagicMock()
                                    mock_snovio = MagicMock()

                                    mock_proxycurl_class.return_value = mock_proxycurl
                                    mock_mailgun_class.return_value = mock_mailgun
                                    mock_snovio_class.return_value = mock_snovio

                                    # Mock company enrichment
                                    mock_proxycurl.enrich_company.return_value = {
                                        "name": "Test Company"
                                    }

                                    # Mock evidence file writing
                                    with patch('src.enrich.write_evidence_file', return_value="test_path"):
                                        result = await run_enrich(payload)

                                        assert "data" in result
                                        assert "errors" in result
                                        assert "metrics" in result
                                        assert len(result["data"]["lead_records"]) == 1
                                        assert result["data"]["lead_records"][0]["status"] == "enrich_partial"

    @pytest.mark.asyncio
    async def test_run_enrich_budget_exceeded(self):
        """Test enrichment with budget exceeded."""
        payload = {
            "lead_records": [{
                "lead_id": "lead1",
                "domain": "test.com",
                "status": "enrich_ready",
                "company": {},
                "contacts": [],
                "cost": {"domain_usd": 0.0, "crawl_usd": 0.0, "enrich_usd": 0.0, "total_usd": 0.0},
                "status_history": [],
                "audit": []
            }],
            "icp_config": {
                "concurrency": {"max_concurrent_requests": 3},
                "role_priority": {"default": 99},
                "default_country": "US",
                "required_fields": {"company": [], "contact": []},
                "testing": {"process_rejected": False, "process_low_crawl": False}
            },
            "caps": {
                "company_usd": 0.02,
                "contact_usd": 0.03,
                "run_usd_max": 0.0  # Budget already exceeded
            }
        }

        # Mock environment variables
        with patch.dict(os.environ, {
            'PROXYCURL_KEY': 'test_key',
            'MAILGUN_SMTP_LOGIN': 'test@domain.com',
            'MAILGUN_SMTP_PW': 'password',
            'SNOV_IO_ID': 'client_id',
            'SNOV_IO_SECRET': 'client_secret'
        }):
            # Mock costs config
            with patch('src.enrich.load_costs_config') as mock_load_costs:
                mock_load_costs.return_value = {
                    'proxycurl': 0.01,
                    'mailgun': 0.002,
                    'snovio': 0.015
                }

                # Mock schema checksum
                with patch('src.enrich.load_schema_checksum') as mock_schema:
                    mock_schema.return_value = "test_checksum"

                    # Mock data directory resolution
                    with patch('src.enrich.resolve_data_dir', return_value="./data"):
                        # Mock provider clients
                        with patch('src.enrich.ProxycurlClient') as mock_proxycurl_class:
                            with patch('src.enrich.MailgunClient') as mock_mailgun_class:
                                with patch('src.enrich.SnovioClient') as mock_snovio_class:
                                    mock_proxycurl = MagicMock()
                                    mock_mailgun = MagicMock()
                                    mock_snovio = MagicMock()

                                    mock_proxycurl_class.return_value = mock_proxycurl
                                    mock_mailgun_class.return_value = mock_mailgun
                                    mock_snovio_class.return_value = mock_snovio

                                    result = await run_enrich(payload)

                                    # Should have BUDGET_EXCEEDED error
                                    assert len(result["errors"]) == 1
                                    assert result["errors"][0]["code"] == ErrorCode.BUDGET_EXCEEDED.value

    @pytest.mark.asyncio
    async def test_run_enrich_missing_environment_variables(self):
        """Test enrichment with missing environment variables."""
        payload = {
            "lead_records": [{
                "lead_id": "lead1",
                "domain": "test.com",
                "status": "enrich_ready",
                "company": {},
                "contacts": [],
                "cost": {"domain_usd": 0.0, "crawl_usd": 0.0, "enrich_usd": 0.0, "total_usd": 0.0},
                "status_history": [],
                "audit": []
            }],
            "icp_config": {
                "concurrency": {"max_concurrent_requests": 3},
                "role_priority": {"default": 99},
                "default_country": "US",
                "required_fields": {"company": [], "contact": []},
                "testing": {"process_rejected": False, "process_low_crawl": False}
            },
            "caps": {
                "company_usd": 0.02,
                "contact_usd": 0.03,
                "run_usd_max": 5.0
            }
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
        input_data = json.dumps({
            "lead_records": [],
            "icp_config": {},
            "caps": {}
        })

        with patch('builtins.input', return_value=input_data):
            with patch('src.enrich.asyncio.run') as mock_run:
                mock_run.return_value = {
                    "data": {"lead_records": []},
                    "errors": [],
                    "metrics": {}
                }

                with patch('builtins.print') as mock_print:
                    main()

                    mock_run.assert_called_once()
                    mock_print.assert_called_once()

    def test_main_json_error(self):
        """Test CLI with JSON parsing error."""
        input_data = "invalid json"

        with patch('builtins.input', return_value=input_data):
            with patch('builtins.print') as mock_print:
                with patch('builtins.exit') as mock_exit:
                    main()

                    mock_print.assert_called_once()
                    mock_exit.assert_called_once_with(1)

    def test_main_general_error(self):
        """Test CLI with general error."""
        input_data = json.dumps({
            "lead_records": [],
            "icp_config": {},
            "caps": {}
        })

        with patch('builtins.input', return_value=input_data):
            with patch('src.enrich.asyncio.run', side_effect=Exception("Test error")):
                with patch('builtins.print') as mock_print:
                    with patch('builtins.exit') as mock_exit:
                        main()

                        mock_print.assert_called_once()
                        mock_exit.assert_called_once_with(1)


class TestErrorHandling:
    """Test error handling and resilience."""

    @pytest.mark.asyncio
    async def test_provider_failover(self):
        """Test provider failover when primary enrichment fails."""
        contact = {"linkedin": "https://linkedin.com/in/test"}
        domain = "test.com"
        proxycurl_client = MagicMock()
        mailgun_client = MagicMock()
        snovio_client = MagicMock()
        costs_config = {"proxycurl": 0.01, "snovio": 0.015, "mailgun": 0.002}

        # Mock Proxycurl failure
        proxycurl_client.enrich_contact.side_effect = Exception("Proxycurl API Error")

        # Mock Snov.io success
        snovio_client.find_email.return_value = {"email": "test@example.com"}

        # Mock Mailgun validation
        mailgun_client.validate_email.return_value = {
            "result": "valid",
            "score": 0.90
        }

        enriched_contact, cost = await enrich_contact_data(
            contact, domain, proxycurl_client, mailgun_client, snovio_client, costs_config
        )

        # Should still get email via Snov.io
        assert enriched_contact["email"] == "test@example.com"
        assert cost == 0.017  # snovio + mailgun

    @pytest.mark.asyncio
    async def test_individual_record_error_handling(self):
        """Test handling of individual record errors."""
        payload = {
            "lead_records": [{
                "lead_id": "lead1",
                "domain": "test.com",
                "status": "enrich_ready",
                "company": {},
                "contacts": [],
                "cost": {"domain_usd": 0.0, "crawl_usd": 0.0, "enrich_usd": 0.0, "total_usd": 0.0},
                "status_history": [],
                "audit": []
            }],
            "icp_config": {
                "concurrency": {"max_concurrent_requests": 3},
                "role_priority": {"default": 99},
                "default_country": "US",
                "required_fields": {"company": [], "contact": []},
                "testing": {"process_rejected": False, "process_low_crawl": False}
            },
            "caps": {
                "company_usd": 0.02,
                "contact_usd": 0.03,
                "run_usd_max": 5.0
            }
        }

        # Mock environment variables
        with patch.dict(os.environ, {
            'PROXYCURL_KEY': 'test_key',
            'MAILGUN_SMTP_LOGIN': 'test@domain.com',
            'MAILGUN_SMTP_PW': 'password',
            'SNOV_IO_ID': 'client_id',
            'SNOV_IO_SECRET': 'client_secret'
        }):
            # Mock costs config
            with patch('src.enrich.load_costs_config') as mock_load_costs:
                mock_load_costs.return_value = {
                    'proxycurl': 0.01,
                    'mailgun': 0.002,
                    'snovio': 0.015
                }

                # Mock schema checksum
                with patch('src.enrich.load_schema_checksum') as mock_schema:
                    mock_schema.return_value = "test_checksum"

                    # Mock data directory resolution
                    with patch('src.enrich.resolve_data_dir', return_value="./data"):
                        # Mock provider clients
                        with patch('src.enrich.ProxycurlClient') as mock_proxycurl_class:
                            with patch('src.enrich.MailgunClient') as mock_mailgun_class:
                                with patch('src.enrich.SnovioClient') as mock_snovio_class:
                                    mock_proxycurl = MagicMock()
                                    mock_mailgun = MagicMock()
                                    mock_snovio = MagicMock()

                                    mock_proxycurl_class.return_value = mock_proxycurl
                                    mock_mailgun_class.return_value = mock_mailgun
                                    mock_snovio_class.return_value = mock_snovio

                                    # Mock company enrichment to raise error
                                    mock_proxycurl.enrich_company.side_effect = Exception("Test error")

                                    # Mock evidence file writing
                                    with patch('src.enrich.write_evidence_file', return_value="test_path"):
                                        result = await run_enrich(payload)

                                        # Should have error but still return partial results
                                        assert len(result["errors"]) == 1
                                        assert result["errors"][0]["code"] == ErrorCode.UNKNOWN.value
                                        assert len(result["data"]["lead_records"]) == 1
                                        assert result["data"]["lead_records"][0]["status"] == "enrich_partial"


if __name__ == "__main__":
    pytest.main([__file__])
