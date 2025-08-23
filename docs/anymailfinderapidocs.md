# EmailFinder API Cheatsheet (Anymail Finder)

> **Last reviewed:** 23 Aug 2025  
> **Docs source:** <https://anymailfinder.com/email-finder-api/docs>

---

## 1. Overview

EmailFinder turns names, company details, or LinkedIn profile URLs into **verified, SMTP‑checked email addresses** through real‑time look‑ups. This cheatsheet condenses the key endpoints for quick reference in development.

---

## 2. Base URL & Version

| Item | Value |
| ---- | ----- |
| **Base URL** | `https://api.anymailfinder.com` |
| **Latest version** | `v5.1` (prefixed on all paths) |

---

## 3. Authentication

Add an `Authorization` header with your API key for every request:

```http
Authorization: YOUR_API_KEY
```

Keep keys server‑side; rotate if exposed.

---

## 4. Pricing & Credits

| Endpoint | Credits billed<sup>†</sup> | Free cases |
| -------- | -------------------------- | ---------- |
| **Find Person** | **1** | `risky`, `blacklisted`, `not_found` |
| **Decision‑maker** | **2** | same as above |
| **LinkedIn URL** | **2** | same as above |

<sup>†</sup>Credits are charged **only when a *valid* email is returned**. Repeated searches within 30 days are free.

---

## 5. Rate & Timeout Guidance

| Endpoint | Recommended rate | Timeout |
| -------- | ---------------- | ------- |
| Person | unlimited (auto‑scales) | 180 s |
| Decision‑maker | unlimited (auto‑scales) | 180 s |
| LinkedIn URL | ≤ 6 req / min | 180 s |

---

## 6. Endpoints Summary

| Purpose | Method & Path | Required JSON Body | Optional Extras |
| ------- | ------------- | ------------------ | --------------- |
| **Find Person Email** | `POST /v5.1/find-email/person` | `domain` *or* `company_name`, **and** (`full_name` *or* `first_name`+`last_name`) | — |
| **Find Decision‑Maker Email** | `POST /v5.1/find-email/decision-maker` | `decision_maker_category`, plus `domain` *or* `company_name` | `x-webhook-url` header |
| **Find Email by LinkedIn URL** | `POST /v5.1/find-email/linkedin-url` | `linkedin_url` | `x-webhook-url` header |

### 6.1 Decision‑maker Categories

`ceo`, `engineering`, `finance`, `hr`, `it`, `logistics`, `marketing`, `operations`, `buyer`, `sales`

---

## 7. Common Headers

| Header | Use |
| ------ | --- |
| `Authorization` | API key |
| `Content-Type` | `application/json` |
| `x-webhook-url` | Async callback (optional) |

---

## 8. Sample Requests

```bash
# Find a specific person
curl -X POST "https://api.anymailfinder.com/v5.1/find-email/person" \
  -H "Authorization: $AMF_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"domain":"microsoft.com","full_name":"John Doe"}'
```

```bash
# Find the CEO's email
curl -X POST "https://api.anymailfinder.com/v5.1/find-email/decision-maker" \
  -H "Authorization: $AMF_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"domain":"microsoft.com","decision_maker_category":"ceo"}'
```

```bash
# Find email from LinkedIn profile
curl -X POST "https://api.anymailfinder.com/v5.1/find-email/linkedin-url" \
  -H "Authorization: $AMF_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"linkedin_url":"https://www.linkedin.com/in/satyanadella/"}'
```

---

## 9. Response Schema (all endpoints)

```jsonc
{
  "email": "john.doe@microsoft.com",   // null if not found
  "email_status": "valid",             // valid | risky | not_found | blacklisted

  // Person / Decision‑maker only
  "person_full_name": "John Doe",
  "person_job_title": "Senior Engineer",
  "person_linkedin_url": "https://www.linkedin.com/in/johndoe/",

  // LinkedIn URL endpoint only
  "person_company_name": "Microsoft",

  /* Original request body is echoed back under "input" */
}
```

---

## 10. Error Codes

| Code | Meaning |
| ---- | ------- |
| **200** | Success |
| **400** | Bad request (missing / invalid parameters) |
| **401** | Unauthorized (invalid or missing API key) |
| **402** | Payment needed (no remaining credits) |

---

*Happy querying!* 🚀
