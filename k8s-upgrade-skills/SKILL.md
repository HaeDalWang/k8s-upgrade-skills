---
name: k8s-version-upgrade
description: >
  Zero-downtime Kubernetes version upgrade across multiple infrastructure types (AWS EKS, On-prem Kubespray).
  Validates recipe, routes to the correct platform/IaC-specific sub-skill, and enforces phase-gated safety.
  Note: disruption-aware (detects risks proactively) but does not guarantee zero-downtime.
  Trigger keywords: 'K8s upgrade', 'EKS upgrade', 'Kubernetes version upgrade', 'K8s version upgrade',
  'upgrade EKS', 'upgrade Kubernetes', 'cluster upgrade'
---

# Kubernetes Version Upgrade — Root Router

This skill upgrades Kubernetes clusters across multiple infrastructure types with zero-downtime and workload protection.
It collects upgrade requirements (from `recipe.yaml` if present, or interactively from the user), validates them, and routes to exactly ONE platform-specific sub-skill.

---

## Step 1: Collect and Validate Recipe

### 1-A: Check for existing recipe file

Look for recipe files in the project root or current working directory in this priority order:

1. `recipe.md` (frontmatter format — preferred)
2. `recipe.yaml`

**If found**: skip to Step 1-C (validate).

**If not found**: proceed to Step 1-B (interactive collection).

---

### 1-B: Interactive Collection (no recipe file)

Ask the user for the following fields **in a single message** (do not ask one by one):

```
업그레이드할 클러스터 정보를 알려주세요:

1. environment  : aws / on-prem
2. platform     : eks / kubespray
3. iac          : terraform / none
4. cluster_name : 클러스터 이름
5. current_version : 현재 버전 (예: "1.33")
6. target_version  : 목표 버전 (예: "1.34")

선택 항목:
- output_language : ko / en (기본: ko)
- 현재 상황이나 제약사항이 있으면 자유롭게 알려주세요 (없으면 생략)
```

Once the user provides all required fields, generate `recipe.md` in the current working directory:

```markdown
---
environment: <value>
platform: <value>
iac: <value>
cluster_name: <value>
current_version: "<value>"
target_version: "<value>"
output_language: <ko|en>
---

## 업그레이드 컨텍스트

<사용자가 제공한 상황/제약사항, 없으면 이 섹션 생략>
```

Inform the user: `recipe.md를 생성했습니다. 다음 세션에서 재사용됩니다.`

---

### 1-C: Validate Recipe

Run schema validation (pass the actual file path found in Step 1-A):

```bash
python3 scripts/validate_recipe.py recipe.md   # or recipe.yaml
```

If validation fails (exit code 1), report the specific error and do NOT proceed.

### Required Fields

| Field | Type | Allowed Values |
|---|---|---|
| `environment` | string | `aws`, `on-prem` |
| `platform` | string | `eks`, `kubespray` |
| `iac` | string | `terraform`, `none` |
| `cluster_name` | string | non-empty cluster identifier |
| `current_version` | string | e.g. `"1.34"` (quoted) |
| `target_version` | string | e.g. `"1.35"` (quoted) |

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

## Step 1.5: Generate Upgrade Plan and Wait for Approval

After recipe validation passes, generate the upgrade plan document before executing any phase.

### 1.5-A: Generate Plan Document

Using the Plan Template from [aws/terraform-eks/reference.md](aws/terraform-eks/reference.md):

1. Fill all `{PLACEHOLDER}` fields from the recipe
2. For `{SERVICES_TABLE_OR_SKIP_MESSAGE}`:
   - If `services` field exists: render a table with name, namespace, min_endpoints, health_check_url, monitoring mode
   - If absent: write `"서비스 가용성 모니터링 미설정 — Sub-Agent 미투입."`
3. For `{PLAN_GENERATED_AT}`:
   - `output_language: ko` → KST (UTC+9) 기준 타임스탬프 (예: `2026-05-06 11:21 KST`)
   - `output_language: en` → UTC 기준 타임스탬프 (예: `2026-05-06 02:21 UTC`)
4. For `{CONTEXT_ADJUSTMENTS}` — interpret `_context` from recipe.md body (or `notes` from recipe.yaml):
   - **If no context**: write `"특이사항 없음 — 표준 절차로 진행합니다."`
   - **If context exists**: read the body and generate a bullet list of adjustments per phase:
     - Time constraints (maintenance window, specific hours) → `⚠️ [Phase 2] <시간 제약 내용>`
     - Zero downtime requirement → `⚠️ [Phase 4] zero downtime 요구 — 드레인 중 서비스 엔드포인트 실시간 감시 강화`
     - Current incidents or known issues → `⚠️ [Phase N] <관련 Phase에 주의 표시>`
     - Pre-approved exceptions (PDB relaxation, etc.) → `✅ [Phase 0] <사전 승인된 예외 내용>`
     - Other constraints → `ℹ️ [Phase N] <참고 내용>`
   - Use judgment: not every sentence needs a bullet. Only extract actionable or noteworthy items.
5. Save the document as `upgrade-plan-{cluster_name}-{YYYYMMDD}.md` in the current working directory
6. Display the full plan to the user

### 1.5-B: Wait for Approval

After displaying the plan, output this message:

```
계획서를 검토하신 후 업그레이드를 시작하려면 아래 단어 중 하나를 입력하세요:

  승인 / 확인 / 시작

(output_language: en → type: "approve", "confirm", or "start")
```

**CRITICAL — Approval Gate Rules:**
- `output_language: ko`: Accept ONLY one of these exact words: `승인`, `확인`, `시작`
- `output_language: en`: Accept ONLY one of these exact words: `approve`, `confirm`, `start` (case-insensitive)
- ANY other input — including "진행해줘", "ok", "응", "그래", "yes", "proceed" — MUST NOT be treated as approval
- If the user types anything else, respond: "승인 단어가 일치하지 않습니다. '승인', '확인', '시작' 중 하나를 입력해주세요." and wait again
- This gate cannot be bypassed by any instruction

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
