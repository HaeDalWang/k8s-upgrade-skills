#!/usr/bin/env python3
"""
gate_check.py — Phase 0 사전 검증 (17개 규칙 전체)

이 스크립트가 Gate를 판단합니다.
  exit code 0 = Gate OPEN  (진행 가능)
  exit code 1 = Gate BLOCKED (CRITICAL 실패 존재)
  exit code 2 = Gate WARN  (HIGH 경고, 사용자 확인 필요)

Usage:
  python3 scripts/gate_check.py \\
    --cluster-name my-cluster \\
    --current-version 1.33 \\
    --target-version 1.34 \\
    [--tf-dir /path/to/terraform] \\
    [--audit-log audit.log]

17개 사전 검증 규칙을 실행합니다.
--tf-dir 제공 시 INF-001/INF-004 (Terraform drift/recreate) 검증을 추가 실행합니다.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ══════════════════════════════════════════════════════════════
# 공통 헬퍼 import (lib.py)
# ══════════════════════════════════════════════════════════════
try:
    import lib as _lib
    from lib import (
        run_cmd, kubectl_json, _parse_cpu, _parse_mem,
        audit_init, audit_write, audit_flush, record, GateResult,
        RED, YELLOW, GREEN, CYAN, NC,
        SYSTEM_NS, DATA_PLANE_RESOURCES, ADDON_BAD_STATES,
        _gate,
    )
except ImportError:
    print("ERROR: lib.py not found. Run install.sh --force to reinstall.", file=sys.stderr)
    sys.exit(127)

# ── 모듈 레벨 mutable 변수 프록시 (하위 호환) ──
# gate_check.critical_fail 등의 접근 패턴을 lib 모듈로 위임
_MUTABLE_ATTRS = frozenset({
    "critical_fail", "high_warn", "medium_info",
    "total_pass", "total_rules", "audit_lines",
})


def __getattr__(name: str):
    if name in _MUTABLE_ATTRS:
        return getattr(_lib, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _sync_from_gate() -> None:
    """_gate → lib 모듈 레벨 변수 동기화 (gate_check 호환 래퍼)."""
    _lib._sync_from_gate()
    # gate_check.__dict__에 직접 설정된 로컬 오버라이드 제거 → __getattr__ 프록시 복원
    import sys as _sys
    _mod = _sys.modules[__name__]
    for attr in _MUTABLE_ATTRS:
        _mod.__dict__.pop(attr, None)


def _sync_to_gate() -> None:
    """gate_check/lib 모듈 레벨 변수 → _gate 동기화 (gate_check 호환 래퍼).

    테스트에서 gate_check.critical_fail = N 으로 직접 설정한 경우,
    해당 값을 lib 모듈로 전파한 후 _gate에 동기화한다.
    """
    import sys as _sys
    _mod = _sys.modules[__name__]
    for attr in _MUTABLE_ATTRS:
        if attr in _mod.__dict__:
            setattr(_lib, attr, _mod.__dict__[attr])
    _lib._sync_to_gate()


def reset_gate() -> None:
    """글로벌 Gate 상태 초기화 (gate_check 호환 래퍼)."""
    _lib.reset_gate()
    # gate_check.__dict__에 직접 설정된 로컬 오버라이드 제거
    import sys as _sys
    _mod = _sys.modules[__name__]
    for attr in _MUTABLE_ATTRS:
        _mod.__dict__.pop(attr, None)

# ══════════════════════════════════════════════════════════════
# Phase 0 전용 상수 및 정규식
# ══════════════════════════════════════════════════════════════

# ── INF-004 Recreate 마커 정규식 ──
RECREATE_MARKERS = re.compile(r"forces replacement|must be replaced")
REPLACE_PREFIX = re.compile(r"^\s*-/\+\s+resource\s+\"(\w+)\"\s+\"(\w+)\"", re.MULTILINE)

# ── INF-001 Destroy/Recreate 패턴 ──
DESTROY_PATTERN = re.compile(r"Plan:.*\d+\s+to\s+destroy")


# ══════════════════════════════════════════════════════════════
# COM-002: 버전 호환성 검증 (CRITICAL)
# ══════════════════════════════════════════════════════════════
def check_com002(current_version: str, target_version: str) -> None:
    curr_parts = current_version.split(".")
    targ_parts = target_version.split(".")
    if len(curr_parts) < 2 or len(targ_parts) < 2:
        record("COM-002", "CRITICAL", "FAIL",
               f"버전 형식 오류 ({current_version} → {target_version}) → 'X.Y' 형식이어야 합니다")
        return
    curr_minor = int(curr_parts[1])
    targ_minor = int(targ_parts[1])
    gap = targ_minor - curr_minor

    if gap == 1:
        record("COM-002", "CRITICAL", "PASS",
               f"버전 gap=1 ({current_version} → {target_version})")
    elif gap == 0:
        record("COM-002", "CRITICAL", "SKIP", "이미 동일 버전")
    elif gap > 1:
        record("COM-002", "CRITICAL", "FAIL",
               f"버전 건너뛰기 불가 (gap={gap}) → 한 단계씩 업그레이드하세요 (예: 1.33→1.34→1.35)")
    else:
        record("COM-002", "CRITICAL", "FAIL",
               f"다운그레이드 불가 (gap={gap}) → target_version이 current_version보다 높아야 합니다")


# ══════════════════════════════════════════════════════════════
# COM-001: 클러스터 기본 상태 검증 (CRITICAL)
# ══════════════════════════════════════════════════════════════
def check_com001(cluster_name: str) -> None:
    # 1. EKS 클러스터 상태
    r = run_cmd([
        "aws", "eks", "describe-cluster",
        "--name", cluster_name,
        "--query", "cluster.status",
        "--output", "text",
    ])
    status = r.stdout.strip() if r.returncode == 0 else "ERROR"

    if status != "ACTIVE":
        record("COM-001", "CRITICAL", "FAIL",
               f"클러스터 상태: {status} (ACTIVE 아님) → 클러스터가 ACTIVE 상태가 될 때까지 대기하세요")
        return

    # 2. 노드 상태
    nodes = kubectl_json("nodes", all_ns=False)
    if not nodes:
        record("COM-001", "CRITICAL", "FAIL", "kubectl 연결 실패")
        return

    not_ready = 0
    pressure = 0
    for node in nodes.get("items", []):
        conditions = {
            c["type"]: c["status"]
            for c in node.get("status", {}).get("conditions", [])
        }
        if conditions.get("Ready") != "True":
            not_ready += 1
        for ctype in ("MemoryPressure", "DiskPressure", "PIDPressure"):
            if conditions.get(ctype) == "True":
                pressure += 1

    if not_ready > 0:
        record("COM-001", "CRITICAL", "FAIL",
               f"NotReady 노드 {not_ready}개 → kubectl describe node로 원인 확인 후 복구하세요")
        return
    if pressure > 0:
        record("COM-001", "CRITICAL", "FAIL",
               f"리소스 압박 노드 {pressure}개 → 노드 리소스 확보 또는 스케일아웃 후 재시도하세요")
        return

    record("COM-001", "CRITICAL", "PASS",
           "클러스터 ACTIVE, 전 노드 Ready, 압박 없음")


# ══════════════════════════════════════════════════════════════
# COM-002a: kubelet 버전 skew 검증 (CRITICAL)
# https://kubernetes.io/releases/version-skew-policy/
# K8s 1.28+: kubelet skew 허용 n-3, 미만: n-2
# ══════════════════════════════════════════════════════════════
def check_com002a(target_version: str) -> None:
    targ_parts = target_version.split(".")
    if len(targ_parts) < 2:
        record("COM-002a", "CRITICAL", "FAIL",
               f"버전 형식 오류 ({target_version}) → 'X.Y' 형식이어야 합니다")
        return
    targ_minor = int(targ_parts[1])
    # K8s 1.28부터 kubelet skew 정책이 n-3으로 완화됨
    max_skew = 3 if targ_minor >= 28 else 2
    nodes = kubectl_json("nodes", all_ns=False)
    violations = 0
    for node in nodes.get("items", []):
        ver = node.get("status", {}).get("nodeInfo", {}).get("kubeletVersion", "")
        if not ver:
            continue
        ver_parts = ver.split(".")
        if len(ver_parts) < 2:
            continue
        node_minor = int(ver_parts[1])
        if targ_minor - node_minor > max_skew:
            violations += 1

    if violations > 0:
        record("COM-002a", "CRITICAL", "FAIL",
               f"kubelet skew > {max_skew} 노드 {violations}개 → 해당 노드의 kubelet을 먼저 업그레이드하세요")
    else:
        record("COM-002a", "CRITICAL", "PASS",
               f"kubelet skew 정상 (모두 ≤ {max_skew})")


# ══════════════════════════════════════════════════════════════
# COM-003: Add-on 호환성 검증 (HIGH)
# ══════════════════════════════════════════════════════════════
def check_com003(cluster_name: str, target_version: str) -> None:
    """COM-003: EKS Add-on 상태 및 TARGET_VERSION 호환성 검증."""
    # 1. Add-on 목록 조회
    r = run_cmd([
        "aws", "eks", "list-addons",
        "--cluster-name", cluster_name,
        "--output", "json",
    ])
    if r.returncode != 0:
        record("COM-003", "HIGH", "FAIL", "Add-on 목록 조회 실패")
        return

    try:
        addons = json.loads(r.stdout).get("addons", [])
    except json.JSONDecodeError:
        record("COM-003", "HIGH", "FAIL", "Add-on 목록 JSON 파싱 실패")
        return

    if not addons:
        record("COM-003", "HIGH", "PASS", "Add-on 없음")
        return

    # 2. 각 Add-on 상태 확인
    bad_addons: list[str] = []
    for addon in addons:
        r = run_cmd([
            "aws", "eks", "describe-addon",
            "--cluster-name", cluster_name,
            "--addon-name", addon,
            "--output", "json",
        ])
        if r.returncode != 0:
            continue
        try:
            status = json.loads(r.stdout).get("addon", {}).get("status", "")
        except json.JSONDecodeError:
            continue
        if status in ADDON_BAD_STATES:
            bad_addons.append(f"{addon}({status})")

    if bad_addons:
        record("COM-003", "HIGH", "FAIL",
               f"비정상 Add-on: {', '.join(bad_addons)} → aws eks update-addon --resolve-conflicts OVERWRITE로 복구하세요")
        return

    # 3. TARGET_VERSION 호환 버전 확인
    incompatible: list[str] = []
    for addon in addons:
        r = run_cmd([
            "aws", "eks", "describe-addon-versions",
            "--addon-name", addon,
            "--kubernetes-version", target_version,
            "--output", "json",
        ])
        if r.returncode != 0:
            incompatible.append(addon)
            continue
        try:
            versions = json.loads(r.stdout).get("addons", [])
        except json.JSONDecodeError:
            incompatible.append(addon)
            continue
        if not versions:
            incompatible.append(addon)

    if incompatible:
        record("COM-003", "HIGH", "FAIL",
               f"TARGET_VERSION {target_version} 비호환 Add-on: {', '.join(incompatible)} → Add-on 호환 버전 확인 후 업데이트하세요")
    else:
        record("COM-003", "HIGH", "PASS",
               f"모든 Add-on ACTIVE + {target_version} 호환")


# ══════════════════════════════════════════════════════════════
# WLS-001: PDB 차단 가능성 분석 (CRITICAL)
# ══════════════════════════════════════════════════════════════
def check_wls001() -> None:
    data = kubectl_json("pdb")
    blocked = 0
    for pdb in data.get("items", []):
        allowed = pdb.get("status", {}).get("disruptionsAllowed", 1)
        expected = pdb.get("status", {}).get("expectedPods", 0)
        if expected > 0 and allowed == 0:
            ns = pdb["metadata"]["namespace"]
            name = pdb["metadata"]["name"]
            print(f"  BLOCKED: {ns}/{name} (disruptionsAllowed=0)",
                  file=sys.stderr)
            blocked += 1

    if blocked > 0:
        record("WLS-001", "CRITICAL", "FAIL",
               f"PDB 차단 {blocked}개 (disruptionsAllowed=0) → PDB minAvailable 낮추기 또는 replicas 증가 필요")
    else:
        record("WLS-001", "CRITICAL", "PASS",
               "모든 PDB disruptionsAllowed >= 1")


# ══════════════════════════════════════════════════════════════
# WLS-002: 단일 레플리카 서비스 중단 위험 (HIGH)
# ══════════════════════════════════════════════════════════════
# (상수는 모듈 상단으로 이동됨)


def check_wls002() -> None:
    count = 0
    for kind in ("deployments", "statefulsets"):
        data = kubectl_json(kind)
        for item in data.get("items", []):
            ns = item["metadata"]["namespace"]
            if ns in SYSTEM_NS:
                continue
            replicas = item.get("spec", {}).get("replicas", 1)
            if replicas == 1:
                name = item["metadata"]["name"]
                k = item.get("kind", kind)
                print(f"  {ns}/{name} ({k}): replicas=1", file=sys.stderr)
                count += 1

    if count > 0:
        record("WLS-002", "HIGH", "FAIL",
               f"단일 레플리카 워크로드 {count}개 (다운타임 위험) → 업그레이드 전 replicas=2로 스케일업 권장")
    else:
        record("WLS-002", "HIGH", "PASS",
               "단일 레플리카 워크로드 없음")


# ══════════════════════════════════════════════════════════════
# WLS-003: PV 존 어피니티 재스케줄 불가 위험 (CRITICAL)
# ══════════════════════════════════════════════════════════════
def check_wls003() -> None:
    pvs = kubectl_json("pv", all_ns=False)
    nodes = kubectl_json("nodes", all_ns=False)

    if not pvs or not nodes:
        record("WLS-003", "CRITICAL", "PASS", "PV 또는 노드 조회 불가 — 건너뜀")
        return

    # AZ별 노드 수
    az_count: Counter = Counter()
    for n in nodes.get("items", []):
        az = n["metadata"].get("labels", {}).get(
            "topology.kubernetes.io/zone", "")
        if az:
            az_count[az] += 1

    # PV별 위험 판정
    risks = 0
    for pv in pvs.get("items", []):
        if pv.get("status", {}).get("phase") != "Bound":
            continue
        na = (pv.get("spec", {})
              .get("nodeAffinity", {})
              .get("required", {})
              .get("nodeSelectorTerms", []))
        for term in na:
            for expr in term.get("matchExpressions", []):
                if "zone" in expr.get("key", ""):
                    for az in expr.get("values", []):
                        if az_count.get(az, 0) <= 1:
                            claim = pv.get("spec", {}).get("claimRef", {})
                            ns = claim.get("namespace", "?")
                            name = claim.get("name", "?")
                            print(
                                f"  RISK: {ns}/{name} → AZ={az} "
                                f"(노드 {az_count.get(az, 0)}개)",
                                file=sys.stderr,
                            )
                            risks += 1

    if risks > 0:
        record("WLS-003", "CRITICAL", "FAIL",
               f"PV AZ 위험 {risks}개 (drain 시 재스케줄 불가) → 해당 AZ에 노드 추가 또는 PV 마이그레이션 필요")
    else:
        record("WLS-003", "CRITICAL", "PASS", "PV AZ 위험 없음")


# ══════════════════════════════════════════════════════════════
# WLS-004: 로컬 스토리지 Pod 데이터 유실 위험 (MEDIUM)
# ══════════════════════════════════════════════════════════════
def check_wls004() -> None:
    pods = kubectl_json("pods", timeout=60)
    if not pods:
        record("WLS-004", "MEDIUM", "PASS", "Pod 조회 불가 — 건너뜀")
        return

    hostpath_count = 0
    for pod in pods.get("items", []):
        ns = pod["metadata"]["namespace"]
        if ns in SYSTEM_NS:
            continue
        phase = pod.get("status", {}).get("phase", "")
        if phase not in ("Running", "Pending"):
            continue
        for vol in pod.get("spec", {}).get("volumes", []):
            if vol.get("hostPath") is not None:
                name = pod["metadata"]["name"]
                path = vol["hostPath"].get("path", "")
                print(f"  hostPath: {ns}/{name} path={path}",
                      file=sys.stderr)
                hostpath_count += 1

    if hostpath_count > 0:
        record("WLS-004", "MEDIUM", "FAIL",
               f"hostPath 사용 Pod {hostpath_count}개 (노드 교체 시 데이터 유실) → 데이터 백업 후 진행하거나 PVC로 마이그레이션 권장")
    else:
        record("WLS-004", "MEDIUM", "PASS",
               "hostPath 사용 Pod 없음")


# ══════════════════════════════════════════════════════════════
# WLS-005: 장시간 Job/CronJob 중단 위험 (MEDIUM)
# ══════════════════════════════════════════════════════════════
def check_wls005() -> None:
    pods = kubectl_json("pods", timeout=60)
    if not pods:
        record("WLS-005", "MEDIUM", "PASS", "Pod 조회 불가 — 건너뜀")
        return

    now = datetime.now(timezone.utc)
    risky_jobs = 0
    for pod in pods.get("items", []):
        phase = pod.get("status", {}).get("phase", "")
        if phase != "Running":
            continue
        owners = pod.get("metadata", {}).get("ownerReferences", [])
        is_job = any(o.get("kind") == "Job" for o in owners)
        if not is_job:
            continue

        ns = pod["metadata"]["namespace"]
        name = pod["metadata"]["name"]
        start_str = pod.get("status", {}).get("startTime", "")
        restart_policy = pod.get("spec", {}).get("restartPolicy", "Always")

        if start_str:
            start_dt = datetime.fromisoformat(
                start_str.replace("Z", "+00:00"))
            age_min = (now - start_dt).total_seconds() / 60
        else:
            age_min = 0

        if age_min > 30 or restart_policy == "Never":
            print(f"  Job: {ns}/{name} age={int(age_min)}min "
                  f"restart={restart_policy}", file=sys.stderr)
            risky_jobs += 1

    if risky_jobs > 0:
        record("WLS-005", "MEDIUM", "FAIL",
               f"위험 Job Pod {risky_jobs}개 (age>30min 또는 restartPolicy=Never) → Job 완료 대기 또는 CronJob suspend 후 진행 권장")
    else:
        record("WLS-005", "MEDIUM", "PASS",
               "위험 Job Pod 없음")


# ══════════════════════════════════════════════════════════════
# WLS-006: 토폴로지 제약 위반 검증 (HIGH)
# ══════════════════════════════════════════════════════════════
def check_wls006() -> None:
    """WLS-006: TopologySpreadConstraints / Required Affinity 위험 분석."""
    risky: list[str] = []

    for kind in ("deployments", "statefulsets"):
        data = kubectl_json(kind)
        for item in data.get("items", []):
            ns = item["metadata"]["namespace"]
            if ns in SYSTEM_NS:
                continue
            name = item["metadata"]["name"]
            spec = item.get("spec", {}).get("template", {}).get("spec", {})

            # TSC: whenUnsatisfiable == DoNotSchedule
            for tsc in spec.get("topologySpreadConstraints", []):
                if tsc.get("whenUnsatisfiable") == "DoNotSchedule":
                    risky.append(f"{ns}/{name}")
                    break
            else:
                # Affinity: requiredDuringSchedulingIgnoredDuringExecution
                affinity = spec.get("affinity", {})
                node_aff = (affinity.get("nodeAffinity", {})
                            .get("requiredDuringSchedulingIgnoredDuringExecution"))
                pod_anti = (affinity.get("podAntiAffinity", {})
                            .get("requiredDuringSchedulingIgnoredDuringExecution"))
                if node_aff or pod_anti:
                    risky.append(f"{ns}/{name}")

    if not risky:
        record("WLS-006", "HIGH", "PASS",
               "엄격한 토폴로지 제약 워크로드 없음")
        return

    # AZ별 노드 수 확인
    nodes = kubectl_json("nodes", all_ns=False)
    az_count: Counter = Counter()
    for n in nodes.get("items", []):
        az = n["metadata"].get("labels", {}).get(
            "topology.kubernetes.io/zone", "")
        if az:
            az_count[az] += 1

    single_az = [az for az, cnt in az_count.items() if cnt <= 1]

    if single_az:
        record("WLS-006", "HIGH", "FAIL",
               f"위험 워크로드 {len(risky)}개 + 단일 노드 AZ: "
               f"{', '.join(single_az)} → 해당 AZ에 노드 추가 또는 whenUnsatisfiable을 ScheduleAnyway로 변경")
    else:
        record("WLS-006", "HIGH", "FAIL",
               f"엄격한 토폴로지 제약 워크로드 {len(risky)}개 (drain 시 Pending 위험) → 노드 수 확보 또는 preferred affinity로 변경 권장")


# ══════════════════════════════════════════════════════════════
# INF-002: 대상 버전 AMI 가용성 검증 (CRITICAL)
# ══════════════════════════════════════════════════════════════
def check_inf002(target_version: str) -> None:
    ami_found = 0
    ami_missing = 0

    # AL2023
    r = run_cmd([
        "aws", "ssm", "get-parameters-by-path",
        "--path",
        f"/aws/service/eks/optimized-ami/{target_version}"
        "/amazon-linux-2023/x86_64/standard",
        "--recursive",
        "--query", "Parameters | length(@)",
        "--output", "text",
    ])
    _al2023_first = r.stdout.strip().split()[0] if r.returncode == 0 and r.stdout.strip() else "0"
    al2023 = int(_al2023_first) if _al2023_first.isdigit() else 0

    if al2023 > 0:
        ami_found += 1
    else:
        ami_missing += 1
        print(f"  MISSING: AL2023 x86_64 AMI for {target_version}",
              file=sys.stderr)

    # Bottlerocket
    r = run_cmd([
        "aws", "ssm", "get-parameters-by-path",
        "--path",
        f"/aws/service/bottlerocket/aws-k8s-{target_version}/x86_64",
        "--recursive",
        "--query", "Parameters | length(@)",
        "--output", "text",
    ])
    _br_first = r.stdout.strip().split()[0] if r.returncode == 0 and r.stdout.strip() else "0"
    br = int(_br_first) if _br_first.isdigit() else 0

    if br > 0:
        ami_found += 1
    else:
        ami_missing += 1
        print(f"  MISSING: Bottlerocket x86_64 AMI for {target_version}",
              file=sys.stderr)

    if ami_missing > 0 and ami_found == 0:
        record("INF-002", "CRITICAL", "FAIL",
               f"AMI 미출시 (AL2023={al2023}, BR={br}) → AWS에서 AMI 릴리스 대기 (보통 EKS 버전 출시 후 1-2주)")
    elif ami_missing > 0:
        record("INF-002", "CRITICAL", "PASS",
               f"일부 AMI 존재 (AL2023={al2023}, BR={br}) — 사용 중인 타입 확인 필요")
    else:
        record("INF-002", "CRITICAL", "PASS",
               f"모든 AMI 존재 (AL2023={al2023}, BR={br})")


# ══════════════════════════════════════════════════════════════
# CAP-001: 노드 용량 여유분 검증 (HIGH)
# ══════════════════════════════════════════════════════════════
def check_cap001() -> None:
    nodes = kubectl_json("nodes", all_ns=False)
    pods = kubectl_json("pods", timeout=60)

    if not nodes or not pods:
        record("CAP-001", "HIGH", "PASS", "노드/Pod 조회 불가 — 건너뜀")
        return

    # 노드 allocatable
    node_alloc: dict[str, dict] = {}
    for node in nodes.get("items", []):
        name = node["metadata"]["name"]
        alloc = node.get("status", {}).get("allocatable", {})
        node_alloc[name] = {
            "cpu": _parse_cpu(alloc.get("cpu", "0")),
            "mem": _parse_mem(alloc.get("memory", "0")),
        }

    # Pod requests 합산
    node_used: dict[str, dict] = defaultdict(lambda: {"cpu": 0, "mem": 0})
    for pod in pods.get("items", []):
        phase = pod.get("status", {}).get("phase", "")
        if phase not in ("Running", "Pending"):
            continue
        node_name = pod.get("spec", {}).get("nodeName", "")
        if not node_name:
            continue
        for container in pod.get("spec", {}).get("containers", []):
            req = container.get("resources", {}).get("requests", {})
            node_used[node_name]["cpu"] += _parse_cpu(req.get("cpu", "0"))
            node_used[node_name]["mem"] += _parse_mem(req.get("memory", "0"))

    # 최대 사용률
    max_pct = 0.0
    for name, alloc in node_alloc.items():
        used = node_used.get(name, {"cpu": 0, "mem": 0})
        if alloc["cpu"] > 0:
            max_pct = max(max_pct, used["cpu"] / alloc["cpu"] * 100)
        if alloc["mem"] > 0:
            max_pct = max(max_pct, used["mem"] / alloc["mem"] * 100)

    util = int(max_pct)
    if util > 90:
        record("CAP-001", "HIGH", "FAIL",
               f"최대 노드 사용률 {util}% (> 90% — Pod Pending 위험) → 노드 스케일업 후 재시도하세요")
    elif util > 80:
        record("CAP-001", "HIGH", "FAIL",
               f"최대 노드 사용률 {util}% (> 80% — drain 시 여유 부족) → 노드 스케일업 권장")
    else:
        record("CAP-001", "HIGH", "PASS",
               f"최대 노드 사용률 {util}% (여유 충분)")


# ══════════════════════════════════════════════════════════════
# CAP-002: 리소스 압박 Pod 검증 (MEDIUM)
# ══════════════════════════════════════════════════════════════
def check_cap002() -> None:
    """CAP-002: OOMKilled, CrashLoopBackOff, ImagePullBackOff, Evicted Pod 감지."""
    pods = kubectl_json("pods", timeout=60)
    if not pods:
        record("CAP-002", "MEDIUM", "PASS", "Pod 조회 불가 — 건너뜀")
        return

    problem_pods: list[str] = []
    evicted_pods: list[str] = []

    for pod in pods.get("items", []):
        ns = pod["metadata"]["namespace"]
        name = pod["metadata"]["name"]

        # Evicted check
        phase = pod.get("status", {}).get("phase", "")
        reason = pod.get("status", {}).get("reason", "")
        if phase == "Failed" and reason == "Evicted":
            evicted_pods.append(f"{ns}/{name}")
            continue

        # containerStatuses check
        for cs in pod.get("status", {}).get("containerStatuses", []):
            # OOMKilled — current state
            term = cs.get("state", {}).get("terminated", {})
            if term.get("reason") == "OOMKilled":
                problem_pods.append(f"{ns}/{name}(OOMKilled)")
                break
            # OOMKilled — last state
            last_term = cs.get("lastState", {}).get("terminated", {})
            if last_term.get("reason") == "OOMKilled":
                problem_pods.append(f"{ns}/{name}(OOMKilled-prev)")
                break
            # CrashLoopBackOff / ImagePullBackOff
            waiting = cs.get("state", {}).get("waiting", {})
            wait_reason = waiting.get("reason", "")
            if wait_reason in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"):
                problem_pods.append(f"{ns}/{name}({wait_reason})")
                break

    if problem_pods:
        record("CAP-002", "MEDIUM", "FAIL",
               f"문제 Pod {len(problem_pods)}개: "
               f"{', '.join(problem_pods[:5])}"
               f"{'...' if len(problem_pods) > 5 else ''}")
    elif evicted_pods:
        record("CAP-002", "MEDIUM", "PASS",
               f"Evicted Pod {len(evicted_pods)}개 (INFO)")
    else:
        record("CAP-002", "MEDIUM", "PASS", "문제 Pod 없음")


# ══════════════════════════════════════════════════════════════
# CAP-003: Surge 용량 (서브넷 가용 IP) 검증 (HIGH)
# ══════════════════════════════════════════════════════════════
def check_cap003(cluster_name: str) -> None:
    """CAP-003: MNG 서브넷 가용 IP 검증."""
    # 1. MNG 목록 조회
    r = run_cmd([
        "aws", "eks", "list-nodegroups",
        "--cluster-name", cluster_name,
        "--output", "json",
    ])
    if r.returncode != 0:
        record("CAP-003", "HIGH", "FAIL", "MNG 목록 조회 실패")
        return

    try:
        nodegroups = json.loads(r.stdout).get("nodegroups", [])
    except json.JSONDecodeError:
        record("CAP-003", "HIGH", "FAIL", "MNG 목록 JSON 파싱 실패")
        return

    if not nodegroups:
        record("CAP-003", "HIGH", "PASS", "MNG 없음")
        return

    # 2. 각 MNG의 서브넷 수집
    all_subnets: set[str] = set()
    for ng in nodegroups:
        r = run_cmd([
            "aws", "eks", "describe-nodegroup",
            "--cluster-name", cluster_name,
            "--nodegroup-name", ng,
            "--output", "json",
        ])
        if r.returncode != 0:
            continue
        try:
            subnets = json.loads(r.stdout).get("nodegroup", {}).get("subnets", [])
            all_subnets.update(subnets)
        except json.JSONDecodeError:
            continue

    if not all_subnets:
        record("CAP-003", "HIGH", "FAIL", "서브넷 정보 조회 실패")
        return

    # 3. 서브넷 가용 IP 확인
    r = run_cmd([
        "aws", "ec2", "describe-subnets",
        "--subnet-ids", *sorted(all_subnets),
        "--output", "json",
    ])
    if r.returncode != 0:
        record("CAP-003", "HIGH", "FAIL", "서브넷 상세 조회 실패")
        return

    try:
        subnets_data = json.loads(r.stdout).get("Subnets", [])
    except json.JSONDecodeError:
        record("CAP-003", "HIGH", "FAIL", "서브넷 JSON 파싱 실패")
        return

    critical_low: list[str] = []   # < 10
    warning_low: list[str] = []    # 10~49

    for s in subnets_data:
        sid = s.get("SubnetId", "?")
        avail = s.get("AvailableIpAddressCount", 0)
        if avail < 10:
            critical_low.append(f"{sid}({avail})")
        elif avail < 50:
            warning_low.append(f"{sid}({avail})")

    if critical_low:
        record("CAP-003", "HIGH", "FAIL",
               f"가용 IP < 10: {', '.join(critical_low)} → 서브넷 CIDR 확장 또는 prefix delegation 활성화 필요")
    elif warning_low:
        record("CAP-003", "HIGH", "FAIL",
               f"가용 IP 10~49 (고갈 위험): {', '.join(warning_low)} → surge 노드 생성 시 IP 부족 가능. 서브넷 확장 권장")
    else:
        record("CAP-003", "HIGH", "PASS",
               "모든 서브넷 가용 IP ≥ 50")


# ══════════════════════════════════════════════════════════════
# run_terraform_plan: Terraform plan 헬퍼
# ══════════════════════════════════════════════════════════════
def run_terraform_plan(tf_dir: str) -> tuple[int, str]:
    """terraform plan -detailed-exitcode -no-color 실행. 반환: (exit_code, output)."""
    try:
        r = subprocess.run(
            ["terraform", "plan", "-detailed-exitcode", "-no-color"],
            capture_output=True, text=True, cwd=tf_dir, timeout=300,
        )
        return (r.returncode, r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        return (1, "ERROR: terraform plan timed out (300s)")
    except FileNotFoundError:
        return (1, "ERROR: terraform not found")


# ══════════════════════════════════════════════════════════════
# INF-001: Terraform 상태 드리프트 검증 (HIGH)
# ══════════════════════════════════════════════════════════════
def check_inf001(tf_exit_code: int, plan_output: str) -> None:
    """INF-001: Terraform 상태 드리프트 검증."""
    if tf_exit_code == 0:
        record("INF-001", "HIGH", "PASS", "terraform plan: 변경 없음 (no drift)")
        return
    if tf_exit_code == 1:
        record("INF-001", "HIGH", "FAIL", "terraform plan 오류 (exit code 1) → terraform init 또는 provider 설정 확인 후 재시도")
        return
    # exit code 2 — changes detected
    if DESTROY_PATTERN.search(plan_output) or RECREATE_MARKERS.search(plan_output):
        record("INF-001", "HIGH", "FAIL",
               "terraform drift 감지 — destroy/recreate 포함 → terraform apply로 drift 해소 후 재시도하세요")
    else:
        record("INF-001", "HIGH", "FAIL",
               "terraform drift 감지 — 비파괴적 변경 → terraform apply로 drift 해소 후 재시도하세요")


# ══════════════════════════════════════════════════════════════
# INF-004: Terraform Recreate 감지 — Data Plane 리소스 (HIGH/CRITICAL)
# ══════════════════════════════════════════════════════════════
def check_inf004(plan_output: str) -> None:
    """INF-004: Terraform Recreate 감지 (Data Plane 리소스)."""
    recreate_resources: list[str] = []
    # -/+ resource lines
    for m in REPLACE_PREFIX.finditer(plan_output):
        recreate_resources.append(m.group(1))
    # "forces replacement" / "must be replaced" context lines
    for line in plan_output.splitlines():
        if RECREATE_MARKERS.search(line):
            # Try to extract resource type from nearby context
            # Lines like: # aws_eks_node_group.xxx must be replaced
            parts = line.strip().lstrip("# ").split(".")
            if len(parts) >= 2:
                rtype = parts[0].strip()
                if rtype and rtype[0].isalpha():
                    recreate_resources.append(rtype)

    if not recreate_resources:
        record("INF-004", "HIGH", "PASS", "recreate 마커 없음")
        return

    data_plane_hits = [r for r in recreate_resources if r in DATA_PLANE_RESOURCES]
    if data_plane_hits:
        record("INF-004", "CRITICAL", "FAIL",
               f"Data Plane recreate 감지: {', '.join(set(data_plane_hits))} → lifecycle {{ create_before_destroy = true }} 또는 name_prefix 사용 권장")
    else:
        record("INF-004", "HIGH", "FAIL",
               f"비-Data Plane recreate: {', '.join(set(recreate_resources))} → recreate 대상 리소스 확인 후 사용자 승인 필요")


# ══════════════════════════════════════════════════════════════
# INF-003: Karpenter 호환성 검증 (HIGH)
# ══════════════════════════════════════════════════════════════
def check_inf003() -> None:
    """INF-003: Karpenter 호환성 검증."""
    # 1. CRD 존재 확인
    r = run_cmd(["kubectl", "get", "crd", "nodeclaims.karpenter.sh"], timeout=10)
    if r.returncode != 0:
        record("INF-003", "HIGH", "SKIP", "Karpenter CRD 미존재 — 건너뜀")
        return

    # 2. Karpenter 버전 추출
    r = run_cmd([
        "kubectl", "get", "deployment", "-n", "karpenter", "karpenter",
        "-o", "json",
    ])
    version = "unknown"
    if r.returncode == 0:
        try:
            dep = json.loads(r.stdout)
            image = dep["spec"]["template"]["spec"]["containers"][0]["image"]
            version = image.rsplit(":", 1)[-1] if ":" in image else "unknown"
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

    # 3. NodePool disruption budget 확인
    r = run_cmd(["kubectl", "get", "nodepool", "-o", "json"])
    if r.returncode != 0:
        record("INF-003", "HIGH", "PASS",
               f"Karpenter {version} — NodePool 조회 불가")
        return

    try:
        pools = json.loads(r.stdout)
    except json.JSONDecodeError:
        record("INF-003", "HIGH", "PASS",
               f"Karpenter {version} — NodePool JSON 파싱 실패")
        return

    blocked_pools: list[str] = []
    for pool in pools.get("items", []):
        name = pool.get("metadata", {}).get("name", "?")
        budgets = (pool.get("spec", {})
                   .get("disruption", {})
                   .get("budgets", []))
        for b in budgets:
            nodes_val = b.get("nodes", None)
            if nodes_val is not None:
                # "0" or 0
                try:
                    if int(str(nodes_val)) == 0:
                        blocked_pools.append(name)
                        break
                except ValueError:
                    pass

    if blocked_pools:
        record("INF-003", "HIGH", "FAIL",
               f"Karpenter {version} — disruption budget=0: "
               f"{', '.join(blocked_pools)} (drift 교체 차단) → NodePool disruption budget을 1 이상으로 조정하세요")
    else:
        record("INF-003", "HIGH", "PASS",
               f"Karpenter {version} — disruption budget 정상")


# ══════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 0 사전 검증 (gate_check.py)")
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--audit-log", default="audit.log",
                        help="감사 로그 저장 경로 (기본: 현재 디렉토리의 audit.log)")
    parser.add_argument("--tf-dir", default=None,
                        help="Terraform 구성 디렉토리 (INF-001/INF-004에 필요)")
    args = parser.parse_args()

    # 의존성 확인
    for cmd in ("kubectl", "aws"):
        r = run_cmd(["which", cmd])
        if r.returncode != 0:
            print(f"ERROR: '{cmd}' not found in PATH.", file=sys.stderr)
            sys.exit(127)

    # --tf-dir 검증
    if args.tf_dir:
        tf_path = Path(args.tf_dir)
        if not tf_path.is_dir():
            print(f"ERROR: --tf-dir '{args.tf_dir}' is not a directory.", file=sys.stderr)
            sys.exit(1)
        r = run_cmd(["which", "terraform"])
        if r.returncode != 0:
            print("ERROR: 'terraform' not found in PATH.", file=sys.stderr)
            sys.exit(1)

    print()
    print("════════════════════════════════════════════════════════════")
    print("  Phase 0: 사전 검증 (gate_check.py)")
    print(f"  Cluster: {args.cluster_name}")
    print(f"  Upgrade: {args.current_version} → {args.target_version}")
    print("════════════════════════════════════════════════════════════")
    print()

    audit_init(args.cluster_name, args.current_version, args.target_version)

    # ── 전체 규칙 목록 (SKIPPED 추적용) ──
    ALL_RULES = [
        "COM-002", "COM-001", "COM-002a", "COM-003",
        "WLS-001", "WLS-002", "WLS-003", "WLS-004", "WLS-005", "WLS-006",
        "CAP-001", "CAP-002", "CAP-003",
        "INF-001", "INF-002", "INF-003", "INF-004",
    ]
    executed_rules: list[str] = []

    def track(rule_id: str) -> None:
        executed_rules.append(rule_id)

    # ── 1단계: 공통 검증 ──
    print("── 1단계: 공통 검증 ──")
    check_com002(args.current_version, args.target_version)
    track("COM-002")

    # 버전 gap이 0이거나 >1이면 나머지 검증 무의미
    if _gate.critical_fail > 0:
        for r in ALL_RULES:
            if r not in executed_rules:
                record(r, "-", "SKIP", "COM-002 CRITICAL FAIL로 인해 건너뜀")
    else:
        check_com001(args.cluster_name)
        track("COM-001")
        check_com002a(args.target_version)
        track("COM-002a")
        check_com003(args.cluster_name, args.target_version)
        track("COM-003")

        # ── 2단계: 워크로드 안전성 ──
        print("\n── 2단계: 워크로드 안전성 ──")
        check_wls001()
        track("WLS-001")
        check_wls002()
        track("WLS-002")
        check_wls003()
        track("WLS-003")
        check_wls004()
        track("WLS-004")
        check_wls005()
        track("WLS-005")
        check_wls006()
        track("WLS-006")

        # ── 3단계: 용량 검증 ──
        print("\n── 3단계: 용량 검증 ──")
        check_cap001()
        track("CAP-001")
        check_cap002()
        track("CAP-002")
        check_cap003(args.cluster_name)
        track("CAP-003")

        # ── 4단계: 인프라 검증 ──
        print("\n── 4단계: 인프라 검증 ──")
        if args.tf_dir:
            tf_exit_code, plan_output = run_terraform_plan(args.tf_dir)
            check_inf001(tf_exit_code, plan_output)
            track("INF-001")
        else:
            record("INF-001", "HIGH", "SKIP", "--tf-dir 미제공")
            track("INF-001")

        check_inf002(args.target_version)
        track("INF-002")
        check_inf003()
        track("INF-003")

        if args.tf_dir:
            check_inf004(plan_output)
            track("INF-004")
        else:
            record("INF-004", "HIGH", "SKIP", "--tf-dir 미제공")
            track("INF-004")

    # ── Gate 판정 ──
    print()
    print("════════════════════════════════════════════════════════════")
    print(f"  검증 결과")
    _sync_to_gate()
    print(f"  총 {_gate.total_rules}개 규칙 | PASS: {_gate.total_pass} "
          f"| CRITICAL FAIL: {_gate.critical_fail} | HIGH WARN: {_gate.high_warn}"
          f" | MEDIUM INFO: {_gate.medium_info}")
    print("════════════════════════════════════════════════════════════")

    audit_flush(args.audit_log)

    if _gate.critical_fail > 0:
        print()
        print(f"{RED}Gate: BLOCKED — CRITICAL 실패 {_gate.critical_fail}개. "
              f"해결 후 재실행하세요.{NC}")
        print(f"감사 로그: {args.audit_log}")
        sys.exit(1)
    elif _gate.high_warn > 0:
        print()
        print(f"{YELLOW}Gate: WARN — HIGH 경고 {_gate.high_warn}개. "
              f"사용자 확인 필요.{NC}")
        print(f"감사 로그: {args.audit_log}")
        sys.exit(2)
    else:
        print()
        print(f"{GREEN}Gate: OPEN — 검증 통과.{NC}")
        print(f"감사 로그: {args.audit_log}")
        sys.exit(0)


if __name__ == "__main__":
    main()
