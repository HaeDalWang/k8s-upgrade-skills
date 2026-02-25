# 테라폼 백엔드 설정
terraform {
  backend "s3" {
    region         = "ap-northeast-2"
    bucket         = "seungdobae-terraform-state"
    key            = "upgrade-test/terraform.tfstate"
    dynamodb_table = "seungdobae-terraform-lock"
    encrypt        = true
  }
}

# 요구되는 테라폼 제공자 목록
# 버전 기준: 2025년 12월 31일
terraform {
  required_version = ">= 1.13.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.26.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.0.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.1.1"
    }
    kubectl = {
      source  = "alekc/kubectl"
      version = "~> 2.1.3"
    }
    htpasswd = {
      source  = "loafoe/htpasswd"
      version = "~> 1.5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

# AWS 제공자 설정
provider "aws" {
  # 해당 테라폼 모듈을 통해서 생성되는 모든 AWS 리소스에 아래의 태그 부여
  default_tags {
    tags = local.tags
  }
}

# provider "aws" {
#   alias  = "us_east_1"
#   region = "us-east-1"
#   default_tags {
#     tags = local.tags
#   }
# }

# Kubernetes 제공자 설정
provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.this.token
}

# Helm 제공자 설정
provider "helm" {
  kubernetes = {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name]
      command     = "aws"
    }
  }
  debug = true
}

# Kubectl 제공자 설정
provider "kubectl" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.this.token
  load_config_file       = false
}