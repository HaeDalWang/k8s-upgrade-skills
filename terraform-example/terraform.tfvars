# =============================================================================
# 업그레이드 테스팅 환경 - Terraform 변수
# =============================================================================

# 네트워크
vpc_cidr    = "10.222.0.0/16"
domain_name = "seungdobae.com" # 실제 사용 도메인으로 변경

# EKS
eks_cluster_version = "1.33"

# EKS 노드 AMI 별칭 (클러스터 버전에 맞게 갱신 필요)
eks_node_ami_alias_al2023       = "al2023@v20260224"
eks_node_ami_alias_bottlerocket = "bottlerocket@1.55.0"

# Helm 차트 버전 (현재 클러스터 배포 버전과 동일하게 유지)
# Chart 버전 최신화: 2026년 2월 26일
karpenter_chart_version                    = "1.8.3"
aws_load_balancer_controller_chart_version = "1.17.0"
external_dns_chart_version                 = "1.19.0"
ingress_nginx_chart_version                = "4.13.3"
argocd_chart_version                       = "9.2.3"
keda_chart_version                         = "2.18.0"

pg-operator_chart_version    = "2.8.2"
psmdb-operator_chart_version = "1.21.3"

opensearch_chart_version      = "3.5.0"
fluentbit_chart_version       = "0.55.0"
milvus_operator_chart_version = "1.3.0"

valkey_chart_version = "0.9.3"