# Terraform EKS 업그레이드 — 참조

## 완료 보고 형식

모든 Phase 완료 후 다음 형식으로 결과를 보고한다:

```
업그레이드 완료 - EKS {현재버전} → {대상버전}

실행된 작업 (순서 준수)

┌──────────┬──────────────────────────────┬─────────────────────────────────┐
│   단계   │             대상             │              결과               │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 0  │ EKS Insights / PDB / 노드    │ 전부 PASSING / 충족 / Ready     │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 1  │ terraform.tfvars             │ 버전 및 AMI alias 업데이트 완료  │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 2  │ Control Plane                │ {현재버전} → {대상버전} ACTIVE   │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 3  │ Add-on (vpc-cni/coredns/...) │ 전부 ACTIVE                     │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 4  │ Managed Node Group           │ Rolling Update 완료             │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 5  │ Karpenter 노드               │ Drift 교체 완료                 │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 6  │ 전체 Terraform Apply         │ 완료 (변경사항 N개)             │
├──────────┼──────────────────────────────┼─────────────────────────────────┤
│ Phase 7  │ 최종 클러스터 검증           │ 전 노드 Ready, 전 Pod Running   │
└──────────┴──────────────────────────────┴─────────────────────────────────┘

최종 클러스터 상태
- Control Plane: {대상버전} ACTIVE
- Managed Node Group: {대상버전} AMI (AL2023)
- Karpenter 노드: {대상버전} (Bottlerocket)
- 전체 Pod: Running/Completed

terraform.tfvars 변경 내용
eks_cluster_version             = "{대상버전}"
eks_node_ami_alias_al2023       = "al2023@{새AMI}"
eks_node_ami_alias_bottlerocket = "bottlerocket@{새버전}"
```

## 비상 중단 기준 (Abort Conditions)

다음 조건 중 하나라도 충족되면 즉시 실행을 중단하고 사용자에게 보고한다:

| 조건 | 상황 |
|------|------|
| EKS Insights ERROR | 업그레이드 비호환 리소스 존재 |
| PDB disruptionsAllowed=0 | Drain 시 서비스 중단 불가피 |
| 노드 NotReady (업그레이드 전) | 클러스터 이미 불안정 상태 |
| terraform plan에 예상 외 destroy | 의도하지 않은 리소스 삭제 위험 |
| FailedEvict 이벤트 발생 | PDB 위반으로 Drain 실패 |
| Add-on status DEGRADED | Add-on 업그레이드 실패 |
| Pod CrashLoopBackOff 급증 | 버전 호환성 문제 의심 |
| Control Plane status FAILED | AWS 측 업그레이드 실패 |
