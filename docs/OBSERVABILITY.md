# Vitali observability and capacity baseline

This baseline is an opt-in operations plane for the current single-host stack.
It provides Prometheus, Grafana, OpenTelemetry Collector, PostgreSQL/Redis/host
exporters, alert rules and a provisioned overview dashboard. Nothing is routed
through the public Nginx service: Prometheus and Grafana bind to loopback only;
exporters and OTLP ports remain Compose-network-only.

## Privacy and security defaults

- The application PHI scrubber runs before export. The collector removes
  cookies, authorization headers, response cookies and SQL statements again.
- Raw spans are not persisted. `spanmetrics` converts them to aggregate RED
  metrics; exemplars are disabled to avoid trace identifiers in Prometheus.
- Grafana has no anonymous access or self-registration. Its password and the
  PostgreSQL exporter password are mounted from root-only host files.
- Redis credentials are materialized from the existing host-only production env
  into a root-directory password file and never added to versioned configuration
  or the exporter environment.
- Dashboards must not use patient, professional, tenant-domain, CPF, CNS,
  accession number or free-text labels. Tenant-level metrics require a reviewed,
  bounded identifier and must not expose schema names to ordinary operators.

## Enable on a single host

The versions and multi-architecture image digests are pinned in
`docker-compose.observability.yml`.

```bash
sudo PROD_ENV_FILE=/etc/vitali/secrets.env \
  bash scripts/provision_observability_secrets.sh

COMPOSE=(docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.observability.yml \
  --env-file /etc/vitali/secrets.env)
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up -d
"${COMPOSE[@]}" ps
```

Access Grafana through an SSH tunnel, never by opening its port at the firewall:

```bash
ssh -L 3002:127.0.0.1:3002 operator@vitali-host
```

Then open `http://127.0.0.1:3002`. Retrieve the initial password locally from
`/etc/vitali/grafana-admin-password`; rotate it after the first controlled login.
Prometheus is similarly available on loopback port 9090 for emergency diagnosis.

Set retention from host capacity, not habit. Defaults are `15d` and `20GB`; the
first limit reached wins. Alert at 70% volume consumption and expand or shorten
retention before 85%. Prometheus/Grafana volumes are operational telemetry, not
the clinical system of record, and have separate backup/retention policy.

## Initial service-level objectives

These are starting objectives to measure for 30 days and ratify with clinical
operations. Maintenance approved and announced in advance is excluded; all
other failures consume error budget.

| Service indicator | Initial SLO | Window | Critical page |
|---|---:|---:|---:|
| Authenticated web/API availability | 99.9% | rolling 30d | 5m total outage |
| Core read API latency | p95 < 500ms, p99 < 1.5s | 5m and 30d | p95 > 1s for 15m |
| Core write API latency | p95 < 1s, p99 < 3s | 5m and 30d | p95 > 2s for 15m |
| Server-side error ratio | < 0.5% | rolling 30d | > 1% for 10m |
| Scheduling/encounter transaction success | 99.95% | rolling 30d | any sustained failure > 5m |
| Celery critical queue age | p95 < 60s | 15m | oldest > 5m |
| PostgreSQL connection saturation | < 80% | 15m | > 90% for 5m |
| Redis memory saturation | < 85% | 15m | > 95% for 5m |
| Host persistent disk free | > 20% target | 15m | < 10% |
| Telemetry target availability | 99.5% | rolling 30d | target down > 5m |

Availability and latency need route-group recording rules before contractual use.
Do not aggregate health endpoints with real workflows: synthetic `/health/` can
be green while login, scheduling or an encounter write is failing. Add black-box
probes for those journeys with dedicated non-clinical accounts.

Use multi-window burn-rate paging when Alertmanager is introduced: fast burn
(14.4× over 1h and 5m) pages; slow burn (6× over 6h and 30m) opens an urgent
ticket. Alert delivery is not complete until two independent channels and a
quarterly page test are verified.

## Capacity review

Weekly review covers CPU throttling, memory working set/OOM, filesystem trend,
PostgreSQL connections/locks/cache hit/replication-WAL growth, Redis memory and
evictions, Celery queue depth/age, DICOM ingest/storage growth, Prometheus
cardinality and backup duration. Forecast 30/60/90-day exhaustion and create a
capacity action whenever projected headroom falls below 30 days.

Celery uses Redis by default; `docker-compose.rabbitmq.yml` is an optional broker
profile. Do not deploy a permanently-down RabbitMQ exporter. When that profile is
enabled, add `docker-compose.observability-rabbitmq.yml` to the Compose command;
it enables RabbitMQ's bundled Prometheus plugin on the private network and swaps
the empty file-discovery target for `rabbitmq:15692`, without another credential.
Alert on queue depth, oldest message, unacked messages, connection/channel count
and disk/memory alarms.

## Topology profiles

### Single host — current beta and small clinic

All application and observability services share one Docker host. This gives
fast diagnosis but no failure-domain independence. Keep loopback-only UIs,
resource limits, host-level disk alerts and external Uptime Kuma probes. A total
host failure also removes local dashboards, so paging must originate outside the
host. Appropriate only while agreed concurrency, storage growth and RTO fit one
machine with at least 30% steady-state headroom.

### Multi-node / dedicated hospital

Move PostgreSQL to HA primary/standby or a managed HA service, Redis to a
replicated topology, workers to multiple nodes and DICOM storage to redundant
object/block storage. Run two collectors with load-balanced OTLP; send metrics
to a redundant Prometheus pair or a remote-write backend. Grafana becomes
stateless behind private SSO. Use stable instance/site/cluster labels, service
discovery and network policy. Monitoring and alert delivery must reside in a
different failure domain from the hospital workload.

### Kubernetes

Use the OpenTelemetry Operator/Collector gateway pattern, Prometheus Operator,
ServiceMonitor/PodMonitor, kube-state-metrics and node-exporter DaemonSet. Apply
requests/limits, PodDisruptionBudgets, anti-affinity/topology spread, NetworkPolicy,
encrypted Secrets/KMS and persistent-volume classes with tested snapshots. Keep
PHI scrubbing at the SDK and collector gateway. Adopt HPA only from bounded
resource/queue metrics, never unbounded tenant or patient labels. Define control
plane, data plane and per-hospital failure domains before migration; Kubernetes
does not by itself provide database, PACS or disaster-recovery correctness.

## Acceptance checklist

- All scrape targets green for 24 hours; deliberate exporter stop pages within
  the documented threshold.
- No exporter/Grafana secret appears in `docker compose config`, Prometheus
  targets, Grafana data source JSON, container environment or logs.
- Trace/span samples inspected for PHI before any raw-trace backend is enabled.
- Dashboard and alert PromQL validated with `promtool` in CI.
- A simulated disk, database saturation and queue backlog exercise has an owner,
  runbook link, page evidence and recovery timestamp.
- SLO report distinguishes user journeys, regions/sites, planned maintenance and
  missing telemetry; missing data never counts as success.
