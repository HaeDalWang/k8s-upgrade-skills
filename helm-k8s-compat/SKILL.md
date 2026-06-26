---
name: helm-k8s-compat
description: >
  Pre-upgrade compatibility check for Helm-installed charts against a target Kubernetes version.
  Detects chart-level upgrade blockers that EKS Insights and kubent cannot see — supported-version
  windows, retired/EOL charts, K8s API-removal breakage, and manual CRD/IAM/webhook upgrade hazards.
  Uses a curated registry of de-facto-standard charts plus live `helm` inspection.
  Trigger keywords: 'helm compatibility', 'helm chart k8s version', 'chart upgrade readiness',
  'helm 호환성', '차트 호환성', 'helm 버전 점검'
---

# Helm ↔ Kubernetes Compatibility Check

Verify that Helm-installed charts will survive a Kubernetes minor-version upgrade **before** it runs.

This skill answers the question EKS Insights and kubent cannot: *"Will my installed charts' controllers
keep working on the target version, and is my chart version even supported there?"* That knowledge lives
in release notes and support matrices, not in live API scans.

The verdict is produced by a deterministic Python script (`helm_compat_check.py`) whose exit code is the
single source of truth — the LLM interprets and reports, but cannot override the gate.

All scripts are in `./scripts/`. The curated knowledge base is in `./registry/`.

---

## When to Use

- As a **Phase 0 supplement** during a Kubernetes/EKS upgrade (run alongside the main upgrade skill's pre-flight gate).
- **Standalone**, any time, to audit chart compatibility without performing an upgrade.

This skill is IaC-agnostic — it inspects Helm releases, not Terraform/CDK/etc. It works whether or not
the main upgrade skill is installed.

---

## Prerequisites

| Requirement | Purpose |
|---|---|
| `helm` CLI (v3+) with cluster access | List installed releases (`helm ls -A`) |
| `python3` (3.9+) | Run the checker (stdlib only, no third-party deps) |
| Current + target K8s version | e.g. `1.33` → `1.34` |

> The checker can also run **without a cluster** via `--releases-json` injection (testing / dry-run).

---

## Step 1: Collect Inputs

Determine the current and target Kubernetes **minor** versions.

- If invoked from the main upgrade skill: reuse `current_version` / `target_version` from the recipe.
- If standalone: ask the user.

```
Helm 호환성 점검을 위해 알려주세요:

1. 현재 Kubernetes 버전 (예: 1.33)
2. 대상 Kubernetes 버전 (예: 1.34)
```

> One minor step at a time (1.33 → 1.34). For multi-step upgrades, run the check once per step.

---

## Step 2: Run the Compatibility Check

Run from the skill root:

```bash
python3 scripts/helm_compat_check.py \
  --current <CURRENT_VERSION> \
  --target <TARGET_VERSION> \
  --registry-dir ./registry \
  --audit-log <AUDIT_LOG_PATH>
```

The script does the following automatically:
1. `helm ls -A -o json` to enumerate installed releases.
2. Match each release against the curated `registry/` by chart name.
3. Evaluate three orthogonal axes plus K8s API-removal events (see `registry/_schema.md`):
   - **support** — does the installed chart version support the target K8s? (`window` / `minor_pin` / `unknown`)
   - **lifecycle** — is the chart retired, or is the installed release past its EOL date?
   - **upgrade_hazards** — if the chart must be bumped, what manual steps bite (CRD re-apply, IAM, webhook, removed flags)?
   - **k8s_breaks** — removed/changed APIs in the jump window (`current < V <= target`).
4. Append findings to the audit log and exit with a gate code.

> If `helm` is unavailable or the cluster is unreachable, the script exits `127`. Do not silently
> treat this as a pass — report it and ask the user to fix access.

---

## Step 3: Interpret the Exit Code (do NOT override)

| Exit | Meaning | Action |
|---|---|---|
| `0` | OPEN — no compatibility problems | Proceed. |
| `1` | BLOCKED — CRITICAL finding(s) | **Stop.** A chart does not support the target version (or hits a removed API). Resolve before upgrading. |
| `2` | WARN — HIGH finding(s) | Manual review required. Surface every finding to the user and get explicit confirmation. |
| `127` | helm CLI missing / no cluster access | Report; ask user to install helm or fix kubeconfig. Not a pass. |

**The exit code is authoritative.** Read it directly; never re-derive the verdict from the printed text.

---

## Step 4: Report to the User

Summarize the audit log findings in Korean. Group by severity and always include the remediation hint.

Example report shape:

```
## Helm 호환성 점검 결과 (1.33 → 1.34)

### ❌ 차단 (CRITICAL)
- ingress-nginx 4.13.5: K8s 1.33이 상한입니다. 1.34로 올리려면 차트를 4.14.x 이상으로 먼저 업그레이드하세요.

### ⚠️ 확인 필요 (HIGH)
- ingress-nginx: 프로젝트가 retirement 되었습니다 (2026-03 EOL). Gateway API 구현체로의 이전 계획이 필요합니다.

### ℹ️ 수동 검토 (INFO)
- my-internal-app 2.1.0: registry 미등록 차트입니다. kubeVersion·릴리스 노트를 직접 확인하세요.

감사 로그: <AUDIT_LOG_PATH>
```

For `unknown`-type charts (no machine-readable matrix), fetch the chart's `compat_source` URL to give the
user the latest official support guidance instead of guessing.

---

## Known Limitations (state these honestly)

- **Registry coverage is curated, not exhaustive.** Only de-facto-standard charts are deeply modeled.
  Unregistered charts get a best-effort `kubeVersion` note and a "manual review required" flag — never a silent pass.
- **`kubeVersion` is a weak signal.** Most charts declare only a lower bound (`>=1.21`), so it rarely
  catches incremental-upgrade blockers. The curated registry is the real source of truth.
- **Support matrices drift.** Registry data reflects the date it was curated. For `unknown` charts and
  borderline cases, the live `compat_source` fetch is authoritative.
- This skill checks **chart compatibility**, not running-workload API usage. Pair it with EKS Insights /
  kubent (API scans) for full coverage — they are complementary, not redundant.

---

## Adding a Chart to the Registry

See `registry/_schema.md` for the full schema and checklist. In short: confirm the version scheme with
`helm show chart`, capture the official `compat_source` URL (do not rely on memory), classify the support
type, record lifecycle/EOL, extract upgrade hazards from release notes, and add an evaluation test.
