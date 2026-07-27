"""
tests/test_service_watch.py — service_watch.py 단위 테스트

순수 함수(count/evaluate/parse)와 watch_loop(의존성 주입)를 검증한다.
"""

import json

import pytest

import service_watch


# ══════════════════════════════════════════════════════════════
# count_ready_endpoints
# ══════════════════════════════════════════════════════════════
class TestCountReadyEndpoints:
    def test_counts_only_ready_addresses(self):
        es = {"items": [{
            "endpoints": [
                {"addresses": ["10.0.0.1"], "conditions": {"ready": True}},
                {"addresses": ["10.0.0.2"], "conditions": {"ready": False}},
            ]
        }]}
        assert service_watch.count_ready_endpoints(es) == 1

    def test_sums_across_multiple_slices(self):
        es = {"items": [
            {"endpoints": [{"addresses": ["10.0.0.1", "10.0.0.2"], "conditions": {"ready": True}}]},
            {"endpoints": [{"addresses": ["10.0.0.3"], "conditions": {"ready": True}}]},
        ]}
        assert service_watch.count_ready_endpoints(es) == 3

    def test_empty_returns_zero(self):
        assert service_watch.count_ready_endpoints({"items": []}) == 0


# ══════════════════════════════════════════════════════════════
# evaluate_endpoint_state
# ══════════════════════════════════════════════════════════════
class TestEvaluateEndpointState:
    def test_below_min_emits_warn(self):
        warn, seen = service_watch.evaluate_endpoint_state("api", "prod", 2, 1, set())
        assert warn is not None
        assert warn["ready"] == 1 and warn["min"] == 2
        assert "prod/api" in seen

    def test_at_or_above_min_no_warn(self):
        warn, seen = service_watch.evaluate_endpoint_state("api", "prod", 2, 2, set())
        assert warn is None
        assert "prod/api" not in seen

    def test_already_degraded_not_re_emitted(self):
        _, seen = service_watch.evaluate_endpoint_state("api", "prod", 2, 0, set())
        warn2, _ = service_watch.evaluate_endpoint_state("api", "prod", 2, 0, seen)
        assert warn2 is None

    def test_recovery_drops_seen_so_relapse_re_emits(self):
        _, seen = service_watch.evaluate_endpoint_state("api", "prod", 2, 0, set())
        # 회복
        _, seen2 = service_watch.evaluate_endpoint_state("api", "prod", 2, 3, seen)
        assert "prod/api" not in seen2
        # 재악화 → 재기록
        warn3, _ = service_watch.evaluate_endpoint_state("api", "prod", 2, 1, seen2)
        assert warn3 is not None


# ══════════════════════════════════════════════════════════════
# evaluate_health_state
# ══════════════════════════════════════════════════════════════
class TestEvaluateHealthState:
    def test_failure_emits_warn(self):
        warn, seen = service_watch.evaluate_health_state("api", "prod", False, set())
        assert warn is not None
        assert "prod/api:health" in seen

    def test_ok_no_warn(self):
        warn, _ = service_watch.evaluate_health_state("api", "prod", True, set())
        assert warn is None

    def test_recovery_allows_relapse(self):
        _, seen = service_watch.evaluate_health_state("api", "prod", False, set())
        _, seen2 = service_watch.evaluate_health_state("api", "prod", True, seen)
        warn3, _ = service_watch.evaluate_health_state("api", "prod", False, seen2)
        assert warn3 is not None


# ══════════════════════════════════════════════════════════════
# parse_services
# ══════════════════════════════════════════════════════════════
class TestParseServices:
    def test_valid_full(self):
        js = '[{"name":"api","namespace":"prod","min_endpoints":2,"health_check_url":"https://h"}]'
        svcs = service_watch.parse_services(js)
        assert svcs[0]["name"] == "api"
        assert svcs[0]["min_endpoints"] == 2
        assert svcs[0]["health_check_url"] == "https://h"

    def test_min_endpoints_defaults_to_1(self):
        js = '[{"name":"api","namespace":"prod"}]'
        svcs = service_watch.parse_services(js)
        assert svcs[0]["min_endpoints"] == 1
        assert svcs[0]["health_check_url"] == ""

    def test_missing_name_raises(self):
        with pytest.raises(ValueError):
            service_watch.parse_services('[{"namespace":"prod"}]')

    def test_non_array_raises(self):
        with pytest.raises(ValueError):
            service_watch.parse_services('{"name":"api"}')


# ══════════════════════════════════════════════════════════════
# watch_loop (의존성 주입)
# ══════════════════════════════════════════════════════════════
class TestWatchLoop:
    def _one_cycle(self, audit_log, services, endpoints_fn,
                   health_fn=lambda url: True, exists_fn=lambda n, ns: True):
        clock_values = iter([0, 0, 1000])
        return service_watch.watch_loop(
            phase="P4", audit_log=str(audit_log), services=services,
            interval=1, max_duration=10,
            endpoints_fn=endpoints_fn, health_fn=health_fn, exists_fn=exists_fn,
            sleep_fn=lambda _s: None, clock=lambda: next(clock_values),
        )

    def test_degraded_endpoint_recorded(self, tmp_path):
        audit_log = tmp_path / "audit.log"
        services = [{"name": "api", "namespace": "prod", "min_endpoints": 2, "health_check_url": ""}]
        rc = self._one_cycle(audit_log, services, endpoints_fn=lambda n, ns: 1)
        assert rc == 0
        content = audit_log.read_text(encoding="utf-8")
        assert "SVC-P4" in content
        assert "ready_endpoints=1 < min=2" in content

    def test_healthy_service_no_warn(self, tmp_path):
        audit_log = tmp_path / "audit.log"
        services = [{"name": "api", "namespace": "prod", "min_endpoints": 2, "health_check_url": ""}]
        self._one_cycle(audit_log, services, endpoints_fn=lambda n, ns: 5)
        content = audit_log.read_text(encoding="utf-8")
        assert "ready_endpoints" not in content
        assert "ServiceWatch started" in content

    def test_besteffort_warning_for_missing_health_url(self, tmp_path):
        audit_log = tmp_path / "audit.log"
        services = [{"name": "api", "namespace": "prod", "min_endpoints": 1, "health_check_url": ""}]
        self._one_cycle(audit_log, services, endpoints_fn=lambda n, ns: 5)
        content = audit_log.read_text(encoding="utf-8")
        assert "BestEffort" in content

    def test_health_check_failure_recorded(self, tmp_path):
        audit_log = tmp_path / "audit.log"
        services = [{"name": "api", "namespace": "prod", "min_endpoints": 1,
                     "health_check_url": "https://api/health"}]
        rc = self._one_cycle(
            audit_log, services,
            endpoints_fn=lambda n, ns: 5,
            health_fn=lambda url: False,
        )
        assert rc == 0
        content = audit_log.read_text(encoding="utf-8")
        assert "health check 실패" in content

    def test_kubectl_failure_returns_none_does_not_crash(self, tmp_path):
        audit_log = tmp_path / "audit.log"
        services = [{"name": "api", "namespace": "prod", "min_endpoints": 2, "health_check_url": ""}]
        rc = self._one_cycle(audit_log, services, endpoints_fn=lambda n, ns: None)
        assert rc == 0

    def test_stop_file_terminates_before_polling(self, tmp_path):
        audit_log = tmp_path / "audit.log"
        stop_file = tmp_path / "stop"
        stop_file.write_text("")
        called = {"n": 0}

        def ep(n, ns):
            called["n"] += 1
            return 5

        clock_values = iter([0, 0, 0])
        services = [{"name": "api", "namespace": "prod", "min_endpoints": 1, "health_check_url": ""}]
        rc = service_watch.watch_loop(
            phase="P5", audit_log=str(audit_log), services=services,
            interval=1, max_duration=3600,
            endpoints_fn=ep, health_fn=lambda url: True, exists_fn=lambda n, ns: True,
            sleep_fn=lambda _s: None, clock=lambda: next(clock_values),
            stop_file=str(stop_file),
        )
        assert rc == 0
        assert called["n"] == 0

    def test_missing_service_warns_and_excluded(self, tmp_path):
        """존재하지 않는 서비스 → WARN 남기고 감시 대상에서 제외."""
        audit_log = tmp_path / "audit.log"
        services = [
            {"name": "ghost", "namespace": "prod", "min_endpoints": 1, "health_check_url": ""},
            {"name": "real", "namespace": "prod", "min_endpoints": 1, "health_check_url": ""},
        ]
        self._one_cycle(
            audit_log, services,
            endpoints_fn=lambda n, ns: 5,
            exists_fn=lambda n, ns: n == "real",
        )
        content = audit_log.read_text(encoding="utf-8")
        assert "ghost" in content and "Service 없음" in content
        # 감시 대상은 real 1개만
        assert "1 service(s)" in content

    def test_missing_service_no_endpoint_spam(self, tmp_path):
        """없는 서비스는 감시 제외 → ready=0 미달 WARN을 매 폴링마다 남기지 않음."""
        audit_log = tmp_path / "audit.log"
        services = [{"name": "ghost", "namespace": "prod", "min_endpoints": 2, "health_check_url": ""}]
        calls = {"n": 0}

        def ep(n, ns):
            calls["n"] += 1
            return 0

        self._one_cycle(audit_log, services, endpoints_fn=ep, exists_fn=lambda n, ns: False)
        content = audit_log.read_text(encoding="utf-8")
        assert "ready_endpoints" not in content  # 미달 스팸 없음
        assert calls["n"] == 0                    # 폴링 자체가 일어나지 않음
