"""
Pytest configuration and common fixtures for Lead Sorcerer tests.
"""

import pytest
import tempfile
import os
from pathlib import Path


@pytest.fixture
def temp_data_dir():
    """Create a temporary data directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create subdirectories
        os.makedirs(os.path.join(temp_dir, "evidence"), exist_ok=True)
        os.makedirs(os.path.join(temp_dir, "crawl_artifacts"), exist_ok=True)
        os.makedirs(os.path.join(temp_dir, "exports"), exist_ok=True)
        yield temp_dir


@pytest.fixture
def sample_icp_config():
    """Sample ICP configuration for testing."""
    return {
        "name": "Test ICP",
        "icp_text": "Test companies for testing purposes",
        "queries": ["test companies in ${region}"],
        "required_fields": {
            "company": ["name"],
            "contact": ["email"]
        },
        "optional_fields": {
            "company": ["description"],
            "contact": ["phone"]
        },
        "threshold": 0.7,
        "filtering_strict": True,
        "mode": "fast",
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


@pytest.fixture
def sample_lead_record():
    """Sample lead record for testing."""
    return {
        "lead_id": "test-lead-id",
        "domain": "example.com",
        "company": {
            "name": None,
            "description": None,
            "industry": None,
            "naics_keywords": [],
            "hq_location": None,
            "locations": [],
            "size_hint": None,
            "socials": {
                "linkedin": None,
                "github": None,
                "twitter": None,
                "telegram": None,
                "instagram": None
            },
            "careers_url": None,
            "blog_url": None,
            "tech_stack": [],
            "evidence_urls": [],
            "ids": {"linkedin": None, "crunchbase": None}
        },
        "contacts": [],
        "icp": {
            "pre_score": None,
            "pre_reason": None,
            "pre_pass": None,
            "pre_flags": [],
            "scoring_meta": {
                "method": None,
                "model": None,
                "prompt_fingerprint": None,
                "temperature": None
            },
            "crawl_score": None,
            "crawl_reason": None,
            "threshold": 0.7,
            "filtering_strict": True
        },
        "provenance": {
            "queries": [],
            "discovery_evidence": [],
            "scored_at": None,
            "crawled_at": None,
            "enriched_at": None,
            "next_revisit_at": None,
            "tool_versions": {
                "domain": {"version": None, "schema_version": None},
                "crawl": {"version": None, "schema_version": None},
                "enrich": {"version": None, "schema_version": None}
            },
            "cache": {"domain_cache_hit": None},
            "evidence_paths": {"domain": None, "crawl": None, "enrich": None}
        },
        "best_contact_id": None,
        "status": "new",
        "status_history": [],
        "audit": [],
        "cost": {"domain_usd": 0.0, "crawl_usd": 0.0, "enrich_usd": 0.0, "total_usd": 0.0}
    }
