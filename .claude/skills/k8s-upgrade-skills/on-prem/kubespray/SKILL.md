---
name: kubespray-upgrade
description: Kubespray(Ansible)로 구성된 온프레미스 Kubernetes 클러스터를 무중단으로 마이너 버전 업그레이드할 때 사용. recipe.md의 cluster_name, current_version, target_version을 사용하며, control-plane 선행·Phase별 검증 게이트·실패 시 중단을 준수.
---

# Kubespray 온프레미스 무중단 버전 업그레이드

Kubespray(Ansible)로 프로비저닝된 온프레미스 클러스터를 **무중단**으로 마이너 버전 업그레이드한다.
Control Plane 선행, 단계별 검증 통과 후에만 다음 단계로 진행한다.

---

## 전제 조건 (recipe.md 연동)

[recipe.md](recipe.md)에서 다음 값을 사용한다. 비어 있으면 업그레이드를 시작하지 않는다.

| 변수 | recipe 항목 | 용도 |
|------|-------------|------|
| CLUSTER_NAME | cluster_name | kubectl/검증 시 식별 |
| 현재버전 | current_version | 검증·버전 스킵 검사 |
| 대상버전 | target_version | upgrade-cluster.yml에 전달 |
| KUBESPRAY_PATH | (사용자 제공) | Ansible playbook 디렉터리 (예: ./kubespray) |

> **버전 제약**: 마이너 버전 1단계씩만 허용. 1.33 → 1.35 직접 업그레이드는 불가. `upgrade-cluster.yml`은 한 단계 업그레이드용이다.

---

## 실행 계획 (선언 후 진행)

```
[Phase 0] 사전 검증           → 검증: 모든 노드 Ready, PDB 충족 가능
[Phase 1] upgrade-cluster.yml → 검증: playbook exit 0, control-plane 선행
[Phase 2] 노드·Pod 검증       → 검증: 전 노드 대상 버전, 전 Pod Running
[Phase 3] 최종 검증           → 검증: kubelet 버전 일치, Insights/상태 확인
```

---

## Phase 0: 사전 검증 (Pre-flight)

**목적**: 업그레이드 진행이 안전한지 확인. 하나라도 실패 시 즉시 중단.

### 0-1. 노드 Ready

```bash
kubectl get nodes -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status,VERSION:.status.nodeInfo.kubeletVersion'
```

**검증**: 모든 노드 READY=True, STATUS=Ready. NotReady 있으면 **즉시 중단**, 원인 파악 후 복구.

### 0-2. PodDisruptionBudget

```bash
kubectl get pdb --all-namespaces \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,MIN-AVAIL:.spec.minAvailable,MAX-UNAVAIL:.spec.maxUnavailable,ALLOWED-DISRUPT:.status.disruptionsAllowed,CURRENT-HEALTHY:.status.currentHealthy,DESIRED-HEALTHY:.status.desiredHealthy'
```

**검증**: `ALLOWED-DISRUPT`가 0인 PDB가 있으면 노드 drain 시 차단됨. 해당 워크로드 사용자에게 알리고 조치 후 진행. `minAvailable == replicas`면 drain 불가 → 사용자와 협의.

### 0-3. 버전 스킵 검사

```bash
# recipe current_version, target_version으로 마이너 1단계만 허용
# 예: 1.34 → 1.35 허용, 1.33 → 1.35 거부
CURR="${current_version}"   # recipe
TARG="${target_version}"    # recipe
# 마이너 버전 차이가 1인지 확인 (스크립트 또는 수동 검증)
```

**검증**: target_version이 current_version보다 마이너 1단계만 높아야 함. 그렇지 않으면 **즉시 중단**.

### 0-4. Kubespray 버전 변수 확인

```bash
# inventory/group_vars/k8s_cluster/k8s-cluster.yml 등에서 kube_version 확인
grep -r "kube_version" "${KUBESPRAY_PATH}/inventory" "${KUBESPRAY_PATH}/group_vars" 2>/dev/null || true
```

**검증**: 현재 배포 버전과 recipe current_version 일치 여부 확인. 대상 버전은 Phase 1에서 `-e kube_version=`으로 전달하므로 기존 파일만 참고.

---

## Phase 1: upgrade-cluster.yml 실행

**목적**: Kubespray 공식 업그레이드 플레이북 실행. Control Plane이 먼저, 그 다음 worker 순으로 진행된다.

### 1-1. Ansible Playbook 실행

```bash
cd "${KUBESPRAY_PATH}"
ansible-playbook -i inventory/<your_inventory>/hosts.yaml upgrade-cluster.yml -e kube_version=${target_version}
```

- `inventory/<your_inventory>/hosts.yaml`: 실제 인벤토리 경로로 교체.
- `target_version`: recipe의 target_version (예: 1.35).

**검증**: playbook exit code 0. 실패 시 **즉시 중단**, Ansible 출력·해당 호스트 로그 수집 후 사용자 보고.

### 1-2. 실행 중 노드 순서 확인

Kubespray `upgrade-cluster.yml`은 control-plane 노드를 먼저 업그레이드한 뒤 worker를 업그레이드한다. 로그에서 control-plane 태스크 완료 후 worker 태스크가 진행되는지 확인.

---

## Phase 2: 노드·Pod 검증

### 2-1. 노드 버전

```bash
kubectl get nodes -o custom-columns='NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status'
```

**검증**: 모든 노드 VERSION이 v{대상버전}.x. 이전 버전 노드 있으면 재확인(아직 롤링 중일 수 있음).

### 2-2. FailedEvict 이벤트

```bash
kubectl get events --all-namespaces --field-selector reason=FailedEvict --sort-by='.lastTimestamp' | tail -20
```

**검증**: FailedEvict 없음. 있으면 PDB 재확인 후 사용자 보고.

### 2-3. 비정상 Pod

```bash
kubectl get pods --all-namespaces \
  --field-selector 'status.phase!=Running,status.phase!=Succeeded' \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,REASON:.status.reason'
```

**검증**: Pending, CrashLoopBackOff, Error 없음. 있으면 원인 파악 후 보고.

---

## Phase 3: 최종 검증

### 3-1. 노드 상태

```bash
kubectl get nodes -o wide --sort-by='.metadata.creationTimestamp'
```

**검증**: 모든 노드 Ready, VERSION=v{대상버전}.x.

### 3-2. Pod 상태

```bash
kubectl get pods --all-namespaces --field-selector 'status.phase!=Running,status.phase!=Succeeded' 2>/dev/null | grep -v "^NAMESPACE" | grep -v "Completed"
```

**검증**: 출력 없음(비정상 Pod 없음).

### 3-3. kube-system Pod

```bash
kubectl get pods -n kube-system -o wide
```

**검증**: 모두 Running.

---

## 비상 중단 기준 (Abort Conditions)

다음 중 하나라도 해당하면 즉시 중단하고 사용자에게 보고한다:

| 조건 | 상황 |
|------|------|
| 노드 NotReady (Phase 0) | 클러스터 불안정 |
| PDB로 drain 불가 | 서비스 중단 위험 |
| 마이너 버전 스킵 시도 | 1.33→1.35 등 거부 |
| upgrade-cluster.yml 실패 | Ansible playbook exit != 0 |
| FailedEvict 발생 | PDB 위반 drain |
| Pod CrashLoopBackOff 급증 | 호환성 문제 의심 |

---

## 안전 규칙 (Non-negotiable)

1. **버전 스킵 금지**: 마이너 1단계씩만 업그레이드.
2. **Control Plane 선행**: Kubespray upgrade-cluster.yml이 자동으로 준수함. 수동 작업 시에도 control-plane 먼저.
3. **PDB 존중**: drain 시 FailedEvict 발생하면 강제 진행 금지.
4. **Phase 역순 금지**: 검증 통과 후에만 다음 Phase 진행.
5. **Plan 없는 실행 금지**: Phase 1 전 반드시 Phase 0 전체 통과.
