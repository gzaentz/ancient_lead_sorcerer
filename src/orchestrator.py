"""
Orchestrator for Lead Sorcerer.

This orchestrator coordinates the three main tools (Domain, Crawl, Enrich) to process
leads through the complete pipeline. It handles data flow, persistence, exports,
and respects all BRD constraints.

Authoritative specifications: BRD §410-439
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import (
    PermitManager, setup_logging,
    validate_provider_config, load_costs_config, round4
)
from .domain import DomainTool
from .crawl import CrawlTool
from .enrich import run_enrich

# ============================================================================
# Constants and Configuration
# ============================================================================

INTERNAL_VERSION = "1.0.0"
DEFAULT_BATCH_SIZE = 50
DEFAULT_MAX_CONCURRENT_REQUESTS = 3

# ============================================================================
# Orchestrator Class
# ============================================================================

class LeadSorcererOrchestrator:
    """
    Main orchestrator that coordinates Domain → Crawl → Enrich pipeline.

    Responsibilities:
    - Load icp_config.json and resolve data directory
    - Call tools in sequence with proper filtering
    - Persist results to JSONL files
    - Handle exports when enabled
    - Manage concurrency and batch processing
    """

    def __init__(self, config_path: str, batch_size: int = DEFAULT_BATCH_SIZE):
        """
        Initialize the orchestrator.

        Args:
            config_path: Path to icp_config.json
            batch_size: Number of leads to process per batch
        """
        self.config_path = config_path
        self.batch_size = batch_size
        self.logger = setup_logging("orchestrator")

        # Load configuration
        self.icp_config = self._load_icp_config()

        # Resolve data directory
        self.data_dir = self._resolve_data_dir()

        # Initialize permit manager for global concurrency control
        max_concurrent = self.icp_config.get("concurrency", {}).get("max_concurrent_requests", DEFAULT_MAX_CONCURRENT_REQUESTS)
        self.permit_manager = PermitManager(max_concurrent)

        # Initialize tools
        self.domain_tool = DomainTool(self.icp_config, self.data_dir)
        self.crawl_tool = CrawlTool()

        # Track metrics
        self.start_time = None
        self.total_errors = []
        self.total_unknown_errors = 0

    def _load_icp_config(self) -> Dict[str, Any]:
        """Load and validate ICP configuration."""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)

            # Validate required fields
            required_fields = ['name', 'icp_text', 'queries', 'required_fields', 'threshold']
            for field in required_fields:
                if field not in config:
                    raise ValueError(f"Missing required field: {field}")

            return config
        except Exception as e:
            self.logger.error(f"Failed to load ICP config: {e}")
            raise

    def _resolve_data_dir(self) -> str:
        """Resolve data directory with precedence."""
        # Check environment variable first
        env_data_dir = os.environ.get('LEADPOET_DATA_DIR')
        if env_data_dir:
            return env_data_dir

        # Default to ./data
        return "./data"

    def _validate_provider_config(self) -> None:
        """Validate that all required providers are configured."""
        try:
            costs_config = load_costs_config()
            required_providers = ['gse', 'openrouter', 'firecrawl', 'proxycurl', 'mailgun', 'snovio']
            validate_provider_config(required_providers, costs_config)
        except Exception as e:
            self.logger.error(f"Provider configuration validation failed: {e}")
            raise

    def _validate_testing_flags(self) -> None:
        """Validate testing configuration flags."""
        testing = self.icp_config.get("testing", {})

        # Validate process_rejected flag
        if not isinstance(testing.get("process_rejected", False), bool):
            raise ValueError("testing.process_rejected must be a boolean")

        # Validate process_low_crawl flag
        if not isinstance(testing.get("process_low_crawl", False), bool):
            raise ValueError("testing.process_low_crawl must be a boolean")

        self.logger.info(f"Testing flags: process_rejected={testing.get('process_rejected', False)}, process_low_crawl={testing.get('process_low_crawl', False)}")

    def _validate_refresh_policy(self) -> None:
        """Validate refresh policy configuration."""
        refresh_policy = self.icp_config.get("refresh_policy", {})

        # Validate domain_ttl_days override
        domain_ttl_days = refresh_policy.get("domain_ttl_days")
        if domain_ttl_days is not None and not isinstance(domain_ttl_days, int):
            raise ValueError("refresh_policy.domain_ttl_days must be an integer")

        # Validate search.max_pages override
        search_config = self.icp_config.get("search", {})
        max_pages = search_config.get("max_pages")
        if max_pages is not None and not isinstance(max_pages, int):
            raise ValueError("search.max_pages must be an integer")

        # Validate default_country
        default_country = self.icp_config.get("default_country")
        if default_country and not isinstance(default_country, str):
            raise ValueError("default_country must be a string")

        # Validate role_priority configuration
        role_priority = self.icp_config.get("role_priority", {})
        if not isinstance(role_priority, dict):
            raise ValueError("role_priority must be a dictionary")

        self.logger.info(f"Refresh policy validated: domain_ttl_days={domain_ttl_days}, max_pages={max_pages}, default_country={default_country}")

    async def run_pipeline(self) -> Dict[str, Any]:
        """
        Run the complete Domain → Crawl → Enrich pipeline.

        Returns:
            Pipeline results with metrics and summary
        """
        self.start_time = time.time()
        self.logger.info(f"Starting Lead Sorcerer pipeline with config: {self.icp_config['name']}")

        try:
            # Validate provider configuration
            self._validate_provider_config()

            # Validate testing flags and refresh policy
            self._validate_testing_flags()
            self._validate_refresh_policy()

            # Step 1: Domain tool - generate and score leads
            self.logger.info("Running Domain tool...")
            domain_result = await self.domain_tool.run()

            if domain_result.get("errors"):
                self.total_errors.extend(domain_result["errors"])

            lead_records = domain_result.get("data", {}).get("lead_records", [])
            self.logger.info(f"Domain tool processed {len(lead_records)} leads")

            # Persist domain results (pass + rejects)
            self._persist_domain_results(lead_records)

            # Filter to passing leads for next stage
            passing_leads = [r for r in lead_records if r.get("icp", {}).get("pre_pass")]
            self.logger.info(f"Filtered to {len(passing_leads)} passing leads")

            # Check testing flags for additional processing
            testing = self.icp_config.get("testing", {})

            # Step 2: Crawl tool - extract company and contact data
            crawl_result = None
            enrich_result = None

            if passing_leads:
                self.logger.info("Running Crawl tool...")
                crawl_payload = {
                    "lead_records": passing_leads,
                    "icp_config": self.icp_config
                }
                crawl_result = await self.crawl_tool.run(crawl_payload)

                if crawl_result.get("errors"):
                    self.total_errors.extend(crawl_result["errors"])

                crawled_leads = crawl_result.get("data", {}).get("lead_records", [])
                self.logger.info(f"Crawl tool processed {len(crawled_leads)} leads")

                # Filter to enrich_ready leads
                enrich_ready_leads = [r for r in crawled_leads if r.get("status") == "enrich_ready"]

                # Check testing flags for additional processing
                process_low_crawl = testing.get("process_low_crawl", False)

                if process_low_crawl:
                    # Include crawled leads that don't meet threshold
                    low_crawl_leads = [r for r in crawled_leads if r.get("status") == "crawled"]
                    enrich_ready_leads.extend(low_crawl_leads)
                    self.logger.info(f"Including {len(low_crawl_leads)} low-crawl leads due to testing flag")

                # Step 3: Enrich tool - fill missing data and verify contacts
                if enrich_ready_leads:
                    self.logger.info("Running Enrich tool...")
                    enrich_payload = {
                        "lead_records": enrich_ready_leads,
                        "icp_config": self.icp_config,
                        "caps": self.icp_config.get("caps", {})
                    }
                    enrich_result = await run_enrich(enrich_payload)

                    if enrich_result.get("errors"):
                        self.total_errors.extend(enrich_result["errors"])

                    enriched_leads = enrich_result.get("data", {}).get("lead_records", [])
                    self.logger.info(f"Enrich tool processed {len(enriched_leads)} leads")

                    # Update the main lead records with enriched data
                    self._update_lead_records_with_enriched_data(lead_records, enriched_leads)
                else:
                    self.logger.info("No leads ready for enrichment")
            else:
                self.logger.info("No passing leads to crawl")

            # Handle exports if enabled
            if self.icp_config.get("exports", {}).get("enabled", False):
                self._export_leads(lead_records)

            # Calculate final metrics
            final_metrics = self._calculate_final_metrics(domain_result, crawl_result, enrich_result)

            # Log summary
            self._log_pipeline_summary(final_metrics)

            return {
                "success": True,
                "metrics": final_metrics,
                "total_errors": len(self.total_errors),
                "unknown_error_count": self.total_unknown_errors
            }

        except Exception as e:
            self.logger.error(f"Pipeline failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "metrics": self._build_error_metrics()
            }

    def _persist_domain_results(self, lead_records: List[Dict[str, Any]]) -> None:
        """Persist domain results to JSONL files."""
        try:
            # Ensure data directory exists
            Path(self.data_dir).mkdir(parents=True, exist_ok=True)

            # Write all results (pass + rejects)
            all_file = Path(self.data_dir) / "domain_all.jsonl"
            with open(all_file, 'a', encoding='utf-8') as f:
                for record in lead_records:
                    f.write(json.dumps(record) + '\n')

            # Write only passing results
            pass_file = Path(self.data_dir) / "domain_pass.jsonl"
            passing_records = [r for r in lead_records if r.get("icp", {}).get("pre_pass")]
            with open(pass_file, 'a', encoding='utf-8') as f:
                for record in passing_records:
                    f.write(json.dumps(record) + '\n')

            self.logger.info(f"Persisted {len(lead_records)} total leads, {len(passing_records)} passing leads")

            # Check if rotation is needed
            self._check_and_rotate_sinks(all_file, pass_file)

        except Exception as e:
            self.logger.error(f"Failed to persist domain results: {e}")

    def _check_and_rotate_sinks(self, all_file: Path, pass_file: Path) -> None:
        """
        Check if sinks need rotation (>10 MB or >30 days) and rotate if needed.

        Uses copy-on-write compaction to ensure atomic pointer swaps.
        """
        try:
            current_time = datetime.utcnow()

            # Check domain_all.jsonl
            if all_file.exists():
                self._rotate_sink_if_needed(all_file, current_time, "domain_all")

            # Check domain_pass.jsonl
            if pass_file.exists():
                self._rotate_sink_if_needed(pass_file, current_time, "domain_pass")

        except Exception as e:
            self.logger.error(f"Failed to check/rotate sinks: {e}")

    def _rotate_sink_if_needed(self, sink_file: Path, current_time: datetime, sink_name: str) -> None:
        """
        Rotate a sink file if it exceeds size or time limits.

        Args:
            sink_file: Path to the sink file
            current_time: Current UTC time
            sink_name: Name of the sink for logging
        """
        try:
            # Check file size (>10 MB)
            file_size_mb = sink_file.stat().st_size / (1024 * 1024)
            size_exceeded = file_size_mb > 10

            # Check file age (>30 days)
            file_mtime = datetime.fromtimestamp(sink_file.stat().st_mtime)
            age_days = (current_time - file_mtime).days
            age_exceeded = age_days > 30

            if size_exceeded or age_exceeded:
                self.logger.info(f"Rotating {sink_name}: size={file_size_mb:.1f}MB, age={age_days} days")
                self._rotate_sink_with_compaction(sink_file, sink_name)

        except Exception as e:
            self.logger.error(f"Failed to check rotation for {sink_name}: {e}")

    def _rotate_sink_with_compaction(self, sink_file: Path, sink_name: str) -> None:
        """
        Rotate sink using copy-on-write compaction for atomic pointer swap.

        Args:
            sink_file: Path to the sink file
            sink_name: Name of the sink for logging
        """
        try:
            # Create timestamped archive name
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
            archive_name = f"{sink_name}_{timestamp}.jsonl"
            archive_path = sink_file.parent / archive_name

            # Copy current content to archive (copy-on-write)
            if sink_file.exists():
                with open(sink_file, 'r', encoding='utf-8') as src, \
                     open(archive_path, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())

                self.logger.info(f"Archived {sink_name} to {archive_name}")

            # Truncate the original file (atomic operation)
            sink_file.write_text("", encoding='utf-8')

            self.logger.info(f"Rotated {sink_name} - file truncated")

        except Exception as e:
            self.logger.error(f"Failed to rotate {sink_name}: {e}")

    def _update_lead_records_with_enriched_data(self, lead_records: List[Dict[str, Any]], enriched_leads: List[Dict[str, Any]]) -> None:
        """Update lead records with enriched data from the enrich tool."""
        enriched_by_id = {r.get("lead_id"): r for r in enriched_leads}

        for record in lead_records:
            lead_id = record.get("lead_id")
            if lead_id in enriched_by_id:
                enriched_record = enriched_by_id[lead_id]
                # Update only the fields that Enrich tool is allowed to modify
                record.update({
                    "best_contact_id": enriched_record.get("best_contact_id"),
                    "status": enriched_record.get("status"),
                    "provenance": enriched_record.get("provenance", {}),
                    "cost": enriched_record.get("cost", {}),
                    "audit": enriched_record.get("audit", [])
                })

                # Update contacts with enriched data
                if "contacts" in enriched_record:
                    record["contacts"] = enriched_record["contacts"]

    def _export_leads(self, lead_records: List[Dict[str, Any]]) -> None:
        """Export leads to JSONL and CSV formats."""
        try:
            exports_config = self.icp_config.get("exports", {})
            if not exports_config.get("enabled", False):
                return

            # Create export directory with UTC timestamp
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
            export_dir = Path(self.data_dir) / "exports" / self.icp_config["name"] / timestamp
            export_dir.mkdir(parents=True, exist_ok=True)

            # Export to JSONL
            jsonl_file = export_dir / "leads.jsonl"
            with open(jsonl_file, 'w', encoding='utf-8') as f:
                for record in lead_records:
                    f.write(json.dumps(record) + '\n')

            # Export to CSV
            csv_file = export_dir / "leads.csv"
            self._export_to_csv(lead_records, csv_file)

            self.logger.info(f"Exported {len(lead_records)} leads to {export_dir}")

        except Exception as e:
            self.logger.error(f"Failed to export leads: {e}")

    def _export_to_csv(self, lead_records: List[Dict[str, Any]], csv_file: Path) -> None:
        """Export leads to CSV format with proper flattening rules."""
        if not lead_records:
            return

        # Get all possible fields for CSV headers
        all_fields = set()
        for record in lead_records:
            self._collect_fields(record, "", all_fields)

        # Sort fields lexicographically for stability
        sorted_fields = sorted(all_fields)

        # Write CSV header
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            f.write(','.join(f'"{field}"' for field in sorted_fields) + '\n')

            # Write data rows
            for record in lead_records:
                row_data = []
                for field in sorted_fields:
                    value = self._get_field_value(record, field)
                    row_data.append(f'"{value}"')
                f.write(','.join(row_data) + '\n')

    def _collect_fields(self, obj: Any, prefix: str, fields: set) -> None:
        """Recursively collect all field paths for CSV flattening."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                field_path = f"{prefix}.{key}" if prefix else key
                if isinstance(value, (dict, list)):
                    self._collect_fields(value, field_path, fields)
                else:
                    fields.add(field_path)
        elif isinstance(obj, list):
            # For arrays, join with "|" separator
            if obj and isinstance(obj[0], (str, int, float, bool)) or obj[0] is None:
                field_path = prefix
                fields.add(field_path)

    def _get_field_value(self, record: Dict[str, Any], field_path: str) -> str:
        """Get field value from record using dot notation."""
        try:
            keys = field_path.split('.')
            value = record
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return ""

            if value is None:
                return ""
            elif isinstance(value, bool):
                return str(value).lower()
            elif isinstance(value, list):
                # Join arrays with "|" separator
                if value and isinstance(value[0], (str, int, float, bool)) or value[0] is None:
                    return "|".join(str(v) if v is not None else "" for v in value)
                else:
                    return ""  # Skip arrays of objects
            else:
                return str(value)
        except Exception:
            return ""

    def _calculate_final_metrics(self, domain_result: Dict[str, Any], crawl_result: Optional[Dict[str, Any]], enrich_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate final pipeline metrics."""
        duration_ms = int((time.time() - self.start_time) * 1000) if self.start_time else 0

        # Aggregate cost metrics
        total_domain_cost = domain_result.get("metrics", {}).get("cost_usd", {}).get("domain", 0.0)
        total_crawl_cost = crawl_result.get("metrics", {}).get("cost_usd", {}).get("crawl", 0.0) if crawl_result else 0.0
        total_enrich_cost = enrich_result.get("metrics", {}).get("cost_usd", {}).get("enrich", 0.0) if enrich_result else 0.0

        # Count leads at each stage
        domain_count = len(domain_result.get("data", {}).get("lead_records", []))
        crawl_count = len(crawl_result.get("data", {}).get("lead_records", [])) if crawl_result else 0
        enrich_count = len(enrich_result.get("data", {}).get("lead_records", [])) if enrich_result else 0

        # Calculate pass rates
        domain_pass_rate = domain_result.get("metrics", {}).get("pass_rate")
        crawl_pass_rate = crawl_result.get("metrics", {}).get("pass_rate") if crawl_result else None
        enrich_pass_rate = enrich_result.get("metrics", {}).get("pass_rate") if enrich_result else None

        return {
            "duration_ms": duration_ms,
            "lead_counts": {
                "domain": domain_count,
                "crawl": crawl_count,
                "enrich": enrich_count
            },
            "pass_rates": {
                "domain": domain_pass_rate,
                "crawl": crawl_pass_rate,
                "enrich": enrich_pass_rate
            },
            "cost_usd": {
                "domain": round4(total_domain_cost),
                "crawl": round4(total_crawl_cost),
                "enrich": round4(total_enrich_cost),
                "total": round4(total_domain_cost + total_crawl_cost + total_enrich_cost)
            },
            "health": {
                "unknown_error_count": self.total_unknown_errors
            }
        }

    def _build_error_metrics(self) -> Dict[str, Any]:
        """Build metrics for error cases."""
        duration_ms = int((time.time() - self.start_time) * 1000) if self.start_time else 0
        return {
            "duration_ms": duration_ms,
            "lead_counts": {"domain": 0, "crawl": 0, "enrich": 0},
            "pass_rates": {"domain": None, "crawl": None, "enrich": None},
            "cost_usd": {"domain": 0.0, "crawl": 0.0, "enrich": 0.0, "total": 0.0},
            "health": {"unknown_error_count": self.total_unknown_errors}
        }

    def _log_pipeline_summary(self, metrics: Dict[str, Any]) -> None:
        """Log pipeline completion summary."""
        duration_seconds = metrics["duration_ms"] / 1000
        domains_per_hour = (metrics["lead_counts"]["domain"] / duration_seconds * 3600) if duration_seconds > 0 else 0
        cost_per_qualified = (metrics["cost_usd"]["total"] / metrics["lead_counts"]["enrich"]) if metrics["lead_counts"]["enrich"] > 0 else 0

        self.logger.info(f"Pipeline completed in {duration_seconds:.2f}s")
        self.logger.info(f"Processed {metrics['lead_counts']['domain']} domains, {metrics['lead_counts']['enrich']} enriched")
        self.logger.info(f"Performance: {domains_per_hour:.1f} domains/hour")
        self.logger.info(f"Cost: ${metrics['cost_usd']['total']:.4f} (${cost_per_qualified:.4f}/qualified lead)")
        self.logger.info(f"Errors: {len(self.total_errors)} total, {self.total_unknown_errors} unknown")

# ============================================================================
# CLI Interface
# ============================================================================

async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Lead Sorcerer Orchestrator")
    parser.add_argument("--config", required=True, help="Path to icp_config.json")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Batch size for processing")
    parser.add_argument("--data-dir", help="Override data directory")

    args = parser.parse_args()

    # Set data directory if provided
    if args.data_dir:
        os.environ['LEADPOET_DATA_DIR'] = args.data_dir

    try:
        # Initialize and run orchestrator
        orchestrator = LeadSorcererOrchestrator(args.config, args.batch_size)
        result = await orchestrator.run_pipeline()

        if result["success"]:
            print(json.dumps(result, indent=2))
            return 0
        else:
            print(json.dumps(result, indent=2))
            return 1
    except Exception as e:
        print(json.dumps({"error": str(e), "success": False}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
