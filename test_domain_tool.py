#!/usr/bin/env python3
"""
Test script for Domain tool in isolation
"""
import os
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def test_domain_tool():
    """Test domain tool in isolation."""

    try:
        print("🔧 Testing Domain Tool...")
        print("-" * 50)

        # Load ICP config
        import json
        with open('icp_config.json', 'r') as f:
            icp_config = json.load(f)

        print("✅ ICP config loaded")
        print(f"📋 Queries: {len(icp_config['queries'])} queries")

        # Test with just 1 query and 1 page
        print("🔍 Testing with minimal configuration...")
        test_config = icp_config.copy()
        test_config['queries'] = test_config['queries'][:1]  # Just first query

        print(f"🔍 Testing query: {test_config['queries'][0]}")

        # Run domain tool as module
        print("🏃 Running domain tool...")

        # Use subprocess to run as module
        import subprocess
        result = subprocess.run([
            sys.executable, "-m", "src.domain",
            "--config", temp_config_path,
            "--test-mode"
        ], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print("✅ Domain tool completed!")
            print(f"📤 Output: {result.stdout}")
        else:
            print(f"❌ Domain tool failed with return code {result.returncode}")
            print(f"📤 Output: {result.stdout}")
            print(f"❌ Error: {result.stderr}")

    except subprocess.TimeoutExpired:
    except subprocess.TimeoutExpired:
        print("⏰ Domain tool timed out after 30 seconds - it's hanging!")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up temporary config file
        import os
        if 'temp_config_path' in locals():
            try:
                os.unlink(temp_config_path)
            except:
                pass  # Ignore cleanup errorsif __name__ == "__main__":
    asyncio.run(test_domain_tool())
