---
name: terraform-eks-upgrade
description: Terraform으로 구성된 EKS 클러스터를 무중단(Zero-Downtime)으로 버전 업그레이드할 때 사용. 'EKS 업그레이드', 'terraform으로 EKS 업그레이드', 'EKS 버전 올려줘' 등 요청 시 실행. recipe.md의 cluster_name, current_version, target_version, terraform_path를 사용하며, Control Plane → Add-on → Data Plane 순서와 Phase별 검증 게이트를 준수. .mcp.json의 EKS/Kubernetes MCP 사용.
---

# Terraform EKS 무중단 버전 업그레이드

Terraform으로 관리되는 EKS 클러스터를 **무중단**으로 버전 업그레이드한다.
AWS 권장 순서 Control Plane → Add-on → Data Plane을 엄격히 준수하며, 각 Phase 경계에서 검증 통과 후에만 다음 단계로 진행한다.

**MCP**: 이 스킬 실행 시 프로젝트 루트 .mcp.json에 정의된 EKS MCP(`get_eks_insights`, `list_k8s_resources` 등)와 Kubernetes MCP를 사용한다.

---

## 전제 조건 (recipe.md 연동)

루트 [recipe.md](recipe.md)에서 다음 값을 사용한다. 비어 있으면 업그레이드를 시작하지 않는다.

| 변수 | recipe 항목 | 용도 |
|------|-------------|------|
| CLUSTER_NAME | cluster_name | aws eks / kubectl 대상 |
| 현재버전 | current_version | 검증·Plan 확인 |
| 대상버전(target_version) | target_version | 업그레이드 목표 |
| TF_DIR | terraform_path | terraform plan/apply 작업 디렉터리 |

> **버전 제약**: EKS는 마이너 버전 1단계씩만 업그레이드 가능. 1.33 → 1.35 직접 업그레이드는 불가.

---

## 실행 계획 (선언 후 진행)

```
[Phase 0] 사전 검증         → 검증: EKS Insights 전부 PASSING, PDB 충족 가능
[Phase 1] tfvars 업데이트   → 검증: eks_cluster_version, AMI alias 값 확인
[Phase 2] Control Plane     → 검증: 클러스터 status=ACTIVE, version={대상버전}
[Phase 3] Add-on 안전 게이트→ 검증: 모든 Add-on status=ACTIVE
[Phase 4] Data Plane        → 검증: 모든 노드 Ready, 버전={대상버전}
[Phase 5] Karpenter 노드    → 검증: Drift 교체 완료, 모든 노드 Ready
[Phase 6] 전체 Apply        → 검증: terraform apply exit code 0
[Phase 7] 최종 검증         → 검증: 전 노드 버전 일치, 전 Pod Running
```

완료 보고 형식·비상 중단 기준: [reference.md](reference.md) 참조.

---

## Phase 0: 사전 검증 (Pre-flight)

**목적**: 업그레이드 진행 가능 여부 확인. 하나라도 실패 시 즉시 중단.

### 0-1. 클러스터 상태

```bash
aws eks describe-cluster \
  --name ${CLUSTER_NAME} \
  --query 'cluster.{version:version, status:status, endpoint:endpoint}' \
  --output json
```

**검증**: `status == "ACTIVE"`. 아니면 중단.

### 0-2. EKS Upgrade Readiness Insights

MCP `get_eks_insights` 사용: `category="UPGRADE_READINESS"`, `cluster_name="${CLUSTER_NAME}"`.

**검증**: 모든 insight `status == "PASSING"`. WARNING은 협의, ERROR이면 **즉시 중단**.

### 0-3. PodDisruptionBudget

```bash
kubectl get pdb --all-namespaces \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,MIN-AVAIL:.spec.minAvailable,MAX-UNAVAIL:.spec.maxUnavailable,ALLOWED-DISRUPT:.status.disruptionsAllowed,CURRENT-HEALTHY:.status.currentHealthy,DESIRED-HEALTHY:.status.desiredHealthy'
```

**검증**: `ALLOWED-DISRUPT`가 0인 PDB가 있으면 Drain 차단 → 사용자에게 알리고 조치 후 진행. `minAvailable == replicas`면 Drain 불가 → 협의 필수.

### 0-4. 대상 버전 AMI 조회

```bash
TARGET_VERSION="${target_version}"  # recipe target_version

# AL2023
aws ssm get-parameters-by-path \
  --path "/aws/service/eks/optimized-ami/${TARGET_VERSION}/amazon-linux-2023/" \
  --recursive --query 'Parameters[].Name' --output text | tr '\t' '\n' | \
  grep -v "recommended" | awk -F '/' '{print $10}' | sed -r 's/.*(v[[:digit:]]+)$/\1/' | sort -u | tail -5

# Bottlerocket
aws ssm get-parameters-by-path \
  --path "/aws/service/bottlerocket/aws-k8s-${TARGET_VERSION}" \
  --recursive --query 'Parameters[].Name' --output text | tr '\t' '\n' | \
  grep -v "latest" | awk -F '/' '{print $7}' | sort -u | tail -5
```

조회한 최신 AMI/버전을 Phase 1에서 사용.

### 0-5. 노드 상태

MCP `list_k8s_resources`: `kind="Node"`, `api_version="v1"`, `cluster_name="${CLUSTER_NAME}"`.

**검증**: 모든 노드 Ready 조건 True. NotReady 있으면 **즉시 중단**.

---

## Phase 1: terraform.tfvars 업데이트

### 1-1. 현재 값 확인

```bash
grep -E "eks_cluster_version|eks_node_ami_alias" "${TF_DIR}/terraform.tfvars"
```

### 1-2. 수정 항목

- `eks_cluster_version` = 현재버전 → 대상버전 (recipe)
- `eks_node_ami_alias_al2023` = al2023@0-4에서 조회한 최신
- `eks_node_ami_alias_bottlerocket` = bottlerocket@0-4에서 조회한 최신

Edit 도구로 위 3항목 수정.

### 1-3. 재확인

```bash
grep -E "eks_cluster_version|eks_node_ami_alias" "${TF_DIR}/terraform.tfvars"
```

**검증**: 3항목 모두 대상 값으로 변경됨.

---

## Phase 2: Control Plane 업그레이드

### 2-1. Plan (module.eks만)

```bash
cd "${TF_DIR}" && terraform plan -target=module.eks 2>&1 | tail -50
```

**검증**: `aws_eks_cluster.this` version 변경, `aws_eks_node_group.this` release_version 변경 표시, exit 0. 예상 외 리소스 포함 시 사용자 확인.

### 2-2. Apply

```bash
cd "${TF_DIR}" && terraform apply -target=module.eks -auto-approve 2>&1
```

**검증 (완료 후)**:

```bash
aws eks describe-cluster --name "${CLUSTER_NAME}" --query 'cluster.{version:version, status:status}' --output json
```

- `version == 대상버전` AND `status == "ACTIVE"` → Phase 3
- `status == "UPDATING"` → 대기 후 재확인
- `status == "FAILED"` → **즉시 중단**, 오류 보고

---

## Phase 3: Add-on 안전 게이트

### 3-1. Add-on 상태

```bash
aws eks list-addons --cluster-name "${CLUSTER_NAME}" --query 'addons[]' --output text | tr '\t' '\n' | while read addon; do
  aws eks describe-addon --cluster-name "${CLUSTER_NAME}" --addon-name "$addon" \
    --query '{name:addon.addonName, version:addon.addonVersion, status:addon.status}' --output json
done
```

**검증**: 모든 Add-on `status == "ACTIVE"`. UPDATING이면 대기 후 재확인. DEGRADED/CREATE_FAILED면 **즉시 중단**.

### 3-2. kube-system Pod

```bash
kubectl get pods -n kube-system \
  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,STATUS:.status.phase,NODE:.spec.nodeName' --sort-by='.metadata.name'
```

**검증**: 모두 Running. Pending/CrashLoopBackOff 있으면 원인 파악 후 보고.

---

## Phase 4: Data Plane (Managed Node Group) 모니터링

### 4-1. 노드 버전

```bash
kubectl get nodes -o custom-columns='NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status'
```

**검증**: 모든 노드 VERSION이 v{대상버전}.x. 이전 버전 노드 있으면 Rolling 진행 중 → 재확인.

### 4-2. FailedEvict

```bash
kubectl get events --all-namespaces --field-selector reason=FailedEvict --sort-by='.lastTimestamp' | tail -20
```

**검증**: FailedEvict 없음. 있으면 PDB 재확인 후 보고.

### 4-3. 비정상 Pod

```bash
kubectl get pods --all-namespaces \
  --field-selector 'status.phase!=Running,status.phase!=Succeeded' \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,REASON:.status.reason'
```

**검증**: Pending/CrashLoopBackOff/Error 없음.

---

## Phase 5: Karpenter 노드 (Drift) 모니터링

Karpenter 미사용 시 이 Phase는 검증만 하고 통과 처리.

### 5-1. Drift 확인

```bash
kubectl get nodeclaims -o yaml | grep -A5 "type: Drifted"
```

또는 MCP `list_k8s_resources`: kind=NodeClaim, api_version=karpenter.sh/v1.

### 5-2. 교체 이벤트

```bash
kubectl get events -n kube-system --field-selector 'involvedObject.kind=Node' --sort-by='.lastTimestamp' | grep -E "Disrupting|Terminating|Launching" | tail -20
```

**검증**: PDB 위반 이벤트 없음.

### 5-3. Karpenter 노드 버전

```bash
kubectl get nodes -l karpenter.sh/nodepool \
  -o custom-columns='NAME:.metadata.name,AMI:.metadata.labels.karpenter\.k8s\.aws/instance-ami-id,VERSION:.status.nodeInfo.kubeletVersion'
```

**검증**: 모두 v{대상버전}.x.

---

## Phase 6: 전체 Terraform Apply

### 6-1. 전체 Plan

```bash
cd "${TF_DIR}" && terraform plan 2>&1 | tail -30
```

**검증**: 파괴적 변경(-/+ destroy) 있으면 **중단**, 사용자 확인.

### 6-2. 전체 Apply

```bash
cd "${TF_DIR}" && terraform apply -auto-approve 2>&1
```

**검증**: exit code 0.

---

## Phase 7: 최종 검증

### 7-1. 클러스터

```bash
aws eks describe-cluster --name "${CLUSTER_NAME}" --query 'cluster.{version:version, status:status}' --output json
```

### 7-2. 노드

```bash
kubectl get nodes -o wide --sort-by='.metadata.creationTimestamp'
```

**검증**: 모든 노드 Ready, VERSION=v{대상버전}.x.

### 7-3. Pod

```bash
kubectl get pods --all-namespaces --field-selector 'status.phase!=Running,status.phase!=Succeeded' 2>/dev/null | grep -v "^NAMESPACE" | grep -v "Completed"
```

**검증**: 출력 없음.

### 7-4. EKS Insights

MCP `get_eks_insights`: category=UPGRADE_READINESS. **검증**: 모두 PASSING.

---

## 안전 규칙 (Non-negotiable)

1. **버전 스킵 금지**: 1.33 → 1.35 직접 업그레이드 거부
2. **Control Plane 선행**: Data Plane이 Control Plane보다 상위 버전 금지
3. **PDB 존중**: FailedEvict 시 강제 진행 금지
4. **Phase 역순 금지**
5. **Plan 없는 Apply 금지**: 모든 apply 전 plan 확인
