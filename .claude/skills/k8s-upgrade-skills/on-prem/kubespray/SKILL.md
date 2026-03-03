---
name: kubespray-upgrade
description: >
  Zero-downtime on-premises Kubernetes version upgrade using Kubespray (Ansible).
  Includes ETCD backup, certificate validation, and phase-gated safety checks.
  Trigger keywords: 'Kubespray upgrade', 'on-prem K8s upgrade', '온프레미스 업그레이드',
  'kubespray 버전 업그레이드', '쿠버네티스 온프레미스 업그레이드'
---

# Kubespray On-Premises Zero-Downtime Version Upgrade

Upgrade a Kubespray-provisioned on-premises Kubernetes cluster with **zero downtime**.
Kubespray's `upgrade-cluster.yml` handles the control-plane-first order automatically.
This skill adds safety checks that Kubespray does NOT perform on its own.

---

## Prerequisites (from recipe.md)

Read these values from `recipe.md`. If any is empty, do NOT start.

| Variable | Recipe Field | Purpose |
|---|---|---|
| `CLUSTER_NAME` | `cluster_name` | kubectl target / identification |
| `CURRENT_VERSION` | `current_version` | Pre-flight version validation |
| `TARGET_VERSION` | `target_version` | Passed to `upgrade-cluster.yml` as `kube_version` |
| `KUBESPRAY_DIR` | (auto-discover) | Kubespray repo directory containing `upgrade-cluster.yml` |
| `INVENTORY_PATH` | (auto-discover) | Inventory file path within Kubespray directory |

> **Version constraint**: Minor version +1 only. 1.33 → 1.35 is rejected.

---

## Execution Plan (Declare, Then Execute)

```
[Phase 0] Pre-flight Validation    → Gate: nodes Ready, PDB safe, ETCD healthy, certs valid
[Phase 1] ETCD Backup              → Gate: snapshot verified, file size > 0
[Phase 2] Kubespray Version Check  → Gate: Kubespray supports TARGET_VERSION
[Phase 3] upgrade-cluster.yml      → Gate: playbook exit code 0
[Phase 4] Post-upgrade Validation  → Gate: all nodes TARGET_VERSION, all pods Running
[Phase 5] Final Verification       → Gate: cluster fully healthy, ETCD healthy
```

---

## Phase 0: Pre-flight Validation

**Purpose**: Confirm the cluster is healthy and safe to upgrade. ANY failure → STOP.

### 0-1. Node Health

```bash
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status,VERSION:.status.nodeInfo.kubeletVersion'
```

**Gate**: ALL nodes `READY=True`. Any `NotReady` → **STOP**, diagnose and recover first.

### 0-2. Version Skip Check

```bash
CURR_MINOR=$(echo "${CURRENT_VERSION}" | cut -d'.' -f2)
TARG_MINOR=$(echo "${TARGET_VERSION}" | cut -d'.' -f2)
GAP=$((TARG_MINOR - CURR_MINOR))
echo "Version gap: ${GAP}"
```

**Gate**: `GAP == 1`. Otherwise → **STOP** with appropriate message.

### 0-3. PodDisruptionBudget Audit

```bash
kubectl get pdb --all-namespaces \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,MIN-AVAIL:.spec.minAvailable,MAX-UNAVAIL:.spec.maxUnavailable,ALLOWED-DISRUPT:.status.disruptionsAllowed,CURRENT-HEALTHY:.status.currentHealthy,DESIRED-HEALTHY:.status.desiredHealthy'
```

**Gate**: No PDB with `ALLOWED-DISRUPT == 0`. If found → report and require user resolution.

### 0-4. ETCD Cluster Health

SSH to the first control-plane node and check ETCD:

```bash
ssh <control-plane-node-1> "sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-<hostname>.pem \
  --key=/etc/ssl/etcd/ssl/node-<hostname>-key.pem \
  endpoint health --write-out=table"
```

Or if `etcdctl` is in a different path:
```bash
ssh <control-plane-node-1> "sudo /usr/local/bin/etcdctl endpoint health --cluster \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-<hostname>.pem \
  --key=/etc/ssl/etcd/ssl/node-<hostname>-key.pem"
```

**Gate**: All ETCD members `healthy: true`. Any unhealthy member → **STOP**.

### 0-5. Certificate Expiry Check

```bash
ssh <control-plane-node-1> "sudo kubeadm certs check-expiration 2>/dev/null || \
  for cert in /etc/kubernetes/ssl/*.pem; do \
    echo \"--- \$cert ---\"; \
    sudo openssl x509 -in \$cert -noout -enddate 2>/dev/null; \
  done"
```

**Gate**: No certificate expiring within 30 days. If expiring soon → WARN user (upgrade may renew certs, but verify).

### 0-6. Disk Space on Control-Plane Nodes

```bash
ssh <control-plane-node-1> "df -h / /var/lib/etcd /var/lib/kubelet 2>/dev/null | grep -v Filesystem"
```

**Gate**: At least 20% free space on `/`, `/var/lib/etcd`, and `/var/lib/kubelet`. If below → **STOP**, free space first.

### 0-7. Container Runtime Check

```bash
kubectl get nodes -o custom-columns='NAME:.metadata.name,RUNTIME:.status.nodeInfo.containerRuntimeVersion'
```

**Gate**: Record the container runtime version. Kubespray `upgrade-cluster.yml` handles runtime upgrades, but note any nodes on deprecated runtimes (e.g. Docker < 24.x).

---

## Phase 1: ETCD Backup

**Purpose**: Create a recoverable ETCD snapshot before any upgrade action. This is the ONLY rollback mechanism for on-premises clusters.

### 1-1. Create Snapshot

SSH to the first control-plane node:

```bash
BACKUP_DIR="/var/backups/etcd"
BACKUP_FILE="${BACKUP_DIR}/snapshot-pre-upgrade-${CURRENT_VERSION}-to-${TARGET_VERSION}-$(date +%Y%m%d%H%M%S).db"

ssh <control-plane-node-1> "sudo mkdir -p ${BACKUP_DIR} && \
  sudo ETCDCTL_API=3 etcdctl snapshot save ${BACKUP_FILE} \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-<hostname>.pem \
  --key=/etc/ssl/etcd/ssl/node-<hostname>-key.pem"
```

### 1-2. Verify Snapshot

```bash
ssh <control-plane-node-1> "sudo ETCDCTL_API=3 etcdctl snapshot status ${BACKUP_FILE} --write-out=table"
```

**Gate**:
- Snapshot file exists and size > 0.
- `etcdctl snapshot status` shows valid revision and total key count.
- Report the snapshot path and size to the user.

### 1-3. (Optional) Copy Snapshot Off-node

```bash
scp <control-plane-node-1>:${BACKUP_FILE} ./etcd-backup/
```

Recommend the user copy the snapshot to a separate storage location.

---

## Phase 2: Kubespray Version Compatibility Check

### 2-1. Discover Kubespray Directory

```bash
find . -name 'upgrade-cluster.yml' -type f | head -5
```

Set `KUBESPRAY_DIR` to the directory containing `upgrade-cluster.yml`.

### 2-2. Discover Inventory

```bash
find "${KUBESPRAY_DIR}/inventory" -name 'hosts.yaml' -o -name 'hosts.yml' -o -name 'hosts.ini' | head -5
```

Set `INVENTORY_PATH` to the discovered inventory file.

### 2-3. Check Kubespray Supported Versions

```bash
grep -r "kube_version" "${KUBESPRAY_DIR}/roles/kubespray-defaults/defaults/main/" 2>/dev/null || \
  grep -r "kube_version" "${KUBESPRAY_DIR}/roles/kubespray-defaults/" 2>/dev/null || \
  grep -r "kube_version_min_required\|kube_version" "${KUBESPRAY_DIR}/roles/" 2>/dev/null | head -10
```

**Gate**: Confirm that the Kubespray version in use supports `TARGET_VERSION`. If unsure, check the Kubespray release notes or `CHANGELOG.md`.

### 2-4. Current Inventory Version

```bash
grep -r "kube_version" "${KUBESPRAY_DIR}/inventory/" "${INVENTORY_PATH}" 2>/dev/null || true
```

**Gate**: If `kube_version` is hardcoded in inventory, note it. The upgrade will override via `-e kube_version=` flag.

---

## Phase 3: Execute upgrade-cluster.yml

### 3-1. Dry Run (Check Mode)

```bash
cd "${KUBESPRAY_DIR}" && \
  ansible-playbook -i ${INVENTORY_PATH} upgrade-cluster.yml \
  -e kube_version=v${TARGET_VERSION}.0 \
  --check --diff 2>&1 | tail -40
```

**Gate**: Review the diff output. If any task shows unexpected changes (e.g. deleting critical resources), **STOP** and investigate.

> Note: `--check` mode may not fully simulate all upgrade tasks, but it catches obvious configuration issues.

### 3-2. Execute Upgrade

```bash
cd "${KUBESPRAY_DIR}" && \
  ansible-playbook -i ${INVENTORY_PATH} upgrade-cluster.yml \
  -e kube_version=v${TARGET_VERSION}.0 \
  -v 2>&1
```

This operation can take **20–60 minutes** depending on cluster size.

Kubespray automatically:
1. Upgrades control-plane nodes first (one by one).
2. Then upgrades worker nodes (with configurable parallelism).
3. Handles kubelet, kube-proxy, and container runtime upgrades.

**Gate**: Playbook exit code 0. If any task fails → **STOP immediately**. Collect the Ansible error output and the failing host name. Report to user.

### 3-3. Monitor Progress (during execution)

Watch the Ansible output for:
- Control-plane tasks completing before worker tasks.
- Any `FAILED` tasks → the playbook should halt automatically.
- Drain events on each node.

---

## Phase 4: Post-upgrade Validation

### 4-1. Node Version

```bash
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status'
```

**Gate**: ALL nodes `VERSION=v${TARGET_VERSION}.x` and `READY=True`. If old-version nodes remain → Kubespray may not have completed all nodes. Investigate.

### 4-2. FailedEvict Events

```bash
kubectl get events --all-namespaces --field-selector reason=FailedEvict \
  --sort-by='.lastTimestamp' | tail -20
```

**Gate**: No FailedEvict events. If present → PDB blocked drain. Report.

### 4-3. Unhealthy Pods

```bash
kubectl get pods --all-namespaces \
  --field-selector 'status.phase!=Running,status.phase!=Succeeded' \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,STATUS:.status.phase,REASON:.status.reason'
```

**Gate**: No `Pending`, `CrashLoopBackOff`, or `Error` pods.

### 4-4. kube-system Components

```bash
kubectl get pods -n kube-system -o wide
```

**Gate**: All kube-system pods Running.

---

## Phase 5: Final Verification

### 5-1. ETCD Health (Post-upgrade)

Re-run the same ETCD health check from Phase 0-4:

```bash
ssh <control-plane-node-1> "sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-<hostname>.pem \
  --key=/etc/ssl/etcd/ssl/node-<hostname>-key.pem \
  endpoint health --write-out=table"
```

**Gate**: All ETCD members healthy.

### 5-2. Full Node Status

```bash
kubectl get nodes -o wide --sort-by='.metadata.creationTimestamp'
```

**Gate**: All nodes Ready, correct version.

### 5-3. Full Pod Status

```bash
kubectl get pods --all-namespaces \
  --field-selector 'status.phase!=Running,status.phase!=Succeeded' 2>/dev/null \
  | grep -v "^NAMESPACE" | grep -v "Completed"
```

**Gate**: Empty output.

### 5-4. Generate Completion Report

Report in the language specified by `output_language` in recipe.md.

**Korean template**:
```
업그레이드 완료 — Kubernetes {CURRENT_VERSION} → {TARGET_VERSION} (Kubespray)

┌──────────┬──────────────────────────────┬─────────────────────────────────┐
│   단계   │             대상             │              결과               │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 0  │ 사전 검증                    │ 노드 Ready / PDB 충족 / ETCD OK │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 1  │ ETCD 백업                    │ 스냅샷 생성 완료 ({PATH})       │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 2  │ Kubespray 호환성 확인        │ TARGET_VERSION 지원 확인        │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 3  │ upgrade-cluster.yml          │ 완료 (exit 0, {DURATION})       │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 4  │ 노드·Pod 검증               │ 전 노드 v{TARGET_VERSION}.x     │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 5  │ 최종 검증                    │ ETCD 정상, 전 Pod Running       │
└──────────┴──────────────────────────────┴─────────────────────────────────┘

최종 클러스터 상태
- Control Plane: v{TARGET_VERSION}.x
- Worker Nodes: v{TARGET_VERSION}.x (전체 {N}개)
- ETCD: Healthy (전체 멤버)
- 전체 Pod: Running/Completed
- ETCD 백업 위치: {BACKUP_PATH}
```

---

## Abort Conditions

| Condition | Situation | Severity |
|---|---|---|
| Node `NotReady` (pre-upgrade) | Cluster already unstable | CRITICAL |
| PDB `disruptionsAllowed == 0` | Drain will be blocked | CRITICAL |
| ETCD member unhealthy | Data store compromised | CRITICAL |
| Certificate expiring < 30 days | May cause TLS failures during upgrade | HIGH |
| Disk space < 20% | May cause ETCD or kubelet failures | HIGH |
| Version skip attempt | 1.33 → 1.35 etc. | CRITICAL |
| `upgrade-cluster.yml` exit != 0 | Ansible playbook failed | CRITICAL |
| FailedEvict events | PDB blocking drain | HIGH |
| Pod CrashLoopBackOff surge | Version compatibility issue | HIGH |
| ETCD unhealthy post-upgrade | Data store degraded after upgrade | CRITICAL |

### On Abort

1. Report the exact error, affected node/host, and phase.
2. If failure is in Phase 3 (playbook execution):
   - Some nodes may be upgraded, others not → mixed-version cluster.
   - The ETCD snapshot from Phase 1 is the recovery point.
   - Guide user to either re-run the playbook (Kubespray is idempotent) or restore from ETCD backup.
3. Never attempt automatic rollback without user consent.

---

## Safety Rules (Non-negotiable)

1. **No version skipping**: Minor +1 only.
2. **Control Plane first**: Kubespray handles this automatically. If running manual steps, always control-plane before workers.
3. **ETCD backup mandatory**: Never skip Phase 1. This is the only rollback path for on-prem.
4. **PDB respect**: Never force-drain. Report and wait.
5. **No phase reversal**: Strict order 0 → 5.
6. **Dry-run before execution**: Phase 3-1 check mode before actual run.
