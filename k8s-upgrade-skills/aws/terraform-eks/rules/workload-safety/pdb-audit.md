---
id: WLS-001
name: PDB 차단 가능성 분석
severity: CRITICAL
category: workload-safety
phase: pre-flight
applies_when: 항상
---

# WLS-001: PDB 차단 가능성 분석

## 목적

PodDisruptionBudget(PDB)이 노드 drain을 차단하여 rolling update가 무한 대기에 빠지는 것을 사전에 방지한다.

## 위험 시나리오

1. `minAvailable == replicas` (또는 `maxUnavailable == 0`): drain 시 어떤 Pod도 퇴거할 수 없어 노드가 영원히 drain 완료되지 않음
2. `disruptionsAllowed == 0`: 현재 healthy Pod 수가 PDB 요구치와 정확히 같아서 1개라도 퇴거하면 위반
3. PDB가 존재하지만 매칭되는 Pod가 없음: 설정 오류 가능성 (경고)
4. 여러 PDB가 동일 Pod를 선택: 가장 제한적인 PDB가 적용되어 예상보다 drain이 어려움

## 검증 명령어

### MCP (우선)
```
list_k8s_resources: kind=PodDisruptionBudget, api_version=policy/v1
```

### kubectl (fallback)
```bash
kubectl get pdb --all-namespaces \
  -o custom-columns='\
    NAMESPACE:.metadata.namespace,\
    NAME:.metadata.name,\
    MIN-AVAIL:.spec.minAvailable,\
    MAX-UNAVAIL:.spec.maxUnavailable,\
    ALLOWED-DISRUPT:.status.disruptionsAllowed,\
    CURRENT-HEALTHY:.status.currentHealthy,\
    DESIRED-HEALTHY:.status.desiredHealthy,\
    EXPECTED-PODS:.status.expectedPods'
```

### 심화 검증: PDB-Pod 매칭 확인
```bash
# 각 PDB의 selector로 매칭되는 Pod 수 확인
kubectl get pdb -A -o json | python3 -c "
import json, sys, subprocess
data = json.load(sys.stdin)
for pdb in data['items']:
    ns = pdb['metadata']['namespace']
    name = pdb['metadata']['name']
    selector = pdb.get('spec', {}).get('selector', {}).get('matchLabels', {})
    label_str = ','.join(f'{k}={v}' for k, v in selector.items())
    allowed = pdb.get('status', {}).get('disruptionsAllowed', 'N/A')
    expected = pdb.get('status', {}).get('expectedPods', 0)
    current = pdb.get('status', {}).get('currentHealthy', 0)
    desired = pdb.get('status', {}).get('desiredHealthy', 0)
    
    # 위험 판정
    risk = 'OK'
    if allowed == 0:
        risk = 'BLOCKED'
    elif expected == 0:
        risk = 'NO_MATCH'
    elif current == desired and allowed <= 1:
        risk = 'TIGHT'
    
    print(f'{ns}/{name}: allowed={allowed} current={current} desired={desired} expected={expected} risk={risk} selector={label_str}')
"
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| 모든 PDB `disruptionsAllowed >= 1` | ✅ PASS | 진행 |
| `risk=TIGHT` (allowed=1, current=desired) | ⚠️ WARN | 보고 — drain 중 일시적 차단 가능성 있음. 사용자 확인 |
| `risk=BLOCKED` (allowed=0) | ❌ FAIL | STOP — drain 불가. 사용자가 PDB 조정 또는 스케일업 필요 |
| `risk=NO_MATCH` (expected=0) | ⚠️ WARN | 보고 — PDB가 아무 Pod도 보호하지 않음 (설정 오류 가능성) |

## 조치 방안

### BLOCKED 해결
```bash
# 옵션 1: PDB의 minAvailable 낮추기
kubectl patch pdb <NAME> -n <NS> --type merge -p '{"spec":{"minAvailable":"50%"}}'

# 옵션 2: 레플리카 수 늘리기 (PDB 요구치보다 1개 이상 여유)
kubectl scale deployment <NAME> -n <NS> --replicas=<CURRENT+1>

# 옵션 3: maxUnavailable로 전환 (minAvailable 대신)
kubectl patch pdb <NAME> -n <NS> --type merge \
  -p '{"spec":{"minAvailable":null,"maxUnavailable":1}}'
```

### TIGHT 완화
```bash
# 레플리카를 1개 추가하여 drain 여유 확보
kubectl scale deployment <NAME> -n <NS> --replicas=<CURRENT+1>
```
