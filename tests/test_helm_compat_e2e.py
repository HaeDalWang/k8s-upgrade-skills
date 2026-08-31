"""
tests/test_helm_compat_e2e.py — helm_compat_check.py 통합 테스트

CLI 엔트리포인트를 클러스터 없이 --releases-json 주입으로 검증한다.
exit code 신뢰 모델(0/1/2)과 audit.log 기록을 확인한다.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CHECKER = REPO / "helm-k8s-compat" / "scripts" / "helm_compat_check.py"
REGISTRY = REPO / "helm-k8s-compat" / "registry"


def run_checker(tmp_path, releases, current, target, today="2026-06-26"):
    """체커를 --releases-json 주입 모드로 실행하고 (returncode, audit내용)을 반환한다."""
    audit = tmp_path / "audit.log"
    proc = subprocess.run(
        [sys.executable, str(CHECKER),
         "--current", current, "--target", target,
         "--registry-dir", str(REGISTRY),
         "--audit-log", str(audit),
         "--today", today,
         "--releases-json", json.dumps(releases)],
        capture_output=True, text=True)
    content = audit.read_text(encoding="utf-8") if audit.exists() else ""
    return proc.returncode, content, proc.stdout


class TestExitCodes:
    def test_window_chart_exceeds_kmax_blocks(self, tmp_path):
        # ingress-nginx 4.13.x → K8s 1.34로 올리면 CRITICAL (상한 1.33)
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "ingress-nginx", "namespace": "ingress-nginx",
              "chart": "ingress-nginx-4.13.5", "app_version": "1.13.5"}],
            current="1.33", target="1.34")
        assert rc == 1
        assert "HELM-SUPPORT" in audit
        assert "1.33 상한" in audit

    def test_supported_window_passes(self, tmp_path):
        # ingress-nginx 4.14.x → K8s 1.34 지원 범위 내. 단 retirement WARN은 남음
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "ingress-nginx", "namespace": "ingress-nginx",
              "chart": "ingress-nginx-4.14.2", "app_version": "1.14.2"}],
            current="1.33", target="1.34")
        # support는 PASS지만 lifecycle(retired)이 HIGH → exit 2
        assert rc == 2
        assert "retirement" in audit

    def test_no_releases_is_clean_pass(self, tmp_path):
        rc, audit, out = run_checker(tmp_path, [], current="1.33", target="1.34")
        assert rc == 0

    def test_unknown_chart_not_in_registry_is_info(self, tmp_path):
        # registry에 없는 차트 → 수동 검토 INFO, gate는 막지 않음(exit 0)
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "my-internal-app", "namespace": "default",
              "chart": "my-internal-app-2.1.0", "app_version": "2.1.0"}],
            current="1.33", target="1.34")
        assert rc == 0
        assert "my-internal-app" in audit
        assert "수동 검토" in audit


class TestK8sBreaks:
    def test_psp_removal_fires_on_125_jump(self, tmp_path):
        # ingress-nginx + 1.24→1.25 점프 → PSP 제거 HIGH 발화
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "ingress-nginx", "namespace": "ingress-nginx",
              "chart": "ingress-nginx-4.14.0", "app_version": "1.14.0"}],
            current="1.24", target="1.25")
        assert "PodSecurityPolicy" in audit or "PSP" in audit
        assert rc in (1, 2)


class TestAuditHeader:
    def test_audit_has_summary_line(self, tmp_path):
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "ingress-nginx", "namespace": "x",
              "chart": "ingress-nginx-4.14.2", "app_version": "1.14.2"}],
            current="1.33", target="1.34")
        assert "HELM-COMPAT" in audit or "Summary" in audit


class TestInputValidation:
    def test_invalid_version_string_rejected(self, tmp_path):
        # "1" 처럼 minor 없는 버전 → traceback 없이 명확한 에러 + 비정상 종료
        rc, audit, out = run_checker(
            tmp_path, [], current="1", target="1.34")
        assert rc != 0
        assert rc != 127  # helm 미존재와 구분

    def test_target_not_greater_than_current_rejected(self, tmp_path):
        # 다운그레이드/동일 버전 → 거부
        rc, audit, out = run_checker(
            tmp_path, [], current="1.34", target="1.33")
        assert rc != 0

    def test_equal_versions_are_audit_mode_not_error(self, tmp_path):
        # 동일 버전은 "지금 상태 점검" 모드다 — 차트를 올릴 때가 됐는지 주기적으로 보는 용도
        rc, audit, out = run_checker(
            tmp_path, [], current="1.34", target="1.34")
        assert rc == 0
        assert "상태 점검" in audit


class TestMalformedRelease:
    def test_unparseable_chart_ref_isolated_not_crash(self, tmp_path):
        # chart 필드가 "app-latest" 같이 버전 파싱 불가 → 해당 release만 격리, 크래시 없음
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "weird", "namespace": "default",
              "chart": "weird-latest", "app_version": "latest"}],
            current="1.33", target="1.34")
        # 크래시 없이 종료(0/1/2 중 하나), traceback 문자열 없음
        assert rc in (0, 1, 2)
        assert "Traceback" not in out


class TestK8sBreaksRequiresChartMin:
    def test_ingress_1_22_break_suppressed_for_modern_chart(self, tmp_path):
        # ingress-nginx 4.14.2로 1.21→1.25 점프 시, 1.22 Ingress v1beta1 제거
        # (requires_chart_min 4.0.0)는 이미 충족되므로 CRITICAL로 차단하면 안 된다.
        # 이 테스트의 핵심: v1beta1 CRITICAL이 억제되어 exit 1이 아니어야 함.
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "ingress-nginx", "namespace": "ingress-nginx",
              "chart": "ingress-nginx-4.14.2", "app_version": "1.14.2"}],
            current="1.21", target="1.25")
        assert "v1beta1" not in audit  # 억제되어 audit에 안 나타남
        assert rc != 1                  # CRITICAL 없음(HIGH들만 남아 exit 2)

    def test_ingress_1_22_break_fires_for_ancient_chart(self, tmp_path):
        # 반대: 구버전 차트 3.40.0은 requires_chart_min(4.0.0) 미충족 → CRITICAL 발화
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "ingress-nginx", "namespace": "ingress-nginx",
              "chart": "ingress-nginx-3.40.0", "app_version": "0.49.0"}],
            current="1.21", target="1.25")
        assert "v1beta1" in audit
        assert rc == 1


class TestUsageErrorsAreNotGateVerdicts:
    """입력 오류가 WARN(2)으로 새어나가면 '검토 후 진행'으로 오해되어 게이트가 무력화된다."""

    def test_malformed_version_exits_64_not_2(self, tmp_path):
        rc, _, _ = run_checker(tmp_path, [], current="abc", target="1.36")
        assert rc == 64

    def test_downgrade_exits_64_not_2(self, tmp_path):
        rc, _, _ = run_checker(tmp_path, [], current="1.36", target="1.35")
        assert rc == 64

    def test_same_version_is_not_a_usage_error(self, tmp_path):
        # 동일 버전은 정기 점검 용도라 입력 오류가 아니다
        rc, _, _ = run_checker(tmp_path, [], current="1.36", target="1.36")
        assert rc != 64


class TestMinorPinAppVersionMissing:
    def test_missing_app_version_warns_not_blocks(self, tmp_path):
        # cluster-autoscaler chart 9.51.0은 app 1.x 체계 — chart 버전을 app으로 오인하면 안 됨
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "ca", "namespace": "kube-system",
              "chart": "cluster-autoscaler-9.51.0", "app_version": ""}],
            current="1.35", target="1.36")
        assert rc == 2
        assert "app 9.51" not in audit


class TestStalenessSurfacing:
    def test_stale_registry_adds_info_but_keeps_gate_open(self, tmp_path):
        # cert-manager 1.21.x는 K8s 1.36 지원 → PASS. 단 오래 지난 시점이면 근거 노후를 알린다.
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "cert-manager", "namespace": "cert-manager",
              "chart": "cert-manager-v1.21.0", "app_version": "v1.21.0"}],
            current="1.35", target="1.36", today="2027-06-01")
        assert rc == 0                    # INFO는 게이트를 막지 않는다
        assert "HELM-STALE" in audit

    def test_fresh_registry_has_no_stale_noise(self, tmp_path):
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "cert-manager", "namespace": "cert-manager",
              "chart": "cert-manager-v1.21.0", "app_version": "v1.21.0"}],
            current="1.35", target="1.36", today="2026-08-31")
        assert rc == 0
        assert "HELM-STALE" not in audit

    def test_app_layer_charts_stay_quiet(self, tmp_path):
        # K8s 확장 지점이 없는 앱 계층은 확인 기록만으로 조용히 통과한다
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "keycloak", "namespace": "keycloak",
              "chart": "keycloak-25.2.0", "app_version": "26.3.3"},
             {"name": "locust", "namespace": "locust",
              "chart": "locust-0.31.5", "app_version": "2.15.1"}],
            current="1.35", target="1.36", today="2026-08-31")
        assert rc == 0

    def test_charts_with_coupling_surface_still_warn(self, tmp_path):
        # 반대로 CRD·webhook을 가진 차트는 "문서에 상한이 없더라"로 통과시키지 않는다
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "keda", "namespace": "keda",
              "chart": "keda-2.18.0", "app_version": "2.18.0"}],
            current="1.35", target="1.36", today="2026-08-31")
        assert rc == 2
        assert "확장 지점" in audit


class TestCurrentStateAuditMode:
    """업그레이드 사전 점검 말고도, 차트를 올릴 때가 됐는지 주기적으로 보는 용도가 있다."""

    def test_same_version_is_audit_mode_not_usage_error(self, tmp_path):
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "keycloak", "namespace": "keycloak",
              "chart": "keycloak-25.2.0", "app_version": "26.3.3"}],
            current="1.35", target="1.35", today="2026-08-31")
        assert rc != 64
        assert "상태 점검" in audit

    def test_audit_mode_catches_already_violated_floor(self, tmp_path):
        # K8s를 올리지 않아도 지금 이미 지원 범위 밖이면 잡아야 한다
        rc, audit, out = run_checker(
            tmp_path,
            [{"name": "karpenter", "namespace": "karpenter",
              "chart": "karpenter-1.8.6", "app_version": "1.8.6"}],
            current="1.35", target="1.35", today="2026-08-31")
        assert rc == 1
        assert "1.9 이상" in audit

    def test_downgrade_still_rejected(self, tmp_path):
        rc, _, _ = run_checker(tmp_path, [], current="1.36", target="1.35")
        assert rc == 64
