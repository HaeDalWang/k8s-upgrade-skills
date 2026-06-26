# Registry 스키마 — helm-k8s-compat

이 디렉토리의 각 `*.json` 파일은 De-facto 표준 Helm 차트 **하나**의 호환성 지식을 담는다.
EKS Insights·kubent가 못 잡는 **차트 레벨 함정**을 큐레이션한 것이다.

> 설계 근거: 실제 차트 5개(ingress-nginx / cert-manager / cluster-autoscaler /
> aws-load-balancer-controller / kube-prometheus-stack)를 공식 문서로 조회한 결과,
> 단일 호환성 모델로는 표현 불가능함이 확인되었다. 아래 **3개 직교축**으로 분해한다.

---

## 왜 `kubeVersion`만으로 부족한가 (실측)

| 차트 | `helm show chart`의 kubeVersion | 실제 |
|------|--------------------------------|------|
| ingress-nginx | `>=1.21.0-0` | 실제론 chart별 **상한선 있는 윈도우** (4.13.x → 최대 1.33) |
| cert-manager | `>= 1.22.0-0` | 실제론 **K8s→차트** 역방향 매트릭스 + release별 날짜 EOL |
| aws-load-balancer-controller | **필드 없음** | 머신리더블 매핑 자체가 없음 |

`kubeVersion`은 하한선만 박는 경우가 대부분이라 **점진적 업그레이드(1.33→1.34)에선 거의 항상 PASS**가 나온다.
따라서 보조 신호로만 쓰고, 본체는 아래 큐레이션 데이터다.

---

## 최상위 필드

```jsonc
{
  "chart_name": "ingress-nginx",        // helm ls의 chart 이름과 매칭 (필수)
  "repo": "https://...",                // 참고용 repo URL
  "compat_source": "https://...",       // LLM이 라이브 확인용으로 fetch할 공식 호환성 문서 (필수)
  "chart_to_app": "same",               // "same" | {매핑표}  (아래 참조)

  "support": { ... },                   // 1축: 대상 K8s를 지원하나?
  "lifecycle": { ... },                 // 2축: 아직 살아있나?
  "upgrade_hazards": [ ... ],           // 3축: 차트 올릴 때 수동으로 뭐가 무나?
  "k8s_breaks": { ... }                 // K8s 점프 사건 (점프 구간에 걸릴 때만 발화)
}
```

### `chart_to_app`
helm은 **chart 버전**(예: cluster-autoscaler 9.51.0)을 주지만, 호환성 매트릭스는
**app 버전**(예: CA 1.34) 기준인 경우가 있다. 둘이 1:1이면 `"same"`,
아니면 변환 규칙을 명시한다.
- `"same"` — chart 버전 = app 버전 (ingress-nginx, cert-manager)
- `{"type": "lookup", "table": {...}}` — chart→app 매핑 필요 (cluster-autoscaler)

---

## 1축: `support` — 대상 K8s 버전을 지원하나?

`type`이 셋 중 하나. (실데이터로 이 3종이 논리적 완결임을 확인)

### `window` — chart 버전 범위마다 [k8s_min, k8s_max] (ingress-nginx)
```jsonc
"support": {
  "type": "window",
  "matrix": [
    { "chart_range": "4.13.x", "k8s_min": "1.29", "k8s_max": "1.33" },
    { "chart_range": "4.14.x", "k8s_min": "1.30", "k8s_max": "1.34" },
    { "chart_range": "4.15.x", "k8s_min": "1.31", "k8s_max": "1.35" }
  ]
}
```
**평가**: 설치된 chart 버전 → 매칭 range → `target > k8s_max`면 **FAIL** (차트 먼저 올려야 함).

### `minor_pin` — K8s minor와 app minor가 1:1 (cluster-autoscaler)
```jsonc
"support": {
  "type": "minor_pin",
  "note": "CA app minor는 K8s minor와 일치해야 함 (patch는 무관)"
}
```
**평가**: 설치된 app minor != target minor면 **FAIL** (차트 minor를 맞춰야 함).

### `unknown` — 머신리더블 매핑 없음 (ALB controller, kube-prometheus-stack)
```jsonc
"support": { "type": "unknown" }
```
**평가**: 자동 판정 불가 → **WARN** + `compat_source` 안내 + `k8s_breaks`/`upgrade_hazards` 발화.
자동 PASS로 조용히 넘기지 않는다 (false 안심 방지).

---

## 2축: `lifecycle` — 차트가 아직 살아있나? (support와 직교)

### `none` — 정상
```jsonc
"lifecycle": { "type": "none" }
```

### `whole_retired` — 차트 전체 EOL (ingress-nginx, 2026-03)
```jsonc
"lifecycle": {
  "type": "whole_retired",
  "eol_date": "2026-03",
  "detail": "보안 패치 없음, 2026-03-24 아카이브",
  "migration": "Gateway API 구현체로 이전 (공식 후속 미지정)",
  "announcement": "https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/",
  "severity": "HIGH"
}
```
**평가**: 항상 **WARN** (지금 당장은 동작하지만 이전 계획 필요).

### `per_release` — release별 날짜 EOL (cert-manager)
```jsonc
"lifecycle": {
  "type": "per_release",
  "policy": "release당 ~4개월 지원, 최소 2개 버전 유지",
  "releases": [
    { "range": "1.18.x", "eol_date": "2026-03-10" },
    { "range": "1.19.x", "eol_date": "2026-08-01" }
  ],
  "severity": "HIGH"
}
```
**평가**: 설치 버전의 `eol_date` < **오늘** 이면 **WARN** (EOL된 release 사용 중).
→ 체커가 **오늘 날짜**를 알아야 한다 (`--today` 주입 가능, 테스트 결정성 위해).

---

## 3축: `upgrade_hazards` — 차트를 올릴 때 수동으로 뭐가 무나?

K8s 점프가 아니라 **차트 버전 점프**에서 터지는 수동 단계. 릴리스 노트에만 묻혀있는 tribal knowledge.
support 평가 결과 "차트를 올려야 한다"가 나올 때 함께 발화한다.

```jsonc
"upgrade_hazards": [
  {
    "trigger": "chart major bump",      // 언제 무는가 (설명용)
    "type": "CRD",                       // CRD | IAM | WEBHOOK | FLAG_REMOVED
    "action": "kubectl apply로 CRD 수동 업데이트 필요 (Helm은 CRD 자동 업글 안 함)",
    "severity": "HIGH"
  }
]
```

### 횡단 규칙 (registry와 무관하게 항상 적용)
**"Helm v3는 CRD를 자동 업그레이드하지 않는다"** — CRD를 가진 모든 차트의 공통 함정.
체커는 release가 CRD 보유 차트로 등록돼 있으면(`"has_crds": true`) 이 경고를 자동 발화한다.

---

## `k8s_breaks` — K8s 버전 점프 사건 (점프 구간에 걸릴 때만)

특정 K8s 버전에서 제거/변경된 API에 차트가 물리는 경우.
`current < V <= target` 구간에 키 V가 들어올 때만 발화한다.

```jsonc
"k8s_breaks": {
  "1.22": { "change": "networking.k8s.io/v1beta1 Ingress 제거", "requires": "chart >= 4.0.0", "severity": "CRITICAL" },
  "1.25": { "change": "PodSecurityPolicy 제거", "severity": "HIGH" }
}
```

---

## 평가 결과 → exit code (기존 gate_check와 동일 신뢰 모델)

| 상황 | severity | exit 영향 |
|------|----------|-----------|
| support FAIL (차트가 target 미지원) | CRITICAL | exit 1 (차단) |
| k8s_breaks CRITICAL 발화 | CRITICAL | exit 1 |
| lifecycle / unknown / hazards / k8s_breaks HIGH | HIGH | exit 2 (확인) |
| 전부 통과 | — | exit 0 |

- `exit 0` = PASS / `exit 1` = FAIL(차단) / `exit 2` = WARN(수동 검토)
- registry에 없는 차트 → `kubeVersion` best-effort 평가 + "수동 검토 필요" INFO

---

## 새 차트 추가 체크리스트

1. `helm show chart <repo>/<chart>`로 kubeVersion·버전 체계 확인
2. `compat_source`(공식 호환성 문서) URL 확보 — **머릿속 기억 금지, 실제 조회**
3. support.type 판별 (window / minor_pin / unknown)
4. lifecycle 확인 (retirement 공지·EOL 정책)
5. 릴리스 노트에서 upgrade_hazards 추출 (CRD/IAM/webhook/flag)
6. 과거 K8s API 제거에 물리면 k8s_breaks 추가
7. `tests/test_helm_compat_check.py`에 평가 테스트 추가
