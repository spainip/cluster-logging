# Initial deployment validation — 2026-11-05

The active GitRepo is `spainip/cluster-logging`; all three bundles reconcile
through the local cluster mapping. No application/Silo credentials were changed.
The repository is public; credential values were checked absent from the source.

## Configuration and access

- Loki chart 21.0.0 / Loki 3.7.9 and Alloy chart 1.15.0 / Alloy v1.21.3 are
  pinned, including controller image digests. Both configs passed the pinned
  binaries' validation. Helm renders and Kubernetes server dry runs passed.
- Only one Loki StatefulSet and one Alloy DaemonSet are deployed. No public
  ingress, gateway, second object store, Grafana or Prometheus was installed.
- Fleet `helm.disablePreProcess: true` is required for Loki: otherwise Fleet
  interprets `${AWS_ACCESS_KEY_ID}` before Loki can expand it at runtime.
- Alloy's persistent `loki.write` WAL requires `stabilityLevel: experimental` in
  this pinned version. This is a deliberate compatibility setting, not a claim
  that the feature is GA. Other configured components are standard collectors.
- The Alloy chart's broad default RBAC was replaced by one Pod-metadata-only
  ClusterRole. Impersonated authorization: list Pods yes, list Secrets no.
- Silo SigV4/path-style preflight passed for both buckets in region `us-east-1`:
  PUT, HEAD, range GET, list, multipart complete/abort and DELETE. Silo returned
  a filtered bucket list containing only the two logging buckets. Listing an
  existing unrelated bucket returned AccessDenied.
- A Pod without an allowed client identity could not reach Loki's `/ready`.
  The collector, Prometheus and Grafana successfully reached their endpoints.

## Functional evidence

- Synthetic HTTP push returned 204, query matched, and `/flush` returned 204.
  S3 objects appeared in `spainip-loki-data`.
- A real canary Pod emitted stdout, stderr, fake password/bearer-token fields,
  and an indented multiline record. Loki returned three records with correct
  stream/namespace/service labels, both fake credentials absent, redaction
  markers present, and both continuation lines joined into the multiline entry.
- Canary collection started with namespace `logging`; the source now selects all
  Running Pods on the local node. Twenty namespaces already produced logs during
  the initial sample; quiet services need not have new entries immediately.
- `k3s.service` journal entries were queried. `nats-server.service` is selected
  too, but did not produce a new sample during the observation window. It was
  not restarted or otherwise disturbed just to generate a test message.
- The namespace-filter rollout replaced Alloy with its positions/WAL host path
  retained. Canary records remained at the expected count, without replay in
  this test. This does not guarantee general exactly-once delivery.
- Loki was gracefully replaced with `storage-loki-0` retained. Existing canary
  logs remained queryable; an entry emitted during the outage appeared afterward.
  The observed Alloy dropped-entry counter remained zero.
- A disposable Loki with a unique test tenant/index prefix used the rules bucket
  and a 24-hour retention setting. A 49-hour-old synthetic chunk was flushed,
  its index uploaded during graceful shutdown, then a cold replacement Compactor
  marked/deleted the expired object using the restricted key. The chunk was absent
  from S3 and no longer queryable. Production retention stayed at 336h throughout.
  The temporary Pods/ConfigMap and remaining test metadata were removed.
- Grafana datasource UID `loki` reports `OK`; an authenticated query through
  Grafana succeeded. Dashboard `spainip-cluster-logs` is provisioned. Existing
  `prometheus` and `alertmanager` datasource UIDs remain present. The current
  organization has one Admin user and no additional viewers.
- Both Prometheus scrape targets reported UP. Alerts cover delivery drops/retries,
  S3 and server errors, WAL backlog/disk pressure, memory/restarts, shared disk,
  PVC availability and bucket planning budgets.

## Initial measurements and practical limits

During the first few minutes of expanded collection, Loki was around 22m CPU /
39 MiB memory after restart; Alloy around 39m CPU / 65 MiB. These are short-window
observations, not capacity guarantees. Received log volume was roughly 1.7 KiB/s
in a five-minute warm-up sample, before representative production peaks.

Loki requests 250m/1 GiB and is limited to 2 CPU/3 GiB; Alloy requests
100m/128 MiB and is limited to 500m/512 MiB. A retained 20 GiB PVC serves Loki;
Silo stores the durable objects. Alloy positions/WAL are at
`/var/lib/alloy-logging`, with 15-minute WAL segment age and bounded retries.
Time limits are not a reserved disk quota or an unlimited outage guarantee.

Review sustained ingestion, dropped/retried entries, bucket growth and shared
disk headroom over the first days. Fourteen-day retention has been configured;
the deployment has not existed for fourteen days. The short-retention proof
validates the deletion path, not a fourteen-day soak test. Neither the server nor
Silo was shut down to simulate a total failure. Off-server log durability and
namespace-level viewer isolation remain outside this single-node deployment.
