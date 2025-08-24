# Apollo API Cheat Sheet

> **Last reviewed:** 23 Aug 2025  
> **Docs source:** Apollo Developer Hub (docs.apollo.io)

---

## 1. Quick Facts

| Item | Detail |
| --- | --- |
| **Base URL** | `https://api.apollo.io/api/v1/` |
| **Auth** | **X‑Api‑Key** header for API keys *(all customers)* · **OAuth 2 (Client Credentials)** for partners *(build integrations on behalf of users)* |
| **Rate Limits** | Vary by plan & endpoint; check via **POST `/usage_stats/api_usage_stats`**. Example default ≈ 200 req/min window. Bulk enrichment endpoints run at **50 %** of the single‑record per‑minute limit. |
| **Credit Model** | People Search, Enrichment, Phone & LinkedIn retrieval all **consume credits**; creating Contacts is free. |
| **Reference Docs** | <https://docs.apollo.io/reference> |

---

## 2. Authentication

```http
# Include your key on every call
X-Api-Key: YOUR_API_KEY
Content-Type: application/json
Cache-Control: no-cache
Accept: application/json
```

Partner integrations should implement the OAuth 2 authorization flow to obtain a Bearer token on behalf of mutual users.

---

## 3. Core Endpoints

| Area | Method & Path | Purpose / Notes |
| --- | --- | --- |
| **People Search** | `POST /mixed_people/search` | Find prospects by filters such as `person_titles[]`, `person_seniorities[]`, `person_locations[]`, `q_organization_domains_list[]`, etc. Max 50 000 results (100 per page × 500 pages). |
| **People Enrichment** | `POST /people/match` | Enrich a single person (up to 10 via Bulk). Provide `email` **or** `first_name`+`last_name`+`organization_domain`. Optional:<br>`reveal_personal_emails`, `reveal_phone_number`, `webhook_url`. |
| **Bulk People Enrichment** | `POST /people/bulk_match` | Enrich up to 10 people per call. Same params as single. Rate‑limited to 50 % of single endpoint per‑minute limit. |
| **Retrieve Mobile Phones** | *same as* People Enrichment with `reveal_phone_number=true` **and** a valid `webhook_url`. Webhook delivers phone array several minutes later. |
| **Retrieve LinkedIn Profiles** | Use **People Search**; response contains `linkedin_url` for each record. |
| **Convert to Contact** | `POST /contacts` | Persist enriched person in your Apollo account so future look‑ups do **not** re‑consume credits. Key fields include `first_name`, `last_name`, `organization_name`, `email`, `website_url`, `direct_phone`, `mobile_phone`. |
| **Usage & Rate Stats** | `POST /usage_stats/api_usage_stats` | Returns per‑endpoint limits & consumption. *Requires a master API key*. |

---

## 4. Example cURL Snippets

### 4.1 Search for West Coast Sales Directors

```bash
curl -X POST \
  'https://api.apollo.io/api/v1/mixed_people/search?person_titles[]=sales%20director&person_titles[]=director%20sales&person_locations[]=California%2C%20US&person_locations[]=Oregon%2C%20US&person_locations[]=Washington%2C%20US&per_page=5' \
  -H 'X-Api-Key: $APOLLO_KEY' -H 'Content-Type: application/json'
```

### 4.2 Enrich a Person by Email

```bash
curl -X POST \
  'https://api.apollo.io/api/v1/people/match?email=joshua.garrison%40apollo.io&reveal_personal_emails=false' \
  -H 'X-Api-Key: $APOLLO_KEY' -H 'Content-Type: application/json'
```

### 4.3 Pull Mobile Phones (Webhook)

```bash
curl -X POST \
  'https://api.apollo.io/api/v1/people/match?email=joshua.garrison%40apollo.io&reveal_phone_number=true&webhook_url=https%3A%2F%2Fwebhook.example.com%2Fcb' \
  -H 'X-Api-Key: $APOLLO_KEY' -H 'Content-Type: application/json'
```

### 4.4 Create a Contact

```bash
curl -X POST \
  'https://api.apollo.io/api/v1/contacts?first_name=Mark&last_name=Twain&organization_name=Great%20American%20Writers&email=mtwain%40gaw.com' \
  -H 'X-Api-Key: $APOLLO_KEY' -H 'Content-Type: application/json'
```

---

## 5. Error Handling & Rate Limits

* **HTTP 403** – invalid or non‑master key for endpoints that require master scope.  
* **HTTP 429** – rate limit exceeded (fixed 60‑second window).  
* Retrieve limits programmatically via `/usage_stats/api_usage_stats`.

---

## 6. Useful Links

* API Overview – <https://docs.apollo.io/docs/api-overview>  
* People Search – <https://docs.apollo.io/docs/find-people-using-filters>  
* People Enrichment – <https://docs.apollo.io/docs/enrich-people-data>  
* Mobile Phone Retrieval – <https://docs.apollo.io/docs/retrieve-mobile-phone-numbers-for-contacts>  
* Convert to Contact – <https://docs.apollo.io/docs/convert-enriched-people-to-contacts>  
* LinkedIn Profiles – <https://docs.apollo.io/docs/retrieve-linkedin-profiles-for-prospects>  
* API FAQs – <https://docs.apollo.io/docs/apollo-api-faqs>

---

### Changelog

* **2025‑08‑23** — Initial cheat sheet generated.