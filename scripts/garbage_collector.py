#!/usr/bin/env python3
"""
Lead Sorcerer Garbage Collection Script

This script runs nightly to clean up old artifacts and maintain data retention policies.
Per BRD specifications:
- Keep latest 3 versions per domain
- Delete files older than 365 days
- Skip deletion if file is referenced in provenance.evidence_paths
"""

import os
import json
import glob
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_data_dir():
    """Get data directory with precedence: env -> ./data"""
    return os.environ.get("LEADPOET_DATA_DIR", "./data")


def get_file_age_days(file_path):
    """Get file age in days"""
    mtime = os.path.getmtime(file_path)
    age = datetime.now() - datetime.fromtimestamp(mtime)
    return age.days


def get_referenced_files(data_dir):
    """Get set of files referenced in provenance.evidence_paths"""
    referenced = set()

    # Check domain_all.jsonl and domain_pass.jsonl for references
    for jsonl_file in ["domain_all.jsonl", "domain_pass.jsonl"]:
        jsonl_path = os.path.join(data_dir, jsonl_file)
        if os.path.exists(jsonl_path):
            try:
                with open(jsonl_path, "r") as f:
                    for line in f:
                        if line.strip():
                            record = json.loads(line)
                            if (
                                "provenance" in record
                                and "evidence_paths" in record["provenance"]
                            ):
                                paths = record["provenance"]["evidence_paths"]
                                for path_type, path in paths.items():
                                    if path and os.path.isabs(path):
                                        referenced.add(path)
                                    elif path:
                                        referenced.add(os.path.join(data_dir, path))
            except Exception as e:
                logger.warning(f"Error reading {jsonl_file}: {e}")

    return referenced


def cleanup_artifacts(data_dir, max_age_days=365, max_versions=3):
    """Clean up old artifacts according to retention policy"""
    logger.info(f"Starting garbage collection in {data_dir}")

    # Get referenced files
    referenced_files = get_referenced_files(data_dir)
    logger.info(f"Found {len(referenced_files)} referenced files")

    # Clean up evidence and crawl artifacts
    artifact_dirs = [
        os.path.join(data_dir, "evidence"),
        os.path.join(data_dir, "crawl_artifacts"),
    ]

    total_deleted = 0
    total_skipped = 0

    for artifact_dir in artifact_dirs:
        if not os.path.exists(artifact_dir):
            continue

        logger.info(f"Processing {artifact_dir}")

        # Group files by domain (eTLD+1)
        domain_files = {}
        for file_path in glob.glob(os.path.join(artifact_dir, "*.json")):
            domain = os.path.splitext(os.path.basename(file_path))[0]
            if domain not in domain_files:
                domain_files[domain] = []
            domain_files[domain].append(file_path)

        # Process each domain
        for domain, files in domain_files.items():
            # Sort by modification time (newest first)
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

            # Keep latest max_versions
            files[:max_versions]
            files_to_check = files[max_versions:]

            # Check remaining files for age and references
            for file_path in files_to_check:
                if file_path in referenced_files:
                    logger.debug(f"Skipping referenced file: {file_path}")
                    total_skipped += 1
                    continue

                age_days = get_file_age_days(file_path)
                if age_days > max_age_days:
                    try:
                        os.remove(file_path)
                        logger.info(
                            f"Deleted old file: {file_path} (age: {age_days} days)"
                        )
                        total_deleted += 1
                    except Exception as e:
                        logger.error(f"Error deleting {file_path}: {e}")
                else:
                    logger.debug(f"Keeping file: {file_path} (age: {age_days} days)")

    logger.info(
        f"Garbage collection complete. Deleted: {total_deleted}, Skipped: {total_skipped}"
    )
    return total_deleted, total_skipped


def main():
    """Main entry point"""
    try:
        data_dir = get_data_dir()
        if not os.path.exists(data_dir):
            logger.error(f"Data directory does not exist: {data_dir}")
            return 1

        deleted, skipped = cleanup_artifacts(data_dir)
        logger.info(
            f"GC completed successfully: {deleted} files deleted, {skipped} files skipped"
        )
        return 0

    except Exception as e:
        logger.error(f"Garbage collection failed: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
