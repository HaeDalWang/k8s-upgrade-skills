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


# ══════════════════════════════════════════════════════════════
# chart_to_app — app 버전 판별 (chart 버전 오인 방지)
# ══════════════════════════════════════════════════════════════
class TestResolveAppMinor:
    """helm ls가 app_version을 비워 보낼 때 chart 버전을 app으로 오인하면 안 된다.

    cluster-autoscaler는 chart 9.x / app 1.x로 체계가 달라, 폴백이 곧 false BLOCK이었다.
    """

    PIN = {"type": "minor_pin"}

    def test_app_version_scheme_missing_app_ver_is_undecidable(self):
        # chart_to_app="app_version" + app_version 빈 값 → CRITICAL이 아니라 판정 불가(HIGH)
        f = compat_lib.evaluate_support(
            {"support": self.PIN, "chart_to_app": "app_version",
             "chart_name": "cluster-autoscaler"},
            installed_chart_ver="9.51.0", installed_app_ver="",
            target_k8s="1.36")
        assert f.result == "FAIL"
        assert f.severity == "HIGH"
        assert "판별할 수 없어" in f.detail
        # chart 버전(9.51)을 app 버전으로 오인한 흔적이 없어야 한다
        assert "app 9.51" not in f.detail

    def test_app_version_scheme_with_app_ver_still_evaluates(self):
        f = compat_lib.evaluate_support(
            {"support": self.PIN, "chart_to_app": "app_version",
             "chart_name": "cluster-autoscaler"},
            installed_chart_ver="9.51.0", installed_app_ver="1.36.0",
            target_k8s="1.36")
        assert f.result == "PASS"

    def test_same_scheme_falls_back_to_chart_ver(self):
        # chart 버전 = app 버전인 차트는 app_version이 비어도 chart 버전으로 판정 가능
        f = compat_lib.evaluate_support(
            {"support": self.PIN, "chart_to_app": "same", "chart_name": "x"},
            installed_chart_ver="1.36.2", installed_app_ver="",
            target_k8s="1.36")
        assert f.result == "PASS"

    def test_lookup_table_maps_chart_to_app(self):
        entry = {"support": self.PIN, "chart_name": "x",
                 "chart_to_app": {"type": "lookup",
                                  "table": {"9.51.x": "1.34.0"}}}
        f = compat_lib.evaluate_support(
            entry, installed_chart_ver="9.51.0", installed_app_ver="",
            target_k8s="1.34")
        assert f.result == "PASS"


# ══════════════════════════════════════════════════════════════
# 신선도 — 큐레이션 데이터가 언제 기준인가
# ══════════════════════════════════════════════════════════════
class TestEvaluateStaleness:
    ENTRY = {"chart_name": "x", "compat_source": "https://example/docs"}

    def test_fresh_data_no_finding(self):
        e = {**self.ENTRY, "last_verified": "2026-08-01"}
        assert compat_lib.evaluate_staleness(e, today="2026-08-31") is None

    def test_stale_data_is_info_not_gate_blocking(self):
        # 낡음은 위험의 증거가 아니라 확신도 문제 — MEDIUM(INFO)이라 게이트를 막지 않는다
        e = {**self.ENTRY, "last_verified": "2026-01-01"}
        f = compat_lib.evaluate_staleness(e, today="2026-08-31")
        assert f is not None
        assert f.severity == "MEDIUM"
        assert "242일 경과" in f.detail

    def test_boundary_exactly_at_threshold_is_fresh(self):
        # 임계값과 같은 날은 아직 낡지 않음 (> 비교)
        e = {**self.ENTRY, "last_verified": "2026-03-04"}  # 2026-08-31까지 180일
        assert compat_lib.evaluate_staleness(e, today="2026-08-31") is None

    def test_missing_last_verified_warns(self):
        # 큐레이션 시점을 모르면 낡았는지도 알 수 없다 → 침묵하지 않는다
        f = compat_lib.evaluate_staleness(self.ENTRY, today="2026-08-31")
        assert f is not None
        assert "last_verified 없음" in f.detail

    def test_malformed_date_warns(self):
        e = {**self.ENTRY, "last_verified": "2026/08/31"}
        f = compat_lib.evaluate_staleness(e, today="2026-08-31")
        assert f is not None
        assert "형식 오류" in f.detail


# ══════════════════════════════════════════════════════════════
# unknown + verified_k8s_max — 상시 WARN 억제
# ══════════════════════════════════════════════════════════════
class TestUnknownVerifiedMax:
    def _entry(self, evidence="official_doc", **kw):
        return {"chart_name": "alb",
                "support": {"type": "unknown", "evidence": evidence, **kw},
                "compat_source": "https://example/docs", "chart_to_app": "same"}

    def test_within_verified_range_is_info_not_pass(self):
        # 근거가 "사람이 확인했다"뿐이므로 공식 매트릭스 PASS와 같은 표시를 내면 안 된다.
        # MEDIUM은 exit code에 영향이 없어 게이트는 열린 채로 남는다.
        f = compat_lib.evaluate_support(
            self._entry(verified_k8s_max="1.36"),
            installed_chart_ver="3.5.0", installed_app_ver="3.5.0", target_k8s="1.36")
        assert f.severity == "MEDIUM"
        assert f.result != "PASS"
        assert "자동 판정 아님" in f.detail

    def test_beyond_verified_range_warns_again(self):
        # 확인 기록을 넘어서면 자동으로 다시 경고 — 기록이 영구 면죄부가 되면 안 된다
        f = compat_lib.evaluate_support(
            self._entry(verified_k8s_max="1.36"),
            installed_chart_ver="3.5.0", installed_app_ver="3.5.0", target_k8s="1.37")
        assert f.result == "FAIL"
        assert f.severity == "HIGH"
        assert "미확인 구간" in f.detail

    def test_no_verified_max_keeps_old_warn(self):
        # 필드가 없는 기존 데이터는 종전대로 HIGH (하위호환)
        f = compat_lib.evaluate_support(
            self._entry(), installed_chart_ver="3.5.0",
            installed_app_ver="3.5.0", target_k8s="1.36")
        assert f.result == "FAIL"
        assert f.severity == "HIGH"


# ══════════════════════════════════════════════════════════════
# upgrade_hazards — 이미 지나온 버전은 발화하지 않음
# ══════════════════════════════════════════════════════════════
class TestFiredHazards:
    ENTRY = {
        "chart_name": "alb",
        "upgrade_hazards": [
            {"trigger": "v3.0.0로 업그레이드", "fires_below": "3.0.0", "action": "a"},
            {"trigger": "v3.4.0로 업그레이드", "fires_below": "3.4.0", "action": "b"},
            {"trigger": "minor 업그레이드", "action": "c"},
        ],
    }

    def test_no_hazards_when_upgrade_not_needed(self):
        assert compat_lib.fired_hazards(self.ENTRY, "3.5.0", False) == []

    def test_passed_versions_suppressed(self):
        # 3.5.0 설치본에 3.0.0/3.4.0 주의사항은 이미 지나온 것 → 버전 무관 항목만 남는다
        out = compat_lib.fired_hazards(self.ENTRY, "3.5.0", True)
        assert len(out) == 1
        assert "minor 업그레이드" in out[0].detail

    def test_older_chart_still_gets_them(self):
        out = compat_lib.fired_hazards(self.ENTRY, "3.1.0", True)
        assert len(out) == 2  # 3.4.0 + 버전 무관

    def test_unknown_installed_version_fires_conservatively(self):
        # 설치 버전을 모르면 억제하지 않는다 (false 안심 방지)
        out = compat_lib.fired_hazards(self.ENTRY, "", True)
        assert len(out) == 3


# ══════════════════════════════════════════════════════════════
# k8s_floor — K8s 버전이 요구하는 최소 차트 버전 (karpenter)
# ══════════════════════════════════════════════════════════════
class TestEvaluateK8sFloor:
    ENTRY = {
        "chart_name": "karpenter",
        "support": {"type": "k8s_floor",
                    "floors": {"1.34": "1.6", "1.35": "1.9", "1.36": "1.13"}},
    }

    def test_below_floor_blocks(self):
        # 실제 사례: karpenter 1.8.6 설치본으로 K8s 1.36에 가려 함
        f = compat_lib.evaluate_support(
            self.ENTRY, installed_chart_ver="1.8.6",
            installed_app_ver="1.8.6", target_k8s="1.36")
        assert f.result == "FAIL"
        assert f.severity == "CRITICAL"
        assert "1.13 이상" in f.detail

    def test_at_floor_passes(self):
        f = compat_lib.evaluate_support(
            self.ENTRY, installed_chart_ver="1.13.0",
            installed_app_ver="1.13.0", target_k8s="1.36")
        assert f.result == "PASS"

    def test_target_not_in_matrix_warns(self):
        # 아직 공식 매핑이 안 나온 K8s는 통과시키지 않는다
        f = compat_lib.evaluate_support(
            self.ENTRY, installed_chart_ver="1.13.0",
            installed_app_ver="1.13.0", target_k8s="1.37")
        assert f.result == "FAIL"
        assert f.severity == "HIGH"

    def test_unknown_installed_version_warns(self):
        f = compat_lib.evaluate_support(
            self.ENTRY, installed_chart_ver="",
            installed_app_ver="", target_k8s="1.36")
        assert f.severity == "HIGH"
        assert "판별할 수 없어" in f.detail


# ══════════════════════════════════════════════════════════════
# window 확장 — app 버전 매칭 / 상한 없는 행
# ══════════════════════════════════════════════════════════════
class TestWindowAppMatching:
    """chart와 app 체계가 다른 차트(metrics-server chart 3.13.0 = app 0.8.0)."""

    ENTRY = {
        "chart_name": "metrics-server",
        "support": {"type": "window", "match_on": "app",
                    "matrix": [{"chart_range": "0.8.x", "k8s_min": "1.31"},
                               {"chart_range": "0.9.x", "k8s_min": "1.34"}]},
    }

    def test_matches_on_app_version_not_chart(self):
        # chart 3.13.0으로 매칭하면 매트릭스에 없어 MEDIUM이 나온다 — app 0.8.0으로 봐야 한다
        f = compat_lib.evaluate_support(
            self.ENTRY, installed_chart_ver="3.13.0",
            installed_app_ver="0.8.0", target_k8s="1.36")
        assert f.result == "PASS"
        assert "app 0.8.0" in f.detail

    def test_open_ended_row_has_no_upper_bound(self):
        # k8s_max가 없는 행은 상한 없음 — 아무리 높은 target도 상한 위반이 아니다
        f = compat_lib.evaluate_support(
            self.ENTRY, installed_chart_ver="3.13.0",
            installed_app_ver="0.8.0", target_k8s="1.40")
        assert f.result == "PASS"

    def test_below_min_still_flagged(self):
        f = compat_lib.evaluate_support(
            self.ENTRY, installed_chart_ver="3.14.0",
            installed_app_ver="0.9.0", target_k8s="1.33")
        assert f.result == "FAIL"
        assert f.severity == "HIGH"

    def test_missing_app_version_is_undecidable(self):
        f = compat_lib.evaluate_support(
            self.ENTRY, installed_chart_ver="3.13.0",
            installed_app_ver="", target_k8s="1.36")
        assert f.severity == "HIGH"
        assert "판별할 수 없음" in f.detail


class TestRegistryChartNameList:
    """istio처럼 여러 chart 이름이 같은 매트릭스를 공유하는 경우."""

    def test_list_registers_every_name(self, tmp_path):
        (tmp_path / "istio.json").write_text(json.dumps({
            "chart_name": ["base", "istiod", "cni", "ztunnel"],
            "support": {"type": "unknown"},
        }), encoding="utf-8")
        reg = compat_lib.load_registry(str(tmp_path))
        assert set(reg) == {"base", "istiod", "cni", "ztunnel"}

    def test_each_entry_carries_its_own_name(self, tmp_path):
        # 원본을 그대로 공유하면 메시지에 리스트가 통째로 찍힌다
        (tmp_path / "istio.json").write_text(json.dumps({
            "chart_name": ["base", "istiod"],
            "support": {"type": "unknown"},
        }), encoding="utf-8")
        reg = compat_lib.load_registry(str(tmp_path))
        assert reg["base"]["chart_name"] == "base"
        assert reg["istiod"]["chart_name"] == "istiod"


# ══════════════════════════════════════════════════════════════
# evidence — 근거 계층이 상한 주장을 통제한다
# ══════════════════════════════════════════════════════════════
class TestEvidenceGatesTheClaim:
    """kubeVersion은 하한만 알려준다. 그것으로 상한을 주장하는 것이 이 스킬이
    처음부터 금지한 추론이며, evidence 라벨을 붙인다고 정당해지지 않는다."""

    def _entry(self, evidence):
        return {"chart_name": "x", "compat_source": "https://example/docs",
                "support": {"type": "unknown", "evidence": evidence,
                            "verified_k8s_max": "1.36"}}

    def test_kubeversion_only_cannot_claim_max(self):
        f = compat_lib.evaluate_support(
            self._entry("kubeversion_only"), installed_chart_ver="1.0.0",
            installed_app_ver="1.0.0", target_k8s="1.36")
        assert f.severity == "HIGH"
        assert "하한만" in f.detail

    def test_no_evidence_cannot_claim_max(self):
        f = compat_lib.evaluate_support(
            self._entry("none"), installed_chart_ver="1.0.0",
            installed_app_ver="1.0.0", target_k8s="1.36")
        assert f.severity == "HIGH"

    def test_missing_evidence_field_defaults_to_none(self):
        # evidence를 안 쓴 기존 데이터도 상한 주장을 인정받지 못한다
        e = {"chart_name": "x", "compat_source": "u",
             "support": {"type": "unknown", "verified_k8s_max": "1.36"}}
        f = compat_lib.evaluate_support(
            e, installed_chart_ver="1.0.0", installed_app_ver="1.0.0",
            target_k8s="1.36")
        assert f.severity == "HIGH"

    def test_chart_inspect_can_claim_max(self):
        f = compat_lib.evaluate_support(
            self._entry("chart_inspect"), installed_chart_ver="1.0.0",
            installed_app_ver="1.0.0", target_k8s="1.36")
        assert f.severity == "MEDIUM"
        assert "chart_inspect" in f.detail

    def test_official_doc_can_claim_max(self):
        f = compat_lib.evaluate_support(
            self._entry("official_doc"), installed_chart_ver="1.0.0",
            installed_app_ver="1.0.0", target_k8s="1.36")
        assert f.severity == "MEDIUM"
