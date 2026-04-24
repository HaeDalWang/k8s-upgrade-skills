#!/usr/bin/env python3
"""
audit_event.py — Sub-Agent가 감지한 이벤트를 audit.log에 기록하는 CLI 래퍼

Sub-Agent(LLM)는 직접 audit.log에 쓰지 않는다.
이 스크립트를 호출하면 스크립트가 기존 audit_write() 형식과 동일하게 append한다.

Usage:
  python3 scripts/audit_event.py \
    --audit-log audit.log \
    --rule-id "DRAIN-P4" \
    --result "WARN" \
    --detail "FailedDrain: node/ip-10-0-1-23 — PDB my-api disruptionsAllowed=0"

Exit codes:
  0 = 기록 성공
  1 = 인자 오류 또는 파일 쓰기 실패
"""

import argparse
import sys
from datetime import datetime, timezone


VALID_RESULTS = {"PASS", "WARN", "FAIL", "INFO"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sub-Agent 감지 이벤트를 audit.log에 기록"
    )
    parser.add_argument("--audit-log", required=True, help="audit.log 경로")
    parser.add_argument("--rule-id", required=True, help="규칙/모니터 ID (예: DRAIN-P4)")
    parser.add_argument(
        "--result",
        required=True,
        choices=list(VALID_RESULTS),
        help="결과 (PASS|WARN|FAIL|INFO)",
    )
    parser.add_argument("--detail", required=True, help="이벤트 상세 내용")
    args = parser.parse_args()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{now} | {args.rule_id} | {args.result} | {args.detail}\n"

    try:
        with open(args.audit_log, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        print(f"ERROR: audit.log 쓰기 실패: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
