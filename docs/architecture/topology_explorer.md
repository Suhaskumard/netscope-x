# Interactive Topology Explorer with Time-Travel (Phase 97)

`frontend/src/` (React + TypeScript + cytoscape) scrubs a capture's topology through its recorded snapshots (Phase 44-49
machinery). Run: `uvicorn backend.app.main:app` and `cd frontend && npm run dev` (Vite proxies `/api` to `127.0.0.1:8000`,
override with `NETSCOPE_API_TARGET`), open `http://localhost:5173/?capture=<id>` (optional `&token=` / `&tenant=`).

## Backend additions (read-only, tenant-scoped, listed in docs/API.md)
`GET /api/v1/history/snapshots` and `GET /api/v1/history/snapshots/{version}/topology`: the graph is read back from the
persisted snapshot file, never recomputed, so the view shows what was recorded. The SDKs gained `snapshots` / `snapshotTopology`.

## UI
A slider with one tick per snapshot placed by `captured_at`, earlier/later/play, and the snapshot id/version/time. Selecting a
tick fetches that snapshot's persisted graph. Changes vs the previous snapshot are overlaid (green added, red dashed removed,
amber confidence changed) with the recorded `GraphChangeEvent`s (from `/history`) listed; clicking a node/edge shows its
confidence, protocols, observation times and evidence. Node/edge counts are printed on the page. Node positions are derived from
the node key, so a host stays in place across snapshots.

## Verified in a real Chrome (`scripts/verify_explorer_in_chrome.mjs`, Chrome DevTools Protocol)
Seeded capture (`scripts/seed_time_travel_demo.py`: real pcap, real `create_snapshot` x4). Expected node/edge sets and
confidences were read from the persisted graph files, independent of the API and UI. Chrome (headless, real rendering) visited
v4, v1, v3, v2, v1, v4 (going back in time included) and after each selection compared the rendered cytoscape elements:
- 6/6 visits: rendered node set, edge set, on-page counts and edge confidence labels equal the recorded snapshot
  (v1: 2 nodes / 1 edge, v2: 3 / 2, v3: 5 / 4, v4: 5 / 4 with the 10.0.0.1-10.0.0.2 confidence 0.637 -> 0.993).
- Selecting an earlier snapshot fetched `/history/snapshots/{v}/topology` for v1-v4 and no console errors occurred.
- The diff panel reported exactly the recorded change events (e.g. v4: 1 confidence change, `0.637 -> 0.993`).
Screenshots and `summary.json` were written per visit. The Claude-in-Chrome extension was not connected, so this drives Chrome
directly over CDP rather than through that extension.

## Limits
Snapshots are cumulative (`as_of`), so the demo shows additions and a confidence change but no real removal; the removed-ghost
rendering is implemented but not exercised by real data. The layout is hash-based, not force-directed: crowded for large
graphs and edge labels can overlap (seen at 3-5 nodes). Only a 5-node demo was checked; no snapshot creation from the UI;
verified in headless Chrome on Windows only; no automated UI test in CI (the Chrome script needs a running server).
