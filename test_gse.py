#!/usr/bin/env python3
"""
Test script for Google Search Engine (GSE) API
"""

import os
import asyncio
import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


async def test_gse_api():
    """Test GSE API connection and search functionality."""

    # Get API credentials from environment
    api_key = os.getenv("GSE_API_KEY")
    cx = os.getenv("GSE_CX")

    print("Testing GSE API...")
    print("API Key: [set]" if api_key else "❌ No API key found")
    print("Search Engine ID: [set]" if cx else "❌ No Search Engine ID found")
    print("-" * 50)
    if not api_key or not cx:
        print("❌ Missing GSE_API_KEY or GSE_CX in environment")
        return

    # Test API endpoint
    base_url = "https://www.googleapis.com/customsearch/v1"
    test_query = "dental practice groups 5+ locations"

    try:
        print(f"🔍 Testing search query: '{test_query}'")

        params = {
            "key": api_key,
            "cx": cx,
            "q": test_query,
            "num": 3,  # Just get 3 results for testing
        }

        async with httpx.AsyncClient(timeout=(5.0, 15.0)) as client:
            print("📡 Making API request...")
            response = await client.get(base_url, params=params)

            print(f"📊 Response status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print("✅ API call successful!")

                # Check response structure
                search_info = data.get("searchInformation", {})
                print(f"📈 Total results: {search_info.get('totalResults', 'Unknown')}")
                print(
                    f"⏱️ Search time: {search_info.get('searchTime', 'Unknown')} seconds"
                )

                # Show first few results
                items = data.get("items", [])
                print(f"📋 Found {len(items)} items")

                for i, item in enumerate(items[:2], 1):
                    print(f"\n{i}. {item.get('title', 'No title')}")
                    print(f"   URL: {item.get('link', 'No URL')}")
                    print(f"   Snippet: {item.get('snippet', 'No snippet')[:100]}...")

            else:
                print(f"❌ API call failed with status {response.status_code}")
                print(f"Response: {response.text[:200]}...")

    except httpx.TimeoutException:
        print("⏰ Request timed out - network issue or API slow")
    except httpx.RequestError as e:
        print(f"🌐 Network error: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(test_gse_api())
