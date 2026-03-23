---
id: INF-002
name: 대상 버전 AMI 가용성 검증
severity: CRITICAL
category: infrastructure
phase: pre-flight
applies_when: 항상
---

# INF-002: 대상 버전 AMI 가용성 검증

## 목적

대상 Kubernetes 버전에 맞는 AMI가 AWS SSM Parameter Store에 존재하는지 확인한다. 새 버전 출시 직후에는 AMI가 아직 준비되지 않았을 수 있다.

## 검증 항목

### 1. 프로젝트에서 사용 중인 AMI 타입 감지

```bash
grep -rE 'ami_type|ami_alias|amiSelectorTerms|eks_node_ami_alias' \
  "${TF_DIR}" --include="*.tf" --include="*.tfvars" --include="*.tfvars.example" 2>/dev/null
```

### 2. AMI 타입별 SSM 조회

AL2023:
```bash
aws ssm get-parameters-by-path \
  --path "/aws/service/eks/optimized-ami/${TARGET_VERSION}/amazon-linux-2023/x86_64/standard" \
  --recursive --query 'Parameters[].Name' --output text \
  | tr '\t' '\n' | awk -F'/' '{print $NF}' | sort -V | tail -5
```

Bottlerocket:
```bash
aws ssm get-parameters-by-path \
  --path "/aws/service/bottlerocket/aws-k8s-${TARGET_VERSION}/x86_64" \
  --recursive --query 'Parameters[].Name' --output text \
  | tr '\t' '\n' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | sort -t. -k1,1n -k2,2n -k3,3n | uniq | tail -5
```

## Gate 조건

| 결과 | 판정 | 처리 |
|------|------|------|
| 모든 AMI 타입에 대해 TARGET_VERSION AMI 존재 | ✅ PASS | 진행 |
| SSM 조회 결과 비어있음 | ❌ FAIL | STOP — AMI 미출시. 며칠 후 재시도 |
| 일부 AMI 타입만 존재 | ⚠️ WARN | 보고 — 해당 AMI 타입 사용 여부 확인 |

## 조치 방안

- AMI 미출시: AWS에서 AMI를 릴리스할 때까지 대기 (보통 EKS 버전 출시 후 1-2주 내)
- 커스텀 AMI 사용 시: 사용자가 직접 TARGET_VERSION 기반 AMI를 빌드해야 함
