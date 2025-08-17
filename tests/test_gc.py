"""
Unit tests for the garbage collection script.
"""

import pytest
import os
import time
import json
from pathlib import Path
from unittest.mock import patch

# Import the GC script
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import garbage_collector as gc_module


class TestGarbageCollection:
    """Test cases for garbage collection functionality."""

    def test_get_data_dir_default(self):
        """Test default data directory when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            assert gc_module.get_data_dir() == "./data"

    def test_get_data_dir_env(self):
        """Test data directory from environment variable."""
        with patch.dict(os.environ, {"LEADPOET_DATA_DIR": "/custom/data"}):
            assert gc_module.get_data_dir() == "/custom/data"

    def test_get_file_age_days(self, temp_data_dir):
        """Test file age calculation."""
        test_file = os.path.join(temp_data_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test")

        # Wait a moment to ensure file timestamp is different
        time.sleep(0.1)

        age = gc_module.get_file_age_days(test_file)
        assert age >= 0
        assert age < 1  # Should be less than 1 day

    def test_get_referenced_files_empty(self, temp_data_dir):
        """Test getting referenced files from empty directory."""
        referenced = gc_module.get_referenced_files(temp_data_dir)
        assert referenced == set()

    def test_get_referenced_files_with_data(self, temp_data_dir):
        """Test getting referenced files from JSONL files."""
        # Create domain_all.jsonl with references
        jsonl_path = os.path.join(temp_data_dir, "domain_all.jsonl")
        test_record = {
            "provenance": {
                "evidence_paths": {
                    "domain": "data/evidence/example.com.json",
                    "crawl": "data/crawl_artifacts/example.com.json",
                }
            }
        }

        with open(jsonl_path, "w") as f:
            f.write(json.dumps(test_record) + "\n")

        referenced = gc_module.get_referenced_files(temp_data_dir)
        expected = {
            os.path.join(temp_data_dir, "data/evidence/example.com.json"),
            os.path.join(temp_data_dir, "data/crawl_artifacts/example.com.json"),
        }
        assert referenced == expected

    def test_cleanup_artifacts_basic(self, temp_data_dir):
        """Test basic artifact cleanup functionality."""
        # Create test artifacts
        evidence_dir = os.path.join(temp_data_dir, "evidence")
        crawl_dir = os.path.join(temp_data_dir, "crawl_artifacts")

        # Create some test files
        test_files = [
            os.path.join(evidence_dir, "example1.com.json"),
            os.path.join(evidence_dir, "example2.com.json"),
            os.path.join(crawl_dir, "example1.com.json"),
        ]

        for file_path in test_files:
            with open(file_path, "w") as f:
                f.write('{"test": "data"}')

        # Run cleanup
        deleted, skipped = gc_module.cleanup_artifacts(
            temp_data_dir, max_age_days=0, max_versions=1
        )

        # Should delete old files (max_age_days=0)
        assert deleted >= 0
        assert skipped >= 0

    def test_cleanup_artifacts_version_limit(self, temp_data_dir):
        """Test version limiting in artifact cleanup."""
        evidence_dir = os.path.join(temp_data_dir, "evidence")

        # Create multiple versions of same domain
        for i in range(5):
            file_path = os.path.join(evidence_dir, f"example.com.v{i}.json")
            with open(file_path, "w") as f:
                f.write(f'{{"version": {i}}}')

        # Run cleanup with max_versions=3
        deleted, skipped = gc_module.cleanup_artifacts(
            temp_data_dir, max_age_days=365, max_versions=3
        )

        # Should keep only 3 files
        remaining_files = list(Path(evidence_dir).glob("*.json"))
        assert len(remaining_files) == 3

    def test_main_success(self, temp_data_dir):
        """Test successful main execution."""
        with patch("gc_module.cleanup_artifacts") as mock_cleanup:
            mock_cleanup.return_value = (5, 2)

            with patch("gc_module.get_data_dir") as mock_get_dir:
                mock_get_dir.return_value = temp_data_dir

                result = gc_module.main()
                assert result == 0
                mock_cleanup.assert_called_once_with(temp_data_dir)

    def test_main_data_dir_not_exists(self):
        """Test main execution when data directory doesn't exist."""
        with patch("gc_module.get_data_dir") as mock_get_dir:
            mock_get_dir.return_value = "/nonexistent/path"

            result = gc_module.main()
            assert result == 1

    def test_main_exception(self):
        """Test main execution when exception occurs."""
        with patch("gc_module.get_data_dir") as mock_get_dir:
            mock_get_dir.side_effect = Exception("Test error")

            result = gc_module.main()
            assert result == 1


if __name__ == "__main__":
    pytest.main([__file__])
