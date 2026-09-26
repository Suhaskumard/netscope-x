// Drives the JS SDK against a RUNNING server and prints one JSON object of results (used by the Python harness).
// env: NS_BASE, NS_PCAP (filename in the server's staging dir), NS_TOKEN?, NS_TENANT_KEY?, NS_CAPTURE_ID? (attach to an existing capture)
import {
  NetscopeClient, NotFoundError, NotImplementedOnServer, ValidationError, AuthenticationError, AuthorizationError,
} from "./index.js";

const client = new NetscopeClient(process.env.NS_BASE, {
  token: process.env.NS_TOKEN || undefined,
  tenantKey: process.env.NS_TENANT_KEY || undefined,
});
const out = {};
const kind = async (fn) => {
  try { await fn(); return "ok"; } catch (e) { return e.constructor.name + ":" + e.status + ":" + e.error; }
};

let captureId = process.env.NS_CAPTURE_ID;
if (!captureId) {
  const acc = await client.uploadPcap(process.env.NS_PCAP);
  captureId = acc.capture_id;
  out.accepted = acc;
}
out.captureId = captureId;
out.flows = await client.flows(captureId);
out.flowsAll = [];
for await (const f of client.paginate("flows", captureId)) out.flowsAll.push(f.flow_id);
out.topology = await client.topology(captureId);
out.dependencies = await client.dependencies(captureId);
if (out.dependencies.items.length) {
  out.causal = await client.causal(out.dependencies.items[0].dependency_id, captureId);
}
out.history = await client.history(captureId, "2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z");
out.experiments = await client.experiments();
out.metrics = await client.metrics();
out.errors = {
  notFound: await kind(() => client.flows("no_such_capture")),
  validation: await kind(() => client.flows("../bad")),
  notImplemented: await kind(() => client.anomalies()),
  causalMissing: await kind(() => client.causal("nope", captureId)),
};
console.log(JSON.stringify(out));
