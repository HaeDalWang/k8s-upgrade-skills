---
name: k8s-version-upgrade
description: >
  Zero-downtime Kubernetes version upgrade across multiple infrastructure types (AWS EKS, On-prem Kubespray).
  Validates recipe, routes to the correct platform/IaC-specific sub-skill, and enforces phase-gated safety.
  Trigger keywords: 'K8s upgrade', 'EKS upgrade', 'Kubernetes version upgrade', 'K8s version upgrade',
  'upgrade EKS', 'upgrade Kubernetes', 'cluster upgrade'
---

# Kubernetes Version Upgrade — Root Router

This skill upgrades Kubernetes clusters across multiple infrastructure types with zero-downtime and workload protection.
It reads user requirements from `recipe.yaml`, validates them, and routes to exactly ONE platform-specific sub-skill.

---

## Step 1: Read and Validate Recipe

Find `recipe.yaml` in the project root or current working directory. If not found, fall back to `recipe.md` (YAML block inside markdown).

Run schema validation before parsing:

```bash
python3 scripts/validate_recipe.py recipe.yaml
```

If validation fails (exit code 1), report the error to the user and do NOT proceed.

### Required Fields

| Field | Type | Allowed Values |
|---|---|---|
| `environment` | string | `aws`, `on-prem` |
| `platform` | string | `eks`, `kubespray` |
| `iac` | string | `terraform`, `none` |
| `cluster_name` | string | non-empty cluster identifier |
| `current_version` | string | e.g. `"1.34"` (quoted) |
| `target_version` | string | e.g. `"1.35"` (quoted) |

If ANY required field is empty or missing, list all missing fields and ask the user to fill them. Do NOT proceed until all 6 fields are populated.

### Version Constraint

- `gap == 1` → Proceed
- `gap == 0` → "Already at target version. No upgrade needed."
- `gap > 1` → "Version skip is NOT allowed. Upgrade one step at a time."
- `gap < 0` → "Downgrade is not supported."

### Optional Fields

| Field | Default | Purpose |
|---|---|---|
| `output_language` | `ko` | Final report language. `ko` = Korean, `en` = English |
| `notes` | (empty) | User-provided special instructions or constraints |

---

## Step 2: Route to Sub-Skill

Match the `(environment, platform, iac)` tuple against the routing table. Select exactly ONE sub-skill.

| environment | platform | iac | Sub-Skill Path |
|---|---|---|---|
| `aws` | `eks` | `terraform` | [aws/terraform-eks/SKILL.md](aws/terraform-eks/SKILL.md) |
| `on-prem` | `kubespray` | `none` | on-prem/kubespray/SKILL.md *(not implemented — planned)* |

### Routing Rules

1. **Exact match only**: All three fields must match a row in the table.
2. **No mixing**: Execute ONLY the matched sub-skill.
3. **No match**: Show the supported combinations table and suggest updating the recipe.
4. **Single execution**: Only one sub-skill runs per invocation.

---

## Step 3: Execute Sub-Skill

Read the matched sub-skill file and follow its phases sequentially from Phase 0 onward.

### Universal Safety Rules (Non-negotiable)

| # | Rule | Detail |
|---|---|---|
| 1 | **No Version Skipping** | Minor version +1 only. Reject 1.33 → 1.35. |
| 2 | **Control Plane First** | Data plane version must NEVER exceed control plane. |
| 3 | **Phase Gates** | Every phase boundary requires ALL validations to pass via gate scripts. |
| 4 | **PDB Respect** | Never force-drain past PodDisruptionBudgets. |
| 5 | **No Reverse Phases** | Phases execute in strict ascending order. |
| 6 | **Plan Before Apply** | Every infrastructure mutation must be previewed before execution. |
| 7 | **Abort on Failure** | Any unexpected error → STOP, report, and await user decision. |
| 8 | **Gate Scripts Are Authoritative** | The LLM MUST NOT override or reinterpret gate script exit codes. |

### Output Language

All **user-facing output** (phase summaries, completion reports, error messages) must be in the language specified by `output_language` in the recipe file.
- Default: `ko` (Korean)
- Internal processing and reasoning: English (for accuracy)
- Sub-skill SKILL.md instructions are written in English for LLM consistency
