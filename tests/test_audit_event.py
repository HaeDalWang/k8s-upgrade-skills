"""
tests/test_audit_event.py — audit_event.py 단위 테스트
"""

import subprocess
import sys
import os
import tempfile

import pytest

import audit_event


class TestAuditEventBasic:
    """기본 동작 테스트."""

    def test_writes_single_line(self, tmp_path):
        """정상 호출 시 audit.log에 단일 라인 기록."""
        log = str(tmp_path / "audit.log")
        rc = audit_event.main.__wrapped__ if hasattr(audit_event.main, "__wrapped__") else None

        result = subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/audit_event.py",
             "--audit-log", log,
             "--rule-id", "DRAIN-P4",
             "--result", "WARN",
             "--detail", "FailedDrain: node/ip-10-0-1-23"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        content = open(log).read()
        assert "DRAIN-P4" in content
        assert "WARN" in content
        assert "FailedDrain: node/ip-10-0-1-23" in content

    def test_line_format_matches_audit_write(self, tmp_path):
        """기록 형식이 audit_write()와 동일한지 확인: timestamp | rule_id | result | detail"""
        log = str(tmp_path / "audit.log")
        subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/audit_event.py",
             "--audit-log", log,
             "--rule-id", "DRAIN-P2",
             "--result", "FAIL",
             "--detail", "NodeNotReady detected"],
            capture_output=True, text=True
        )
        line = open(log).read().strip()
        parts = line.split(" | ")
        assert len(parts) == 4, f"형식 불일치: {line}"
        assert parts[1] == "DRAIN-P2"
        assert parts[2] == "FAIL"
        assert parts[3] == "NodeNotReady detected"

    def test_appends_multiple_events(self, tmp_path):
        """여러 번 호출 시 append 동작 확인."""
        log = str(tmp_path / "audit.log")
        for i in range(3):
            subprocess.run(
                [sys.executable, "k8s-upgrade-skills/scripts/audit_event.py",
                 "--audit-log", log,
                 "--rule-id", f"DRAIN-P4-{i}",
                 "--result", "WARN",
                 "--detail", f"event {i}"],
                capture_output=True, text=True
            )
        lines = open(log).read().strip().splitlines()
        assert len(lines) == 3
        assert "DRAIN-P4-0" in lines[0]
        assert "DRAIN-P4-1" in lines[1]
        assert "DRAIN-P4-2" in lines[2]

    def test_appends_to_existing_log(self, tmp_path):
        """기존 audit.log에 append — 기존 내용 보존 확인."""
        log = str(tmp_path / "audit.log")
        with open(log, "w") as f:
            f.write("existing content\n")

        subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/audit_event.py",
             "--audit-log", log,
             "--rule-id", "DRAIN-P5",
             "--result", "INFO",
             "--detail", "NodeClaim replaced"],
            capture_output=True, text=True
        )
        content = open(log).read()
        assert "existing content" in content
        assert "DRAIN-P5" in content


class TestAuditEventResultValues:
    """result 값 검증 테스트."""

    @pytest.mark.parametrize("result", ["PASS", "WARN", "FAIL", "INFO"])
    def test_valid_results_accepted(self, tmp_path, result):
        """유효한 result 값 모두 허용."""
        log = str(tmp_path / "audit.log")
        r = subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/audit_event.py",
             "--audit-log", log,
             "--rule-id", "TEST",
             "--result", result,
             "--detail", "test"],
            capture_output=True, text=True
        )
        assert r.returncode == 0

    def test_invalid_result_rejected(self, tmp_path):
        """유효하지 않은 result 값 거부."""
        log = str(tmp_path / "audit.log")
        r = subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/audit_event.py",
             "--audit-log", log,
             "--rule-id", "TEST",
             "--result", "UNKNOWN",
             "--detail", "test"],
            capture_output=True, text=True
        )
        assert r.returncode != 0


class TestAuditEventErrorHandling:
    """오류 처리 테스트."""

    def test_missing_required_args_returns_nonzero(self, tmp_path):
        """필수 인자 누락 시 비정상 종료."""
        r = subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/audit_event.py",
             "--audit-log", str(tmp_path / "audit.log")],
            capture_output=True, text=True
        )
        assert r.returncode != 0

    def test_unwritable_path_returns_1(self):
        """쓰기 불가 경로 → exit 1."""
        r = subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/audit_event.py",
             "--audit-log", "/nonexistent/path/audit.log",
             "--rule-id", "TEST",
             "--result", "WARN",
             "--detail", "test"],
            capture_output=True, text=True
        )
        assert r.returncode == 1
        assert "ERROR" in r.stderr

    def test_timestamp_is_utc_iso8601(self, tmp_path):
        """타임스탬프가 UTC ISO8601 형식인지 확인."""
        import re
        log = str(tmp_path / "audit.log")
        subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/audit_event.py",
             "--audit-log", log,
             "--rule-id", "DRAIN-P4",
             "--result", "WARN",
             "--detail", "test"],
            capture_output=True, text=True
        )
        line = open(log).read().strip()
        timestamp = line.split(" | ")[0]
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", timestamp), \
            f"타임스탬프 형식 불일치: {timestamp}"


class TestAuditEventCoexistence:
    """기존 gate 스크립트와 공존 테스트."""

    def test_does_not_interfere_with_audit_flush(self, tmp_path):
        """audit_event.py 기록 후 audit_flush()가 정상 동작하는지 확인."""
        import sys
        sys.path.insert(0, "k8s-upgrade-skills/scripts")
        import lib
        lib.reset_gate()

        log = str(tmp_path / "audit.log")

        # Sub-Agent가 이벤트 기록
        subprocess.run(
            [sys.executable, "k8s-upgrade-skills/scripts/audit_event.py",
             "--audit-log", log,
             "--rule-id", "DRAIN-P4",
             "--result", "WARN",
             "--detail", "FailedDrain detected"],
            capture_output=True, text=True
        )

        # 메인 gate가 이후 flush
        lib.audit_init("test-cluster", "1.33", "1.34")
        lib.audit_write("PHASE4-NODE", "PASS", "All nodes ready")
        lib.audit_flush(log)

        content = open(log).read()
        assert "DRAIN-P4" in content
        assert "PHASE4-NODE" in content
        assert "# Summary:" in content
