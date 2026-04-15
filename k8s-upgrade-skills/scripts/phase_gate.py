#!/usr/bin/env python3
"""
phase_gate.py — Phase 2~7 Gate 검증

서브커맨드 방식으로 Phase 2~7 각각의 Gate를 검증한다.
  exit code 0   = PASS  (Gate OPEN — 다음 Phase 진행)
  exit code 1   = FAIL  (Gate BLOCKED — 즉시 중단)
  exit code 2   = WARN  (사용자 확인 필요)
  exit code 127 = CLI 도구 미존재

Usage:
  python3 scripts/phase_gate.py phase2 --cluster-name X --target-version Y [--audit-log FILE]
  python3 scripts/phase_gate.py phase3 --cluster-name X [--audit-log FILE]
  python3 scripts/phase_gate.py phase4 --cluster-name X --target-version Y [--audit-log FILE]
  python3 scripts/phase_gate.py phase5 --target-version Y [--audit-log FILE]
  python3 scripts/phase_gate.py phase6 --tf-dir /path [--audit-log FILE]
  python3 scripts/phase_gate.py phase7 --cluster-name X --target-version Y [--audit-log FILE]
"""

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ══════════════════════════════════════════════════════════════
# 공통 헬퍼 import (lib.py)
# ══════════════════════════════════════════════════════════════
try:
    from lib import (  # noqa: F401
        run_cmd, kubectl_json,
        audit_init, audit_write, audit_flush, record, GateResult,
        RED, YELLOW, GREEN, CYAN, NC,
        SYSTEM_NS, ADDON_BAD_STATES,
        _gate, reset_gate,
    )
except ImportError:
    print("ERROR: lib.py not found. Run install.sh --force to reinstall.", file=sys.stderr)
    sys.exit(127)


# ══════════════════════════════════════════════════════════════
# CLI 도구 존재 확인
# ══════════════════════════════════════════════════════════════
def check_tool_exists(tools: list) -> None:
    """PATH에서 CLI 도구 존재 확인. 미존재 시 sys.exit(127)."""
    for tool in tools:
        if shutil.which(tool) is None:
            print(f"ERROR: '{tool}' not found in PATH.", file=sys.stderr)
            sys.exit(127)


# ══════════════════════════════════════════════════════════════
# Phase Gate 함수 (스텁 — 후속 태스크에서 구현)
# ══════════════════════════════════════════════════════════════
def gate_phase2(cluster_name: str, target_version: str, audit_log: str) -> int:
    """Phase 2: Control Plane 검증. 반환: exit code (0/1)."""
    reset_gate()
    audit_init(cluster_name, "", target_version)

    # aws eks describe-cluster 호출
    r = run_cmd(["aws", "eks", "describe-cluster", "--name", cluster_name, "--output", "json"])
    if r.returncode != 0:
        audit_write("PHASE2-CP", "FAIL", f"aws eks describe-cluster 실패 (exit {r.returncode})")
        print(f"{RED}❌ PHASE2-CP FAIL{NC}  aws eks describe-cluster 실패")
        audit_flush(audit_log)
        return 1

    try:
        cluster = json.loads(r.stdout).get("cluster", {})
    except json.JSONDecodeError:
        audit_write("PHASE2-CP", "FAIL", "JSON 파싱 실패")
        print(f"{RED}❌ PHASE2-CP FAIL{NC}  JSON 파싱 실패")
        audit_flush(audit_log)
        return 1

    status = cluster.get("status", "")
    version = cluster.get("version", "")

    if status == "ACTIVE" and version == target_version:
        audit_write("PHASE2-CP", "PASS", f"클러스터 ACTIVE, version={version}")
        print(f"{GREEN}✅ PHASE2-CP PASS{NC}  클러스터 ACTIVE, version={version}")
        audit_flush(audit_log)
        return 0
    else:
        detail = f"status={status}, version={version} (expected: ACTIVE, {target_version})"
        audit_write("PHASE2-CP", "FAIL", detail)
        print(f"{RED}❌ PHASE2-CP FAIL{NC}  {detail}")
        audit_flush(audit_log)
        return 1


def gate_phase3(cluster_name: str, audit_log: str) -> int:
    """Phase 3: Add-on + kube-system Pod 검증. 반환: exit code (0/1)."""
    reset_gate()
    audit_init(cluster_name, "", "")

    failed = False

    # 1. Add-on 상태 확인
    r = run_cmd(["aws", "eks", "list-addons", "--cluster-name", cluster_name, "--output", "json"])
    if r.returncode != 0:
        audit_write("PHASE3-ADDON", "FAIL", "aws eks list-addons 실패")
        print(f"{RED}❌ PHASE3-ADDON FAIL{NC}  aws eks list-addons 실패")
        audit_flush(audit_log)
        return 1

    try:
        addons = json.loads(r.stdout).get("addons", [])
    except json.JSONDecodeError:
        audit_write("PHASE3-ADDON", "FAIL", "Add-on 목록 JSON 파싱 실패")
        print(f"{RED}❌ PHASE3-ADDON FAIL{NC}  JSON 파싱 실패")
        audit_flush(audit_log)
        return 1

    bad_addons = []
    for addon in addons:
        r = run_cmd(["aws", "eks", "describe-addon", "--cluster-name", cluster_name, "--addon-name", addon, "--output", "json"])
        if r.returncode != 0:
            bad_addons.append(f"{addon}(조회실패)")
            continue
        try:
            status = json.loads(r.stdout).get("addon", {}).get("status", "")
        except json.JSONDecodeError:
            bad_addons.append(f"{addon}(JSON파싱실패)")
            continue
        if status != "ACTIVE":
            bad_addons.append(f"{addon}({status})")

    if bad_addons:
        detail = f"비정상 Add-on: {', '.join(bad_addons)}"
        audit_write("PHASE3-ADDON", "FAIL", detail)
        print(f"{RED}❌ PHASE3-ADDON FAIL{NC}  {detail}")
        failed = True
    else:
        audit_write("PHASE3-ADDON", "PASS", f"모든 Add-on ACTIVE ({len(addons)}개)")
        print(f"{GREEN}✅ PHASE3-ADDON PASS{NC}  모든 Add-on ACTIVE ({len(addons)}개)")

    # 2. kube-system Pod 상태 확인
    r = run_cmd(["kubectl", "get", "pods", "-n", "kube-system", "-o", "json"])
    if r.returncode != 0:
        audit_write("PHASE3-ADDON", "FAIL", "kubectl get pods -n kube-system 실패")
        print(f"{RED}❌ PHASE3-ADDON FAIL{NC}  kube-system Pod 조회 실패")
        audit_flush(audit_log)
        return 1

    try:
        pods = json.loads(r.stdout).get("items", [])
    except json.JSONDecodeError:
        audit_write("PHASE3-ADDON", "FAIL", "kube-system Pod JSON 파싱 실패")
        print(f"{RED}❌ PHASE3-ADDON FAIL{NC}  kube-system Pod JSON 파싱 실패")
        audit_flush(audit_log)
        return 1

    bad_pods = []
    for pod in pods:
        name = pod.get("metadata", {}).get("name", "?")
        phase = pod.get("status", {}).get("phase", "")
        if phase != "Running":
            bad_pods.append(f"{name}({phase})")
            continue
        # Check Ready condition
        conditions = pod.get("status", {}).get("conditions", [])
        ready = False
        for c in conditions:
            if c.get("type") == "Ready" and c.get("status") == "True":
                ready = True
                break
        if not ready:
            bad_pods.append(f"{name}(NotReady)")

    if bad_pods:
        detail = f"비정상 kube-system Pod: {', '.join(bad_pods)}"
        audit_write("PHASE3-ADDON", "FAIL", detail)
        print(f"{RED}❌ PHASE3-ADDON FAIL{NC}  {detail}")
        failed = True
    else:
        audit_write("PHASE3-ADDON", "PASS", f"모든 kube-system Pod Running+Ready ({len(pods)}개)")
        print(f"{GREEN}✅ PHASE3-ADDON PASS{NC}  모든 kube-system Pod Running+Ready ({len(pods)}개)")

    audit_flush(audit_log)
    return 1 if failed else 0


# ══════════════════════════════════════════════════════════════
# Pod 분류 (Phase 4/7 내부)
# ══════════════════════════════════════════════════════════════
@dataclass
class PodClassification:
    """unhealthy Pod를 TRANSIENT/STALE/BLOCKING 3단계로 분류한 결과."""
    transient: list = field(default_factory=list)   # [{"ns": str, "name": str, "node": str, "node_age_sec": int}]
    stale: list = field(default_factory=list)       # [{"ns": str, "name": str, "owner": str, "phase": str}]
    blocking: list = field(default_factory=list)    # [{"ns": str, "name": str, "reason": str, "pending_min": float}]


def classify_pods(pods_json: dict, nodes_json: dict, now=None) -> PodClassification:
    """unhealthy Pod를 TRANSIENT/STALE/BLOCKING 3단계로 분류."""
    if now is None:
        now = datetime.now(timezone.utc)

    result = PodClassification()

    # Build node creation time map
    node_creation = {}
    for node in nodes_json.get("items", []):
        name = node.get("metadata", {}).get("name", "")
        ts_str = node.get("metadata", {}).get("creationTimestamp", "")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                node_creation[name] = ts
            except ValueError:
                pass

    # Build owner → running pods map
    owner_has_running = set()
    all_pods = pods_json.get("items", [])
    for pod in all_pods:
        phase = pod.get("status", {}).get("phase", "")
        if phase == "Running":
            owners = pod.get("metadata", {}).get("ownerReferences", [])
            if owners:
                owner_has_running.add(owners[0].get("uid", ""))

    # Classify non-Running/non-Succeeded pods
    transient_set = set()  # track transient pod names to exclude from BLOCKING

    for pod in all_pods:
        phase = pod.get("status", {}).get("phase", "")
        if phase == "Succeeded":
            continue

        # Running Pod: 모든 컨테이너 ready 여부 확인
        if phase == "Running":
            container_statuses = pod.get("status", {}).get("containerStatuses", [])
            init_statuses = pod.get("status", {}).get("initContainerStatuses", [])
            all_ready = (
                all(cs.get("ready", False) for cs in container_statuses)
                and all(
                    cs.get("ready", False)
                    or cs.get("state", {}).get("terminated", {}).get("reason") == "Completed"
                    for cs in init_statuses
                )
            ) if container_statuses else True
            if all_ready:
                continue
            # NotReady Running Pod → 시간 기준 분류
            ns = pod.get("metadata", {}).get("namespace", "?")
            name = pod.get("metadata", {}).get("name", "?")
            not_ready = [cs.get("name", "?") for cs in container_statuses if not cs.get("ready", False)]
            ts_str = pod.get("metadata", {}).get("creationTimestamp", "")
            if ts_str:
                try:
                    pod_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    age_sec = (now - pod_ts).total_seconds()
                    if age_sec < 180:
                        result.transient.append({
                            "ns": ns, "name": name,
                            "node": pod.get("spec", {}).get("nodeName", ""),
                            "node_age_sec": int(age_sec),
                        })
                        continue
                    elif age_sec > 300:
                        result.blocking.append({
                            "ns": ns, "name": name,
                            "reason": f"NotReady containers: {','.join(not_ready)}",
                            "pending_min": round(age_sec / 60, 1),
                        })
                        continue
                except ValueError:
                    pass
            continue  # grace period (3~5분)

        ns = pod.get("metadata", {}).get("namespace", "?")
        name = pod.get("metadata", {}).get("name", "?")
        node_name = pod.get("spec", {}).get("nodeName", "")
        pod_key = f"{ns}/{name}"

        # 1. TRANSIENT check
        if phase == "Pending" and node_name and node_name in node_creation:
            node_age = (now - node_creation[node_name]).total_seconds()
            if node_age < 180:
                result.transient.append({
                    "ns": ns, "name": name, "node": node_name,
                    "node_age_sec": int(node_age),
                })
                transient_set.add(pod_key)
                continue

        # 2. STALE check
        if phase in ("Error", "Failed"):
            owners = pod.get("metadata", {}).get("ownerReferences", [])
            if owners:
                owner_uid = owners[0].get("uid", "")
                if owner_uid and owner_uid in owner_has_running:
                    owner_name = owners[0].get("name", "?")
                    result.stale.append({
                        "ns": ns, "name": name, "owner": owner_name, "phase": phase,
                    })
                    continue

        # 3. BLOCKING check
        # CrashLoopBackOff / ImagePullBackOff
        is_crash_or_pull = False
        for cs in pod.get("status", {}).get("containerStatuses", []):
            waiting = cs.get("state", {}).get("waiting", {})
            reason = waiting.get("reason", "")
            if reason in ("CrashLoopBackOff", "ImagePullBackOff"):
                result.blocking.append({
                    "ns": ns, "name": name, "reason": reason, "pending_min": 0.0,
                })
                is_crash_or_pull = True
                break

        if is_crash_or_pull:
            continue

        # Pending > 5min (not TRANSIENT)
        if phase == "Pending" and pod_key not in transient_set:
            ts_str = pod.get("metadata", {}).get("creationTimestamp", "")
            if ts_str:
                try:
                    pod_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    pending_sec = (now - pod_ts).total_seconds()
                    if pending_sec > 300:
                        result.blocking.append({
                            "ns": ns, "name": name, "reason": "Pending>5min",
                            "pending_min": round(pending_sec / 60, 1),
                        })
                except ValueError:
                    pass

    return result


def gate_phase4(cluster_name: str, target_version: str, audit_log: str) -> int:
    """Phase 4: 노드 버전 + FailedEvict + Pod 분류. 반환: exit code (0/1/2)."""
    reset_gate()
    audit_init(cluster_name, "", target_version)

    exit_code = 0

    # 1. 노드 버전 + Ready 상태 확인
    r = run_cmd(["kubectl", "get", "nodes", "-o", "json"])
    if r.returncode != 0:
        audit_write("PHASE4-DATAPLANE", "FAIL", "kubectl get nodes 실패")
        print(f"{RED}❌ PHASE4-DATAPLANE FAIL{NC}  노드 조회 실패")
        audit_flush(audit_log)
        return 1

    try:
        nodes = json.loads(r.stdout).get("items", [])
    except json.JSONDecodeError:
        audit_write("PHASE4-DATAPLANE", "FAIL", "노드 JSON 파싱 실패")
        print(f"{RED}❌ PHASE4-DATAPLANE FAIL{NC}  노드 JSON 파싱 실패")
        audit_flush(audit_log)
        return 1

    if not target_version:
        audit_write("PHASE4-DATAPLANE", "FAIL", "target_version이 비어있음")
        print(f"{RED}❌ PHASE4-DATAPLANE FAIL{NC}  target_version이 비어있음")
        audit_flush(audit_log)
        return 1
    version_pattern = re.compile(rf"v{re.escape(target_version)}\.")
    bad_nodes = []
    for node in nodes:
        name = node.get("metadata", {}).get("name", "?")
        kubelet_ver = node.get("status", {}).get("nodeInfo", {}).get("kubeletVersion", "")
        conditions = {
            c.get("type", ""): c.get("status", "")
            for c in node.get("status", {}).get("conditions", [])
            if c.get("type")
        }
        ready = conditions.get("Ready", "False")

        if not version_pattern.match(kubelet_ver):
            bad_nodes.append(f"{name}(version={kubelet_ver})")
        elif ready != "True":
            bad_nodes.append(f"{name}(NotReady)")

    if bad_nodes:
        detail = f"비정상 노드: {', '.join(bad_nodes)}"
        audit_write("PHASE4-DATAPLANE", "FAIL", detail)
        print(f"{RED}❌ PHASE4-DATAPLANE FAIL{NC}  {detail}")
        audit_flush(audit_log)
        return 1
    else:
        audit_write("PHASE4-DATAPLANE", "PASS", f"모든 노드 v{target_version}.x + Ready ({len(nodes)}개)")
        print(f"{GREEN}✅ PHASE4-DATAPLANE PASS{NC}  모든 노드 v{target_version}.x + Ready ({len(nodes)}개)")

    # 2. FailedEvict 이벤트 확인
    r = run_cmd(["kubectl", "get", "events", "-A", "--field-selector", "reason=FailedEvict", "-o", "json"])
    if r.returncode == 0:
        try:
            events = json.loads(r.stdout).get("items", [])
        except json.JSONDecodeError:
            events = []

        if events:
            affected = []
            for evt in events:
                ns = evt.get("metadata", {}).get("namespace", "?")
                msg = evt.get("message", "")
                affected.append(f"{ns}: {msg[:80]}")
            detail = f"FailedEvict 이벤트 {len(events)}개: {'; '.join(affected[:5])}"
            audit_write("PHASE4-DATAPLANE", "FAIL", detail)
            print(f"{RED}❌ PHASE4-DATAPLANE FAIL{NC}  {detail}")
            audit_flush(audit_log)
            return 1
        else:
            audit_write("PHASE4-DATAPLANE", "PASS", "FailedEvict 이벤트 없음")
            print(f"{GREEN}✅ PHASE4-DATAPLANE PASS{NC}  FailedEvict 이벤트 없음")

    # 3. Pod 분류
    r = run_cmd(["kubectl", "get", "pods", "-A", "-o", "json"])
    if r.returncode != 0:
        audit_write("PHASE4-DATAPLANE", "FAIL", "kubectl get pods 실패")
        print(f"{RED}❌ PHASE4-DATAPLANE FAIL{NC}  Pod 조회 실패")
        audit_flush(audit_log)
        return 1

    try:
        pods_json = json.loads(r.stdout)
    except json.JSONDecodeError:
        audit_write("PHASE4-DATAPLANE", "FAIL", "Pod JSON 파싱 실패")
        print(f"{RED}❌ PHASE4-DATAPLANE FAIL{NC}  Pod JSON 파싱 실패")
        audit_flush(audit_log)
        return 1

    # Reuse nodes parsed earlier
    nodes_json = {"items": nodes}

    classification = classify_pods(pods_json, nodes_json)

    if classification.blocking:
        detail = f"BLOCKING Pod {len(classification.blocking)}개: {', '.join(p['ns']+'/'+p['name'] for p in classification.blocking[:5])}"
        audit_write("PHASE4-DATAPLANE", "FAIL", detail)
        print(f"{RED}❌ PHASE4-DATAPLANE FAIL{NC}  {detail}")
        exit_code = 1
    elif classification.stale or classification.transient:
        if classification.stale:
            detail = f"STALE Pod {len(classification.stale)}개: {', '.join(p['ns']+'/'+p['name'] for p in classification.stale[:5])} — 삭제 필요"
            audit_write("PHASE4-DATAPLANE", "WARN", detail)
            print(f"{YELLOW}⚠️ PHASE4-DATAPLANE WARN{NC}  {detail}")
        if classification.transient:
            detail = f"TRANSIENT Pod {len(classification.transient)}개: {', '.join(p['ns']+'/'+p['name'] for p in classification.transient[:5])} — 재확인 필요"
            audit_write("PHASE4-DATAPLANE", "WARN", detail)
            print(f"{YELLOW}⚠️ PHASE4-DATAPLANE WARN{NC}  {detail}")
        exit_code = 2
    else:
        audit_write("PHASE4-DATAPLANE", "PASS", "unhealthy Pod 없음")
        print(f"{GREEN}✅ PHASE4-DATAPLANE PASS{NC}  unhealthy Pod 없음")

    audit_flush(audit_log)
    return exit_code


def gate_phase5(target_version: str, audit_log: str) -> int:
    """Phase 5: Karpenter 노드 검증. 반환: exit code (0/1)."""
    reset_gate()
    audit_init("", "", target_version)

    # 1. Karpenter CRD 존재 확인
    r = run_cmd(["kubectl", "get", "crd", "nodeclaims.karpenter.sh"])
    if r.returncode != 0:
        audit_write("PHASE5-KARPENTER", "PASS", "Karpenter 미사용 — SKIP")
        print(f"{CYAN}⏭️ PHASE5-KARPENTER SKIP{NC}  Karpenter 미사용")
        audit_flush(audit_log)
        return 0

    # 2. Karpenter 노드 버전 + Ready 확인
    r = run_cmd(["kubectl", "get", "nodes", "-l", "karpenter.sh/nodepool", "-o", "json"])
    if r.returncode != 0:
        audit_write("PHASE5-KARPENTER", "FAIL", "Karpenter 노드 조회 실패")
        print(f"{RED}❌ PHASE5-KARPENTER FAIL{NC}  Karpenter 노드 조회 실패")
        audit_flush(audit_log)
        return 1

    try:
        nodes = json.loads(r.stdout).get("items", [])
    except json.JSONDecodeError:
        audit_write("PHASE5-KARPENTER", "FAIL", "Karpenter 노드 JSON 파싱 실패")
        print(f"{RED}❌ PHASE5-KARPENTER FAIL{NC}  JSON 파싱 실패")
        audit_flush(audit_log)
        return 1

    if not nodes:
        audit_write("PHASE5-KARPENTER", "PASS", "Karpenter 노드 0개 — SKIP")
        print(f"{CYAN}⏭️ PHASE5-KARPENTER SKIP{NC}  Karpenter 노드 0개")
        audit_flush(audit_log)
        return 0

    if not target_version:
        audit_write("PHASE5-KARPENTER", "FAIL", "target_version이 비어있음")
        print(f"{RED}❌ PHASE5-KARPENTER FAIL{NC}  target_version이 비어있음")
        audit_flush(audit_log)
        return 1
    version_pattern = re.compile(rf"v{re.escape(target_version)}\.")
    bad_nodes = []
    for node in nodes:
        name = node.get("metadata", {}).get("name", "?")
        kubelet_ver = node.get("status", {}).get("nodeInfo", {}).get("kubeletVersion", "")
        conditions = {
            c.get("type", ""): c.get("status", "")
            for c in node.get("status", {}).get("conditions", [])
            if c.get("type")
        }
        ready = conditions.get("Ready", "False")

        if not version_pattern.match(kubelet_ver):
            bad_nodes.append(f"{name}(version={kubelet_ver})")
        elif ready != "True":
            bad_nodes.append(f"{name}(NotReady)")

    if bad_nodes:
        detail = f"비정상 Karpenter 노드: {', '.join(bad_nodes)}"
        audit_write("PHASE5-KARPENTER", "FAIL", detail)
        print(f"{RED}❌ PHASE5-KARPENTER FAIL{NC}  {detail}")
        audit_flush(audit_log)
        return 1
    else:
        audit_write("PHASE5-KARPENTER", "PASS", f"모든 Karpenter 노드 v{target_version}.x + Ready ({len(nodes)}개)")
        print(f"{GREEN}✅ PHASE5-KARPENTER PASS{NC}  모든 Karpenter 노드 v{target_version}.x + Ready ({len(nodes)}개)")
        audit_flush(audit_log)
        return 0


def gate_phase6(tf_dir: str, audit_log: str) -> int:
    """Phase 6: Terraform plan JSON 분석. 반환: exit code (0/1)."""
    reset_gate()
    audit_init("", "", "")

    from pathlib import Path as _Path
    import subprocess as _sp

    tf_dir = str(_Path(tf_dir).resolve())  # 상대→절대 변환
    tfplan_path = _Path(tf_dir) / ".tfplan"

    try:
        # 1. terraform plan
        try:
            plan_result = _sp.run(
                ["terraform", "plan", f"-out={tfplan_path}"],
                capture_output=True, text=True, cwd=tf_dir, timeout=300,
            )
        except (_sp.TimeoutExpired, FileNotFoundError) as e:
            audit_write("PHASE6-TFSYNC", "FAIL", f"terraform plan 실행 실패: {e}")
            print(f"{RED}❌ PHASE6-TFSYNC FAIL{NC}  terraform plan 실행 실패")
            audit_flush(audit_log)
            return 1

        if plan_result.returncode != 0 and plan_result.returncode != 2:
            audit_write("PHASE6-TFSYNC", "FAIL", f"terraform plan 실패 (exit {plan_result.returncode})")
            print(f"{RED}❌ PHASE6-TFSYNC FAIL{NC}  terraform plan 실패 (exit {plan_result.returncode})")
            audit_flush(audit_log)
            return 1

        # 2. terraform show -json
        try:
            show_result = _sp.run(
                ["terraform", "show", "-json", str(tfplan_path)],
                capture_output=True, text=True, cwd=tf_dir, timeout=60,
            )
        except (_sp.TimeoutExpired, FileNotFoundError) as e:
            audit_write("PHASE6-TFSYNC", "FAIL", f"terraform show 실행 실패: {e}")
            print(f"{RED}❌ PHASE6-TFSYNC FAIL{NC}  terraform show 실행 실패")
            audit_flush(audit_log)
            return 1

        if show_result.returncode != 0:
            audit_write("PHASE6-TFSYNC", "FAIL", f"terraform show 실패 (exit {show_result.returncode})")
            print(f"{RED}❌ PHASE6-TFSYNC FAIL{NC}  terraform show 실패")
            audit_flush(audit_log)
            return 1

        try:
            plan_json = json.loads(show_result.stdout)
        except json.JSONDecodeError:
            audit_write("PHASE6-TFSYNC", "FAIL", "terraform show JSON 파싱 실패")
            print(f"{RED}❌ PHASE6-TFSYNC FAIL{NC}  JSON 파싱 실패")
            audit_flush(audit_log)
            return 1

        # 3. resource_changes 분석 (no-op/read 제외)
        resource_changes = [
            rc for rc in plan_json.get("resource_changes", [])
            if rc.get("change", {}).get("actions", []) not in (["no-op"], ["read"])
        ]

        if not resource_changes:
            audit_write("PHASE6-TFSYNC", "PASS", "변경 없음 (no changes)")
            print(f"{GREEN}✅ PHASE6-TFSYNC PASS{NC}  변경 없음")
            audit_flush(audit_log)
            return 0

        # recreate 감지: actions == ["delete", "create"] or ["create", "delete"]
        recreate_resources = []
        for rc_entry in resource_changes:
            actions = rc_entry.get("change", {}).get("actions", [])
            if set(actions) == {"delete", "create"} and len(actions) == 2:
                addr = rc_entry.get("address", "?")
                rtype = rc_entry.get("type", "?")
                recreate_resources.append(f"{rtype}({addr})")

        if recreate_resources:
            detail = f"recreate 감지: {', '.join(recreate_resources)}"
            audit_write("PHASE6-TFSYNC", "FAIL", detail)
            print(f"{RED}❌ PHASE6-TFSYNC FAIL{NC}  {detail}")
            audit_flush(audit_log)
            return 1
        else:
            audit_write("PHASE6-TFSYNC", "PASS", f"비파괴적 변경만 존재 ({len(resource_changes)}개)")
            print(f"{GREEN}✅ PHASE6-TFSYNC PASS{NC}  비파괴적 변경만 존재 ({len(resource_changes)}개)")
            audit_flush(audit_log)
            return 0

    finally:
        tfplan_path.unlink(missing_ok=True)


def gate_phase7(cluster_name: str, target_version: str, audit_log: str) -> int:
    """Phase 7: phase2+3+4 함수 호출 + Insights. 반환: exit code (0/1/2)."""
    import os
    import tempfile
    from pathlib import Path as _Path

    sub_results = {}

    # 1. Call sub-gates — each writes to temp audit, then append to main audit
    def _run_sub_gate(name, gate_fn, *args):
        with tempfile.TemporaryDirectory() as tmpdir:
            sub_audit = os.path.join(tmpdir, "sub_audit.log")
            rc = gate_fn(*args, sub_audit)
            # Append sub-gate audit to main audit log
            sub_path = _Path(sub_audit)
            if sub_path.exists():
                main_path = _Path(audit_log)
                with main_path.open("a", encoding="utf-8") as f:
                    f.write(f"\n# --- Phase 7: sub-gate {name} ---\n")
                    f.write(sub_path.read_text(encoding="utf-8"))
            return rc

    sub_results["phase2"] = _run_sub_gate("phase2", gate_phase2, cluster_name, target_version)
    sub_results["phase3"] = _run_sub_gate("phase3", gate_phase3, cluster_name)
    sub_results["phase4"] = _run_sub_gate("phase4", gate_phase4, cluster_name, target_version)

    # 2. Now init our own audit session (sub-gates cleared state via reset_gate)
    reset_gate()
    audit_init(cluster_name, "", target_version)

    # 3. EKS Insights
    r = run_cmd(["aws", "eks", "list-insights", "--cluster-name", cluster_name, "--output", "json"])
    insights_rc = 0
    if r.returncode == 0:
        try:
            insights = json.loads(r.stdout).get("insights", [])
            non_passing = [i for i in insights if i.get("insightStatus", {}).get("status") != "PASSING"]
            if non_passing:
                names = [i.get("name", "?") for i in non_passing[:5]]
                detail = f"비정상 Insight: {', '.join(names)}"
                audit_write("PHASE7-FINAL", "FAIL", detail)
                print(f"{RED}❌ PHASE7-FINAL FAIL{NC}  {detail}")
                insights_rc = 1
            else:
                audit_write("PHASE7-FINAL", "PASS", f"모든 Insight PASSING ({len(insights)}개)")
                print(f"{GREEN}✅ PHASE7-FINAL PASS{NC}  모든 Insight PASSING ({len(insights)}개)")
        except json.JSONDecodeError:
            audit_write("PHASE7-FINAL", "FAIL", "Insights JSON 파싱 실패")
            print(f"{RED}❌ PHASE7-FINAL FAIL{NC}  Insights JSON 파싱 실패")
            insights_rc = 1
    else:
        audit_write("PHASE7-FINAL", "FAIL", "aws eks list-insights 실패")
        print(f"{RED}❌ PHASE7-FINAL FAIL{NC}  aws eks list-insights 실패")
        insights_rc = 1

    sub_results["insights"] = insights_rc

    # 4. Write individual sub-gate results to audit
    for name, rc in sub_results.items():
        result_str = {0: "PASS", 1: "FAIL", 2: "WARN"}.get(rc, f"UNKNOWN({rc})")
        audit_write("PHASE7-FINAL", result_str, f"sub-gate {name}: exit {rc}")

    # 5. Aggregate exit codes: FAIL(1) > WARN(2) > PASS(0)
    all_codes = list(sub_results.values())
    if 1 in all_codes:
        final_rc = 1
        audit_write("PHASE7-FINAL", "FAIL", "최종 판정: FAIL")
        print(f"\n{RED}❌ PHASE7-FINAL: FAIL{NC}")
    elif 2 in all_codes:
        final_rc = 2
        audit_write("PHASE7-FINAL", "WARN", "최종 판정: WARN")
        print(f"\n{YELLOW}⚠️ PHASE7-FINAL: WARN{NC}")
    else:
        final_rc = 0
        audit_write("PHASE7-FINAL", "PASS", "최종 판정: PASS")
        print(f"\n{GREEN}✅ PHASE7-FINAL: PASS{NC}")

    audit_flush(audit_log)
    return final_rc


# ══════════════════════════════════════════════════════════════
# 서브커맨드별 CLI 도구 의존성
# ══════════════════════════════════════════════════════════════
TOOL_DEPS: dict = {
    "phase2": ["aws"],
    "phase3": ["aws", "kubectl"],
    "phase4": ["kubectl"],
    "phase5": ["kubectl"],
    "phase6": ["terraform"],
    "phase7": ["aws", "kubectl"],
}


# ══════════════════════════════════════════════════════════════
# main — argparse + 디스패치
# ══════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 2~7 Gate 검증 (phase_gate.py)",
    )
    subparsers = parser.add_subparsers(dest="phase", required=True)

    # ── phase2: Control Plane 검증 ──
    p2 = subparsers.add_parser("phase2", help="Phase 2: Control Plane 검증")
    p2.add_argument("--cluster-name", required=True)
    p2.add_argument("--target-version", required=True)
    p2.add_argument("--audit-log", default="audit.log")

    # ── phase3: Add-on Safety 검증 ──
    p3 = subparsers.add_parser("phase3", help="Phase 3: Add-on Safety 검증")
    p3.add_argument("--cluster-name", required=True)
    p3.add_argument("--audit-log", default="audit.log")

    # ── phase4: Data Plane 검증 ──
    p4 = subparsers.add_parser("phase4", help="Phase 4: Data Plane 검증")
    p4.add_argument("--cluster-name", required=True)
    p4.add_argument("--target-version", required=True)
    p4.add_argument("--audit-log", default="audit.log")

    # ── phase5: Karpenter 노드 검증 ──
    p5 = subparsers.add_parser("phase5", help="Phase 5: Karpenter 노드 검증")
    p5.add_argument("--target-version", required=True)
    p5.add_argument("--audit-log", default="audit.log")

    # ── phase6: Terraform Sync 검증 ──
    p6 = subparsers.add_parser("phase6", help="Phase 6: Terraform Sync 검증")
    p6.add_argument("--tf-dir", required=True)
    p6.add_argument("--audit-log", default="audit.log")

    # ── phase7: Final Validation 검증 ──
    p7 = subparsers.add_parser("phase7", help="Phase 7: Final Validation 검증")
    p7.add_argument("--cluster-name", required=True)
    p7.add_argument("--target-version", required=True)
    p7.add_argument("--audit-log", default="audit.log")

    args = parser.parse_args()

    # CLI 도구 의존성 확인
    check_tool_exists(TOOL_DEPS[args.phase])

    # 서브커맨드 디스패치
    if args.phase == "phase2":
        rc = gate_phase2(args.cluster_name, args.target_version, args.audit_log)
    elif args.phase == "phase3":
        rc = gate_phase3(args.cluster_name, args.audit_log)
    elif args.phase == "phase4":
        rc = gate_phase4(args.cluster_name, args.target_version, args.audit_log)
    elif args.phase == "phase5":
        rc = gate_phase5(args.target_version, args.audit_log)
    elif args.phase == "phase6":
        rc = gate_phase6(args.tf_dir, args.audit_log)
    elif args.phase == "phase7":
        rc = gate_phase7(args.cluster_name, args.target_version, args.audit_log)
    else:
        parser.print_help()
        rc = 1

    sys.exit(rc)


if __name__ == "__main__":
    main()
