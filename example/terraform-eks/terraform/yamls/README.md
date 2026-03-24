# 시나리오 목록

| 파일 | 규칙 | 심각도 | 문제 |
|------|------|--------|------|
| `scenario-pdb-blocking.yaml` | WLS-001 | CRITICAL | `maxUnavailable=0` PDB — drain 영구 차단 |
| `scenario-single-replica.yaml` | WLS-002 | HIGH | PDB 없는 단일 레플리카 — drain 시 서비스 중단 |
| `scenario-pv-zone-affinity.yaml` | WLS-003 | CRITICAL | EBS PV AZ 고정 StatefulSet — 재스케줄 불가 |
| `scenario-local-storage.yaml` | WLS-004 | MEDIUM | emptyDir/hostPath — drain 시 데이터 유실 |
| `scenario-long-running-job.yaml` | WLS-005 | MEDIUM | 장시간 Job/CronJob — drain 시 강제 종료 |
| `scenario-topology-spread.yaml` | WLS-006 | HIGH | `DoNotSchedule` TSC — 노드 부족 시 Pending 고착 |