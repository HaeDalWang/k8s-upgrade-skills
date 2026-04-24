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

Interpret the exit code per the convention table above. On FAIL or WARN, report `audit.log` contents to the user.

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

Audit log (`audit.log`) is written by the script in **append mode** — each phase appends its records without overwriting previous phases. The LLM reads it but does not write to it.

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

### 1-4. Update Values

Update these variables in `${TF_DIR}/terraform.tfvars`:
- `eks_cluster_version` → `"${TARGET_VERSION}"`
- Each `eks_node_ami_alias_*` → latest value for TARGET_VERSION
- Only update variables that actually exist in the file

### 1-5. Verify Update

```bash
grep -E 'eks_cluster_version|eks_node_ami_alias' "${TF_DIR}/terraform.tfvars"
```

**Gate**: All values reflect the target version. Report before/after diff to user.

---

## Phase 2: Control Plane Upgrade

### 2-1. Targeted Plan

```bash
cd "${TF_DIR}" && terraform plan -target=${EKS_MODULE} 2>&1 | tail -60
```

Review the plan output:
- `aws_eks_cluster` version change → Expected
- `aws_eks_node_group` release_version change → Expected (rolling update)
- Any `-/+` (destroy-recreate) that is NOT `time_sleep` → **STOP and ask user**

### 2-2. Launch Sub-Agent Drain Monitor

Before running terraform apply, launch a Sub-Agent in parallel to watch kube-system events in real time.

**Sub-Agent instructions:**
- Run the following command to watch Warning events:
  ```bash
  kubectl get events -n kube-system --watch --field-selector type=Warning \
    -o custom-columns='TIME:.lastTimestamp,REASON:.reason,OBJ:.involvedObject.name,MSG:.message'
  ```
- Report to the main agent immediately and record to audit.log when any of these events are detected:
  - `FailedMount`, `BackOff`, `OOMKilling`, `NodeNotReady`
- Record to audit.log by calling the script:
  ```bash
  python3 scripts/audit_event.py \
    --audit-log audit.log \
    --rule-id "DRAIN-P2" \
    --result "WARN" \
    --detail "<REASON>: <OBJ> — <MSG>"
  ```
- **Read-only** — never run any write or delete commands
- Terminate immediately when the main agent signals Phase 2 complete

### 2-3. Targeted Apply

```bash
cd "${TF_DIR}" && terraform apply -target=${EKS_MODULE} -auto-approve 2>&1
```

This typically takes 8–15 minutes.

### 2-3. Poll Until Complete

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

## Phase 4: Data Plane (Managed Node Group) Monitoring

The targeted apply in Phase 2 triggers MNG rolling update automatically. Monitor until complete.

### 4-0. Launch Sub-Agent Drain Monitor

Before the node rolling update begins, launch a Sub-Agent in parallel to watch drain events in real time.

**Sub-Agent instructions:**
- Run the following command to watch Warning events across all namespaces:
  ```bash
  kubectl get events -A --watch --field-selector type=Warning \
    -o custom-columns='TIME:.lastTimestamp,NS:.metadata.namespace,REASON:.reason,OBJ:.involvedObject.name,MSG:.message'
  ```
- Check PDB status every 30 seconds:
  ```bash
  kubectl get pdb -A \
    -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,ALLOWED:.status.disruptionsAllowed,DESIRED:.status.desiredHealthy,CURRENT:.status.currentHealthy'
  ```
- Report to the main agent immediately and record to audit.log when any of these events are detected:
  - `FailedDrain` → request immediate stop + report PDB status together
  - `DisruptionBlocked` → report PDB deadlock
  - `ExceededGracePeriod` → report Graceful Termination failure
  - `FailedKillPod` → report forced pod termination failure
- Record to audit.log by calling the script:
  ```bash
  python3 scripts/audit_event.py \
    --audit-log audit.log \
    --rule-id "DRAIN-P4" \
    --result "WARN" \
    --detail "<REASON>: <NS>/<OBJ> — <MSG>"
  ```
- Use `--result "FAIL"` when `FailedDrain` is detected, and request the main agent to stop immediately
- **Read-only** — never run any write or delete commands
- Terminate immediately when the main agent signals Phase 4 complete

### 4-0b. Launch Service-Aware Sub-Agent (if services defined)

**Skip this step if `services` field is absent in recipe.yaml.**

If `services` is defined, launch a second Sub-Agent in parallel to monitor service availability during node rollout.

**Sub-Agent instructions:**
- For each service in `services`, poll every 30 seconds:

  1. Check EndpointSlice ready address count:
     ```bash
     kubectl get endpointslices -n <namespace> \
       -l kubernetes.io/service-name=<name> -o json | python3 -c "
     import json, sys
     data = json.load(sys.stdin)
     ready = sum(
         len(ep.get('addresses', []))
         for item in data.get('items', [])
         for ep in item.get('endpoints', [])
         if ep.get('conditions', {}).get('ready', False)
     )
     print(ready)
     "
     ```
     If `ready < min_endpoints`, record WARN and report to main agent:
     ```bash
     python3 scripts/audit_event.py \
       --audit-log audit.log \
       --rule-id "SVC-P4" \
       --result "WARN" \
       --detail "<name>: ready_endpoints=<N> < min=<min_endpoints> (EndpointSlice)"
     ```

  2. If `health_check_url` is set, check HTTP response:
     ```bash
     curl -sf --max-time 5 --retry 2 <health_check_url> -o /dev/null
     ```
     If non-2xx or timeout, record WARN and report to main agent:
     ```bash
     python3 scripts/audit_event.py \
       --audit-log audit.log \
       --rule-id "SVC-P4" \
       --result "WARN" \
       --detail "<name>: health_check_url returned non-2xx or timed out"
     ```

- For services without `health_check_url`, warn **once** at startup:
  ```
  ⚠️ [SVC-P4] <name>: health_check_url not set — monitoring EndpointSlice only.
  True zero-downtime cannot be guaranteed without HTTP health check.
  ```
  Record this warning to audit.log:
  ```bash
  python3 scripts/audit_event.py \
    --audit-log audit.log \
    --rule-id "SVC-P4" \
    --result "INFO" \
    --detail "<name>: BestEffort mode — EndpointSlice only, no health_check_url"
  ```
- **Read-only** — never run any write or delete commands
- Terminate immediately when the main agent signals Phase 4 complete

### 4-1. Monitor Node Rollout

Poll every 60 seconds until all nodes show the target version:

```bash
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,READY:.status.conditions[-1].status'
```

### 4-2. Gate Verification

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

Before Karpenter node replacement begins, launch a Sub-Agent in parallel to watch events in real time.

**Sub-Agent instructions:**
- Run the following command to watch Warning events across all namespaces (same as Phase 4):
  ```bash
  kubectl get events -A --watch --field-selector type=Warning \
    -o custom-columns='TIME:.lastTimestamp,NS:.metadata.namespace,REASON:.reason,OBJ:.involvedObject.name,MSG:.message'
  ```
- Watch NodeClaim status in parallel:
  ```bash
  kubectl get nodeclaims --watch \
    -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,REASON:.status.conditions[?(@.type=="Ready")].reason'
  ```
- Report to the main agent immediately and record to audit.log when any of these events are detected:
  - All Phase 4 targets (`FailedDrain`, `DisruptionBlocked`, `ExceededGracePeriod`, `FailedKillPod`)
  - `NodeClaimNotFound` → report NodeClaim loss
  - `NodeClaimTerminationFailed` → report NodeClaim termination failure
- Record to audit.log by calling the script:
  ```bash
  python3 scripts/audit_event.py \
    --audit-log audit.log \
    --rule-id "DRAIN-P5" \
    --result "WARN" \
    --detail "<REASON>: <NS>/<OBJ> — <MSG>"
  ```
- Use `--result "FAIL"` when `FailedDrain` or `NodeClaimTerminationFailed` is detected
- **Read-only** — never run any write or delete commands
- Terminate immediately when the main agent signals Phase 5 complete

### 5-0b. Launch Service-Aware Sub-Agent (if services defined)

**Skip this step if `services` field is absent in recipe.yaml.**

Same instructions as Phase 4-0b, with rule-id `SVC-P5` instead of `SVC-P4`.

### 5-1. Monitor Karpenter Node Replacement

If Karpenter is present, AMI alias updates in Phase 1 trigger drift detection and automatic node replacement.

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

When any phase gate returns exit code 1, generate a failure report **before** stopping:

| Failed Phase | Report Type | Template |
|-------------|-------------|---------|
| Phase 0 | Type A | 사전 검증 실패 보고서 |
| Phase 1–6 | Type B | 업그레이드 중단 보고서 |

**For Type B reports**, include in `{MIXED_VERSION_WARNING_OR_CLEAN}`:
- Phase 0–1 FAIL: "업그레이드 미시작 — 클러스터 상태 변경 없음"
- Phase 2 FAIL: "⚠️ Control Plane 업그레이드 중 실패. 현재 버전 확인 필요"
- Phase 3+ FAIL: "⚠️ Control Plane은 {TARGET_VERSION}으로 업그레이드됨. Data Plane은 이전 버전 상태일 수 있음"

Save as `upgrade-report-{CLUSTER_NAME}-{YYYYMMDD}-FAILED.md`.

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
