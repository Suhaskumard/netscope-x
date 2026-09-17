"""Phase 06 placeholder FastAPI app.

Exists only to give the backend Docker image something real to run and
prove the container works end-to-end. The actual API surface (/capture,
/flows, /topology, ...) is designed and built in Phase 09 -- this file
will be replaced, not extended in place, when that phase starts.
"""

from fastapi import FastAPI

app = FastAPI(title="NETSCOPE-X (Phase 06 placeholder)")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
