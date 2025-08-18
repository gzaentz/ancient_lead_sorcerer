#!/usr/bin/env python3
"""
Test script for LLM API (OpenAI)
"""
import os
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def test_llm_api():
    """Test LLM API connection and basic functionality."""

    # Get API credentials from environment
    api_key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('OPENAI_MODEL', 'gpt-4o')

    print(f"Testing LLM API...")
    print(f"API Key: {api_key[:10]}..." if api_key else "❌ No API key found")
    print(f"Model: {model}")
    print("-" * 50)

    if not api_key:
        print("❌ Missing OPENAI_API_KEY in environment")
        return

    try:
        print("🤖 Initializing OpenAI client...")
        client = AsyncOpenAI(api_key=api_key)

        print("💬 Testing simple completion...")
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "Say 'Hello, Lead Sorcerer!' in one sentence."}
            ],
            max_tokens=50,
            temperature=0.1
        )

        print("✅ LLM API call successful!")
        print(f"🤖 Response: {response.choices[0].message.content}")
        print(f"📊 Usage: {response.usage}")

    except Exception as e:
        print(f"❌ LLM API error: {e}")

if __name__ == "__main__":
    asyncio.run(test_llm_api())
