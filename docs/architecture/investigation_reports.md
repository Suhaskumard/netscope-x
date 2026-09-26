# Automated Investigation Reports (Phase 100)

`POST /api/v1/investigation/report {capture_id, dependency_id, failed_node_id?}` (`backend/nlq/report.py`) writes a cited
investigation report for one dependency from real evidence only. Same Section 23 pattern as Phase 98: code builds the facts,
an LLM may only draft prose over them, code verifies the prose.

## Pipeline
1. **Facts (code).** Numbered `Fact`s, each with a `source` path and the real value it was built from: the dependency
   (strength), the Phase 99 per-signal contributions, the Phase 56 evidence report (relationship, each evidence, counter-evidence
   and limitation line), and, when `failed_node_id` is given, the real Phase 61 pipeline (connectivity, newly unreachable nodes,
   route changes, service impacts, causal propagation impacts) and Phase 62 indicators. Verbatim report text keeps its words;
   only sentence punctuation is normalized so one fact is one cited sentence.
2. **Template report (code).** Deterministic sections (Finding, Signal breakdown, Impact, Counter-evidence, Limitations), one
   cited fact per line. This is a complete report and is returned when no LLM is configured (`source: "template"`).
3. **Optional LLM draft.** Prose that must cite `[F#]` on every sentence. The Phase 98 verifier checks each sentence: cited
   facts exist; every number, node/edge id, IP and identifier appears in the cited facts; no number words except those quoted in
   a cited fact; no causal or certainty wording without a cited causal-propagation fact. Any violation discards the draft and
   returns the template (`violations` lists why). A verified draft (`source: "llm"`) still gets the evidence report's limitations
   and a correlational caveat appended **by code**, so the model cannot drop them.
4. **Response** includes `citations[]` (`fact_id`, `source`, `value`, `text`) so a reader can trace each sentence to a value.

## Verified (tests with a scripted LLM; no key, no network)
- On a real seeded capture, with and without a failed node: every citation's `source` was re-resolved by an independent
  recomputation that does not use `report.py` (`estimate_dependency_strength`, `build_dependency_evidence_report`, a Shapley average
  over all 120 orderings, the failure pipeline and resilience indicators) and equals the cited value to 1e-12 (strings equal
  verbatim); the value shows in the cited text.
- The template report passes the same sentence verifier; a faithful draft is accepted; drafts with an invented number, invented
  IP/id, uncited sentence, unknown fact id, causal claim, or a number word all fall back to the template; limitations and the
  caveat are always present; an LLM error gives the template, not an error; the route returns 404 for an unknown dependency or
  node and 422 for a bad capture id.
- `python -m scripts.run_report_check` prints a full report and its citation table from a real capture.
- **NOT verified: real-LLM drafts.** No API key here. `run_report_check` runs the real model per dependency when
  `ANTHROPIC_API_KEY` is set and counts verified vs fallback drafts; without a key that half prints NOT RUN.

## Limits
The verifier is lexical: it cannot judge a misleading arrangement of true cited words, and it is strict, so a real model may
fall back to the template often. One dependency per report; no persistence or UI; the report inherits the evidence report's
correlational limits (the `Counter-evidence` and `Limitations` sections are always shown).
