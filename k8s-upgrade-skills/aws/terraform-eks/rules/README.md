# EKS 업그레이드 사전 검증 규칙 (Pre-upgrade Validation Rules)

AIDLC 방법론에서 영감을 받아 설계된 체계적인 사전 검증 규칙 시스템.
각 규칙은 독립적인 마크다운 파일로 정의되며, AI Agent가 Phase 0에서 순차적으로 실행한다.

## 구조

```
rules/
├── README.md                          # 이 파일 — 규칙 시스템 개요
├── rule-index.md                      # 전체 규칙 색인 + 실행 순서
├── common/                            # 공통 규칙 (모든 업그레이드에 적용)
│   ├── cluster-health.md              # 클러스터 기본 상태 검증
│   ├── version-compatibility.md       # 버전 호환성 검증
│   └── addon-readiness.md             # Add-on 호환성 사전 검증
├── workload-safety/                   # 워크로드 안전성 (drain/cordon 영향 분석)
│   ├── pdb-audit.md                   # PDB 차단 가능성 분석
│   ├── single-replica-risk.md         # 단일 레플리카 서비스 중단 위험
│   ├── pv-zone-affinity.md            # PV 존 어피니티 재스케줄 불가 위험
│   ├── local-storage-pods.md          # emptyDir/hostPath 데이터 유실 위험
│   ├── long-running-jobs.md           # 장시간 Job/CronJob 중단 위험
│   └── topology-constraints.md        # TopologySpread/Affinity 위반 위험
├── capacity/                          # 용량 및 리소스 검증
│   ├── node-capacity-headroom.md      # 노드 용량 여유분 검증
│   ├── pod-resource-pressure.md       # 리소스 압박 상태 Pod 검증
│   └── surge-capacity.md              # Rolling Update surge 용량 검증
└── infrastructure/                    # 인프라 수준 검증
    ├── terraform-state-drift.md       # Terraform 상태 드리프트 검증
    ├── ami-availability.md            # 대상 버전 AMI 가용성 검증
    └── karpenter-compatibility.md     # Karpenter 호환성 검증
```

## 규칙 파일 형식

모든 규칙 파일은 다음 구조를 따른다:

```markdown
---
id: RULE-CATEGORY-NNN
name: 규칙 이름 (한국어)
severity: CRITICAL | HIGH | MEDIUM | LOW
category: common | workload-safety | capacity | infrastructure
phase: pre-flight (Phase 0에서 실행)
applies_when: 항상 | 조건부 (조건 설명)
---

# 규칙 이름

## 목적
왜 이 검증이 필요한지 설명

## 위험 시나리오
drain/cordon 시 어떤 문제가 발생하는지 구체적으로 설명

## 검증 명령어
kubectl/aws cli 명령어와 MCP fallback

## Gate 조건
통과/경고/차단 기준

## 조치 방안
문제 발견 시 해결 방법
```

## 심각도 정의

| 심각도 | 의미 | 처리 |
|--------|------|------|
| CRITICAL | drain 시 서비스 중단 또는 데이터 유실 확정 | 즉시 STOP, 사용자 해결 필수 |
| HIGH | drain 시 서비스 중단 가능성 높음 | STOP, 사용자 확인 후 진행 |
| MEDIUM | 잠재적 문제, 대부분 자동 복구 가능 | WARNING 보고, 사용자 확인 후 진행 |
| LOW | 참고 사항, 업그레이드 차단하지 않음 | INFO 보고, 자동 진행 |

## 실행 원칙

1. 모든 규칙은 Phase 0에서 실행된다
2. CRITICAL 규칙이 하나라도 실패하면 업그레이드를 시작하지 않는다
3. HIGH 규칙 실패 시 사용자에게 보고하고 진행 여부를 확인받는다
4. 규칙 실행 결과는 테이블 형태로 요약하여 사용자에게 보고한다
5. 각 규칙은 독립적으로 실행 가능하며, 다른 규칙의 결과에 의존하지 않는다
