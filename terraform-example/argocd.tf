# Argo CD에 프로젝트 생성 (kubectl provider: apply 시점에 CRD 이미 있음, depends_on으로 Helm 선행)
resource "kubectl_manifest" "argocd_project" {
  yaml_body = <<-YAML
    apiVersion: argoproj.io/v1alpha1
    kind: AppProject
    metadata:
      name: ${local.project}
      namespace: ${kubernetes_namespace_v1.argocd.metadata[0].name}
      finalizers:
        - resources-finalizer.argocd.argoproj.io
    spec:
      description: "${local.project} 환경"
      sourceRepos:
        - "*"
      destinations:
        - name: "*"
          server: "*"
          namespace: "*"
      clusterResourceWhitelist:
        - group: "*"
          kind: "*"
  YAML

  depends_on = [helm_release.argocd]
}

# -----------------------------------------------------------------------------
# upgrade-test-app 차트 배포 (HaeDalWang/k8s-upgrade-skills/charts/upgrade-test-app)
# 변수만 바꿔서 기본 / PDB / PV 시나리오 3개 Application, 오토싱크
# -----------------------------------------------------------------------------
locals {
  upgrade_test_app_repo = "https://github.com/HaeDalWang/k8s-upgrade-skills"
  upgrade_test_app_path = "charts/upgrade-test-app"
  upgrade_test_namespace = "workload"
}

resource "kubectl_manifest" "argocd_app_upgrade_test_default" {
  yaml_body = <<-YAML
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: upgrade-test-app-default
      namespace: ${kubernetes_namespace_v1.argocd.metadata[0].name}
      finalizers:
        - resources-finalizer.argocd.argoproj.io
    spec:
      project: ${local.project}
      source:
        repoURL: ${local.upgrade_test_app_repo}
        targetRevision: HEAD
        path: ${local.upgrade_test_app_path}
        helm:
          valueFiles:
            - values.yaml
      destination:
        server: https://kubernetes.default.svc
        namespace: ${local.upgrade_test_namespace}
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
  YAML
  depends_on = [kubectl_manifest.argocd_project]
}

resource "kubectl_manifest" "argocd_app_upgrade_test_pdb" {
  yaml_body = <<-YAML
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: upgrade-test-app-pdb
      namespace: ${kubernetes_namespace_v1.argocd.metadata[0].name}
      finalizers:
        - resources-finalizer.argocd.argoproj.io
    spec:
      project: ${local.project}
      source:
        repoURL: ${local.upgrade_test_app_repo}
        targetRevision: HEAD
        path: ${local.upgrade_test_app_path}
        helm:
          valueFiles:
            - values.yaml
            - values_pdb.yaml
      destination:
        server: https://kubernetes.default.svc
        namespace: ${local.upgrade_test_namespace}
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
  YAML
  depends_on = [kubectl_manifest.argocd_project]
}

resource "kubectl_manifest" "argocd_app_upgrade_test_pv" {
  yaml_body = <<-YAML
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: upgrade-test-app-pv
      namespace: ${kubernetes_namespace_v1.argocd.metadata[0].name}
      finalizers:
        - resources-finalizer.argocd.argoproj.io
    spec:
      project: ${local.project}
      source:
        repoURL: ${local.upgrade_test_app_repo}
        targetRevision: HEAD
        path: ${local.upgrade_test_app_path}
        helm:
          valueFiles:
            - values.yaml
            - values_pv.yaml
      destination:
        server: https://kubernetes.default.svc
        namespace: ${local.upgrade_test_namespace}
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
  YAML
  depends_on = [kubectl_manifest.argocd_project]
}

# # Argo CD 애플리케이션 생성 (ingress-controller-test.git)
# resource "kubernetes_manifest" "argocd_app_ingress_nginx" {
#   manifest = {
#     apiVersion = "argoproj.io/v1alpha1"
#     kind       = "Application"

#     metadata = {
#       name      = "ezl-app-server"
#       namespace = kubernetes_namespace_v1.argocd.metadata[0].name
#       finalizers = [
#         "resources-finalizer.argocd.argoproj.io"
#       ]
#     }

#     spec = {
#       project = kubernetes_manifest.argocd_project.manifest.metadata.name

#       sources = [
#         {
#           repoURL        = "https://github.com/HaeDalWang/seungdo-helm-chart.git"
#           targetRevision = "HEAD"
#           path           = "ezl-app-server"
#           helm = {
#             releaseName = "app-server"
#             valueFiles = [
#               "values_dev.yaml"
#             ]
#           }
#         }
#       ]

#       destination = {
#         name      = "in-cluster"
#         namespace = "intgapp"
#       }

#       syncPolicy = {
#         syncOptions : ["CreateNamespace=true"]
#         automated : {}
#       }
#     }
#   }

#   depends_on = [
#     helm_release.argocd,
#     kubernetes_manifest.argocd_project
#   ]
# }