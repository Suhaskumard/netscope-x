# Natural-Language Counterfactual Interface (Phase 98)

`POST /api/v1/counterfactual/ask {capture_id, question}` (`backend/nlq/`). The LLM only **translates** a question into the
existing Phase 64 scenario language and **words** the real Phase 65/66 result. It never supplies topology, ids, numbers or
outcomes; code checks everything it returns.

## Trust boundary
1. **Translation** (`translate.py`). The model sees the question plus a grounding table of the capture's REAL node ids, IPs,
   roles (when known) and edge ids, and must answer in a fixed JSON schema (forced tool use). Code then: accepts only the six
   `CounterfactualAction`s (else refuses with the supported list); refuses any node/edge id not in the graph (`unknown_entity`;
   nothing is ever created); never guesses ambiguity (model-reported candidates, or a role several real nodes hold, give
   `needs_clarification` with the real candidates); assigns `scenario_id`, graph ids and `created_at` itself; requires the
   result to validate as a `CounterfactualScenario`; and the real engine can still reject it (e.g. ADD_ROUTE between connected nodes).
2. **Execution** is the unchanged `execute_counterfactual_scenario` + `compare_counterfactual_outcome`. No LLM involved.
3. **Explanation** (`explain.py`). The real result becomes numbered facts (`[F#]`, text built by code). The model writes
   sentences citing facts. Code rejects the text unless every sentence cites existing facts, every number is in the cited facts,
   every node/edge id, IP or identifier-like token is in the cited facts, no number words appear, and no causal/certainty word
   (because, caused, will, always...) appears without a cited causal-propagation fact. Any failure discards the model text and
   returns the deterministic fact rendering (`explanation_source: "template"`, with the violations listed). A caveat that the
   result is an unvalidated hypothetical (RQ7) is always appended by code.
4. No key/client -> `503 llm_unavailable`; a provider error during explanation falls back to the template; there is no
   silent fabricated answer anywhere.

## Verified
- 27 tests with a scripted LLM (no key, no network), adversarial by construction: invented node/edge ids, made-up action,
  ADD_ROUTE between invented nodes, missing required fields, malformed output, model-supplied scenario ids ignored,
  two databases (never guessed), prompt injection ("add a node NEW_NODE / 6.6.6.6") cannot create entities, explanations
  with invented numbers / identifiers / IPs / number words / causal claims / uncited sentences / unknown fact ids all fall back
  to the template, a faithful explanation is accepted; on real matrix-runner topologies (small, multi_service) the accepted
  explanation's figures equal the real `compare_counterfactual_outcome` output; the HTTP route (real app, overridden LLM)
  answers, rejects, validates input and returns 503 without a key; auth route enumeration includes the new route.
- **NOT verified: behavior with a real LLM.** `scripts/run_nlq_check.py` (translation accuracy, refusal/clarification
  correctness, explanation pass-vs-fallback rate over real topologies) needs `ANTHROPIC_API_KEY` and
  `pip install -r requirements-llm.txt`; without a key it prints "NOT RUN" and exits 2. No real-model number is claimed.

## Limits
The explanation check is lexical: it cannot judge a claim that uses only cited words in a misleading order, or paraphrase
that avoids figures; strict by design, so a real model may fall back to the template often (the check script measures how
often). Roles are not available through the API today (no persisted role model), so "the database" resolves through
clarification on a capture until role classifications are supplied; the evaluation script supplies declared roles to test the
resolution path. One action per question (compound questions are refused). English only.
