#!/usr/bin/env python3
"""
helm_compat_check.py — Helm 차트 ↔ K8s 버전 호환성 사전 검증 (Phase 0 보조)

설치된 Helm Release를 registry의 큐레이션 지식과 대조하여, EKS Insights·kubent가
못 잡는 차트 레벨 호환성 함정을 업그레이드 전에 검출한다.

⚠️ 독립 설치 스킬 — 부모 lib.py에 의존하지 않는다. compat_lib.py만 사용한다.

Usage:
  # 클러스터에서 직접 (helm ls 자동 호출)
  python3 helm_compat_check.py --current 1.33 --target 1.34 \
    --registry-dir ../registry --audit-log audit.log

  # 클러스터 없이 주입 (테스트/드라이런)
  python3 helm_compat_check.py --current 1.33 --target 1.34 \
    --registry-dir ../registry --audit-log audit.log \
    --releases-json '[{"name":"ingress-nginx","namespace":"x","chart":"ingress-nginx-4.13.5","app_version":"1.13.5"}]'

Exit codes (기존 gate_check.py와 동일 신뢰 모델):
  0 = PASS (호환성 문제 없음)
  1 = FAIL (CRITICAL — 업그레이드 차단, 차트 먼저 조치)
  2 = WARN (HIGH — 수동 검토 필요)
  127 = helm CLI 미존재
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

try:
    import compat_lib
except ImportError:
    print("ERROR: compat_lib.py not found (같은 scripts 디렉토리에 있어야 함).", file=sys.stderr)
    sys.exit(1)

RED = "\033[0;31m"
YELLOW = "\033[0;33m"
GREEN = "\033[0;32m"
CYAN = "\033[0;36m"
NC = "\033[0m"


# ══════════════════════════════════════════════════════════════
# Release 수집
# ══════════════════════════════════════════════════════════════
def fetch_releases_from_helm(timeout: int = 60):
    """helm ls -A -o json 실행. 실패 시 None (helm 미존재/오류와 빈 목록을 구분)."""
    try:
        r = subprocess.run(["helm", "ls", "-A", "-o", "json"],
                           capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


# ══════════════════════════════════════════════════════════════
# 단일 Release 평가 (3축 + k8s_breaks + CRD 횡단 규칙)
# ══════════════════════════════════════════════════════════════
def evaluate_release(entry: dict, release: dict, current: str, target: str,
                     today: str) -> list:
    """registry entry와 설치 release를 대조하여 Finding 리스트를 반환한다."""
    chart_ref = release.get("chart", "")
    _, chart_ver = compat_lib.parse_chart_ref(chart_ref)
    app_ver = release.get("app_version", "") or chart_ver

    findings = []

    # 1축: support
    sup = compat_lib.evaluate_support(entry, chart_ver, app_ver, target)
    findings.append(sup)
    chart_upgrade_needed = (sup.result == "FAIL" and sup.severity in ("CRITICAL", "HIGH"))

    # 2축: lifecycle
    lc = compat_lib.evaluate_lifecycle(entry, chart_ver, today)
    if lc is not None:
        findings.append(lc)

    # k8s_breaks (점프 구간만)
    findings.extend(compat_lib.fired_k8s_breaks(entry, current, target))

    # 3축 + 횡단: CRD 수동 업글 경고
    crd = compat_lib.crd_warning(entry, chart_upgrade_needed)
    if crd is not None:
        findings.append(crd)

    # 등록된 upgrade_hazards (차트 업글이 필요할 때만 발화)
    if chart_upgrade_needed:
        for hz in entry.get("upgrade_hazards", []):
            findings.append(compat_lib.Finding(
                "HELM-HAZARD", "FAIL", hz.get("severity", "HIGH"),
                f"{entry.get('chart_name', '?')}: {hz.get('action', '')} "
                f"(trigger: {hz.get('trigger', '')})"))

    return findings


# ══════════════════════════════════════════════════════════════
# 집계 + audit (자체 포함 — 부모 lib.py 비의존)
# ══════════════════════════════════════════════════════════════
class Aggregator:
    """Finding을 누적하고 severity를 카운트한다. exit code 판정의 단일 진실 원천."""

    def __init__(self) -> None:
        self.critical_fail = 0
        self.high_warn = 0
        self.medium_info = 0
        self.total_pass = 0
        self.checked = 0
        self.lines: list = []

    def add(self, f) -> None:
        self.checked += 1
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.lines.append(f"{now} | {f.rule_id} | {f.result} | {f.detail}")
        if f.result in ("PASS", "SKIP"):
            self.total_pass += 1
            print(f"{GREEN}✅ {f.result}{NC}  {f.rule_id:<14s} {f.detail}")
        elif f.severity == "CRITICAL":
            self.critical_fail += 1
            print(f"{RED}❌ FAIL{NC}  {f.rule_id:<14s} [{f.severity}] {f.detail}")
        elif f.severity == "HIGH":
            self.high_warn += 1
            print(f"{YELLOW}⚠️  WARN{NC}  {f.rule_id:<14s} [{f.severity}] {f.detail}")
        else:
            self.medium_info += 1
            print(f"{CYAN}ℹ️  INFO{NC}  {f.rule_id:<14s} [{f.severity}] {f.detail}")

    def exit_code(self) -> int:
        if self.critical_fail > 0:
            return 1
        if self.high_warn > 0:
            return 2
        return 0


def write_audit(path: str, cluster_header: str, agg: Aggregator) -> None:
    """audit.log에 헤더 + Finding 라인 + Summary를 append한다."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    gate = "BLOCKED" if agg.critical_fail > 0 else ("WARN" if agg.high_warn > 0 else "OPEN")
    out = ["# Helm K8s Compatibility Audit (HELM-COMPAT)",
           cluster_header,
           f"# Started: {now}",
           "# ──────────────────────────────────────────"]
    out.extend(agg.lines)
    out.extend([
        "# ──────────────────────────────────────────",
        f"# Summary: CRITICAL={agg.critical_fail} HIGH={agg.high_warn} "
        f"INFO={agg.medium_info} PASS={agg.total_pass} CHECKED={agg.checked}",
        f"# Gate: {gate}",
        f"# Finished: {now}",
    ])
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════
def main() -> int:
    p = argparse.ArgumentParser(description="Helm 차트 ↔ K8s 버전 호환성 검증")
    p.add_argument("--current", required=True, help="현재 K8s 버전 (예: 1.33)")
    p.add_argument("--target", required=True, help="대상 K8s 버전 (예: 1.34)")
    p.add_argument("--registry-dir", required=True, help="registry JSON 디렉토리")
    p.add_argument("--audit-log", required=True, help="audit.log 경로")
    p.add_argument("--today", default=None, help="오늘 날짜 YYYY-MM-DD (per_release EOL 비교용, 기본=실제 오늘)")
    p.add_argument("--releases-json", default=None,
                   help="helm ls 대신 주입할 release JSON 배열 (테스트/드라이런)")
    args = p.parse_args()

    today = args.today or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Release 수집
    if args.releases_json is not None:
        try:
            releases = json.loads(args.releases_json)
        except json.JSONDecodeError as e:
            print(f"ERROR: --releases-json 파싱 실패: {e}", file=sys.stderr)
            return 1
    else:
        releases = fetch_releases_from_helm()
        if releases is None:
            print(f"{RED}ERROR: helm ls 실행 불가 — helm CLI 설치/인증 확인{NC}", file=sys.stderr)
            return 127

    registry = compat_lib.load_registry(args.registry_dir)

    print("════════════════════════════════════════════════════════════")
    print(f"  Helm 호환성 검증: K8s {args.current} → {args.target}")
    print(f"  설치 Release: {len(releases)}개 | registry 차트: {len(registry)}개")
    print("════════════════════════════════════════════════════════════")

    agg = Aggregator()

    for rel in releases:
        chart_ref = rel.get("chart", "")
        chart_name, _ = compat_lib.parse_chart_ref(chart_ref)
        ns = rel.get("namespace", "?")

        entry = registry.get(chart_name)
        if entry is None:
            # registry 미등록 — 자동 평가 불가, 수동 검토 INFO (gate 차단 안 함)
            agg.add(compat_lib.Finding(
                "HELM-UNKNOWN", "FAIL", "MEDIUM",
                f"{ns}/{chart_name} ({chart_ref}): registry 미등록 차트 — "
                f"수동 검토 필요 (kubeVersion·릴리스 노트 직접 확인)"))
            continue

        for f in evaluate_release(entry, rel, args.current, args.target, today):
            agg.add(f)

    write_audit(args.audit_log, f"# Upgrade: {args.current} → {args.target}", agg)

    code = agg.exit_code()
    print()
    if code == 1:
        print(f"{RED}Gate: BLOCKED — CRITICAL {agg.critical_fail}개. 차트 조치 후 재실행.{NC}")
    elif code == 2:
        print(f"{YELLOW}Gate: WARN — HIGH {agg.high_warn}개. 수동 검토 필요.{NC}")
    else:
        print(f"{GREEN}Gate: OPEN — Helm 호환성 문제 없음.{NC}")
    print(f"감사 로그: {args.audit_log}")
    return code


if __name__ == "__main__":
    sys.exit(main())
