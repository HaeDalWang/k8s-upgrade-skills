---
id: WLS-004
name: 로컬 스토리지 Pod 데이터 유실 위험
severity: MEDIUM
category: workload-safety
phase: pre-flight
applies_when: 항상
---

# WLS-004: 로컬 스토리지 Pod 데이터 유실 위험

## 목적

emptyDir, hostPath를 사용하는 Pod는 drain 시 해당 볼륨의 데이터가 영구 삭제된다. 캐시 용도라면 문제없지만, 임시 데이터 저장소로 사용 중이라면 데이터 유실이 발생한다.

## 위험 시나리오

1. `emptyDir` (memory 또는 disk): Pod 퇴거 시 데이터 완전 삭제
2. `hostPath`: 노드 교체 시 해당 경로의 데이터 접근 불가 (새 노드에는 없음)
3. `local` PV: 특정 노드에 바인딩 — 해당 노드 drain 시 Pod Pending (WLS-003과 유사)
4. `emptyDir.sizeLimit` 초과로 eviction 발생 가능성

## 검증 명령어

```bash
kubectl get pods --all-namespaces -o json | python3 -c "
import json, sys
SYSTEM_NS = {'kube-system', 'kube-node-lease', 'kube-public', 'karpenter'}
data = json.load(sys.stdin)
risks = []
for pod in data['items']:
    ns = pod['metadata']['namespace']
    name = pod['metadata']['name']
    if ns in SYSTEM_NS:
        continue
    phase = pod.get('status', {}).get('phase', '')
    if phase not in ('Running', 'Pending'):
        continue
    
    volumes = pod.get('spec', {}).get('volumes', [])
    for vol in volumes:
        vol_name = vol.get('name', '')
        if vol.get('emptyDir') is not None:
            medium = vol['emptyDir'].get('medium', 'disk')
            size = vol['emptyDir'].get('sizeLimit', 'unlimited')
            # kube-api-access 등 자동 마운트 제외
            if 'kube-api-access' in vol_name or 'token' in vol_name:
                continue
            risks.append({
                'ns': ns, 'name': name, 'type': 'emptyDir',
                'detail': f'medium={medium} sizeLimit={size}',
                'severity': 'LOW'  # 대부분 캐시 용도
            })
        elif vol.get('hostPath') is not None:
            path = vol['hostPath'].get('path', '')
            risks.append({
                'ns': ns, 'name': name, 'type': 'hostPath',
                'detail': f'path={path}',
                'severity': 'HIGH'  # 노드 종속 데이터
            })

# 결과 출력
high = [r for r in risks if r['severity'] == 'HIGH']
low = [r for r in risks if r['severity'] == 'LOW']

if high:
    print('=== hostPath 사용 Pod (데이터 유실 위험 높음) ===')
    for r in high:
        print(f\"  {r['ns']}/{r['name']}: {r['type']} {r['detail']}\")

if low:
    print(f'=== emptyDir 사용 Pod ({len(low)}개, 대부분 캐시 용도) ===')
    # 네임스페이스별 집계만 출력
    from collections import Counter
    ns_count = Counter(r['ns'] for r in low)
    for ns, count in ns_count.most_common():
        print(f'  {ns}: {count}개')

if not risks:
    print('로컬 스토리지 사용 Pod 없음')
"
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| 로컬 스토리지 Pod 없음 | ✅ PASS | 진행 |
| emptyDir만 존재 | ✅ PASS | INFO 보고 (캐시 용도 추정) |
| hostPath 존재 | ⚠️ WARN | 보고 — 사용자에게 데이터 유실 감수 여부 확인 |
| local PV 존재 | ⚠️ WARN → WLS-003 연계 | PV AZ 검증으로 에스컬레이션 |

## 조치 방안

### hostPath 사용 Pod
```bash
# 데이터 백업 후 진행
# 또는 PVC로 마이그레이션 권장
```

### emptyDir 사용 Pod
- 대부분 캐시/임시 데이터이므로 별도 조치 불필요
- 사용자에게 목록만 보고
