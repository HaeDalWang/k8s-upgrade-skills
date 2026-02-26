# -----------------------------------------------------------------------------
# DB 전용 Karpenter NodePool (PostgreSQL / PSMDB 배포용)
# 노드에는 자동으로 karpenter.sh/nodepool: database 레이블 부여됨 → yamls에서 해당 레이블로 스케줄
# -----------------------------------------------------------------------------
resource "kubectl_manifest" "karpenter_database_node_class" {
  yaml_body = <<-YAML
    apiVersion: karpenter.k8s.aws/v1
    kind: EC2NodeClass
    metadata:
      name: database
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
          volumeSize: 30Gi
          volumeType: gp3
          encrypted: true
      metadataOptions:
        httpEndpoint: enabled
        httpTokens: optional
        httpPutResponseHopLimit: 2
      tags:
        ${jsonencode(merge(local.tags, { "workload" = "database" }))}
  YAML

  depends_on = [helm_release.karpenter]
}

resource "kubectl_manifest" "karpenter_database_nodepool" {
  yaml_body = <<-YAML
    apiVersion: karpenter.sh/v1
    kind: NodePool
    metadata:
      name: database
    spec:
      template:
        spec:
          # 테인트 없음: karpenter.sh/nodepool=database 레이블만으로 스케줄링 (toleration 누락/충돌 방지)
          requirements:
          - key: kubernetes.io/arch
            operator: In
            values: ["amd64"]
          - key: kubernetes.io/os
            operator: In
            values: ["linux"]
          - key: topology.kubernetes.io/zone
            operator: In
            values: ["ap-northeast-2a", "ap-northeast-2b", "ap-northeast-2c", "ap-northeast-2d"]
          - key: karpenter.sh/capacity-type
            operator: In
            values: ["spot"]
          - key: karpenter.k8s.aws/instance-family
            operator: In
            values: ["t3", "t3a", "t4g", "c5", "c5a", "c6g", "c6i", "c7g", "c7i", "m5", "m5a", "m6g", "m7g"]
          - key: karpenter.k8s.aws/instance-size
            operator: In
            values: ["large", "xlarge"]
          nodeClassRef:
            apiVersion: karpenter.k8s.aws/v1
            kind: EC2NodeClass
            name: database
            group: karpenter.k8s.aws
      limits:
        cpu: 8
      disruption:
        consolidationPolicy: WhenEmptyOrUnderutilized
        consolidateAfter: 60s
  YAML

  depends_on = [kubectl_manifest.karpenter_database_node_class]
}

########################################################
# Percona Server for MongoDB
########################################################

# Mongodb namespace
resource "kubernetes_namespace_v1" "psmdb_operator" {
  metadata {
    name = "mongodb"
  }
}

# Percona Server for MongoDB Operator Helm Chart
resource "helm_release" "psmdb_operator" {
  name = "psmdb-operator"
  repository = "https://percona.github.io/percona-helm-charts/"
  chart = "psmdb-operator"
  namespace = kubernetes_namespace_v1.psmdb_operator.metadata[0].name
  version = var.psmdb-operator_chart_version
}

# MongoDB Secret은 Operator가 자동으로 생성하므로 Terraform으로 관리하지 않음
# 비밀번호 Secret 확인 방법:
# kubectl get secret -n mongodb mongodb-cluster-secrets -o jsonpath='{.data.MONGODB_CLUSTER_ADMIN_PASSWORD}' | base64 -d

# PerconaServerMongoDB CR을 생성하여 Operator가 관리할 수 있도록 합니다
# docs: https://docs.percona.com/percona-operator-for-mongodb/operator.html
# spec: https://github.com/percona/percona-server-mongodb-operator/blob/main/deploy/cr.yaml
resource "kubectl_manifest" "psmdb" {
  yaml_body = file("${path.module}/yamls/psmdb.yaml")
  depends_on = [
    helm_release.psmdb_operator
  ]
}

# # PerconaServerMongoDB CR 싱글 노드 배포용
# # spec: https://github.com/percona/percona-server-mongodb-operator/blob/main/deploy/cr.yaml
# resource "kubectl_manifest" "psmdb" {
#   yaml_body = file("${path.module}/yamls/psmdb-single.yaml")
#   depends_on = [
#     helm_release.psmdb_operator
#   ]
# }

# ########################################################
# # Percona Server for PostgreSQL
# ########################################################

# PostgreSQL namespace
resource "kubernetes_namespace_v1" "pg-operator" {
  metadata {
    name = "postgresql"
  }
}

# Percona Server for PostgreSQL Operator Helm Chart
resource "helm_release" "pg-operator" {
  name = "pg-operator"
  repository = "https://percona.github.io/percona-helm-charts/"
  chart = "pg-operator"
  namespace = kubernetes_namespace_v1.pg-operator.metadata[0].name
  version = var.pg-operator_chart_version
}

# Percona PostgreSQL CR 싱글 노드 배포용
# spec: https://github.com/percona/percona-postgresql-operator/blob/main/deploy/cr.yaml
resource "kubectl_manifest" "pgsql-single" {
  yaml_body = file("${path.module}/yamls/pgsql-single.yaml")
  depends_on = [
    helm_release.pg-operator
  ]
}