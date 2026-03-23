---
id: COM-002
name: 버전 호환성 검증
severity: CRITICAL
category: common
phase: pre-flight
applies_when: 항상
---

# COM-002: 버전 호환성 검증

## 목적

Kubernetes는 마이너 버전 +1 단계씩만 업그레이드를 지원한다. 또한 kubelet 버전이 control plane보다 2단계 이상 낮으면 지원 범위를 벗어난다. 업그레이드 전 현재 클러스터의 모든 컴포넌트 버전이 정상 범위인지 확인한다.

## 검증 항목

### 1. 마이너 버전 +1 제약

```bash
# recipe.md에서 추출한 CURRENT_VERSION, TARGET_VERSION으로 검증
python3 -c "
current = '${CURRENT_VERSION}'
target = '${TARGET_VERSION}'
curr_minor = int(current.split('.')[1])
targ_minor = int(target.split('.')[1])
gap = targ_minor - curr_minor
if gap == 1:
    print(f'OK: {current} → {target} (minor +1)')
elif gap == 0:
    print(f'SKIP: 이미 동일 버전')
elif gap > 1:
    print(f'FAIL: 버전 건너뛰기 불가 ({current} → {target}, gap={gap})')
elif gap < 0:
    print(f'FAIL: 다운그레이드 불가 ({current} → {target})')
"
```

### 2. kubelet 버전 skew 검증

```bash
kubectl get nodes -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
target = '${TARGET_VERSION}'
targ_minor = int(target.split('.')[1])
issues = []
for node in data['items']:
    name = node['metadata']['name']
    version = node['status']['nodeInfo']['kubeletVersion']
    # v1.33.7-eks-xxxx → 33
    node_minor = int(version.split('.')[1])
    skew = targ_minor - node_minor
    if skew > 2:
        issues.append(f'{name}: kubelet {version} → target {target} (skew={skew}, 지원 범위 초과)')
    elif skew == 2:
        issues.append(f'{name}: kubelet {version} → target {target} (skew={skew}, 경계값)')
    else:
        print(f'{name}: kubelet {version} → target {target} (skew={skew}, OK)')
for i in issues:
    print(f'⚠️ {i}')
if not issues:
    print('모든 노드 kubelet 버전 skew 정상')
"
```

### 3. Deprecated API 사용 여부

```bash
# EKS Insights에서 deprecated API 관련 insight 확인
aws eks list-insights --cluster-name ${CLUSTER_NAME} \
  --filter '{categories: ["UPGRADE_READINESS"]}' \
  --query 'insights[?contains(name, `deprecated`) || contains(name, `API`)].{name:name, status:insightStatus.status, description:description}' \
  --output table
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| minor +1, 모든 kubelet skew ≤ 2, deprecated API 없음 | ✅ PASS | 진행 |
| minor gap > 1 | ❌ FAIL | STOP — 한 단계씩 업그레이드 필요 |
| kubelet skew > 2 | ❌ FAIL | STOP — 해당 노드 먼저 업그레이드 필요 |
| deprecated API 사용 감지 | ⚠️ WARN | 보고 — 업그레이드 후 API 제거 가능성 안내 |
