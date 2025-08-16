"""Test the unified lead record JSON schema."""

import json
import os
import hashlib
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError


def test_schema_file_exists():
    """Test that the schema file exists."""
    schema_path = Path("schemas/unified_lead_record.json")
    assert schema_path.exists(), "Schema file should exist"


def test_schema_is_valid_json():
    """Test that the schema file contains valid JSON."""
    schema_path = Path("schemas/unified_lead_record.json")
    with open(schema_path, "r") as f:
        schema_data = json.load(f)

    # Basic structure checks
    assert "$schema" in schema_data, "Schema should have $schema field"
    assert schema_data["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "properties" in schema_data, "Schema should have properties"
    assert "required" in schema_data, "Schema should have required fields"


def test_schema_validation():
    """Test that the schema can be used for validation."""
    schema_path = Path("schemas/unified_lead_record.json")
    with open(schema_path, "r") as f:
        schema_data = json.load(f)

    # Create validator
    validator = Draft202012Validator(schema_data)

    # Test with minimal valid record
    minimal_record = {
        "lead_id": "550e8400-e29b-41d4-a716-446655440000",
        "domain": "example.com",
        "company": {},
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
            "cache": {},
            "evidence_paths": {
                "domain": None,
                "crawl": None,
                "enrich": None
            }
        },
        "status": "new",
        "status_history": [
            {
                "status": "new",
                "ts": "2024-01-01T00:00:00Z",
                "notes": "Initial status"
            }
        ],
        "audit": [
            {
                "step": "Domain",
                "notes": "Initial audit entry",
                "ts": "2024-01-01T00:00:00Z"
            }
        ],
        "cost": {
            "domain_usd": 0.0,
            "crawl_usd": 0.0,
            "enrich_usd": 0.0,
            "total_usd": 0.0
        }
    }

    # Should not raise validation errors
    errors = list(validator.iter_errors(minimal_record))
    assert len(errors) == 0, f"Minimal record should be valid: {errors}"


def test_schema_checksum():
    """Test that schema checksum can be computed."""
    schema_path = Path("schemas/unified_lead_record.json")
    with open(schema_path, "rb") as f:
        schema_content = f.read()

    checksum = hashlib.sha256(schema_content).hexdigest()
    assert len(checksum) == 64, "SHA256 checksum should be 64 characters"
    assert checksum.isalnum() or all(c in 'abcdef' for c in checksum), "Checksum should be valid hex"


def test_schema_constraints():
    """Test that schema enforces constraints."""
    schema_path = Path("schemas/unified_lead_record.json")
    with open(schema_path, "r") as f:
        schema_data = json.load(f)

    validator = Draft202012Validator(schema_data)

    # Test array length constraints
    test_record = {
        "lead_id": "550e8400-e29b-41d4-a716-446655440000",
        "domain": "example.com",
        "company": {
            "evidence_urls": ["url1", "url2", "url3", "url4", "url5",
                             "url6", "url7", "url8", "url9", "url10", "url11"]  # > 10
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
            "cache": {},
            "evidence_paths": {
                "domain": None,
                "crawl": None,
                "enrich": None
            }
        },
        "status": "new",
        "status_history": [
            {
                "status": "new",
                "ts": "2024-01-01T00:00:00Z",
                "notes": "Initial status"
            }
        ],
        "audit": [
            {
                "step": "Domain",
                "notes": "Initial audit entry",
                "ts": "2024-01-01T00:00:00Z"
            }
        ],
        "cost": {
            "domain_usd": 0.0,
            "crawl_usd": 0.0,
            "enrich_usd": 0.0,
            "total_usd": 0.0
        }
    }

    # Should raise validation error for too many evidence URLs
    errors = list(validator.iter_errors(test_record))
    assert len(errors) > 0, "Should fail validation with too many evidence URLs"

    # Check that the error is about maxItems
    error_messages = [str(e) for e in errors]
    assert any("maxItems" in msg for msg in error_messages), "Should have maxItems validation error"
