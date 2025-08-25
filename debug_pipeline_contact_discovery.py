#!/usr/bin/env python3
"""
Debug script to test contact discovery exactly as the pipeline does it.
"""

import asyncio
import json
import logging
from src.enrich_provider_router import create_enrichment_router
from src.enrich_providers.base import EnrichmentRequest, ProviderTier

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_pipeline_contact_discovery():
    """Test contact discovery exactly as the pipeline does it."""

    print("🔍 Testing Pipeline Contact Discovery")
    print("=" * 50)

    # Load ICP config
    with open('icp_config_dental_optimized quick.json', 'r') as f:
        icp_config = json.load(f)

    print(f"✅ Loaded ICP config: {icp_config['name']}")

    # Create enrichment router (exactly as pipeline does)
    print("\n🚀 Creating enrichment router...")
    try:
        router = create_enrichment_router(icp_config)
        print("✅ Router created successfully")

        # Show providers
        print(f"\n📋 Providers initialized:")
        for tier, providers in router.providers.items():
            print(f"  {tier}: {[p.name for p in providers]}")

    except Exception as e:
        print(f"❌ Router creation failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test with gentledental.com (exactly as pipeline does)
    domain = "gentledental.com"
    print(f"\n🎯 Testing contact discovery for domain: {domain}")

    # Create enrichment request (exactly as pipeline does)
    request = EnrichmentRequest(domain=domain)

    print(f"✅ Created enrichment request:")
    print(f"  Domain: {request.domain}")

    # Test the router's get_all_domain_prospects method (exactly as pipeline does)
    print(f"\n🚀 Testing router.get_all_domain_prospects...")
    try:
        result = await router.get_all_domain_prospects(request)

        print(f"✅ Router result:")
        print(f"  Success: {result.success}")
        print(f"  Error: {result.error}")
        print(f"  Provider: {result.provider}")
        print(f"  Cost: {result.cost}")
        print(f"  Data type: {type(result.data)}")
        print(f"  Data length: {len(result.data) if result.data else 0}")

        if result.data:
            print(f"  First item type: {type(result.data[0]) if isinstance(result.data, list) else 'N/A'}")
            if isinstance(result.data, list) and result.data:
                print(f"  First item keys: {list(result.data[0].keys()) if hasattr(result.data[0], 'keys') else 'N/A'}")
                print(f"  Sample data: {result.data[0] if isinstance(result.data, list) else 'N/A'}")

    except Exception as e:
        print(f"❌ Router execution failed: {e}")
        import traceback
        traceback.print_exc()

    # Test individual providers to see which one works
    print(f"\n🔍 Testing individual providers...")

    # Test Anymail Finder
    try:
        anymail_provider = [p for p in router.providers[ProviderTier.TIER_0] if p.name == 'AnymailFinder'][0]
        print(f"✅ Testing Anymail Finder: {anymail_provider.name}")

        result = await anymail_provider.get_all_domain_prospects(request)
        print(f"  Anymail Finder result:")
        print(f"    Success: {result.success}")
        print(f"    Error: {result.error}")
        print(f"    Data type: {type(result.data)}")
        print(f"    Data length: {len(result.data) if result.data else 0}")

    except Exception as e:
        print(f"❌ Anymail Finder test failed: {e}")

    # Test Apollo provider
    try:
        apollo_provider = [p for p in router.providers[ProviderTier.TIER_0] if p.name == 'Apollo'][0]
        print(f"✅ Testing Apollo: {apollo_provider.name}")

        result = await apollo_provider.get_all_domain_prospects(request)
        print(f"  Apollo result:")
        print(f"    Success: {result.success}")
        print(f"    Error: {result.error}")
        print(f"    Data type: {type(result.data)}")
        print(f"    Data length: {len(result.data) if result.data else 0}")

    except Exception as e:
        print(f"❌ Apollo test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_pipeline_contact_discovery())
