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
  "chart_name": "ingress-nginx",        // helm ls의 chart 이름과 매칭 (필수, 배열 가능)
  "last_verified": "2026-08-31",        // 공식 문서로 마지막 대조한 날짜 YYYY-MM-DD (필수)
  "repo": "https://...",                // 참고용 repo URL
  "compat_source": "https://...",       // LLM이 라이브 확인용으로 fetch할 공식 호환성 문서 (필수)
  "chart_to_app": "same",               // "same" | "app_version" | {매핑표}  (아래 참조)

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
- `"same"` — chart 버전 = app 버전 (ingress-nginx, cert-manager).
  helm이 `app_version`을 비워 보내도 chart 버전으로 대체 판정한다.
- `"app_version"` — chart와 app이 **별개 체계** (cluster-autoscaler: chart 9.x vs CA 1.x).
  helm의 `app_version`만 신뢰하고, 없으면 chart 버전으로 대체하지 **않는다**.
  대체하면 chart 9.51.0을 app 9.51로 오인해 `minor_pin`이 false BLOCK을 낸다.
- `{"type": "lookup", "table": {...}}` — chart_range → app 버전 매핑표가 있는 경우.

### `last_verified` (필수)
이 파일의 내용을 **공식 문서로 실제 대조한 날짜**. 추측으로 채우면 안 된다 — 확인하지
않았다면 확인한 사람이 마지막으로 손댄 날짜를 적는다.

체커는 support가 **PASS일 때만** 이 값을 본다. `STALE_AFTER_DAYS`(기본 180일)를 넘으면
`HELM-STALE`을 MEDIUM(INFO)으로 남긴다. FAIL은 데이터가 낡아도 "조치가 필요하다"는 결론이
유효하지만, 오래된 근거로 "문제 없음"이라 말하는 것은 위험하기 때문이다.
필드가 없으면 낡았는지조차 알 수 없으므로 역시 INFO로 알린다.

---

## `evidence` — 이 판단의 근거가 어느 계층에서 왔나

`support` 안에 둔다. **출처의 등급이지 정확도 보증이 아니다.** 높은 등급이 붙었다고 재검증이
면제되지 않는다 — 공식 매트릭스도 잘못 읽으면 틀린다(실제로 Istio 지원 표를 조회하면서
`Supported`와 `Tested, but not supported` 열을 뒤집어 읽은 적이 있다).

| 등급 | 의미 |
|---|---|
| `official_matrix` | 공식 호환성 매트릭스가 존재하고 그걸 그대로 옮김 |
| `official_doc` | 공식 문서에 서술은 있으나 매트릭스는 아님 ("requires K8s 1.22+") |
| `chart_inspect` | 차트를 렌더해 **K8s 결합 표면**(CRD/webhook/APIService/CSI)을 확인 |
| `kubeversion_only` | Chart.yaml의 `kubeVersion`만 확인 — **하한 정보뿐** |
| `community` | 공신력 있는 커뮤니티 신호(GitHub 이슈, 설치 후기) |
| `none` | 근거 없음 |

### 등급이 `verified_k8s_max`를 통제한다 (코드로 강제)

- `kubeversion_only` / `none` → **상한을 주장할 수 없다.** `kubeVersion`은 대부분 하한만
  선언하므로 "`>=1.25`를 1.36이 충족하니 1.36까지 OK"는 이 스킬이 처음부터 금지한 추론이다.
  라벨을 붙인다고 정당해지지 않는다.
- **K8s 확장 지점을 가진 차트**(아래 `surface` 참조)는 `official_matrix`가 아닌 근거로
  상한을 주장할 수 없다. CRD·webhook·APIService는 마이너 업그레이드가 실제로 깨뜨리는
  지점이고, "문서에 상한이 없더라"는 그것을 확인한 것이 아니다.

---

## `surface` — 차트가 K8s API에 붙는 표면 (실측)

`helm template` + `helm show crds`로 렌더해 센다. 클러스터 접근이 필요 없다.

```jsonc
"surface": {
  "verified_by": "helm template + helm show crds (2026-08-31, 클러스터 미접속)",
  "crds": 6, "webhooks": 1, "apiservices": 1, "csi_drivers": 0, "daemonsets": 0
}
```

`crds`/`webhooks`/`apiservices`/`csi_drivers` 중 하나라도 0보다 크면 "결합 표면 있음"으로
보고 위의 상한 주장 제한이 걸린다. `daemonsets`는 노드 레벨 배포 신호일 뿐 API 확장은
아니라서 제한에 넣지 않는다.

### 렌더가 모든 것을 보여주지는 않는다

argo-workflows는 `crds.install` 기본값이 `true`인데도 렌더 결과의 CRD가 **0개**다. 차트가
CRD를 pre-install/pre-upgrade **hook Job**으로 server-side apply 하기 때문이다. 실제로는
CRD를 쓴다. 이런 경우 실측값 대신 사실을 적고 `"hook_installed_crds": true`로 표시한다.

렌더 자체가 실패하는 경우도 있다(gitlab은 필수 values가 없어 실패, ghcr.io 403 등).
그때는 `"measured": false`와 이유를 적고 `evidence`를 `kubeversion_only` 이하로 둔다 —
추측으로 `chart_inspect`를 붙이지 않는다.

---

## 1축: `support` — 대상 K8s 버전을 지원하나?

`type`이 셋 중 하나. (실데이터로 이 3종이 논리적 완결임을 확인)

> **`chart_name`에 배열을 줄 수 있다.** istio처럼 `base`/`istiod`/`cni`/`ztunnel`이 같은
> 버전·같은 매트릭스를 공유하면 파일을 4벌 복제하지 말고 배열 하나로 등록한다. 로더가 각
> 이름을 개별 키로 등록하면서 그 키의 `chart_name`을 자기 이름으로 채워준다.

### `window` — 버전 범위마다 [k8s_min, k8s_max] (ingress-nginx)
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
**평가**: 설치된 chart 버전 → 매칭 range →

- `target > k8s_max`면 **FAIL/CRITICAL** (차트가 너무 구버전 — 먼저 올려야 함).
- `target < k8s_min`면 **FAIL/HIGH** (차트가 너무 최신 — target이 이 차트의 지원 하한보다 낮음).
- 그 사이면 **PASS**.

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
"support": {
  "type": "unknown",
  "verified_k8s_max": "1.36",   // 선택: 사람이 여기까지 확인함
  "note": "무엇을 근거로 확인했는지"
}
```
**평가**: 자동 판정 불가 → **WARN** + `compat_source` 안내 + `k8s_breaks`/`upgrade_hazards` 발화.
자동 PASS로 조용히 넘기지 않는다 (false 안심 방지).

**`verified_k8s_max`** (선택): 사람이 공식 문서를 조회해 **이 K8s 버전까지 차단 요인이 없음을
확인했다**는 기록. 공식이 그 버전을 보장한다는 뜻이 **아니다** — 상한을 명시하지 않는 차트가
대부분이라 "확인 결과 막는 것이 없었다"가 실제 의미다. 무엇을 근거로 그렇게 판단했는지 `note`에
반드시 남긴다.

- `target <= verified_k8s_max` → **PASS** (확인 날짜를 함께 표시)
- `target > verified_k8s_max` → **WARN** (미확인 구간 — 기록이 영구 면죄부가 되지 않는다)
- 필드 없음 → 종전대로 항상 WARN

이 필드가 없으면 `unknown` 차트는 설치돼 있는 한 **매번** WARN이 뜬다. ALB controller처럼
대부분의 EKS 클러스터에 있는 차트가 그러면 게이트가 상시 경고 상태가 되어 사람이 무시하게 된다.
확인한 범위를 기록해 조용히 두고, K8s가 그 위로 올라갈 때 다시 울리게 하는 것이 목적이다.

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
    "fires_below": "3.4.0",              // 선택: 설치 차트가 이 버전 미만일 때만 발화
    "action": "kubectl apply로 CRD 수동 업데이트 필요 (Helm은 CRD 자동 업글 안 함)",
    "severity": "HIGH"
  }
]
```

**`fires_below`** (선택): 이 주의사항을 **아직 지나지 않은** 설치본에만 띄운다. 설치 차트가
이 버전 이상이면 이미 겪고 넘어온 것이므로 발화하지 않는다. v3.5.0 설치본에 v3.0.0~v3.4.0
주의사항 4건을 매번 띄우면 정작 봐야 할 항목이 묻힌다. `k8s_breaks`의 `requires_chart_min`과
같은 억제 원리다.

설치 차트 버전을 알 수 없으면(빈 문자열) 억제하지 않고 발화한다(false 안심 방지).
버전과 무관하게 매 업그레이드마다 해당되는 항목(cert-manager의 "minor 업그레이드 시 CRD 갱신")
에는 이 필드를 **넣지 않는다**.

### 횡단 규칙 (registry와 무관하게 항상 적용)
**"Helm v3는 CRD를 자동 업그레이드하지 않는다"** — CRD를 가진 모든 차트의 공통 함정.
체커는 release가 CRD 보유 차트로 등록돼 있으면(`"has_crds": true`) 이 경고를 자동 발화한다.

---

## `k8s_breaks` — K8s 버전 점프 사건 (점프 구간에 걸릴 때만)

특정 K8s 버전에서 제거/변경된 API에 차트가 물리는 경우.
`current < V <= target` 구간에 키 V가 들어올 때만 발화한다.

```jsonc
"k8s_breaks": {
  "1.22": { "change": "networking.k8s.io/v1beta1 Ingress 제거", "requires_chart_min": "4.0.0", "severity": "CRITICAL" },
  "1.25": { "change": "PodSecurityPolicy 제거", "severity": "HIGH" }
}
```

#### `match_on: "app"` — chart가 아니라 app 버전으로 매트릭스를 찾는다

공식 매트릭스가 app 버전 기준으로 쓰였고 chart 버전 체계가 다른 경우에 쓴다. 실측 예:

| 차트 | chart | app | 매트릭스 기준 |
|---|---|---|---|
| metrics-server | 3.13.0 | 0.8.0 | app |
| external-dns | 1.19.0 | 0.19.0 | app |

`match_on`이 없으면 종전대로 chart 버전으로 매칭한다. 이 값을 잘못 두면 매트릭스에 없는
버전으로 취급돼 조용히 MEDIUM으로 빠지므로, 새 차트를 넣을 때 `helm show chart`로 두 버전을
반드시 실측해 확인한다.

#### `k8s_max` 생략 = 상한 없음

metrics-server처럼 공식 매트릭스가 **하한만** 제시하는 경우가 있다(`0.8.x → 1.31+`).
이때 `k8s_max`를 쓰지 않으면 상한 없음으로 평가한다. 없는 상한을 임의로 만들어 넣지 않는다.

### `k8s_floor` — K8s 버전마다 요구되는 최소 차트 버전 (karpenter)

`window`와 방향이 반대다. window는 "이 차트 버전이 어느 K8s를 지원하나"이고, 이쪽은
"이 K8s를 쓰려면 차트가 최소 몇이어야 하나"이다.

```jsonc
"support": {
  "type": "k8s_floor",
  "floors": {
    "1.34": "1.6",
    "1.35": "1.9",
    "1.36": "1.13"
  }
}
```

**평가**: target K8s의 floor를 찾아 설치 차트와 비교한다.
- 설치 차트 >= floor → PASS
- 설치 차트 < floor → **CRITICAL** (차트를 먼저 올려야 함)
- target이 `floors`에 없음 → **HIGH** (아직 미발행이거나 지원 범위 밖 — 통과시키지 않는다)

Karpenter 공식 표가 이 형태라, window로 옮기려면 사람이 각 차트 버전의 상한을 역산해야 하고
새 릴리스가 나올 때마다 그 역산이 낡는다. 공식 표를 그대로 옮길 수 있게 별도 타입으로 둔다.

---

**`requires_chart_min`** (선택): 이 API 제거를 안전하게 넘길 수 있는 **최소 차트 버전**.
설치된 차트가 이 버전 이상이면 이미 대응된 것이므로 발화하지 않는다(false BLOCK 방지).
설치 차트 버전을 판별할 수 없으면(빈 문자열) 안전하게 발화한다(false 안심 방지).
필드가 없으면 차트 버전과 무관하게 항상 발화한다(예: PSP 제거는 어느 버전이든 영향).

---

## 평가 결과 → exit code (기존 gate_check와 동일 신뢰 모델)

| 상황 | severity | exit 영향 |
|------|----------|-----------|
| support FAIL (차트가 target 미지원) | CRITICAL | exit 1 (차단) |
| k8s_breaks CRITICAL 발화 | CRITICAL | exit 1 |
| lifecycle / unknown / hazards / k8s_breaks HIGH | HIGH | exit 2 (확인) |
| 전부 통과 | — | exit 0 |

- `exit 0` = PASS / `exit 1` = FAIL(차단) / `exit 2` = WARN(수동 검토) / `exit 64` = 입력 오류(게이트 판정 아님) / `exit 127` = helm 미존재
- registry에 없는 차트 → "수동 검토 필요" INFO (gate 차단 안 함). 체커가 `kubeVersion`을 직접
  읽지는 않으므로, 검토 시 `helm show chart`·릴리스 노트를 사람이 확인한다.

---

## 새 차트 추가 체크리스트

1. `helm show chart <repo>/<chart> --version <ver>`로 **chart/app 버전과 kubeVersion을 실측**
   (OCI는 `helm show chart oci://<repo>/<chart> --version <ver>`). 클러스터 접근 없이 된다
2. `compat_source`(공식 호환성 문서) URL 확보 — **머릿속 기억 금지, 실제 조회**
3. `chart_to_app` 판별 — chart 버전과 app 버전이 같은 체계인가(`same`), 별개인가(`app_version`)
4. support.type 판별 (window / k8s_floor / minor_pin / unknown).
   매트릭스가 app 버전 기준이면 `match_on: "app"`, 하한만 있으면 `k8s_max` 생략.
   `unknown`이면 어디까지 확인했는지 `verified_k8s_max` + 근거 `note` 기록
5. lifecycle 확인 (retirement 공지·EOL 정책)
6. 릴리스 노트에서 upgrade_hazards 추출 (CRD/IAM/webhook/flag).
   특정 버전으로 올라갈 때만 해당되면 `fires_below` 지정
7. 과거 K8s API 제거에 물리면 k8s_breaks 추가
8. **`last_verified`를 실제 조회한 날짜로 기록** — 추측 금지
9. `tests/test_helm_compat_check.py`에 평가 테스트 추가
