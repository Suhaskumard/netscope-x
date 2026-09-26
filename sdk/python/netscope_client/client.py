"""Blocking client for the NETSCOPE-X REST API. Responses are plain dicts/lists as the server returns them."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterator, Optional

API_PREFIX = "/api/v1"
_RETRY_STATUS = {502, 503, 504}


class NetscopeError(Exception):
    """Any non-2xx reply. `error`/`detail`/`request_id` are the server's ErrorResponse fields."""

    def __init__(self, status: int, error: str, detail: Any, request_id: Optional[str]) -> None:
        super().__init__(f"{status} {error}: {detail} (request_id={request_id})")
        self.status, self.error, self.detail, self.request_id = status, error, detail, request_id


class ValidationError(NetscopeError):
    """422"""


class AuthenticationError(NetscopeError):
    """401"""


class AuthorizationError(NetscopeError):
    """403"""


class NotFoundError(NetscopeError):
    """404"""


class NotImplementedOnServer(NetscopeError):
    """501: the route validates input but its backend stage is not wired in."""


class ServerError(NetscopeError):
    """5xx and any other non-2xx status."""


_BY_STATUS = {422: ValidationError, 401: AuthenticationError, 403: AuthorizationError, 404: NotFoundError,
              501: NotImplementedOnServer}


def _json_default(o: Any) -> str:
    return o.isoformat() if hasattr(o, "isoformat") else str(o)


class NetscopeClient:
    def __init__(self, base_url: str, token: Optional[str] = None, tenant_key: Optional[str] = None,
                 timeout: float = 30.0, retries: int = 2, backoff: float = 0.2) -> None:
        self.base_url = base_url.rstrip("/")
        self.token, self.tenant_key = token, tenant_key
        self.timeout, self.retries, self.backoff = timeout, retries, backoff

    # -- transport ---------------------------------------------------------------------------------------
    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, body: Any = None) -> Any:
        url = self.base_url + API_PREFIX + path
        if params:
            q = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in params.items() if v is not None}
            if q:
                url += "?" + urllib.parse.urlencode(q)
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.tenant_key:
            headers["X-Tenant-Key"] = self.tenant_key
        data = None
        if body is not None:
            data = json.dumps(body, default=_json_default).encode()
            headers["Content-Type"] = "application/json"
        attempts = 1 + (self.retries if method == "GET" else 0)  # only idempotent reads are retried
        for attempt in range(attempts):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as exc:
                if exc.code in _RETRY_STATUS and attempt < attempts - 1:
                    time.sleep(self.backoff * 2 ** attempt)
                    continue
                raise self._error(exc) from None
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                if attempt < attempts - 1:
                    time.sleep(self.backoff * 2 ** attempt)
                    continue
                raise
        raise AssertionError("unreachable")

    @staticmethod
    def _error(exc: urllib.error.HTTPError) -> NetscopeError:
        try:
            body = json.loads(exc.read())
        except Exception:  # noqa: BLE001 - non-JSON error body
            body = {}
        if not isinstance(body, dict):
            body = {}
        cls = _BY_STATUS.get(exc.code, ServerError)
        return cls(exc.code, body.get("error", "http_error"), body.get("detail", exc.reason), body.get("request_id"))

    # -- capture -----------------------------------------------------------------------------------------
    def capture(self, source: str, *, pcap_filename: Optional[str] = None, interface: Optional[str] = None,
                flow_filename: Optional[str] = None, flow_format: Optional[str] = None) -> dict:
        body = {"source": source, "pcap_filename": pcap_filename, "interface": interface,
                "flow_filename": flow_filename, "flow_format": flow_format}
        return self._request("POST", "/capture", body={k: v for k, v in body.items() if v is not None})

    def upload_pcap(self, pcap_filename: str) -> dict:
        return self.capture("pcap_upload", pcap_filename=pcap_filename)

    def upload_netflow(self, flow_filename: str, flow_format: str) -> dict:
        return self.capture("netflow_upload", flow_filename=flow_filename, flow_format=flow_format)

    # -- reads -------------------------------------------------------------------------------------------
    def flows(self, capture_id: str, limit: int = 50, offset: int = 0) -> dict:
        return self._request("GET", "/flows", {"capture_id": capture_id, "limit": limit, "offset": offset})

    def topology(self, capture_id: str) -> dict:
        return self._request("GET", "/topology", {"capture_id": capture_id})

    def dependencies(self, capture_id: str, limit: int = 50, offset: int = 0) -> dict:
        return self._request("GET", "/dependencies", {"capture_id": capture_id, "limit": limit, "offset": offset})

    def causal(self, dependency_id: str, capture_id: str) -> dict:
        return self._request("GET", f"/causal/{urllib.parse.quote(dependency_id, safe='')}", {"capture_id": capture_id})

    def attribution(self, dependency_id: str, capture_id: str) -> dict:
        """Per-signal Shapley breakdown of a dependency's strength (Phase 99); contributions sum to `strength`."""
        return self._request("GET", f"/causal/{urllib.parse.quote(dependency_id, safe='')}/attribution", {"capture_id": capture_id})

    def history(self, capture_id: str, start: Any, end: Any, limit: int = 50, offset: int = 0) -> dict:
        return self._request("GET", "/history", {"capture_id": capture_id, "start": start, "end": end,
                                                 "limit": limit, "offset": offset})

    def snapshots(self, capture_id: str, limit: int = 50, offset: int = 0) -> dict:
        return self._request("GET", "/history/snapshots", {"capture_id": capture_id, "limit": limit, "offset": offset})

    def snapshot_topology(self, capture_id: str, version: int) -> dict:
        return self._request("GET", f"/history/snapshots/{int(version)}/topology", {"capture_id": capture_id})

    def experiments(self, limit: int = 50, offset: int = 0) -> dict:
        return self._request("GET", "/experiments", {"limit": limit, "offset": offset})

    def metrics(self, context: Optional[str] = None, limit: int = 50, offset: int = 0) -> dict:
        return self._request("GET", "/metrics", {"context": context, "limit": limit, "offset": offset})

    def anomalies(self, node_id: Optional[str] = None, limit: int = 50, offset: int = 0) -> dict:
        return self._request("GET", "/anomalies", {"node_id": node_id, "limit": limit, "offset": offset})

    def behavior(self, node_id: str) -> dict:
        return self._request("GET", f"/behaviors/{urllib.parse.quote(node_id, safe='')}")

    # -- writes ------------------------------------------------------------------------------------------
    def simulate(self, scenario: dict) -> dict:
        return self._request("POST", "/simulation", body=scenario)

    def counterfactual(self, scenario: dict) -> dict:
        return self._request("POST", "/counterfactual", body=scenario)

    def ask_counterfactual(self, capture_id: str, question: str) -> dict:
        """Natural-language what-if (Phase 98). 503 `llm_unavailable` (ServerError) when the server has no LLM key."""
        return self._request("POST", "/counterfactual/ask", body={"capture_id": capture_id, "question": question})

    def investigation_report(self, capture_id: str, dependency_id: str, failed_node_id: str = None) -> dict:
        """Cited investigation report (Phase 100). `source` is "llm" (verified draft) or "template" (deterministic)."""
        body = {"capture_id": capture_id, "dependency_id": dependency_id}
        if failed_node_id is not None:
            body["failed_node_id"] = failed_node_id
        return self._request("POST", "/investigation/report", body=body)

    def create_experiment(self, experiment: dict) -> dict:
        return self._request("POST", "/experiments", body=experiment)

    # -- helpers -----------------------------------------------------------------------------------------
    def paginate(self, method: str, *args: Any, page_size: int = 100, **kwargs: Any) -> Iterator[Any]:
        """Yields every item of a paginated list method (`flows`, `dependencies`, `history`, `experiments`, ...)."""
        fn = getattr(self, method)
        offset = 0
        while True:
            page = fn(*args, limit=page_size, offset=offset, **kwargs)
            yield from page["items"]
            offset += len(page["items"])
            if not page["items"] or offset >= page["total"]:
                return
