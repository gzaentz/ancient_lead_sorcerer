#!/usr/bin/env python3
"""
Test script for Domain tool in isolation
"""

import os
import asyncio
import sys
import tempfile
import json
import subprocess
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


async def test_domain_tool():
    """Test domain tool in isolation."""

    temp_config_path = None
    try:
        print("🔧 Testing Domain Tool...")
        print("-" * 50)

        # Load ICP config
        with open("icp_config.json", "r") as f:
            icp_config = json.load(f)

        print("✅ ICP config loaded")
        print(f"📋 Queries: {len(icp_config['queries'])} queries")

        # Test with just 1 query and 1 page
        print("🔍 Testing with minimal configuration...")
        test_config = icp_config.copy()
        test_config["queries"] = test_config["queries"][:1]  # Just first query

        print(f"🔍 Testing query: {test_config['queries'][0]}")

        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(test_config, f)
            temp_config_path = f.name

        print(f"📁 Temporary config created: {temp_config_path}")

        # Run domain tool as module
        print("🏃 Running domain tool...")

        # Use subprocess to run as module
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.domain",
                "--config",
                temp_config_path,
                "--test-mode",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            print("✅ Domain tool completed!")
            print(f"📤 Output: {result.stdout}")
        else:
            print(f"❌ Domain tool failed with return code {result.returncode}")
            print(f"📤 Output: {result.stdout}")
            print(f"❌ Error: {result.stderr}")

    except subprocess.TimeoutExpired:
        print("⏰ Domain tool timed out after 30 seconds - it's hanging!")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Clean up temporary config file
        if temp_config_path and os.path.exists(temp_config_path):
            try:
                os.unlink(temp_config_path)
            except Exception:
                pass  # Ignore cleanup errors


if __name__ == "__main__":
    asyncio.run(test_domain_tool())
