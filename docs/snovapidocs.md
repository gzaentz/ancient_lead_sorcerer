# Snov.io API Overview

> **Last reviewed:** 20 Aug 2025
> **Docs source:** <https://snov.io/api>

---

## 1. Quick Facts

| Item            | Detail                                                                                                                                                       |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Base URL**    | `https://api.snov.io/v1/` _(OAuth + v1 endpoints)_, `https://api.snov.io/v2/` _(most newer feature endpoints)_                                               |
| **Auth**        | OAuth 2 **Client Credentials** — exchange `client_id` & `client_secret` once per hour for a **Bearer** token via `POST /v1/oauth/access_token`               |
| **Rate limit**  | **60 requests / minute** per account (throttling kicks in at 429)                                                                                            |
| **Quota model** | Most calls consume **credits**. Typical cost is **1 credit per unique request** plus **1 credit per prospect email returned** (see §4). Bulk options differ. |
| **Docs**        | <https://snov.io/api>                                                                                                                                        |

---

## 2. Authentication Flow

```text
POST  https://api.snov.io/v1/oauth/access_token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=<ID>&client_secret=<SECRET>
Returns JSON:

json
Copy
Edit
{
  "access_token": "<token>",
  "token_type": "Bearer",
  "expires_in": 3600
}
Include the token in every request header

http
Copy
Edit
Authorization: Bearer <access_token>
Cache the token for ~55 min to avoid extra auth calls.

3. Major Feature Groups & Endpoints
<details> <summary><strong>Email Finder</strong></summary>
Endpoint	Method	Purpose	Credit cost
/v2/domain-search/start	POST	Get company info by domain	1 / request
/v2/domain-search/result/{task_hash}	GET	Retrieve company-info task results	–
/v2/domain-search/prospects/start	POST	Find prospect profiles for a domain (filter by positions[] if needed)	1 / request
/v2/domain-search/prospects/result/{task_hash}	GET	Prospect list (≤ 20 per page)	–
/v2/domain-search/prospects/search-emails/start/{prospect_hash}	POST	Look up a prospect’s email	1 / prospect w/ email returned
/v2/domain-search/domain-emails/start	POST	List all emails on a domain	1 / request
/v2/domain-search/generic-contacts/start	POST	Find generic (info@, sales@) emails	1 / request

Bulk Domain Search – Emails-Only: special batch endpoint (outside normal flow) costs 2 credits per domain.

</details> <details> <summary><strong>Email Verification</strong></summary>
POST /v2/email-verification/start – Verify up to 10 emails at once. Optional webhook_url for async delivery. Returns task_hash for polling.

GET /v2/email-verification/result?task_hash=… – Poll if no webhook.

</details> <details> <summary><strong>Data Enrichment</strong></summary>
Endpoint	Flow (start → result)	Purpose
`/v2/company-domain-by-name/{start	result}`	POST …/start → GET …/result
`/v2/li-profiles-by-urls/{start	result}`	POST …/start → GET …/result
`/v2/enrich-profile/{start	result}`	POST …/start → GET …/result

</details> <details> <summary><strong>Prospect & List Management <em>(v1 namespace)</em></strong></summary>
Endpoint	Method	Description
/v1/add-prospect-to-list	POST	Add prospect(s) to a list
/v1/get-prospect-with-id	POST	Find prospect by internal ID
/v1/get-prospect-with-email	POST	Find prospect by email
/v1/get-user-lists	GET	List all user lists
/v1/get-prospects-from-list	POST	View prospects in a list
/v1/add-user-list	POST	Create a new list

</details> <details> <summary><strong>Drip-Campaign Analytics <em>(v1)</em></strong></summary>
GET /v1/drip-campaign/analytics – Campaign performance (opens, clicks, replies, etc.)

POST /v1/drip-campaign/change-recipient-status – Update recipient status

POST /v1/do-not-email/add – Add addresses to the global suppression list

</details> <details> <summary><strong>Webhooks</strong></summary>
Endpoint	Method	Description
/v1/webhooks	GET	List all webhooks
/v1/webhooks	POST	Create webhook
/v1/webhooks/{id}	PUT	Enable / disable
/v1/webhooks/{id}	DELETE	Remove webhook

Events: email_verified, prospect_created, campaign_reply, etc.
Retries: up to 5 attempts with exponential back-off if your endpoint returns non-2xx.

</details>
## 4. Credit Consumption Cheat-Sheet

| Action                              | Credits                    |
|-------------------------------------|----------------------------|
| Domain search (company info)        | 1 / unique domain          |
Prospect lookup                       1 / request
Prospect email found                  1 / each email returned
Domain email list                     1 / request
Generic contacts                      1 / request
Email verification                    1 / emails
Bulk Domain Search – Emails-Only      2 / domain

Tip: No credits are deducted if a request returns zero results.

## 5. Error Handling

| HTTP | Meaning                                            |
|------|----------------------------------------------------|
| 400  | Validation / missing params                        |
401  Invalid or expired token
403  Forbidden (feature not available on current plan)
429  Too Many Requests – rate-limit exceeded (see retry_after)
500  Snov.io internal error

Payload example:
6. Best Practices
Cache the OAuth token for ~55 min; refresh proactively.

Throttle at ~50 RPM to stay under the 60 RPM ceiling. Respect retry_after on any 429.

Prefer the Authorization header over query-string tokens.

Supply a webhook_url when offered to avoid polling and receive task completion instantly.

Verify emails before outreach to keep bounce rate < 2 %.

When polling tasks (status: in_progress), back-off 5-15 s between attempts.

7. Changelog Highlights (last 12 mo)
Date	Change
18 Aug 2025	Added v2 Email-Verification batch endpoint (≤ 10 emails)
06 May 2025	Rate limit increased from 40 ➜ 60 RPM
10 Feb 2025	New Data-Enrichment endpoints (company-domain-by-name, LinkedIn enrich)

8. Further Reading
Official API guide – https://snov.io/api

Knowledge-base tutorials – https://snov.io/knowledgebase

SDK examples (PHP) – https://github.com/HelgeSverre/snov-io
```
