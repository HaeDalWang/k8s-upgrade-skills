# Helm K8s Compatibility — Reference

Output templates and remediation guidance for `helm_compat_check.py`.
The checker emits findings to the audit log; this file standardizes how the agent reports them.

---

## Finding Types

| rule_id | Axis | Typical severity | Meaning |
|---|---|---|---|
| `HELM-SUPPORT` | support | CRITICAL / HIGH / MEDIUM | Installed chart version vs target K8s support |
| `HELM-LIFECYCLE` | lifecycle | HIGH | Chart retired, or installed release past EOL |
| `HELM-K8SBREAK` | k8s_breaks | CRITICAL / HIGH | Removed/changed K8s API hit in the jump window |
| `HELM-CRD` | cross-cutting | HIGH | CRD-bearing chart needs a bump (Helm won't auto-update CRDs) |
| `HELM-HAZARD` | upgrade_hazards | HIGH | Manual step on chart bump (IAM, webhook, removed flag, …) |
| `HELM-UNKNOWN` | — | MEDIUM | Chart not in registry — manual review required |

---

## Report Template (보고서)

### Korean Template (output_language: ko)

```
# Helm 호환성 점검 결과

## 점검 개요
- 대상: K8s {CURRENT} → {TARGET}
- 설치 Release: {N}개 | registry 등록 차트: {M}개
- 판정: {OPEN / WARN / BLOCKED}

## ❌ 차단 (CRITICAL)
- {chart} {version}: {detail}
  → 조치: {remediation}

## ⚠️ 확인 필요 (HIGH)
- {chart}: {detail}
  → 조치: {remediation}

## ℹ️ 수동 검토 (INFO)
- {chart} {version}: registry 미등록 — kubeVersion·릴리스 노트 직접 확인

## 다음 단계
{BLOCKED이면: 차단 항목 조치 후 재실행}
{WARN이면: 위 HIGH 항목을 검토하고 진행 여부 결정}
{OPEN이면: Helm 측 차단 요인 없음, 업그레이드 진행 가능}

감사 로그: {AUDIT_LOG_PATH}
```

### English Template (output_language: en)

```
# Helm Compatibility Check Result

## Overview
- Target: K8s {CURRENT} → {TARGET}
- Installed releases: {N} | registered charts: {M}
- Verdict: {OPEN / WARN / BLOCKED}

## ❌ Blocking (CRITICAL)
- {chart} {version}: {detail}
  → Action: {remediation}

## ⚠️ Review Required (HIGH)
- {chart}: {detail}
  → Action: {remediation}

## ℹ️ Manual Review (INFO)
- {chart} {version}: not in registry — check kubeVersion / release notes manually

## Next Steps
{If BLOCKED: resolve blocking items, then re-run}
{If WARN: review HIGH items and decide whether to proceed}
{If OPEN: no Helm-side blockers, safe to proceed}

Audit log: {AUDIT_LOG_PATH}
```

---

## Remediation Hints by Finding

Use these as the `→ 조치` line. Tailor to the specific chart from the finding detail.

| Finding | Remediation |
|---|---|
| `HELM-SUPPORT` window exceeded | Bump the chart to a version whose support window includes the target K8s, **before** upgrading the cluster. |
| `HELM-STALE` | The registry entry backing this PASS is older than 180 days (or has no `last_verified`). Not a defect — re-check `compat_source` and update `last_verified` if it still holds. |
| `HELM-SUPPORT` minor_pin mismatch | Upgrade the chart so its app minor equals the target K8s minor (e.g. cluster-autoscaler 1.34.x for K8s 1.34). |
| `HELM-SUPPORT` unknown | Open the chart's `compat_source` URL; confirm target-K8s support from official docs. Do not assume PASS. |
| `HELM-LIFECYCLE` whole_retired | Plan migration to the documented successor (e.g. Gateway API). Existing deploys keep working but receive no security fixes. |
| `HELM-LIFECYCLE` per_release EOL | Upgrade to a currently-supported release of the same chart. |
| `HELM-K8SBREAK` | The target removes/changes an API this chart relies on. Bump the chart to the version that supports the new API. |
| `HELM-CRD` | Helm v3 does not auto-update CRDs. Run `kubectl apply` on the chart's CRDs before/after `helm upgrade`. |
| `HELM-HAZARD` | Follow the chart's UPGRADE notes for the specific version jump (IAM policy, webhook, removed flags). |
| `HELM-UNKNOWN` | Inspect `helm show chart <repo>/<name>` kubeVersion and the project's release notes manually. |

---

## When the Checker Cannot Run

| Symptom | Cause | Response |
|---|---|---|
| exit `127` | `helm` not installed or no cluster access | Report plainly; ask user to install helm / fix kubeconfig. **Not a pass.** |
| exit `64` | Usage error — bad version string, downgrade/same version, malformed `--releases-json` | Fix the invocation and re-run. This is **not** a gate verdict; never read it as WARN. |
| 0 registered charts loaded | `--registry-dir` wrong or empty | Verify the path points at `helm-k8s-compat/registry/`. |

Never convert an inability-to-check into an implicit "compatible." Surface the gap to the user.
