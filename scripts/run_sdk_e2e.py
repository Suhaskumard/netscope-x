"""Real end-to-end check of the Python and JavaScript SDKs (spec Phase 96).

    python -m scripts.run_sdk_e2e

Starts a real uvicorn server (temp artifact root), then drives both SDKs over real HTTP through the full request/response
cycle, comparing with raw httpx and with the backend functions; then repeats with authentication and tenancy enabled.
Needs `node` (>= 18) for the JavaScript half. Exit code 1 if any check fails.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from sdk.e2e import run_all


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        report = run_all(Path(tmp))
    print(report.format())
    return 0 if report.passed == len(report.checks) else 1


if __name__ == "__main__":
    sys.exit(main())
