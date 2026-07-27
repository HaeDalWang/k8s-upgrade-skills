"""
tests/test_helm_compat_check.py — helm-k8s-compat 체커 단위 테스트

순수 함수(버전 파싱/범위 매칭/3축 평가)를 클러스터·네트워크 없이 검증한다.
설계 근거: 실측 5개 차트가 단일 호환성 모델로 표현 불가 → window/minor_pin/unknown
3종 + lifecycle 2종 + k8s_breaks 직교 분해. (registry/_schema.md 참조)
"""

import json

import pytest

import compat_lib


# ══════════════════════════════════════════════════════════════
# 버전 파싱 헬퍼
# ══════════════════════════════════════════════════════════════
class TestParseChartRef:
    def test_hyphenated_name(self):
        # helm ls의 chart 필드는 "<name>-<version>" — name에 하이픈이 있어도 분리
        name, ver = compat_lib.parse_chart_ref("ingress-nginx-4.15.1")
        assert name == "ingress-nginx"
        assert ver == "4.15.1"

    def test_v_prefixed_version(self):
        name, ver = compat_lib.parse_chart_ref("cert-manager-v1.20.3")
        assert name == "cert-manager"
        assert ver == "v1.20.3"

    def test_simple_name(self):
        name, ver = compat_lib.parse_chart_ref("karpenter-1.6.3")
        assert name == "karpenter"
        assert ver == "1.6.3"

    def test_no_version_returns_empty_version(self):
        name, ver = compat_lib.parse_chart_ref("weird-chart-name")
        # 버전 패턴이 없으면 전체를 이름으로, 버전은 빈 문자열
        assert ver == ""


class TestParseMinor:
    def test_basic(self):
        assert compat_lib.parse_minor("1.34.2") == (1, 34)

    def test_v_prefix(self):
        assert compat_lib.parse_minor("v1.20.3") == (1, 20)

    def test_minor_only(self):
        assert compat_lib.parse_minor("1.33") == (1, 33)


class TestVersionMatchesRange:
    def test_x_patch_wildcard_matches(self):
        assert compat_lib.version_matches_range("4.13.5", "4.13.x") is True

    def test_different_minor_no_match(self):
        assert compat_lib.version_matches_range("4.14.0", "4.13.x") is False

    def test_v_prefix_normalized(self):
        assert compat_lib.version_matches_range("v4.13.0", "4.13.x") is True


class TestK8sGt:
    def test_greater_minor(self):
        assert compat_lib.k8s_gt("1.34", "1.33") is True

    def test_equal_not_greater(self):
        assert compat_lib.k8s_gt("1.33", "1.33") is False

    def test_lesser(self):
        assert compat_lib.k8s_gt("1.32", "1.33") is False


# ══════════════════════════════════════════════════════════════
# 1축: support 평가
# ══════════════════════════════════════════════════════════════
INGRESS_WINDOW = {
    "type": "window",
    "matrix": [
        {"chart_range": "4.13.x", "k8s_min": "1.29", "k8s_max": "1.33"},
        {"chart_range": "4.14.x", "k8s_min": "1.30", "k8s_max": "1.34"},
        {"chart_range": "4.15.x", "k8s_min": "1.31", "k8s_max": "1.35"},
    ],
}


class TestEvaluateWindow:
    def test_target_exceeds_kmax_fails(self):
        # chart 4.13.x는 K8s 1.33이 상한 → 1.34로 올리면 차단
        f = compat_lib.evaluate_support(
            {"support": INGRESS_WINDOW, "chart_to_app": "same"},
            installed_chart_ver="4.13.5", installed_app_ver="1.13.5",
            target_k8s="1.34")
        assert f.result == "FAIL"
        assert f.severity == "CRITICAL"

    def test_target_within_window_passes(self):
        f = compat_lib.evaluate_support(
            {"support": INGRESS_WINDOW, "chart_to_app": "same"},
            installed_chart_ver="4.14.2", installed_app_ver="1.14.2",
            target_k8s="1.34")
        assert f.result == "PASS"

    def test_chart_version_outside_matrix_is_info(self):
        # 매트릭스에 없는 구버전 → 자동 판정 불가, INFO로 수동 검토 안내
        f = compat_lib.evaluate_support(
            {"support": INGRESS_WINDOW, "chart_to_app": "same"},
            installed_chart_ver="3.40.0", installed_app_ver="0.49.0",
            target_k8s="1.34")
        assert f.result in ("FAIL", "SKIP")
        assert f.severity in ("MEDIUM", "LOW", "HIGH")


class TestEvaluateMinorPin:
    PIN = {"type": "minor_pin"}

    def test_minor_mismatch_fails(self):
        # CA app 1.33 인데 K8s 1.34로 올림 → 차트 minor 안 맞음
        f = compat_lib.evaluate_support(
            {"support": self.PIN, "chart_to_app": "same"},
            installed_chart_ver="9.47.0", installed_app_ver="1.33.0",
            target_k8s="1.34")
        assert f.result == "FAIL"
        assert f.severity == "CRITICAL"

    def test_minor_match_passes(self):
        f = compat_lib.evaluate_support(
            {"support": self.PIN, "chart_to_app": "same"},
            installed_chart_ver="9.51.0", installed_app_ver="1.34.1",
            target_k8s="1.34")
        assert f.result == "PASS"


class TestEvaluateUnknown:
    def test_unknown_is_warn_not_silent_pass(self):
        # 머신리더블 매핑 없음 → 자동 PASS 금지, WARN으로 수동 검토 유도
        f = compat_lib.evaluate_support(
            {"support": {"type": "unknown"}, "chart_to_app": "same",
             "compat_source": "https://example/docs"},
            installed_chart_ver="3.4.0", installed_app_ver="3.4.0",
            target_k8s="1.34")
        assert f.result == "FAIL"
        assert f.severity == "HIGH"


# ══════════════════════════════════════════════════════════════
# 2축: lifecycle 평가
# ══════════════════════════════════════════════════════════════
class TestEvaluateLifecycle:
    def test_none_returns_no_finding(self):
        assert compat_lib.evaluate_lifecycle(
            {"lifecycle": {"type": "none"}}, "4.15.1", today="2026-06-26") is None

    def test_whole_retired_always_warns(self):
        f = compat_lib.evaluate_lifecycle(
            {"lifecycle": {"type": "whole_retired", "severity": "HIGH",
                           "detail": "EOL", "migration": "Gateway API"}},
            "4.15.1", today="2026-06-26")
        assert f is not None
        assert f.result == "FAIL" and f.severity == "HIGH"

    def test_per_release_eol_passed_warns(self):
        # 1.18.x는 2026-03-10 EOL → 오늘(2026-06-26)이 지났으므로 WARN
        lc = {"lifecycle": {"type": "per_release", "severity": "HIGH",
              "releases": [{"range": "1.18.x", "eol_date": "2026-03-10"},
                           {"range": "1.20.x", "eol_date": "2026-09-01"}]}}
        f = compat_lib.evaluate_lifecycle(lc, "1.18.2", today="2026-06-26")
        assert f is not None and f.result == "FAIL"

    def test_per_release_still_supported_no_warn(self):
        lc = {"lifecycle": {"type": "per_release", "severity": "HIGH",
              "releases": [{"range": "1.18.x", "eol_date": "2026-03-10"},
                           {"range": "1.20.x", "eol_date": "2026-09-01"}]}}
        f = compat_lib.evaluate_lifecycle(lc, "1.20.1", today="2026-06-26")
        assert f is None


# ══════════════════════════════════════════════════════════════
# k8s_breaks 발화 (점프 구간만)
# ══════════════════════════════════════════════════════════════
class TestFiredK8sBreaks:
    BREAKS = {
        "k8s_breaks": {
            "1.22": {"change": "Ingress v1beta1 제거", "severity": "CRITICAL"},
            "1.25": {"change": "PSP 제거", "severity": "HIGH"},
        }
    }

    def test_only_breaks_in_jump_window_fire(self):
        # 1.24 → 1.25 점프 → 1.25만 발화, 1.22는 이미 지난 과거라 발화 안 함
        fs = compat_lib.fired_k8s_breaks(self.BREAKS, current_k8s="1.24", target_k8s="1.25")
        assert len(fs) == 1
        assert "PSP" in fs[0].detail

    def test_multiple_breaks_in_wide_jump(self):
        fs = compat_lib.fired_k8s_breaks(self.BREAKS, current_k8s="1.21", target_k8s="1.25")
        assert len(fs) == 2

    def test_no_breaks_when_jump_clears_all(self):
        fs = compat_lib.fired_k8s_breaks(self.BREAKS, current_k8s="1.30", target_k8s="1.31")
        assert fs == []


class TestFiredK8sBreaksRequiresChartMin:
    """requires_chart_min 조건 평가 — 설치 차트가 요구 최소 버전을 충족하면 발화하지 않아야 함."""

    BREAKS = {
        "k8s_breaks": {
            "1.22": {
                "change": "networking.k8s.io/v1beta1 Ingress 제거",
                "requires_chart_min": "4.0.0",
                "severity": "CRITICAL",
            },
        }
    }

    def test_installed_chart_meets_requirement_no_fire(self):
        # 설치 차트 4.14.2 >= 요구 4.0.0 → 이미 충족, 차단하지 않음
        fs = compat_lib.fired_k8s_breaks(
            self.BREAKS, current_k8s="1.21", target_k8s="1.25",
            installed_chart_ver="4.14.2")
        assert fs == []

    def test_installed_chart_below_requirement_fires(self):
        # 설치 차트 3.40.0 < 요구 4.0.0 → 차단
        fs = compat_lib.fired_k8s_breaks(
            self.BREAKS, current_k8s="1.21", target_k8s="1.25",
            installed_chart_ver="3.40.0")
        assert len(fs) == 1
        assert fs[0].severity == "CRITICAL"

    def test_no_requires_field_always_fires(self):
        # requires_chart_min 없는 break(예: PSP 제거)는 차트 버전과 무관하게 발화
        breaks = {"k8s_breaks": {"1.25": {"change": "PSP 제거", "severity": "HIGH"}}}
        fs = compat_lib.fired_k8s_breaks(
            breaks, current_k8s="1.24", target_k8s="1.25",
            installed_chart_ver="4.14.2")
        assert len(fs) == 1

    def test_missing_installed_ver_still_fires_conservatively(self):
        # 설치 차트 버전 판별 불가 → 안전하게 발화(false 안심 방지)
        fs = compat_lib.fired_k8s_breaks(
            self.BREAKS, current_k8s="1.21", target_k8s="1.25",
            installed_chart_ver="")
        assert len(fs) == 1


class TestChartVersionCompare:
    """chart_ge: 차트 버전 semver 비교 (requires_chart_min 평가에 사용)."""

    def test_greater_patch(self):
        assert compat_lib.chart_ge("4.14.2", "4.0.0") is True

    def test_equal(self):
        assert compat_lib.chart_ge("4.0.0", "4.0.0") is True

    def test_less(self):
        assert compat_lib.chart_ge("3.40.0", "4.0.0") is False

    def test_v_prefix_normalized(self):
        assert compat_lib.chart_ge("v4.14.2", "4.0.0") is True

    def test_minor_only_string(self):
        # patch 없는 "4.14" 도 허용
        assert compat_lib.chart_ge("4.14", "4.0.0") is True


class TestWindowLowerBound:
    """window 평가에서 target이 k8s_min 미만이면(차트가 너무 새것) 검출."""

    WINDOW = {
        "type": "window",
        "matrix": [
            {"chart_range": "4.15.x", "k8s_min": "1.31", "k8s_max": "1.35"},
        ],
    }

    def test_target_below_kmin_fails(self):
        # chart 4.15.x는 K8s 1.31 하한 → 1.30으로는 지원 범위 밖
        f = compat_lib.evaluate_support(
            {"support": self.WINDOW, "chart_to_app": "same"},
            installed_chart_ver="4.15.1", installed_app_ver="1.15.1",
            target_k8s="1.30")
        assert f.result == "FAIL"

    def test_target_at_kmin_passes(self):
        f = compat_lib.evaluate_support(
            {"support": self.WINDOW, "chart_to_app": "same"},
            installed_chart_ver="4.15.1", installed_app_ver="1.15.1",
            target_k8s="1.31")
        assert f.result == "PASS"


class TestVersionValidation:
    """K8s 버전 문자열 검증 — 시스템 경계 fail-fast."""

    def test_valid_minor(self):
        assert compat_lib.is_valid_k8s_version("1.33") is True

    def test_valid_with_patch(self):
        assert compat_lib.is_valid_k8s_version("1.33.2") is True

    def test_missing_minor_invalid(self):
        assert compat_lib.is_valid_k8s_version("1") is False

    def test_non_numeric_invalid(self):
        assert compat_lib.is_valid_k8s_version("abc") is False

    def test_empty_invalid(self):
        assert compat_lib.is_valid_k8s_version("") is False


# ══════════════════════════════════════════════════════════════
# 횡단 규칙: Helm CRD 자동 업글 안 함
# ══════════════════════════════════════════════════════════════
class TestCrdCrosscuttingRule:
    def test_has_crds_emits_warn_when_chart_upgrade_needed(self):
        # CRD 보유 차트 + 차트 업그레이드 필요 상황 → CRD 수동 경고
        f = compat_lib.crd_warning({"has_crds": True}, chart_upgrade_needed=True)
        assert f is not None and f.severity == "HIGH"

    def test_no_crds_no_warning(self):
        assert compat_lib.crd_warning({"has_crds": False}, chart_upgrade_needed=True) is None

    def test_crds_but_no_upgrade_needed_no_warning(self):
        assert compat_lib.crd_warning({"has_crds": True}, chart_upgrade_needed=False) is None


# ══════════════════════════════════════════════════════════════
# registry 로딩
# ══════════════════════════════════════════════════════════════
class TestLoadRegistry:
    def test_loads_json_keyed_by_chart_name(self, tmp_path):
        (tmp_path / "foo.json").write_text(
            json.dumps({"chart_name": "foo", "support": {"type": "unknown"}}),
            encoding="utf-8")
        (tmp_path / "_schema.md").write_text("# 무시됨", encoding="utf-8")
        reg = compat_lib.load_registry(str(tmp_path))
        assert "foo" in reg
        assert "_schema" not in reg  # .md는 로드 안 함

    def test_missing_dir_returns_empty(self):
        assert compat_lib.load_registry("/nonexistent/path/xyz") == {}

    def test_corrupt_json_warns_to_stderr(self, tmp_path, capsys):
        # 파손된 JSON은 조용히 삼키지 말고 stderr로 경고 — false 안심 방지
        (tmp_path / "broken.json").write_text("{ not valid json", encoding="utf-8")
        (tmp_path / "ok.json").write_text(
            json.dumps({"chart_name": "ok", "support": {"type": "unknown"}}),
            encoding="utf-8")
        reg = compat_lib.load_registry(str(tmp_path))
        # 정상 파일은 로드되고, 파손 파일은 경고만 남기고 스킵
        assert "ok" in reg
        err = capsys.readouterr().err
        assert "broken.json" in err

    def test_missing_chart_name_warns(self, tmp_path, capsys):
        # chart_name 없는 JSON도 조용히 무시하지 말고 경고
        (tmp_path / "nameless.json").write_text(
            json.dumps({"support": {"type": "unknown"}}), encoding="utf-8")
        compat_lib.load_registry(str(tmp_path))
        err = capsys.readouterr().err
        assert "nameless.json" in err


# ══════════════════════════════════════════════════════════════
# parse_chart_ref — 비정상 입력 방어
# ══════════════════════════════════════════════════════════════
class TestParseChartRefDefensive:
    def test_latest_tag_no_crash(self):
        # "my-app-latest" 같은 비정상 chart 필드 — 크래시 없이 빈 버전 반환
        name, ver = compat_lib.parse_chart_ref("my-app-latest")
        assert ver == ""
