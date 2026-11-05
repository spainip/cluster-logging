# SpainIP cluster logging

Public, secret-free source for Loki and Alloy in the `logging` namespace on
`spainip-k3s`. The Fleet GitRepo is registered in the `spainip` workspace by
`spainip/infra/fleet/cluster-logging-gitrepo.yaml`.

- Loki chart 21.0.0, image 3.7.9 pinned by digest; monolithic, replication 1.
- Alloy chart 1.15.0, image v1.21.3 pinned by digest; one node collector.
- Existing Silo buckets `spainip-loki-data` and `spainip-loki-rules`, region
  `us-east-1`, path-style S3 via the internal Service.
- Existing system Grafana and Prometheus; no public Loki/Alloy ingress.
- Fourteen-day Compactor retention and retained 20 GiB Loki local storage.
- Alloy positions/WAL in `/var/lib/alloy-logging`; 15-minute WAL segment age,
  bounded retries. This bounds recovery buffering by time, not a reserved disk
  quota. The logging system is not HA and cannot guarantee lossless delivery.

## Credentials and ownership

Provision `logging/loki-s3` with `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY` before activation. Only Loki references it; plaintext
values, Secret manifests and Silo administrator credentials never belong here.
The source of the user provisioning contract and IAM policy is `LOGGING.md`
in `spainip/infra`.

`fleet/logging-support` owns namespace, retained StorageClass, NetworkPolicies,
Alloy configuration/RBAC, Grafana datasource/dashboard and Prometheus alerts.
`fleet/loki` depends on support; `fleet/alloy` depends on Loki. Fleet installs
both charts at pinned versions. Do not manually install duplicate Helm releases.

`LOG_NAMESPACE_FILTER` in Alloy values controls canary/full namespace collection.
Discovery is restricted to Running Pods on the local node. Files are initially
read from the end, journal history is initially limited to five minutes, and
positions survive replacement. Logs created before discovery/collection starts
are not promised to be recovered. `^\S` starts a multiline record; indented
continuations are joined with a 128-line/3-second bound. Known token, cookie,
password and authorization formats are redacted; this is not a substitute for
safe application logging.

## Validation

Requires Helm, kubectl and Python 3 with PyYAML. `scripts/validate.py` renders
pinned charts and asserts deployment, credential, RBAC and exposure invariants.
Run server dry runs and pinned-binary config validation before promotion.
Runtime evidence is recorded in `docs/VALIDATION.md` after activation.

## Operations

Grafana datasource UID: `loki`. Dashboard UID: `spainip-cluster-logs`.
Query example: `{cluster="spainip-k3s",namespace="traefik"}`.
Host journal: `{cluster="spainip-k3s",source="journal"}`.

Loki URL: `http://loki.logging.svc.cluster.local:3100`.
Alloy writes `/loki/api/v1/push`; only trusted Grafana/Alloy/Prometheus Pod labels
are admitted by ingress NetworkPolicies. This is a single trusted tenant;
NetworkPolicy cannot distinguish query from ingestion on port 3100.

For credential rotation update the existing Secret, roll Loki once, verify Silo
reads/writes/compaction, then revoke the old key. For rollback stop Alloy through
its source first; preserve buckets, retained Loki PVC and Alloy host state.
Silo must be restored before Loki. Coordinate Loki flush/pause when backing up
Silo; Alloy buffers only within the documented bounds.
