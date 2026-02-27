# -----------------------------------------------------------------------------
# MSA Demo 전용 미들웨어: Valkey (Redis-compatible) pub/sub 이벤트 브로커
# 서비스명: valkey-production.middleware.svc.cluster.local:6379
# -----------------------------------------------------------------------------

resource "kubernetes_namespace_v1" "middleware" {
  metadata {
    name = "middleware"
  }
}

# Valkey 공식 헬름 레포지토리 등록 및 배포
resource "helm_release" "valkey" {
  name       = "valkey-production"
  repository = "https://valkey.io/valkey-helm/"
  chart      = "valkey"
  version    = var.valkey_chart_version

  namespace = kubernetes_namespace_v1.middleware.metadata[0].name

  # https://github.com/valkey-io/valkey-helm/blob/valkey-0.9.3/valkey/values.yaml
  values = [
    <<-EOF
    replica:
      enabled: true
      replicas: 3
      replicationUser: "default"
      persistence:
        size: 10Gi
        storageClass: "gp3"
    auth:
      enabled: true
      aclUsers:
        default:
          permissions: "~* &* +@all"
          password: "Test1234!"
    metrics:
      enabled: false
    EOF
  ]
}