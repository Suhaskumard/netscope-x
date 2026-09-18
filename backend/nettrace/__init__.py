"""NETTRACE -- capture, flow reconstruction, and topology inference (spec Phase 21+).

This is the first pipeline module populated (starting Phase 21, packet
capture). Like every other pipeline module, it imports shared schemas from
`backend.app.models` (Phase 04) but never imports `simulator.ground_truth`
directly -- inference must never see ground truth, enforced structurally by
`scripts/check_ground_truth_boundary.py` (Phase 17).
"""
