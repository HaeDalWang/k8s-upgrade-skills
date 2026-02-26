
# OpenSearch 네임스페이스
resource "kubernetes_namespace" "opensearch" {
  metadata {
    name = "logging"
  }
}

# OpenSearch
resource "helm_release" "opensearch" {
  name       = "opensearch"
  repository = "https://opensearch-project.github.io/helm-charts/"
  chart      = "opensearch"
  version    = var.opensearch_chart_version
  namespace  = kubernetes_namespace.opensearch.metadata[0].name

  values = [
    templatefile("${path.module}/helm-values/opensearch.yaml", {
      # 초기 비밀번호 첫 로그인 시 변경 후 사용
      initial_admin_password = "Test1234!"
    })
  ]

  replace      = true
  force_update = true

  depends_on = [
    kubectl_manifest.karpenter_default_nodepool,
    helm_release.ingress_nginx
  ]
}

# OpenSearch Dashboards
resource "helm_release" "opensearch_dashboards" {
  name       = "opensearch-dashboards"
  repository = "https://opensearch-project.github.io/helm-charts/"
  chart      = "opensearch-dashboards"
  version    = var.opensearch_chart_version
  namespace  = kubernetes_namespace.opensearch.metadata[0].name

  replace = true

  values = [
    templatefile("${path.module}/helm-values/opensearch_dashboards.yaml", {
      domain_name = "es.${local.project_domain_name}"
    })
  ]

  depends_on = [
    helm_release.opensearch
  ]
}