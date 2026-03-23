---
id: WLS-003
name: PV 존 어피니티 재스케줄 불가 위험
severity: CRITICAL
category: workload-safety
phase: pre-flight
applies_when: PV 사용 워크로드 존재 시
---

# WLS-003: PV 존 어피니티 재스케줄 불가 위험

## 목적

EBS 기반 PersistentVolume은 특정 AZ에 고정된다. 노드 drain 시 Pod가 퇴거되면, 해당 PV와 같은 AZ에 가용 노드가 없으면 Pod가 영원히 Pending 상태에 빠진다. 이는 rolling update에서 가장 흔한 장애 원인 중 하나다.

## 위험 시나리오

1. EBS PV가 AZ-a에 있는데, AZ-a의 유일한 노드가 drain됨 → Pod Pending (다른 AZ 노드에서 EBS 마운트 불가)
2. StatefulSet + volumeClaimTemplates: 각 Pod의 PVC가 서로 다른 AZ에 바인딩 → 특정 AZ 노드가 모두 drain되면 해당 Pod Pending
3. `WaitForFirstConsumer` StorageClass: 아직 바인딩 안 된 PVC는 안전 (새 노드의 AZ에 생성됨)
4. 이미 바인딩된 PV (`Bound` 상태): AZ 고정 — 위험 대상

## 검증 명령어

```bash
# 1단계: Bound 상태 PVC와 해당 PV의 AZ 매핑
kubectl get pv -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
pv_zones = {}
for pv in data['items']:
    name = pv['metadata']['name']
    phase = pv.get('status', {}).get('phase', '')
    if phase != 'Bound':
        continue
    claim = pv.get('spec', {}).get('claimRef', {})
    claim_ns = claim.get('namespace', '')
    claim_name = claim.get('name', '')
    
    # AZ 추출: nodeAffinity에서
    zones = []
    na = pv.get('spec', {}).get('nodeAffinity', {}).get('required', {}).get('nodeSelectorTerms', [])
    for term in na:
        for expr in term.get('matchExpressions', []):
            if expr.get('key') in ('topology.kubernetes.io/zone', 'failure-domain.beta.kubernetes.io/zone'):
                zones.extend(expr.get('values', []))
    
    if zones:
        pv_zones[f'{claim_ns}/{claim_name}'] = {
            'pv': name, 'zones': zones,
            'storage_class': pv.get('spec', {}).get('storageClassName', ''),
            'access_modes': pv.get('spec', {}).get('accessModes', [])
        }

for claim, info in pv_zones.items():
    print(f\"{claim} → PV={info['pv']} AZ={info['zones']} SC={info['storage_class']}\")
if not pv_zones:
    print('AZ 고정 PV 없음')
"

# 2단계: 각 AZ별 가용 노드 수 확인
kubectl get nodes -o json | python3 -c "
import json, sys
from collections import Counter
data = json.load(sys.stdin)
az_nodes = Counter()
az_ready = Counter()
for node in data['items']:
    az = node['metadata'].get('labels', {}).get('topology.kubernetes.io/zone', 'unknown')
    az_nodes[az] += 1
    conditions = {c['type']: c['status'] for c in node.get('status', {}).get('conditions', [])}
    if conditions.get('Ready') == 'True':
        az_ready[az] += 1

for az in sorted(az_nodes):
    print(f'{az}: 전체={az_nodes[az]} Ready={az_ready[az]}')
"

# 3단계: 위험 교차 분석 — PV AZ에 노드가 1개뿐인 경우
kubectl get pv -o json | python3 -c "
import json, sys, subprocess
pvs = json.load(sys.stdin)
nodes_raw = subprocess.run(['kubectl','get','nodes','-o','json'], capture_output=True, text=True)
nodes = json.loads(nodes_raw.stdout)

# AZ별 노드 수
from collections import Counter
az_count = Counter()
for n in nodes['items']:
    az = n['metadata'].get('labels',{}).get('topology.kubernetes.io/zone','')
    az_count[az] += 1

# PV별 위험 판정
risks = []
for pv in pvs['items']:
    if pv.get('status',{}).get('phase') != 'Bound':
        continue
    claim = pv.get('spec',{}).get('claimRef',{})
    na = pv.get('spec',{}).get('nodeAffinity',{}).get('required',{}).get('nodeSelectorTerms',[])
    for term in na:
        for expr in term.get('matchExpressions',[]):
            if 'zone' in expr.get('key',''):
                for az in expr.get('values',[]):
                    if az_count.get(az, 0) <= 1:
                        risks.append({
                            'pvc': f\"{claim.get('namespace')}/{claim.get('name')}\",
                            'pv': pv['metadata']['name'],
                            'az': az,
                            'nodes_in_az': az_count.get(az, 0)
                        })

for r in risks:
    print(f\"⚠️ {r['pvc']} → PV={r['pv']} AZ={r['az']} 노드수={r['nodes_in_az']} — drain 시 재스케줄 불가 위험\")
if not risks:
    print('PV AZ 위험 없음 — 모든 PV AZ에 2개 이상 노드 존재')
"
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| AZ 고정 PV 없음 | ✅ PASS | 진행 |
| 모든 PV AZ에 노드 2개 이상 | ✅ PASS | 진행 |
| PV AZ에 노드 1개만 존재 | ❌ FAIL | STOP — drain 시 해당 Pod Pending 확정 |
| PV AZ에 노드 2개이지만 동시 drain 가능성 | ⚠️ WARN | 보고 — MNG maxUnavailable 설정 확인 필요 |

## 조치 방안

### FAIL 해결

```bash
# 옵션 1: 해당 AZ에 노드 추가 (Karpenter 사용 시 자동)
# Karpenter NodePool에 해당 AZ가 포함되어 있는지 확인
kubectl get nodepool -o yaml | grep -A5 'topology.kubernetes.io/zone'

# 옵션 2: MNG의 경우 desired_size 증가
# terraform.tfvars에서 desired_size 조정 후 apply

# 옵션 3: PV 데이터를 다른 AZ로 마이그레이션 (EBS snapshot → 다른 AZ에 restore)
# 이 방법은 다운타임이 필요하므로 최후의 수단
```

### 예방적 설계 권장사항
- StorageClass에 `volumeBindingMode: WaitForFirstConsumer` 사용 (이미 적용됨)
- StatefulSet은 `topologySpreadConstraints`로 AZ 분산 배치
- 중요 워크로드는 replicas >= 2 + PV를 서로 다른 AZ에 분산
