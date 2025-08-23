# Company Enrich API Cheatsheet

A concise, developer‑friendly reference that merges the essentials from **Quickstart**, **GET /companies/enrich**, and **POST /companies/enrich/batch** into one file.

---

## Overview
Company Enrich offers REST‑style JSON endpoints that translate a domain (or list of domains) into a rich company profile—size, industry, revenue, HQ location, tech stack, and more.  
All requests are authenticated with a single token, billed **per successfully enriched domain**, and guarded by generous but enforceable rate limits.

*Docs sources: [Quickstart][1] • [Single Enrich][2] • [Batch Enrich][3]*

---

## Base URL & Version

| Item             | Value                                                 |
| ---------------- | ----------------------------------------------------- |
| **Base URL**     | `https://api.companyenrich.com` |
| **Current ver.** | `v1.0` (appears in all path headings) |

---

## Authentication

```text
# example call with correct header spelling
GET /companies/enrich?domain=hubspot.com
Authorization: Basic <YOUR_API_TOKEN>
```

* **Where to get the token?** In your **Dashboard**.  
* **Header spelling matters:** `Authorization`, not the misspelled variant in one doc snippet.  
* **Raw token, no base‑64:** The value after `Basic` is **just the token string**—_not_ `base64(username:password)`.

---

## Quotas & Rate Limits

| Limit           | Value                          |
| --------------- | ------------------------------ |
| **Requests**    | 300 requests / minute (account‑wide) |
| **Credit cost** | 1 credit per enriched domain (single **and** batch) |

---

## Core Endpoints

### 1 · Enrich by Domain (single)

| Property          | Value                                                   |
| ----------------- | ------------------------------------------------------- |
| **Method & Path** | `GET /companies/enrich`                                 |
| **Input**         | `domain` (query‑string)                                 |
| **Cost**          | 1 credit                                                |
| **Typical 404**   | Returned when no match exists for the supplied domain.  |
| **Best Practice** | Prefer single‑domain look‑ups—they’re fastest.          |

```bash
curl -H "Authorization: Basic $TOKEN"      "https://api.companyenrich.com/companies/enrich?domain=hubspot.com"
```

### 2 · Batch Enrich (≤ 50 domains)

| Property          | Value                                               |
| ----------------- | --------------------------------------------------- |
| **Method & Path** | `POST /companies/enrich/batch`                      |
| **Payload**       | JSON object with `domains` array (up to 50 items)   |
| **Cost**          | 1 credit per domain                                 |
| **Why batch?**    | Fewer HTTP round‑trips and friendlier to the rate limiter.|

```json
{
  "domains": [
    "hubspot.com",
    "stripe.com",
    "microsoft.com"
  ]
}
```

```bash
curl -X POST https://api.companyenrich.com/companies/enrich/batch      -H "Authorization: Basic $TOKEN"      -H "Content-Type: application/json"      -d @payload.json
```

---

## Response Anatomy (illustrative)

```jsonc
{
  "companyId": "cmp_123456",
  "name": "HubSpot",
  "domain": "hubspot.com",
  "description": "...",
  "industry": "Software / CRM",
  "size": { "employees": 5800 },
  "revenue": { "annual": 2090000000 },
  "location": {
    "city": "Cambridge",
    "state": "MA",
    "country": "US"
  },
  "foundedYear": 2006,
  "techStack": [ "aws", "react", "snowflake" ],
  "social": {
    "linkedinUrl": "...",
    "twitter": "@HubSpot"
  }
  /* additional keys omitted */
}
```

> **Schema can evolve.** Field names and nested objects may expand over time; code defensively by ignoring unknown keys and validating only the ones you require.

---

## Error Handling

| HTTP Code | Meaning           | Common Cause                       |
| --------- | ----------------- | ---------------------------------- |
| **200**   | OK                | Enrichment data returned           |
| **401**   | Unauthorized      | Missing/invalid token              |
| **404**   | Not found         | Unknown domain                     |
| **429**   | Too many requests | Burst exceeded 300 req/min         |
| **5xx**   | Server error      | Rare; retry with exponential back‑off |

Errors ≥ 400 return a JSON body with `code` and `message` fields.

---

## Practical Tips

1. **Cache results** – domains rarely change; caching saves money and avoids rate limits.  
2. **Batch whenever possible** – up to 50 domains per request gives best throughput.  
3. **Treat 404 gracefully** – log as “unknown company” rather than hard failure.  
4. **Back‑off on 429** – start at 2 s and use exponential retry.  

---

_Last reviewed: **23 Aug 2025**_

[1]: https://docs.companyenrich.com/reference/quickstart "Quickstart"
[2]: https://docs.companyenrich.com/reference/get_companies-enrich "Enrich by domain"
[3]: https://docs.companyenrich.com/reference/post_companies-enrich-batch "Batch enrich by domains"
