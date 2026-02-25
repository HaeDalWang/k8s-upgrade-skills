# # Ingress NGINX를 설치할 네임스페이스
# resource "kubernetes_namespace_v1" "ingress_nginx" {
#   metadata {
#     name = "ingress-nginx"
#   }
# }

# # Ingress NGINX
# resource "helm_release" "ingress_nginx" {
#   name       = "ingress-nginx"
#   repository = "https://kubernetes.github.io/ingress-nginx"
#   chart      = "ingress-nginx"
#   version    = var.ingress_nginx_chart_version
#   namespace  = kubernetes_namespace_v1.ingress_nginx.metadata[0].name

#   values = [
#     templatefile("${path.module}/helm-values/ingress-nginx.yaml", {
#       lb_acm_certificate_arn = join(",", [
#         data.aws_acm_certificate.existing.arn,
#         aws_acm_certificate_validation.project.certificate_arn,
#       ])
#     })
#   ]

#   depends_on = [
#     helm_release.karpenter
#   ]
# }