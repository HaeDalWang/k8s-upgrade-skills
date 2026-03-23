---
id: CAP-002
name: 리소스 압박 상태 Pod 검증
severity: MEDIUM
category: capacity
phase: pre-flight
applies_when: 항상
---

# CAP-002: 리소스 압박 상태 Pod 검증

## 목적

이미 OOMKilled, CrashLoopBackOff, Evicted 상태인 Pod가 있으면 업그레이드 중 문제가 악화될 수 있다. 업그레이드 전에 기존 문제를 정리하여 깨끗한 상태에서 시작한다.

## 검증 명령어

```bash
kubectl get pods --all-namespaces -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
issues = []

for pod in data['items']:
    ns = pod['metadata']['namespace']
    name = pod['metadata']['name']
    phase = pod.get('status', {}).get('phase', '')
    
    # Evicted Pod
    if phase == 'Failed' and pod.get('status', {}).get('reason') == 'Evicted':
        issues.append({'ns': ns, 'name': name, 'issue': 'Evicted', 'severity': 'LOW'})
        continue
    
    # Container 상태 확인
    for cs in pod.get('status', {}).get('containerStatuses', []):
        # OOMKilled
        terminated = cs.get('lastState', {}).get('terminated', {})
        if terminated.get('reason') == 'OOMKilled':
            issues.append({'ns': ns, 'name': name, 'issue': 'OOMKilled (last)', 'severity': 'MEDIUM'})
        
        current_terminated = cs.get('state', {}).get('terminated', {})
        if current_terminated.get('reason') == 'OOMKilled':
            issues.append({'ns': ns, 'name': name, 'issue': 'OOMKilled (current)', 'severity': 'HIGH'})
        
        # CrashLoopBackOff
        waiting = cs.get('state', {}).get('waiting', {})
        if waiting.get('reason') == 'CrashLoopBackOff':
            restarts = cs.get('restartCount', 0)
            issues.append({'ns': ns, 'name': name, 'issue': f'CrashLoopBackOff (restarts={restarts})', 'severity': 'HIGH'})
        
        # ImagePullBackOff
        if waiting.get('reason') in ('ImagePullBackOff', 'ErrImagePull'):
            issues.append({'ns': ns, 'name': name, 'issue': waiting['reason'], 'severity': 'HIGH'})

# 결과 출력
if issues:
    high = [i for i in issues if i['severity'] == 'HIGH']
    medium = [i for i in issues if i['severity'] == 'MEDIUM']
    low = [i for i in issues if i['severity'] == 'LOW']
    
    if high:
        print('=== 즉시 조치 필요 ===')
        for i in high:
            print(f\"  {i['ns']}/{i['name']}: {i['issue']}\")
    if medium:
        print('=== 주의 필요 ===')
        for i in medium:
            print(f\"  {i['ns']}/{i['name']}: {i['issue']}\")
    if low:
        print(f'=== 정리 권장 (Evicted Pod {len(low)}개) ===')
else:
    print('리소스 압박 Pod 없음')
"
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| 문제 Pod 없음 | ✅ PASS | 진행 |
| Evicted Pod만 존재 | ✅ PASS | INFO — 자동 정리 후 진행 |
| OOMKilled (last state) | ⚠️ WARN | 보고 — 현재는 Running이지만 메모리 한계 근접 |
| CrashLoopBackOff / ImagePullBackOff | ⚠️ WARN | 보고 — 업그레이드와 무관한 기존 문제. 사용자 확인 |

## 조치 방안

```bash
# Evicted Pod 일괄 정리
kubectl get pods --all-namespaces --field-selector=status.phase=Failed \
  -o json | python3 -c "
import json, sys, subprocess
data = json.load(sys.stdin)
for pod in data['items']:
    if pod.get('status', {}).get('reason') == 'Evicted':
        ns = pod['metadata']['namespace']
        name = pod['metadata']['name']
        subprocess.run(['kubectl', 'delete', 'pod', '-n', ns, name])
        print(f'Deleted: {ns}/{name}')
"

# OOMKilled Pod 리소스 한도 조정은 업그레이드 범위 밖 — 사용자에게 보고만
```
