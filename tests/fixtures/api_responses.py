"""
Mock API response fixtures for enrichment providers.

This module contains realistic mock responses for testing enrichment providers
without making actual API calls.
"""

# CompanyEnrich API Response Fixtures
COMPANY_ENRICH_COMPANY_SUCCESS = {
    "success": True,
    "data": {
        "company": {
            "name": "TestCorp Inc",
            "description": "A leading software development company specializing in B2B SaaS solutions",
            "industry": "Software Development",
            "size": "100-500 employees",
            "founded_year": 2015,
            "revenue": "$10M-$50M",
            "website": "https://testcorp.com",
            "linkedin_url": "https://linkedin.com/company/testcorp",
            "twitter_url": "https://twitter.com/testcorp",
            "headquarters": {
                "city": "San Francisco",
                "state": "CA",
                "country": "United States",
            },
            "technologies": ["Python", "React", "AWS", "Docker", "PostgreSQL"],
            "employee_count": 287,
        }
    },
    "cost": 0.01,
    "request_id": "ce_req_123456789",
}

COMPANY_ENRICH_CONTACTS_SUCCESS = {
    "success": True,
    "data": {
        "contacts": [
            {
                "email": "john.smith@testcorp.com",
                "first_name": "John",
                "last_name": "Smith",
                "full_name": "John Smith",
                "job_title": "Chief Executive Officer",
                "department": "Executive",
                "seniority": "Executive",
                "linkedin_url": "https://linkedin.com/in/john-smith-ceo",
                "phone": "+1-415-555-0123",
                "location": "San Francisco, CA",
                "email_confidence": 0.95,
                "status": "verified",
            },
            {
                "email": "sarah.johnson@testcorp.com",
                "first_name": "Sarah",
                "last_name": "Johnson",
                "full_name": "Sarah Johnson",
                "job_title": "Chief Technology Officer",
                "department": "Engineering",
                "seniority": "Executive",
                "linkedin_url": "https://linkedin.com/in/sarah-johnson-cto",
                "location": "San Francisco, CA",
                "email_confidence": 0.92,
                "status": "verified",
            },
            {
                "email": "mike.brown@testcorp.com",
                "first_name": "Mike",
                "last_name": "Brown",
                "full_name": "Mike Brown",
                "job_title": "VP of Sales",
                "department": "Sales",
                "seniority": "Director",
                "linkedin_url": "https://linkedin.com/in/mike-brown-vp",
                "location": "New York, NY",
                "email_confidence": 0.88,
                "status": "verified",
            },
        ]
    },
    "cost": 0.02,
    "request_id": "ce_req_123456790",
}

COMPANY_ENRICH_EMAIL_FIND_SUCCESS = {
    "success": True,
    "data": {
        "contact": {
            "email": "bob.wilson@testcorp.com",
            "first_name": "Bob",
            "last_name": "Wilson",
            "full_name": "Bob Wilson",
            "job_title": "VP Sales",
            "department": "Sales",
            "seniority": "Director",
            "linkedin_url": "https://linkedin.com/in/bob-wilson-sales",
            "email_confidence": 0.92,
            "status": "verified",
            "sources": ["company_website", "linkedin"],
        }
    },
    "cost": 0.015,
    "request_id": "ce_req_123456791",
}

COMPANY_ENRICH_ERROR_RATE_LIMIT = {
    "success": False,
    "error": {
        "code": "RATE_LIMIT_EXCEEDED",
        "message": "API rate limit exceeded. Please try again in 60 seconds.",
        "retry_after": 60,
    },
    "request_id": "ce_req_123456792",
}

COMPANY_ENRICH_ERROR_AUTH = {
    "success": False,
    "error": {
        "code": "AUTHENTICATION_FAILED",
        "message": "Invalid API key provided",
    },
    "request_id": "ce_req_123456793",
}

# Anymail Finder API Response Fixtures
ANYMAIL_FINDER_COMPANY_SUCCESS = {
    "status": "success",
    "data": {
        "company": {
            "name": "TestCorp Inc",
            "description": "Leading B2B SaaS development company",
            "industry": "Software Development",
            "size": "100-500",
            "founded": 2015,
            "website": "testcorp.com",
            "linkedin": "testcorp",
            "location": "San Francisco, CA",
            "country": "United States",
            "technologies": ["Python", "JavaScript", "AWS"],
        }
    },
    "credits_used": 0.008,
}

ANYMAIL_FINDER_CONTACTS_SUCCESS = {
    "status": "success",
    "data": {
        "emails": [
            {
                "email": "alice.cooper@testcorp.com",
                "first_name": "Alice",
                "last_name": "Cooper",
                "full_name": "Alice Cooper",
                "position": "Marketing Director",
                "department": "Marketing",
                "confidence": 0.94,
                "verified": True,
                "sources": ["company_website"],
            },
            {
                "email": "david.lee@testcorp.com",
                "first_name": "David",
                "last_name": "Lee",
                "full_name": "David Lee",
                "position": "Senior Developer",
                "department": "Engineering",
                "confidence": 0.89,
                "verified": True,
                "sources": ["linkedin"],
            },
        ]
    },
    "credits_used": 0.015,
}

ANYMAIL_FINDER_EMAIL_FIND_SUCCESS = {
    "status": "success",
    "data": {
        "email": "jane.doe@testcorp.com",
        "first_name": "Jane",
        "last_name": "Doe",
        "full_name": "Jane Doe",
        "position": "Product Manager",
        "confidence": 0.91,
        "verified": True,
        "sources": ["company_website", "social_media"],
    },
    "credits_used": 0.012,
}

ANYMAIL_FINDER_ERROR_RATE_LIMIT = {
    "status": "error",
    "error": {
        "code": "RATE_LIMIT",
        "message": "Rate limit exceeded. Try again in 5 minutes.",
        "retry_after": 300,
    },
}

ANYMAIL_FINDER_ERROR_AUTH = {
    "status": "error",
    "error": {"code": "INVALID_API_KEY", "message": "The provided API key is invalid"},
}

# Coresignal API Response Fixtures
CORESIGNAL_COMPANY_SUCCESS = {
    "company": {
        "id": "cs_123456",
        "name": "TestCorp Inc",
        "description": "B2B SaaS company providing innovative solutions",
        "industry": "Software Development",
        "website": "https://testcorp.com",
        "linkedin_url": "https://linkedin.com/company/testcorp",
        "founded_year": 2015,
        "size_range": "100-500",
        "headquarters": {
            "city": "San Francisco",
            "state": "California",
            "country": "United States",
        },
        "employee_count": 287,
        "annual_revenue": "$10M-$50M",
    }
}

CORESIGNAL_ERROR_AUTH = {
    "error": {"code": 401, "message": "Unauthorized: Invalid API token"}
}

# Snovio API Response Fixtures
SNOVIO_AUTH_SUCCESS = {
    "access_token": "snov_token_abcdef123456",
    "expires_in": 3600,
    "token_type": "Bearer",
}

SNOVIO_CONTACTS_SUCCESS = {
    "success": True,
    "data": {
        "emails": [
            {
                "email": "ceo@testcorp.com",
                "firstName": "Robert",
                "lastName": "Johnson",
                "position": "Chief Executive Officer",
                "status": "valid",
                "type": "personal",
            },
            {
                "email": "cto@testcorp.com",
                "firstName": "Lisa",
                "lastName": "Wang",
                "position": "Chief Technology Officer",
                "status": "valid",
                "type": "personal",
            },
        ],
        "companyName": "TestCorp Inc",
        "domain": "testcorp.com",
    },
}

SNOVIO_ERROR_AUTH = {"success": False, "error": "Invalid client credentials"}

SNOVIO_ERROR_RATE_LIMIT = {
    "success": False,
    "error": "Rate limit exceeded. Please wait 60 seconds.",
}

# Error response patterns for testing
HTTP_ERROR_RESPONSES = {
    400: {"error": "Bad Request", "message": "Invalid request parameters"},
    401: {"error": "Unauthorized", "message": "Authentication required"},
    403: {"error": "Forbidden", "message": "Access denied"},
    404: {"error": "Not Found", "message": "Resource not found"},
    429: {"error": "Too Many Requests", "message": "Rate limit exceeded"},
    500: {"error": "Internal Server Error", "message": "Server error occurred"},
    503: {"error": "Service Unavailable", "message": "Service temporarily unavailable"},
}
