---
environment: aws
platform: eks
iac: terraform
cluster_name: upgrade-skill
current_version: "1.34"
target_version: "1.35"
output_language: ko
services:
  - name: my-api
    namespace: production
    min_endpoints: 2
    health_check_url: "https://api.example.com/health"
  - name: my-worker
    namespace: production
    min_endpoints: 1
---

## 업그레이드 컨텍스트

여기에 LLM이 알기 어려운 현재 상황과 제약을 자유롭게 서술하세요.
포맷 제약 없음 — 마크다운, 불릿, 자유 문장 모두 가능합니다.

### 현재 상황
- 특이사항 없음

### 제약 및 요구사항
- zero downtime 필수 — 서비스 중단 허용 불가

### 기타
- (없음)
