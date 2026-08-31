#!/usr/bin/env python3
"""
compat_lib.py — helm-k8s-compat 체커 공통 헬퍼

버전 파싱, 범위 매칭, 3직교축(support/lifecycle/k8s_breaks) 평가의 순수 함수를
제공한다. 클러스터·네트워크 없이 테스트 가능하도록 부수효과를 분리했다.

설계 근거 및 스키마: registry/_schema.md 참조.
Python 3.9+ stdlib only — 서드파티 의존성 없음.
"""

import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

# 차트 ref에서 버전 부분을 식별하는 패턴 (선택적 v + 숫자.숫자)
_VERSION_RE = re.compile(r"^(?P<name>.+)-(?P<ver>v?\d+\.\d+[\w.\-+]*)$")


# ══════════════════════════════════════════════════════════════
# Finding: 평가 결과 1건 (불변)
# ══════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Finding:
    """평가 결과 1건. record()로 그대로 흘려보낼 수 있도록 result/severity/detail를 갖는다."""
    rule_id: str
    result: str       # PASS | FAIL | SKIP
    severity: str     # CRITICAL | HIGH | MEDIUM | LOW
    detail: str


# ══════════════════════════════════════════════════════════════
# 버전 파싱 헬퍼
# ══════════════════════════════════════════════════════════════
def _strip_v(ver: str) -> str:
    """선행 'v' 제거. 'v1.20.3' → '1.20.3'."""
    return ver[1:] if ver.startswith("v") else ver


def parse_chart_ref(chart_ref: str) -> tuple:
    """helm ls의 chart 필드('<name>-<version>')를 (name, version)으로 분리한다.

    이름에 하이픈이 있어도(ingress-nginx) 버전 패턴을 기준으로 마지막 하이픈에서 자른다.
    버전 패턴이 없으면 (전체, '')를 반환한다.
    """
    m = _VERSION_RE.match(chart_ref)
    if m:
        return m.group("name"), m.group("ver")
    return chart_ref, ""


def parse_minor(ver: str) -> tuple:
    """버전 문자열에서 (major, minor) 정수 튜플을 추출한다. 'v1.20.3' → (1, 20)."""
    parts = _strip_v(ver).split(".")
    return int(parts[0]), int(parts[1])


def version_matches_range(ver: str, chart_range: str) -> bool:
    """버전이 'X.Y.x' 형태의 range에 속하는지. '4.13.5' vs '4.13.x' → True."""
    prefix = chart_range[:-1] if chart_range.endswith("x") else chart_range
    return _strip_v(ver).startswith(prefix)


def k8s_gt(a: str, b: str) -> bool:
    """K8s 버전 a가 b보다 minor 기준으로 큰가. '1.34' > '1.33' → True."""
    return parse_minor(a) > parse_minor(b)


def k8s_lt(a: str, b: str) -> bool:
    """K8s 버전 a가 b보다 minor 기준으로 작은가. '1.30' < '1.31' → True."""
    return parse_minor(a) < parse_minor(b)


# K8s 버전 문자열 형식: 최소 major.minor (patch 선택적)
_K8S_VERSION_RE = re.compile(r"^v?\d+\.\d+(\.\d+.*)?$")


def is_valid_k8s_version(ver: str) -> bool:
    """K8s 버전 문자열이 major.minor(.patch) 형식인지. 시스템 경계 검증용."""
    return bool(_K8S_VERSION_RE.match(ver))


def _semver_tuple(ver: str) -> tuple:
    """차트 버전을 (major, minor, patch) 정수 튜플로. 누락 자리는 0. 'v4.14' → (4, 14, 0)."""
    parts = _strip_v(ver).split(".")
    nums = []
    for p in parts[:3]:
        m = re.match(r"^\d+", p)
        nums.append(int(m.group()) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def chart_ge(a: str, b: str) -> bool:
    """차트 버전 a가 b 이상인가(semver major.minor.patch 비교). '4.14.2' >= '4.0.0' → True."""
    return _semver_tuple(a) >= _semver_tuple(b)


# ══════════════════════════════════════════════════════════════
# 1축: support — 대상 K8s 버전을 지원하나?
# ══════════════════════════════════════════════════════════════
def _resolve_app_minor(entry: dict, installed_chart_ver: str,
                       installed_app_ver: str) -> Optional[tuple]:
    """chart_to_app 규칙에 따라 app minor를 결정한다. 판별 불가면 None.

    - `"same"`        — chart 버전 = app 버전. app_version이 비어도 chart 버전으로 대체 가능.
    - `"app_version"` — chart와 app이 별개 체계(cluster-autoscaler chart 9.x vs CA 1.x).
      helm의 app_version만 신뢰하며, 없으면 chart 버전으로 대체하지 않고 None을 반환한다.
      (chart 9.51.0을 app 9.51로 오인해 false BLOCK 내던 문제 방지)
    - `{"type": "lookup"}` — chart_range → app 버전 매핑표. 미매칭이면 app_version으로 폴백.
    """
    mapping = entry.get("chart_to_app", "same")

    if isinstance(mapping, dict) and mapping.get("type") == "lookup":
        for rng, app_ver in mapping.get("table", {}).items():
            if version_matches_range(installed_chart_ver, rng):
                return parse_minor(app_ver)

    # "same"은 chart 버전이 곧 app 버전 → app_version 누락 시 안전하게 대체 가능
    if mapping == "same" and not installed_app_ver and installed_chart_ver:
        return parse_minor(installed_chart_ver)

    if not installed_app_ver:
        return None
    return parse_minor(installed_app_ver)


def _eval_window(entry: dict, support: dict, chart_name: str,
                 installed_chart_ver: str, installed_app_ver: str,
                 target_k8s: str) -> Finding:
    """버전 범위마다 [k8s_min, k8s_max]가 정해진 경우 (ingress-nginx, cert-manager, istio).

    `match_on: "app"`이면 chart 버전이 아니라 app 버전으로 매트릭스를 찾는다. external-dns나
    metrics-server처럼 chart(1.19.0 / 3.13.0)와 app(0.19.x / 0.8.x)의 체계가 다르고 공식
    매트릭스가 app 기준으로 쓰인 차트가 그렇다.

    `k8s_max`가 없는 행은 **상한 없음**(하한만 명시된 매트릭스)으로 본다.
    """
    match_on_app = support.get("match_on") == "app"
    probe = installed_app_ver if match_on_app else installed_chart_ver
    label = f"app {probe}" if match_on_app else probe

    if not probe:
        return Finding(
            "HELM-SUPPORT", "FAIL", "HIGH",
            f"{chart_name}: 매트릭스 대조에 필요한 "
            f"{'app' if match_on_app else 'chart'} 버전을 판별할 수 없음 — 수동 확인 필요")

    for row in support.get("matrix", []):
        if not version_matches_range(probe, row["chart_range"]):
            continue
        k_max = row.get("k8s_max")
        k_min = row.get("k8s_min")
        if k_max and k8s_gt(target_k8s, k_max):
            return Finding(
                "HELM-SUPPORT", "FAIL", "CRITICAL",
                f"{chart_name} {label}: K8s {k_max} 상한 — "
                f"target {target_k8s} 지원하려면 차트를 먼저 올려야 함")
        if k_min and k8s_lt(target_k8s, k_min):
            # 차트가 target보다 앞선 상황 — 업그레이드하면 오히려 해소된다.
            # 막을 일이 아니라 알릴 일이므로 HIGH를 유지한다.
            return Finding(
                "HELM-SUPPORT", "FAIL", "HIGH",
                f"{chart_name} {label}: K8s {k_min} 하한 — "
                f"target {target_k8s}는 이 차트 버전의 지원 범위보다 낮음(차트가 너무 최신)")
        return Finding(
            "HELM-SUPPORT", "PASS", "LOW",
            f"{chart_name} {label}: target {target_k8s} 지원 범위 내")

    return Finding(
        "HELM-SUPPORT", "FAIL", "MEDIUM",
        f"{chart_name} {label}: 호환성 매트릭스에 없는 버전 — 수동 검토 필요")


def _eval_k8s_floor(entry: dict, support: dict, chart_name: str,
                    installed_chart_ver: str, target_k8s: str) -> Finding:
    """K8s 버전마다 **요구되는 최소 차트 버전**이 정해진 경우 (karpenter).

    `window`와 방향이 반대다. window는 "이 차트 버전이 어느 K8s를 지원하나"이고,
    이쪽은 "이 K8s를 쓰려면 차트가 최소 몇이어야 하나"이다. Karpenter 공식 매트릭스가
    후자 형태라 window로 옮기려면 사람이 상한을 역산해야 하고, 새 릴리스마다 그 역산이
    낡는다. 공식 표를 그대로 옮길 수 있게 별도 타입으로 둔다.
    """
    floors = support.get("floors", {})
    floor = floors.get(target_k8s)

    if not floor:
        return Finding(
            "HELM-SUPPORT", "FAIL", "HIGH",
            f"{chart_name}: 공식 매트릭스에 K8s {target_k8s} 행이 없음 — "
            f"아직 미발행이거나 지원 범위 밖. 릴리스 노트 직접 확인 필요")

    if not installed_chart_ver:
        return Finding(
            "HELM-SUPPORT", "FAIL", "HIGH",
            f"{chart_name}: 설치 버전을 판별할 수 없어 K8s {target_k8s} 요구사항"
            f"(>= {floor}) 충족 여부 자동 판정 불가 — 수동 확인 필요")

    if not chart_ge(installed_chart_ver, floor):
        return Finding(
            "HELM-SUPPORT", "FAIL", "CRITICAL",
            f"{chart_name} {installed_chart_ver}: K8s {target_k8s}는 "
            f"{chart_name} {floor} 이상을 요구 — 차트를 먼저 올려야 함")

    return Finding(
        "HELM-SUPPORT", "PASS", "LOW",
        f"{chart_name} {installed_chart_ver}: K8s {target_k8s} 요구사항"
        f"(>= {floor}) 충족")


def _eval_minor_pin(entry: dict, chart_name: str, installed_chart_ver: str,
                    installed_app_ver: str, target_k8s: str) -> Finding:
    """app minor가 클러스터 K8s minor와 1:1이어야 하는 경우 (cluster-autoscaler)."""
    app_minor = _resolve_app_minor(entry, installed_chart_ver, installed_app_ver)
    if app_minor is None:
        return Finding(
            "HELM-SUPPORT", "FAIL", "HIGH",
            f"{chart_name} (chart {installed_chart_ver}): app 버전을 판별할 수 없어 "
            f"K8s minor 일치 여부를 자동 판정할 수 없음 — 수동 확인 필요")

    if app_minor != parse_minor(target_k8s):
        return Finding(
            "HELM-SUPPORT", "FAIL", "CRITICAL",
            f"{chart_name} app {app_minor[0]}.{app_minor[1]}: K8s minor와 1:1 일치 필요 — "
            f"target {target_k8s}에 맞춰 차트를 올려야 함")

    return Finding(
        "HELM-SUPPORT", "PASS", "LOW",
        f"{chart_name}: app minor가 target {target_k8s}와 일치")


# ══════════════════════════════════════════════════════════════
# evidence — 이 판단의 근거가 어느 계층에서 왔나
# ══════════════════════════════════════════════════════════════
# 출처의 등급이지 정확도 보증이 아니다. 높은 등급이 붙었다고 재검증이 면제되지 않는다
# (공식 매트릭스도 잘못 읽으면 틀린다).
#
#   official_matrix  — 공식 호환성 매트릭스가 존재하고 그걸 그대로 옮김
#   official_doc     — 공식 문서에 서술은 있으나 매트릭스는 아님 ("requires K8s 1.22+")
#   chart_inspect    — 차트를 렌더해 K8s 결합 표면(CRD/webhook/APIService/CSI)을 확인
#   kubeversion_only — Chart.yaml의 kubeVersion만 확인. **하한 정보뿐이다**
#   community        — 공신력 있는 커뮤니티 신호(GitHub 이슈, 설치 후기)
#   none             — 근거 없음
EVIDENCE_LEVELS = ("official_matrix", "official_doc", "chart_inspect",
                   "kubeversion_only", "community", "none")

# kubeVersion은 대부분 하한만 선언하므로, 그것만으로 "이 버전까지 괜찮다"는 상한을
# 주장할 수 없다. 이 스킬이 kubeVersion을 자동 판정에 쓰지 않기로 한 이유 그대로다.
EVIDENCE_CANNOT_CLAIM_MAX = ("kubeversion_only", "none")

# K8s API에 직접 붙는 표면. 이게 있으면 마이너 업그레이드가 실제로 깨뜨릴 수 있으므로
# 공식 매트릭스가 아닌 근거로 "여기까지 괜찮다"고 말할 수 없다.
COUPLING_KEYS = ("crds", "webhooks", "apiservices", "csi_drivers")


def has_coupling_surface(entry: dict) -> bool:
    """차트가 K8s API 확장 지점(CRD/webhook/APIService/CSI)을 갖는가.

    `surface`는 `helm template` + `helm show crds`로 실측해 기록한다. 다만 렌더가
    모든 것을 보여주지는 않는다 — argo-workflows처럼 CRD를 pre-install hook Job으로
    설치하는 차트는 렌더 결과에 CRD가 0으로 나온다. 그런 경우 실측값 대신 사실을
    적고 `hook_installed_crds: true`로 표시한다.
    """
    surface = entry.get("surface", {})
    if surface.get("hook_installed_crds"):
        return True
    return any(int(surface.get(k, 0) or 0) > 0 for k in COUPLING_KEYS)


def _eval_unknown(entry: dict, support: dict, chart_name: str,
                  target_k8s: str) -> Finding:
    """머신리더블 매핑이 없는 경우 (ALB controller, kube-prometheus-stack).

    자동 PASS는 금지하되(false 안심 방지), 매번 WARN을 내면 상시 경고가 되어 사람이 무시한다.
    `verified_k8s_max`는 "사람이 공식 문서로 여기까지 확인했다"는 기록이며, 그 범위 안이면
    조용히 통과시키고 target이 그 위로 올라가면 자동으로 다시 경고한다.
    """
    src = entry.get("compat_source", "(문서 미등록)")
    verified_max = support.get("verified_k8s_max", "")
    evidence = support.get("evidence", "none")

    # K8s 확장 지점을 가진 차트는 공식 매트릭스가 아닌 근거로 상한을 주장할 수 없다.
    # CRD·webhook·APIService는 마이너 업그레이드가 실제로 깨뜨리는 지점이고,
    # "문서에 상한이 없더라"는 그것을 확인한 것이 아니다.
    if verified_max and has_coupling_surface(entry) and evidence != "official_matrix":
        surface = entry.get("surface", {})
        detail_bits = ", ".join(f"{k}={surface[k]}" for k in COUPLING_KEYS
                                if int(surface.get(k, 0) or 0) > 0) or "hook 설치 CRD"
        return Finding(
            "HELM-SUPPORT", "FAIL", "HIGH",
            f"{chart_name}: K8s 확장 지점 보유({detail_bits}) — 근거가 {evidence}"
            f"뿐이라 K8s {verified_max}까지 안전하다고 볼 수 없음. 공식 문서 확인 필요: {src}")

    # 근거가 kubeVersion뿐이면 상한 주장을 인정하지 않는다. 라벨을 붙인다고 하한에서
    # 상한을 끌어내는 추론이 정당해지지는 않는다.
    if verified_max and evidence in EVIDENCE_CANNOT_CLAIM_MAX:
        return Finding(
            "HELM-SUPPORT", "FAIL", "HIGH",
            f"{chart_name}: 매트릭스 없음 + 근거가 {evidence} 뿐 — "
            f"kubeVersion은 하한만 알려주므로 K8s {verified_max}까지 괜찮다는 "
            f"판단의 근거가 되지 못함. 공식 문서 확인 필요: {src}")

    if not verified_max:
        return Finding(
            "HELM-SUPPORT", "FAIL", "HIGH",
            f"{chart_name}: 호환성 매트릭스 없음 — 공식 문서 수동 확인 필요: {src}")

    if k8s_gt(target_k8s, verified_max):
        return Finding(
            "HELM-SUPPORT", "FAIL", "HIGH",
            f"{chart_name}: 수동 확인 기록은 K8s {verified_max}까지 — "
            f"target {target_k8s}는 미확인 구간. 공식 문서 확인 필요: {src}")

    # PASS로 찍지 않는다. 근거가 "사람이 확인했다"뿐인데 공식 매트릭스 기반 PASS와
    # 같은 표시가 나가면 실제 검증 강도를 과대평가하게 된다. 게이트는 열리되(MEDIUM은
    # exit code에 영향 없음) audit에는 자동 판정이 아니라는 사실이 남는다.
    when = f", {entry['last_verified']} 확인" if entry.get("last_verified") else ""
    return Finding(
        "HELM-SUPPORT", "FAIL", "MEDIUM",
        f"{chart_name}: 매트릭스 없음 — K8s {verified_max}까지 확인 기록"
        f"(근거: {evidence}{when}) — target {target_k8s}는 그 범위 내, 자동 판정 아님")


def evaluate_support(entry: dict, installed_chart_ver: str,
                     installed_app_ver: str, target_k8s: str) -> Finding:
    """support 축 평가. window/minor_pin/unknown 3종을 각 평가 함수로 분기한다."""
    support = entry.get("support", {})
    stype = support.get("type")
    chart_name = entry.get("chart_name", "?")

    if stype == "window":
        return _eval_window(entry, support, chart_name, installed_chart_ver,
                            installed_app_ver, target_k8s)

    if stype == "minor_pin":
        return _eval_minor_pin(entry, chart_name, installed_chart_ver,
                               installed_app_ver, target_k8s)

    if stype == "k8s_floor":
        return _eval_k8s_floor(entry, support, chart_name,
                               installed_chart_ver, target_k8s)

    return _eval_unknown(entry, support, chart_name, target_k8s)


# ══════════════════════════════════════════════════════════════
# 신선도 — 큐레이션 데이터가 언제 기준인가
# ══════════════════════════════════════════════════════════════
# registry는 공식 문서를 사람이 옮겨 적은 스냅샷이라 시간이 지나면 낡는다.
# 이 일수를 넘으면 "판정의 근거가 오래됐다"고 알린다.
STALE_AFTER_DAYS = 180


def _days_between(earlier: str, later: str) -> Optional[int]:
    """'YYYY-MM-DD' 두 날짜의 일수 차. 파싱 불가면 None."""
    try:
        return (date.fromisoformat(later) - date.fromisoformat(earlier)).days
    except ValueError:
        return None


def evaluate_staleness(entry: dict, today: str,
                       stale_after_days: int = STALE_AFTER_DAYS) -> Optional[Finding]:
    """큐레이션 데이터의 신선도를 평가한다. 문제없으면 None.

    호출 측은 **support가 PASS일 때만** 이 결과를 쓴다. FAIL은 데이터가 낡아도 조치가
    필요하다는 결론이 그대로 유효하지만, "문제 없음"을 오래된 근거로 말하는 것은 위험하다.

    MEDIUM(INFO)으로 유지해 게이트를 막지는 않는다 — 낡음은 위험의 증거가 아니라
    확신도의 문제이고, 여기서 차단하면 그것대로 상시 경고가 된다.
    """
    chart_name = entry.get("chart_name", "?")
    last_verified = entry.get("last_verified", "")

    if not last_verified:
        return Finding(
            "HELM-STALE", "FAIL", "MEDIUM",
            f"{chart_name}: registry 항목에 last_verified 없음 — "
            f"큐레이션 시점을 알 수 없어 PASS 판정의 신뢰도가 불명")

    age = _days_between(last_verified, today)
    if age is None:
        return Finding(
            "HELM-STALE", "FAIL", "MEDIUM",
            f"{chart_name}: last_verified '{last_verified}' 형식 오류 "
            f"(YYYY-MM-DD 필요) — 신선도 판정 불가")

    if age > stale_after_days:
        return Finding(
            "HELM-STALE", "FAIL", "MEDIUM",
            f"{chart_name}: 큐레이션 데이터 {age}일 경과 (마지막 확인 {last_verified}) — "
            f"PASS 판정의 근거가 오래됨. {entry.get('compat_source', '공식 문서')} 재확인 권장")

    return None


# ══════════════════════════════════════════════════════════════
# 2축: lifecycle — 차트가 아직 살아있나?
# ══════════════════════════════════════════════════════════════
def evaluate_lifecycle(entry: dict, installed_ver: str,
                       today: str) -> Optional[Finding]:
    """lifecycle 축 평가. 정상이면 None, 문제면 Finding을 반환한다.

    today는 'YYYY-MM-DD' 문자열로 주입(테스트 결정성). per_release EOL 비교에 사용.
    """
    lc = entry.get("lifecycle", {})
    ltype = lc.get("type", "none")
    chart_name = entry.get("chart_name", "?")
    severity = lc.get("severity", "HIGH")

    if ltype == "none":
        return None

    if ltype == "whole_retired":
        detail = lc.get("detail", "EOL")
        migration = lc.get("migration", "")
        msg = f"{chart_name}: 차트 전체 retirement — {detail}"
        if migration:
            msg += f" / 이전: {migration}"
        return Finding("HELM-LIFECYCLE", "FAIL", severity, msg)

    if ltype == "per_release":
        for rel in lc.get("releases", []):
            if version_matches_range(installed_ver, rel["range"]):
                eol = rel.get("eol_date", "")
                if eol and eol < today:
                    return Finding(
                        "HELM-LIFECYCLE", "FAIL", severity,
                        f"{chart_name} {installed_ver}: release EOL 경과 "
                        f"(EOL {eol} < 오늘 {today}) — 지원 버전으로 올려야 함")
                return None
        return None

    return None


# ══════════════════════════════════════════════════════════════
# k8s_breaks — K8s 버전 점프 사건 (점프 구간만 발화)
# ══════════════════════════════════════════════════════════════
def fired_k8s_breaks(entry: dict, current_k8s: str, target_k8s: str,
                     installed_chart_ver: str = "") -> list:
    """current < V <= target 구간에 걸린 k8s_breaks 항목만 Finding 리스트로 반환한다.

    break에 requires_chart_min이 있으면, 설치 차트가 그 최소 버전을 이미 충족한 경우
    발화하지 않는다(false BLOCK 방지). 설치 차트 버전을 알 수 없으면(빈 문자열) 안전하게
    발화한다(false 안심 방지).
    """
    breaks = entry.get("k8s_breaks", {})
    chart_name = entry.get("chart_name", "?")
    cur = parse_minor(current_k8s)
    tgt = parse_minor(target_k8s)

    out = []
    for ver_key, info in sorted(breaks.items(), key=lambda kv: parse_minor(kv[0])):
        v = parse_minor(ver_key)
        if not (cur < v <= tgt):
            continue
        requires_min = info.get("requires_chart_min", "")
        # 요구 최소 버전이 있고, 설치 차트가 이를 충족하면 이미 안전 → 발화 안 함
        if requires_min and installed_chart_ver and chart_ge(installed_chart_ver, requires_min):
            continue
        detail = f"{chart_name}: K8s {ver_key} — {info.get('change', '')}"
        if requires_min:
            detail += f" (요구: chart >= {requires_min})"
        out.append(Finding("HELM-K8SBREAK", "FAIL",
                           info.get("severity", "HIGH"), detail))
    return out


# ══════════════════════════════════════════════════════════════
# 3축: upgrade_hazards — 차트를 올릴 때 수동으로 뭐가 무나?
# ══════════════════════════════════════════════════════════════
def fired_hazards(entry: dict, installed_chart_ver: str,
                  chart_upgrade_needed: bool) -> list:
    """차트 업그레이드가 필요할 때 걸리는 hazard만 Finding 리스트로 반환한다.

    `fires_below`가 있으면 설치 차트가 그 버전 이상일 때 발화하지 않는다. 이미 지나온
    버전의 주의사항까지 매번 띄우면(v3.5.0 설치본에 v3.0.0 hazard 4건) 경고 피로가 되어
    정작 봐야 할 것을 묻는다. k8s_breaks의 `requires_chart_min`과 같은 억제 원리다.

    설치 차트 버전을 알 수 없으면 안전하게 발화한다(false 안심 방지).
    """
    if not chart_upgrade_needed:
        return []

    chart_name = entry.get("chart_name", "?")
    out = []
    for hz in entry.get("upgrade_hazards", []):
        fires_below = hz.get("fires_below", "")
        if fires_below and installed_chart_ver and chart_ge(installed_chart_ver, fires_below):
            continue
        out.append(Finding(
            "HELM-HAZARD", "FAIL", hz.get("severity", "HIGH"),
            f"{chart_name}: {hz.get('action', '')} (trigger: {hz.get('trigger', '')})"))
    return out


# ══════════════════════════════════════════════════════════════
# 횡단 규칙: Helm v3는 CRD를 자동 업그레이드하지 않음
# ══════════════════════════════════════════════════════════════
def crd_warning(entry: dict, chart_upgrade_needed: bool) -> Optional[Finding]:
    """CRD 보유 차트를 올려야 하는 상황이면 CRD 수동 업데이트 경고를 반환한다."""
    if entry.get("has_crds") and chart_upgrade_needed:
        chart_name = entry.get("chart_name", "?")
        return Finding(
            "HELM-CRD", "FAIL", "HIGH",
            f"{chart_name}: 차트 업그레이드 필요 — Helm v3는 CRD를 자동 업데이트하지 않음. "
            f"kubectl apply로 CRD를 수동 갱신해야 함")
    return None


# ══════════════════════════════════════════════════════════════
# registry 로딩
# ══════════════════════════════════════════════════════════════
def load_registry(registry_dir: str) -> dict:
    """registry_dir의 *.json을 chart_name으로 키잉한 dict로 로드한다.

    .md(스키마 문서)는 무시한다. 디렉토리가 없으면 빈 dict 반환.
    파손된 JSON이나 chart_name 누락은 조용히 삼키지 않고 stderr로 경고한다
    (오타 하나로 차트가 사라져 false 안심을 주는 것을 방지).
    """
    d = Path(registry_dir)
    if not d.is_dir():
        return {}
    reg = {}
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: registry 파일 로드 실패, 스킵함: {f.name} ({e})",
                  file=sys.stderr)
            continue
        name = data.get("chart_name")
        if not name:
            print(f"WARNING: registry 파일에 chart_name 없음, 스킵함: {f.name}",
                  file=sys.stderr)
            continue
        # 한 파일이 여러 chart 이름을 담을 수 있다 — istio처럼 base/istiod/cni/ztunnel이
        # 같은 버전·같은 매트릭스를 공유하는 경우 파일을 4벌 복제하지 않는다.
        for n in (name if isinstance(name, list) else [name]):
            # 각 키가 자기 이름을 갖도록 얕은 복사 — 원본을 그대로 공유하면
            # 메시지에 ['base', 'istiod', ...] 리스트가 통째로 찍힌다.
            reg[n] = {**data, "chart_name": n}
    return reg
