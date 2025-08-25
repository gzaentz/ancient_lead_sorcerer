#!/usr/bin/env python3
"""
Debug script to test title matching logic.
"""

import json

def test_title_matching():
    """Test the title matching logic used in the pipeline."""

    print("🔍 Testing Title Matching Logic")
    print("=" * 50)

    # Load ICP config
    with open('icp_config_dental_optimized quick.json', 'r') as f:
        icp_config = json.load(f)

    print(f"✅ Loaded ICP config: {icp_config['name']}")

    # Get role priorities
    role_priority = icp_config.get("role_priority", {})
    print(f"\n📋 Role Priorities:")
    for role, priority in role_priority.items():
        print(f"  {role}: {priority}")

    # Build decision-maker titles from role priorities
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

    print(f"\n🎯 Decision Maker Titles (Priority ≤ 5):")
    for title in decision_maker_titles:
        print(f"  {title}")

    decision_set = {t.lower() for t in decision_maker_titles}
    print(f"\n🔍 Decision Set (lowercase):")
    for title in sorted(decision_set):
        print(f"  {title}")

    # Test some sample titles that Apollo might return
    sample_titles = [
        "Founder",
        "CEO",
        "Chief Executive Officer",
        "Owner",
        "President",
        "Vice President",
        "Director",
        "Manager",
        "Administrator",
        "Coordinator",
        "Assistant",
        "Founder & CEO",
        "Owner/Operator",
        "Practice Administrator",
        "Office Manager"
    ]

    print(f"\n🧪 Testing Sample Titles:")
    for title in sample_titles:
        title_lower = title.lower()
        is_decision_maker = False

        # Check for exact matches first
        if title_lower in decision_set:
            is_decision_maker = True
        else:
            # Check for partial matches
            for decision_title in decision_set:
                if (
                    decision_title in title_lower
                    or title_lower in decision_title
                ):
                    is_decision_maker = True
                    break

        status = "✅ MATCH" if is_decision_maker else "❌ NO MATCH"
        print(f"  {status} '{title}' -> {title_lower}")

if __name__ == "__main__":
    test_title_matching()

