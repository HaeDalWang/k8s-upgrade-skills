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

EKS 노드는 linux/amd64. Mac(arm64)에서 로컬 빌드 시 `--platform linux/amd64` 필수.

```bash
# mongo-crud
docker buildx build --platform linux/amd64 -t svvwac98/msa-demo-apps:mongo-crud-latest apps/mongo-crud/ --push

# pg-crud
docker buildx build --platform linux/amd64 -t svvwac98/msa-demo-apps:pg-crud-latest apps/pg-crud/ --push

# event-hub
docker buildx build --platform linux/amd64 -t svvwac98/msa-demo-apps:event-hub-latest apps/event-hub/ --push
```

CI(GitHub Actions)는 apps/ 변경 시 자동 빌드·푸시 (platforms: linux/amd64).

## Secret 준비 예시

```bash
# mongo-crud: PSMDB(mongodb-cluster-secrets)에서 credential 추출 후 MONGO_URI 생성
# USER=$(kubectl get secret mongodb-cluster-secrets -n mongodb -o jsonpath='{.data.MONGODB_DATABASE_ADMIN_USER}' | base64 -d)
# PASS=$(kubectl get secret mongodb-cluster-secrets -n mongodb -o jsonpath='{.data.MONGODB_DATABASE_ADMIN_PASSWORD}' | base64 -d)
kubectl create secret generic mongo-crud-secret \
  --from-literal=MONGO_URI="mongodb://databaseAdmin:PASSWORD@mongodb-cluster-rs0.mongodb.svc.cluster.local/demo?authSource=admin&replicaSet=rs0" \
  -n workload
# PASSWORD는 위 명령으로 mongodb-cluster-secrets에서 추출한 값으로 교체

# pg-crud: cluster1-pguser-demo의 pgbouncer-uri 사용 (비밀번호 특수문자 URL 인코딩됨)
kubectl delete secret pg-crud-secret -n workload 2>/dev/null
PG_DSN=$(kubectl get secret cluster1-pguser-demo -n postgresql -o jsonpath='{.data.pgbouncer-uri}' | base64 -d)
PG_DSN="${PG_DSN/postgresql.svc:/postgresql.svc.cluster.local:}?sslmode=require"
kubectl create secret generic pg-crud-secret --from-literal=PG_DSN="$PG_DSN" -n workload
kubectl rollout restart deployment -n workload -l app.kubernetes.io/instance=pg-crud
```
