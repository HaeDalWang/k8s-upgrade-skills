#!/usr/bin/env python3
"""
service_watch.py — 서비스 가용성 인라인 백그라운드 모니터

⚠️ Sub-Agent가 아니다. 메인 에이전트가 `run_in_background: true`로 띄우는
   결정적 폴링 스크립트다. (이유는 drain_watch.py / k8s-drain-monitor.md 참조 —
   동기 호출-반환 Agent 모델로는 "감시 중 즉시 보고"가 불가능.)

recipe의 `services`에 정의된 각 서비스에 대해 30초마다:
  - EndpointSlice ready 엔드포인트 수가 min_endpoints 미만이면 WARN
  - health_check_url(선택)이 non-2xx 또는 timeout이면 WARN
새 이상 신호만 `SVC-{PHASE}`로 audit.log에 한 줄씩 기록한다.

Usage:
  python3 scripts/service_watch.py --phase P4 --audit-log audit.log \
    --services-json '[{"name":"my-api","namespace":"prod","min_endpoints":2,"health_check_url":"https://api/health"}]' \
    [--interval 30] [--max-duration 3600] [--stop-file PATH]

종료 조건: --max-duration 초과 / KillShell / --stop-file 생성. (drain_watch.py와 동일)

Exit codes:
  0 = 정상 종료
  1 = 인자 오류 (services-json 파싱 실패 등)
"""

import argparse
import json
import os
import sys
import time

try:
    from lib import audit_append, run_cmd
except ImportError:
    print("ERROR: lib.py not found. Run install.sh --force to reinstall.", file=sys.stderr)
    sys.exit(1)

DEFAULT_INTERVAL_SEC = 30
DEFAULT_MAX_DURATION_SEC = 3600
HEALTH_TIMEOUT_SEC = 5


# ══════════════════════════════════════════════════════════════
# 순수 함수 (테스트 대상 — kubectl/curl 호출 없음)
# ══════════════════════════════════════════════════════════════
def count_ready_endpoints(es_json: dict) -> int:
    """EndpointSlice 목록에서 ready=True인 주소 수를 합산한다."""
    ready = 0
    for item in es_json.get("items", []):
        for ep in item.get("endpoints", []):
            if ep.get("conditions", {}).get("ready", False):
                ready += len(ep.get("addresses", []) or [])
    return ready


def evaluate_endpoint_state(name: str, ns: str, min_endpoints: int,
                            ready: int, seen: set) -> tuple:
    """엔드포인트 수를 min과 비교. degraded면 새 WARN 후보를 반환하고 seen 갱신.

    상태 기반 de-dup: degraded 동안 1회만 기록, 회복되면 seen에서 빼서 재발 시 재기록.
    반환: (warn: Optional[dict], updated_seen: set)
    """
    key = f"{ns}/{name}"
    new_seen = set(seen)
    if ready < min_endpoints:
        if key in seen:
            return None, new_seen
        new_seen.add(key)
        return {"ns": ns, "name": name, "ready": ready, "min": min_endpoints}, new_seen
    # 회복 — seen에서 제거
    new_seen.discard(key)
    return None, new_seen


def evaluate_health_state(name: str, ns: str, ok: bool, seen: set) -> tuple:
    """health check 결과를 상태 기반 de-dup. 반환: (warn: Optional[dict], updated_seen: set)."""
    key = f"{ns}/{name}:health"
    new_seen = set(seen)
    if not ok:
        if key in seen:
            return None, new_seen
        new_seen.add(key)
        return {"ns": ns, "name": name}, new_seen
    new_seen.discard(key)
    return None, new_seen


def parse_services(services_json: str) -> list:
    """--services-json 파싱 + 최소 필드 검증. 실패 시 ValueError."""
    data = json.loads(services_json)
    if not isinstance(data, list):
        raise ValueError("services-json must be a JSON array")
    out = []
    for svc in data:
        name = svc.get("name")
        ns = svc.get("namespace")
        if not name or not ns:
            raise ValueError(f"service missing name/namespace: {svc}")
        out.append({
            "name": name,
            "namespace": ns,
            "min_endpoints": int(svc.get("min_endpoints", 1)),
            "health_check_url": svc.get("health_check_url", "") or "",
        })
    return out


# ══════════════════════════════════════════════════════════════
# 폴링 (kubectl / curl — 실패 시 명확한 신호 반환)
# ══════════════════════════════════════════════════════════════
def poll_endpoints(name: str, ns: str):
    """서비스의 EndpointSlice ready 수. kubectl 실패 시 None."""
    r = run_cmd([
        "kubectl", "get", "endpointslices", "-n", ns,
        "-l", f"kubernetes.io/service-name={name}", "-o", "json",
    ], timeout=20)
    if r.returncode != 0:
        return None
    try:
        return count_ready_endpoints(json.loads(r.stdout))
    except json.JSONDecodeError:
        return None


def poll_health(url: str) -> bool:
    """health_check_url에 curl. 2xx면 True. 실패/timeout/비2xx면 False."""
    r = run_cmd([
        "curl", "-sf", "--max-time", str(HEALTH_TIMEOUT_SEC),
        "--retry", "1", "-o", "/dev/null", url,
    ], timeout=HEALTH_TIMEOUT_SEC + 5)
    return r.returncode == 0


def poll_service_exists(name: str, ns: str) -> bool:
    """서비스 존재 여부. kubectl get svc 성공(0)이면 True.

    recipe의 services 항목이 실제 클러스터와 다를 때(오타·릴리스명 누락 등)
    조용히 무시되지 않도록, 감시 시작 전에 존재를 확인하는 데 쓴다.
    """
    r = run_cmd(["kubectl", "get", "svc", "-n", ns, name, "-o", "name"], timeout=15)
    return r.returncode == 0


# ══════════════════════════════════════════════════════════════
# 감시 루프
# ══════════════════════════════════════════════════════════════
def watch_loop(phase: str, audit_log: str, services: list, interval: int,
               max_duration: int, stop_file: str = None,
               endpoints_fn=poll_endpoints, health_fn=poll_health,
               exists_fn=poll_service_exists,
               sleep_fn=time.sleep, clock=time.monotonic) -> int:
    """서비스 가용성 폴링 루프. 의존성 주입 가능(테스트용). 반환: exit code."""
    rule_id = f"SVC-{phase}"

    # 서비스 존재 사전 확인 — recipe에 잘못 적힌 서비스는 조용히 무시되지 않도록
    # WARN을 남기고 감시 대상에서 제외한다(없는 서비스의 ready=0 스팸 방지).
    present = []
    for svc in services:
        if exists_fn(svc["name"], svc["namespace"]):
            present.append(svc)
        else:
            msg = (f"{svc['namespace']}/{svc['name']}: Service 없음 — "
                   f"recipe services 항목을 실측(kubectl get svc)으로 확인하세요. 감시 대상에서 제외")
            audit_append(audit_log, rule_id, "WARN", msg)
            print(f"[WARN] {msg}", flush=True)
    services = present

    # BestEffort 경고 — health_check_url 없는 서비스는 EndpointSlice만 감시
    for svc in services:
        if not svc["health_check_url"]:
            msg = (f"{svc['namespace']}/{svc['name']}: health_check_url 미설정 — "
                   f"EndpointSlice만 감시 (BestEffort, 진정한 무중단 보장 불가)")
            audit_append(audit_log, rule_id, "INFO", msg)
            print(f"[INFO] {msg}", flush=True)

    ep_seen: set = set()
    health_seen: set = set()
    total = {"endpoint": 0, "health": 0}

    names = ", ".join(f"{s['namespace']}/{s['name']}" for s in services)
    print(f"[service_watch] started — phase={phase} services=[{names}] interval={interval}s", flush=True)
    audit_append(audit_log, rule_id, "INFO",
                 f"ServiceWatch started: {len(services)} service(s), interval={interval}s (inline background monitor)")

    start = clock()
    while clock() - start < max_duration:
        if stop_file and os.path.exists(stop_file):
            print("[service_watch] stop-file detected — terminating", flush=True)
            break

        for svc in services:
            name, ns = svc["name"], svc["namespace"]
            min_ep = svc["min_endpoints"]

            # 1. EndpointSlice ready 수
            ready = endpoints_fn(name, ns)
            if ready is not None:
                warn, ep_seen = evaluate_endpoint_state(name, ns, min_ep, ready, ep_seen)
                if warn:
                    detail = (f"{ns}/{name}: ready_endpoints={warn['ready']} < "
                              f"min={warn['min']} (EndpointSlice)")
                    audit_append(audit_log, rule_id, "WARN", detail)
                    total["endpoint"] += 1
                    print(f"[WARN] {detail}", flush=True)

            # 2. HTTP health check (url 있을 때만)
            url = svc["health_check_url"]
            if url:
                ok = health_fn(url)
                warn, health_seen = evaluate_health_state(name, ns, ok, health_seen)
                if warn:
                    detail = f"{ns}/{name}: health check 실패 (non-2xx 또는 timeout) — {url}"
                    audit_append(audit_log, rule_id, "WARN", detail)
                    total["health"] += 1
                    print(f"[WARN] {detail}", flush=True)

        sleep_fn(interval)

    summary = f"ServiceWatch finished: endpoint_warns={total['endpoint']} health_warns={total['health']}"
    audit_append(audit_log, rule_id, "INFO", summary)
    print(f"[service_watch] {summary}", flush=True)
    return 0


# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════
def main() -> int:
    import shutil

    parser = argparse.ArgumentParser(description="서비스 가용성 인라인 백그라운드 모니터")
    parser.add_argument("--phase", required=True, help="Phase 라벨 (예: P4, P5)")
    parser.add_argument("--audit-log", required=True, help="audit.log 경로")
    parser.add_argument("--services-json", required=True,
                        help="recipe services 필드의 JSON 배열")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SEC)
    parser.add_argument("--max-duration", type=int, default=DEFAULT_MAX_DURATION_SEC,
                        help=f"최대 실행 시간 초 (기본: {DEFAULT_MAX_DURATION_SEC})")
    parser.add_argument("--stop-file", default=None)
    args = parser.parse_args()

    for tool in ("kubectl", "curl"):
        if shutil.which(tool) is None:
            print(f"ERROR: '{tool}' not found in PATH.", file=sys.stderr)
            return 127

    try:
        services = parse_services(args.services_json)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"ERROR: --services-json 파싱 실패: {e}", file=sys.stderr)
        return 1

    if not services:
        print("ERROR: services가 비어있습니다.", file=sys.stderr)
        return 1

    return watch_loop(
        phase=args.phase, audit_log=args.audit_log, services=services,
        interval=args.interval, max_duration=args.max_duration,
        stop_file=args.stop_file,
    )


if __name__ == "__main__":
    sys.exit(main())
