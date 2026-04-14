"""
tests/test_phase_gate.py — phase_gate.py 단위 테스트

Task 4.2: argparse 설정 및 CLI 도구 검증 테스트
- 각 서브커맨드의 필수/선택 인자 파싱 검증
- check_tool_exists 미존재 시 exit 127 검증
- --audit-log 기본값 "audit.log" 검증
"""

import json
import os
import subprocess
import sys
import unittest.mock

import pytest

# ── phase_gate 모듈 import ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'k8s-upgrade-skills', 'scripts'))
import phase_gate


# ══════════════════════════════════════════════════════════════
# 헬퍼: argparse parser 생성 (main() 내부 parser를 재구성)
# ══════════════════════════════════════════════════════════════
def _build_parser():
    """phase_gate.main() 내부와 동일한 argparse 파서를 생성."""
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="phase", required=True)

    p2 = subparsers.add_parser("phase2")
    p2.add_argument("--cluster-name", required=True)
    p2.add_argument("--target-version", required=True)
    p2.add_argument("--audit-log", default="audit.log")

    p3 = subparsers.add_parser("phase3")
    p3.add_argument("--cluster-name", required=True)
    p3.add_argument("--audit-log", default="audit.log")

    p4 = subparsers.add_parser("phase4")
    p4.add_argument("--cluster-name", required=True)
    p4.add_argument("--target-version", required=True)
    p4.add_argument("--audit-log", default="audit.log")

    p5 = subparsers.add_parser("phase5")
    p5.add_argument("--target-version", required=True)
    p5.add_argument("--audit-log", default="audit.log")

    p6 = subparsers.add_parser("phase6")
    p6.add_argument("--tf-dir", required=True)
    p6.add_argument("--audit-log", default="audit.log")

    p7 = subparsers.add_parser("phase7")
    p7.add_argument("--cluster-name", required=True)
    p7.add_argument("--target-version", required=True)
    p7.add_argument("--audit-log", default="audit.log")

    return parser


# ══════════════════════════════════════════════════════════════
# Task 4.2: 서브커맨드 argparse 파싱 테스트
# ══════════════════════════════════════════════════════════════


class TestPhase2Args:
    """phase2 서브커맨드 인자 파싱 검증."""

    def test_phase2_required_args(self):
        parser = _build_parser()
        args = parser.parse_args(["phase2", "--cluster-name", "my-cluster", "--target-version", "1.35"])
        assert args.phase == "phase2"
        assert args.cluster_name == "my-cluster"
        assert args.target_version == "1.35"

    def test_phase2_missing_cluster_name(self):
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["phase2", "--target-version", "1.35"])
        assert exc_info.value.code == 2

    def test_phase2_missing_target_version(self):
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["phase2", "--cluster-name", "my-cluster"])
        assert exc_info.value.code == 2

    def test_phase2_audit_log_default(self):
        parser = _build_parser()
        args = parser.parse_args(["phase2", "--cluster-name", "c", "--target-version", "1.35"])
        assert args.audit_log == "audit.log"

    def test_phase2_audit_log_custom(self):
        parser = _build_parser()
        args = parser.parse_args(["phase2", "--cluster-name", "c", "--target-version", "1.35", "--audit-log", "custom.log"])
        assert args.audit_log == "custom.log"


class TestPhase3Args:
    """phase3 서브커맨드 인자 파싱 검증."""

    def test_phase3_required_args(self):
        parser = _build_parser()
        args = parser.parse_args(["phase3", "--cluster-name", "my-cluster"])
        assert args.phase == "phase3"
        assert args.cluster_name == "my-cluster"

    def test_phase3_missing_cluster_name(self):
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["phase3"])
        assert exc_info.value.code == 2

    def test_phase3_audit_log_default(self):
        parser = _build_parser()
        args = parser.parse_args(["phase3", "--cluster-name", "c"])
        assert args.audit_log == "audit.log"


class TestPhase4Args:
    """phase4 서브커맨드 인자 파싱 검증."""

    def test_phase4_required_args(self):
        parser = _build_parser()
        args = parser.parse_args(["phase4", "--cluster-name", "my-cluster", "--target-version", "1.35"])
        assert args.phase == "phase4"
        assert args.cluster_name == "my-cluster"
        assert args.target_version == "1.35"

    def test_phase4_missing_cluster_name(self):
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["phase4", "--target-version", "1.35"])
        assert exc_info.value.code == 2

    def test_phase4_missing_target_version(self):
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["phase4", "--cluster-name", "c"])
        assert exc_info.value.code == 2

    def test_phase4_audit_log_default(self):
        parser = _build_parser()
        args = parser.parse_args(["phase4", "--cluster-name", "c", "--target-version", "1.35"])
        assert args.audit_log == "audit.log"


class TestPhase5Args:
    """phase5 서브커맨드 인자 파싱 검증."""

    def test_phase5_required_args(self):
        parser = _build_parser()
        args = parser.parse_args(["phase5", "--target-version", "1.35"])
        assert args.phase == "phase5"
        assert args.target_version == "1.35"

    def test_phase5_missing_target_version(self):
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["phase5"])
        assert exc_info.value.code == 2

    def test_phase5_no_cluster_name_arg(self):
        """phase5는 --cluster-name을 받지 않는다."""
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["phase5", "--target-version", "1.35", "--cluster-name", "c"])
        assert exc_info.value.code == 2

    def test_phase5_audit_log_default(self):
        parser = _build_parser()
        args = parser.parse_args(["phase5", "--target-version", "1.35"])
        assert args.audit_log == "audit.log"


class TestPhase6Args:
    """phase6 서브커맨드 인자 파싱 검증."""

    def test_phase6_required_args(self):
        parser = _build_parser()
        args = parser.parse_args(["phase6", "--tf-dir", "/path/to/tf"])
        assert args.phase == "phase6"
        assert args.tf_dir == "/path/to/tf"

    def test_phase6_missing_tf_dir(self):
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["phase6"])
        assert exc_info.value.code == 2

    def test_phase6_audit_log_default(self):
        parser = _build_parser()
        args = parser.parse_args(["phase6", "--tf-dir", "/tmp"])
        assert args.audit_log == "audit.log"


class TestPhase7Args:
    """phase7 서브커맨드 인자 파싱 검증."""

    def test_phase7_required_args(self):
        parser = _build_parser()
        args = parser.parse_args(["phase7", "--cluster-name", "my-cluster", "--target-version", "1.35"])
        assert args.phase == "phase7"
        assert args.cluster_name == "my-cluster"
        assert args.target_version == "1.35"

    def test_phase7_missing_cluster_name(self):
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["phase7", "--target-version", "1.35"])
        assert exc_info.value.code == 2

    def test_phase7_missing_target_version(self):
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["phase7", "--cluster-name", "c"])
        assert exc_info.value.code == 2

    def test_phase7_audit_log_default(self):
        parser = _build_parser()
        args = parser.parse_args(["phase7", "--cluster-name", "c", "--target-version", "1.35"])
        assert args.audit_log == "audit.log"


class TestNoSubcommand:
    """서브커맨드 미제공 시 에러 검증."""

    def test_no_subcommand_exits(self):
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args([])
        assert exc_info.value.code == 2


# ══════════════════════════════════════════════════════════════
# Task 4.2: check_tool_exists 검증
# ══════════════════════════════════════════════════════════════


class TestCheckToolExists:
    """check_tool_exists — CLI 도구 미존재 시 exit 127 검증."""

    def test_missing_tool_exits_127(self):
        """단일 도구 미존재 시 exit 127."""
        with unittest.mock.patch("shutil.which", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                phase_gate.check_tool_exists(["nonexistent-tool"])
            assert exc_info.value.code == 127

    def test_all_tools_present_no_exit(self):
        """모든 도구 존재 시 정상 반환 (exit 없음)."""
        with unittest.mock.patch("shutil.which", return_value="/usr/bin/tool"):
            phase_gate.check_tool_exists(["aws", "kubectl"])

    def test_second_tool_missing_exits_127(self):
        """두 번째 도구만 미존재 시 exit 127."""
        def which_side_effect(tool):
            return "/usr/bin/aws" if tool == "aws" else None

        with unittest.mock.patch("shutil.which", side_effect=which_side_effect):
            with pytest.raises(SystemExit) as exc_info:
                phase_gate.check_tool_exists(["aws", "kubectl"])
            assert exc_info.value.code == 127

    def test_empty_tools_list_no_exit(self):
        """빈 도구 리스트 시 정상 반환."""
        phase_gate.check_tool_exists([])


# ══════════════════════════════════════════════════════════════
# Task 4.2: TOOL_DEPS 매핑 검증
# ══════════════════════════════════════════════════════════════


class TestToolDeps:
    """서브커맨드별 CLI 도구 의존성 매핑 검증."""

    def test_phase2_deps(self):
        assert phase_gate.TOOL_DEPS["phase2"] == ["aws"]

    def test_phase3_deps(self):
        assert phase_gate.TOOL_DEPS["phase3"] == ["aws", "kubectl"]

    def test_phase4_deps(self):
        assert phase_gate.TOOL_DEPS["phase4"] == ["kubectl"]

    def test_phase5_deps(self):
        assert phase_gate.TOOL_DEPS["phase5"] == ["kubectl"]

    def test_phase6_deps(self):
        assert phase_gate.TOOL_DEPS["phase6"] == ["terraform"]

    def test_phase7_deps(self):
        assert phase_gate.TOOL_DEPS["phase7"] == ["aws", "kubectl"]


# ══════════════════════════════════════════════════════════════
# Task 5.1: gate_phase2 단위 테스트
# ══════════════════════════════════════════════════════════════


class TestGatePhase2:
    """gate_phase2 — Phase 2 Control Plane 검증 단위 테스트."""

    def _mock_run_cmd(self, status: str, version: str, returncode: int = 0):
        """run_cmd mock 생성: aws eks describe-cluster 응답."""
        import json as _json
        import subprocess

        stdout = _json.dumps({"cluster": {"status": status, "version": version}})
        return unittest.mock.patch(
            "phase_gate.run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=returncode, stdout=stdout, stderr=""
            ),
        )

    def test_active_matching_version_returns_0(self, tmp_path):
        """ACTIVE + 버전 일치 → exit 0."""
        audit = str(tmp_path / "audit.log")
        with self._mock_run_cmd("ACTIVE", "1.35"):
            rc = phase_gate.gate_phase2("my-cluster", "1.35", audit)
        assert rc == 0

    def test_active_mismatched_version_returns_1(self, tmp_path):
        """ACTIVE + 버전 불일치 → exit 1."""
        audit = str(tmp_path / "audit.log")
        with self._mock_run_cmd("ACTIVE", "1.34"):
            rc = phase_gate.gate_phase2("my-cluster", "1.35", audit)
        assert rc == 1

    def test_updating_status_returns_1(self, tmp_path):
        """UPDATING 상태 → exit 1."""
        audit = str(tmp_path / "audit.log")
        with self._mock_run_cmd("UPDATING", "1.35"):
            rc = phase_gate.gate_phase2("my-cluster", "1.35", audit)
        assert rc == 1

    def test_aws_cli_failure_returns_1(self, tmp_path):
        """aws eks describe-cluster 실패 → exit 1."""
        import subprocess

        audit = str(tmp_path / "audit.log")
        with unittest.mock.patch(
            "phase_gate.run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error"
            ),
        ):
            rc = phase_gate.gate_phase2("my-cluster", "1.35", audit)
        assert rc == 1

    def test_invalid_json_returns_1(self, tmp_path):
        """JSON 파싱 실패 → exit 1."""
        import subprocess

        audit = str(tmp_path / "audit.log")
        with unittest.mock.patch(
            "phase_gate.run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="not-json", stderr=""
            ),
        ):
            rc = phase_gate.gate_phase2("my-cluster", "1.35", audit)
        assert rc == 1

    def test_audit_log_written_on_pass(self, tmp_path):
        """PASS 시 audit.log에 PHASE2-CP PASS 기록."""
        audit = str(tmp_path / "audit.log")
        with self._mock_run_cmd("ACTIVE", "1.35"):
            phase_gate.gate_phase2("my-cluster", "1.35", audit)
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE2-CP" in content
        assert "PASS" in content

    def test_audit_log_written_on_fail(self, tmp_path):
        """FAIL 시 audit.log에 PHASE2-CP FAIL 기록."""
        audit = str(tmp_path / "audit.log")
        with self._mock_run_cmd("FAILED", "1.34"):
            phase_gate.gate_phase2("my-cluster", "1.35", audit)
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE2-CP" in content
        assert "FAIL" in content

    def test_missing_cluster_key_returns_1(self, tmp_path):
        """JSON에 cluster 키 없음 → exit 1 (빈 status/version)."""
        import json as _json
        import subprocess

        audit = str(tmp_path / "audit.log")
        with unittest.mock.patch(
            "phase_gate.run_cmd",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=_json.dumps({}), stderr=""
            ),
        ):
            rc = phase_gate.gate_phase2("my-cluster", "1.35", audit)
        assert rc == 1


# ══════════════════════════════════════════════════════════════
# Task 5.2: Phase 2 Property-Based Test (Property 1)
# ══════════════════════════════════════════════════════════════

from hypothesis import given, settings
import hypothesis.strategies as st


# Feature: phase-gate-scripts, Property 1: Phase 2 Control Plane gate correctness
class TestPhase2Property:
    """Property 1: gate_phase2 returns 0 iff status==ACTIVE and version==target_version.

    **Validates: Requirements 2.2, 2.3**
    """

    @given(
        status=st.sampled_from(["ACTIVE", "UPDATING", "FAILED", "CREATING", "DELETING"]),
        cluster_version=st.from_regex(r"\d+\.\d+", fullmatch=True),
        target_version=st.from_regex(r"\d+\.\d+", fullmatch=True),
    )
    @settings(max_examples=200)
    def test_phase2_gate_correctness(self, status, cluster_version, target_version):
        """Property 1: gate_phase2 returns 0 iff status==ACTIVE and version==target_version."""
        import json
        import subprocess
        import tempfile

        # Mock run_cmd to return the generated status/version
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"cluster": {"status": status, "version": cluster_version}}),
            stderr="",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            audit_log = os.path.join(tmpdir, "audit.log")

            with unittest.mock.patch("phase_gate.run_cmd", return_value=mock_result):
                rc = phase_gate.gate_phase2("test-cluster", target_version, audit_log)

        expected = 0 if (status == "ACTIVE" and cluster_version == target_version) else 1
        assert rc == expected, (
            f"status={status}, cluster_version={cluster_version}, "
            f"target_version={target_version}: expected {expected}, got {rc}"
        )


# ══════════════════════════════════════════════════════════════
# Task 5.3: gate_phase3 단위 테스트
# ══════════════════════════════════════════════════════════════


class TestGatePhase3:
    """gate_phase3 — Phase 3 Add-on + kube-system Pod 검증 단위 테스트."""

    @staticmethod
    def _make_list_addons_result(addons: list, returncode: int = 0):
        """aws eks list-addons mock 결과 생성."""
        import subprocess
        stdout = json.dumps({"addons": addons}) if returncode == 0 else ""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=""
        )

    @staticmethod
    def _make_describe_addon_result(status: str, returncode: int = 0):
        """aws eks describe-addon mock 결과 생성."""
        import subprocess
        stdout = json.dumps({"addon": {"status": status}}) if returncode == 0 else ""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=""
        )

    @staticmethod
    def _make_pods_result(pods: list, returncode: int = 0):
        """kubectl get pods mock 결과 생성."""
        import subprocess
        stdout = json.dumps({"items": pods}) if returncode == 0 else ""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=""
        )

    @staticmethod
    def _running_ready_pod(name: str) -> dict:
        """Running + Ready=True Pod 객체 생성."""
        return {
            "metadata": {"name": name},
            "status": {
                "phase": "Running",
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        }

    @staticmethod
    def _unhealthy_pod(name: str, phase: str = "Pending", ready: bool = False) -> dict:
        """비정상 Pod 객체 생성."""
        conditions = [{"type": "Ready", "status": "True" if ready else "False"}]
        return {
            "metadata": {"name": name},
            "status": {"phase": phase, "conditions": conditions},
        }

    def test_all_addons_active_all_pods_ready_returns_0(self, tmp_path):
        """모든 Add-on ACTIVE + 모든 Pod Running+Ready → exit 0."""
        audit = str(tmp_path / "audit.log")
        addons = ["vpc-cni", "coredns", "kube-proxy"]
        pods = [self._running_ready_pod("coredns-abc"), self._running_ready_pod("kube-proxy-xyz")]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "list-addons" in cmd:
                return self._make_list_addons_result(addons)
            if "describe-addon" in cmd:
                return self._make_describe_addon_result("ACTIVE")
            if "kubectl" in cmd:
                return self._make_pods_result(pods)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        import subprocess
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase3("my-cluster", audit)
        assert rc == 0

    def test_one_addon_degraded_returns_1(self, tmp_path):
        """하나의 Add-on DEGRADED → exit 1."""
        audit = str(tmp_path / "audit.log")
        addons = ["vpc-cni", "coredns"]
        pods = [self._running_ready_pod("coredns-abc")]

        call_count = {"describe": 0}

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "list-addons" in cmd:
                return self._make_list_addons_result(addons)
            if "describe-addon" in cmd:
                call_count["describe"] += 1
                status = "ACTIVE" if call_count["describe"] == 1 else "DEGRADED"
                return self._make_describe_addon_result(status)
            if "kubectl" in cmd:
                return self._make_pods_result(pods)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        import subprocess
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase3("my-cluster", audit)
        assert rc == 1

    def test_pod_not_running_returns_1(self, tmp_path):
        """kube-system Pod가 Running이 아닌 경우 → exit 1."""
        audit = str(tmp_path / "audit.log")
        addons = ["vpc-cni"]
        pods = [self._running_ready_pod("coredns-abc"), self._unhealthy_pod("bad-pod", "Pending")]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "list-addons" in cmd:
                return self._make_list_addons_result(addons)
            if "describe-addon" in cmd:
                return self._make_describe_addon_result("ACTIVE")
            if "kubectl" in cmd:
                return self._make_pods_result(pods)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        import subprocess
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase3("my-cluster", audit)
        assert rc == 1

    def test_pod_running_but_not_ready_returns_1(self, tmp_path):
        """Pod Running이지만 Ready=False → exit 1."""
        audit = str(tmp_path / "audit.log")
        addons = ["vpc-cni"]
        pods = [self._unhealthy_pod("not-ready-pod", "Running", ready=False)]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "list-addons" in cmd:
                return self._make_list_addons_result(addons)
            if "describe-addon" in cmd:
                return self._make_describe_addon_result("ACTIVE")
            if "kubectl" in cmd:
                return self._make_pods_result(pods)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        import subprocess
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase3("my-cluster", audit)
        assert rc == 1

    def test_list_addons_failure_returns_1(self, tmp_path):
        """aws eks list-addons 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")
        import subprocess
        with unittest.mock.patch(
            "phase_gate.run_cmd",
            return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error"),
        ):
            rc = phase_gate.gate_phase3("my-cluster", audit)
        assert rc == 1

    def test_list_addons_invalid_json_returns_1(self, tmp_path):
        """list-addons JSON 파싱 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")
        import subprocess
        with unittest.mock.patch(
            "phase_gate.run_cmd",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="not-json", stderr=""),
        ):
            rc = phase_gate.gate_phase3("my-cluster", audit)
        assert rc == 1

    def test_kubectl_pods_failure_returns_1(self, tmp_path):
        """kubectl get pods 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")
        addons = ["vpc-cni"]

        call_count = {"n": 0}

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "list-addons" in cmd:
                return self._make_list_addons_result(addons)
            if "describe-addon" in cmd:
                return self._make_describe_addon_result("ACTIVE")
            if "kubectl" in cmd:
                return self._make_pods_result([], returncode=1)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        import subprocess
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase3("my-cluster", audit)
        assert rc == 1

    def test_empty_addons_and_pods_returns_0(self, tmp_path):
        """Add-on 0개 + Pod 0개 → exit 0."""
        audit = str(tmp_path / "audit.log")

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "list-addons" in cmd:
                return self._make_list_addons_result([])
            if "kubectl" in cmd:
                return self._make_pods_result([])
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        import subprocess
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase3("my-cluster", audit)
        assert rc == 0

    def test_audit_log_contains_phase3_addon(self, tmp_path):
        """audit.log에 PHASE3-ADDON 식별자 기록 확인."""
        audit = str(tmp_path / "audit.log")
        addons = ["vpc-cni"]
        pods = [self._running_ready_pod("coredns-abc")]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "list-addons" in cmd:
                return self._make_list_addons_result(addons)
            if "describe-addon" in cmd:
                return self._make_describe_addon_result("ACTIVE")
            if "kubectl" in cmd:
                return self._make_pods_result(pods)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        import subprocess
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            phase_gate.gate_phase3("my-cluster", audit)
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE3-ADDON" in content

    def test_bad_addon_and_bad_pod_both_reported(self, tmp_path):
        """Add-on FAIL + Pod FAIL 모두 보고, exit 1."""
        audit = str(tmp_path / "audit.log")
        addons = ["vpc-cni"]
        pods = [self._unhealthy_pod("bad-pod", "CrashLoopBackOff")]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "list-addons" in cmd:
                return self._make_list_addons_result(addons)
            if "describe-addon" in cmd:
                return self._make_describe_addon_result("DEGRADED")
            if "kubectl" in cmd:
                return self._make_pods_result(pods)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        import subprocess
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase3("my-cluster", audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        # Both addon and pod failures should be in audit
        assert "PHASE3-ADDON" in content
        assert "FAIL" in content

    def test_describe_addon_failure_marks_addon_bad(self, tmp_path):
        """describe-addon 호출 실패 시 해당 addon을 비정상으로 처리."""
        audit = str(tmp_path / "audit.log")
        addons = ["vpc-cni"]
        pods = [self._running_ready_pod("coredns-abc")]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "list-addons" in cmd:
                return self._make_list_addons_result(addons)
            if "describe-addon" in cmd:
                return self._make_describe_addon_result("", returncode=1)
            if "kubectl" in cmd:
                return self._make_pods_result(pods)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        import subprocess
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase3("my-cluster", audit)
        assert rc == 1


# ══════════════════════════════════════════════════════════════
# Task 5.4: Phase 3 Property-Based Test (Property 2)
# ══════════════════════════════════════════════════════════════


# Feature: phase-gate-scripts, Property 2: Phase 3 Add-on gate correctness
class TestPhase3Property:
    """Property 2: gate_phase3 returns 0 iff all addon statuses are ACTIVE
    and all kube-system pods are Running with Ready=True.

    **Validates: Requirements 3.2, 3.3, 3.4, 3.5**
    """

    @given(
        addon_statuses=st.lists(
            st.tuples(
                st.text(
                    min_size=1,
                    max_size=20,
                    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
                ),
                st.sampled_from([
                    "ACTIVE", "DEGRADED", "CREATE_FAILED", "UPDATE_FAILED",
                    "DELETE_FAILED", "CREATING", "UPDATING", "DELETING",
                ]),
            ),
            min_size=0,
            max_size=5,
        ).filter(
            lambda addons: len({name for name, _ in addons}) == len(addons)  # unique names
        ),
        pod_states=st.lists(
            st.tuples(
                st.sampled_from(["Running", "Pending", "Failed", "Succeeded", "Unknown"]),
                st.booleans(),  # Ready condition
            ),
            min_size=0,
            max_size=5,
        ),
    )
    @settings(max_examples=200)
    def test_phase3_gate_correctness(self, addon_statuses, pod_states):
        """Property 2: gate_phase3 returns 0 iff all addon statuses are ACTIVE
        and all pods Running with Ready=True."""
        import subprocess
        import tempfile

        addon_names = [name for name, _ in addon_statuses]
        addon_status_map = {name: status for name, status in addon_statuses}

        # Build pod items for kubectl response
        pod_items = []
        for i, (phase, ready) in enumerate(pod_states):
            pod_items.append({
                "metadata": {"name": f"pod-{i}"},
                "status": {
                    "phase": phase,
                    "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
                },
            })

        # Track call sequence to route mock responses
        call_seq = {"idx": 0}

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            call_seq["idx"] += 1

            if "list-addons" in cmd:
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"addons": addon_names}), stderr="",
                )
            if "describe-addon" in cmd:
                # Extract addon name from args: ... --addon-name <name> ...
                addon_name = args[args.index("--addon-name") + 1]
                status = addon_status_map.get(addon_name, "ACTIVE")
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"addon": {"status": status}}), stderr="",
                )
            if "kubectl" in cmd:
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"items": pod_items}), stderr="",
                )
            return subprocess.CompletedProcess(
                args=args, returncode=1, stdout="", stderr="unknown cmd",
            )

        # Determine expected result
        all_addons_active = all(status == "ACTIVE" for _, status in addon_statuses)
        all_pods_healthy = all(
            phase == "Running" and ready
            for phase, ready in pod_states
        )
        expected = 0 if (all_addons_active and all_pods_healthy) else 1

        with tempfile.TemporaryDirectory() as tmpdir:
            audit_log = os.path.join(tmpdir, "audit.log")
            with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
                rc = phase_gate.gate_phase3("test-cluster", audit_log)

        assert rc == expected, (
            f"addon_statuses={addon_statuses}, pod_states={pod_states}: "
            f"expected {expected}, got {rc}"
        )


# ══════════════════════════════════════════════════════════════
# Task 6.1: gate_phase4 단위 테스트 — 노드 버전 + FailedEvict
# ══════════════════════════════════════════════════════════════


class TestGatePhase4NodeAndEvents:
    """gate_phase4 — 노드 버전 확인 + FailedEvict 이벤트 검증."""

    @staticmethod
    def _make_node(name: str, kubelet_version: str, ready: str = "True") -> dict:
        """노드 JSON 객체 생성."""
        return {
            "metadata": {"name": name},
            "status": {
                "nodeInfo": {"kubeletVersion": kubelet_version},
                "conditions": [{"type": "Ready", "status": ready}],
            },
        }

    @staticmethod
    def _make_nodes_result(nodes: list, returncode: int = 0):
        """kubectl get nodes mock 결과 생성."""
        stdout = json.dumps({"items": nodes}) if returncode == 0 else ""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=""
        )

    @staticmethod
    def _make_events_result(events: list, returncode: int = 0):
        """kubectl get events mock 결과 생성."""
        stdout = json.dumps({"items": events}) if returncode == 0 else ""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=""
        )

    @staticmethod
    def _make_event(namespace: str, message: str) -> dict:
        """FailedEvict 이벤트 JSON 객체 생성."""
        return {
            "metadata": {"namespace": namespace},
            "reason": "FailedEvict",
            "message": message,
        }

    @staticmethod
    def _make_pods_result(pods: list, returncode: int = 0):
        """kubectl get pods mock 결과 생성."""
        stdout = json.dumps({"items": pods}) if returncode == 0 else ""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=""
        )

    def _build_side_effect(self, nodes_result, events_result, pods_result=None):
        """run_cmd side_effect 생성: nodes → events → pods 순서."""
        if pods_result is None:
            pods_result = self._make_pods_result([])
        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "nodes" in cmd:
                return nodes_result
            if "get" in cmd and "events" in cmd:
                return events_result
            if "get" in cmd and "pods" in cmd:
                return pods_result
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        return side_effect

    def test_all_nodes_matching_version_ready_no_events_returns_0(self, tmp_path):
        """모든 노드 버전 일치 + Ready + FailedEvict 없음 → exit 0."""
        audit = str(tmp_path / "audit.log")
        nodes = [
            self._make_node("node-1", "v1.35.0"),
            self._make_node("node-2", "v1.35.1-eks-abc123"),
        ]
        se = self._build_side_effect(
            self._make_nodes_result(nodes),
            self._make_events_result([]),
        )
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 0

    def test_node_version_mismatch_returns_1(self, tmp_path):
        """노드 버전 불일치 → exit 1."""
        audit = str(tmp_path / "audit.log")
        nodes = [
            self._make_node("node-1", "v1.35.0"),
            self._make_node("node-2", "v1.34.5"),
        ]
        se = self._build_side_effect(
            self._make_nodes_result(nodes),
            self._make_events_result([]),
        )
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 1

    def test_node_not_ready_returns_1(self, tmp_path):
        """노드 NotReady → exit 1."""
        audit = str(tmp_path / "audit.log")
        nodes = [
            self._make_node("node-1", "v1.35.0", ready="True"),
            self._make_node("node-2", "v1.35.0", ready="False"),
        ]
        se = self._build_side_effect(
            self._make_nodes_result(nodes),
            self._make_events_result([]),
        )
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 1

    def test_failed_evict_events_returns_1(self, tmp_path):
        """FailedEvict 이벤트 존재 → exit 1."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]
        events = [self._make_event("workload", "Cannot evict pod: pdb-blocked")]
        se = self._build_side_effect(
            self._make_nodes_result(nodes),
            self._make_events_result(events),
        )
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 1

    def test_kubectl_get_nodes_failure_returns_1(self, tmp_path):
        """kubectl get nodes 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")
        with unittest.mock.patch(
            "phase_gate.run_cmd",
            return_value=subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error"),
        ):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 1

    def test_nodes_invalid_json_returns_1(self, tmp_path):
        """노드 JSON 파싱 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")
        with unittest.mock.patch(
            "phase_gate.run_cmd",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="not-json", stderr=""),
        ):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 1

    def test_empty_nodes_no_events_returns_0(self, tmp_path):
        """노드 0개 + FailedEvict 없음 → exit 0."""
        audit = str(tmp_path / "audit.log")
        se = self._build_side_effect(
            self._make_nodes_result([]),
            self._make_events_result([]),
        )
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 0

    def test_eks_version_suffix_matches(self, tmp_path):
        """EKS 스타일 버전 (v1.35.1-eks-abc) 매칭 확인."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.1-eks-abc123")]
        se = self._build_side_effect(
            self._make_nodes_result(nodes),
            self._make_events_result([]),
        )
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 0

    def test_audit_log_contains_phase4_dataplane(self, tmp_path):
        """audit.log에 PHASE4-DATAPLANE 식별자 기록 확인."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]
        se = self._build_side_effect(
            self._make_nodes_result(nodes),
            self._make_events_result([]),
        )
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            phase_gate.gate_phase4("my-cluster", "1.35", audit)
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE4-DATAPLANE" in content

    def test_multiple_failed_evict_events_reported(self, tmp_path):
        """여러 FailedEvict 이벤트 → 상세 보고."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]
        events = [
            self._make_event("ns-a", "Cannot evict pod-a"),
            self._make_event("ns-b", "Cannot evict pod-b"),
        ]
        se = self._build_side_effect(
            self._make_nodes_result(nodes),
            self._make_events_result(events),
        )
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "FailedEvict" in content

    def test_events_cmd_failure_still_passes(self, tmp_path):
        """kubectl get events 실패 시에도 Pod 분류로 진행 (all clear → exit 0)."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "nodes" in cmd:
                return self._make_nodes_result(nodes)
            if "get" in cmd and "events" in cmd:
                return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
            if "get" in cmd and "pods" in cmd:
                return self._make_pods_result([])
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 0

    def test_version_with_special_regex_chars(self, tmp_path):
        """target_version에 regex 특수문자가 포함된 경우 re.escape 동작 확인."""
        audit = str(tmp_path / "audit.log")
        # 비현실적이지만 re.escape 동작 검증
        nodes = [self._make_node("node-1", "v1.35.0")]
        se = self._build_side_effect(
            self._make_nodes_result(nodes),
            self._make_events_result([]),
        )
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 0



# ══════════════════════════════════════════════════════════════
# Task 6.5: gate_phase4 Pod 분류 exit code 통합 테스트
# ══════════════════════════════════════════════════════════════


class TestGatePhase4PodClassification:
    """gate_phase4 — Pod 분류 결과에 따른 exit code 검증."""

    @staticmethod
    def _make_node(name: str, kubelet_version: str, ready: str = "True",
                   creation_ts: str = "2025-01-15T09:00:00Z") -> dict:
        return {
            "metadata": {"name": name, "creationTimestamp": creation_ts},
            "status": {
                "nodeInfo": {"kubeletVersion": kubelet_version},
                "conditions": [{"type": "Ready", "status": ready}],
            },
        }

    @staticmethod
    def _make_nodes_result(nodes: list):
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"items": nodes}), stderr=""
        )

    @staticmethod
    def _make_events_result(events: list):
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"items": events}), stderr=""
        )

    @staticmethod
    def _make_pods_result(pods: list, returncode: int = 0):
        stdout = json.dumps({"items": pods}) if returncode == 0 else ""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=""
        )

    def _build_side_effect(self, nodes, events, pods):
        nodes_r = self._make_nodes_result(nodes)
        events_r = self._make_events_result(events)
        pods_r = self._make_pods_result(pods)
        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "nodes" in cmd:
                return nodes_r
            if "get" in cmd and "events" in cmd:
                return events_r
            if "get" in cmd and "pods" in cmd:
                return pods_r
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        return side_effect

    def test_blocking_pod_returns_1(self, tmp_path):
        """BLOCKING Pod 존재 → exit 1."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]
        pods = [{
            "metadata": {"name": "crash-pod", "namespace": "default",
                         "creationTimestamp": "2025-01-15T09:00:00Z"},
            "spec": {},
            "status": {
                "phase": "Pending",
                "containerStatuses": [{"state": {"waiting": {"reason": "CrashLoopBackOff"}}}],
            },
        }]
        se = self._build_side_effect(nodes, [], pods)
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "BLOCKING" in content

    def test_stale_only_returns_2(self, tmp_path):
        """STALE Pod만 존재 → exit 2 (WARN)."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]
        pods = [
            {
                "metadata": {"name": "running-pod", "namespace": "default",
                             "ownerReferences": [{"uid": "owner-1", "name": "rs-1"}]},
                "spec": {},
                "status": {"phase": "Running"},
            },
            {
                "metadata": {"name": "stale-pod", "namespace": "default",
                             "ownerReferences": [{"uid": "owner-1", "name": "rs-1"}]},
                "spec": {},
                "status": {"phase": "Error"},
            },
        ]
        se = self._build_side_effect(nodes, [], pods)
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 2
        content = (tmp_path / "audit.log").read_text()
        assert "STALE" in content
        assert "삭제 필요" in content

    def test_transient_only_returns_2(self, tmp_path):
        """TRANSIENT Pod만 존재 → exit 2 (WARN)."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]
        pods = [
            {"metadata": {"name": "transient-pod", "namespace": "default"},
             "spec": {"nodeName": "node-1"},
             "status": {"phase": "Pending"}},
        ]
        se = self._build_side_effect(nodes, [], pods)
        # Mock classify_pods to return a known TRANSIENT result
        mock_classification = phase_gate.PodClassification(
            transient=[{"ns": "default", "name": "transient-pod", "node": "node-1", "node_age_sec": 60}],
            stale=[],
            blocking=[],
        )
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            with unittest.mock.patch("phase_gate.classify_pods", return_value=mock_classification):
                rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 2
        content = (tmp_path / "audit.log").read_text()
        assert "TRANSIENT" in content
        assert "재확인 필요" in content

    def test_all_pods_healthy_returns_0(self, tmp_path):
        """모든 Pod Running/Succeeded → exit 0."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]
        pods = [
            {"metadata": {"name": "p1", "namespace": "default"}, "spec": {},
             "status": {"phase": "Running"}},
            {"metadata": {"name": "p2", "namespace": "default"}, "spec": {},
             "status": {"phase": "Succeeded"}},
        ]
        se = self._build_side_effect(nodes, [], pods)
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 0
        content = (tmp_path / "audit.log").read_text()
        assert "unhealthy Pod 없음" in content

    def test_kubectl_get_pods_failure_returns_1(self, tmp_path):
        """kubectl get pods 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "nodes" in cmd:
                return self._make_nodes_result(nodes)
            if "get" in cmd and "events" in cmd:
                return self._make_events_result([])
            if "get" in cmd and "pods" in cmd:
                return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "Pod 조회 실패" in content or "kubectl get pods 실패" in content

    def test_pods_invalid_json_returns_1(self, tmp_path):
        """Pod JSON 파싱 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "nodes" in cmd:
                return self._make_nodes_result(nodes)
            if "get" in cmd and "events" in cmd:
                return self._make_events_result([])
            if "get" in cmd and "pods" in cmd:
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="not-json", stderr="")
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 1

    def test_blocking_takes_priority_over_stale(self, tmp_path):
        """BLOCKING + STALE 동시 존재 → exit 1 (BLOCKING 우선)."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]
        pods = [
            # Running sibling for stale check
            {"metadata": {"name": "running-pod", "namespace": "default",
                          "ownerReferences": [{"uid": "uid-1", "name": "rs-1"}]},
             "spec": {}, "status": {"phase": "Running"}},
            # STALE pod
            {"metadata": {"name": "stale-pod", "namespace": "default",
                          "ownerReferences": [{"uid": "uid-1", "name": "rs-1"}]},
             "spec": {}, "status": {"phase": "Error"}},
            # BLOCKING pod
            {"metadata": {"name": "crash-pod", "namespace": "default",
                          "creationTimestamp": "2025-01-15T09:00:00Z"},
             "spec": {},
             "status": {"phase": "Pending",
                        "containerStatuses": [{"state": {"waiting": {"reason": "ImagePullBackOff"}}}]}},
        ]
        se = self._build_side_effect(nodes, [], pods)
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            rc = phase_gate.gate_phase4("my-cluster", "1.35", audit)
        assert rc == 1

    def test_audit_log_phase4_dataplane_identifier(self, tmp_path):
        """Pod 분류 결과가 PHASE4-DATAPLANE 식별자로 audit에 기록."""
        audit = str(tmp_path / "audit.log")
        nodes = [self._make_node("node-1", "v1.35.0")]
        pods = []
        se = self._build_side_effect(nodes, [], pods)
        with unittest.mock.patch("phase_gate.run_cmd", side_effect=se):
            phase_gate.gate_phase4("my-cluster", "1.35", audit)
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE4-DATAPLANE" in content


# ══════════════════════════════════════════════════════════════
# Task 6.2: Phase 4 Property-Based Test — Node Version Check (Property 3)
# ══════════════════════════════════════════════════════════════


# Feature: phase-gate-scripts, Property 3: Node version check correctness
class TestNodeVersionProperty:
    """Property 3: Node version check passes iff every node's kubelet version
    matches v{TARGET_VERSION}.* and every node's Ready condition is "True".

    **Validates: Requirements 4.2, 4.3**
    """

    @given(
        nodes=st.lists(
            st.tuples(
                st.from_regex(r"v\d+\.\d+\.\d+(-eks-[a-z0-9]+)?", fullmatch=True),  # kubelet version
                st.sampled_from(["True", "False"]),  # Ready condition
            ),
            min_size=0,
            max_size=5,
        ),
        target_version=st.from_regex(r"\d+\.\d+", fullmatch=True),
    )
    @settings(max_examples=200)
    def test_node_version_check_correctness(self, nodes, target_version):
        """Property 3: gate_phase4 node check passes iff all nodes match
        v{target_version}.* and Ready=='True'."""
        import re
        import subprocess
        import tempfile

        # Build node JSON objects
        node_items = []
        for i, (kubelet_ver, ready) in enumerate(nodes):
            node_items.append({
                "metadata": {"name": f"node-{i}"},
                "status": {
                    "nodeInfo": {"kubeletVersion": kubelet_ver},
                    "conditions": [{"type": "Ready", "status": ready}],
                },
            })

        # Mock run_cmd: nodes query → generated nodes, events query → empty, pods query → empty
        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "nodes" in cmd:
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"items": node_items}), stderr="",
                )
            if "get" in cmd and "events" in cmd:
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"items": []}), stderr="",
                )
            if "get" in cmd and "pods" in cmd:
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"items": []}), stderr="",
                )
            return subprocess.CompletedProcess(
                args=args, returncode=1, stdout="", stderr="unknown cmd",
            )

        # Compute expected: pass iff all nodes match version pattern AND Ready
        version_pattern = re.compile(rf"v{re.escape(target_version)}\.")
        all_ok = all(
            version_pattern.match(kubelet_ver) and ready == "True"
            for kubelet_ver, ready in nodes
        )
        expected = 0 if all_ok else 1

        with tempfile.TemporaryDirectory() as tmpdir:
            audit_log = os.path.join(tmpdir, "audit.log")
            with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
                rc = phase_gate.gate_phase4("test-cluster", target_version, audit_log)

        assert rc == expected, (
            f"nodes={nodes}, target_version={target_version}: "
            f"expected {expected}, got {rc}"
        )


# ══════════════════════════════════════════════════════════════
# Task 6.3: classify_pods 단위 테스트
# ══════════════════════════════════════════════════════════════
from datetime import datetime, timezone, timedelta


class TestClassifyPods:
    """classify_pods 함수의 TRANSIENT → STALE → BLOCKING 분류 로직 검증."""

    @staticmethod
    def _make_pod(name, ns="default", phase="Pending", node_name="",
                  creation_ts="", owner_uid="", owner_name="",
                  container_waiting_reason=""):
        """테스트용 Pod JSON 객체 생성 헬퍼."""
        pod = {
            "metadata": {"name": name, "namespace": ns},
            "spec": {},
            "status": {"phase": phase},
        }
        if node_name:
            pod["spec"]["nodeName"] = node_name
        if creation_ts:
            pod["metadata"]["creationTimestamp"] = creation_ts
        if owner_uid:
            pod["metadata"]["ownerReferences"] = [{"uid": owner_uid, "name": owner_name or "owner"}]
        if container_waiting_reason:
            pod["status"]["containerStatuses"] = [{
                "state": {"waiting": {"reason": container_waiting_reason}},
            }]
        return pod

    @staticmethod
    def _make_node(name, creation_ts):
        """테스트용 Node JSON 객체 생성 헬퍼."""
        return {
            "metadata": {"name": name, "creationTimestamp": creation_ts},
        }

    def test_empty_pods_returns_empty_classification(self):
        result = phase_gate.classify_pods({"items": []}, {"items": []})
        assert result.transient == []
        assert result.stale == []
        assert result.blocking == []

    def test_running_and_succeeded_pods_are_skipped(self):
        pods = {"items": [
            self._make_pod("p1", phase="Running"),
            self._make_pod("p2", phase="Succeeded"),
        ]}
        result = phase_gate.classify_pods(pods, {"items": []})
        assert result.transient == []
        assert result.stale == []
        assert result.blocking == []

    def test_running_pod_with_not_ready_container_blocking(self):
        """Running Pod에 NotReady 컨테이너가 있고 5분 초과 → BLOCKING."""
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        pod_ts = (now - timedelta(minutes=10)).isoformat()
        pod = {
            "metadata": {"name": "bad-pod", "namespace": "workload",
                         "creationTimestamp": pod_ts},
            "spec": {"nodeName": "node-1"},
            "status": {
                "phase": "Running",
                "containerStatuses": [
                    {"name": "app", "ready": True},
                    {"name": "sidecar", "ready": False},
                ],
            },
        }
        pods = {"items": [pod]}
        result = phase_gate.classify_pods(pods, {"items": []}, now=now)
        assert len(result.blocking) == 1
        assert result.blocking[0]["ns"] == "workload"
        assert "sidecar" in result.blocking[0]["reason"]

    def test_running_pod_with_not_ready_container_transient(self):
        """Running Pod에 NotReady 컨테이너가 있지만 2분 미만 → TRANSIENT."""
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        pod_ts = (now - timedelta(seconds=90)).isoformat()
        pod = {
            "metadata": {"name": "new-pod", "namespace": "workload",
                         "creationTimestamp": pod_ts},
            "spec": {"nodeName": "node-1"},
            "status": {
                "phase": "Running",
                "containerStatuses": [
                    {"name": "app", "ready": False},
                ],
            },
        }
        pods = {"items": [pod]}
        result = phase_gate.classify_pods(pods, {"items": []}, now=now)
        assert len(result.transient) == 1
        assert result.transient[0]["name"] == "new-pod"
        assert result.blocking == []

    def test_running_pod_all_ready_skipped(self):
        """Running Pod의 모든 컨테이너가 ready → skip (기존 동작 유지)."""
        pod = {
            "metadata": {"name": "ok-pod", "namespace": "default",
                         "creationTimestamp": "2025-01-15T09:50:00Z"},
            "spec": {"nodeName": "node-1"},
            "status": {
                "phase": "Running",
                "containerStatuses": [
                    {"name": "app", "ready": True},
                    {"name": "sidecar", "ready": True},
                ],
            },
        }
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        result = phase_gate.classify_pods({"items": [pod]}, {"items": []}, now=now)
        assert result.transient == []
        assert result.stale == []
        assert result.blocking == []

    def test_running_pod_grace_period_not_classified(self):
        """Running Pod NotReady 3~5분 사이 → grace period로 분류하지 않음."""
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        pod_ts = (now - timedelta(minutes=4)).isoformat()
        pod = {
            "metadata": {"name": "grace-pod", "namespace": "workload",
                         "creationTimestamp": pod_ts},
            "spec": {"nodeName": "node-1"},
            "status": {
                "phase": "Running",
                "containerStatuses": [{"name": "app", "ready": False}],
            },
        }
        result = phase_gate.classify_pods({"items": [pod]}, {"items": []}, now=now)
        assert result.transient == []
        assert result.blocking == []

    def test_transient_pending_on_young_node(self):
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        node_ts = (now - timedelta(seconds=60)).isoformat()  # 1분 전 생성
        pods = {"items": [
            self._make_pod("p1", phase="Pending", node_name="node-1"),
        ]}
        nodes = {"items": [self._make_node("node-1", node_ts)]}
        result = phase_gate.classify_pods(pods, nodes, now=now)
        assert len(result.transient) == 1
        assert result.transient[0]["name"] == "p1"
        assert result.transient[0]["node"] == "node-1"
        assert result.transient[0]["node_age_sec"] == 60
        assert result.blocking == []

    def test_transient_excludes_blocking(self):
        """TRANSIENT으로 분류된 Pod는 Pending > 5min이어도 BLOCKING에 포함되지 않는다."""
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        node_ts = (now - timedelta(seconds=120)).isoformat()  # 노드 2분 전 생성 (< 3min)
        pod_ts = (now - timedelta(minutes=10)).isoformat()    # Pod 10분 전 생성 (> 5min)
        pods = {"items": [
            self._make_pod("p1", phase="Pending", node_name="node-1", creation_ts=pod_ts),
        ]}
        nodes = {"items": [self._make_node("node-1", node_ts)]}
        result = phase_gate.classify_pods(pods, nodes, now=now)
        assert len(result.transient) == 1
        assert result.blocking == []

    def test_stale_error_pod_with_running_sibling(self):
        pods = {"items": [
            self._make_pod("p-running", phase="Running", owner_uid="owner-1"),
            self._make_pod("p-error", phase="Error", owner_uid="owner-1", owner_name="my-rs"),
        ]}
        result = phase_gate.classify_pods(pods, {"items": []})
        assert len(result.stale) == 1
        assert result.stale[0]["name"] == "p-error"
        assert result.stale[0]["owner"] == "my-rs"
        assert result.stale[0]["phase"] == "Error"

    def test_stale_failed_pod_with_running_sibling(self):
        pods = {"items": [
            self._make_pod("p-running", phase="Running", owner_uid="uid-abc"),
            self._make_pod("p-failed", phase="Failed", owner_uid="uid-abc", owner_name="rs-1"),
        ]}
        result = phase_gate.classify_pods(pods, {"items": []})
        assert len(result.stale) == 1
        assert result.stale[0]["phase"] == "Failed"

    def test_error_pod_without_running_sibling_not_stale(self):
        """Error Pod의 owner에 Running Pod가 없으면 STALE이 아니다."""
        pods = {"items": [
            self._make_pod("p-error", phase="Error", owner_uid="uid-orphan", owner_name="rs-x"),
        ]}
        result = phase_gate.classify_pods(pods, {"items": []})
        assert result.stale == []

    def test_blocking_crashloopbackoff(self):
        pods = {"items": [
            self._make_pod("p1", phase="Running",
                           container_waiting_reason="CrashLoopBackOff"),
            self._make_pod("p2", phase="Failed",
                           container_waiting_reason="CrashLoopBackOff"),
        ]}
        result = phase_gate.classify_pods(pods, {"items": []})
        # p1 is Running → skipped; p2 is Failed with CrashLoopBackOff → BLOCKING
        assert len(result.blocking) == 1
        assert result.blocking[0]["name"] == "p2"
        assert result.blocking[0]["reason"] == "CrashLoopBackOff"

    def test_blocking_imagepullbackoff(self):
        pods = {"items": [
            self._make_pod("p1", phase="Pending",
                           container_waiting_reason="ImagePullBackOff"),
        ]}
        result = phase_gate.classify_pods(pods, {"items": []})
        assert len(result.blocking) == 1
        assert result.blocking[0]["reason"] == "ImagePullBackOff"

    def test_blocking_pending_over_5min(self):
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        pod_ts = (now - timedelta(minutes=10)).isoformat()
        pods = {"items": [
            self._make_pod("p1", phase="Pending", creation_ts=pod_ts),
        ]}
        result = phase_gate.classify_pods(pods, {"items": []}, now=now)
        assert len(result.blocking) == 1
        assert result.blocking[0]["reason"] == "Pending>5min"
        assert result.blocking[0]["pending_min"] == 10.0

    def test_pending_under_5min_on_old_node_not_classified(self):
        """Pending < 5min, 노드 AGE > 3min → TRANSIENT도 BLOCKING도 아님."""
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        node_ts = (now - timedelta(minutes=10)).isoformat()  # 노드 10분 전 (old)
        pod_ts = (now - timedelta(minutes=2)).isoformat()    # Pod 2분 전 (< 5min)
        pods = {"items": [
            self._make_pod("p1", phase="Pending", node_name="node-1", creation_ts=pod_ts),
        ]}
        nodes = {"items": [self._make_node("node-1", node_ts)]}
        result = phase_gate.classify_pods(pods, nodes, now=now)
        assert result.transient == []
        assert result.blocking == []

    def test_classification_order_transient_before_stale_before_blocking(self):
        """분류 순서: TRANSIENT → STALE → BLOCKING. 각 카테고리에 올바르게 분류."""
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        young_node_ts = (now - timedelta(seconds=60)).isoformat()
        old_pod_ts = (now - timedelta(minutes=10)).isoformat()

        pods = {"items": [
            # Running pod (owner for stale check)
            self._make_pod("p-running", phase="Running", owner_uid="uid-1"),
            # TRANSIENT: Pending on young node
            self._make_pod("p-transient", phase="Pending", node_name="young-node"),
            # STALE: Error with running sibling
            self._make_pod("p-stale", phase="Error", owner_uid="uid-1", owner_name="rs-1"),
            # BLOCKING: Pending > 5min
            self._make_pod("p-blocking", phase="Pending", creation_ts=old_pod_ts),
        ]}
        nodes = {"items": [self._make_node("young-node", young_node_ts)]}

        result = phase_gate.classify_pods(pods, nodes, now=now)
        assert len(result.transient) == 1
        assert result.transient[0]["name"] == "p-transient"
        assert len(result.stale) == 1
        assert result.stale[0]["name"] == "p-stale"
        assert len(result.blocking) == 1
        assert result.blocking[0]["name"] == "p-blocking"

    def test_node_timestamp_with_z_suffix(self):
        """ISO 타임스탬프 'Z' 접미사 파싱 검증."""
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        node_ts = "2025-01-15T09:58:00Z"  # 2분 전
        pods = {"items": [
            self._make_pod("p1", phase="Pending", node_name="node-z"),
        ]}
        nodes = {"items": [self._make_node("node-z", node_ts)]}
        result = phase_gate.classify_pods(pods, nodes, now=now)
        assert len(result.transient) == 1

    def test_pod_without_node_name_not_transient(self):
        """nodeName이 없는 Pending Pod는 TRANSIENT가 아니다."""
        now = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        pod_ts = (now - timedelta(minutes=10)).isoformat()
        pods = {"items": [
            self._make_pod("p1", phase="Pending", creation_ts=pod_ts),
        ]}
        nodes = {"items": [self._make_node("node-1", now.isoformat())]}
        result = phase_gate.classify_pods(pods, nodes, now=now)
        assert result.transient == []
        assert len(result.blocking) == 1


# ══════════════════════════════════════════════════════════════
# Task 6.4: Phase 4 Property-Based Test — Pod Classification Priority (Property 4)
# ══════════════════════════════════════════════════════════════


# Feature: phase-gate-scripts, Property 4: Pod classification priority — TRANSIENT excludes BLOCKING
class TestPodClassificationPriorityProperty:
    """Property 4: If a pod is classified TRANSIENT, it is NOT in the BLOCKING list.

    **Validates: Requirements 4.6**
    """

    @given(
        pod_entries=st.lists(
            st.fixed_dictionaries({
                "phase": st.sampled_from(["Pending", "Error", "Failed", "Running", "Succeeded"]),
                "has_node": st.booleans(),
                "node_young": st.booleans(),          # node age < 3min
                "node_age_sec": st.integers(min_value=0, max_value=600),
                "pod_old": st.booleans(),              # pod creation > 5min ago
                "pod_age_sec": st.integers(min_value=0, max_value=900),
                "has_owner": st.booleans(),
                "owner_has_running": st.booleans(),
                "waiting_reason": st.sampled_from(["", "CrashLoopBackOff", "ImagePullBackOff", "ContainerCreating"]),
            }),
            min_size=0,
            max_size=8,
        ),
    )
    @settings(max_examples=300)
    def test_transient_excludes_blocking(self, pod_entries):
        """Property 4: No pod name appears in both transient and blocking lists."""
        import tempfile

        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        pods_items = []
        nodes_items = []
        node_names_seen = set()
        owner_uid_counter = 0

        for i, entry in enumerate(pod_entries):
            pod_name = f"pod-{i}"
            ns = "default"
            node_name = f"node-{i}" if entry["has_node"] else ""

            # Build node if needed
            if node_name and node_name not in node_names_seen:
                node_names_seen.add(node_name)
                if entry["node_young"]:
                    node_age = min(entry["node_age_sec"], 179)  # < 3min
                else:
                    node_age = max(entry["node_age_sec"], 180)  # >= 3min
                node_ts = (now - timedelta(seconds=node_age)).isoformat()
                nodes_items.append({
                    "metadata": {"name": node_name, "creationTimestamp": node_ts},
                })

            # Build pod
            pod = {
                "metadata": {
                    "name": pod_name,
                    "namespace": ns,
                },
                "spec": {},
                "status": {"phase": entry["phase"]},
            }

            if node_name:
                pod["spec"]["nodeName"] = node_name

            # Pod creation timestamp
            if entry["pod_old"]:
                pod_age = max(entry["pod_age_sec"], 301)  # > 5min
            else:
                pod_age = min(entry["pod_age_sec"], 300)   # <= 5min
            pod["metadata"]["creationTimestamp"] = (now - timedelta(seconds=pod_age)).isoformat()

            # Owner references
            if entry["has_owner"]:
                owner_uid_counter += 1
                uid = f"owner-uid-{owner_uid_counter}"
                pod["metadata"]["ownerReferences"] = [{"uid": uid, "name": f"owner-{owner_uid_counter}"}]

                # If owner should have a running sibling, add one
                if entry["owner_has_running"] and entry["phase"] in ("Error", "Failed"):
                    sibling = {
                        "metadata": {
                            "name": f"sibling-{i}",
                            "namespace": ns,
                            "ownerReferences": [{"uid": uid, "name": f"owner-{owner_uid_counter}"}],
                        },
                        "spec": {},
                        "status": {"phase": "Running"},
                    }
                    pods_items.append(sibling)

            # Container waiting reason
            if entry["waiting_reason"]:
                pod["status"]["containerStatuses"] = [{
                    "state": {"waiting": {"reason": entry["waiting_reason"]}},
                }]

            pods_items.append(pod)

        pods_json = {"items": pods_items}
        nodes_json = {"items": nodes_items}

        result = phase_gate.classify_pods(pods_json, nodes_json, now=now)

        # Core property: no pod name appears in both transient and blocking
        transient_names = {p["name"] for p in result.transient}
        blocking_names = {p["name"] for p in result.blocking}
        overlap = transient_names & blocking_names

        assert overlap == set(), (
            f"Pods in BOTH transient and blocking: {overlap}\n"
            f"transient={result.transient}\n"
            f"blocking={result.blocking}"
        )

    @given(
        pod_entries=st.lists(
            st.fixed_dictionaries({
                "phase": st.sampled_from(["Pending", "Error", "Failed", "Running", "Succeeded"]),
                "has_node": st.booleans(),
                "node_young": st.booleans(),
                "pod_old": st.booleans(),
                "waiting_reason": st.sampled_from(["", "CrashLoopBackOff", "ImagePullBackOff", "ContainerCreating"]),
            }),
            min_size=0,
            max_size=8,
        ),
    )
    @settings(max_examples=300)
    def test_all_three_lists_are_disjoint(self, pod_entries):
        """Extended Property 4: transient, stale, and blocking lists are fully disjoint."""
        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        pods_items = []
        nodes_items = []
        node_names_seen = set()

        for i, entry in enumerate(pod_entries):
            pod_name = f"pod-{i}"
            node_name = f"node-{i}" if entry["has_node"] else ""

            if node_name and node_name not in node_names_seen:
                node_names_seen.add(node_name)
                node_age = 60 if entry["node_young"] else 300
                node_ts = (now - timedelta(seconds=node_age)).isoformat()
                nodes_items.append({
                    "metadata": {"name": node_name, "creationTimestamp": node_ts},
                })

            pod = {
                "metadata": {
                    "name": pod_name,
                    "namespace": "default",
                    "creationTimestamp": (now - timedelta(minutes=10 if entry["pod_old"] else 1)).isoformat(),
                },
                "spec": {},
                "status": {"phase": entry["phase"]},
            }
            if node_name:
                pod["spec"]["nodeName"] = node_name
            if entry["waiting_reason"]:
                pod["status"]["containerStatuses"] = [{
                    "state": {"waiting": {"reason": entry["waiting_reason"]}},
                }]

            pods_items.append(pod)

        result = phase_gate.classify_pods({"items": pods_items}, {"items": nodes_items}, now=now)

        transient_names = {p["name"] for p in result.transient}
        stale_names = {p["name"] for p in result.stale}
        blocking_names = {p["name"] for p in result.blocking}

        assert transient_names.isdisjoint(blocking_names), (
            f"transient ∩ blocking = {transient_names & blocking_names}"
        )
        assert transient_names.isdisjoint(stale_names), (
            f"transient ∩ stale = {transient_names & stale_names}"
        )
        assert stale_names.isdisjoint(blocking_names), (
            f"stale ∩ blocking = {stale_names & blocking_names}"
        )


# ══════════════════════════════════════════════════════════════
# Task 6.6: Phase 4 Property-Based Test — Exit Code from Pod Classification (Property 5)
# ══════════════════════════════════════════════════════════════


# Feature: phase-gate-scripts, Property 5: Phase 4 exit code from pod classification
class TestPhase4ExitCodeProperty:
    """Property 5: Phase 4 exit code from pod classification.

    For any PodClassification result:
    - BLOCKING non-empty → exit 1
    - else STALE or TRANSIENT non-empty → exit 2
    - else → exit 0

    (Assuming node version and FailedEvict checks pass.)

    **Validates: Requirements 4.7, 4.8, 4.9**
    """

    @given(
        blocking_count=st.integers(min_value=0, max_value=5),
        stale_count=st.integers(min_value=0, max_value=5),
        transient_count=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=200)
    def test_phase4_exit_code_from_classification(self, blocking_count, stale_count, transient_count):
        """Property 5: exit code is determined solely by PodClassification contents."""
        import subprocess
        import tempfile

        # Build PodClassification with generated counts
        classification = phase_gate.PodClassification(
            transient=[{"ns": "ns", "name": f"t-{i}", "node": "n", "node_age_sec": 60} for i in range(transient_count)],
            stale=[{"ns": "ns", "name": f"s-{i}", "owner": "o", "phase": "Error"} for i in range(stale_count)],
            blocking=[{"ns": "ns", "name": f"b-{i}", "reason": "CrashLoop", "pending_min": 0.0} for i in range(blocking_count)],
        )

        # Mock run_cmd: valid nodes (matching version) + empty events + valid pods
        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "nodes" in cmd:
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"items": [{
                        "metadata": {"name": "node-1", "creationTimestamp": "2025-01-15T09:00:00Z"},
                        "status": {
                            "nodeInfo": {"kubeletVersion": "v1.35.0"},
                            "conditions": [{"type": "Ready", "status": "True"}],
                        },
                    }]}),
                    stderr="",
                )
            if "get" in cmd and "events" in cmd:
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"items": []}),
                    stderr="",
                )
            if "get" in cmd and "pods" in cmd:
                # Return minimal valid pods JSON (classify_pods is mocked anyway)
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"items": []}),
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=args, returncode=1, stdout="", stderr="unknown cmd",
            )

        # Determine expected exit code
        if blocking_count > 0:
            expected = 1
        elif stale_count > 0 or transient_count > 0:
            expected = 2
        else:
            expected = 0

        with tempfile.TemporaryDirectory() as tmpdir:
            audit_log = os.path.join(tmpdir, "audit.log")
            with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
                with unittest.mock.patch("phase_gate.classify_pods", return_value=classification):
                    rc = phase_gate.gate_phase4("test-cluster", "1.35", audit_log)

        assert rc == expected, (
            f"blocking={blocking_count}, stale={stale_count}, transient={transient_count}: "
            f"expected {expected}, got {rc}"
        )


# ══════════════════════════════════════════════════════════════
# Task 8.1: gate_phase5 단위 테스트
# ══════════════════════════════════════════════════════════════


class TestGatePhase5:
    """gate_phase5 — Phase 5 Karpenter 노드 검증 단위 테스트."""

    @staticmethod
    def _make_crd_result(exists: bool):
        """kubectl get crd nodeclaims.karpenter.sh mock 결과."""
        return subprocess.CompletedProcess(
            args=[], returncode=0 if exists else 1,
            stdout="nodeclaims.karpenter.sh" if exists else "",
            stderr="" if exists else "NotFound",
        )

    @staticmethod
    def _make_nodes_result(nodes: list, returncode: int = 0):
        """kubectl get nodes -l karpenter.sh/nodepool mock 결과."""
        stdout = json.dumps({"items": nodes}) if returncode == 0 else ""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr="",
        )

    @staticmethod
    def _karpenter_node(name: str, kubelet_version: str, ready: bool = True) -> dict:
        """Karpenter 노드 객체 생성."""
        return {
            "metadata": {"name": name},
            "status": {
                "nodeInfo": {"kubeletVersion": kubelet_version},
                "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            },
        }

    def test_crd_not_found_returns_0_skip(self, tmp_path):
        """Karpenter CRD 미존재 → exit 0 (SKIP)."""
        audit = str(tmp_path / "audit.log")
        with unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_crd_result(False)):
            rc = phase_gate.gate_phase5("1.35", audit)
        assert rc == 0
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE5-KARPENTER" in content
        assert "PASS" in content
        assert "Karpenter 미사용" in content

    def test_crd_exists_all_nodes_pass_returns_0(self, tmp_path):
        """CRD 존재 + 모든 노드 버전 일치 + Ready → exit 0."""
        audit = str(tmp_path / "audit.log")
        nodes = [
            self._karpenter_node("karp-1", "v1.35.2"),
            self._karpenter_node("karp-2", "v1.35.0"),
        ]

        call_count = {"n": 0}

        def side_effect(args, **kwargs):
            call_count["n"] += 1
            cmd = " ".join(args)
            if "get" in cmd and "crd" in cmd:
                return self._make_crd_result(True)
            if "get" in cmd and "nodes" in cmd:
                return self._make_nodes_result(nodes)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase5("1.35", audit)
        assert rc == 0
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE5-KARPENTER" in content
        assert "PASS" in content

    def test_crd_exists_version_mismatch_returns_1(self, tmp_path):
        """CRD 존재 + 노드 버전 불일치 → exit 1."""
        audit = str(tmp_path / "audit.log")
        nodes = [
            self._karpenter_node("karp-1", "v1.35.2"),
            self._karpenter_node("karp-2", "v1.34.1"),  # 불일치
        ]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "crd" in cmd:
                return self._make_crd_result(True)
            if "get" in cmd and "nodes" in cmd:
                return self._make_nodes_result(nodes)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase5("1.35", audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "FAIL" in content
        assert "karp-2" in content

    def test_crd_exists_node_not_ready_returns_1(self, tmp_path):
        """CRD 존재 + 노드 NotReady → exit 1."""
        audit = str(tmp_path / "audit.log")
        nodes = [
            self._karpenter_node("karp-1", "v1.35.0", ready=False),
        ]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "crd" in cmd:
                return self._make_crd_result(True)
            if "get" in cmd and "nodes" in cmd:
                return self._make_nodes_result(nodes)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase5("1.35", audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "FAIL" in content
        assert "NotReady" in content

    def test_crd_exists_zero_nodes_returns_0_skip(self, tmp_path):
        """CRD 존재 + Karpenter 노드 0개 → exit 0 (SKIP)."""
        audit = str(tmp_path / "audit.log")

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "crd" in cmd:
                return self._make_crd_result(True)
            if "get" in cmd and "nodes" in cmd:
                return self._make_nodes_result([])
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase5("1.35", audit)
        assert rc == 0
        content = (tmp_path / "audit.log").read_text()
        assert "Karpenter 노드 0개" in content

    def test_kubectl_nodes_failure_returns_1(self, tmp_path):
        """kubectl get nodes 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "crd" in cmd:
                return self._make_crd_result(True)
            if "get" in cmd and "nodes" in cmd:
                return self._make_nodes_result([], returncode=1)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase5("1.35", audit)
        assert rc == 1

    def test_invalid_json_returns_1(self, tmp_path):
        """노드 JSON 파싱 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "crd" in cmd:
                return self._make_crd_result(True)
            if "get" in cmd and "nodes" in cmd:
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="not-json", stderr="",
                )
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase5("1.35", audit)
        assert rc == 1

    def test_audit_log_identifier_phase5_karpenter(self, tmp_path):
        """audit.log에 PHASE5-KARPENTER 식별자 기록 확인."""
        audit = str(tmp_path / "audit.log")
        with unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_crd_result(False)):
            phase_gate.gate_phase5("1.35", audit)
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE5-KARPENTER" in content

    def test_mixed_bad_nodes_all_reported(self, tmp_path):
        """버전 불일치 + NotReady 노드 모두 보고."""
        audit = str(tmp_path / "audit.log")
        nodes = [
            self._karpenter_node("karp-ok", "v1.35.0"),
            self._karpenter_node("karp-old", "v1.34.0"),
            self._karpenter_node("karp-sick", "v1.35.1", ready=False),
        ]

        def side_effect(args, **kwargs):
            cmd = " ".join(args)
            if "get" in cmd and "crd" in cmd:
                return self._make_crd_result(True)
            if "get" in cmd and "nodes" in cmd:
                return self._make_nodes_result(nodes)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("phase_gate.run_cmd", side_effect=side_effect):
            rc = phase_gate.gate_phase5("1.35", audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "karp-old" in content
        assert "karp-sick" in content


# ══════════════════════════════════════════════════════════════
# Task 8.2: gate_phase6 단위 테스트
# ══════════════════════════════════════════════════════════════


class TestGatePhase6:
    """gate_phase6 — Phase 6 Terraform plan JSON 분석 단위 테스트."""

    @staticmethod
    def _plan_result(returncode: int = 0):
        """terraform plan mock 결과."""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout="", stderr="",
        )

    @staticmethod
    def _show_result(plan_json: dict, returncode: int = 0):
        """terraform show -json mock 결과."""
        stdout = json.dumps(plan_json) if returncode == 0 else ""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr="",
        )

    @staticmethod
    def _rc_entry(address: str, rtype: str, actions: list) -> dict:
        """resource_changes 항목 생성."""
        return {
            "address": address,
            "type": rtype,
            "change": {"actions": actions},
        }

    def _mock_subprocess_run(self, plan_rc=0, show_rc=0, plan_json=None):
        """subprocess.run mock side_effect 생성 (plan → show 순서)."""
        if plan_json is None:
            plan_json = {"resource_changes": []}
        call_seq = {"n": 0}

        def side_effect(args, **kwargs):
            call_seq["n"] += 1
            cmd_list = [str(a) for a in args]
            # Route by second argument: "plan" vs "show"
            if len(cmd_list) >= 2 and cmd_list[1] == "plan":
                return self._plan_result(plan_rc)
            if len(cmd_list) >= 2 and cmd_list[1] == "show":
                return self._show_result(plan_json, show_rc)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        return side_effect

    def test_no_changes_returns_0(self, tmp_path):
        """resource_changes 비어있음 → exit 0."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        se = self._mock_subprocess_run(plan_json={"resource_changes": []})
        with unittest.mock.patch("subprocess.run", side_effect=se):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 0
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE6-TFSYNC" in content
        assert "PASS" in content
        assert "변경 없음" in content

    def test_non_destructive_changes_returns_0(self, tmp_path):
        """비파괴적 변경만 → exit 0."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        plan_json = {"resource_changes": [
            self._rc_entry("aws_eks_cluster.this", "aws_eks_cluster", ["update"]),
            self._rc_entry("aws_eks_addon.coredns", "aws_eks_addon", ["create"]),
        ]}
        se = self._mock_subprocess_run(plan_json=plan_json)
        with unittest.mock.patch("subprocess.run", side_effect=se):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 0
        content = (tmp_path / "audit.log").read_text()
        assert "비파괴적 변경만 존재" in content

    def test_recreate_delete_create_returns_1(self, tmp_path):
        """recreate (delete, create) → exit 1."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        plan_json = {"resource_changes": [
            self._rc_entry("aws_eks_node_group.main", "aws_eks_node_group", ["delete", "create"]),
        ]}
        se = self._mock_subprocess_run(plan_json=plan_json)
        with unittest.mock.patch("subprocess.run", side_effect=se):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "recreate" in content
        assert "aws_eks_node_group" in content

    def test_recreate_create_delete_returns_1(self, tmp_path):
        """recreate (create, delete) → exit 1."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        plan_json = {"resource_changes": [
            self._rc_entry("module.eks.aws_launch_template.this[0]", "aws_launch_template", ["create", "delete"]),
        ]}
        se = self._mock_subprocess_run(plan_json=plan_json)
        with unittest.mock.patch("subprocess.run", side_effect=se):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "recreate" in content
        assert "aws_launch_template" in content

    def test_terraform_plan_failure_returns_1(self, tmp_path):
        """terraform plan 실패 (exit 1) → exit 1."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        se = self._mock_subprocess_run(plan_rc=1)
        with unittest.mock.patch("subprocess.run", side_effect=se):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE6-TFSYNC" in content
        assert "FAIL" in content

    def test_terraform_plan_exit_2_continues(self, tmp_path):
        """terraform plan exit 2 (changes present) → 계속 진행."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        plan_json = {"resource_changes": [
            self._rc_entry("aws_eks_addon.coredns", "aws_eks_addon", ["update"]),
        ]}
        se = self._mock_subprocess_run(plan_rc=2, plan_json=plan_json)
        with unittest.mock.patch("subprocess.run", side_effect=se):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 0

    def test_terraform_show_failure_returns_1(self, tmp_path):
        """terraform show 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        se = self._mock_subprocess_run(show_rc=1)
        with unittest.mock.patch("subprocess.run", side_effect=se):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 1

    def test_terraform_show_invalid_json_returns_1(self, tmp_path):
        """terraform show JSON 파싱 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        def side_effect(args, **kwargs):
            cmd_list = [str(a) for a in args]
            if len(cmd_list) >= 2 and cmd_list[1] == "plan":
                return self._plan_result(0)
            if len(cmd_list) >= 2 and cmd_list[1] == "show":
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="not-valid-json", stderr="",
                )
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("subprocess.run", side_effect=side_effect):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 1

    def test_tfplan_cleanup_on_success(self, tmp_path):
        """.tfplan 파일이 성공 시 삭제됨."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()
        tfplan = tmp_path / "tf" / ".tfplan"
        tfplan.write_text("dummy")

        se = self._mock_subprocess_run(plan_json={"resource_changes": []})
        with unittest.mock.patch("subprocess.run", side_effect=se):
            phase_gate.gate_phase6(tf_dir, audit)
        assert not tfplan.exists()

    def test_tfplan_cleanup_on_failure(self, tmp_path):
        """.tfplan 파일이 실패 시에도 삭제됨."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()
        tfplan = tmp_path / "tf" / ".tfplan"
        tfplan.write_text("dummy")

        se = self._mock_subprocess_run(plan_rc=1)
        with unittest.mock.patch("subprocess.run", side_effect=se):
            phase_gate.gate_phase6(tf_dir, audit)
        assert not tfplan.exists()

    def test_tfplan_cleanup_on_exception(self, tmp_path):
        """.tfplan 파일이 예외 발생 시에도 삭제됨 (try/finally)."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()
        tfplan = tmp_path / "tf" / ".tfplan"
        tfplan.write_text("dummy")

        def side_effect(args, **kwargs):
            cmd = " ".join(str(a) for a in args)
            if "plan" in cmd:
                raise FileNotFoundError("terraform not found")
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with unittest.mock.patch("subprocess.run", side_effect=side_effect):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 1
        assert not tfplan.exists()

    def test_mixed_changes_with_one_recreate_returns_1(self, tmp_path):
        """비파괴적 + recreate 혼합 → exit 1."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        plan_json = {"resource_changes": [
            self._rc_entry("aws_eks_addon.coredns", "aws_eks_addon", ["update"]),
            self._rc_entry("aws_eks_node_group.main", "aws_eks_node_group", ["delete", "create"]),
            self._rc_entry("aws_security_group.sg", "aws_security_group", ["create"]),
        ]}
        se = self._mock_subprocess_run(plan_json=plan_json)
        with unittest.mock.patch("subprocess.run", side_effect=se):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "aws_eks_node_group" in content

    def test_delete_only_not_recreate_returns_0(self, tmp_path):
        """delete만 있는 경우 (recreate 아님) → exit 0."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        plan_json = {"resource_changes": [
            self._rc_entry("aws_security_group.old", "aws_security_group", ["delete"]),
        ]}
        se = self._mock_subprocess_run(plan_json=plan_json)
        with unittest.mock.patch("subprocess.run", side_effect=se):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 0

    def test_no_op_actions_returns_0(self, tmp_path):
        """no-op 액션 → exit 0."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        plan_json = {"resource_changes": [
            self._rc_entry("aws_eks_cluster.this", "aws_eks_cluster", ["no-op"]),
        ]}
        se = self._mock_subprocess_run(plan_json=plan_json)
        with unittest.mock.patch("subprocess.run", side_effect=se):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 0

    def test_terraform_plan_timeout_returns_1(self, tmp_path):
        """terraform plan 타임아웃 → exit 1."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        def side_effect(args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args, timeout=300)

        with unittest.mock.patch("subprocess.run", side_effect=side_effect):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE6-TFSYNC" in content
        assert "FAIL" in content

    def test_audit_log_identifier_phase6_tfsync(self, tmp_path):
        """audit.log에 PHASE6-TFSYNC 식별자 기록 확인."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        se = self._mock_subprocess_run(plan_json={"resource_changes": []})
        with unittest.mock.patch("subprocess.run", side_effect=se):
            phase_gate.gate_phase6(tf_dir, audit)
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE6-TFSYNC" in content

    def test_multiple_recreate_resources_all_reported(self, tmp_path):
        """여러 recreate 리소스 → 모두 보고."""
        audit = str(tmp_path / "audit.log")
        tf_dir = str(tmp_path / "tf")
        (tmp_path / "tf").mkdir()

        plan_json = {"resource_changes": [
            self._rc_entry("aws_eks_node_group.a", "aws_eks_node_group", ["delete", "create"]),
            self._rc_entry("aws_launch_template.b", "aws_launch_template", ["create", "delete"]),
        ]}
        se = self._mock_subprocess_run(plan_json=plan_json)
        with unittest.mock.patch("subprocess.run", side_effect=se):
            rc = phase_gate.gate_phase6(tf_dir, audit)
        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "aws_eks_node_group" in content
        assert "aws_launch_template" in content


# ══════════════════════════════════════════════════════════════
# Task 8.3: Phase 6 Property-Based Test — Terraform Recreate Detection (Property 6)
# ══════════════════════════════════════════════════════════════


# Feature: phase-gate-scripts, Property 6: Phase 6 Terraform recreate detection
class TestPhase6RecreateProperty:
    """Property 6: gate_phase6 returns exit code 0 if no resource_changes entry
    has change.actions equal to ["delete","create"] or ["create","delete"];
    otherwise it returns exit code 1.

    **Validates: Requirements 6.3, 6.4**
    """

    @given(
        resource_changes=st.lists(
            st.fixed_dictionaries({
                "address": st.text(
                    min_size=1, max_size=50,
                    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="._[]"),
                ),
                "type": st.text(
                    min_size=1, max_size=30,
                    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
                ),
                "actions": st.sampled_from([
                    ["create"], ["update"], ["delete"], ["no-op"], ["read"],
                    ["delete", "create"], ["create", "delete"],
                ]),
            }),
            min_size=0,
            max_size=10,
        ),
    )
    @settings(max_examples=200)
    def test_phase6_recreate_detection(self, resource_changes):
        """Property 6: gate_phase6 returns 0 iff no recreate; else 1."""
        import tempfile

        # Build plan JSON with generated resource_changes
        plan_json = {
            "resource_changes": [
                {
                    "address": rc["address"],
                    "type": rc["type"],
                    "change": {"actions": rc["actions"]},
                }
                for rc in resource_changes
            ],
        }

        # Determine expected result: exit 1 if any entry has recreate actions
        has_recreate = any(
            set(rc["actions"]) == {"delete", "create"} and len(rc["actions"]) == 2
            for rc in resource_changes
        )
        expected = 1 if has_recreate else 0

        # Mock subprocess.run: terraform plan → success, terraform show → plan JSON
        def side_effect(args, **kwargs):
            cmd_list = [str(a) for a in args]
            if len(cmd_list) >= 2 and cmd_list[1] == "plan":
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="", stderr="",
                )
            if len(cmd_list) >= 2 and cmd_list[1] == "show":
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps(plan_json), stderr="",
                )
            return subprocess.CompletedProcess(
                args=args, returncode=1, stdout="", stderr="unknown cmd",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            import os as _os
            tf_dir = _os.path.join(tmpdir, "tf")
            _os.makedirs(tf_dir)
            audit_log = _os.path.join(tmpdir, "audit.log")

            with unittest.mock.patch("subprocess.run", side_effect=side_effect):
                rc = phase_gate.gate_phase6(tf_dir, audit_log)

        assert rc == expected, (
            f"resource_changes={resource_changes}: expected {expected}, got {rc}"
        )


# ══════════════════════════════════════════════════════════════
# Task 9.1: gate_phase7 단위 테스트
# ══════════════════════════════════════════════════════════════


class TestGatePhase7:
    """gate_phase7 — Phase 7 Final Validation 검증 단위 테스트."""

    @staticmethod
    def _make_insights_result(insights: list, returncode: int = 0):
        """aws eks list-insights mock 결과 생성."""
        stdout = json.dumps({"insights": insights}) if returncode == 0 else ""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr="",
        )

    @staticmethod
    def _passing_insight(name: str) -> dict:
        return {"name": name, "insightStatus": {"status": "PASSING"}}

    @staticmethod
    def _failing_insight(name: str, status: str = "ERROR") -> dict:
        return {"name": name, "insightStatus": {"status": status}}

    def test_all_pass_returns_0(self, tmp_path):
        """모든 sub-gate PASS + Insights PASSING → exit 0."""
        audit = str(tmp_path / "audit.log")
        insights = [self._passing_insight("i1"), self._passing_insight("i2")]

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=0) as m2, \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=0) as m3, \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=0) as m4, \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result(insights)):
            rc = phase_gate.gate_phase7("my-cluster", "1.35", audit)

        assert rc == 0
        content = (tmp_path / "audit.log").read_text()
        assert "PHASE7-FINAL" in content
        assert "최종 판정: PASS" in content

    def test_phase2_fail_returns_1(self, tmp_path):
        """phase2 FAIL → exit 1."""
        audit = str(tmp_path / "audit.log")
        insights = [self._passing_insight("i1")]

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=1), \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=0), \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result(insights)):
            rc = phase_gate.gate_phase7("my-cluster", "1.35", audit)

        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "최종 판정: FAIL" in content

    def test_phase3_fail_returns_1(self, tmp_path):
        """phase3 FAIL → exit 1."""
        audit = str(tmp_path / "audit.log")
        insights = [self._passing_insight("i1")]

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=1), \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=0), \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result(insights)):
            rc = phase_gate.gate_phase7("my-cluster", "1.35", audit)

        assert rc == 1

    def test_phase4_fail_returns_1(self, tmp_path):
        """phase4 FAIL → exit 1."""
        audit = str(tmp_path / "audit.log")
        insights = [self._passing_insight("i1")]

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=1), \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result(insights)):
            rc = phase_gate.gate_phase7("my-cluster", "1.35", audit)

        assert rc == 1

    def test_phase4_warn_no_fail_returns_2(self, tmp_path):
        """phase4 WARN(2) + 나머지 PASS → exit 2."""
        audit = str(tmp_path / "audit.log")
        insights = [self._passing_insight("i1")]

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=2), \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result(insights)):
            rc = phase_gate.gate_phase7("my-cluster", "1.35", audit)

        assert rc == 2
        content = (tmp_path / "audit.log").read_text()
        assert "최종 판정: WARN" in content

    def test_fail_takes_priority_over_warn(self, tmp_path):
        """FAIL(1) + WARN(2) 동시 → exit 1 (FAIL 우선)."""
        audit = str(tmp_path / "audit.log")
        insights = [self._passing_insight("i1")]

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=1), \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=2), \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result(insights)):
            rc = phase_gate.gate_phase7("my-cluster", "1.35", audit)

        assert rc == 1

    def test_non_passing_insight_returns_1(self, tmp_path):
        """Insight가 PASSING이 아닌 경우 → exit 1."""
        audit = str(tmp_path / "audit.log")
        insights = [
            self._passing_insight("i1"),
            self._failing_insight("i2", "WARNING"),
        ]

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=0), \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result(insights)):
            rc = phase_gate.gate_phase7("my-cluster", "1.35", audit)

        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "비정상 Insight" in content

    def test_insights_cmd_failure_returns_1(self, tmp_path):
        """aws eks list-insights 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=0), \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result([], returncode=1)):
            rc = phase_gate.gate_phase7("my-cluster", "1.35", audit)

        assert rc == 1
        content = (tmp_path / "audit.log").read_text()
        assert "aws eks list-insights 실패" in content

    def test_insights_invalid_json_returns_1(self, tmp_path):
        """Insights JSON 파싱 실패 → exit 1."""
        audit = str(tmp_path / "audit.log")

        bad_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not-json", stderr="",
        )
        with unittest.mock.patch("phase_gate.gate_phase2", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=0), \
             unittest.mock.patch("phase_gate.run_cmd", return_value=bad_result):
            rc = phase_gate.gate_phase7("my-cluster", "1.35", audit)

        assert rc == 1

    def test_empty_insights_returns_0(self, tmp_path):
        """Insights 0개 (모두 PASSING 조건 충족) → exit 0."""
        audit = str(tmp_path / "audit.log")

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=0), \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result([])):
            rc = phase_gate.gate_phase7("my-cluster", "1.35", audit)

        assert rc == 0

    def test_sub_gate_results_in_audit(self, tmp_path):
        """개별 sub-gate 결과가 audit에 기록됨."""
        audit = str(tmp_path / "audit.log")
        insights = [self._passing_insight("i1")]

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=0), \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=1), \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=2), \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result(insights)):
            phase_gate.gate_phase7("my-cluster", "1.35", audit)

        content = (tmp_path / "audit.log").read_text()
        assert "sub-gate phase2: exit 0" in content
        assert "sub-gate phase3: exit 1" in content
        assert "sub-gate phase4: exit 2" in content
        assert "sub-gate insights: exit 0" in content

    def test_calls_sub_gates_as_functions_not_subprocess(self, tmp_path):
        """Phase 7은 sub-gate를 함수 호출로 실행 (subprocess 아님)."""
        audit = str(tmp_path / "audit.log")
        insights = [self._passing_insight("i1")]

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=0) as m2, \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=0) as m3, \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=0) as m4, \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result(insights)):
            phase_gate.gate_phase7("my-cluster", "1.35", audit)

        # Verify sub-gates were called as functions with correct args
        m2.assert_called_once()
        assert m2.call_args[0][0] == "my-cluster"
        assert m2.call_args[0][1] == "1.35"

        m3.assert_called_once()
        assert m3.call_args[0][0] == "my-cluster"

        m4.assert_called_once()
        assert m4.call_args[0][0] == "my-cluster"
        assert m4.call_args[0][1] == "1.35"

    def test_all_sub_gates_fail_returns_1(self, tmp_path):
        """모든 sub-gate FAIL → exit 1."""
        audit = str(tmp_path / "audit.log")

        with unittest.mock.patch("phase_gate.gate_phase2", return_value=1), \
             unittest.mock.patch("phase_gate.gate_phase3", return_value=1), \
             unittest.mock.patch("phase_gate.gate_phase4", return_value=1), \
             unittest.mock.patch("phase_gate.run_cmd", return_value=self._make_insights_result([], returncode=1)):
            rc = phase_gate.gate_phase7("my-cluster", "1.35", audit)

        assert rc == 1


# ══════════════════════════════════════════════════════════════
# Task 9.2: Phase 7 Property-Based Test (Property 7)
# ══════════════════════════════════════════════════════════════


# Feature: phase-gate-scripts, Property 7: Phase 7 exit code aggregation
class TestPhase7AggregationProperty:
    """Property 7: gate_phase7 returns 1 if any sub-gate returned 1;
    else 2 if any sub-gate returned 2; else 0.
    FAIL(1) takes strict priority over WARN(2).

    **Validates: Requirements 7.2, 7.3, 7.4, 7.6**
    """

    @given(
        phase2_rc=st.sampled_from([0, 1, 2]),
        phase3_rc=st.sampled_from([0, 1]),
        phase4_rc=st.sampled_from([0, 1, 2]),
        insights_pass=st.booleans(),
    )
    @settings(max_examples=200)
    def test_phase7_exit_code_aggregation(self, phase2_rc, phase3_rc, phase4_rc, insights_pass):
        """Property 7: Phase 7 aggregates sub-gate exit codes with FAIL > WARN > PASS."""
        import subprocess
        import tempfile

        # insights_pass=True → all PASSING (rc=0), False → non-PASSING insight (rc=1)
        insights_rc = 0 if insights_pass else 1

        # Build expected result: any 1 → 1; else any 2 → 2; else 0
        all_codes = [phase2_rc, phase3_rc, phase4_rc, insights_rc]
        if 1 in all_codes:
            expected = 1
        elif 2 in all_codes:
            expected = 2
        else:
            expected = 0

        # Mock insights run_cmd response
        if insights_pass:
            insights_stdout = json.dumps({
                "insights": [{"name": "test-insight", "insightStatus": {"status": "PASSING"}}]
            })
            insights_result = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=insights_stdout, stderr="",
            )
        else:
            insights_stdout = json.dumps({
                "insights": [{"name": "bad-insight", "insightStatus": {"status": "ERROR"}}]
            })
            insights_result = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=insights_stdout, stderr="",
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            audit_log = os.path.join(tmpdir, "audit.log")

            with unittest.mock.patch("phase_gate.gate_phase2", return_value=phase2_rc), \
                 unittest.mock.patch("phase_gate.gate_phase3", return_value=phase3_rc), \
                 unittest.mock.patch("phase_gate.gate_phase4", return_value=phase4_rc), \
                 unittest.mock.patch("phase_gate.run_cmd", return_value=insights_result):
                rc = phase_gate.gate_phase7("my-cluster", "1.35", audit_log)

        assert rc == expected, (
            f"phase2_rc={phase2_rc}, phase3_rc={phase3_rc}, phase4_rc={phase4_rc}, "
            f"insights_rc={insights_rc}: expected {expected}, got {rc}"
        )


# ══════════════════════════════════════════════════════════════
# Bug fix 검증: audit.log append 모드
# ══════════════════════════════════════════════════════════════
class TestAuditLogAppend:
    """audit_flush가 기존 내용을 보존하고 append하는지 검증."""

    def test_audit_flush_appends_not_overwrites(self, tmp_path):
        """두 번 flush 후 양쪽 기록이 모두 존재해야 함."""
        import importlib
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'k8s-upgrade-skills', 'scripts'))
        import lib
        importlib.reload(lib)

        audit_path = str(tmp_path / "audit.log")

        # 첫 번째 phase
        lib.reset_gate()
        lib.audit_init("test-cluster", "1.33", "1.34")
        lib.audit_write("PHASE2-CP", "PASS", "Control Plane OK")
        lib.audit_flush(audit_path)

        # 두 번째 phase
        lib.reset_gate()
        lib.audit_init("test-cluster", "", "1.34")
        lib.audit_write("PHASE3-ADDON", "PASS", "Add-ons OK")
        lib.audit_flush(audit_path)

        content = open(audit_path, encoding="utf-8").read()
        assert "PHASE2-CP" in content, "Phase 2 기록이 사라짐"
        assert "PHASE3-ADDON" in content, "Phase 3 기록이 없음"
        # 두 섹션 모두 존재
        assert content.count("# Gate:") == 2


# ══════════════════════════════════════════════════════════════
# Bug fix 검증: resource_changes no-op 필터
# ══════════════════════════════════════════════════════════════
class TestPhase6NoOpFilter:
    """terraform plan JSON에서 no-op 항목이 필터링되는지 검증."""

    def test_noop_resources_filtered_as_no_changes(self, tmp_path):
        """resource_changes가 전부 no-op이면 '변경 없음' 판정."""
        tf_dir = str(tmp_path / "terraform")
        os.makedirs(tf_dir, exist_ok=True)

        plan_json = json.dumps({
            "resource_changes": [
                {"address": "aws_vpc.main", "type": "aws_vpc",
                 "change": {"actions": ["no-op"]}},
                {"address": "aws_subnet.a", "type": "aws_subnet",
                 "change": {"actions": ["no-op"]}},
            ]
        })

        plan_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        show_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=plan_json, stderr="")

        with unittest.mock.patch("subprocess.run") as mock_run:
            mock_run.side_effect = [plan_result, show_result]
            audit_log = str(tmp_path / "audit.log")
            rc = phase_gate.gate_phase6(tf_dir, audit_log)

        assert rc == 0, "no-op만 있으면 변경 없음(exit 0)이어야 함"
        content = open(audit_log, encoding="utf-8").read()
        assert "변경 없음" in content

    def test_real_changes_counted_without_noop(self, tmp_path):
        """no-op과 실제 변경이 섞여 있을 때 no-op은 카운트에서 제외."""
        tf_dir = str(tmp_path / "terraform")
        os.makedirs(tf_dir, exist_ok=True)

        plan_json = json.dumps({
            "resource_changes": [
                {"address": "aws_vpc.main", "type": "aws_vpc",
                 "change": {"actions": ["no-op"]}},
                {"address": "aws_eks.cluster", "type": "aws_eks_cluster",
                 "change": {"actions": ["update"]}},
            ]
        })

        plan_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        show_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=plan_json, stderr="")

        with unittest.mock.patch("subprocess.run") as mock_run:
            mock_run.side_effect = [plan_result, show_result]
            audit_log = str(tmp_path / "audit.log")
            rc = phase_gate.gate_phase6(tf_dir, audit_log)

        assert rc == 0
        content = open(audit_log, encoding="utf-8").read()
        assert "1개" in content  # no-op 제외 후 1개만
