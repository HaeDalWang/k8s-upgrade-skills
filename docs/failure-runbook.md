# 실패 시나리오 런북 (Failure Runbook)

업그레이드 중 "보고 후 판단 대기" 상태가 되었을 때, 사용자가 실제로 해야 할 것들입니다.

---

## Phase 0: 사전 검증 실패

### CRITICAL: PDB 차단 (WLS-001)

증상: `disruptionsAllowed=0` — drain 시 노드가 영원히 대기

```bash
# 1. 차단 중인 PDB 확인
kubectl get pdb -A -o wide

# 2. 해당 PDB의 타겟 Pod 확인
kubectl get pdb <NAME> -n <NS> -o yaml | grep -A5 selector

# 3. 해결 옵션 (택 1)
# 옵션 A: 레플리카 증가 (PDB 요구치보다 1개 이상 여유)
kubectl scale deployment <NAME> -n <NS> --replicas=<CURRENT+1>

# 옵션 B: PDB 완화
kubectl patch pdb <NAME> -n <NS> --type merge \
  -p '{"spec":{"minAvailable":null,"maxUnavailable":1}}'

# 옵션 C: 업그레이드 윈도우 동안 PDB 일시 삭제 (위험)
kubectl delete pdb <NAME> -n <NS>
# 업그레이드 완료 후 반드시 재생성
```

### CRITICAL: PV AZ 위험 (WLS-003)

증상: PV가 바인딩된 AZ에 노드가 1개뿐 — drain 시 Pod Pending 확정

```bash
# 1. 위험 PV 확인
kubectl get pv -o json | python3 -c "
import json, sys
for pv in json.load(sys.stdin)['items']:
    if pv['status']['phase'] != 'Bound': continue
    na = pv.get('spec',{}).get('nodeAffinity',{}).get('required',{}).get('nodeSelectorTerms',[])
    for t in na:
        for e in t.get('matchExpressions',[]):
            if 'zone' in e.get('key',''):
                claim = pv['spec'].get('claimRef',{})
                print(f\"{claim.get('namespace')}/{claim.get('name')} → AZ={e['values']}\")"

# 2. 해결 옵션 (택 1)
# 옵션 A: 해당 AZ에 노드 추가
# Karpenter 사용 시 — NodePool에 해당 AZ 포함 확인
kubectl get nodepool -o yaml | grep -A5 topology.kubernetes.io/zone
# MNG 사용 시 — desired_size 증가 (terraform.tfvars 수정 후 apply)

# 옵션 B: 다운타임 감수하고 진행 (StatefulSet 단일 레플리카인 경우)
# → Agent에게 "WLS-003 경고를 승인하고 진행" 지시
```

### CRITICAL: AMI 미출시 (INF-002)

증상: 대상 버전의 AMI가 아직 AWS에 없음

```bash
# 확인
aws ssm get-parameters-by-path \
  --path "/aws/service/eks/optimized-ami/${TARGET_VERSION}/amazon-linux-2023/x86_64/standard" \
  --recursive --query 'Parameters[0].Name'

# 대응: 대기. AWS가 AMI를 릴리스할 때까지 기다려야 합니다.
# 일반적으로 EKS 버전 출시 후 1~2주 내 AMI가 제공됩니다.
```

### HIGH: 단일 레플리카 (WLS-002)

증상: replicas=1 워크로드가 drain 시 일시적 서비스 중단

```bash
# 1. 목록 확인 (Agent가 보고한 리스트)
# 2. 판단 기준:
#    - 내부 도구/배치 작업 → 다운타임 감수 가능 → 승인
#    - 사용자 대면 서비스 → 업그레이드 전 replicas 증가
kubectl scale deployment <NAME> -n <NS> --replicas=2
# 업그레이드 완료 후 원복
```

---

## Phase 2: Control Plane 업그레이드 실패

### Control Plane status=FAILED

EKS Control Plane 업그레이드는 비가역적입니다. 다운그레이드할 수 없습니다.

```bash
# 1. 현재 상태 확인
aws eks describe-cluster --name ${CLUSTER_NAME} \
  --query 'cluster.{status:status, version:version}' --output json

# 2. 상태별 대응
# FAILED → AWS Support 케이스 오픈
#   - 클러스터가 FAILED 상태에서 복구되지 않으면 AWS 지원이 필요합니다
#   - https://console.aws.amazon.com/support/home

# UPDATING (장시간) → 대기
#   - Control Plane 업그레이드는 보통 8~15분 소요
#   - 30분 이상 UPDATING이면 AWS Support 문의

# 3. Data Plane은 아직 이전 버전
#   - Control Plane만 업그레이드된 상태는 정상 (mixed-version)
#   - kubelet은 CP보다 2 마이너 버전까지 허용
#   - Data Plane 업그레이드를 수동으로 완료해야 합니다
```

### terraform apply 실패 (exit code != 0)

```bash
# 1. 에러 메시지 확인
cd ${TF_DIR} && terraform plan 2>&1 | tail -30

# 2. 일반적인 원인
# - State lock: 다른 terraform 프로세스가 실행 중
terraform force-unlock <LOCK_ID>

# - Provider 인증 만료
aws sts get-caller-identity  # IAM 자격 증명 확인

# - State drift: 수동 변경이 있었음
terraform refresh
terraform plan  # 변경 내용 재확인
```

---

## Phase 4: Data Plane Rolling Update 문제

### FailedEvict 이벤트 (PDB 차단)

```bash
# 1. 차단 원인 확인
kubectl get events -A --field-selector reason=FailedEvict \
  --sort-by='.lastTimestamp' | tail -10

# 2. 차단 중인 PDB 확인
kubectl get pdb -A | grep -v 'ALLOWED' | grep '0'

# 3. 해결: Phase 0 WLS-001과 동일
# 레플리카 증가 또는 PDB 완화 후 rolling update가 자동 재개됩니다
```

### Pod Pending (노드 용량 부족)

```bash
# 1. Pending Pod 확인
kubectl get pods -A | grep Pending

# 2. 원인 확인
kubectl describe pod <POD_NAME> -n <NS> | grep -A5 Events

# 3. 해결
# Insufficient cpu/memory → 노드 추가
# Karpenter: 자동 스케일아웃 대기 (1~2분)
# MNG: desired_size 증가
aws eks update-nodegroup-config \
  --cluster-name ${CLUSTER_NAME} \
  --nodegroup-name <NODEGROUP_NAME> \
  --scaling-config desiredSize=<CURRENT+1>
```

### CrashLoopBackOff 급증

```bash
# 1. 영향받는 Pod 확인
kubectl get pods -A | grep CrashLoop

# 2. 로그 확인
kubectl logs <POD_NAME> -n <NS> --previous

# 3. 판단
# - 업그레이드 전에도 있었던 문제 → 업그레이드와 무관, 진행 가능
# - 업그레이드 후 새로 발생 → API 호환성 문제 가능성
#   - deprecated API 사용 여부 확인
kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis
```

---

## Phase 5: Karpenter 노드 교체 문제

### Drift 교체가 시작되지 않음

```bash
# 1. NodeClaim drift 상태 확인
kubectl get nodeclaims -o yaml | grep -A5 "type: Drifted"

# 2. NodePool disruption budget 확인
kubectl get nodepool -o yaml | grep -A3 budgets
# budget이 0이면 교체가 차단됨

# 3. EC2NodeClass AMI alias 확인
kubectl get ec2nodeclass -o yaml | grep alias
# alias가 업데이트되지 않았으면 drift가 감지되지 않음
# → terraform apply로 EC2NodeClass 업데이트 필요
```

---

## Phase 6: Terraform 전체 동기화 문제

### 예상치 못한 destroy 감지

```bash
# 1. 어떤 리소스가 destroy 대상인지 확인
cd ${TF_DIR} && terraform plan | grep -E '^\s*-|destroy'

# 2. 판단
# - time_sleep, null_resource → 무해, 진행 가능
# - aws_eks_node_group, aws_launch_template → 위험! 진행 금지
#   → 원인 분석 후 lifecycle 설정 또는 state 조정

# 3. 안전한 진행
# destroy 대상을 제외하고 apply
terraform apply -target=<SAFE_RESOURCE_1> -target=<SAFE_RESOURCE_2>
```

---

## 공통: 업그레이드 중단 후 재개

업그레이드가 중간에 중단된 경우:

```bash
# 1. 현재 상태 파악
aws eks describe-cluster --name ${CLUSTER_NAME} \
  --query 'cluster.{version:version, status:status}'
kubectl get nodes -o custom-columns='NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion'

# 2. 상태별 재개 방법
# CP=TARGET, DP=CURRENT → Phase 4부터 재개 (recipe.yaml 수정 불필요)
# CP=CURRENT, DP=CURRENT → Phase 2부터 재개
# CP=TARGET, DP=TARGET → Phase 7 최종 검증만 실행

# 3. Agent에게 지시
# "Phase N부터 재개해줘" — Agent가 해당 Phase의 Gate부터 검증 시작
```
