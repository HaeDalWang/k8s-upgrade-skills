# 네트워크
vpc_cidr    = "10.222.0.0/16"

# EKS
eks_cluster_version = "1.33"

eks_node_ami_alias_bottlerocket = "bottlerocket@1.55.0"

# Chart 버전 최신화: 2026년 2월 26일
karpenter_chart_version                    = "1.8.3"
aws_load_balancer_controller_chart_version = "1.17.0"
argocd_chart_version                       = "9.2.3"
keda_chart_version                         = "2.18.0"
