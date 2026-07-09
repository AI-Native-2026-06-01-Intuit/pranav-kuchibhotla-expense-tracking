# PLG-T bootstrap for expense-api (W5 D5)

`./scripts/observability-apply.sh` assumes the cluster already has the
kube-prometheus-stack operator CRDs, Loki, Alloy, Tempo, and an OTel
Collector reachable from the expense-api Deployment. This file captures
the exact commands that were used to stand that up in the local k3d
cluster so a fresh operator can reproduce it end to end.

All components live in the `monitoring` namespace. Tested against
Kubernetes 1.35 on k3d 5.9 (Rancher Desktop, 6 CPU / 24 GiB VM).

## Prereqs

```
kubectl config current-context           # k3d-expense
helm version --short                      # v4.x
docker info | grep -E "CPUs|Total Memory" # >= 4 CPU, >= 8 GiB for the full stack
```

## Helm repos

```
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update
```

## 1. kube-prometheus-stack (Prometheus + Grafana + Alertmanager + operator)

```
helm upgrade --install kube-prometheus-stack \
  prometheus-community/kube-prometheus-stack \
  --version 65.1.0 \
  --namespace monitoring --create-namespace \
  --set 'prometheus.prometheusSpec.enableFeatures[0]=exemplar-storage' \
  --wait --timeout 12m
```

Grafana admin password:

```
kubectl -n monitoring get secret kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

Reach Grafana:

```
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
# http://localhost:3000 (admin / password above)
```

## 2. Loki (single binary, filesystem storage)

The bare `--set deploymentMode=SingleBinary` install fails the chart
template on 6.6.4 because `loki.storage.bucketNames.*` and
`loki.schemaConfig` are required even for filesystem storage. Use these
explicit values:

```
helm upgrade --install loki grafana/loki \
  --version 6.6.4 \
  --namespace monitoring \
  --set deploymentMode=SingleBinary \
  --set loki.auth_enabled=false \
  --set 'loki.commonConfig.replication_factor=1' \
  --set 'loki.storage.type=filesystem' \
  --set 'loki.storage.bucketNames.chunks=chunks' \
  --set 'loki.storage.bucketNames.ruler=ruler' \
  --set 'loki.storage.bucketNames.admin=admin' \
  --set 'loki.schemaConfig.configs[0].from=2024-04-01' \
  --set 'loki.schemaConfig.configs[0].store=tsdb' \
  --set 'loki.schemaConfig.configs[0].object_store=filesystem' \
  --set 'loki.schemaConfig.configs[0].schema=v13' \
  --set 'loki.schemaConfig.configs[0].index.prefix=index_' \
  --set 'loki.schemaConfig.configs[0].index.period=24h' \
  --set singleBinary.replicas=1 \
  --set write.replicas=0 \
  --set read.replicas=0 \
  --set backend.replicas=0 \
  --set chunksCache.enabled=false \
  --set resultsCache.enabled=false \
  --wait --timeout 10m
```

## 3. Alloy (log shipper → Loki)

Alloy's default install runs the agent with an empty config, which
means it does nothing. Use the checked-in values file that wires pod
discovery + Loki write:

```
helm upgrade --install alloy grafana/alloy \
  --version 0.5.0 \
  --namespace monitoring \
  -f manifests/observability/helm-values/alloy-values.yaml \
  --wait --timeout 10m

# ConfigMap change does not restart the DaemonSet by itself:
kubectl -n monitoring rollout restart daemonset alloy
```

## 4. Tempo (traces)

```
helm upgrade --install tempo grafana/tempo \
  --version 1.10.1 \
  --namespace monitoring \
  --wait --timeout 10m
```

## 5. OTel Collector (traces gateway → Tempo)

The `opentelemetry-collector` chart no longer ships a default image; you
have to pass one, and the traces pipeline needs an explicit exporter.
The values file below uses the `contrib` image and points OTLP export
at Tempo.

```
helm upgrade --install otel-collector \
  open-telemetry/opentelemetry-collector \
  --version 0.97.0 \
  --namespace monitoring \
  -f manifests/observability/helm-values/otel-collector-values.yaml \
  --wait --timeout 10m
```

The Deployment's OTel init container will send OTLP/gRPC to
`otel-collector-opentelemetry-collector.monitoring.svc.cluster.local:4317`
(the chart-generated service name — matches
`manifests/observability/expense-api-deployment-patch.yaml`).

## 6. Grafana datasource wiring (Loki + Tempo)

`kube-prometheus-stack` only ships Prometheus + Alertmanager as
provisioned datasources. Add Loki and Tempo, and thread the
trace ↔ logs pivot, with a re-usable overlay. `additionalDataSources` is
a *list*, so it must be merged as a values file (`-f`) — `--set-file`
would inject the whole file as one string and break provisioning:

```
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --version 65.1.0 \
  --namespace monitoring \
  --reuse-values \
  -f manifests/observability/helm-values/grafana-datasources.yaml \
  --wait --timeout 5m

kubectl -n monitoring rollout restart deploy/kube-prometheus-stack-grafana
```

The overlay wires the pivot both ways and keeps trace_id out of the Loki
labels (matched on the JSON body / as a line filter instead):

- **Tempo → logs**: `tracesToLogsV2` on the Tempo datasource maps the
  span's `service.name` onto the bounded `app` label and sets
  `filterByTraceID`, so each span's **Logs for this span** button opens a
  split Loki pane querying `{app="expense-api"} |= "<trace_id>"`.
- **logs → Tempo**: `derivedFields` on the Loki datasource extracts
  `trace_id` from the JSON log line and renders a **View trace in Tempo**
  link.

If Grafana's datasource-settings page ever shows `Unable to connect to
Tempo` for the Tempo datasource, that is Grafana's health probe hitting
`/api/status/services`, which only exists on Tempo Enterprise. The
datasource proxy and Explore search still work on Tempo OSS — verify
with:

```
curl -sS -u admin:<pw> \
  "http://localhost:3000/api/datasources/proxy/uid/tempo/api/search?q=%7Bresource.service.name%3D%22expense-api%22%7D&limit=3" | jq
```

## Sanity checks after bootstrap

```
kubectl get pods -n monitoring
kubectl get svc  -n monitoring
kubectl get pods -n expense-dev

# Prometheus scraping the app:
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 19090:9090 &
curl -sS -G "http://127.0.0.1:19090/api/v1/query" \
  --data-urlencode 'query=sum by (uri, status) (http_server_requests_seconds_count{app="expense-api"})' | jq

# Tempo search:
kubectl -n monitoring port-forward svc/tempo 3200:3100 &
curl -sS -G "http://127.0.0.1:3200/api/search" \
  --data-urlencode 'q={resource.service.name="expense-api"}' | jq

# Loki labels:
kubectl -n monitoring port-forward svc/loki-gateway 13100:80 &
curl -sS "http://127.0.0.1:13100/loki/api/v1/label/app/values" | jq
```

Once the stack is up, `./scripts/observability-apply.sh` and
`./scripts/observability-smoke.sh` become the day-to-day workflow.
