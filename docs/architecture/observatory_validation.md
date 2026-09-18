# NETSCOPE-X — Observatory Validation

Phase 20 deliverable, per the master spec (`NETSCOPE (1).pdf`, §"PHASE 20 — OBSERVATORY
VALIDATION"): "Before NETTRACE receives data, verify that the laboratory itself behaves
correctly. Validate: expected connectivity, expected routes, expected services, expected
traffic." Code: `scripts/validate_observatory.py`. Verified by
`simulator/tests/test_observatory_validation.py` (16 pure unit tests) and a real run against the
live Phase 11-15 lab, including a deliberately induced failure to prove the checks can actually
fail, not just always pass.

## Design: automate the manual checks Phases 11-13/15 already performed once

Every one of the four things this phase must validate was already verified once, by hand, and
written up as prose evidence in `docs/architecture/network_laboratory.md` (Phase 11's positive
end-to-end chain, Phase 12's positive+negative boundary enforcement, Phase 13's load-balancer
failover) and `docs/architecture/protocol_generation.md` (Phase 15's per-protocol reachability).
Phase 20 does not redefine what any of those four things mean — it turns the existing manual
procedure into a single repeatable script, reusing existing code wherever it already exists:

| Spec bullet | Check | Reused infrastructure |
|---|---|---|
| Expected services | `check_expected_services` | `simulator.ground_truth.generate.check_services_match_compose` (Phase 16) unchanged, run against the compose file's real service list. |
| Expected connectivity (positive) | `check_positive_connectivity` | `docker compose exec client curl -s http://gateway/`, parsing the same JSON shape `simulator/docker/api/api.py` (Phase 11) already reports. |
| Expected connectivity (negative/boundary) | `check_negative_connectivity` | Re-runs Phase 12's own boundary-enforcement procedure: `client`/`gateway`/`load-balancer` attempting to reach `redis`/`database`/`external-service` directly must fail. |
| Expected routes | `check_expected_routes` | Re-runs Phase 13's `X-Gateway-Upstream` alternation check across several requests. |
| Expected traffic | `check_expected_traffic` | Runs `simulator.traffic.generate_protocol` (Phase 15) for a one-shot smoke attempt per reachability-correct container/protocol pair. |

Because this script is inherently Docker-dependent — it has to actually reach into the live lab's
network namespaces the same way the Phase 12/13 manual verification did — it stays a standalone
script rather than a pytest addition. Exploration confirmed there is no existing precedent in this
project for a Docker-dependent pytest fixture; every Docker-touching check so far has been a
manual CLI run captured as markdown prose. This script keeps that boundary: the *pure*
parsing/decision logic each check reduces to (`_evaluate_reachability_payload`,
`_parse_upstream_header`, `_summarize_protocol_attempt`) is factored out and unit-tested without
Docker; everything that actually shells out to `docker compose exec` stays in the script itself.

Follows the exact same standalone-validator convention already established by
`scripts/validate_data_contracts.py` (Phase 04) and `scripts/check_ground_truth_boundary.py`
(Phase 17): argument-free, `[PASS]`/`[FAIL]` per line, a summary count, `SystemExit(1)` on any
failure.

## Scope

Validates the **fixed Phase 11-13 lab** (`simulator/docker/docker-compose.yml`) — what "the
laboratory" means throughout `docs/architecture/network_laboratory.md`, and the lab Phase 21's
NETTRACE work will actually capture traffic from. Phase 18's independently-deployed generated
scenarios are explicitly out of scope (already scoped that way in `network_laboratory.md`'s
"Explicitly deferred" section) — extending this to arbitrary generated scenarios is not required
by the one-line Phase 20 spec.

## Wiring into the lab

```
docker compose -f simulator/docker/docker-compose.yml up -d
.venv/Scripts/python.exe -m scripts.validate_observatory
```

Run this before starting any Phase 21+ (NETTRACE) work against the lab.

## Verification actually performed this phase

- `pytest simulator/tests/test_observatory_validation.py` — 16/16 passed: reachability-payload
  evaluation (all true / one false / all false / missing field), upstream-header parsing (present,
  case-insensitive, absent, empty string), protocol-attempt summarization (`ok` true/false,
  `status_code` 200/500, `rcode` 0/nonzero, an explicit `error` overriding an otherwise-true `ok`,
  and missing fields). Combined suite: `pytest backend/tests experiments/tests simulator/tests` —
  136/136 passed (up from 120/120 after Phase 19), no regression.
- **Real integration run** against the live lab, all 5 checks:
  ```
  [PASS] expected services: ground-truth role declarations match docker-compose.yml
  [PASS] expected connectivity (positive): client->gateway reachability report:
         {'service': 'api-1', 'redis_reachable': True, 'database_reachable': True, 'external_reachable': True}
  [PASS] expected connectivity (negative/boundary): all 5 out-of-boundary targets correctly unreachable
  [PASS] expected routes: observed 6 requests alternate across upstreams: ['172.18.0.5:80', '172.18.0.6:80']
  [PASS] expected traffic: real traffic generated and answered for:
         ['client/dns', 'client/http', 'api-1/cache', 'api-1/database', 'api-1/tls']

  5 passed, 0 failed, 5 total
  ```
- **Negative-result sanity check** (proving the script can actually detect a real problem, not
  just always print PASS): stopped `load-balancer-2` (`docker compose stop load-balancer-2`) and
  re-ran the script. The routes check still reported `[PASS]`, but with an observably different,
  honestly-captured detail: one upstream value in the alternation list carried nginx's
  failover-trail trailing comma (`'172.18.0.6:80,'`) instead of a clean second address — the same
  real finding Phase 13's own manual verification already documented (nginx's passive health check
  routes the failed peer's traffic to the survivor within the same request rather than the request
  failing outright, so a stopped `load-balancer-2` produces a visibly degraded-but-still-succeeding
  header rather than a hard check failure). This is reported here exactly as observed, not
  smoothed over into an artificial FAIL. `load-balancer-2` was restarted
  (`docker compose start load-balancer-2`) and a follow-up run confirmed full recovery (clean
  alternation, no trailing comma).
- Lab torn down (`docker compose ... down`) after verification.

## Known limitations

- The routes check (`check_expected_routes`) detects *alternation*, not *hard failover as a
  distinguishable state* — as the negative-result sanity check above shows, nginx's own
  `proxy_next_upstream` behavior means a downed load-balancer instance can still produce a
  passing-looking result (a degraded-but-successful header) rather than a clean fail signal. This
  is an honest reflection of Phase 13's own finding, not a defect introduced this phase — a
  stronger check would need to independently confirm both upstream containers are actually
  running (e.g. via `docker compose ps`) rather than relying solely on header alternation.
- `check_expected_traffic`'s smoke checks use `count=1` — enough to prove the lab can still
  genuinely generate and answer traffic right now, not a statistically meaningful sample; that
  remains Phase 14/15's own generators' job, already verified at larger sample sizes in their own
  phases.
- This script assumes the fixed Phase 11-13 lab topology (specific container/service names,
  specific negative-check target list); it is not a generic validator for arbitrary compose
  topologies or Phase 18 generated scenarios (explicitly out of scope, see "Scope" above).

## Status

This document, together with `scripts/validate_observatory.py` and
`simulator/tests/test_observatory_validation.py`, satisfies Phase 20: the lab's expected services,
connectivity (positive and negative), routes, and traffic-generation capability are all verified
by a single repeatable, automated gate — with both a full-pass real run and a real induced-failure
run demonstrating the gate can actually fail, not just always report success.
