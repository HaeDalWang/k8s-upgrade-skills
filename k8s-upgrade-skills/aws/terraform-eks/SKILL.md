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

## Prerequisites (from recipe.yaml)

Read these values from `recipe.yaml` (or `recipe.md` fallback). If any is empty, do NOT start the upgrade.

**검증**: 파싱 전에 반드시 스키마 검증을 실행한다.

```bash
python3 scripts/validate_recipe.py recipe.yaml
```

검증 실패(exit code 1) 시 에러 메시지를 사용자에게 보고하고 진행하지 않는다.

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
[Phase 0] Pre-flight Validation     → Gate: 16개 규칙 전부 PASS (rules/ 참조)
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

## Phase 0: Pre-flight Validation (규칙 기반)

**Purpose**: 클러스터 상태, 워크로드 안전성, 용량, 인프라를 체계적으로 검증한다.

### Phase 0-A: 결정론적 검증 (gate_check.py) — 필수 선행

**LLM이 아닌 스크립트가 Gate를 판단한다.** 아래 스크립트를 먼저 실행하고, exit code로 진행 여부를 결정한다.

```bash
# 프로젝트 루트의 scripts/ 디렉토리에서 실행
# 스크립트가 없으면 install.sh로 설치된 경로에서 찾는다
python3 scripts/gate_check.py \
  --cluster-name "${CLUSTER_NAME}" \
  --current-version "${CURRENT_VERSION}" \
  --target-version "${TARGET_VERSION}" \
  --audit-log audit.log
```

**Exit code 해석 (LLM이 변경할 수 없음)**:

| Exit Code | 의미 | LLM 행동 |
|-----------|------|----------|
| `0` | Gate OPEN — 결정론적 검증 통과 | Phase 0-B 진행 |
| `1` | Gate BLOCKED — CRITICAL 실패 존재 | **즉시 중단**. audit.log 내용을 사용자에게 보고. Phase 1 진행 금지 |
| `2` | Gate WARN — HIGH 경고 존재 | audit.log 내용을 사용자에게 보고. 사용자 승인 시에만 Phase 0-B 진행 |

**스크립트가 검증하는 규칙 (10개)**:
- COM-001: 클러스터 기본 상태 (노드 Ready, 리소스 압박)
- COM-002: 버전 호환성 (minor +1 제약)
- COM-002a: kubelet 버전 skew
- WLS-001: PDB 차단 가능성 (disruptionsAllowed == 0)
- WLS-002: 단일 레플리카 위험 (replicas == 1 카운트)
- WLS-003: PV 존 어피니티 (AZ별 노드 수 교차 분석)
- WLS-004: 로컬 스토리지 Pod (hostPath 감지)
- WLS-005: 장시간 Job (running time > 30분, restartPolicy=Never)
- CAP-001: 노드 용량 여유분 (CPU/MEM 사용률)
- INF-002: AMI 가용성 (SSM Parameter Store 조회)

**감사 로그 (audit.log)**: 스크립트가 기록 주체. LLM은 읽기만 한다.

### Phase 0-B: LLM 보조 검증 (gate_check.py 통과 후에만 실행)

gate_check.py가 exit code 0 또는 사용자 승인(exit code 2)을 받은 후에만 실행한다.
나머지 규칙은 LLM 해석이 필요하므로 [rules/rule-index.md](rules/rule-index.md)를 참조하여 실행한다.

**LLM이 실행하는 규칙 (6개)**:
- COM-003: Add-on 호환성 (AWS API + 해석)
- WLS-006: 토폴로지 제약 위반 (복합 분석)
- CAP-002: 리소스 압박 Pod (상태 분류)
- CAP-003: Surge 용량 (서브넷/EC2 한도)
- INF-001: Terraform 상태 드리프트 (plan 해석)
- INF-003: Karpenter 호환성 (조건부)
- INF-004: Terraform Recreate 감지 (plan 해석)

> **중요**: LLM 보조 검증에서 CRITICAL 실패가 발견되면 즉시 중단한다. 단, 이 판단은 LLM이 하므로 audit.log에 결과를 추가 기록하고 사용자에게 보고한다.

### 규칙 카테고리 및 실행 순서

| 단계 | 카테고리 | 규칙 수 | 핵심 검증 내용 |
|------|----------|---------|---------------|
| 1 | [common/](rules/common/) | 3개 | 클러스터 상태, 버전 호환성, Add-on 준비 |
| 2 | [workload-safety/](rules/workload-safety/) | 6개 | PDB, 단일 레플리카, PV AZ, 로컬 스토리지, Job, 토폴로지 |
| 3 | [capacity/](rules/capacity/) | 3개 | 노드 여유분, 리소스 압박, surge 용량 |
| 4 | [infrastructure/](rules/infrastructure/) | 4개 | Terraform drift, AMI 가용성, Karpenter 호환성, Recreate 감지 |

### 판정 기준

| 조건 | 판정 |
|------|------|
| CRITICAL 실패 1개 이상 | ❌ 업그레이드 불가 — 해결 후 재실행 |
| HIGH 실패 1개 이상, CRITICAL 없음 | ⚠️ 사용자 확인 필요 — 승인 시 진행 |
| MEDIUM/LOW만 | ✅ 자동 진행 (보고만) |
| 전부 PASS | ✅ 즉시 진행 |

### 결과 보고

모든 규칙 실행 후 아래 형식으로 요약 테이블을 출력한다:

```
사전 검증 결과 — {CLUSTER_NAME} ({CURRENT_VERSION} → {TARGET_VERSION})

┌─────────┬──────────────────────────┬──────────┬──────────┐
│   ID    │          규칙            │  심각도  │   결과   │
├─────────┼──────────────────────────┼──────────┼──────────┤
│ COM-001 │ 클러스터 기본 상태       │ CRITICAL │ ✅ PASS  │
│ COM-002 │ 버전 호환성              │ CRITICAL │ ✅ PASS  │
│ COM-003 │ Add-on 호환성            │ HIGH     │ ✅ PASS  │
│ WLS-001 │ PDB 차단 가능성          │ CRITICAL │ ✅ PASS  │
│ WLS-002 │ 단일 레플리카 위험       │ HIGH     │ ⚠️ WARN  │
│ WLS-003 │ PV 존 어피니티           │ CRITICAL │ ✅ PASS  │
│ WLS-004 │ 로컬 스토리지 Pod        │ MEDIUM   │ ✅ PASS  │
│ WLS-005 │ 장시간 Job               │ MEDIUM   │ ⏭️ SKIP  │
│ WLS-006 │ 토폴로지 제약            │ HIGH     │ ✅ PASS  │
│ CAP-001 │ 노드 용량 여유분         │ HIGH     │ ✅ PASS  │
│ CAP-002 │ 리소스 압박 Pod          │ MEDIUM   │ ✅ PASS  │
│ CAP-003 │ Surge 용량               │ HIGH     │ ✅ PASS  │
│ INF-001 │ Terraform 드리프트       │ HIGH     │ ✅ PASS  │
│ INF-002 │ AMI 가용성               │ CRITICAL │ ✅ PASS  │
│ INF-003 │ Karpenter 호환성         │ HIGH     │ ✅ PASS  │
│ INF-004 │ Terraform Recreate 감지  │ CRITICAL │ ✅ PASS  │
└─────────┴──────────────────────────┴──────────┴──────────┘

CRITICAL 실패: 0개 | HIGH 경고: 1개 | MEDIUM 참고: 0개
→ 진행 가능 (HIGH 경고 항목 사용자 확인 필요)
```

> 각 규칙의 상세 검증 명령어, Gate 조건, 조치 방안은 [rules/](rules/) 디렉토리의 개별 파일을 참조한다.

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
