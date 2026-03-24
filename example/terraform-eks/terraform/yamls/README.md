# 워크로드 + 업그레이드 위험 시나리오

EKS 업그레이드 검증용 워크로드와 drain/cordon 중 문제가 되는 패턴을 재현하는 샘플.
모든 리소스는 `workload` 네임스페이스에 배포된다.

## 배포

```bash
kubectl apply -f yamls/
```

## 파일 목록

### 워크로드

| 파일 | 용도 |
|------|------|
| `workload-valkey.yaml` | Valkey StatefulSet + PVC — drain 후 PV 재연결/데이터 유지 검증 |
| `workload-traffic-generator.yaml` | Valkey PING 1초 간격 — 업그레이드 중 downtime 측정 |

### 위험 시나리오

| 파일 | 규칙 | 심각도 | 문제 |
|------|------|--------|------|
| `scenario-pdb-blocking.yaml` | WLS-001 | CRITICAL | `maxUnavailable=0` PDB — drain 영구 차단 |
| `scenario-single-replica.yaml` | WLS-002 | HIGH | PDB 없는 단일 레플리카 — drain 시 서비스 중단 |
| `scenario-pv-zone-affinity.yaml` | WLS-003 | CRITICAL | EBS PV AZ 고정 StatefulSet — 재스케줄 불가 |
| `scenario-local-storage.yaml` | WLS-004 | MEDIUM | emptyDir/hostPath — drain 시 데이터 유실 |
| `scenario-long-running-job.yaml` | WLS-005 | MEDIUM | 장시간 Job/CronJob — drain 시 강제 종료 |
| `scenario-topology-spread.yaml` | WLS-006 | HIGH | `DoNotSchedule` TSC — 노드 부족 시 Pending 고착 |
| `scenario-resource-pressure.yaml` | CAP-002 | MEDIUM | request 작음 + 실제 사용량 높음 — drain 시 노드 과부하 |

## 정리

```bash
kubectl delete namespace workload
kubectl delete storageclasses ebs-single-az
```
