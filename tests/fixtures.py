"""
Test fixtures and mocks for Lead Sorcerer.

Provides responses/httpx_mock stubs for external APIs including GSE, Firecrawl,
Proxycurl, Mailgun, and Snov.io as required by Task 6.3.
"""

import json
import pytest
from unittest.mock import Mock, AsyncMock
from unittest.mock import patch


# ============================================================================
# Google Search Engine (GSE) Mocks
# ============================================================================

@pytest.fixture
def mock_gse_response():
    """Mock GSE API response."""
    return {
        "items": [
            {
                "title": "Test Company 1 - B2B SaaS Solutions",
                "link": "https://testcompany1.com",
                "snippet": "Leading B2B SaaS company providing enterprise software solutions",
                "rank": 1
            },
            {
                "title": "Test Company 2 - Enterprise Software",
                "link": "https://testcompany2.com",
                "snippet": "Enterprise software company specializing in B2B solutions",
                "rank": 2
            }
        ]
    }


@pytest.fixture
def mock_gse_client():
    """Mock GSE client."""
    client = AsyncMock()
    client.search.return_value = mock_gse_response()
    return client


# ============================================================================
# Firecrawl Mocks
# ============================================================================

@pytest.fixture
def mock_firecrawl_response():
    """Mock Firecrawl API response."""
    return {
        "company": {
            "name": "Test Company",
            "description": "A technology company",
            "industry": "Technology",
            "hq_location": "San Francisco, CA",
            "socials": {
                "linkedin": "https://linkedin.com/company/test-company"
            },
            "careers_url": "https://testcompany.com/careers",
            "blog_url": "https://testcompany.com/blog"
        },
        "employees": [
            {
                "full_name": "John Doe",
                "role": "CEO",
                "linkedin": "https://linkedin.com/in/johndoe",
                "email": "john@testcompany.com"
            },
            {
                "full_name": "Jane Smith",
                "role": "CTO",
                "linkedin": "https://linkedin.com/in/janesmith",
                "email": "jane@testcompany.com"
            }
        ]
    }


@pytest.fixture
def mock_firecrawl_client():
    """Mock Firecrawl client."""
    client = AsyncMock()
    client.extract.return_value = mock_firecrawl_response()
    return client


# ============================================================================
# Proxycurl Mocks
# ============================================================================

@pytest.fixture
def mock_proxycurl_company_response():
    """Mock Proxycurl company enrichment response."""
    return {
        "name": "Test Company",
        "description": "A technology company",
        "industry": "Technology",
        "hq_location": "San Francisco, CA",
        "size": "50-200",
        "linkedin_id": "test-company-123",
        "crunchbase_id": "test-company"
    }


@pytest.fixture
def mock_proxycurl_contact_response():
    """Mock Proxycurl contact enrichment response."""
    return {
        "full_name": "John Doe",
        "role": "CEO",
        "department": "Executive",
        "seniority": "C-Level",
        "email": "john@testcompany.com",
        "phone": "+1234567890",
        "linkedin": "https://linkedin.com/in/johndoe"
    }


@pytest.fixture
def mock_proxycurl_client():
    """Mock Proxycurl client."""
    client = AsyncMock()
    client.enrich_company.return_value = mock_proxycurl_company_response()
    client.enrich_contact.return_value = mock_proxycurl_contact_response()
    return client


# ============================================================================
# Mailgun Mocks
# ============================================================================

@pytest.fixture
def mock_mailgun_validation_response():
    """Mock Mailgun email validation response."""
    return {
        "result": "valid",
        "score": 0.90,
        "reason": "Valid email address"
    }


@pytest.fixture
def mock_mailgun_client():
    """Mock Mailgun client."""
    client = AsyncMock()
    client.validate_email.return_value = mock_mailgun_validation_response()
    return client


# ============================================================================
# Snov.io Mocks
# ============================================================================

@pytest.fixture
def mock_snovio_email_response():
    """Mock Snov.io email finder response."""
    return {
        "email": "john@testcompany.com",
        "confidence": 0.85,
        "source": "website"
    }


@pytest.fixture
def mock_snovio_client():
    """Mock Snovio client."""
    client = AsyncMock()
    client.find_email.return_value = mock_snovio_email_response()
    return client


# ============================================================================
# OpenRouter Mocks
# ============================================================================

@pytest.fixture
def mock_openrouter_response():
    """Mock OpenRouter LLM response."""
    return {
        "choices": [
            {
                "message": {
                    "content": '{"score": 0.85, "reason": "Good match for B2B SaaS", "flags": []}'
                }
            }
        ],
        "usage": {
            "total_tokens": 150,
            "prompt_tokens": 100,
            "completion_tokens": 50
        }
    }


@pytest.fixture
def mock_openrouter_client():
    """Mock OpenRouter client."""
    client = AsyncMock()
    client.chat.completions.create.return_value = mock_openrouter_response()
    return client


# ============================================================================
# HTTP Response Mocks
# ============================================================================

@pytest.fixture
def mock_http_response():
    """Mock HTTP response."""
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"success": True}
    response.text = '{"success": true}'
    return response


@pytest.fixture
def mock_http_error_response():
    """Mock HTTP error response."""
    response = Mock()
    response.status_code = 429
    response.json.return_value = {"error": "Rate limited"}
    response.text = '{"error": "Rate limited"}'
    return response


# ============================================================================
# Error Response Mocks
# ============================================================================

@pytest.fixture
def mock_provider_error_response():
    """Mock provider error response."""
    return {
        "error": "Service unavailable",
        "status": 503,
        "retry_after": 60
    }


@pytest.fixture
def mock_parse_error_response():
    """Mock parse error response."""
    return {
        "error": "Invalid data format",
        "details": "Phone number format not recognized"
    }


# ============================================================================
# Test Data Fixtures
# ============================================================================

@pytest.fixture
def sample_lead_record():
    """Sample lead record for testing."""
    return {
        "lead_id": "test-lead-id-123",
        "domain": "testcompany.com",
        "company": {
            "name": "Test Company",
            "description": "A technology company",
            "industry": "Technology",
            "hq_location": "San Francisco, CA",
            "socials": {
                "linkedin": "https://linkedin.com/company/test-company"
            },
            "evidence_urls": []
        },
        "contacts": [
            {
                "contact_id": "test-contact-id-123",
                "full_name": "John Doe",
                "role": "CEO",
                "email": "john@testcompany.com",
                "phone": "+1234567890",
                "linkedin": "https://linkedin.com/in/johndoe"
            }
        ],
        "icp": {
            "pre_score": 0.85,
            "pre_pass": True,
            "threshold": 0.7
        },
        "provenance": {
            "scored_at": "2024-01-01T00:00:00Z",
            "next_revisit_at": None,
            "tool_versions": {},
            "evidence_paths": {}
        },
        "status": "scored",
        "status_history": [],
        "audit": [],
        "cost": {
            "domain_usd": 0.0,
            "crawl_usd": 0.0,
            "enrich_usd": 0.0,
            "total_usd": 0.0
        }
    }


@pytest.fixture
def sample_icp_config():
    """Sample ICP configuration for testing."""
    return {
        "name": "Test ICP",
        "icp_text": "B2B SaaS companies in the US with 50-500 employees",
        "queries": [
            "B2B SaaS companies in California",
            "enterprise software companies in New York"
        ],
        "required_fields": {
            "company": ["name", "hq_location"],
            "contact": ["email"]
        },
        "optional_fields": {
            "company": ["tech_stack"],
            "contact": ["phone"]
        },
        "threshold": 0.7,
        "filtering_strict": True,
        "mode": "thorough",
        "refresh_policy": {
            "revisit_after_days": 90,
            "failure_revisit_days": 1,
            "domain_serp_ttl_hours": 24,
            "crawl_ttl_days": 14
        },
        "concurrency": {
            "max_concurrent_requests": 3
        },
        "search": {
            "max_pages": 5
        },
        "testing": {
            "process_rejected": False,
            "process_low_crawl": False
        },
        "caps": {
            "company_usd": 0.02,
            "contact_usd": 0.03,
            "run_usd_max": 5.0
        },
        "role_priority": {
            "ceo": 1,
            "vp sales": 2,
            "director": 3,
            "default": 99
        },
        "exports": {
            "enabled": True
        },
        "default_country": "US"
    }


# ============================================================================
# Mock Environment Variables
# ============================================================================

@pytest.fixture
def mock_env_vars():
    """Mock environment variables."""
    return {
        "GSE_API_KEY": "test_gse_key",
        "GSE_CX": "test_gse_cx",
        "FIRECRAWL_KEY": "test_firecrawl_key",
        "PROXYCURL_KEY": "test_proxycurl_key",
        "MAILGUN_SMTP_LOGIN": "test@domain.com",
        "MAILGUN_SMTP_PW": "test_password",
        "SNOV_IO_ID": "test_snovio_id",
        "SNOV_IO_SECRET": "test_snovio_secret",
        "OPENROUTER_KEY": "test_openrouter_key"
    }


# ============================================================================
# Mock Configuration Files
# ============================================================================

@pytest.fixture
def mock_costs_config():
    """Mock costs configuration."""
    return {
        "proxycurl": {
            "unit": "lookup",
            "usd_per_unit": 0.0100
        },
        "mailgun": {
            "unit": "smtp_validation",
            "usd_per_unit": 0.0020
        },
        "snovio": {
            "unit": "email_enrich",
            "usd_per_unit": 0.0150
        },
        "openrouter": {
            "unit": "1k_tokens",
            "usd_per_unit": 0.0020
        },
        "gse": {
            "unit": "request",
            "usd_per_unit": 0.0005
        },
        "firecrawl": {
            "unit": "extract",
            "usd_per_unit": 0.0010
        }
    }


@pytest.fixture
def mock_schema_checksum():
    """Mock schema checksum."""
    return "abc123def456ghi789"


# ============================================================================
# HTTPX Mock Patches
# ============================================================================

@pytest.fixture
def mock_httpx_client():
    """Mock httpx client for HTTP requests."""
    with patch('httpx.AsyncClient') as mock_client:
        client = mock_client.return_value
        client.post = AsyncMock()
        client.get = AsyncMock()
        client.close = AsyncMock()
        yield client


@pytest.fixture
def mock_httpx_response():
    """Mock httpx response."""
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"success": True}
    response.text = '{"success": true}'
    response.raise_for_status = Mock()
    return response


@pytest.fixture
def mock_httpx_error_response():
    """Mock httpx error response."""
    response = Mock()
    response.status_code = 429
    response.json.return_value = {"error": "Rate limited"}
    response.text = '{"error": "Rate limited"}'
    response.raise_for_status.side_effect = Exception("Rate limited")
    return response


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def temp_data_dir(tmp_path):
    """Create temporary data directory for testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Create subdirectories
    (data_dir / "evidence" / "domain").mkdir(parents=True, exist_ok=True)
    (data_dir / "evidence" / "enrich").mkdir(parents=True, exist_ok=True)
    (data_dir / "crawl_artifacts").mkdir(parents=True, exist_ok=True)
    (data_dir / "exports").mkdir(parents=True, exist_ok=True)

    return str(data_dir)


@pytest.fixture
def mock_file_lock():
    """Mock file lock for testing."""
    with patch('portalocker.Lock') as mock_lock:
        lock = mock_lock.return_value
        lock.__enter__ = Mock(return_value=lock)
        lock.__exit__ = Mock(return_value=None)
        yield lock


@pytest.fixture
def mock_time():
    """Mock time functions for testing."""
    with patch('time.time') as mock_time_func:
        mock_time_func.return_value = 1000.0
        yield mock_time_func


@pytest.fixture
def mock_datetime():
    """Mock datetime functions for testing."""
    with patch('datetime.datetime') as mock_datetime_class:
        mock_datetime_class.utcnow.return_value = Mock(
            isoformat=lambda: "2024-01-01T00:00:00Z"
        )
        yield mock_datetime_class


# ============================================================================
# Error Injection Fixtures
# ============================================================================

@pytest.fixture
def mock_network_error():
    """Mock network error for testing."""
    return Exception("Network connection failed")


@pytest.fixture
def mock_timeout_error():
    """Mock timeout error for testing."""
    return Exception("Request timed out")


@pytest.fixture
def mock_rate_limit_error():
    """Mock rate limit error for testing."""
    return Exception("Rate limit exceeded")


@pytest.fixture
def mock_validation_error():
    """Mock validation error for testing."""
    return ValueError("Invalid data format")


# ============================================================================
# Test Scenario Fixtures
# ============================================================================

@pytest.fixture
def mock_success_scenario():
    """Mock successful API call scenario."""
    return {
        "status": "success",
        "data": {"result": "success"},
        "cost": 0.001
    }


@pytest.fixture
def mock_failure_scenario():
    """Mock failed API call scenario."""
    return {
        "status": "error",
        "error": "API call failed",
        "retryable": True
    }


@pytest.fixture
def mock_partial_success_scenario():
    """Mock partially successful API call scenario."""
    return {
        "status": "partial",
        "data": {"result": "partial"},
        "errors": ["Some items failed"],
        "cost": 0.0005
    }
