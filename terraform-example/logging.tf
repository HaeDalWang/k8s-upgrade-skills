
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
resource "helm_release" "fluent_bit" {
  name       = "fluent-bit"
  repository = "https://fluent.github.io/helm-charts"
  chart      = "fluent-bit"
  version    = var.fluentbit_chart_version
  namespace  = kubernetes_namespace.opensearch.metadata[0].name

  values = [
    templatefile("${path.module}/helm-values/fluent-bit.yaml", {
      es_host       = "opensearch-cluster-master"
      es_port       = "9200"
      es_user       = "admin"
      es_password   = "Test1234!" # OpenSearch initial_admin_password와 동일. 프로덕션은 Secret 사용 권장
      es_tls        = "On"
      app_namespace = "workload"
      index_prefix  = "workload-app"
    })
  ]

  depends_on = [helm_release.opensearch]
}