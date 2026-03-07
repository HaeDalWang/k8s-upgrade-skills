---
name: terraform-eks-upgrade
description: >
  Zero-downtime EKS cluster version upgrade managed by Terraform.
  Follows AWS best-practice order: Control Plane → Add-ons → Data Plane.
  Uses recipe.md for cluster_name, current_version, target_version; auto-discovers TF_DIR.
  Trigger keywords: 'EKS upgrade', 'terraform EKS upgrade', 'EKS 버전 업그레이드', 'EKS 버전 올려줘'
---

# Terraform EKS Zero-Downtime Version Upgrade

Upgrade a Terraform-managed EKS cluster with **zero downtime**.
Strictly follow the AWS-recommended order: **Control Plane → Add-ons → Data Plane**.
Each phase boundary requires validation to pass before proceeding.

**MCP**: Use EKS MCP (`get_eks_insights`, `list_k8s_resources`) and Kubernetes MCP from `.mcp.json`.
If an MCP call fails, fall back to the equivalent AWS CLI / kubectl command shown in each step.

---

## Prerequisites (from recipe.md)

Read these values from `recipe.md`. If any is empty, do NOT start the upgrade.

| Variable | Recipe Field | Purpose |
|---|---|---|
| `CLUSTER_NAME` | `cluster_name` | Target for aws eks / kubectl commands |
| `CURRENT_VERSION` | `current_version` | Pre-flight validation |
| `TARGET_VERSION` | `target_version` | Upgrade target |
| `TF_DIR` | (auto-discover) | Directory containing `terraform.tfvars` or `*.tf` files — search the project |
| `EKS_MODULE` | (auto-discover) | Terraform module name for EKS — inspect `*.tf` files in TF_DIR |

> **Version constraint**: EKS supports only minor +1 upgrades. 1.33 → 1.35 is rejected.

---

## Execution Plan (Declare, Then Execute)

Print this plan to the user before starting, filling in the actual version numbers:

```
[Phase 0] Pre-flight Validation     → Gate: EKS Insights PASSING, PDB safe, all nodes Ready
[Phase 1] Discovery & tfvars Update → Gate: TF_DIR found, version/AMI values updated
[Phase 2] Control Plane Upgrade     → Gate: cluster status=ACTIVE, version={TARGET_VERSION}
[Phase 3] Add-on Safety Gate        → Gate: all add-ons status=ACTIVE
[Phase 4] Data Plane (MNG) Rolling  → Gate: all nodes Ready, version=v{TARGET_VERSION}.x
[Phase 5] Karpenter Nodes (if any)  → Gate: drift replacement complete, all nodes Ready
[Phase 6] Full Terraform Sync       → Gate: terraform plan shows no unexpected changes
[Phase 7] Final Validation          → Gate: cluster healthy, all pods Running
```

Report format and abort conditions: see [reference.md](reference.md).

---

## Phase 0: Pre-flight Validation

**Purpose**: Confirm the cluster is healthy and the upgrade is safe. If ANY check fails → STOP.

### 0-1. Cluster Status

```bash
aws eks describe-cluster \
  --name ${CLUSTER_NAME} \
  --query 'cluster.{version:version, status:status, endpoint:endpoint}' \
  --output json
```

**Gate**: `status == "ACTIVE"` AND `version == CURRENT_VERSION`. Otherwise STOP.

### 0-2. EKS Upgrade Readiness Insights

Use MCP `get_eks_insights`: `category="UPGRADE_READINESS"`, `cluster_name="${CLUSTER_NAME}"`.

Fallback CLI:
```bash
aws eks list-insights --cluster-name ${CLUSTER_NAME} \
  --filter '{categories: ["UPGRADE_READINESS"]}' \
  --query 'insights[].{name:name, status:insightStatus.status}' --output table
```

**Gate**:
- All insights `PASSING` → Proceed.
- Any insight `WARNING` → Report the specific insight to user and ask whether to proceed.
- Any insight `ERROR` → **STOP immediately**. Show the insight details.

### 0-3. PodDisruptionBudget Audit

```bash
kubectl get pdb --all-namespaces \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,MIN-AVAIL:.spec.minAvailable,MAX-UNAVAIL:.spec.maxUnavailable,ALLOWED-DISRUPT:.status.disruptionsAllowed,CURRENT-HEALTHY:.status.currentHealthy,DESIRED-HEALTHY:.status.desiredHealthy'
```

**Gate**:
- `ALLOWED-DISRUPT == 0` for any PDB → Drain will be blocked. Report the specific PDB and namespace. Ask user to resolve before proceeding.
- `minAvailable == replicas` (i.e. DESIRED-HEALTHY == CURRENT-HEALTHY and ALLOWED-DISRUPT == 0) → Drain impossible. **User must adjust PDB or scale up first**.

### 0-4. Target Version AMI Lookup

**Principle**: Only look up AMI types actually used in this project. Never assume AL2/Bottlerocket/GPU — detect from project files.

**0-4-1. Detect AMI types from project**

```bash
grep -rE 'ami_type|ami_alias|amiSelectorTerms|ami_id|eks_node_ami_alias' \
  "${TF_DIR}" --include="*.tf" --include="*.tfvars" --include="*.tfvars.example" 2>/dev/null
```

From the output, identify which AMI type variables exist (e.g. `eks_node_ami_alias_al2023`, `eks_node_ami_alias_bottlerocket`).

**0-4-2. Query latest AMI per detected type**

For each detected AMI type, query the corresponding SSM path:

| AMI Type Pattern | SSM Path |
|---|---|
| `al2023` | `/aws/service/eks/optimized-ami/${TARGET_VERSION}/amazon-linux-2023/` |
| `al2` | `/aws/service/eks/optimized-ami/${TARGET_VERSION}/amazon-linux-2/` |
| `bottlerocket` | `/aws/service/bottlerocket/aws-k8s-${TARGET_VERSION}` |

**AL2023 example**:
```bash
aws ssm get-parameters-by-path \
  --path "/aws/service/eks/optimized-ami/${TARGET_VERSION}/amazon-linux-2023/x86_64/standard" \
  --recursive \
  --query 'Parameters[].Name' --output text \
  | tr '\t' '\n' | awk -F'/' '{print $NF}' | sort -V | tail -5
```

**Bottlerocket example**:
```bash
aws ssm get-parameters-by-path \
  --path "/aws/service/bottlerocket/aws-k8s-${TARGET_VERSION}/x86_64" \
  --recursive \
  --query 'Parameters[].Name' --output text \
  | tr '\t' '\n' | grep -E '[0-9]+\.[0-9]+\.[0-9]+' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | sort -t. -k1,1n -k2,2n -k3,3n | uniq | tail -5
```

> macOS/Alpine 등 `-P` 미지원 환경을 고려해 POSIX ERE(`-E`)를 사용한다.

**Gate**: At least one AMI version retrieved for each detected type. If SSM returns empty → report and STOP.

### 0-5. Node Health

Use MCP `list_k8s_resources`: `kind="Node"`, `api_version="v1"`, `cluster_name="${CLUSTER_NAME}"`.

Fallback:
```bash
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status,VERSION:.status.nodeInfo.kubeletVersion'
```

**Gate**: ALL nodes `READY=True`. Any `NotReady` → **STOP**.

---

## Phase 1: Discovery & terraform.tfvars Update

### 1-1. Auto-discover TF_DIR

Search the project for the directory containing Terraform configuration:

```bash
find . -name 'terraform.tfvars' -o -name '*.tf' | head -20
```

Identify the directory containing both `terraform.tfvars` and EKS-related `*.tf` files.
Set `TF_DIR` to this directory path.

### 1-2. Auto-discover EKS Module Name

```bash
grep -rE 'module\s+"[^"]*"' "${TF_DIR}"/*.tf | grep -iE 'eks|cluster'
```

The EKS module name (e.g. `module.eks`, `module.eks_cluster`) is needed for targeted plan/apply in Phase 2.
If multiple candidates exist, inspect the module source to confirm which one wraps `aws_eks_cluster`.

### 1-3. Read Current Values

```bash
grep -E 'eks_cluster_version|eks_node_ami_alias' "${TF_DIR}/terraform.tfvars"
```

### 1-4. Update Values

Using the edit tool, update these variables in `${TF_DIR}/terraform.tfvars`:

- `eks_cluster_version` → `"${TARGET_VERSION}"`
- Each `eks_node_ami_alias_*` variable → latest value from Phase 0-4 lookup
  - Only update variables that actually exist in the file
  - If current value already matches the latest for TARGET_VERSION, leave unchanged

### 1-5. Verify Update

```bash
grep -E 'eks_cluster_version|eks_node_ami_alias' "${TF_DIR}/terraform.tfvars"
```

**Gate**: All values reflect the target version. Report the before/after diff to the user.

---

## Phase 2: Control Plane Upgrade

### 2-1. Targeted Plan

```bash
cd "${TF_DIR}" && terraform plan -target=${EKS_MODULE} 2>&1 | tail -60
```

**Gate**:
- `aws_eks_cluster` shows version change `CURRENT_VERSION → TARGET_VERSION` → Expected.
- `aws_eks_node_group` shows `release_version` change → Expected (rolling update).
- Any resource with `-/+` (destroy-recreate) that is NOT `time_sleep` → **STOP and ask user**.
- Exit code 0.

### 2-2. Targeted Apply

```bash
cd "${TF_DIR}" && terraform apply -target=${EKS_MODULE} -auto-approve 2>&1
```

This operation typically takes **8–15 minutes** for control plane + node group rolling update.

### 2-3. Poll Until Complete

After apply starts, poll the cluster status every 60 seconds:

```bash
aws eks describe-cluster --name "${CLUSTER_NAME}" \
  --query 'cluster.{version:version, status:status}' --output json
```

- `status == "UPDATING"` → Wait and re-poll.
- `status == "ACTIVE"` AND `version == TARGET_VERSION` → Proceed to Phase 3.
- `status == "FAILED"` → **STOP immediately**. Report the error.

---

## Phase 3: Add-on Safety Gate

### 3-1. Add-on Status Check

```bash
aws eks list-addons --cluster-name "${CLUSTER_NAME}" --query 'addons[]' --output text \
  | tr '\t' '\n' | while read addon; do
    aws eks describe-addon --cluster-name "${CLUSTER_NAME}" --addon-name "$addon" \
      --query '{name:addon.addonName, version:addon.addonVersion, status:addon.status}' --output json
  done
```

**Gate**:
- All add-ons `status == "ACTIVE"` → Proceed.
- `UPDATING` → Wait 30s, re-check (up to 5 minutes).
- `DEGRADED` or `CREATE_FAILED` → **STOP**.

### 3-2. kube-system Pod Health

```bash
kubectl get pods -n kube-system \
  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,STATUS:.status.phase,NODE:.spec.nodeName' \
  --sort-by='.metadata.name'
```

**Gate**: All pods `Running` with `READY=True`. If `Pending` or `CrashLoopBackOff` → investigate and report.

---

## Phase 4: Data Plane (Managed Node Group) Monitoring

The targeted apply in Phase 2 triggers MNG rolling update automatically. Monitor until complete.

### 4-1. Node Version Check

```bash
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status'
```

**Gate**: ALL nodes show `VERSION=v${TARGET_VERSION}.x`. If old-version nodes remain, rolling update is still in progress → re-check after 60s.

### 4-2. FailedEvict Events

```bash
kubectl get events --all-namespaces --field-selector reason=FailedEvict \
  --sort-by='.lastTimestamp' | tail -20
```

**Gate**: No `FailedEvict` events. If present → PDB blocking drain. Report the affected PDB and namespace.

### 4-3. Unhealthy Pods

> `--field-selector status.phase!=Running`은 EKS API 서버에서 지원되지 않는다. 반드시 JSON+Python으로 조회한다.

```bash
kubectl get pods --all-namespaces -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
bad = []
for p in data['items']:
    phase = p.get('status', {}).get('phase', '')
    ns    = p['metadata']['namespace']
    name  = p['metadata']['name']
    if phase in ('Running', 'Succeeded'):
        continue
    # containerStatuses에서 실제 상태 확인
    cs = p.get('status', {}).get('containerStatuses', [])
    reasons = [c.get('state', {}).get('waiting', {}).get('reason', '') for c in cs]
    bad.append({'ns': ns, 'name': name, 'phase': phase, 'reasons': reasons})
for b in bad:
    print(f\"{b['ns']}/{b['name']}: {b['phase']} {b['reasons']}\")
"
```

**Gate — 3단계 분류 후 판정**:

| 분류 | 조건 | 처리 |
|---|---|---|
| **TRANSIENT** | DaemonSet/init 파드가 업그레이드 중인 노드 위에서 Pending | 60s 대기 후 재확인 (최대 5회) |
| **STALE** | Error/Failed 상태이지만 **동일 owner의 Running 파드가 존재** | `kubectl delete pod -n <ns> <name>` 로 자동 삭제 후 재확인 |
| **BLOCKING** | CrashLoopBackOff / ImagePullBackOff / Pending (노드 무관) / STALE 삭제 후에도 잔존 | **STOP** — 상세 내역을 사용자에게 보고 |

**STALE 판별 — 동일 owner 확인**:
```bash
# owner 확인 (예: ReplicaSet, DaemonSet)
kubectl get pod -n <NAMESPACE> <POD_NAME> \
  -o jsonpath='{.metadata.ownerReferences[0].name} {.metadata.ownerReferences[0].kind}'

# 동일 owner 아래 Running 파드가 1개 이상 존재하면 STALE
kubectl get pods -n <NAMESPACE> \
  --field-selector=status.phase=Running \
  -l <same-label-selector> --no-headers | wc -l
```

**STALE 자동 삭제**:
```bash
kubectl delete pod -n <NAMESPACE> <STALE_POD_NAME>
```

삭제 후 30s 대기 → 재조회하여 잔존 파드 없음 확인.

---

## Phase 5: Karpenter Nodes (If Applicable)

### 5-0. Detect Karpenter Presence

```bash
kubectl get crd nodeclaims.karpenter.sh 2>/dev/null && echo "KARPENTER_DETECTED" || echo "KARPENTER_NOT_FOUND"
```

- `KARPENTER_NOT_FOUND` → **Skip Phase 5 entirely**. Proceed to Phase 6.
- `KARPENTER_DETECTED` → Continue with 5-1.

### 5-1. Check Drift Status

```bash
kubectl get nodeclaims -o yaml | grep -A5 "type: Drifted"
```

Or use MCP `list_k8s_resources`: `kind=NodeClaim`, `api_version=karpenter.sh/v1`.

If AMI aliases were updated in Phase 1, Karpenter's drift detection should trigger automatic node replacement.

### 5-2. Monitor Replacement Events

```bash
kubectl get events -n kube-system --field-selector 'involvedObject.kind=Node' \
  --sort-by='.lastTimestamp' | grep -E "Disrupting|Terminating|Launching" | tail -20
```

**Gate**: No PDB violation events during Karpenter disruption.

### 5-3. Verify Karpenter Node Versions

```bash
kubectl get nodes -l karpenter.sh/nodepool \
  -o custom-columns='NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,READY:.status.conditions[-1].status'
```

**Gate**: All Karpenter-managed nodes at `v${TARGET_VERSION}.x` and `READY=True`.

---

## Phase 6: Full Terraform Sync

After all component upgrades are complete, run a full plan to catch any remaining drift.

### 6-1. Full Plan

```bash
cd "${TF_DIR}" && terraform plan 2>&1 | tail -40
```

**Gate**:
- `No changes` → Infrastructure fully synced. Skip apply.
- Non-destructive changes only → Apply.
- Any `-/+` (destroy-recreate) → **STOP**, report to user.

### 6-2. Full Apply (if needed)

```bash
cd "${TF_DIR}" && terraform apply -auto-approve 2>&1
```

**Gate**: Exit code 0.

---

## Phase 7: Final Validation

### 7-1. Cluster Version

```bash
aws eks describe-cluster --name "${CLUSTER_NAME}" \
  --query 'cluster.{version:version, status:status}' --output json
```

**Gate**: `version == TARGET_VERSION` AND `status == "ACTIVE"`.

### 7-2. All Nodes

```bash
kubectl get nodes -o wide --sort-by='.metadata.creationTimestamp'
```

**Gate**: ALL nodes `Ready`, ALL versions `v${TARGET_VERSION}.x`.

### 7-3. All Pods — Final Health Check

> Phase 4-3과 동일하게 JSON+Python으로 조회한다. `--field-selector status.phase!=Running`은 사용 금지.

```bash
kubectl get pods --all-namespaces -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
bad = []
for p in data['items']:
    phase = p.get('status', {}).get('phase', '')
    ns    = p['metadata']['namespace']
    name  = p['metadata']['name']
    if phase in ('Running', 'Succeeded'):
        continue
    cs = p.get('status', {}).get('containerStatuses', [])
    reasons = [c.get('state', {}).get('waiting', {}).get('reason', '') for c in cs]
    owner = p['metadata'].get('ownerReferences', [{}])[0].get('kind', 'None')
    bad.append({'ns': ns, 'name': name, 'phase': phase, 'reasons': reasons, 'owner': owner})
for b in bad:
    print(f\"{b['ns']}/{b['name']}: {b['phase']} reasons={b['reasons']} owner={b['owner']}\")
"
```

**Gate — 3단계 분류 처리 후 완전 클린 상태 확보**:

| 분류 | 조건 | 처리 |
|---|---|---|
| **STALE** | Error/Failed 이며 동일 owner 하의 Running 파드 존재 | 즉시 `kubectl delete pod` 후 재확인 |
| **TRANSIENT** | Pending 이며 노드가 방금 조인 (AGE < 3m) | 90s 대기 후 재확인 (최대 3회) |
| **BLOCKING** | CrashLoopBackOff / ImagePullBackOff / Pending 장기화 / 삭제 후 재생성 반복 | **STOP** — 사용자에게 상세 보고 후 진행 여부 확인 |

**STALE 정리 절차**:
```bash
# 1. 동일 owner 아래 Running 파드가 있는지 확인
kubectl get pods -n <NAMESPACE> -o wide | grep <OWNER_NAME>

# 2. STALE 파드 삭제
kubectl delete pod -n <NAMESPACE> <STALE_POD_NAME>

# 3. 30s 대기 후 재조회
sleep 30
kubectl get pods -n <NAMESPACE> | grep -v Running | grep -v Completed
```

**최종 Gate**: 위 절차 완료 후 unhealthy 파드 **0개**. BLOCKING 분류 파드가 1개라도 있으면 완료 보고서를 발행하지 않고 사용자에게 먼저 보고한다.

### 7-4. EKS Insights (Post-upgrade)

Use MCP `get_eks_insights`: `category=UPGRADE_READINESS`.

**Gate**: All insights `PASSING`.

### 7-5. Generate Completion Report

Produce the final report using the template in [reference.md](reference.md), in the language specified by `output_language` in recipe.md.

---

## Safety Rules (Non-negotiable)

1. **No version skipping**: Reject 1.33 → 1.35 direct upgrade.
2. **Control Plane first**: Data Plane must never exceed Control Plane version.
3. **PDB respect**: If `FailedEvict` occurs, never force-proceed. Report and wait.
4. **No phase reversal**: Phases execute in strict order 0 → 7.
5. **No apply without plan**: Every `terraform apply` must be preceded by `terraform plan` review.
6. **Abort on unexpected destroy**: If plan shows unexpected resource destruction, STOP immediately.
7. **No field-selector for pod phase**: `--field-selector status.phase!=Running` is not supported on EKS API server. Always use `kubectl get pods -o json | python3 -c "..."` for phase-based filtering.
8. **No silent pod ignore**: Never mark a phase Gate as passed while unhealthy pods exist. Classify every non-Running pod (TRANSIENT / STALE / BLOCKING) and resolve before proceeding. STALE pods must be deleted; BLOCKING pods require user confirmation.
9. **Completion report only after clean state**: The final report must not be issued until Phase 7-3 Gate confirms zero unhealthy pods.
