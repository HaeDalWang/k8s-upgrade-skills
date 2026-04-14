---
name: k8s-version-upgrade
description: >
  Zero-downtime Kubernetes version upgrade across multiple infrastructure types (AWS EKS, On-prem Kubespray).
  Validates recipe.md, routes to the correct platform/IaC-specific sub-skill, and enforces phase-gated safety.
  Trigger keywords: 'K8s upgrade', 'EKS upgrade', 'Kubernetes version upgrade', '쿠버네티스 업그레이드',
  'EKS 버전 올리기', '무중단 업그레이드', 'K8s 버전 업그레이드', '온프레미스 업그레이드'
---

# Kubernetes Version Upgrade — Root Router

This skill upgrades Kubernetes clusters across multiple infrastructure types with **zero-downtime** and **workload protection**.
It reads user requirements from `recipe.yaml`, validates them, and routes to exactly ONE platform-specific sub-skill.

---

## Step 1: Read and Validate recipe.yaml (or recipe.md)

Find `recipe.yaml` in the project root or current working directory. If not found, fall back to `recipe.md` (YAML block inside markdown).

**검증**: 파싱 전에 반드시 스키마 검증을 실행한다.

```bash
python3 scripts/validate_recipe.py recipe.yaml
# 또는
python3 scripts/validate_recipe.py recipe.md
```

검증 실패(exit code 1) 시 에러 메시지를 사용자에게 보고하고 진행하지 않는다.

Parse the YAML content (from `.yaml` file directly, or from the code block inside `.md`).

### 1-1. Required Fields

| Field | Type | Allowed Values |
|---|---|---|
| `environment` | string | `aws`, `on-prem` |
| `platform` | string | `eks`, `kubespray` |
| `iac` | string | `terraform`, `none` |
| `cluster_name` | string | non-empty cluster identifier |
| `current_version` | string | e.g. `"1.34"` (quoted) |
| `target_version` | string | e.g. `"1.35"` (quoted) |

**Validation**: If ANY required field is empty or missing, list all missing fields and ask the user to fill them. Do NOT proceed until all 6 fields are populated.

### 1-2. Version Constraint Check

Parse `current_version` and `target_version` as `major.minor` integers.

```
current_minor = int(current_version.split('.')[1])
target_minor  = int(target_version.split('.')[1])
gap = target_minor - current_minor
```

**Validation**:
- `gap == 1` → Proceed.
- `gap == 0` → "Already at target version. No upgrade needed."
- `gap > 1` → "Version skip is NOT allowed. Kubernetes only supports minor version +1 upgrades (e.g. 1.34 → 1.35). Upgrade one step at a time."
- `gap < 0` → "Downgrade is not supported by this skill."

### 1-3. Optional Fields

| Field | Default | Purpose |
|---|---|---|
| `output_language` | `ko` | Final report language. `ko` = Korean, `en` = English |
| `notes` | (empty) | User-provided special instructions or constraints |

---

## Step 2: Route to Sub-Skill

Match the `(environment, platform, iac)` tuple against the routing table below. Select exactly ONE sub-skill.

### Routing Table

| environment | platform | iac | Sub-Skill Path |
|---|---|---|---|
| `aws` | `eks` | `terraform` | [aws/terraform-eks/SKILL.md](aws/terraform-eks/SKILL.md) |
| `on-prem` | `kubespray` | `none` | on-prem/kubespray/SKILL.md *(미구현 — 계획됨)* |

### Routing Rules

1. **Exact match only**: All three fields must match a row in the table.
2. **No mixing**: Execute ONLY the matched sub-skill. Never combine procedures from different sub-skills.
3. **No match**: If the combination is not in the table, respond with:
   - The supported combinations table above.
   - A suggestion to either update recipe.md or request that a new sub-skill be added for the desired platform.
4. **Single execution**: Only one sub-skill runs per invocation.

---

## Step 3: Execute Sub-Skill

Read the matched sub-skill file and follow its phases sequentially from Phase 0 onward.
Every sub-skill MUST obey these universal rules:

### Universal Safety Rules (Non-negotiable)

| # | Rule | Detail |
|---|---|---|
| 1 | **No Version Skipping** | Minor version +1 only. Reject 1.33 → 1.35. |
| 2 | **Control Plane First** | Control plane upgraded before data plane. Data plane version must NEVER exceed control plane. |
| 3 | **Phase Gates** | Every phase boundary requires ALL validations to pass. If ANY validation fails → STOP immediately and report. |
| 4 | **PDB Respect** | Never force-drain past PodDisruptionBudgets. If `disruptionsAllowed == 0`, report and wait for user resolution. |
| 5 | **No Reverse Phases** | Phases execute in strict ascending order. No skipping, no reordering. |
| 6 | **Plan Before Apply** | Every infrastructure mutation must be previewed (terraform plan / ansible --check / dry-run) before execution. |
| 7 | **Abort on Failure** | Any unexpected error during apply/execution → STOP, report full error context, and await user decision. |

### MCP Servers

This skill can leverage MCP servers for richer data. Configuration method varies by AI tool
(Claude Code: `.mcp.json`, Kiro: `.kiro/settings/mcp.json`, etc.):

| Server | Purpose | Used By |
|---|---|---|
| `awslabs.eks-mcp-server` | EKS Insights, K8s resource listing | AWS sub-skills |
| `kubernetes-mcp-server` | Node/Pod status queries | All sub-skills |

MCP servers are optional. If unavailable or a call fails, fall back to equivalent CLI commands (aws cli, kubectl, terraform).

### Output Language

All **user-facing output** (phase summaries, completion reports, error messages) must be in the language specified by `output_language` in recipe.md.
- Default: `ko` (Korean)
- Internal processing and reasoning: English (for accuracy)
