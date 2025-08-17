"""
Test configuration and fixtures for Lead Sorcerer tests.
"""

import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create subdirectories
        (Path(temp_dir) / "evidence" / "domain").mkdir(parents=True, exist_ok=True)
        (Path(temp_dir) / "evidence" / "enrich").mkdir(parents=True, exist_ok=True)
        (Path(temp_dir) / "crawl_artifacts").mkdir(parents=True, exist_ok=True)
        (Path(temp_dir) / "exports").mkdir(parents=True, exist_ok=True)

        yield temp_dir


@pytest.fixture
def sample_icp_config():
    """Sample ICP configuration for testing."""
    return {
        "name": "test_icp",
        "icp_text": "Technology companies in California",
        "queries": ["${industry} companies in ${region}"],
        "required_fields": {"company": ["name", "hq_location"], "contact": ["email"]},
        "optional_fields": {"company": ["tech_stack"], "contact": ["phone"]},
        "threshold": 0.7,
        "filtering_strict": True,
        "mode": "thorough",
        "refresh_policy": {
            "revisit_after_days": 90,
            "failure_revisit_days": 1,
            "domain_serp_ttl_hours": 24,
            "crawl_ttl_days": 14,
        },
        "concurrency": {"max_concurrent_requests": 3},
        "search": {"max_pages": 5},
        "testing": {"process_rejected": False, "process_low_crawl": False},
        "caps": {"company_usd": 0.02, "contact_usd": 0.03, "run_usd_max": 5.0},
        "role_priority": {"ceo": 1, "vp sales": 2, "director": 3, "default": 99},
        "exports": {"enabled": True},
        "default_country": "US",
    }


@pytest.fixture
def sample_lead_record():
    """Sample lead record for testing."""
    return {
        "lead_id": "test-lead-id",
        "domain": "example.com",
        "company": {
            "name": "Example Corp",
            "description": "A technology company",
            "industry": "Technology",
            "hq_location": "San Francisco, CA",
            "socials": {"linkedin": None, "github": None, "twitter": None},
            "evidence_urls": [],
        },
        "contacts": [
            {
                "contact_id": "test-contact-id",
                "full_name": "John Doe",
                "role": "CEO",
                "email": "john@example.com",
                "phone": "+1234567890",
                "linkedin": "/in/johndoe",
            }
        ],
        "icp": {"pre_score": 0.8, "pre_pass": True, "threshold": 0.7},
        "provenance": {
            "scored_at": "2024-01-01T00:00:00Z",
            "next_revisit_at": None,
            "tool_versions": {},
            "evidence_paths": {},
        },
        "status": "scored",
        "status_history": [],
        "audit": [],
        "cost": {
            "domain_usd": 0.0,
            "crawl_usd": 0.0,
            "enrich_usd": 0.0,
            "total_usd": 0.0,
        },
    }


@pytest.fixture
def mock_schema_file():
    """Mock schema file content for testing."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"test": {"type": "string"}},
    }
