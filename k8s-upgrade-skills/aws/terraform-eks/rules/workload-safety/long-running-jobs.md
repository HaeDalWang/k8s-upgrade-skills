---
id: WLS-005
name: 장시간 Job/CronJob 중단 위험
severity: MEDIUM
category: workload-safety
phase: pre-flight
applies_when: 활성 Job 존재 시
---

# WLS-005: 장시간 Job/CronJob 중단 위험

## 목적

실행 중인 Job Pod가 drain으로 퇴거되면 작업이 중단된다. `restartPolicy: OnFailure`인 경우 재시작되지만, 처음부터 다시 실행되므로 장시간 작업은 시간 낭비가 크다. `restartPolicy: Never`인 경우 재시작 없이 실패로 끝난다.

## 위험 시나리오

1. 장시간 실행 중인 Job Pod (AGE > 30분): drain 시 작업 중단, 재시작 시 처음부터
2. `restartPolicy: Never` Job: drain 시 영구 실패 (재시도 없음)
3. CronJob이 방금 시작한 Job: drain 타이밍에 따라 중단 가능
4. `activeDeadlineSeconds` 설정된 Job: 재시작 후 남은 시간 부족으로 실패 가능

## 검증 명령어

```bash
# 활성 Job Pod 검출
kubectl get pods --all-namespaces --field-selector=status.phase=Running -o json | python3 -c "
import json, sys
from datetime import datetime, timezone
data = json.load(sys.stdin)
now = datetime.now(timezone.utc)
job_pods = []
for pod in data['items']:
    owners = pod.get('metadata', {}).get('ownerReferences', [])
    is_job = any(o.get('kind') == 'Job' for o in owners)
    if not is_job:
        continue
    
    ns = pod['metadata']['namespace']
    name = pod['metadata']['name']
    start = pod.get('status', {}).get('startTime', '')
    restart_policy = pod.get('spec', {}).get('restartPolicy', 'Always')
    
    if start:
        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
        age_min = (now - start_dt).total_seconds() / 60
    else:
        age_min = 0
    
    risk = 'LOW'
    if age_min > 30 and restart_policy == 'Never':
        risk = 'HIGH'
    elif age_min > 30:
        risk = 'MEDIUM'
    elif restart_policy == 'Never':
        risk = 'MEDIUM'
    
    job_pods.append({
        'ns': ns, 'name': name, 'age_min': round(age_min),
        'restart_policy': restart_policy, 'risk': risk
    })

if job_pods:
    for j in sorted(job_pods, key=lambda x: x['risk'], reverse=True):
        print(f\"{j['ns']}/{j['name']}: age={j['age_min']}min restart={j['restart_policy']} risk={j['risk']}\")
else:
    print('활성 Job Pod 없음')
"
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| 활성 Job Pod 없음 | ✅ PASS | 진행 |
| 활성 Job 있으나 age < 30분 + OnFailure | ✅ PASS | INFO 보고 |
| age > 30분 또는 restartPolicy=Never | ⚠️ WARN | 보고 — 사용자에게 Job 완료 대기 또는 중단 감수 확인 |

## 조치 방안

```bash
# 옵션 1: Job 완료까지 대기
kubectl wait --for=condition=complete job/<JOB_NAME> -n <NS> --timeout=600s

# 옵션 2: 업그레이드 시작 전 CronJob 일시 중지
kubectl patch cronjob <NAME> -n <NS> -p '{"spec":{"suspend":true}}'
# 업그레이드 완료 후 재개
kubectl patch cronjob <NAME> -n <NS> -p '{"spec":{"suspend":false}}'
```
