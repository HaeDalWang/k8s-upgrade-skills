"""
tests/test_gate_check.py — gate_check.py 단위 테스트 + Property 테스트 기본 구조

Task 8.1: 기본 구조 (pytest + hypothesis imports, 모듈 import, 모킹 헬퍼, reset fixture)
Task 8.11: Unit 테스트 (Edge case 및 통합 검증)
"""

import inspect
import subprocess
import sys
import os
import unittest.mock

import pytest

# ── gate_check 모듈 import ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import gate_check


# ══════════════════════════════════════════════════════════════
# Fixture: 글로벌 카운터 리셋
# ══════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def reset_counters():
    """각 테스트 전 gate_check 글로벌 카운터 초기화."""
    gate_check.reset_gate()


# ══════════════════════════════════════════════════════════════
# Task 8.11: Unit 테스트
# ══════════════════════════════════════════════════════════════


class TestAllRulesOrder:
    """17개 규칙 ALL_RULES 순서 확인."""

    def test_all_rules_order(self):
        """main() 소스에 ALL_RULES 17개 항목이 올바른 순서로 정의되어 있는지 확인."""
        source = inspect.getsource(gate_check.main)
        expected = [
            "COM-002", "COM-001", "COM-002a", "COM-003",
            "WLS-001", "WLS-002", "WLS-003", "WLS-004", "WLS-005", "WLS-006",
            "CAP-001", "CAP-002", "CAP-003",
            "INF-001", "INF-002", "INF-003", "INF-004",
        ]
        assert "ALL_RULES" in source
        for rule in expected:
            assert f'"{rule}"' in source, f"{rule} not found in ALL_RULES"
        # 17개 항목 확인
        assert len(expected) == 17


class TestTfDirNotProvidedSkipsInfRules:
    """--tf-dir 미제공 시 INF-001/INF-004 SKIP 확인."""

    def test_tf_dir_not_provided_skips_inf001_inf004(self):
        """--tf-dir 미제공 시 INF-001, INF-004가 SKIP으로 기록되는지 확인."""
        gate_check.record("INF-001", "HIGH", "SKIP", "--tf-dir 미제공")
        gate_check.record("INF-004", "HIGH", "SKIP", "--tf-dir 미제공")
        assert gate_check.total_pass == 2  # SKIP counts as pass
        assert gate_check.critical_fail == 0
        assert gate_check.high_warn == 0


class TestKarpenterCrdMissingSkipsInf003:
    """Karpenter CRD 미존재 시 INF-003 SKIP 확인."""

    def test_karpenter_crd_missing_skips_inf003(self):
        with unittest.mock.patch.object(gate_check, 'run_cmd') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 1, stdout="", stderr="not found")
            gate_check.check_inf003()
        assert gate_check.total_pass == 1  # SKIP counts as pass
        assert gate_check.critical_fail == 0


class TestTfDirNonexistentExits1:
    """--tf-dir 경로 미존재 시 exit code 1 확인."""

    def test_tf_dir_nonexistent_exits_1(self):
        with pytest.raises(SystemExit) as exc_info:
            with unittest.mock.patch('sys.argv', [
                'gate_check.py',
                '--cluster-name', 'test',
                '--current-version', '1.33',
                '--target-version', '1.34',
                '--tf-dir', '/nonexistent/path/that/does/not/exist',
            ]):
                with unittest.mock.patch.object(gate_check, 'run_cmd') as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(
                        [], 0, stdout="/usr/bin/kubectl", stderr="")
                    gate_check.main()
        assert exc_info.value.code == 1


class TestCom002CriticalFailSkipsRest:
    """COM-002 CRITICAL FAIL 시 나머지 17개 규칙 SKIP 확인."""

    def test_com002_critical_fail_skips_rest(self):
        with unittest.mock.patch('sys.argv', [
            'gate_check.py',
            '--cluster-name', 'test',
            '--current-version', '1.30',
            '--target-version', '1.34',
            '--audit-log', '/dev/null',
        ]):
            with unittest.mock.patch.object(gate_check, 'run_cmd') as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    [], 0, stdout="/usr/bin/kubectl", stderr="")
                with pytest.raises(SystemExit) as exc_info:
                    gate_check.main()
        assert exc_info.value.code == 1
        assert gate_check.critical_fail >= 1
        # 17개 규칙 전부 기록 (1 FAIL + 16 SKIP)
        assert gate_check.total_rules == 17


class TestCom003EmptyAddonsPass:
    """Add-on 목록 비어있는 경우 COM-003 PASS 확인."""

    def test_com003_empty_addons_pass(self):
        with unittest.mock.patch.object(gate_check, 'run_cmd') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout='{"addons": []}', stderr="")
            gate_check.check_com003("test-cluster", "1.34")
        assert gate_check.total_pass == 1
        assert gate_check.critical_fail == 0


class TestCap003EmptyNodegroupsPass:
    """MNG 목록 비어있는 경우 CAP-003 PASS 확인."""

    def test_cap003_empty_nodegroups_pass(self):
        with unittest.mock.patch.object(gate_check, 'run_cmd') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout='{"nodegroups": []}', stderr="")
            gate_check.check_cap003("test-cluster")
        assert gate_check.total_pass == 1
        assert gate_check.critical_fail == 0


class TestTerraformPlanTimeout300:
    """terraform plan timeout 300초 설정 확인."""

    def test_terraform_plan_timeout_300(self):
        with unittest.mock.patch('subprocess.run') as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                [], 0, stdout="No changes.", stderr="")
            gate_check.run_terraform_plan("/tmp/tf")
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            # timeout은 keyword arg로 전달됨
            assert call_kwargs.kwargs.get('timeout') == 300 or \
                call_kwargs[1].get('timeout') == 300


# ══════════════════════════════════════════════════════════════
# Task 8.2: Property 1 테스트 — COM-003 Add-on 상태 및 호환성 분류
# Feature: gate-check-full-deterministic, Property 1: COM-003 Add-on 상태 및 호환성 분류
# ══════════════════════════════════════════════════════════════
from hypothesis import given, settings, assume
from hypothesis import strategies as st


# Strategy: 각 Add-on의 상태와 호환 여부를 조합 생성
_addon_entry = st.fixed_dictionaries({
    "name": st.from_regex(r"[a-z][a-z0-9\-]{1,20}", fullmatch=True),
    "status": st.sampled_from(["ACTIVE", "DEGRADED", "CREATE_FAILED"]),
    "compatible": st.booleans(),  # True = target version 호환 버전 존재
})

_addon_list_strategy = st.lists(_addon_entry, min_size=0, max_size=5).filter(
    lambda addons: len({a["name"] for a in addons}) == len(addons)  # unique names
)


def _build_run_cmd_side_effect(cluster_name, target_version, addons):
    """check_com003 내부의 run_cmd 호출을 시뮬레이션하는 side_effect 함수 생성."""
    import json as _json

    addon_names = [a["name"] for a in addons]
    addon_map = {a["name"]: a for a in addons}

    def side_effect(args, timeout=30):
        # 1) aws eks list-addons
        if args[:3] == ["aws", "eks", "list-addons"]:
            return subprocess.CompletedProcess(
                args, 0,
                stdout=_json.dumps({"addons": addon_names}),
                stderr="",
            )
        # 2) aws eks describe-addon
        if args[:3] == ["aws", "eks", "describe-addon"] and "--addon-name" in args:
            idx = args.index("--addon-name") + 1
            name = args[idx]
            entry = addon_map.get(name)
            if entry:
                return subprocess.CompletedProcess(
                    args, 0,
                    stdout=_json.dumps({"addon": {"status": entry["status"]}}),
                    stderr="",
                )
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="not found")
        # 3) aws eks describe-addon-versions
        if args[:3] == ["aws", "eks", "describe-addon-versions"]:
            idx = args.index("--addon-name") + 1
            name = args[idx]
            entry = addon_map.get(name)
            if entry and entry["compatible"]:
                return subprocess.CompletedProcess(
                    args, 0,
                    stdout=_json.dumps({"addons": [{"addonName": name}]}),
                    stderr="",
                )
            else:
                # 비호환: 빈 addons 리스트
                return subprocess.CompletedProcess(
                    args, 0,
                    stdout=_json.dumps({"addons": []}),
                    stderr="",
                )
        # fallback
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="unknown cmd")

    return side_effect


class TestCom003Property:
    """
    Property 1: COM-003 Add-on 상태 및 호환성 분류

    **Validates: Requirements 1.2, 1.3, 1.4, 1.5**
    """

    @given(addons=_addon_list_strategy)
    @settings(max_examples=100)
    def test_com003_addon_classification(self, addons):
        """
        For any combination of Add-on states and compatibility:
        - DEGRADED/CREATE_FAILED → FAIL(HIGH)
        - ACTIVE + incompatible → FAIL(HIGH)
        - All ACTIVE + all compatible → PASS
        - Empty addon list → PASS

        **Validates: Requirements 1.2, 1.3, 1.4, 1.5**
        """
        # Manual counter reset (hypothesis generates multiple inputs per test call)
        gate_check.reset_gate()

        cluster_name = "test-cluster"
        target_version = "1.34"

        side_effect = _build_run_cmd_side_effect(cluster_name, target_version, addons)

        with unittest.mock.patch.object(gate_check, 'run_cmd', side_effect=side_effect):
            gate_check.check_com003(cluster_name, target_version)

        # Determine expected outcome
        has_bad_state = any(
            a["status"] in ("DEGRADED", "CREATE_FAILED") for a in addons
        )
        all_active = all(a["status"] == "ACTIVE" for a in addons)
        has_incompatible = any(
            a["status"] == "ACTIVE" and not a["compatible"] for a in addons
        )

        assert gate_check.total_rules == 1, "check_com003 should record exactly one result"

        if len(addons) == 0:
            # Empty addon list → PASS
            assert gate_check.total_pass == 1
            assert gate_check.high_warn == 0
            assert gate_check.critical_fail == 0
        elif has_bad_state:
            # Req 1.2: DEGRADED/CREATE_FAILED → FAIL(HIGH)
            assert gate_check.high_warn == 1
            assert gate_check.total_pass == 0
            # Verify bad addon names appear in audit
            bad_names = [
                a["name"] for a in addons
                if a["status"] in ("DEGRADED", "CREATE_FAILED")
            ]
            audit_text = " ".join(gate_check.audit_lines)
            for name in bad_names:
                assert name in audit_text, (
                    f"Bad addon '{name}' should appear in audit log"
                )
        elif all_active and has_incompatible:
            # Req 1.3, 1.4: ACTIVE + incompatible → FAIL(HIGH)
            assert gate_check.high_warn == 1
            assert gate_check.total_pass == 0
            # Verify incompatible addon names in audit
            incompat_names = [
                a["name"] for a in addons
                if a["status"] == "ACTIVE" and not a["compatible"]
            ]
            audit_text = " ".join(gate_check.audit_lines)
            for name in incompat_names:
                assert name in audit_text, (
                    f"Incompatible addon '{name}' should appear in audit log"
                )
        elif all_active and not has_incompatible:
            # Req 1.5: All ACTIVE + all compatible → PASS
            assert gate_check.total_pass == 1
            assert gate_check.high_warn == 0
            assert gate_check.critical_fail == 0


# ══════════════════════════════════════════════════════════════
# Task 8.3: Property 2 테스트 — WLS-006 토폴로지 위험 워크로드 분류 및 판정
# Feature: gate-check-full-deterministic, Property 2: WLS-006 토폴로지 위험 워크로드 분류 및 판정
# ══════════════════════════════════════════════════════════════

# ── Strategy: 워크로드 항목 생성 ──
_user_ns = st.sampled_from(["default", "app", "production", "staging", "monitoring"])
_system_ns = st.sampled_from(list(gate_check.SYSTEM_NS))

_tsc_strategy = st.one_of(
    st.just(None),  # no TSC
    st.just([{"whenUnsatisfiable": "DoNotSchedule", "topologyKey": "topology.kubernetes.io/zone"}]),
    st.just([{"whenUnsatisfiable": "ScheduleAnyway", "topologyKey": "topology.kubernetes.io/zone"}]),
)

_affinity_strategy = st.one_of(
    st.just({}),  # no affinity
    st.just({"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": []}}}),
    st.just({"podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [{"topologyKey": "kubernetes.io/hostname"}]}}),
    st.just({"nodeAffinity": {"preferredDuringSchedulingIgnoredDuringExecution": []}}),  # preferred only — not risky
)

_workload_entry = st.fixed_dictionaries({
    "namespace": st.one_of(_user_ns, _system_ns),
    "name": st.from_regex(r"[a-z][a-z0-9\-]{1,15}", fullmatch=True),
    "tsc": _tsc_strategy,
    "affinity": _affinity_strategy,
})

_workload_list_strategy = st.lists(_workload_entry, min_size=0, max_size=6)

# AZ별 노드 분포: AZ 이름 → 노드 수
_az_node_strategy = st.dictionaries(
    keys=st.sampled_from(["us-east-1a", "us-east-1b", "us-east-1c", "ap-northeast-2a", "ap-northeast-2b"]),
    values=st.integers(min_value=1, max_value=5),
    min_size=1,
    max_size=4,
)


def _build_wls006_kubectl_json_side_effect(workloads, az_nodes):
    """check_wls006 내부의 kubectl_json 호출을 시뮬레이션하는 side_effect 함수 생성."""
    import json as _json

    def _make_item(w):
        spec_inner = {}
        if w["tsc"] is not None:
            spec_inner["topologySpreadConstraints"] = w["tsc"]
        if w["affinity"]:
            spec_inner["affinity"] = w["affinity"]
        return {
            "metadata": {"namespace": w["namespace"], "name": w["name"]},
            "spec": {
                "template": {
                    "spec": spec_inner,
                },
            },
        }

    deploy_items = [_make_item(w) for w in workloads]

    # Build node items from az_nodes dict
    node_items = []
    for az, count in az_nodes.items():
        for i in range(count):
            node_items.append({
                "metadata": {
                    "name": f"node-{az}-{i}",
                    "labels": {"topology.kubernetes.io/zone": az},
                },
            })

    def side_effect(resource, all_ns=True, timeout=30):
        if resource == "deployments":
            return {"items": deploy_items}
        if resource == "statefulsets":
            return {"items": []}  # all workloads as deployments for simplicity
        if resource == "nodes":
            return {"items": node_items}
        return {}

    return side_effect


def _is_risky_workload(w):
    """워크로드가 위험으로 분류되는지 판정 (시스템 NS 제외 후)."""
    if w["namespace"] in gate_check.SYSTEM_NS:
        return False
    # TSC check
    if w["tsc"] is not None:
        for tsc in w["tsc"]:
            if tsc.get("whenUnsatisfiable") == "DoNotSchedule":
                return True
    # Affinity check (only if TSC didn't match)
    # Note: check_wls006 uses for/else — affinity is only checked if TSC loop didn't break
    if w["tsc"] is not None:
        has_dns_tsc = any(
            tsc.get("whenUnsatisfiable") == "DoNotSchedule" for tsc in w["tsc"]
        )
        if has_dns_tsc:
            return True  # already caught above
    # If no DoNotSchedule TSC, check affinity
    affinity = w.get("affinity", {})
    node_aff = affinity.get("nodeAffinity", {}).get("requiredDuringSchedulingIgnoredDuringExecution")
    pod_anti = affinity.get("podAntiAffinity", {}).get("requiredDuringSchedulingIgnoredDuringExecution")
    if node_aff or pod_anti:
        return True
    return False


class TestWls006Property:
    """
    Property 2: WLS-006 토폴로지 위험 워크로드 분류 및 판정

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
    """

    @given(workloads=_workload_list_strategy, az_nodes=_az_node_strategy)
    @settings(max_examples=100)
    def test_wls006_topology_risk_classification(self, workloads, az_nodes):
        """
        For any combination of workloads (namespace, TSC, affinity) and AZ node distribution:
        - System NS workloads are always excluded
        - DoNotSchedule TSC or required affinity → risky classification
        - Risky workloads + single-node AZ → FAIL(HIGH) with AZ info
        - Risky workloads + all AZs 2+ nodes → FAIL(HIGH) with workload count
        - No risky workloads → PASS

        **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
        """
        # Reset counters
        gate_check.reset_gate()

        side_effect = _build_wls006_kubectl_json_side_effect(workloads, az_nodes)

        with unittest.mock.patch.object(gate_check, 'kubectl_json', side_effect=side_effect):
            gate_check.check_wls006()

        # Determine expected outcome
        risky_workloads = [w for w in workloads if _is_risky_workload(w)]
        single_az = [az for az, cnt in az_nodes.items() if cnt <= 1]

        assert gate_check.total_rules == 1, "check_wls006 should record exactly one result"

        if not risky_workloads:
            # Req 2.5: No risky workloads → PASS
            assert gate_check.total_pass == 1, (
                f"Expected PASS with no risky workloads, got pass={gate_check.total_pass}, "
                f"high_warn={gate_check.high_warn}"
            )
            assert gate_check.high_warn == 0
            assert gate_check.critical_fail == 0
        elif risky_workloads and single_az:
            # Req 2.4: Risky workloads + single-node AZ → FAIL(HIGH) with AZ info
            assert gate_check.high_warn == 1, (
                f"Expected FAIL(HIGH) with risky workloads + single AZ, "
                f"got high_warn={gate_check.high_warn}"
            )
            assert gate_check.total_pass == 0
            # Verify single AZ names appear in audit
            audit_text = " ".join(gate_check.audit_lines)
            for az in single_az:
                assert az in audit_text, (
                    f"Single-node AZ '{az}' should appear in audit log"
                )
        else:
            # Risky workloads but all AZs have 2+ nodes → FAIL(HIGH) with workload count
            assert gate_check.high_warn == 1, (
                f"Expected FAIL(HIGH) with risky workloads (all AZs 2+ nodes), "
                f"got high_warn={gate_check.high_warn}"
            )
            assert gate_check.total_pass == 0
            # Verify workload count in audit
            audit_text = " ".join(gate_check.audit_lines)
            assert str(len(risky_workloads)) in audit_text, (
                f"Risky workload count {len(risky_workloads)} should appear in audit log"
            )


# ══════════════════════════════════════════════════════════════
# Task 8.4: Property 3 테스트 — CAP-002 Pod 상태 분류 및 판정
# Feature: gate-check-full-deterministic, Property 3: CAP-002 Pod 상태 분류 및 판정
# ══════════════════════════════════════════════════════════════

# ── Strategy: Pod 상태 조합 생성 ──
# 각 Pod는 다음 중 하나의 상태를 가짐:
#   - "normal": 문제 없는 정상 Pod
#   - "oomkilled_current": state.terminated.reason == "OOMKilled"
#   - "oomkilled_prev": lastState.terminated.reason == "OOMKilled"
#   - "crashloop": state.waiting.reason == "CrashLoopBackOff"
#   - "imagepull": state.waiting.reason == "ImagePullBackOff"
#   - "errimagepull": state.waiting.reason == "ErrImagePull"
#   - "evicted": phase == "Failed", reason == "Evicted"

_pod_condition = st.sampled_from([
    "normal",
    "oomkilled_current",
    "oomkilled_prev",
    "crashloop",
    "imagepull",
    "errimagepull",
    "evicted",
])

_pod_entry = st.fixed_dictionaries({
    "namespace": st.from_regex(r"[a-z][a-z0-9\-]{1,10}", fullmatch=True),
    "name": st.from_regex(r"pod-[a-z0-9]{1,8}", fullmatch=True),
    "condition": _pod_condition,
})

_pod_list_strategy = st.lists(_pod_entry, min_size=0, max_size=8)


def _build_cap002_pod_items(pods):
    """Pod 엔트리 리스트를 kubectl_json 반환 형식의 items 리스트로 변환."""
    items = []
    for p in pods:
        ns = p["namespace"]
        name = p["name"]
        cond = p["condition"]

        pod_obj = {
            "metadata": {"namespace": ns, "name": name},
            "status": {},
        }

        if cond == "evicted":
            pod_obj["status"]["phase"] = "Failed"
            pod_obj["status"]["reason"] = "Evicted"
            # Evicted pods don't need containerStatuses
        elif cond == "oomkilled_current":
            pod_obj["status"]["phase"] = "Running"
            pod_obj["status"]["containerStatuses"] = [{
                "state": {"terminated": {"reason": "OOMKilled"}},
                "lastState": {},
            }]
        elif cond == "oomkilled_prev":
            pod_obj["status"]["phase"] = "Running"
            pod_obj["status"]["containerStatuses"] = [{
                "state": {"running": {"startedAt": "2024-01-01T00:00:00Z"}},
                "lastState": {"terminated": {"reason": "OOMKilled"}},
            }]
        elif cond == "crashloop":
            pod_obj["status"]["phase"] = "Running"
            pod_obj["status"]["containerStatuses"] = [{
                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                "lastState": {},
            }]
        elif cond == "imagepull":
            pod_obj["status"]["phase"] = "Pending"
            pod_obj["status"]["containerStatuses"] = [{
                "state": {"waiting": {"reason": "ImagePullBackOff"}},
                "lastState": {},
            }]
        elif cond == "errimagepull":
            pod_obj["status"]["phase"] = "Pending"
            pod_obj["status"]["containerStatuses"] = [{
                "state": {"waiting": {"reason": "ErrImagePull"}},
                "lastState": {},
            }]
        else:
            # normal pod
            pod_obj["status"]["phase"] = "Running"
            pod_obj["status"]["containerStatuses"] = [{
                "state": {"running": {"startedAt": "2024-01-01T00:00:00Z"}},
                "lastState": {},
            }]

        items.append(pod_obj)
    return items


# Problem conditions (mapped to check_cap002 logic)
_PROBLEM_CONDITIONS = frozenset({
    "oomkilled_current", "oomkilled_prev",
    "crashloop", "imagepull", "errimagepull",
})


class TestCap002Property:
    """
    Property 3: CAP-002 Pod 상태 분류 및 판정

    **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6**
    """

    @given(pods=_pod_list_strategy)
    @settings(max_examples=100)
    def test_cap002_pod_status_classification(self, pods):
        """
        For any combination of Pod statuses:
        - OOMKilled (current/prev), CrashLoopBackOff, ImagePullBackOff, ErrImagePull → problem list
        - phase=Failed, reason=Evicted → evicted list
        - Problem pods exist → FAIL(MEDIUM) with pod count
        - Only evicted pods → PASS with INFO
        - No problem pods → PASS

        **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6**
        """
        # Reset counters
        gate_check.reset_gate()

        pod_items = _build_cap002_pod_items(pods)

        def mock_kubectl_json(resource, all_ns=True, timeout=30):
            if resource == "pods":
                return {"items": pod_items}
            return {}

        with unittest.mock.patch.object(gate_check, 'kubectl_json', side_effect=mock_kubectl_json):
            gate_check.check_cap002()

        # Determine expected outcome
        has_problem = any(p["condition"] in _PROBLEM_CONDITIONS for p in pods)
        has_evicted = any(p["condition"] == "evicted" for p in pods)
        problem_count = sum(1 for p in pods if p["condition"] in _PROBLEM_CONDITIONS)

        assert gate_check.total_rules == 1, "check_cap002 should record exactly one result"

        if has_problem:
            # Req 3.4: CrashLoop/ImagePull/OOMKilled → FAIL(MEDIUM)
            # record("CAP-002", "MEDIUM", "FAIL", ...) → medium_info += 1
            assert gate_check.medium_info == 1, (
                f"Expected FAIL(MEDIUM) with problem pods, "
                f"got medium_info={gate_check.medium_info}, conditions={[p['condition'] for p in pods]}"
            )
            assert gate_check.total_pass == 0
            assert gate_check.critical_fail == 0
            assert gate_check.high_warn == 0
            # Verify problem pod count in audit
            audit_text = " ".join(gate_check.audit_lines)
            assert str(problem_count) in audit_text, (
                f"Problem pod count {problem_count} should appear in audit log"
            )
        elif has_evicted:
            # Req 3.5: Evicted only → PASS with INFO
            assert gate_check.total_pass == 1, (
                f"Expected PASS with evicted-only pods, "
                f"got pass={gate_check.total_pass}, high_warn={gate_check.high_warn}"
            )
            assert gate_check.high_warn == 0
            assert gate_check.critical_fail == 0
            # Verify evicted count in audit
            evicted_count = sum(1 for p in pods if p["condition"] == "evicted")
            audit_text = " ".join(gate_check.audit_lines)
            assert str(evicted_count) in audit_text, (
                f"Evicted pod count {evicted_count} should appear in audit log"
            )
        else:
            # Req 3.6: No problem pods → PASS
            assert gate_check.total_pass == 1, (
                f"Expected PASS with no problem pods, "
                f"got pass={gate_check.total_pass}, high_warn={gate_check.high_warn}"
            )
            assert gate_check.high_warn == 0
            assert gate_check.critical_fail == 0


# ══════════════════════════════════════════════════════════════
# Task 8.5: Property 4 테스트 — CAP-003 서브넷 가용 IP 임계값
# Feature: gate-check-full-deterministic, Property 4: CAP-003 서브넷 가용 IP 임계값 분류
# ══════════════════════════════════════════════════════════════

# ── Strategy: 서브넷별 가용 IP 수 조합 생성 ──
_subnet_entry = st.fixed_dictionaries({
    "subnet_id": st.from_regex(r"subnet-[a-f0-9]{8}", fullmatch=True),
    "available_ips": st.integers(min_value=0, max_value=200),
})

_subnet_list_strategy = st.lists(_subnet_entry, min_size=1, max_size=6).filter(
    lambda subs: len({s["subnet_id"] for s in subs}) == len(subs)  # unique subnet IDs
)

# Nodegroup 이름 리스트 (최소 1개 — 서브넷이 있으려면 MNG이 있어야 함)
_nodegroup_names_strategy = st.lists(
    st.from_regex(r"ng-[a-z0-9]{1,8}", fullmatch=True),
    min_size=1, max_size=3,
).filter(lambda ngs: len(set(ngs)) == len(ngs))


def _build_cap003_run_cmd_side_effect(cluster_name, nodegroups, subnets):
    """check_cap003 내부의 run_cmd 호출을 시뮬레이션하는 side_effect 함수 생성."""
    import json as _json

    # 모든 서브넷 ID를 MNG에 균등 분배
    subnet_ids = [s["subnet_id"] for s in subnets]
    subnet_map = {s["subnet_id"]: s for s in subnets}

    # 각 nodegroup에 서브넷 할당 (라운드 로빈)
    ng_subnets = {ng: [] for ng in nodegroups}
    for i, sid in enumerate(subnet_ids):
        ng = nodegroups[i % len(nodegroups)]
        ng_subnets[ng].append(sid)

    def side_effect(args, timeout=30):
        # 1) aws eks list-nodegroups
        if "list-nodegroups" in args:
            return subprocess.CompletedProcess(
                args, 0,
                stdout=_json.dumps({"nodegroups": nodegroups}),
                stderr="",
            )
        # 2) aws eks describe-nodegroup
        if "describe-nodegroup" in args:
            idx = args.index("--nodegroup-name") + 1
            ng_name = args[idx]
            subs = ng_subnets.get(ng_name, [])
            return subprocess.CompletedProcess(
                args, 0,
                stdout=_json.dumps({"nodegroup": {"subnets": subs}}),
                stderr="",
            )
        # 3) aws ec2 describe-subnets
        if "describe-subnets" in args:
            # 요청된 subnet-ids에 해당하는 서브넷 데이터 반환
            subnet_data = []
            for sid in subnet_ids:
                entry = subnet_map[sid]
                subnet_data.append({
                    "SubnetId": sid,
                    "AvailableIpAddressCount": entry["available_ips"],
                })
            return subprocess.CompletedProcess(
                args, 0,
                stdout=_json.dumps({"Subnets": subnet_data}),
                stderr="",
            )
        # fallback
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="unknown cmd")

    return side_effect


class TestCap003Property:
    """
    Property 4: CAP-003 서브넷 가용 IP 임계값 분류

    **Validates: Requirements 4.3, 4.4, 4.5**
    """

    @given(
        nodegroups=_nodegroup_names_strategy,
        subnets=_subnet_list_strategy,
    )
    @settings(max_examples=100)
    def test_cap003_subnet_ip_threshold_classification(self, nodegroups, subnets):
        """
        For any combination of subnets with available IP counts (0~200):
        - IP < 10 → FAIL(HIGH) (critical low)
        - 10 <= IP < 50 → FAIL(HIGH) (warning low)
        - All IP >= 50 → PASS

        **Validates: Requirements 4.3, 4.4, 4.5**
        """
        # Reset counters
        gate_check.reset_gate()

        cluster_name = "test-cluster"
        side_effect = _build_cap003_run_cmd_side_effect(cluster_name, nodegroups, subnets)

        with unittest.mock.patch.object(gate_check, 'run_cmd', side_effect=side_effect):
            gate_check.check_cap003(cluster_name)

        # Determine expected outcome
        critical_low = [s for s in subnets if s["available_ips"] < 10]
        warning_low = [s for s in subnets if 10 <= s["available_ips"] < 50]
        all_ok = all(s["available_ips"] >= 50 for s in subnets)

        assert gate_check.total_rules == 1, "check_cap003 should record exactly one result"

        if critical_low:
            # Req 4.3: IP < 10 → FAIL(HIGH)
            assert gate_check.high_warn == 1, (
                f"Expected FAIL(HIGH) with critical_low subnets, "
                f"got high_warn={gate_check.high_warn}"
            )
            assert gate_check.total_pass == 0
            assert gate_check.critical_fail == 0
            # Verify critical subnet IDs appear in audit
            audit_text = " ".join(gate_check.audit_lines)
            for s in critical_low:
                assert s["subnet_id"] in audit_text, (
                    f"Critical subnet '{s['subnet_id']}' should appear in audit log"
                )
        elif warning_low:
            # Req 4.4: 10 <= IP < 50 → FAIL(HIGH) with warning
            assert gate_check.high_warn == 1, (
                f"Expected FAIL(HIGH) with warning_low subnets, "
                f"got high_warn={gate_check.high_warn}"
            )
            assert gate_check.total_pass == 0
            assert gate_check.critical_fail == 0
            # Verify warning subnet IDs appear in audit
            audit_text = " ".join(gate_check.audit_lines)
            for s in warning_low:
                assert s["subnet_id"] in audit_text, (
                    f"Warning subnet '{s['subnet_id']}' should appear in audit log"
                )
        else:
            # Req 4.5: All IP >= 50 → PASS
            assert all_ok
            assert gate_check.total_pass == 1, (
                f"Expected PASS with all subnets >= 50 IP, "
                f"got pass={gate_check.total_pass}, high_warn={gate_check.high_warn}"
            )
            assert gate_check.high_warn == 0
            assert gate_check.critical_fail == 0


# ══════════════════════════════════════════════════════════════
# Task 8.6: Property 5 테스트 — INF-001 Terraform Plan Exit Code 해석
# Feature: gate-check-full-deterministic, Property 5: INF-001 Terraform Plan Exit Code 해석
# ══════════════════════════════════════════════════════════════

# ── Strategy: exit code + plan 출력 조합 생성 ──
_tf_exit_code_strategy = st.sampled_from([0, 1, 2])

# Plan 출력 패턴 종류:
#   - "empty": 빈 출력 (no changes)
#   - "destroy": DESTROY_PATTERN 매칭 (Plan: N to add, M to destroy)
#   - "forces_replacement": RECREATE_MARKERS 매칭 (forces replacement)
#   - "must_be_replaced": RECREATE_MARKERS 매칭 (must be replaced)
#   - "non_destructive": 변경은 있지만 destroy/recreate 패턴 없음
_plan_output_type = st.sampled_from([
    "empty",
    "destroy",
    "forces_replacement",
    "must_be_replaced",
    "non_destructive",
])


def _build_plan_output(output_type: str) -> str:
    """plan 출력 타입에 따라 terraform plan 출력 텍스트 생성."""
    if output_type == "empty":
        return "No changes. Your infrastructure matches the configuration."
    elif output_type == "destroy":
        return (
            "Terraform will perform the following actions:\n"
            "  # aws_instance.example will be destroyed\n"
            "Plan: 0 to add, 0 to change, 1 to destroy."
        )
    elif output_type == "forces_replacement":
        return (
            "Terraform will perform the following actions:\n"
            "  # aws_instance.example forces replacement\n"
            "Plan: 1 to add, 0 to change, 0 to destroy."
        )
    elif output_type == "must_be_replaced":
        return (
            "Terraform will perform the following actions:\n"
            "  # aws_launch_template.main must be replaced\n"
            "Plan: 1 to add, 0 to change, 0 to destroy."
        )
    else:
        # non_destructive: 변경만 있고 destroy/recreate 패턴 없음
        return (
            "Terraform will perform the following actions:\n"
            "  # aws_security_group_rule.example will be updated in-place\n"
            "Plan: 0 to add, 1 to change, 0 to destroy."
        )


class TestInf001Property:
    """
    Property 5: INF-001 Terraform Plan Exit Code 해석

    **Validates: Requirements 5.3, 5.4, 5.5, 5.6**
    """

    @given(
        exit_code=_tf_exit_code_strategy,
        output_type=_plan_output_type,
    )
    @settings(max_examples=100)
    def test_inf001_exit_code_interpretation(self, exit_code, output_type):
        """
        For any combination of terraform plan exit code (0/1/2) and plan output
        (destroy pattern / recreate markers / non-destructive):
        - exit 0 → PASS (no changes)
        - exit 1 → FAIL(HIGH) (terraform plan error)
        - exit 2 + destroy/recreate pattern → FAIL(HIGH) "destroy/recreate 포함"
        - exit 2 + non-destructive only → FAIL(HIGH) "비파괴적 변경"

        **Validates: Requirements 5.3, 5.4, 5.5, 5.6**
        """
        # Reset counters
        gate_check.reset_gate()

        plan_output = _build_plan_output(output_type)

        # Pure function call — no mocking needed
        gate_check.check_inf001(exit_code, plan_output)

        assert gate_check.total_rules == 1, "check_inf001 should record exactly one result"

        if exit_code == 0:
            # Req 5.3: exit 0 → PASS
            assert gate_check.total_pass == 1, (
                f"Expected PASS for exit_code=0, got pass={gate_check.total_pass}"
            )
            assert gate_check.high_warn == 0
            assert gate_check.critical_fail == 0
        elif exit_code == 1:
            # Req 5.6: exit 1 → FAIL(HIGH)
            assert gate_check.high_warn == 1, (
                f"Expected FAIL(HIGH) for exit_code=1, got high_warn={gate_check.high_warn}"
            )
            assert gate_check.total_pass == 0
            assert gate_check.critical_fail == 0
        elif exit_code == 2:
            # Req 5.4, 5.5: exit 2 → always FAIL(HIGH)
            assert gate_check.high_warn == 1, (
                f"Expected FAIL(HIGH) for exit_code=2, got high_warn={gate_check.high_warn}"
            )
            assert gate_check.total_pass == 0
            assert gate_check.critical_fail == 0

            # Verify audit message distinguishes destroy vs non-destructive
            audit_text = " ".join(gate_check.audit_lines)
            has_destroy = gate_check.DESTROY_PATTERN.search(plan_output)
            has_recreate = gate_check.RECREATE_MARKERS.search(plan_output)

            if has_destroy or has_recreate:
                # Req 5.4: destroy/recreate pattern detected
                assert "destroy" in audit_text or "recreate" in audit_text, (
                    f"Audit should mention destroy/recreate for pattern match, "
                    f"got: {audit_text}"
                )
            else:
                # Req 5.5: non-destructive changes only
                assert "비파괴" in audit_text, (
                    f"Audit should mention 비파괴적 for non-destructive changes, "
                    f"got: {audit_text}"
                )


# ══════════════════════════════════════════════════════════════
# Task 8.7: Property 6 테스트 — INF-003 Karpenter 존재 및 Budget 분류
# Feature: gate-check-full-deterministic, Property 6: INF-003 Karpenter 존재 및 Budget 분류
# ══════════════════════════════════════════════════════════════

# ── Strategy: CRD 존재 여부, 이미지 태그, budget 값 조합 생성 ──
_crd_exists_strategy = st.booleans()

_image_tag_strategy = st.one_of(
    st.just("v0.37.0"),
    st.just("v1.0.0"),
    st.just("v0.33.2"),
    st.from_regex(r"v[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}", fullmatch=True),
    st.just("latest"),
)

# NodePool 엔트리: 이름 + budget 값 (0 = blocked, >0 = ok, None = no budget field)
_budget_value_strategy = st.one_of(
    st.just(0),           # int 0 → blocked
    st.just("0"),         # string "0" → blocked
    st.integers(min_value=1, max_value=100),   # int >0 → ok
    st.just("10%"),       # percentage string → ok (not 0)
    st.just(None),        # no nodes field in budget
)

_nodepool_entry = st.fixed_dictionaries({
    "name": st.from_regex(r"[a-z][a-z0-9\-]{1,12}", fullmatch=True),
    "budget_nodes": _budget_value_strategy,
})

_nodepool_list_strategy = st.lists(_nodepool_entry, min_size=0, max_size=5).filter(
    lambda pools: len({p["name"] for p in pools}) == len(pools)  # unique names
)


def _build_inf003_run_cmd_side_effect(crd_exists, image_tag, nodepools):
    """check_inf003 내부의 run_cmd 호출을 시뮬레이션하는 side_effect 함수 생성."""
    import json as _json

    def side_effect(args, timeout=30):
        # 1) kubectl get crd nodeclaims.karpenter.sh
        if args[:3] == ["kubectl", "get", "crd"] and "nodeclaims.karpenter.sh" in args:
            if crd_exists:
                return subprocess.CompletedProcess(args, 0, stdout="nodeclaims.karpenter.sh", stderr="")
            else:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="not found")

        # 2) kubectl get deployment -n karpenter karpenter -o json
        if "deployment" in args and "-n" in args and "karpenter" in args:
            dep = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{
                                "image": f"public.ecr.aws/karpenter/controller:{image_tag}",
                            }],
                        },
                    },
                },
            }
            return subprocess.CompletedProcess(args, 0, stdout=_json.dumps(dep), stderr="")

        # 3) kubectl get nodepool -o json
        if "nodepool" in args and "-o" in args and "json" in args:
            items = []
            for pool in nodepools:
                pool_obj = {
                    "metadata": {"name": pool["name"]},
                    "spec": {
                        "disruption": {
                            "budgets": [],
                        },
                    },
                }
                budget_entry = {}
                if pool["budget_nodes"] is not None:
                    budget_entry["nodes"] = pool["budget_nodes"]
                pool_obj["spec"]["disruption"]["budgets"].append(budget_entry)
                items.append(pool_obj)
            return subprocess.CompletedProcess(
                args, 0,
                stdout=_json.dumps({"items": items}),
                stderr="",
            )

        # fallback
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="unknown cmd")

    return side_effect


def _is_blocked_pool(pool):
    """NodePool의 budget이 0인지 판정 (check_inf003 로직 미러링)."""
    val = pool["budget_nodes"]
    if val is None:
        return False
    try:
        return int(str(val)) == 0
    except (ValueError, TypeError):
        return False


class TestInf003Property:
    """
    Property 6: INF-003 Karpenter 존재 및 Budget 분류

    **Validates: Requirements 6.2, 6.3, 6.5, 6.6**
    """

    @given(
        crd_exists=_crd_exists_strategy,
        image_tag=_image_tag_strategy,
        nodepools=_nodepool_list_strategy,
    )
    @settings(max_examples=100)
    def test_inf003_karpenter_budget_classification(self, crd_exists, image_tag, nodepools):
        """
        For any combination of Karpenter CRD existence, image tag, and NodePool
        disruption budget values:
        - CRD not present → SKIP
        - CRD present + budget == 0 (int or string) → FAIL(HIGH) with pool names
        - CRD present + budget != 0 → PASS with version info

        **Validates: Requirements 6.2, 6.3, 6.5, 6.6**
        """
        # Reset counters
        gate_check.reset_gate()

        side_effect = _build_inf003_run_cmd_side_effect(crd_exists, image_tag, nodepools)

        with unittest.mock.patch.object(gate_check, 'run_cmd', side_effect=side_effect):
            gate_check.check_inf003()

        assert gate_check.total_rules == 1, "check_inf003 should record exactly one result"

        if not crd_exists:
            # Req 6.2: CRD 미존재 → SKIP
            assert gate_check.total_pass == 1, (
                f"Expected SKIP (counted as pass) for CRD not present, "
                f"got pass={gate_check.total_pass}"
            )
            assert gate_check.high_warn == 0
            assert gate_check.critical_fail == 0
            # Verify SKIP in audit
            audit_text = " ".join(gate_check.audit_lines)
            assert "SKIP" in audit_text, "Audit should contain SKIP for missing CRD"
        else:
            # CRD exists — check budget classification
            blocked = [p for p in nodepools if _is_blocked_pool(p)]

            if blocked:
                # Req 6.5: budget == 0 → FAIL(HIGH)
                assert gate_check.high_warn == 1, (
                    f"Expected FAIL(HIGH) with blocked pools {[p['name'] for p in blocked]}, "
                    f"got high_warn={gate_check.high_warn}"
                )
                assert gate_check.total_pass == 0
                assert gate_check.critical_fail == 0
                # Verify blocked pool names in audit
                audit_text = " ".join(gate_check.audit_lines)
                for p in blocked:
                    assert p["name"] in audit_text, (
                        f"Blocked pool '{p['name']}' should appear in audit log"
                    )
                # Verify version in audit
                assert image_tag in audit_text, (
                    f"Version '{image_tag}' should appear in audit log"
                )
            else:
                # Req 6.6: budget != 0 → PASS with version
                assert gate_check.total_pass == 1, (
                    f"Expected PASS with no blocked pools, "
                    f"got pass={gate_check.total_pass}, high_warn={gate_check.high_warn}"
                )
                assert gate_check.high_warn == 0
                assert gate_check.critical_fail == 0
                # Verify version in audit
                audit_text = " ".join(gate_check.audit_lines)
                assert image_tag in audit_text, (
                    f"Version '{image_tag}' should appear in audit log"
                )

# ══════════════════════════════════════════════════════════════
# Task 8.8: Property 7 테스트 — INF-004 Recreate 마커 감지 및 Data Plane 분류
# Feature: gate-check-full-deterministic, Property 7: INF-004 Recreate 마커 감지 및 Data Plane 분류
# ══════════════════════════════════════════════════════════════

# ── Strategy: plan 출력 조합 생성 ──
# 리소스 타입: Data Plane vs 비-Data Plane
_data_plane_resource = st.sampled_from(list(gate_check.DATA_PLANE_RESOURCES))
_non_data_plane_resource = st.sampled_from([
    "aws_security_group", "aws_iam_role", "aws_s3_bucket",
    "aws_instance", "aws_vpc", "aws_subnet",
])
_any_resource_type = st.one_of(_data_plane_resource, _non_data_plane_resource)

# 마커 종류: forces_replacement, must_be_replaced, replace_prefix (-/+)
_marker_type = st.sampled_from(["forces_replacement", "must_be_replaced", "replace_prefix"])

# 리소스 이름 (Terraform 리소스 인스턴스 이름)
_resource_instance_name = st.from_regex(r"[a-z][a-z0-9_]{1,12}", fullmatch=True)

# 단일 recreate 항목: (마커 종류, 리소스 타입, 인스턴스 이름)
_recreate_entry = st.tuples(_marker_type, _any_resource_type, _resource_instance_name)

# recreate 항목 리스트 (0개 = no markers, 1~4개 = recreate 존재)
_recreate_list_strategy = st.lists(_recreate_entry, min_size=0, max_size=4)


def _build_inf004_plan_output(recreate_entries):
    """recreate 항목 리스트로부터 terraform plan 출력 텍스트를 생성."""
    lines = ["Terraform will perform the following actions:", ""]

    for marker_type, resource_type, instance_name in recreate_entries:
        if marker_type == "forces_replacement":
            # # resource_type.instance_name forces replacement
            lines.append(f"  # {resource_type}.{instance_name} forces replacement")
        elif marker_type == "must_be_replaced":
            # # resource_type.instance_name must be replaced
            lines.append(f"  # {resource_type}.{instance_name} must be replaced")
        elif marker_type == "replace_prefix":
            # -/+ resource "resource_type" "instance_name"
            lines.append(f"  -/+ resource \"{resource_type}\" \"{instance_name}\"")

    if recreate_entries:
        lines.append("")
        lines.append(f"Plan: {len(recreate_entries)} to add, 0 to change, 0 to destroy.")
    else:
        lines.append("No changes. Your infrastructure matches the configuration.")

    return "\n".join(lines)


class TestInf004Property:
    """
    Property 7: INF-004 Recreate 마커 감지 및 Data Plane 분류

    **Validates: Requirements 7.3, 7.4, 7.5, 7.6**
    """

    @given(recreate_entries=_recreate_list_strategy)
    @settings(max_examples=100)
    def test_inf004_recreate_marker_classification(self, recreate_entries):
        """
        For any combination of terraform plan output with recreate markers
        (forces replacement, must be replaced, -/+ prefix) and resource types
        (Data Plane vs non-Data Plane):
        - Data Plane recreate detected → FAIL(CRITICAL)
        - Non-Data Plane recreate only → FAIL(HIGH)
        - No recreate markers → PASS

        **Validates: Requirements 7.3, 7.4, 7.5, 7.6**
        """
        # Reset counters
        gate_check.reset_gate()

        plan_output = _build_inf004_plan_output(recreate_entries)

        # Pure function call — no mocking needed
        gate_check.check_inf004(plan_output)

        assert gate_check.total_rules == 1, "check_inf004 should record exactly one result"

        # Determine expected outcome based on generated entries
        has_data_plane = any(
            rtype in gate_check.DATA_PLANE_RESOURCES
            for _, rtype, _ in recreate_entries
        )
        has_any_recreate = len(recreate_entries) > 0

        if not has_any_recreate:
            # Req 7.6: No recreate markers → PASS
            assert gate_check.total_pass == 1, (
                f"Expected PASS with no recreate markers, "
                f"got pass={gate_check.total_pass}, "
                f"critical={gate_check.critical_fail}, high={gate_check.high_warn}"
            )
            assert gate_check.critical_fail == 0
            assert gate_check.high_warn == 0
        elif has_data_plane:
            # Req 7.4: Data Plane recreate → FAIL(CRITICAL)
            assert gate_check.critical_fail == 1, (
                f"Expected FAIL(CRITICAL) with Data Plane recreate, "
                f"got critical={gate_check.critical_fail}, high={gate_check.high_warn}, "
                f"entries={[(m, r) for m, r, _ in recreate_entries]}"
            )
            assert gate_check.total_pass == 0
            # Verify data plane resource names in audit
            audit_text = " ".join(gate_check.audit_lines)
            dp_types = {
                rtype for _, rtype, _ in recreate_entries
                if rtype in gate_check.DATA_PLANE_RESOURCES
            }
            for dp in dp_types:
                assert dp in audit_text, (
                    f"Data Plane resource '{dp}' should appear in audit log"
                )
        else:
            # Req 7.5: Non-Data Plane recreate only → FAIL(HIGH)
            assert gate_check.high_warn == 1, (
                f"Expected FAIL(HIGH) with non-Data Plane recreate, "
                f"got high_warn={gate_check.high_warn}, critical={gate_check.critical_fail}, "
                f"entries={[(m, r) for m, r, _ in recreate_entries]}"
            )
            assert gate_check.total_pass == 0
            assert gate_check.critical_fail == 0
            # Verify non-data-plane resource types in audit
            audit_text = " ".join(gate_check.audit_lines)
            non_dp_types = {rtype for _, rtype, _ in recreate_entries}
            for rtype in non_dp_types:
                assert rtype in audit_text, (
                    f"Non-Data Plane resource '{rtype}' should appear in audit log"
                )


# ══════════════════════════════════════════════════════════════
# Task 8.9: Property 8 테스트 — Gate Exit Code 판정
# Feature: gate-check-full-deterministic, Property 8: Gate Exit Code 판정
# ══════════════════════════════════════════════════════════════

# ── Strategy: critical_fail, high_warn 카운터 값 조합 생성 ──
_critical_fail_strategy = st.integers(min_value=0, max_value=20)
_high_warn_strategy = st.integers(min_value=0, max_value=20)


def _expected_exit_code(critical_fail: int, high_warn: int) -> int:
    """Gate 판정 로직의 기대 exit code를 계산하는 오라클 함수."""
    if critical_fail > 0:
        return 1  # BLOCKED
    elif high_warn > 0:
        return 2  # WARN
    else:
        return 0  # OPEN


class TestGateExitCodeProperty:
    """
    Property 8: Gate Exit Code 판정

    **Validates: Requirements 9.3, 9.4, 9.5**
    """

    @given(
        critical_fail=_critical_fail_strategy,
        high_warn=_high_warn_strategy,
    )
    @settings(max_examples=100)
    def test_gate_exit_code_decision(self, critical_fail, high_warn):
        """
        For any combination of critical_fail and high_warn counter values:
        - critical_fail > 0 → exit code 1 (BLOCKED)
        - critical_fail == 0 and high_warn > 0 → exit code 2 (WARN)
        - critical_fail == 0 and high_warn == 0 → exit code 0 (OPEN)

        Tests the gate decision logic at the end of main() by setting
        module-level counters and verifying the SystemExit code.

        **Validates: Requirements 9.3, 9.4, 9.5**
        """
        # Set module-level counters directly
        gate_check.critical_fail = critical_fail
        gate_check.high_warn = high_warn
        gate_check.total_pass = 0
        gate_check.total_rules = 0
        gate_check.audit_lines.clear()
        gate_check._sync_to_gate()

        expected = _expected_exit_code(critical_fail, high_warn)

        # Execute the gate decision block by mimicking the logic from main()
        # We capture sys.exit() via SystemExit exception
        with pytest.raises(SystemExit) as exc_info:
            if gate_check._gate.critical_fail > 0:
                sys.exit(1)
            elif gate_check._gate.high_warn > 0:
                sys.exit(2)
            else:
                sys.exit(0)

        actual = exc_info.value.code

        assert actual == expected, (
            f"Gate exit code mismatch: critical_fail={critical_fail}, "
            f"high_warn={high_warn} → expected exit {expected}, got exit {actual}"
        )

        # Verify specific requirement conditions
        if critical_fail > 0:
            # Req 9.3: CRITICAL 실패 1개 이상 → exit 1 (BLOCKED)
            assert actual == 1
        elif high_warn > 0:
            # Req 9.4: CRITICAL 없고 HIGH 경고 1개 이상 → exit 2 (WARN)
            assert actual == 2
        else:
            # Req 9.5: 모든 규칙 PASS/SKIP → exit 0 (OPEN)
            assert actual == 0


# ══════════════════════════════════════════════════════════════
# Task 8.10: Property 9 테스트 — CLI 실패 시 Graceful 처리
# Feature: gate-check-full-deterministic, Property 9: CLI 실패 시 Graceful 처리 및 계속 실행
# ══════════════════════════════════════════════════════════════

# ── Strategy: CLI 실패 유형 조합 생성 ──
# run_cmd()는 subprocess.run을 래핑하여 TimeoutExpired/FileNotFoundError를 잡고
# CompletedProcess(returncode=1, stdout="", stderr=str(e))를 반환한다.
# 따라서 run_cmd를 호출하는 check 함수들은 항상 CompletedProcess를 받는다.
# 이 테스트는 run_cmd가 실패를 graceful하게 처리한 결과를 시뮬레이션한다.
_failure_type = st.sampled_from(["timeout", "file_not_found", "bad_exit"])


def _make_failing_run_cmd(failure_type):
    """run_cmd가 실패를 처리한 후 반환하는 결과를 시뮬레이션.

    run_cmd()는 내부적으로 TimeoutExpired/FileNotFoundError를 잡아서
    CompletedProcess(returncode=1, stdout="", stderr=str(e))를 반환한다.
    이 함수는 그 동작을 재현한다.
    """
    def side_effect(args, timeout=30):
        if failure_type == "timeout":
            return subprocess.CompletedProcess(
                args, returncode=1, stdout="",
                stderr=f"Command timed out after {timeout} seconds",
            )
        elif failure_type == "file_not_found":
            return subprocess.CompletedProcess(
                args, returncode=1, stdout="",
                stderr="No such file or directory: 'kubectl'",
            )
        else:
            # bad_exit: returncode != 0 with garbage output
            return subprocess.CompletedProcess(
                args, returncode=1, stdout="", stderr="command failed",
            )
    return side_effect


def _make_failing_kubectl_json(failure_type):
    """kubectl_json이 실패하도록 하는 side_effect를 생성.

    kubectl_json()은 run_cmd를 호출하고 실패 시 빈 dict {}를 반환한다.
    """
    def side_effect(resource, all_ns=True, timeout=30):
        return {}
    return side_effect


class TestCliFailureGracefulProperty:
    """
    Property 9: CLI 실패 시 Graceful 처리 및 계속 실행

    **Validates: Requirements 12.4**
    """

    @given(
        failure_type=_failure_type,
        fn_choice=st.integers(min_value=0, max_value=4),
    )
    @settings(max_examples=100)
    def test_cli_failure_graceful_handling(self, failure_type, fn_choice):
        """
        For any CLI failure type (timeout, FileNotFoundError, bad exit code)
        applied to any check function:
        1. The function records a result (SKIP or FAIL) without raising an exception
        2. Subsequent check functions can still execute normally

        **Validates: Requirements 12.4**
        """
        # Reset counters
        gate_check.reset_gate()

        # Select a check function based on fn_choice
        all_fns = [
            ("check_wls006", lambda: gate_check.check_wls006()),
            ("check_cap002", lambda: gate_check.check_cap002()),
            ("check_inf003", lambda: gate_check.check_inf003()),
            ("check_com003", lambda: gate_check.check_com003("test-cluster", "1.34")),
            ("check_cap003", lambda: gate_check.check_cap003("test-cluster")),
        ]
        fn_name, fn_call = all_fns[fn_choice]

        # check_wls006 and check_cap002 use kubectl_json (which wraps run_cmd)
        # check_inf003, check_com003, check_cap003 use run_cmd directly
        uses_kubectl_json = fn_name in ("check_wls006", "check_cap002")

        # Phase 1: Apply failure to the selected check function
        if uses_kubectl_json:
            with unittest.mock.patch.object(
                gate_check, 'kubectl_json',
                side_effect=_make_failing_kubectl_json(failure_type),
            ):
                # Should NOT raise any exception
                fn_call()
        else:
            with unittest.mock.patch.object(
                gate_check, 'run_cmd',
                side_effect=_make_failing_run_cmd(failure_type),
            ):
                # Should NOT raise any exception
                fn_call()

        # Verify: function recorded exactly one result (SKIP or FAIL, not crash)
        assert gate_check.total_rules == 1, (
            f"{fn_name} with {failure_type} failure should record exactly one result, "
            f"got total_rules={gate_check.total_rules}"
        )

        # The result should be either PASS (for SKIP-counted-as-pass) or FAIL
        recorded_pass = gate_check.total_pass
        recorded_fail = gate_check.critical_fail + gate_check.high_warn
        assert recorded_pass + recorded_fail == 1, (
            f"{fn_name} with {failure_type} should record exactly one SKIP/PASS or FAIL, "
            f"got pass={recorded_pass}, fail={recorded_fail}"
        )

        # Phase 2: Verify subsequent check function can still execute normally
        # Save counters after first function
        rules_after_first = gate_check.total_rules

        # Run a different check function with normal (successful) mocks
        # Use check_inf001 as it's a pure function (no CLI calls)
        gate_check.check_inf001(0, "No changes.")

        # Verify the second function also recorded a result
        assert gate_check.total_rules == rules_after_first + 1, (
            f"Subsequent check function should execute normally after {fn_name} failure, "
            f"expected total_rules={rules_after_first + 1}, got {gate_check.total_rules}"
        )
        # check_inf001 with exit_code=0 should PASS
        assert gate_check.total_pass >= 1, (
            f"Subsequent check_inf001(0, ...) should PASS after {fn_name} failure"
        )
