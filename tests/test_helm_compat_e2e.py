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
