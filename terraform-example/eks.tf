# EKS 클러스터 및 관리형 노드 그룹 (통합)
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.10.1" # 최신화 2025년 12월 11일

  name               = local.project
  kubernetes_version = var.eks_cluster_version

  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.private_subnets
  control_plane_subnet_ids = module.vpc.intra_subnets

  endpoint_public_access  = true
  endpoint_private_access = true

  # 클러스터를 생성한 IAM 객체에서 쿠버네티스 어드민 권한 할당
  enable_cluster_creator_admin_permissions = true
  # Nodepool에서 태그기반으로도 가져갈 수 있도록 선언
  node_security_group_tags = {
    "karpenter.sh/discovery" = local.project
  }
  # 노드 보안그룹 생성
  create_node_security_group = true

  # 로깅 비활성화
  enabled_log_types = []

  # Karpenter 노드가 아니며 초기 관리형노드그룹에 띄우기 위한 애드온들만 추가
  addons = {
    vpc-cni = {
      before_compute = true # 노드 그룹 생성 전에 설치 (필수)
      most_recent    = true
    }
    kube-proxy = {
      before_compute = true # 노드 그룹 생성 전에 설치 (필수)
      most_recent    = true
    }
    coredns = {
      before_compute = true # 노드 그룹 생성 전에 설치 (필수)
      most_recent    = true
      configuration_values = jsonencode({
        # 시스템 노드에 배포
        nodeSelector = {
          workload  = "system"
          nodegroup = "system"
        }
        tolerations = [
          {
            key      = "workload"
            operator = "Equal"
            value    = "system"
            effect   = "NoSchedule"
          }
        ]
        resources = {
          limits = {
            cpu    = "0.25"
            memory = "256M"
          }
          requests = {
            cpu    = "0.25"
            memory = "256M"
          }
        }
      })
    }
  }

  # 관리형 노드 그룹 통합
  eks_managed_node_groups = {
    system-node = {
      name            = "${local.project_prefix}-system-node"
      use_name_prefix = true # true로 설정하면 이름에 랜덤 서픽스가 추가되어 충돌 방지
      subnet_ids      = module.vpc.private_subnets

      # 켜두면 맨날 최신버전이라 업그레이드를 너무 자주해야함, 왜냐하면 최신버전 ami만 바라봄
      use_latest_ami_release_version = false
      ami_type                       = "AL2023_x86_64_STANDARD"
      capacity_type                  = "ON_DEMAND"
      instance_types                 = ["t3a.medium"]
      desired_size                   = 2
      min_size                       = 2
      max_size                       = 2

      # IAM Role 생성 + 기본 EKS 노드 정책 부착 기본값임
      # create_iam_role            = true
      # iam_role_attach_cni_policy = true

      # 시스템 워크로드만 스케줄되도록 테인트
      labels = {
        workload  = "system"
        nodegroup = "system"
      }
      taints = {
        workload = {
          key    = "workload"
          value  = "system"
          effect = "NO_SCHEDULE"
        }
      }

      tags = local.tags
    }
  }
}

# Karpenter 구성에 필요한 AWS 리소스 생성
module "karpenter" {
  source    = "terraform-aws-modules/eks/aws//modules/karpenter"
  version   = "21.10.1" # 최신화 2025년 12월 31일
  namespace = kubernetes_namespace_v1.karpenter.metadata[0].name

  cluster_name                  = module.eks.cluster_name
  node_iam_role_name            = "${module.eks.cluster_name}-node-role"

  # Pod Identity는 Fargate을 지원하지 않음, IRSA을 karpenter 모듈이 지원하지않음 그러므로 전부 false 후
  # 신뢰관계 정책을 직접 부여하는 방식으로 변경
  create_pod_identity_association = false
  iam_role_source_assume_policy_documents = [
    data.aws_iam_policy_document.karpenter_controller_assume_role_policy.json
  ]

  iam_policy_name            = "KarpenterController-${module.eks.cluster_name}"

  # Karpenter가 생성할 노드에 부여할 역할에 기본 정책 이외에 추가할 IAM 정책
  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
    AmazonEBSCSIDriverPolicy     = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
  }

  # Farget로 운영 시에는 Delete시 Coredns가 마지막으로 삭제되도록 의존성 추가
  depends_on = [
    module.eks
  ]
}

# Karpenter Controller에 부여할 신뢰관계 정책 
data "aws_iam_policy_document" "karpenter_controller_assume_role_policy" {
  statement {
    effect = "Allow"
    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:sub"
      values   = ["system:serviceaccount:karpenter:karpenter"]
    }
    # https://aws.amazon.com/premiumsupport/knowledge-center/eks-troubleshoot-oidc-and-irsa/?nc1=h_ls
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }

    actions = ["sts:AssumeRoleWithWebIdentity"]
  }
}
# Karpenter를 배포할 네임 스페이스
resource "kubernetes_namespace_v1" "karpenter" {
  metadata {
    name = "karpenter"
  }
}

# Karpenter CRDs
# 분리해서 설치 시 karpenter chart에서 "skip_crds = true" 옵션 사용 필수
resource "helm_release" "karpenter-crd" {
  name       = "karpenter-crd"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter-crd"
  version    = var.karpenter_chart_version
  namespace  = kubernetes_namespace_v1.karpenter.metadata[0].name
}

# Karpenter 메인 차트
resource "helm_release" "karpenter" {
  name       = "karpenter"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = var.karpenter_chart_version
  namespace  = kubernetes_namespace_v1.karpenter.metadata[0].name

  skip_crds = true

  values = [
    <<-EOT
    settings:
      clusterName: ${module.eks.cluster_name}
      clusterEndpoint: ${module.eks.cluster_endpoint}
      interruptionQueue: ${module.karpenter.queue_name}
      featureGates:
        spotToSpotConsolidation: true
    serviceAccount:
      annotations:
        eks.amazonaws.com/role-arn: ${module.karpenter.iam_role_arn}
    controller:
      resources:
        requests:
          cpu: 200m
          memory: 250Mi
    nodeSelector:
      workload: system
      nodegroup: system
    tolerations:
      - key: workload
        operator: Equal
        value: system
        effect: NoSchedule
    EOT
  ]

  depends_on = [
    helm_release.karpenter-crd,
    module.karpenter
  ]
}

# Karpenter 기본 노드 클래스
# - id: ${module.eks.cluster_primary_security_group_id}
resource "kubectl_manifest" "karpenter_default_node_class" {
  yaml_body = <<-YAML
    apiVersion: karpenter.k8s.aws/v1
    kind: EC2NodeClass
    metadata:
      name: default
    spec:
      amiSelectorTerms:
      - alias: "${var.eks_node_ami_alias_bottlerocket}"
      role: ${module.karpenter.node_iam_role_name}
      subnetSelectorTerms:
      - tags:
          karpenter.sh/discovery: ${module.eks.cluster_name}
      securityGroupSelectorTerms:
      - id: ${module.eks.node_security_group_id}
      blockDeviceMappings:
      - deviceName: /dev/xvda
        ebs:
          volumeSize: 20Gi
          volumeType: gp3
          encrypted: true
      metadataOptions:
        httpEndpoint: enabled
        httpTokens: optional
        httpPutResponseHopLimit: 2
      tags:
        ${jsonencode(local.tags)}
    YAML

  depends_on = [
    helm_release.karpenter
  ]
}

# Karpenter 기본 노드 풀
resource "kubectl_manifest" "karpenter_default_nodepool" {
  yaml_body = <<-YAML
    apiVersion: karpenter.sh/v1
    kind: NodePool
    metadata:
      name: default
    spec:
      template:
        spec:
          expireAfter: 720h
          requirements:
          - key: kubernetes.io/arch
            operator: In
            values: ["amd64", "arm64"]
          - key: kubernetes.io/os
            operator: In
            values: ["linux"]
          - key: topology.kubernetes.io/zone
            operator: In
            values: ["ap-northeast-2a", "ap-northeast-2b", "ap-northeast-2c", "ap-northeast-2d"]
          - key: karpenter.sh/capacity-type
            operator: In
            values: ["spot", "on-demand"]
          - key: karpenter.k8s.aws/instance-family
            operator: In
            values: ["t3", "t3a", "t4g", "c5", "c5a", "c6g", "c6i", "c7g", "c7i", "m5", "m5a", "m6g", "m7g"]
          - key: karpenter.k8s.aws/instance-size
            operator: In
            values: ["large","xlarge"]
          nodeClassRef:
            apiVersion: karpenter.k8s.aws/v1
            kind: EC2NodeClass
            name: "default"
            group: karpenter.k8s.aws
      limits:
        cpu: 10
      disruption:
        consolidationPolicy: WhenEmptyOrUnderutilized 
        consolidateAfter: 10s
    YAML

  depends_on = [
    kubectl_manifest.karpenter_default_node_class
  ]
}

# EKS-Addon
# karpenter 포함 컴퓨팅이 전부 준비완료 일때 설치
locals {
  eks_addons = [
    "metrics-server",
    "aws-ebs-csi-driver",
    "eks-pod-identity-agent",
    "aws-secrets-store-csi-driver-provider"
    # "snapshot-controller"
  ]
}
data "aws_eks_addon_version" "this" {
  for_each = toset(local.eks_addons)

  addon_name         = each.key
  kubernetes_version = module.eks.cluster_version
}

resource "aws_eks_addon" "this" {
  for_each = toset(local.eks_addons)

  cluster_name                = module.eks.cluster_name
  addon_name                  = each.key
  addon_version               = data.aws_eks_addon_version.this[each.key].version
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  # Secrets Store CSI Driver Provider에만 syncSecret 및 rotation 설정 추가
  configuration_values = each.key == "aws-secrets-store-csi-driver-provider" ? jsonencode({
    "secrets-store-csi-driver" = {
      syncSecret = {
        enabled = true
      }
      enableSecretRotation = true
    }
  }) : null

  depends_on = [
    kubectl_manifest.karpenter_default_nodepool
  ]

  timeouts {
    create = "5m"
  }
}

# 기본값 gp3 Delete 스토리지 클래스
resource "kubernetes_storage_class_v1" "ebs_sc" {
  metadata {
    name = "gp3"
    annotations = {
      "storageclass.kubernetes.io/is-default-class" : "true"
    }
  }
  storage_provisioner = "ebs.csi.aws.com"
  volume_binding_mode = "WaitForFirstConsumer"
  parameters = {
    type      = "gp3"
    encrypted = "true"
  }
}

# gp3 retain 스토리지 클래스
resource "kubernetes_storage_class_v1" "ebs_sc_retain" {
  metadata {
    name = "gp3-retain"
    annotations = {
      "storageclass.kubernetes.io/is-default-class" = "false"
    }
  }
  storage_provisioner = "ebs.csi.aws.com"
  reclaim_policy      = "Retain"
  volume_binding_mode = "WaitForFirstConsumer"
  parameters = {
    type      = "gp3"
    encrypted = "true"
  }
}

# 기본값으로 생성된 스토리지 클래스 해제
resource "kubernetes_annotations" "default_storageclass" {
  api_version = "storage.k8s.io/v1"
  kind        = "StorageClass"
  force       = "true"
  metadata {
    name = "gp2"
  }
  annotations = {
    "storageclass.kubernetes.io/is-default-class" = "false"
  }
  depends_on = [
    kubernetes_storage_class_v1.ebs_sc
  ]
}

# AWS Load Balancer Controller에 부여할 IAM 역할 및 Pod Identity Association
module "aws_load_balancer_controller_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "2.6.0" # 최신화 2025년 12월 31일

  name = "aws-load-balancer-controller"

  attach_aws_lb_controller_policy = true

  associations = {
    aws_load_balancer_controller = {
      cluster_name    = module.eks.cluster_name
      namespace       = "kube-system"
      service_account = "aws-load-balancer-controller"
      tags = {
        app = "aws-load-balancer-controller"
      }
    }
  }
}

# AWS Load Balancer Controller
resource "helm_release" "aws_load_balancer_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = var.aws_load_balancer_controller_chart_version
  namespace  = "kube-system"

  values = [
    <<-EOT
    clusterName: ${module.eks.cluster_name}
    serviceAccount:
      create: true
      annotations:
        eks.amazonaws.com/role-arn: ${module.aws_load_balancer_controller_pod_identity.iam_role_arn}
    EOT
  ]

  depends_on = [
    kubectl_manifest.karpenter_default_nodepool
  ]
}

# External DNS Pod Identity
module "external_dns_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "2.6.0" # 최신화 2025년 12월 31일

  name = "external-dns"

  attach_external_dns_policy    = true
  external_dns_hosted_zone_arns = ["${data.aws_route53_zone.this.arn}"]

  association_defaults = {
    namespace       = "kube-system"
    service_account = "external-dns-sa"
  }

  associations = {
    external_dns = {
      cluster_name    = module.eks.cluster_name
      namespace       = "kube-system"
      service_account = "external-dns-sa"
      tags = {
        app = "external-dns"
      }
    }
  }

  tags = local.tags
}

# External DNS
resource "helm_release" "external_dns" {
  name       = "external-dns"
  repository = "https://kubernetes-sigs.github.io/external-dns"
  chart      = "external-dns"
  version    = var.external_dns_chart_version
  namespace  = "kube-system"

  # source의 api로 없는걸 넣으면 애초에 Pod가 죽으므로 정말로 쓸것만 명시해야합니다
  values = [
    <<-EOT
    serviceAccount:
      create: true
      name: external-dns-sa
      annotations:
        eks.amazonaws.com/role-arn: ${module.external_dns_pod_identity.iam_role_arn}
    txtOwnerId: ${module.eks.cluster_name}
    policy: sync
    sources:
      - service
      - ingress
    extraArgs:
      - --annotation-filter=external-dns.alpha.kubernetes.io/exclude notin (true)
    env:
      - name: AWS_REGION
        value: ${data.aws_region.current.id}
    EOT
  ]

  depends_on = [
    kubectl_manifest.karpenter_default_nodepool
  ]
}