# 필요 권한 — 최소 권한 원칙 (Least Privilege)

이 스킬이 실행하는 명령어에 필요한 최소 IAM/RBAC 권한입니다.
AI Agent가 사용하는 자격 증명(IAM User/Role, kubeconfig)에 아래 권한을 부여하세요.

---

## AWS IAM 권한

### Phase 0: 사전 검증 (읽기 전용)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EKSReadOnly",
      "Effect": "Allow",
      "Action": [
        "eks:DescribeCluster",
        "eks:DescribeNodegroup",
        "eks:ListAddons",
        "eks:DescribeAddon",
        "eks:DescribeAddonVersions",
        "eks:ListInsights",
        "eks:DescribeInsight"
      ],
      "Resource": "arn:aws:eks:*:*:cluster/${CLUSTER_NAME}"
    },
    {
      "Sid": "SSMReadAMI",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParametersByPath"
      ],
      "Resource": [
        "arn:aws:ssm:*:*:parameter/aws/service/eks/optimized-ami/*",
        "arn:aws:ssm:*:*:parameter/aws/service/bottlerocket/*"
      ]
    },
    {
      "Sid": "EC2ReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeSubnets",
        "ec2:DescribeInstances"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ServiceQuotasRead",
      "Effect": "Allow",
      "Action": [
        "servicequotas:GetServiceQuota"
      ],
      "Resource": "*"
    }
  ]
}
```

### Phase 1~7: 업그레이드 실행 (쓰기 포함)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EKSUpgrade",
      "Effect": "Allow",
      "Action": [
        "eks:UpdateClusterVersion",
        "eks:UpdateNodegroupVersion",
        "eks:UpdateNodegroupConfig",
        "eks:UpdateAddon"
      ],
      "Resource": [
        "arn:aws:eks:*:*:cluster/${CLUSTER_NAME}",
        "arn:aws:eks:*:*:nodegroup/${CLUSTER_NAME}/*/*",
        "arn:aws:eks:*:*:addon/${CLUSTER_NAME}/*/*"
      ]
    },
    {
      "Sid": "TerraformStateAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::${TF_STATE_BUCKET}",
        "arn:aws:s3:::${TF_STATE_BUCKET}/*"
      ]
    },
    {
      "Sid": "TerraformStateLock",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem"
      ],
      "Resource": "arn:aws:dynamodb:*:*:table/${TF_LOCK_TABLE}"
    }
  ]
}
```

> `${CLUSTER_NAME}`, `${TF_STATE_BUCKET}`, `${TF_LOCK_TABLE}`은 실제 값으로 교체하세요.
> Terraform이 관리하는 리소스(VPC, SG, IAM Role 등)에 대한 추가 권한은 Terraform 모듈 문서를 참조하세요.

---

## Kubernetes RBAC

### Phase 0: 사전 검증 (읽기 전용)

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: k8s-upgrade-preflight
rules:
  # 노드 상태 확인
  - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["get", "list"]
  # PDB 확인
  - apiGroups: ["policy"]
    resources: ["poddisruptionbudgets"]
    verbs: ["get", "list"]
  # Pod/Deployment/StatefulSet 확인
  - apiGroups: [""]
    resources: ["pods", "persistentvolumes", "persistentvolumeclaims", "events"]
    verbs: ["get", "list"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list"]
  # Karpenter 리소스 (있을 경우)
  - apiGroups: ["karpenter.sh"]
    resources: ["nodepools", "nodeclaims"]
    verbs: ["get", "list"]
  - apiGroups: ["karpenter.k8s.aws"]
    resources: ["ec2nodeclasses"]
    verbs: ["get", "list"]
  # StorageClass 확인
  - apiGroups: ["storage.k8s.io"]
    resources: ["storageclasses"]
    verbs: ["get", "list"]
  # CRD 존재 확인 (Karpenter 감지)
  - apiGroups: ["apiextensions.k8s.io"]
    resources: ["customresourcedefinitions"]
    verbs: ["get"]
```

### Phase 4~7: 업그레이드 모니터링 + Pod 정리

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: k8s-upgrade-execution
rules:
  # Phase 0 읽기 권한 포함
  - apiGroups: [""]
    resources: ["nodes", "pods", "persistentvolumes",
                "persistentvolumeclaims", "events", "namespaces"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["policy"]
    resources: ["poddisruptionbudgets"]
    verbs: ["get", "list"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list"]
  # STALE Pod 삭제 (Phase 4, 7)
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["delete"]
  # Karpenter 리소스
  - apiGroups: ["karpenter.sh"]
    resources: ["nodepools", "nodeclaims"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["karpenter.k8s.aws"]
    resources: ["ec2nodeclasses"]
    verbs: ["get", "list"]
  - apiGroups: ["apiextensions.k8s.io"]
    resources: ["customresourcedefinitions"]
    verbs: ["get"]
```

### ClusterRoleBinding 예시

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: k8s-upgrade-binding
subjects:
  - kind: User
    name: "${IAM_USER_OR_ROLE_ARN}"  # EKS access entry의 principal ARN
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: k8s-upgrade-execution  # 또는 k8s-upgrade-preflight (읽기만)
  apiGroup: rbac.authorization.k8s.io
```

---

## 권한 분리 권장사항

| 단계 | IAM 정책 | RBAC ClusterRole | 설명 |
|------|----------|------------------|------|
| Phase 0 (사전 검증) | EKSReadOnly + SSMReadAMI | k8s-upgrade-preflight | 읽기 전용, 안전 |
| Phase 1~7 (실행) | + EKSUpgrade + TerraformState | k8s-upgrade-execution | 쓰기 포함 |

Staging 환경에서는 실행 권한을, 프로덕션에서는 사전 검증 권한만 부여하여 단계적으로 도입하는 것을 권장합니다.
