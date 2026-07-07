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
                       installed_app_ver: str) -> tuple:
    """chart_to_app 규칙에 따라 app minor를 결정한다. 'same'이면 app_ver를 그대로 사용."""
    mapping = entry.get("chart_to_app", "same")
    if mapping == "same":
        return parse_minor(installed_app_ver)
    # lookup 테이블 (chart_range → app 버전)
    if isinstance(mapping, dict) and mapping.get("type") == "lookup":
        for rng, app_ver in mapping.get("table", {}).items():
            if version_matches_range(installed_chart_ver, rng):
                return parse_minor(app_ver)
    return parse_minor(installed_app_ver)


def evaluate_support(entry: dict, installed_chart_ver: str,
                     installed_app_ver: str, target_k8s: str) -> Finding:
    """support 축 평가. window/minor_pin/unknown 3종을 처리한다."""
    support = entry.get("support", {})
    stype = support.get("type")
    chart_name = entry.get("chart_name", "?")

    if stype == "window":
        for row in support.get("matrix", []):
            if version_matches_range(installed_chart_ver, row["chart_range"]):
                k_max = row["k8s_max"]
                k_min = row.get("k8s_min")
                if k8s_gt(target_k8s, k_max):
                    return Finding(
                        "HELM-SUPPORT", "FAIL", "CRITICAL",
                        f"{chart_name} {installed_chart_ver}: K8s {k_max} 상한 — "
                        f"target {target_k8s} 지원하려면 차트를 먼저 올려야 함")
                if k_min and k8s_lt(target_k8s, k_min):
                    return Finding(
                        "HELM-SUPPORT", "FAIL", "HIGH",
                        f"{chart_name} {installed_chart_ver}: K8s {k_min} 하한 — "
                        f"target {target_k8s}는 이 차트 버전의 지원 범위보다 낮음(차트가 너무 최신)")
                return Finding(
                    "HELM-SUPPORT", "PASS", "LOW",
                    f"{chart_name} {installed_chart_ver}: target {target_k8s} 지원 범위 내")
        # 매트릭스에 없는 버전 — 자동 판정 불가
        return Finding(
            "HELM-SUPPORT", "FAIL", "MEDIUM",
            f"{chart_name} {installed_chart_ver}: 호환성 매트릭스에 없는 버전 — 수동 검토 필요")

    if stype == "minor_pin":
        app_minor = _resolve_app_minor(entry, installed_chart_ver, installed_app_ver)
        target_minor = parse_minor(target_k8s)
        if app_minor != target_minor:
            return Finding(
                "HELM-SUPPORT", "FAIL", "CRITICAL",
                f"{chart_name} app {app_minor[0]}.{app_minor[1]}: K8s minor와 1:1 일치 필요 — "
                f"target {target_k8s}에 맞춰 차트를 올려야 함")
        return Finding(
            "HELM-SUPPORT", "PASS", "LOW",
            f"{chart_name}: app minor가 target {target_k8s}와 일치")

    # unknown — 머신리더블 매핑 없음. 자동 PASS 금지 (false 안심 방지)
    src = entry.get("compat_source", "(문서 미등록)")
    return Finding(
        "HELM-SUPPORT", "FAIL", "HIGH",
        f"{chart_name}: 호환성 매트릭스 없음 — 공식 문서 수동 확인 필요: {src}")


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
        if name:
            reg[name] = data
        else:
            print(f"WARNING: registry 파일에 chart_name 없음, 스킵함: {f.name}",
                  file=sys.stderr)
    return reg
