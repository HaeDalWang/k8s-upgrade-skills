---
id: INF-003
name: Karpenter 호환성 검증
severity: HIGH
category: infrastructure
phase: pre-flight
applies_when: Karpenter 사용 시
---

# INF-003: Karpenter 호환성 검증

## 목적

Karpenter 버전이 대상 Kubernetes 버전과 호환되는지 확인한다. Karpenter는 특정 K8s 버전 범위만 지원하며, 호환되지 않는 버전에서는 노드 프로비저닝이 실패할 수 있다.

## 검증 항목

### 1. Karpenter 존재 여부 확인

```bash
kubectl get crd nodeclaims.karpenter.sh 2>/dev/null && echo "KARPENTER_DETECTED" || echo "KARPENTER_NOT_FOUND"
```

`KARPENTER_NOT_FOUND` → 이 규칙 건너뛰기.

### 2. 현재 Karpenter 버전 확인

```bash
kubectl get deployment -n karpenter karpenter -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null
# 또는
helm list -n karpenter -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for r in data:
    if 'karpenter' in r.get('name', ''):
        print(f\"chart={r['chart']} version={r.get('app_version', r.get('revision', 'unknown'))}\")
"
```

### 3. Karpenter-K8s 호환성 매트릭스 확인

```bash
# Karpenter 호환성은 공식 문서 참조
# https://karpenter.sh/docs/upgrading/compatibility/
# 일반적으로 Karpenter v1.x는 K8s 1.25-1.32+ 지원
# 정확한 범위는 릴리스 노트 확인 필요
echo "현재 Karpenter 버전: $(kubectl get deployment -n karpenter karpenter -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null | awk -F: '{print $2}')"
echo "대상 K8s 버전: ${TARGET_VERSION}"
```

### 4. EC2NodeClass AMI alias 호환성

```bash
# EC2NodeClass의 amiSelectorTerms에서 alias 확인
kubectl get ec2nodeclass -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for nc in data.get('items', []):
    name = nc['metadata']['name']
    terms = nc.get('spec', {}).get('amiSelectorTerms', [])
    for t in terms:
        alias = t.get('alias', '')
        if alias:
            print(f'{name}: alias={alias}')
"
```

### 5. NodePool disruption 설정 확인

```bash
kubectl get nodepool -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for np in data.get('items', []):
    name = np['metadata']['name']
    disruption = np.get('spec', {}).get('disruption', {})
    policy = disruption.get('consolidationPolicy', 'WhenEmptyOrUnderutilized')
    budgets = disruption.get('budgets', [])
    expire = np.get('spec', {}).get('template', {}).get('spec', {}).get('expireAfter', 'Never')
    print(f'{name}: consolidation={policy} expireAfter={expire} budgets={budgets}')
"
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| Karpenter 미사용 | ✅ SKIP | 규칙 건너뛰기 |
| Karpenter 버전이 TARGET_VERSION 지원 | ✅ PASS | 진행 |
| Karpenter 버전 호환성 불확실 | ⚠️ WARN | 보고 — Karpenter 업그레이드 선행 권장 |
| EC2NodeClass alias가 TARGET_VERSION과 불일치 | ⚠️ WARN | Phase 1에서 tfvars 업데이트로 해결 예정 |
| NodePool disruption budget이 0 | ⚠️ WARN | 보고 — drift 교체가 차단될 수 있음 |

## 조치 방안

```bash
# Karpenter 업그레이드 (Terraform으로 관리 시)
# terraform.tfvars에서 karpenter_chart_version 업데이트 후 apply

# NodePool disruption budget 확인/조정
kubectl edit nodepool default
# spec.disruption.budgets 확인
```
