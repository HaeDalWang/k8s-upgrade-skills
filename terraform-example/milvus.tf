# -----------------------------------------------------------------------------
# Milvus 전용 Karpenter NodePool
# 노드에는 자동으로 karpenter.sh/nodepool: milvus 레이블 부여 → 워크로드에서 해당 레이블로 스케줄
# -----------------------------------------------------------------------------
resource "kubectl_manifest" "karpenter_milvus_node_class" {
  yaml_body = <<-YAML
    apiVersion: karpenter.k8s.aws/v1
    kind: EC2NodeClass
    metadata:
      name: milvus
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
          volumeSize: 50Gi
          volumeType: gp3
          encrypted: true
      metadataOptions:
        httpEndpoint: enabled
        httpTokens: optional
        httpPutResponseHopLimit: 2
      tags:
        ${jsonencode(merge(local.tags, { "workload" = "milvus" }))}
  YAML

  depends_on = [helm_release.karpenter]
}

resource "kubectl_manifest" "karpenter_milvus_nodepool" {
  yaml_body = <<-YAML
    apiVersion: karpenter.sh/v1
    kind: NodePool
    metadata:
      name: milvus
    spec:
      template:
        spec:
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
            values: ["m5", "m5a", "m6g", "m6i", "m7g", "m7i", "r5", "r5a", "r6g", "r6i"]
          - key: karpenter.k8s.aws/instance-size
            operator: In
            values: ["large", "xlarge", "2xlarge"]
          nodeClassRef:
            apiVersion: karpenter.k8s.aws/v1
            kind: EC2NodeClass
            name: milvus
            group: karpenter.k8s.aws
      limits:
        cpu: 16
      disruption:
        consolidationPolicy: WhenEmptyOrUnderutilized
        consolidateAfter: 5m
  YAML

  depends_on = [kubectl_manifest.karpenter_milvus_node_class]
}

# -----------------------------------------------------------------------------
# Milvus Operator (Helm)
# https://github.com/zilliztech/milvus-operator
# -----------------------------------------------------------------------------
resource "kubernetes_namespace_v1" "milvus_operator" {
  metadata {
    name = "milvus-operator"
  }
}
# Milvus Operator Helm Release 배포
resource "helm_release" "milvus_operator" {
  name             = "milvus-operator"
  repository       = "https://zilliztech.github.io/milvus-operator/"
  chart            = "milvus-operator"
  version          = "${var.milvus_operator_chart_version}"
  namespace        = kubernetes_namespace_v1.milvus_operator.metadata[0].name

  # helm install의 --wait 및 --wait-for-jobs 플래그와 동일한 역할
  wait          = true
  wait_for_jobs = true
}

# Milvus CR 배포용
resource "kubectl_manifest" "milvus" {
  yaml_body = file("${path.module}/yamls/milvuscluster.yaml")
  depends_on = [
    helm_release.milvus_operator
  ]
}