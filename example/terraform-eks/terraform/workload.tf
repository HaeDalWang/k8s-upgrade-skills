# 업그레이드 검증용 워크로드
# 1) Stateful 워크로드 (Valkey + PVC)
# 2) 트래픽 생성기 (업그레이드 중 downtime 측정)
# 3) Deprecated API 리소스 (버전 호환성 검증)

# ─────────────────────────────────────────────
# 네임스페이스
# ─────────────────────────────────────────────
resource "kubernetes_namespace_v1" "upgrade_test" {
  metadata {
    name = "upgrade-test"
  }
}

# ─────────────────────────────────────────────
# 1. Stateful 워크로드 — Valkey (Redis-compatible) + PVC
#    drain 후 PV 재연결 + 데이터 유지 검증용
# ─────────────────────────────────────────────
resource "kubectl_manifest" "valkey_statefulset" {
  yaml_body = <<-YAML
    apiVersion: apps/v1
    kind: StatefulSet
    metadata:
      name: valkey
      namespace: ${kubernetes_namespace_v1.upgrade_test.metadata[0].name}
      labels:
        app: valkey
        purpose: upgrade-validation
    spec:
      replicas: 1
      serviceName: valkey
      selector:
        matchLabels:
          app: valkey
      template:
        metadata:
          labels:
            app: valkey
        spec:
          containers:
            - name: valkey
              image: valkey/valkey:8-alpine
              ports:
                - containerPort: 6379
              args: ["--appendonly", "yes"]
              volumeMounts:
                - name: data
                  mountPath: /data
              resources:
                requests:
                  cpu: 50m
                  memory: 64Mi
                limits:
                  cpu: 200m
                  memory: 128Mi
              readinessProbe:
                exec:
                  command: ["valkey-cli", "ping"]
                initialDelaySeconds: 5
                periodSeconds: 5
      volumeClaimTemplates:
        - metadata:
            name: data
          spec:
            accessModes: ["ReadWriteOnce"]
            storageClassName: gp3
            resources:
              requests:
                storage: 1Gi
  YAML

  depends_on = [
    kubernetes_storage_class_v1.ebs_sc,
    kubectl_manifest.karpenter_default_nodepool
  ]
}

resource "kubectl_manifest" "valkey_service" {
  yaml_body = <<-YAML
    apiVersion: v1
    kind: Service
    metadata:
      name: valkey
      namespace: ${kubernetes_namespace_v1.upgrade_test.metadata[0].name}
    spec:
      clusterIP: None
      selector:
        app: valkey
      ports:
        - port: 6379
          targetPort: 6379
  YAML

  depends_on = [kubectl_manifest.valkey_statefulset]
}


# ─────────────────────────────────────────────
# 2. 트래픽 생성기 — 업그레이드 중 downtime 측정
#    Valkey에 1초 간격으로 PING → 응답 실패 시 타임스탬프 기록
#    업그레이드 후 로그 확인: kubectl logs -n upgrade-test deploy/traffic-generator
# ─────────────────────────────────────────────
resource "kubectl_manifest" "traffic_generator" {
  yaml_body = <<-YAML
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: traffic-generator
      namespace: ${kubernetes_namespace_v1.upgrade_test.metadata[0].name}
      labels:
        app: traffic-generator
        purpose: downtime-measurement
    spec:
      replicas: 1
      selector:
        matchLabels:
          app: traffic-generator
      template:
        metadata:
          labels:
            app: traffic-generator
        spec:
          containers:
            - name: probe
              image: busybox:stable
              command:
                - sh
                - -c
                - |
                  echo "=== 트래픽 생성기 시작: $(date -u +%FT%TZ) ==="
                  SEQ=0
                  FAIL=0
                  while true; do
                    SEQ=$((SEQ+1))
                    TS=$(date -u +%FT%TZ)
                    # Valkey PING 체크 (TCP 6379)
                    if echo PING | nc -w 2 valkey.upgrade-test.svc.cluster.local 6379 | grep -q PONG; then
                      echo "$TS seq=$SEQ status=OK"
                    else
                      FAIL=$((FAIL+1))
                      echo "$TS seq=$SEQ status=FAIL (total_failures=$FAIL)"
                    fi
                    sleep 1
                  done
              resources:
                requests:
                  cpu: 10m
                  memory: 16Mi
                limits:
                  cpu: 50m
                  memory: 32Mi
  YAML

  depends_on = [kubectl_manifest.valkey_service]
}

# ─────────────────────────────────────────────
# 3. Deprecated API 리소스 — 버전 호환성 규칙(COM-002) 검증
#    policy/v1beta1 PDB — K8s 1.25+에서 제거됨
#    업그레이드 전 Agent가 deprecated API 사용을 탐지해야 함
# ─────────────────────────────────────────────

# 3-a. Deprecated PDB 대상 Deployment
resource "kubectl_manifest" "deprecated_api_app" {
  yaml_body = <<-YAML
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: deprecated-api-app
      namespace: ${kubernetes_namespace_v1.upgrade_test.metadata[0].name}
      labels:
        app: deprecated-api-app
        purpose: deprecated-api-test
    spec:
      replicas: 2
      selector:
        matchLabels:
          app: deprecated-api-app
      template:
        metadata:
          labels:
            app: deprecated-api-app
        spec:
          containers:
            - name: app
              image: nginx:stable-alpine
              resources:
                requests:
                  cpu: 10m
                  memory: 16Mi
  YAML

  depends_on = [kubectl_manifest.karpenter_default_nodepool]
}

# 3-b. Deprecated API — policy/v1beta1 PDB
# 주의: K8s 1.25+에서는 이 API가 제거되어 apply 자체가 실패함.
#       1.24 이하 클러스터에서만 배포 가능. 1.25+ 환경에서는 주석 처리 필요.
# resource "kubectl_manifest" "deprecated_pdb" {
#   yaml_body = <<-YAML
#     apiVersion: policy/v1beta1
#     kind: PodDisruptionBudget
#     metadata:
#       name: deprecated-pdb
#       namespace: ${kubernetes_namespace_v1.upgrade_test.metadata[0].name}
#       labels:
#         purpose: deprecated-api-test
#       annotations:
#         notice: "policy/v1beta1은 K8s 1.21에서 deprecated, 1.25에서 제거됨. policy/v1 사용 권장."
#     spec:
#       minAvailable: 1
#       selector:
#         matchLabels:
#           app: deprecated-api-app
#   YAML

#   depends_on = [kubectl_manifest.deprecated_api_app]
# }
