---
name: terraform-eks-upgrade
description: >
  Upgrade a Terraform-managed EKS cluster version with zero downtime.
  Executes phases sequentially: Pre-flight → tfvars Update → Control Plane → Add-ons → Data Plane → Karpenter → Terraform Sync → Final Validation.
  Each phase boundary is enforced by deterministic gate scripts (exit code based).
  Trigger keywords: 'EKS upgrade', 'terraform EKS upgrade', 'EKS version upgrade', 'upgrade EKS cluster'
---

# Terraform EKS Version Upgrade

Upgrade a Terraform-managed EKS cluster following a strict phase-gated process.
Each phase boundary is enforced by a deterministic Python script — the LLM cannot bypass gates.

All scripts are located in `./scripts/` relative to the skill root directory.

---

## Prerequisites

Recipe values are already validated by the root skill router. Read these values directly:

| Variable | Recipe Field | Purpose |
|---|---|---|
| `CLUSTER_NAME` | `cluster_name` | Target for aws eks / kubectl commands |
| `CURRENT_VERSION` | `current_version` | Pre-flight validation |
| `TARGET_VERSION` | `target_version` | Upgrade target |
| `TF_DIR` | (auto-discover) | Directory containing `terraform.tfvars` or `*.tf` files |
| `EKS_MODULE` | (auto-discover) | Terraform module name for EKS (e.g. `module.eks`) |

> **Version constraint**: Only minor +1 upgrades are supported. 1.33 → 1.35 is rejected.

---

## Execution Plan

Print this plan to the user before starting:

```
[Phase 0] Pre-flight Validation     → Gate: gate_check.py (17 rules, exit code)
[Phase 1] Discovery & tfvars Update → Gate: grep verification
[Phase 2] Control Plane Upgrade     → Gate: phase_gate.py phase2 (exit code)
[Phase 3] Add-on Safety Gate        → Gate: phase_gate.py phase3 (exit code)
[Phase 4] Data Plane (MNG) Rolling  → Gate: phase_gate.py phase4 (exit code)
[Phase 5] Karpenter Nodes (if any)  → Gate: phase_gate.py phase5 (exit code)
[Phase 6] Full Terraform Sync       → Gate: phase_gate.py phase6 (exit code)
[Phase 7] Final Validation          → Gate: phase_gate.py phase7 (exit code)
```

Report format and abort conditions: see [reference.md](reference.md).

---

## Exit Code Convention (All Gate Scripts)

| Exit Code | Meaning | LLM Action |
|-----------|---------|------------|
| `0` | PASS — Gate open | Proceed to next phase |
| `1` | FAIL — Gate blocked | **STOP immediately**. Report audit.log to user. Do NOT proceed |
| `2` | WARN — User confirmation required | Report audit.log to user. Proceed ONLY with explicit user approval |
| `127` | CLI tool not found | Report missing tool. STOP |

WARN (exit code 2) is a soft-FAIL: the LLM MUST ask the user for approval before proceeding.

---

## Phase 0: Pre-flight Validation

Run the deterministic gate check script. The script validates 17 rules and returns an exit code.

```bash
python3 scripts/gate_check.py \
  --cluster-name "${CLUSTER_NAME}" \
  --current-version "${CURRENT_VERSION}" \
  --target-version "${TARGET_VERSION}" \
  --tf-dir "${TF_DIR}" \
  --audit-log audit.log
```

Interpret the exit code per the convention table above.

**On exit code 1 (FAIL):** Output an inline remediation checklist — do NOT generate a report file. Format:

```
## Phase 0 사전 검증 실패 — 조치 후 재실행 필요

검증 시각: {timestamp} | Gate: BLOCKED

### 🔴 CRITICAL — 해결 전까지 업그레이드 불가
- **{RULE_ID}**: {상세 내용}
  → 조치: {구체적 명령어 또는 방법}

### 🟡 HIGH — 해결 권장
- **{RULE_ID}**: {상세 내용}

### 🔵 MEDIUM/INFO — 참고
- **{RULE_ID}**: {상세 내용}

재실행:
python3 scripts/gate_check.py \
  --cluster-name "${CLUSTER_NAME}" --current-version "${CURRENT_VERSION}" \
  --target-version "${TARGET_VERSION}" --tf-dir "${TF_DIR}" --audit-log audit.log
```

Only include sections that have items. CRITICAL items must include a concrete remediation command.
Do NOT generate an `upgrade-report-*-FAILED.md` file for Phase 0 failures — that is reserved for mid-upgrade failures (Phase 1–7).

**On exit code 2 (WARN):** Report HIGH/MEDIUM items inline and ask the user to confirm before proceeding.

The script checks these 17 rules:
- COM-001: Cluster health (node Ready, resource pressure)
- COM-002: Version compatibility (minor +1 constraint)
- COM-002a: Kubelet version skew
- COM-003: Add-on compatibility (status + TARGET_VERSION compatibility)
- WLS-001: PDB blocking risk (disruptionsAllowed == 0)
- WLS-002: Single replica risk (replicas == 1)
- WLS-003: PV zone affinity (AZ node count cross-analysis)
- WLS-004: Local storage pods (hostPath detection)
- WLS-005: Long-running jobs (age > 30min, restartPolicy=Never)
- WLS-006: Topology constraint violations (TSC DoNotSchedule, Required Affinity)
- CAP-001: Node capacity headroom (CPU/MEM utilization)
- CAP-002: Resource pressure pods (OOMKilled, CrashLoop, ImagePull, Evicted)
- CAP-003: Surge capacity (subnet available IPs)
- INF-001: Terraform state drift (requires --tf-dir)
- INF-002: AMI availability (SSM Parameter Store)
- INF-003: Karpenter compatibility (conditional on CRD existence)
- INF-004: Terraform recreate detection (requires --tf-dir)

Audit log (`audit.log`) is written by the script in **append mode** — each phase appends its records without overwriting previous phases. The LLM reads it but does not write to it directly — use `scripts/audit_event.py` to append LLM-side events.

---

## Phase 1: Discovery & terraform.tfvars Update

### 1-1. Auto-discover TF_DIR

```bash
find . -name 'terraform.tfvars' -o -name '*.tf' | head -20
```

Identify the directory containing both `terraform.tfvars` and EKS-related `*.tf` files.

### 1-2. Auto-discover EKS Module Name

```bash
grep -rE 'module\s+"[^"]*"' "${TF_DIR}"/*.tf | grep -iE 'eks|cluster'
```

### 1-3. Read Current Values

```bash
grep -E 'eks_cluster_version|eks_node_ami_alias' "${TF_DIR}/terraform.tfvars"
```

Save the current values as `OLD_CLUSTER_VERSION` and `OLD_AMI_*` for audit recording.

### 1-4. Update eks_cluster_version Only

Update **only** `eks_cluster_version` in `${TF_DIR}/terraform.tfvars`:
- `eks_cluster_version` → `"${TARGET_VERSION}"`
- **DO NOT update `eks_node_ami_alias_*` here** — AMI updates are deferred to Phase 4 to prevent MNG from rolling before the Control Plane is upgraded.

### 1-5. Verify Update

```bash
grep -E 'eks_cluster_version' "${TF_DIR}/terraform.tfvars"
```

Confirm `eks_cluster_version` reflects `TARGET_VERSION`. Confirm `eks_node_ami_alias_*` is **unchanged**.

**Gate**: `eks_cluster_version` = TARGET_VERSION. Report before/after diff to user.

### 1-6. Record to audit.log

```bash
python3 scripts/audit_event.py \
  --audit-log audit.log \
  --rule-id "PHASE1-TFVARS" \
  --result "PASS" \
  --detail "eks_cluster_version: ${OLD_CLUSTER_VERSION} → ${TARGET_VERSION} (AMI update deferred to Phase 4)"
```

---

## Phase 2: Control Plane Upgrade

### 2-1. Targeted Plan

```bash
cd "${TF_DIR}" && terraform plan -target=${EKS_MODULE} 2>&1 | tail -60
```

Review the plan output:
- `aws_eks_cluster` version change → Expected
- `aws_eks_addon` version change → Expected
- `time_sleep` replace → Expected
- `aws_eks_node_group` version change (kubernetes version only, NOT release_version) → **Expected when using terraform-aws-eks module** — this means MNG rolling will be triggered simultaneously with CP upgrade. Verify `eks_node_ami_alias_*` was NOT modified in Phase 1 before proceeding.
- `aws_eks_node_group` release_version / AMI change → **STOP**: `eks_node_ami_alias_*` was accidentally modified in Phase 1. Revert it before proceeding.
- Any `-/+` (destroy-recreate) that is NOT `time_sleep` → **STOP and ask user**

> **If `aws_eks_node_group` appears in the plan (version change):** MNG rolling will start alongside CP upgrade.
> You MUST launch the drain monitor sub-agent (step 2-2) BEFORE running terraform apply.

### 2-2. Launch Sub-Agent Drain Monitor

> ⛔ **HARD GATE**: Launch the `k8s-drain-monitor` agent and confirm it is running BEFORE proceeding to step 2-3.
> Do NOT run `terraform apply` until the drain monitor is active.
> This applies even if `aws_eks_node_group` does NOT appear in the plan — CP upgrade can still cause transient node events.

Launch the `k8s-drain-monitor` agent with these parameters:
- `PHASE`: `P2`
- `AUDIT_LOG`: absolute path to `audit.log`
- `SKILL_SCRIPTS_DIR`: absolute path to the `scripts/` directory

The agent will watch kube-system Warning events and record `DRAIN-P2` entries to audit.log.
Signal the agent to terminate after Phase 2 gate passes.

### 2-3. Targeted Apply

Run in background so polling can proceed in parallel:

```bash
cd "${TF_DIR}" && terraform apply -target=${EKS_MODULE} -auto-approve 2>&1
```

This typically takes 8–40 minutes for the Control Plane. The MNG rolling update may also be triggered if it was already pending — monitor below.

### 2-3-b. Terraform Apply Timeout Handling

While the apply runs in background, poll every 60 seconds:

```bash
aws eks describe-cluster --name "${CLUSTER_NAME}" \
  --query 'cluster.{version:version, status:status}' --output json
```

**If apply has been running for 30+ minutes AND cluster is already `ACTIVE` + `TARGET_VERSION`:**

1. Check MNG status:
   ```bash
   aws eks list-nodegroups --cluster-name "${CLUSTER_NAME}" --output json | \
     jq -r '.nodegroups[]' | while read ng; do
       aws eks describe-nodegroup --cluster-name "${CLUSTER_NAME}" --nodegroup-name "$ng" \
         --query '{name:nodegroup.nodegroupName, status:nodegroup.status, version:nodegroup.version}' --output json
     done
   ```

2. If ALL nodegroups are `ACTIVE` + `TARGET_VERSION`:
   - Stop the background terraform apply process (TaskStop)
   - Run `terraform apply -auto-approve` (no target) to clean up any deposed resources
   - Proceed to Phase 2 gate

3. If any nodegroup is still `UPDATING`: continue waiting (re-check every 10 minutes)

4. If cluster is still `UPDATING`: continue waiting (re-check every 60 seconds)

### 2-4. Poll Until Complete

Poll every 60 seconds:

```bash
aws eks describe-cluster --name "${CLUSTER_NAME}" \
  --query 'cluster.{version:version, status:status}' --output json
```

- `UPDATING` → Wait and re-poll
- `ACTIVE` + correct version → Run gate script
- `FAILED` → **STOP immediately**

### 2-4. Gate Verification

```bash
python3 scripts/phase_gate.py phase2 \
  --cluster-name "${CLUSTER_NAME}" \
  --target-version "${TARGET_VERSION}" \
  --audit-log audit.log
```

Interpret exit code per convention table. On PASS, proceed to Phase 3.

---

## Phase 3: Add-on Safety Gate

### 3-1. Wait for Add-on Stabilization

After control plane upgrade, add-ons may take time to reconcile. Wait up to 5 minutes, polling every 30 seconds:

```bash
aws eks list-addons --cluster-name "${CLUSTER_NAME}" --query 'addons[]' --output text \
  | tr '\t' '\n' | while read addon; do
    aws eks describe-addon --cluster-name "${CLUSTER_NAME}" --addon-name "$addon" \
      --query '{name:addon.addonName, version:addon.addonVersion, status:addon.status}' --output json
  done
```

### 3-2. Gate Verification

```bash
python3 scripts/phase_gate.py phase3 \
  --cluster-name "${CLUSTER_NAME}" \
  --audit-log audit.log
```

Interpret exit code per convention table. On PASS, proceed to Phase 4.

---

## Phase 4: Data Plane (Managed Node Group) Rolling Update

Phase 4 has two parts:
1. **4-A**: Update AMI alias in tfvars and apply MNG rolling update via Terraform
2. **4-B**: Monitor rollout and verify via gate script

### 4-0. Launch Sub-Agent Drain Monitor

> ⛔ **HARD GATE**: Launch the `k8s-drain-monitor` agent and confirm it is running BEFORE any Phase 4 action.
> **If MNG is already in `UPDATING` state** (triggered by Phase 2 apply): launch the agent IMMEDIATELY upon entering Phase 4 — do not wait for AMI update steps.
> Do NOT proceed with AMI alias updates or terraform apply until the drain monitor is active.

Launch the `k8s-drain-monitor` agent with these parameters:
- `PHASE`: `P4`
- `AUDIT_LOG`: absolute path to `audit.log`
- `SKILL_SCRIPTS_DIR`: absolute path to the `scripts/` directory

The agent watches all-namespace Warning events, polls PDB status every 30s, and records `DRAIN-P4` entries to audit.log.
Signal the agent to terminate after Phase 4 gate passes.

### 4-0b. Launch Service-Aware Sub-Agent (if services defined)

**Skip this step if `services` field is absent in recipe.md/recipe.yaml.**

> ⛔ **HARD GATE**: If `services` is defined, launch the `k8s-service-aware` agent and confirm it is running BEFORE any Phase 4 action.
> Do NOT proceed until both drain monitor and service-aware agents are active.

Launch the `k8s-service-aware` agent with these parameters:
- `PHASE`: `P4`
- `AUDIT_LOG`: absolute path to `audit.log`
- `SKILL_SCRIPTS_DIR`: absolute path to the `scripts/` directory
- `SERVICES`: JSON array from recipe `services` field

The agent polls EndpointSlice ready counts and HTTP health checks every 30s, records `SVC-P4` entries to audit.log.
Signal the agent to terminate after Phase 4 gate passes.

### 4-1. Detect Current amiType (Architecture Preservation)

**CRITICAL**: Always read the current amiType before querying AMI versions. This preserves the existing architecture (x86_64 vs arm64) and prevents accidental RI waste.

```bash
aws eks list-nodegroups --cluster-name "${CLUSTER_NAME}" --output json | \
  jq -r '.nodegroups[]' | while read ng; do
    aws eks describe-nodegroup --cluster-name "${CLUSTER_NAME}" --nodegroup-name "$ng" \
      --query '{name:nodegroup.nodegroupName, amiType:nodegroup.amiType}' --output json
  done
```

Determine the SSM path suffix based on amiType:

| amiType | SSM path suffix |
|---------|----------------|
| `AL2023_x86_64_STANDARD` | `amazon-linux-2023/x86_64/standard` |
| `AL2023_ARM_64_STANDARD` | `amazon-linux-2023/arm64/standard` |
| `BOTTLEROCKET_x86_64` | `bottlerocket/aws-k8s-${TARGET_VERSION}/x86_64` |
| `BOTTLEROCKET_ARM_64` | `bottlerocket/aws-k8s-${TARGET_VERSION}/arm64` |
| `CUSTOM` / `WINDOWS_*` | Skip SSM query — user manages AMI manually |

### 4-2. Update AMI Alias (Data Plane Only)

Read the current AMI alias values:

```bash
grep -E 'eks_node_ami_alias' "${TF_DIR}/terraform.tfvars"
```

Query the latest AMI version for TARGET_VERSION from SSM using the amiType-derived path:

```bash
# Bottlerocket x86_64 (BOTTLEROCKET_x86_64)
aws ssm get-parameters-by-path \
  --path "/aws/service/bottlerocket/aws-k8s-${TARGET_VERSION}/x86_64/latest" \
  --recursive \
  --query "Parameters[?ends_with(Name, 'image_version')].Value" \
  --output text

# Bottlerocket arm64 (BOTTLEROCKET_ARM_64)
aws ssm get-parameters-by-path \
  --path "/aws/service/bottlerocket/aws-k8s-${TARGET_VERSION}/arm64/latest" \
  --recursive \
  --query "Parameters[?ends_with(Name, 'image_version')].Value" \
  --output text

# AL2023 x86_64 (AL2023_x86_64_STANDARD)
aws ssm get-parameters-by-path \
  --path "/aws/service/eks/optimized-ami/${TARGET_VERSION}/amazon-linux-2023/x86_64/standard" \
  --recursive \
  --query "Parameters[?ends_with(Name, 'image_version')].Value" \
  --output text

# AL2023 arm64 (AL2023_ARM_64_STANDARD)
aws ssm get-parameters-by-path \
  --path "/aws/service/eks/optimized-ami/${TARGET_VERSION}/amazon-linux-2023/arm64/standard" \
  --recursive \
  --query "Parameters[?ends_with(Name, 'image_version')].Value" \
  --output text
```

Only query the path that matches the current amiType. Update each `eks_node_ami_alias_*` variable that exists in `terraform.tfvars` to the queried value.

Record to audit.log:

```bash
python3 scripts/audit_event.py \
  --audit-log audit.log \
  --rule-id "PHASE4-AMI" \
  --result "PASS" \
  --detail "eks_node_ami_alias_bottlerocket: ${OLD_AMI} → ${NEW_AMI} (amiType=${AMI_TYPE})"
```

### 4-2. Targeted Plan for MNG

```bash
cd "${TF_DIR}" && terraform plan \
  -target=module.eks.module.eks_managed_node_group 2>&1 | tail -40
```

Review the plan:
- `aws_eks_node_group` `release_version` change → Expected
- Any `-/+` (destroy-recreate) on `aws_eks_node_group` → **STOP and ask user**

### 4-3. Targeted Apply for MNG

```bash
cd "${TF_DIR}" && terraform apply \
  -target=module.eks.module.eks_managed_node_group -auto-approve 2>&1
```

This triggers the MNG rolling update. Typical duration: 10–30 minutes per node group.

### 4-4. Monitor Node Rollout

Poll every 60 seconds until all MNG nodes show the target version:

```bash
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,READY:.status.conditions[-1].status'
```

### 4-5. Gate Verification

```bash
python3 scripts/phase_gate.py phase4 \
  --cluster-name "${CLUSTER_NAME}" \
  --target-version "${TARGET_VERSION}" \
  --audit-log audit.log
```

Interpret exit code per convention table.

**On WARN (exit code 2)**: The script reports STALE or TRANSIENT pods.
- STALE pods: The LLM deletes them with `kubectl delete pod -n <ns> <name>`, then re-runs the gate script.
- TRANSIENT pods: Wait 60 seconds, then re-run the gate script.
- The script classifies and reports only — it does NOT delete pods.

On PASS, proceed to Phase 5.

---

## Phase 5: Karpenter Nodes (If Applicable)

### 5-0. Launch Sub-Agent Drain Monitor

> ⛔ **HARD GATE**: Launch the `k8s-drain-monitor` agent and confirm it is running BEFORE updating `eks_node_ami_alias_*` in tfvars.
> AMI alias update triggers Karpenter drift detection and automatic node replacement immediately.
> Do NOT modify tfvars until the drain monitor is active.

Launch the `k8s-drain-monitor` agent with these parameters:
- `PHASE`: `P5`
- `AUDIT_LOG`: absolute path to `audit.log`
- `SKILL_SCRIPTS_DIR`: absolute path to the `scripts/` directory

The agent watches all-namespace Warning events, watches NodeClaim status, and records `DRAIN-P5` entries to audit.log.
Signal the agent to terminate after Phase 5 gate passes.

### 5-0b. Launch Service-Aware Sub-Agent (if services defined)

**Skip this step if `services` field is absent in recipe.md/recipe.yaml.**

> ⛔ **HARD GATE**: If `services` is defined, launch the `k8s-service-aware` agent and confirm it is running BEFORE updating `eks_node_ami_alias_*` in tfvars.

Launch the `k8s-service-aware` agent with these parameters:
- `PHASE`: `P5`
- `AUDIT_LOG`: absolute path to `audit.log`
- `SKILL_SCRIPTS_DIR`: absolute path to the `scripts/` directory
- `SERVICES`: JSON array from recipe `services` field

The agent records `SVC-P5` entries to audit.log.
Signal the agent to terminate after Phase 5 gate passes.

### 5-1. Monitor Karpenter Node Replacement

If Karpenter is present, AMI alias updates in Phase 4 trigger drift detection and automatic node replacement.

Monitor replacement progress:

```bash
kubectl get nodeclaims -o yaml | grep -A5 "type: Drifted"
kubectl get nodes -l karpenter.sh/nodepool \
  -o custom-columns='NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,READY:.status.conditions[-1].status'
```

### 5-2. Gate Verification

```bash
python3 scripts/phase_gate.py phase5 \
  --target-version "${TARGET_VERSION}" \
  --audit-log audit.log
```

Interpret exit code per convention table. If Karpenter is not present, the script returns PASS (skip). On PASS, proceed to Phase 6.

---

## Phase 6: Full Terraform Sync

After all component upgrades, run a full plan to catch remaining drift.

### 6-1. Full Plan and Apply

```bash
cd "${TF_DIR}" && terraform plan 2>&1 | tail -40
```

If non-destructive changes exist, apply:

```bash
cd "${TF_DIR}" && terraform apply -auto-approve 2>&1
```

### 6-2. Gate Verification

```bash
python3 scripts/phase_gate.py phase6 \
  --tf-dir "${TF_DIR}" \
  --audit-log audit.log
```

Interpret exit code per convention table. The script uses `terraform show -json` for plan analysis (not text parsing). On PASS, proceed to Phase 7.

---

## Phase 7: Final Validation

### 7-1. Gate Verification

The Phase 7 gate internally calls Phase 2/3/4 verification functions (same process, not subprocess) plus EKS Insights check.

```bash
python3 scripts/phase_gate.py phase7 \
  --cluster-name "${CLUSTER_NAME}" \
  --target-version "${TARGET_VERSION}" \
  --audit-log audit.log
```

Interpret exit code per convention table.

**On WARN (exit code 2)**: Same STALE/TRANSIENT pod handling as Phase 4 — LLM deletes STALE pods, waits for TRANSIENT, then re-runs.

**On PASS**: Proceed to generate the completion report.

### 7-2. Generate Report

Determine the report type from the outcome and generate using the template in [reference.md](reference.md).

**Report type selection:**
- Phase 7 exit 0 → **Type C** (완료 보고서)
- Phase 7 exit 2 + user approved continuation → **Type D** (경고 포함 완료 보고서)

**How to fill the template:**
1. Extract Phase start/end times from audit.log (`# Started:` / `# Finished:` lines per phase block)
2. Calculate duration = Finished − Started for each phase
3. Extract all WARN/FAIL events from audit.log (all lines matching `{timestamp} | {rule_id} | WARN|FAIL | {detail}`)
4. Include Sub-Agent events (`DRAIN-P*`, `SVC-P*` rule-ids) in the events table
5. Summarize troubleshooting actions taken during the upgrade in `{TROUBLESHOOTING_LOG}`
6. Query final cluster state for `{FINAL_CLUSTER_STATE_TABLE}`

Save as `upgrade-report-{CLUSTER_NAME}-{YYYYMMDD}.md` in the current working directory.

> The completion report MUST NOT be issued until Phase 7 gate returns exit code 0 (or exit 2 with explicit user approval).

### On Any Phase FAIL — Generate Failure Report Immediately

When any phase gate returns exit code 1, take the following action:

| Failed Phase | Action | Template |
|-------------|--------|---------|
| Phase 0 | **Inline remediation checklist only** — no file generated | See Phase 0 inline format above |
| Phase 1–6 | Generate `upgrade-report-*-FAILED.md` | Type B — 업그레이드 중단 보고서 |
| Phase 7 exit 1 | Generate `upgrade-report-*-FAILED.md` | Type B — 업그레이드 중단 보고서 (최종 검증 실패) |

**For Type B reports**, include in `{MIXED_VERSION_WARNING_OR_CLEAN}`:
- Phase 1 FAIL: "업그레이드 미시작 — 클러스터 상태 변경 없음"
- Phase 2 FAIL: "⚠️ Control Plane 업그레이드 중 실패. 현재 버전 확인 필요"
- Phase 3+ FAIL: "⚠️ Control Plane은 {TARGET_VERSION}으로 업그레이드됨. Data Plane은 이전 버전 상태일 수 있음"

---

## Safety Rules (Non-negotiable)

1. **No version skipping**: Reject 1.33 → 1.35 direct upgrade.
2. **Control Plane first**: Data Plane version must NEVER exceed Control Plane version.
3. **PDB respect**: If `FailedEvict` occurs, never force-proceed. Report and wait.
4. **No phase reversal**: Phases execute in strict order 0 → 7. No skipping, no reordering.
5. **No apply without plan**: Every `terraform apply` must be preceded by `terraform plan` review.
6. **Abort on unexpected destroy**: If plan shows unexpected resource destruction, STOP immediately.
7. **No field-selector for pod phase**: `--field-selector status.phase!=Running` is not supported on EKS API server. Always use JSON + Python for phase-based filtering.
8. **No silent pod ignore**: Never mark a phase Gate as passed while unhealthy pods exist. Classify every non-Running pod AND every Running pod with NotReady containers (TRANSIENT / STALE / BLOCKING) and resolve before proceeding.
9. **Completion report only after clean state**: The final report must not be issued until Phase 7 gate confirms zero unhealthy pods.
10. **Gate scripts are authoritative**: The LLM MUST NOT override or reinterpret gate script exit codes. Exit code 1 = STOP. No exceptions.
