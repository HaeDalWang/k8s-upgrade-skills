# Terraform EKS Upgrade — Reference

## Completion Report Template

After all phases are complete, generate the report below.
Use the language specified by `output_language` in recipe.md (default: Korean).

### Korean Template (output_language: ko)

```
업그레이드 완료 — EKS {CURRENT_VERSION} → {TARGET_VERSION}

실행된 작업 (순서 준수)

┌──────────┬──────────────────────────────┬─────────────────────────────────┐
│   단계   │             대상             │              결과               │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 0  │ EKS Insights / PDB / 노드    │ 전부 PASSING / 충족 / Ready     │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 1  │ terraform.tfvars             │ 버전 및 AMI alias 업데이트 완료  │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 2  │ Control Plane                │ {CURRENT_VERSION} → {TARGET_VERSION} ACTIVE │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 3  │ Add-on (vpc-cni/coredns/...) │ 전부 ACTIVE                     │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 4  │ Managed Node Group           │ Rolling Update 완료             │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 5  │ Karpenter 노드               │ Drift 교체 완료 / 미사용        │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 6  │ 전체 Terraform Apply         │ 완료 (변경사항 N개) / No changes │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 7  │ 최종 클러스터 검증           │ 전 노드 Ready, 전 Pod Running   │
└──────────┴──────────────────────────────┴─────────────────────────────────┘

최종 클러스터 상태
- Control Plane: {TARGET_VERSION} ACTIVE
- Managed Node Group: v{TARGET_VERSION}.x ({AMI_TYPE})
- Karpenter 노드: v{TARGET_VERSION}.x ({AMI_TYPE}) / 미사용
- 전체 Pod: Running/Completed

terraform.tfvars 변경 내용
eks_cluster_version             = "{TARGET_VERSION}"
eks_node_ami_alias_al2023       = "{NEW_VALUE}"    # {OLD_VALUE} → {NEW_VALUE}
eks_node_ami_alias_bottlerocket = "{NEW_VALUE}"    # {OLD_VALUE} → {NEW_VALUE}
```

### English Template (output_language: en)

```
Upgrade Complete — EKS {CURRENT_VERSION} → {TARGET_VERSION}

Executed Steps (in order)

┌──────────┬──────────────────────────────┬─────────────────────────────────┐
│  Phase   │           Target             │            Result               │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 0  │ EKS Insights / PDB / Nodes   │ All PASSING / Safe / Ready      │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 1  │ terraform.tfvars             │ Version & AMI alias updated     │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 2  │ Control Plane                │ {CURRENT_VERSION} → {TARGET_VERSION} ACTIVE │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 3  │ Add-ons (vpc-cni/coredns/..) │ All ACTIVE                      │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 4  │ Managed Node Group           │ Rolling Update complete         │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 5  │ Karpenter Nodes              │ Drift replacement done / N/A    │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 6  │ Full Terraform Apply         │ Complete (N changes) / No changes│
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 7  │ Final Cluster Validation     │ All nodes Ready, all pods Running│
└──────────┴──────────────────────────────┴─────────────────────────────────┘

Final Cluster State
- Control Plane: {TARGET_VERSION} ACTIVE
- Managed Node Group: v{TARGET_VERSION}.x ({AMI_TYPE})
- Karpenter Nodes: v{TARGET_VERSION}.x ({AMI_TYPE}) / Not used
- All Pods: Running/Completed

terraform.tfvars Changes
eks_cluster_version             = "{TARGET_VERSION}"
eks_node_ami_alias_al2023       = "{NEW_VALUE}"    # {OLD_VALUE} → {NEW_VALUE}
eks_node_ami_alias_bottlerocket = "{NEW_VALUE}"    # {OLD_VALUE} → {NEW_VALUE}
```

---

## Abort Conditions

If ANY of the following conditions is met, **STOP immediately** and report to the user:

| Condition | Situation | Severity |
|---|---|---|
| EKS Insights `ERROR` | Incompatible resources detected for target version | CRITICAL |
| PDB `disruptionsAllowed == 0` | Node drain will cause service disruption | CRITICAL |
| Node `NotReady` (pre-upgrade) | Cluster already unstable before upgrade | CRITICAL |
| `terraform plan` shows unexpected destroy | Unintended resource deletion risk | CRITICAL |
| `FailedEvict` events during rolling update | PDB blocking drain | HIGH |
| Add-on status `DEGRADED` / `CREATE_FAILED` | Add-on upgrade failure | HIGH |
| Pod `CrashLoopBackOff` surge after upgrade | Version compatibility issue suspected | HIGH |
| Control Plane status `FAILED` | AWS-side upgrade failure | CRITICAL |
| `terraform apply` exit code != 0 | Infrastructure mutation failed | HIGH |
| SSM AMI query returns empty | Target version AMI not yet available | MEDIUM |

### On Abort

1. Report the exact error, affected resource, and phase where failure occurred.
2. Do NOT attempt automatic rollback — EKS control plane upgrades are irreversible.
3. Suggest the user investigate the root cause before retrying.
4. If the failure is in Data Plane (Phase 4+) and Control Plane is already upgraded, the cluster is in a mixed-version state. Guide the user to complete the Data Plane upgrade manually if needed.
