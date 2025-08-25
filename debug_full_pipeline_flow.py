#!/usr/bin/env python3
"""
Debug script to test the full pipeline flow exactly as it happens.
"""

import asyncio
import json
import logging
from src.enrich_provider_router import create_enrichment_router
from src.enrich_providers.base import EnrichmentRequest, ProviderTier

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_full_pipeline_flow():
    """Test the full pipeline flow exactly as it happens."""

    print("🔍 Testing Full Pipeline Flow")
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
    print(f"\n🎯 Testing full pipeline flow for domain: {domain}")

    # Create enrichment request (exactly as pipeline does)
    request = EnrichmentRequest(domain=domain)

    print(f"✅ Created enrichment request:")
    print(f"  Domain: {request.domain}")

    # Step 1: Call router (exactly as pipeline does)
    print(f"\n🚀 Step 1: Calling router.get_all_domain_prospects...")
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
            print(f"  Data keys: {list(result.data.keys()) if isinstance(result.data, dict) else 'N/A'}")
            if isinstance(result.data, dict) and "data" in result.data:
                prospects = result.data["data"]
                print(f"  Prospects type: {type(prospects)}")
                print(f"  Prospects length: {len(prospects) if prospects else 0}")
                if prospects and len(prospects) > 0:
                    first_prospect = prospects[0]
                    print(f"  First prospect type: {type(first_prospect)}")
                    print(f"  First prospect keys: {list(first_prospect.keys()) if isinstance(first_prospect, dict) else 'N/A'}")
                    print(f"  First prospect: {first_prospect}")

    except Exception as e:
        print(f"❌ Router execution failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Step 2: Simulate pipeline data processing
    print(f"\n🔍 Step 2: Simulating pipeline data processing...")

    if result.success and result.data:
        prospects_data = result.data
        discovered_contacts = []

        print(f"  Processing prospects_data: {type(prospects_data)}")

        # Process prospects data to extract contacts (exactly as pipeline does)
        if (
            isinstance(prospects_data, dict)
            and "data" in prospects_data
        ):
            prospects = prospects_data["data"]
            print(f"  ✅ Extracted prospects from 'data' key: {len(prospects)} prospects")
        elif isinstance(prospects_data, list):
            prospects = prospects_data
            print(f"  ✅ Prospects is direct list: {len(prospects)} prospects")
        else:
            prospects = []
            print(f"  ❌ No prospects found, type: {type(prospects_data)}")

        if prospects:
            print(f"  📋 Processing {len(prospects)} prospects...")

            # Build decision-maker titles from role priorities (exactly as pipeline does)
            role_priority = icp_config.get("role_priority", {})
            decision_maker_titles = []

            for role, priority in role_priority.items():
                if priority <= 5:  # Focus on high-priority roles
                    decision_maker_titles.append(role.title())
                    # Add common variations
                    if role.lower() == "ceo":
                        decision_maker_titles.extend([
                            "Chief Executive Officer",
                            "Chief Executive",
                        ])
                    elif role.lower() == "owner":
                        decision_maker_titles.extend(["Founder", "Proprietor"])
                    elif role.lower() == "president":
                        decision_maker_titles.extend([
                            "Chief Executive",
                            "Executive Director",
                        ])
                    elif role.lower() == "vp":
                        decision_maker_titles.extend(["Vice President", "Vice-President"])
                    elif role.lower() == "director":
                        decision_maker_titles.extend([
                            "Managing Director",
                            "Executive Director",
                            "General Manager",
                        ])
                    elif role.lower() == "head":
                        decision_maker_titles.extend([
                            "Head of",
                            "Department Head",
                            "Division Head",
                        ])
                    elif role.lower() == "manager":
                        # Use configurable manager titles from ICP config, or fall back to generic ones
                        manager_titles = icp_config.get("role_priority", {}).get(
                            "manager_titles",
                            [
                                "Operations Manager",
                                "General Manager",
                                "Department Manager",
                            ],
                        )
                        decision_maker_titles.extend(manager_titles)

            decision_set = {t.lower() for t in decision_maker_titles}
            print(f"  🎯 Decision maker titles: {sorted(decision_set)}")

            # Process prospects and build contacts (exactly as pipeline does)
            for i, profile in enumerate(prospects[:5]):  # Limit to 5 contacts
                print(f"  \n🔍 Processing prospect {i+1}:")
                print(f"    Profile type: {type(profile)}")
                print(f"    Profile keys: {list(profile.keys()) if isinstance(profile, dict) else 'N/A'}")

                # Handle both ContactData objects and dictionaries
                if hasattr(profile, "__dataclass_fields__"):
                    # It's a ContactData object, access attributes directly
                    title_value = profile.job_title or ""
                    first_name = profile.first_name or ""
                    last_name = profile.last_name or ""
                    company_name = profile.company_name or ""
                    linkedin_url = profile.linkedin_url or ""
                    location = profile.location or ""
                else:
                    # It's a dictionary, use .get() method
                    title_value = (
                        profile.get("jobTitle")
                        or profile.get("position")
                        or profile.get("title")
                        or ""
                    )
                    first_name = profile.get("firstName", "")
                    last_name = profile.get("lastName", "")
                    company_name = profile.get("company", "")
                    linkedin_url = profile.get("linkedinUrl", "")
                    location = profile.get("location", "")

                print(f"    Title: '{title_value}'")
                print(f"    Name: {first_name} {last_name}")
                print(f"    Company: {company_name}")

                # Check if title matches any decision-maker role
                is_decision_maker = False
                if title_value:
                    title_lower = title_value.lower()
                    # Check for exact matches first
                    if title_lower in decision_set:
                        is_decision_maker = True
                        print(f"    ✅ EXACT MATCH: '{title_value}' matches '{title_lower}'")
                    else:
                        # Check for partial matches
                        for decision_title in decision_set:
                            if (
                                decision_title in title_lower
                                or title_lower in decision_title
                            ):
                                is_decision_maker = True
                                print(f"    ✅ PARTIAL MATCH: '{title_value}' contains '{decision_title}'")
                                break

                if not is_decision_maker:
                    print(f"    ❌ NO MATCH: '{title_value}' is not a decision-maker title")
                    continue

                print(f"    ✅ ACCEPTED: Creating contact for {first_name} {last_name}")

                contact = {
                    "contact_id": f"discovered_{len(discovered_contacts)}",
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": "",
                    "job_title": title_value,
                    "company": company_name,
                    "linkedin_url": linkedin_url,
                    "location": location,
                    "discovery_source": "router",
                    "discovery_method": "domain_prospects",
                }

                discovered_contacts.append(contact)

            print(f"\n📊 Summary:")
            print(f"  Total prospects processed: {len(prospects)}")
            print(f"  Contacts discovered: {len(discovered_contacts)}")
            print(f"  Contacts rejected: {len(prospects) - len(discovered_contacts)}")

            if discovered_contacts:
                print(f"  \n✅ Discovered contacts:")
                for i, contact in enumerate(discovered_contacts):
                    print(f"    {i+1}. {contact['first_name']} {contact['last_name']} - {contact['job_title']}")
            else:
                print(f"  \n❌ No contacts discovered - all prospects were filtered out")
        else:
            print(f"  ❌ No prospects to process")
    else:
        print(f"  ❌ Router result indicates failure or no data")

if __name__ == "__main__":
    asyncio.run(test_full_pipeline_flow())

