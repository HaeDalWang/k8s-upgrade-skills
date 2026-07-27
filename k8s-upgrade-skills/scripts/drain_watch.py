#!/usr/bin/env python3
"""
drain_watch.py — 노드 드레인/교체 인라인 백그라운드 모니터

⚠️ 이것은 Sub-Agent가 아니다. 메인 에이전트가 `run_in_background: true`로 직접 띄우는
   결정적 폴링 스크립트다. (Claude Code Agent는 동기 호출-반환 모델이라 "감시 중
   즉시 STOP 신호"가 구조적으로 불가능 → 인라인 백그라운드 폴링으로 대체.)

주기적으로 다음을 스냅샷으로 떠서 위험 신호를 감지하고, 새 신호만 audit.log에
`DRAIN-{PHASE}` 항목으로 한 줄씩 기록한다 (fcntl 락, 게이트 스크립트와 동시 쓰기 안전):
  - Warning 이벤트 (FailedDrain, DisruptionBlocked, OOMKilling 등)
  - PDB disruptionsAllowed=0 (drain 차단)
  - NodeClaim Ready != True (Phase 5 Karpenter 교체)

stdout에도 실시간 출력하므로 메인 에이전트가 BashOutput으로 진행 상황을 확인한다.

Usage:
  python3 scripts/drain_watch.py --phase P5 --audit-log audit.log \
    [--interval 30] [--max-duration 3600] [--scope all|kube-system] [--stop-file PATH]

종료 조건 (셋 중 하나):
  1. --max-duration(초) 초과 — 무한 실행 방지 안전장치 (기본 3600초)
  2. 메인 에이전트가 프로세스 종료 (KillShell)
  3. --stop-file 경로에 파일이 생기면 다음 사이클에 정상 종료

Exit codes:
  0 = 정상 종료 (FAIL 이벤트 없음)
  1 = 종료까지 FAIL 등급 이벤트를 1건 이상 감지 (메인이 검토해야 함)
"""

import argparse
import json
import os
import sys
import time
from typing import Optional

try:
    from lib import audit_append, run_cmd
except ImportError:
    print("ERROR: lib.py not found. Run install.sh --force to reinstall.", file=sys.stderr)
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
# 감시 대상 이벤트 reason → 심각도
# (k8s-drain-monitor 규칙 기반 — FAIL은 즉시 메인이 중단 판단)
#
# 의도적 제외: `BackOff`는 CrashLoop/ImagePull로 드레인과 무관하게 상시 발생하는
# 노이즈라 제외한다 (원본 규칙도 ">3회 지속 시에만 보고"하는 조건부였음).
# 드레인 위험의 본질 신호(FailedDrain/DisruptionBlocked/ExceededGracePeriod 등)에 집중한다.
# ══════════════════════════════════════════════════════════════
WATCHED_REASONS: dict = {
    "FailedDrain": "FAIL",
    "NodeClaimTerminationFailed": "FAIL",
    "DisruptionBlocked": "WARN",
    "ExceededGracePeriod": "WARN",
    "FailedKillPod": "WARN",
    "NodeNotReady": "WARN",
    "NodeNotSchedulable": "WARN",
    "OOMKilling": "WARN",
    "FailedMount": "WARN",
    "NodeClaimNotFound": "WARN",
    "Evicted": "WARN",
}

DEFAULT_INTERVAL_SEC = 30
DEFAULT_MAX_DURATION_SEC = 3600

# 노드 교체 중 여러 Pod/노드에 걸쳐 대량으로 정상 발생하는 노이즈성 reason.
# 이들은 count가 오를 때마다(폴링마다) 재기록하면 audit.log를 폭주시키므로
# (실전: secrets-store FailedMount·NodeNotReady 수백 줄) uid당 1회만 기록한다.
# FailedDrain/OOMKilling 등 본질 신호는 count를 포함해 재발도 잡는다.
NOISY_REASONS: set = {"FailedMount", "NodeNotReady", "NodeNotSchedulable"}


# ══════════════════════════════════════════════════════════════
# 순수 감지 함수 (테스트 대상 — kubectl 호출 없음)
# ══════════════════════════════════════════════════════════════
def event_key(evt: dict) -> str:
    """이벤트 고유 키.

    노이즈성 reason(NOISY_REASONS)은 uid만으로 식별해 반복 기록을 억제하고,
    그 외는 uid + 발생 횟수(count)로 식별해 재발도 새 이벤트로 본다.
    """
    md = evt.get("metadata", {})
    uid = md.get("uid", "") or f"{md.get('namespace', '')}/{md.get('name', '')}"
    if evt.get("reason", "") in NOISY_REASONS:
        return uid
    count = evt.get("count")
    if count is None:
        count = evt.get("series", {}).get("count", 1)
    return f"{uid}:{count}"


def extract_warning_events(events_json: dict, seen_keys: set) -> tuple:
    """Warning 이벤트 중 감시 대상 reason만, 아직 안 본 것만 추출.

    반환: (new_events: list[dict], updated_seen: set)
      new_events 각 항목: {reason, severity, ns, obj, msg}
    """
    new_events: list = []
    seen = set(seen_keys)
    for evt in events_json.get("items", []):
        if evt.get("type") != "Warning":
            continue
        reason = evt.get("reason", "")
        severity = WATCHED_REASONS.get(reason)
        if severity is None:
            continue
        key = event_key(evt)
        if key in seen:
            continue
        seen.add(key)
        involved = evt.get("involvedObject", {})
        ns = evt.get("metadata", {}).get("namespace", "") or involved.get("namespace", "")
        new_events.append({
            "reason": reason,
            "severity": severity,
            "ns": ns or "-",
            "obj": involved.get("name", "?"),
            "msg": (evt.get("message", "") or "").strip(),
        })
    return new_events, seen


def extract_blocked_pdbs(pdb_json: dict, seen_keys: set) -> tuple:
    """disruptionsAllowed=0 (expectedPods>0) PDB 중 아직 기록 안 한 것만 추출.

    상태가 유지되는 동안 중복 기록을 막고, 해소되면 seen에서 빼서 재발 시 다시 기록한다.
    반환: (new_blocked: list[dict], updated_seen: set)
    """
    current = set()
    new_blocked: list = []
    for pdb in pdb_json.get("items", []):
        status = pdb.get("status", {})
        allowed = status.get("disruptionsAllowed", 1)
        expected = status.get("expectedPods", 0)
        if expected > 0 and allowed == 0:
            ns = pdb.get("metadata", {}).get("namespace", "?")
            name = pdb.get("metadata", {}).get("name", "?")
            key = f"{ns}/{name}"
            current.add(key)
            if key not in seen_keys:
                new_blocked.append({"ns": ns, "name": name})
    # 현재 차단 상태인 것만 seen으로 유지 (해소된 것은 제거 → 재발 시 재기록)
    return new_blocked, current


def extract_bad_nodeclaims(nc_json: dict, seen_keys: set) -> tuple:
    """Ready != True인 NodeClaim 중 아직 기록 안 한 것만 추출 (Phase 5 교체 모니터).

    반환: (new_bad: list[dict], updated_seen: set)
    """
    current = set()
    new_bad: list = []
    for nc in nc_json.get("items", []):
        name = nc.get("metadata", {}).get("name", "?")
        conds = {
            c.get("type"): c
            for c in nc.get("status", {}).get("conditions", [])
            if c.get("type")
        }
        ready = conds.get("Ready", {})
        status = ready.get("status")
        # status가 비어있으면(아직 condition 미설정) 판단 보류
        if status and status != "True":
            reason = ready.get("reason", "")
            key = f"{name}:{reason}"
            current.add(key)
            if key not in seen_keys:
                new_bad.append({
                    "name": name,
                    "reason": reason or "NotReady",
                    "message": (ready.get("message", "") or "").strip(),
                })
    return new_bad, current


# ══════════════════════════════════════════════════════════════
# 폴링 (kubectl 호출 — 실패 시 None)
# ══════════════════════════════════════════════════════════════
def _kubectl_get(resource: str, scope: str = "all") -> Optional[dict]:
    """kubectl get <resource> -o json. 실패 시 None (kubectl 일시 오류와 빈 결과 구분)."""
    cmd = ["kubectl", "get", resource, "-o", "json"]
    if scope == "all":
        cmd.insert(2, "-A")
    elif scope and scope != "none":
        cmd.insert(2, "-n")
        cmd.insert(3, scope)
    r = run_cmd(cmd, timeout=30)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


# ══════════════════════════════════════════════════════════════
# 감시 루프
# ══════════════════════════════════════════════════════════════
def watch_loop(phase: str, audit_log: str, interval: int, max_duration: int,
               scope: str, stop_file: str = None,
               poll_events=None, poll_pdb=None, poll_nc=None,
               sleep_fn=time.sleep, clock=time.monotonic) -> int:
    """폴링 루프. 의존성(poll_*, sleep_fn, clock)은 테스트를 위해 주입 가능.

    반환: exit code (0=FAIL 이벤트 없음, 1=FAIL 이벤트 1건 이상).
    """
    rule_id = f"DRAIN-{phase}"
    event_scope = "kube-system" if scope == "kube-system" else "all"

    if poll_events is None:
        poll_events = lambda: _kubectl_get("events", event_scope)
    if poll_pdb is None:
        poll_pdb = lambda: _kubectl_get("pdb", "all")
    if poll_nc is None:
        poll_nc = lambda: _kubectl_get("nodeclaims", "none")

    seen_events: set = set()
    seen_pdb: set = set()
    seen_nc: set = set()
    total = {"event": 0, "pdb": 0, "nodeclaim": 0, "fail": 0}

    print(f"[drain_watch] started — phase={phase} scope={event_scope} "
          f"interval={interval}s max={max_duration}s", flush=True)
    audit_append(audit_log, rule_id, "INFO",
                 f"DrainWatch started: scope={event_scope}, interval={interval}s (inline background monitor)")

    start = clock()
    while clock() - start < max_duration:
        if stop_file and os.path.exists(stop_file):
            print("[drain_watch] stop-file detected — terminating", flush=True)
            break

        # 1. Warning 이벤트
        events = poll_events()
        if events is not None:
            new_evts, seen_events = extract_warning_events(events, seen_events)
            for e in new_evts:
                detail = f"{e['reason']}: {e['ns']}/{e['obj']} — {e['msg'][:140]}"
                audit_append(audit_log, rule_id, e["severity"], detail)
                total["event"] += 1
                if e["severity"] == "FAIL":
                    total["fail"] += 1
                print(f"[{e['severity']}] {detail}", flush=True)

        # 2. PDB 차단 (drain blocked)
        pdbs = poll_pdb()
        if pdbs is not None:
            new_pdb, seen_pdb = extract_blocked_pdbs(pdbs, seen_pdb)
            for p in new_pdb:
                detail = f"DisruptionBlocked(PDB): {p['ns']}/{p['name']} disruptionsAllowed=0"
                audit_append(audit_log, rule_id, "WARN", detail)
                total["pdb"] += 1
                print(f"[WARN] {detail}", flush=True)

        # 3. NodeClaim 비정상 (Karpenter 교체)
        ncs = poll_nc()
        if ncs is not None:
            new_nc, seen_nc = extract_bad_nodeclaims(ncs, seen_nc)
            for n in new_nc:
                detail = f"NodeClaimNotReady: {n['name']} reason={n['reason']} — {n['message'][:100]}"
                audit_append(audit_log, rule_id, "WARN", detail)
                total["nodeclaim"] += 1
                print(f"[WARN] {detail}", flush=True)

        sleep_fn(interval)

    summary = (f"DrainWatch finished: events={total['event']} pdb={total['pdb']} "
               f"nodeclaim={total['nodeclaim']} (FAIL={total['fail']})")
    audit_append(audit_log, rule_id, "FAIL" if total["fail"] else "INFO", summary)
    print(f"[drain_watch] {summary}", flush=True)
    return 1 if total["fail"] else 0


# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════
def main() -> int:
    import shutil

    parser = argparse.ArgumentParser(description="노드 드레인/교체 인라인 백그라운드 모니터")
    parser.add_argument("--phase", required=True, help="Phase 라벨 (예: P2, P4, P5)")
    parser.add_argument("--audit-log", required=True, help="audit.log 경로")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SEC,
                        help=f"폴링 간격 초 (기본: {DEFAULT_INTERVAL_SEC})")
    parser.add_argument("--max-duration", type=int, default=DEFAULT_MAX_DURATION_SEC,
                        help=f"최대 실행 시간 초 — 무한 실행 방지 (기본: {DEFAULT_MAX_DURATION_SEC})")
    parser.add_argument("--scope", choices=["all", "kube-system"], default="all",
                        help="이벤트 감시 범위 (Phase 2는 kube-system, Phase 4/5는 all)")
    parser.add_argument("--stop-file", default=None,
                        help="이 경로에 파일이 생기면 다음 사이클에 정상 종료")
    args = parser.parse_args()

    if shutil.which("kubectl") is None:
        print("ERROR: 'kubectl' not found in PATH.", file=sys.stderr)
        return 127

    return watch_loop(
        phase=args.phase,
        audit_log=args.audit_log,
        interval=args.interval,
        max_duration=args.max_duration,
        scope=args.scope,
        stop_file=args.stop_file,
    )


if __name__ == "__main__":
    sys.exit(main())
