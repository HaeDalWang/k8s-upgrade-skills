---
id: WLS-002
name: 단일 레플리카 서비스 중단 위험
severity: HIGH
category: workload-safety
phase: pre-flight
applies_when: 항상
---

# WLS-002: 단일 레플리카 서비스 중단 위험

## 목적

replicas=1인 Deployment/StatefulSet은 drain 시 해당 Pod가 퇴거되면 새 Pod가 다른 노드에서 Ready 될 때까지 서비스가 완전히 중단된다. PDB가 있어도 결국 1개를 퇴거해야 하므로 다운타임은 불가피하다.

## 위험 시나리오

1. replicas=1 Deployment + Service: drain 시 Pod 퇴거 → 새 Pod Pending/ContainerCreating 동안 서비스 불가
2. replicas=1 StatefulSet + PVC: drain 시 Pod 퇴거 → PV가 다른 AZ에 있으면 재스케줄 불가 (WLS-003과 연계)
3. replicas=1 + PDB(minAvailable=1): drain이 영원히 차단됨 (WLS-001과 연계)
4. DaemonSet은 노드당 1개가 정상이므로 제외

## 검증 명령어

```bash
# Deployment replicas=1 검출 (kube-system, karpenter 등 시스템 네임스페이스 제외)
kubectl get deployments --all-namespaces -o json | python3 -c "
import json, sys
SYSTEM_NS = {'kube-system', 'kube-node-lease', 'kube-public', 'karpenter', 'cert-manager'}
data = json.load(sys.stdin)
singles = []
for d in data['items']:
    ns = d['metadata']['namespace']
    name = d['metadata']['name']
    replicas = d.get('spec', {}).get('replicas', 1)
    if ns in SYSTEM_NS:
        continue
    if replicas == 1:
        # Service 연결 여부 확인을 위해 selector 추출
        labels = d.get('spec', {}).get('template', {}).get('metadata', {}).get('labels', {})
        singles.append({'ns': ns, 'name': name, 'kind': 'Deployment', 'labels': labels})
for s in singles:
    print(f\"{s['ns']}/{s['name']} ({s['kind']}): replicas=1\")
if not singles:
    print('단일 레플리카 Deployment 없음')
"

# StatefulSet replicas=1 검출
kubectl get statefulsets --all-namespaces -o json | python3 -c "
import json, sys
SYSTEM_NS = {'kube-system', 'kube-node-lease', 'kube-public', 'karpenter', 'cert-manager'}
data = json.load(sys.stdin)
singles = []
for s in data['items']:
    ns = s['metadata']['namespace']
    name = s['metadata']['name']
    replicas = s.get('spec', {}).get('replicas', 1)
    if ns in SYSTEM_NS:
        continue
    if replicas == 1:
        has_pvc = len(s.get('spec', {}).get('volumeClaimTemplates', [])) > 0
        singles.append({'ns': ns, 'name': name, 'has_pvc': has_pvc})
for s in singles:
    pvc_warn = ' [PVC 있음 — AZ 고정 위험]' if s['has_pvc'] else ''
    print(f\"{s['ns']}/{s['name']} (StatefulSet): replicas=1{pvc_warn}\")
if not singles:
    print('단일 레플리카 StatefulSet 없음')
"
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| 단일 레플리카 워크로드 없음 | ✅ PASS | 진행 |
| 단일 레플리카 존재 (시스템 NS 제외) | ⚠️ WARN | 목록 보고, 사용자에게 다운타임 감수 여부 확인 |
| 단일 레플리카 + PDB(minAvailable=1) | ❌ FAIL → WLS-001 CRITICAL로 에스컬레이션 | drain 불가 |

## 조치 방안

### 다운타임 최소화
```bash
# 옵션 1: 업그레이드 전 일시적으로 replicas 증가
kubectl scale deployment <NAME> -n <NS> --replicas=2

# 옵션 2: 업그레이드 후 원복
kubectl scale deployment <NAME> -n <NS> --replicas=1
```

### StatefulSet + PVC인 경우
- replicas 증가가 어려울 수 있음 (PVC 바인딩, 라이선스 등)
- 사용자에게 다운타임 예상 시간 안내 (일반적으로 30초~2분)
- WLS-003 규칙과 함께 PV AZ 제약 확인 필수

### 허용 가능한 예외
- Operator 패턴 (controller replicas=1은 일반적): 사용자에게 보고하되 차단하지 않음
- CronJob에 의해 생성된 일시적 Pod: 무시
