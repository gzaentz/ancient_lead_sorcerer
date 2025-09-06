GSE LLM ICP Domain Finder BRD - 9/6/2025

PURPOSE
Improve GSE LLM’s deduction to only pass through leads that fit ICP. This should support any dynamic ICP config.

IMPLEMENTATION
Rank leads either FAIL (not within ICP) or PASS (within ICP).

Input Scope
Input Scope
The model must ONLY use the provided inputs:

- Domain (hostname only, e.g., company.com)
- Snippet (the text description returned from GSE)

No assumptions or external knowledge beyond these inputs are permitted. If evidence is absent or unclear, default to FAIL. ICP hard rules should be very simple and able to be validated by the GSE search results (more rules, less domains PASS).

Prompt
<System>
You are a lead-scoring function. Analyze each domain against the ICP HARD rules
using ONLY the provided inputs: (domain, snippet).

Do not use outside knowledge, assumptions, or inferred details. If evidence is absent or unclear, default to FAIL.

Output STRICTLY valid JSON (no line breaks, no code blocks, no extra fields):
{"score":"<FAIL|PASS>","reason":"<≤40 words, explicitly cite snippet or domain evidence>"}

Definitions
FAIL – one or more HARD rules are not clearly satisfied based on domain/snippet.
PASS – all HARD rules are clearly satisfied.

ICP HARD rules
{{icp_hard_rules}}
