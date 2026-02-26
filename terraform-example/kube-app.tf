# Argo CD를 설치할 네임스페이스
resource "kubernetes_namespace_v1" "argocd" {
  metadata {
    name = "argocd"
  }
}
# 테스트 환경 전용: admin 비밀번호 고정 (운영에서는 Secrets Manager 등 사용)
resource "htpasswd_password" "argocd" {
  password = "Test1234!"
}
# Argo CD
resource "helm_release" "argocd" {
  name       = "argocd"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  version    = var.argocd_chart_version
  namespace  = kubernetes_namespace_v1.argocd.metadata[0].name

  values = [
    templatefile("${path.module}/helm-values/argocd.yaml", {
      domain                = "argocd.${local.project_domain_name}"
      server_admin_password = htpasswd_password.argocd.bcrypt,
      lb_acm_certificate_arn = join(",", [
        aws_acm_certificate_validation.project.certificate_arn,
      ]),
      lb_group_name = local.project
    })
  ]

  depends_on = [
    helm_release.aws_load_balancer_controller,
    helm_release.ingress_nginx
  ]
}


# KEDA를 설치할 네임스페이스
resource "kubernetes_namespace_v1" "keda" {
  metadata {
    name = "keda"
  }
}

# KEDA
resource "helm_release" "keda" {
  name       = "keda"
  repository = "https://kedacore.github.io/charts"
  chart      = "keda"
  version    = var.keda_chart_version
  namespace  = kubernetes_namespace_v1.keda.metadata[0].name

  depends_on = [
    helm_release.karpenter
  ]
}