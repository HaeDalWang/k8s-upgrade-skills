---
id: WLS-006
name: 토폴로지 제약 위반 위험
severity: HIGH
category: workload-safety
phase: pre-flight
applies_when: TopologySpreadConstraints 또는 requiredDuringScheduling Affinity 사용 워크로드 존재 시
---

# WLS-006: 토폴로지 제약 위반 위험

## 목적

`topologySpreadConstraints(whenUnsatisfiable: DoNotSchedule)` 또는 `requiredDuringSchedulingIgnoredDuringExecution` affinity를 사용하는 워크로드는 drain 후 재스케줄 시 제약 조건을 만족하는 노드가 없으면 Pending에 빠진다.

## 위험 시나리오

1. `topologySpreadConstraints` + `DoNotSchedule` + AZ 2개만 사용: 한 AZ의 노드가 모두 drain되면 maxSkew 위반으로 Pending
2. `requiredDuringScheduling` nodeAffinity: 특정 라벨의 노드만 허용 → 해당 노드가 모두 drain되면 Pending
3. `requiredDuringScheduling` podAntiAffinity + hostname: 노드 수 < replicas이면 일부 Pod Pending
4. `minDomains` 설정: 가용 도메인(AZ) 수가 minDomains 미만이면 스케줄 불가

## 검증 명령어

```bash
# TopologySpreadConstraints 사용 워크로드 검출
kubectl get deployments,statefulsets --all-namespaces -o json | python3 -c "
import json, sys
SYSTEM_NS = {'kube-system', 'kube-node-lease', 'kube-public', 'karpenter'}
data = json.load(sys.stdin)
risks = []

for item in data['items']:
    ns = item['metadata']['namespace']
    name = item['metadata']['name']
    kind = item['kind']
    if ns in SYSTEM_NS:
        continue
    
    spec = item.get('spec', {}).get('template', {}).get('spec', {})
    replicas = item.get('spec', {}).get('replicas', 1)
    
    # TopologySpreadConstraints 검사
    tsc = spec.get('topologySpreadConstraints', [])
    for t in tsc:
        if t.get('whenUnsatisfiable') == 'DoNotSchedule':
            min_domains = t.get('minDomains', 0)
            risks.append({
                'ns': ns, 'name': name, 'kind': kind,
                'type': 'TSC-DoNotSchedule',
                'detail': f\"topologyKey={t.get('topologyKey')} maxSkew={t.get('maxSkew')} minDomains={min_domains}\",
                'replicas': replicas
            })
    
    # Required NodeAffinity 검사
    affinity = spec.get('affinity', {})
    na = affinity.get('nodeAffinity', {}).get('requiredDuringSchedulingIgnoredDuringExecution', {})
    if na:
        terms = na.get('nodeSelectorTerms', [])
        for term in terms:
            exprs = term.get('matchExpressions', [])
            for expr in exprs:
                risks.append({
                    'ns': ns, 'name': name, 'kind': kind,
                    'type': 'Required-NodeAffinity',
                    'detail': f\"{expr.get('key')} {expr.get('operator')} {expr.get('values', [])}\",
                    'replicas': replicas
                })
    
    # Required PodAntiAffinity 검사
    paa = affinity.get('podAntiAffinity', {}).get('requiredDuringSchedulingIgnoredDuringExecution', [])
    for rule in paa:
        risks.append({
            'ns': ns, 'name': name, 'kind': kind,
            'type': 'Required-PodAntiAffinity',
            'detail': f\"topologyKey={rule.get('topologyKey')}\",
            'replicas': replicas
        })

if risks:
    for r in risks:
        print(f\"{r['ns']}/{r['name']} ({r['kind']} replicas={r['replicas']}): {r['type']} — {r['detail']}\")
else:
    print('엄격한 토폴로지 제약 사용 워크로드 없음')
"

# AZ별 노드 수 확인 (TSC 위반 가능성 교차 분석)
kubectl get nodes --show-labels | grep -oP 'topology.kubernetes.io/zone=\K[^ ,]+' | sort | uniq -c
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| 엄격한 제약 없음 | ✅ PASS | 진행 |
| `DoNotSchedule` TSC 있으나 AZ/노드 여유 충분 | ✅ PASS | INFO 보고 |
| `DoNotSchedule` TSC + AZ별 노드 1개 | ⚠️ WARN | 보고 — rolling update 중 일시적 Pending 가능성 |
| `Required` affinity + 매칭 노드 부족 | ⚠️ WARN | 보고 — drain 시 재스케줄 불가 가능성 |
| `Required` podAntiAffinity + hostname + replicas > 노드 수 | ❌ FAIL | STOP — 물리적으로 스케줄 불가 |

## 조치 방안

### TSC DoNotSchedule 완화
```bash
# 옵션 1: whenUnsatisfiable을 ScheduleAnyway로 변경 (일시적)
# Helm values에서 수정 후 ArgoCD sync

# 옵션 2: 노드 수 확보 (Karpenter가 자동 처리)
# MNG의 경우 desired_size 증가
```

### Required Affinity 완화
```bash
# preferred로 변경하여 유연성 확보
# requiredDuringScheduling → preferredDuringScheduling
```
