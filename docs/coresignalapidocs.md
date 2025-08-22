CoreSignal — Clean Company API Cheatsheet

1. API Overview
   CoreSignal’s Clean Company API is a read‑only data‑retrieval service. It exposes three main types of endpoints:
   • Search endpoint (POST, Elasticsearch DSL) – find matching company IDs.
   • Collect endpoints (GET) – retrieve full company profiles by numeric ID or LinkedIn‑style shorthand.
   • Enrich endpoint (GET) – get company details using a website or social‑profile URL.
   All requests must use HTTPS and be authenticated via your unique API key in the apikey request header (CoreSignal docs).
2. Base URL
   All endpoint paths are appended to the base URL:
   https://api.coresignal.com/cdapi/v2
3. Endpoints & Rate Limits
   Endpoint path Method Input Use case Rate limit (req/s)
   /company_clean/search/es_dsl POST JSON query (Elasticsearch DSL) Find matching company IDs 27
   /company_clean/collect/{company_id} GET company_id (numeric) Full profile by numeric ID 54
   /company_clean/collect/{shorthand_name} GET shorthand_name (e.g. apple) Full profile by LinkedIn‑style slug 54
   /company_clean/enrich?website={url} GET company website or social URL One‑shot enrichment via URL 18
   The rate‑limit values above come directly from CoreSignal’s Clean Company rate‑limit table (CoreSignal docs). If your integration needs higher throughput, contact CoreSignal to discuss increased quotas.
4. Authentication & Headers
   Your API key must be included in every request header. JSON is the recommended response format.
   Header Value
   apikey Your personal API key
   Accept application/json (recommended)
   Content-Type application/json (required for POST requests)
   Every successful response also includes an X‑Credits‑Remaining header indicating how many credits you have left, and an X‑RateLimit‑Remaining header showing remaining rate limit capacity (CoreSignal docs).
5. Credit Consumption
   • Search (/search/es_dsl) → 1 search credit per HTTP 200 response.
   • Collect/Enrich (/collect/\*, /enrich) → 1 collect credit per HTTP 200 response.
   If you need larger quotas, discuss them with your CoreSignal account manager (CoreSignal docs).
6. Enrich Endpoint Details
   The enrich endpoint retrieves a company’s profile via its website or social URL.
   • Path: GET /company_clean/enrich?website={url}
   • Supported formats:
   • Full domains, e.g. https://www.apple.com
   • Sub‑pages or sub‑domains, e.g. https://careers.amazon.com
   • With or without protocol, www, or trailing slash – the API normalises these variants automatically (CoreSignal docs).
   Example cURL request
   curl -X GET \
    'https://api.coresignal.com/cdapi/v2/company_clean/enrich?website=thermofisher.com' \
    -H 'accept: application/json' \
    -H 'apikey: YOUR_API_KEY'
7. Sample Response (truncated)
   {
   "id": 1234567,
   "name": "Company 123",
   "type": "private",
   "founded": "2019",
   "followers": 121000,
   "websites": {
   "main": "https://www.company123.com",
   "facebook": "https://www.facebook.com/company123",
   "twitter": "https://twitter.com/company123"
   },
   "size_range": "51-200 employees",
   "industry": "software",
   "location_hq_country": "United States",
   "employees_count": 150,
   "ticker": "CMP123",
   "...": "additional fields omitted for brevity"
   }
   A full sample payload is available in the CoreSignal documentation.
8. Common Error Codes
   HTTP status Meaning Typical fix
   400 Bad request / invalid parameter Verify path and query string
   401 Invalid or missing apikey Check header spelling and key
   402 Insufficient credits Top‑up credits or lower request volume
   404 Record not found Ensure correct ID or URL
   409 Duplicate request in progress Wait for existing job to finish
   429 Rate‑limit exceeded Throttle requests to the allowed rate
   5xx Server error Retry with exponential back‑off
   The official Response Codes page groups these error payloads; the table above summarises the relevant excerpts (CoreSignal docs).
9. Best‑Practice Tips
   • Batch your searches – use the DSL endpoint to retrieve IDs, then pipe them into /collect/\* calls in parallel (up to 54 requests per second).
   • Cache enrich results – a given domain rarely changes; store responses to save credits and stay within rate limits.
   • Graceful throttling – monitor X‑Credits‑Remaining and HTTP 429 responses; implement retries with back‑off to avoid hard failures.
   • Filter early – apply precise filters in the DSL query to minimise the number of costly collect/enrich calls.
10. Reference Pages
    Refer to the CoreSignal documentation for additional details:
    • Clean Company API overview and endpoints
    • Enrich endpoint usage guide
    • Sample Clean Company JSON payload
    • Credits & Tokens guide
    • Rate Limits table

---
