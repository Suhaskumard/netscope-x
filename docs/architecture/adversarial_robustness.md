# Adversarial Robustness Evaluation (Phase 84)

Spec (master spec addendum, Arc B): build a red-team suite of crafted traffic against topology inference, role
classification and anomaly detection; measure real degradation; harden the affected stage; re-measure; document
every successful case, including ones not yet fixed.

**Verdict: 6 of 8 crafted attacks succeed against the unhardened pipeline. Hardening fixes 3 cleanly, fixes 2 only
by making the classifier abstain, and leaves 2 topology attacks open. Nothing hardened is on by default.**
Code: `experiments/adversarial/{attacks,benchmark}.py`, CLI `scripts/run_adversarial_benchmark.py`, tests
`experiments/tests/test_adversarial.py`.

## Protocol
- Attacks are packet-level transforms of real synthetic traffic run through the unmodified pipeline. Each states the
  attacker capability: forged (inject packets) or compromised host (controls a real node).
- 5 topologies (small, medium, large, multi_path, dynamic) x seeds 42-44 = up to 15 units per attack; each unit is
  scored clean, attacked, clean+hardened, attacked+hardened (456 scored cells).
- Rule fixed before the run: an attack SUCCEEDS if clean minus attacked exceeds the clean metric's across-unit
  standard deviation; a fix WORKS if it recovers more than that; a fix is ACCEPTED only if clean+hardened stays within
  it of clean. Role attacks target a node the default classifier gets right on clean traffic (chosen on clean traffic).
- Hardening is opt-in with defaults that reproduce old behavior (tested bit-identical): `min_edge_bidirectionality`
  (0.15) in `build_topology_graph`; `classify_node_role_robust` (abstain when a feature is > 4 scale units from every
  role); `build_anchored_baseline` (oldest 5 epochs) and `detect_sustained_drift` (3 rising epochs, each >= 1.5 MADs).

## Results
| attack | capability | metric | clean | attacked | hardened clean | hardened attacked | outcome |
|---|---|---|---|---|---|---|---|
| spoofed_sources | forged | node F1 | 1.000 | 0.708 | 1.000 | 1.000 | fixed |
| decoy_chatter | compromised host | edge F1 | 1.000 | 0.850 | 1.000 | 0.850 | **open** |
| ip_aliasing | compromised host | node F1 | 1.000 | 0.708 | 1.000 | 0.708 | **open** |
| role_mimicry | compromised host | not confidently wrong | 1.000 | 0.500 | 1.000 | 0.833 | mitigated by abstention |
| fingerprint_noise | compromised host | not confidently wrong | 1.000 | 0.917 | 1.000 | 1.000 | see caveat |
| low_and_slow | compromised host | recall | 1.000 | 1.000 | 1.000 | 1.000 | not successful on recall |
| baseline_poisoning | compromised host | recall | 1.000 | 0.235 | 1.000 | 0.897 | fixed (partly) |
| minimal_burst | compromised host | recall | 1.000 | 1.000 | 1.000 | 1.000 | not successful |

## Caveats, stated rather than hidden
- **Role "fix" is abstention, not correctness.** Under attack, the hardened classifier is right 0% of the time and
  abstains 83% (mimicry) and 100% (noise); the default was right 50% and 92%. "Not confidently wrong" rises, but a
  defender gets no role at all. For fingerprint_noise the default lost only 0.083 and hardening removes every answer, so
  that is not clearly an improvement. 17% of mimicry cases still fool even the hardened classifier into the imitated role.
- **Clean spread is 0** on every primary metric (the clean synthetic traffic is deterministic per seed), so the success
  rule reduces to "any drop". Effect sizes above are the real information.
- **Low-and-slow is not an evasion of recall but of latency and noise:** detection latency rises from 51 s to 88 s and
  false positives double (11.5 to 22.1); `detect_sustained_drift` does not reduce either (86 s, 29.4). It is not fixed.
- **False alarms are high everywhere:** 11-15 per unit on clean traffic; hardening raises this a little (11.5 to 14.5,
  anchored baseline). Detection here is sensitive, which is also why minimal_burst (one new peer, 2 packets) is caught.
- Open: decoy_chatter (real two-way conversations between undeclared pairs are indistinguishable from real edges) and
  ip_aliasing (one node appears as three). Neither has a fix in this phase; both need evidence outside packets.
- Provisional hardening parameters (0.15, 4.0, 5 epochs, 3 epochs, 1.5 MADs) were not tuned on held-out seeds. One run.
