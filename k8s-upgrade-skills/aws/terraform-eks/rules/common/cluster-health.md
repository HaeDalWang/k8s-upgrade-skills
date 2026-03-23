---
id: COM-001
name: 클러스터 기본 상태 검증
severity: CRITICAL
category: common
phase: pre-flight
applies_when: 항상
---

# COM-001: 클러스터 기본 상태 검증

## 목적

업그레이드 시작 전 클러스터가 정상 상태인지 확인한다. 이미 불안정한 클러스터에 업그레이드를 적용하면 장애가 확대된다.

## 검증 항목

### 1. 클러스터 상태

```bash
aws eks describe-cluster \
  --name ${CLUSTER_NAME} \
  --query 'cluster.{version:version, status:status, endpoint:endpoint}' \
  --output json
```

### 2. 노드 상태

```bash
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status,VERSION:.status.nodeInfo.kubeletVersion'
```

### 3. 노드 Condition 상세 (MemoryPressure, DiskPressure, PIDPressure)

```bash
kubectl get nodes -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
issues = []
for node in data['items']:
    name = node['metadata']['name']
    for cond in node.get('status', {}).get('conditions', []):
        if cond['type'] == 'Ready' and cond['status'] != 'True':
            issues.append(f\"{name}: NotReady — {cond.get('reason', '')} {cond.get('message', '')}\")
        elif cond['type'] in ('MemoryPressure', 'DiskPressure', 'PIDPressure') and cond['status'] == 'True':
            issues.append(f\"{name}: {cond['type']}=True — {cond.get('reason', '')}\")
for i in issues:
    print(i)
if not issues:
    print('모든 노드 정상')
"
```

### 4. EKS Upgrade Readiness Insights

MCP: `get_eks_insights(cluster_name, category="UPGRADE_READINESS")`

Fallback:
```bash
aws eks list-insights --cluster-name ${CLUSTER_NAME} \
  --filter '{categories: ["UPGRADE_READINESS"]}' \
  --query 'insights[].{name:name, status:insightStatus.status}' --output table
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| status=ACTIVE, version=CURRENT, 모든 노드 Ready, Insights 전부 PASSING | ✅ PASS | 진행 |
| 노드 MemoryPressure/DiskPressure/PIDPressure | ❌ FAIL | STOP — 리소스 압박 해소 후 재시도 |
| 노드 NotReady | ❌ FAIL | STOP — 노드 복구 후 재시도 |
| Insights WARNING | ⚠️ WARN | 보고 — 사용자 확인 후 진행 |
| Insights ERROR | ❌ FAIL | STOP — 호환성 문제 해결 필수 |
| status != ACTIVE | ❌ FAIL | STOP — 클러스터가 이미 업데이트/오류 상태 |
