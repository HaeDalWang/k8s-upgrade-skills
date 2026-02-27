# ArgoCD Helm 차트 (업그레이드·트러블슈팅 테스트)

ArgoCD가 이 디렉터리(또는 이 레포의 `charts/` 경로)를 Helm 소스로 바라보고, values 파일만 바꿔서 여러 시나리오를 배포할 수 있도록 구성했다.

## 차트: upgrade-test-app

### 기본 values

| 파일 | 용도 |
|------|------|
| `values.yaml` | 기본 배포 (PDB/PV/앱 없음) |
| `values_pdb.yaml` | PDB 활성화 — drain/업그레이드 시 `disruptionsAllowed` 트러블슈팅 |
| `values_pv.yaml` | StatefulSet + PVC — 노드 롤링 시 볼륨·재스케줄 트러블슈팅 |

### MSA Demo 앱 values

| 파일 | 앱 | 언어 |
|------|-----|------|
| `values_mongo_crud.yaml` | mongo-crud | Python / FastAPI |
| `values_pg_crud.yaml` | pg-crud | Go / net/http |
| `values_event_hub.yaml` | event-hub | Node.js / Express |

### 트러블슈팅 미션 오버레이

| 파일 | MISSION | 증상 | 트러블슈팅 포인트 |
|------|---------|------|-------------------|
| `values_mission_wrong_creds.yaml` | wrong-creds | DB 연결 실패 / CrashLoopBackOff | `kubectl logs`, Secret 확인 |
| `values_mission_oom.yaml` | oom | OOMKilled (Exit 137) | `kubectl describe pod`, limits 조정 |
| `values_mission_slow_query.yaml` | slow-query | readiness 실패 / Unready | `pg_stat_activity`, slow query 확인 |
| `values_mission_dns_fail.yaml` | dns-fail | 502 Bad Gateway | `nslookup`, `kubectl get svc` |

## ArgoCD Application 예시

- **기본**: `source.helm.valueFiles: ["values.yaml"]`
- **PDB**: `["values.yaml", "values_pdb.yaml"]`
- **PV**: `["values.yaml", "values_pv.yaml"]`
- **mongo-crud**: `["values.yaml", "values_mongo_crud.yaml"]`
- **pg-crud + 슬로우쿼리 미션**: `["values.yaml", "values_pg_crud.yaml", "values_mission_slow_query.yaml"]`

## 이미지 빌드

```bash
# mongo-crud
docker build -t <REGISTRY>/mongo-crud:latest apps/mongo-crud/
docker push <REGISTRY>/mongo-crud:latest

# pg-crud
docker build -t <REGISTRY>/pg-crud:latest apps/pg-crud/
docker push <REGISTRY>/pg-crud:latest

# event-hub
docker build -t <REGISTRY>/event-hub:latest apps/event-hub/
docker push <REGISTRY>/event-hub:latest
```

빌드 후 각 values 파일의 `image.repository` 를 교체한다.

## Secret 준비 예시

```bash
# mongo-crud: MONGO_URI Secret
kubectl create secret generic mongo-crud-secret \
  --from-literal=MONGO_URI="mongodb://userAdmin:PASSWORD@mongodb-cluster-rs0.mongodb.svc.cluster.local/demo?authSource=admin&replicaSet=rs0" \
  -n workload

# pg-crud: PG_DSN Secret
kubectl create secret generic pg-crud-secret \
  --from-literal=PG_DSN="host=cluster1-pgbouncer.postgresql.svc.cluster.local port=5432 user=demo password=PASSWORD dbname=demo sslmode=disable" \
  -n workload
```
