"""
tests/test_drain_watch.py — drain_watch.py 단위 테스트

순수 감지 함수(extract_*)와 watch_loop(의존성 주입)를 검증한다.
인라인 백그라운드 폴링 모니터의 핵심: 새 위험 신호만 audit에 한 번씩 기록하고,
상태성 신호(PDB/NodeClaim)는 해소되면 재발 시 다시 기록한다.
"""

import drain_watch


# ══════════════════════════════════════════════════════════════
# extract_warning_events
# ══════════════════════════════════════════════════════════════
class TestExtractWarningEvents:
    def _event(self, reason, etype="Warning", uid="u1", count=1, ns="default", obj="pod-x"):
        return {
            "type": etype,
            "reason": reason,
            "count": count,
            "metadata": {"uid": uid, "namespace": ns},
            "involvedObject": {"name": obj, "namespace": ns},
            "message": f"{reason} happened",
        }

    def test_failed_drain_classified_as_fail(self):
        # Arrange
        events = {"items": [self._event("FailedDrain")]}

        # Act
        new, seen = drain_watch.extract_warning_events(events, set())

        # Assert
        assert len(new) == 1
        assert new[0]["severity"] == "FAIL"
        assert new[0]["reason"] == "FailedDrain"

    def test_disruption_blocked_classified_as_warn(self):
        events = {"items": [self._event("DisruptionBlocked")]}
        new, _ = drain_watch.extract_warning_events(events, set())
        assert new[0]["severity"] == "WARN"

    def test_normal_type_event_ignored(self):
        events = {"items": [self._event("FailedDrain", etype="Normal")]}
        new, _ = drain_watch.extract_warning_events(events, set())
        assert new == []

    def test_unwatched_reason_ignored(self):
        events = {"items": [self._event("SomeRandomReason")]}
        new, _ = drain_watch.extract_warning_events(events, set())
        assert new == []

    def test_already_seen_event_not_re_emitted(self):
        # Arrange
        events = {"items": [self._event("OOMKilling", uid="u9", count=1)]}
        _, seen = drain_watch.extract_warning_events(events, set())

        # Act — same event, same count
        new2, _ = drain_watch.extract_warning_events(events, seen)

        # Assert
        assert new2 == []

    def test_recurring_event_with_higher_count_re_emitted(self):
        # Arrange — first occurrence count=1
        first = {"items": [self._event("OOMKilling", uid="u9", count=1)]}
        _, seen = drain_watch.extract_warning_events(first, set())

        # Act — same uid but count incremented → new occurrence
        second = {"items": [self._event("OOMKilling", uid="u9", count=2)]}
        new2, _ = drain_watch.extract_warning_events(second, seen)

        # Assert
        assert len(new2) == 1

    def test_backoff_noise_reason_excluded(self):
        # BackOff는 드레인과 무관한 노이즈라 의도적으로 감시 대상에서 제외
        events = {"items": [self._event("BackOff")]}
        new, _ = drain_watch.extract_warning_events(events, set())
        assert new == []

    def test_noisy_reason_count_increment_not_re_emitted(self):
        # FailedMount는 노드 교체 중 대량 발생하는 노이즈 — count가 올라도 재기록 X
        first = {"items": [self._event("FailedMount", uid="u5", count=1)]}
        _, seen = drain_watch.extract_warning_events(first, set())
        second = {"items": [self._event("FailedMount", uid="u5", count=7)]}
        new2, _ = drain_watch.extract_warning_events(second, seen)
        assert new2 == []

    def test_noisy_nodenotready_count_increment_not_re_emitted(self):
        first = {"items": [self._event("NodeNotReady", uid="n1", count=1)]}
        _, seen = drain_watch.extract_warning_events(first, set())
        second = {"items": [self._event("NodeNotReady", uid="n1", count=3)]}
        new2, _ = drain_watch.extract_warning_events(second, seen)
        assert new2 == []

    def test_noisy_reason_still_emitted_once(self):
        # 노이즈여도 첫 발생은 기록되어야 함 (완전 무시가 아님)
        events = {"items": [self._event("FailedMount", uid="u5", count=1)]}
        new, _ = drain_watch.extract_warning_events(events, set())
        assert len(new) == 1
        assert new[0]["reason"] == "FailedMount"

    def test_distinct_pods_same_noisy_reason_all_emitted(self):
        # 서로 다른 Pod(uid)의 같은 노이즈 reason은 각각 기록 (dedup은 동일 객체 한정)
        events = {"items": [
            self._event("FailedMount", uid="a", obj="pod-a"),
            self._event("FailedMount", uid="b", obj="pod-b"),
        ]}
        new, _ = drain_watch.extract_warning_events(events, set())
        assert len(new) == 2


# ══════════════════════════════════════════════════════════════
# extract_blocked_pdbs
# ══════════════════════════════════════════════════════════════
class TestExtractBlockedPdbs:
    def _pdb(self, name, allowed, expected=2, ns="prod"):
        return {
            "metadata": {"name": name, "namespace": ns},
            "status": {"disruptionsAllowed": allowed, "expectedPods": expected},
        }

    def test_blocked_pdb_detected(self):
        pdbs = {"items": [self._pdb("api", allowed=0)]}
        new, seen = drain_watch.extract_blocked_pdbs(pdbs, set())
        assert len(new) == 1
        assert new[0]["name"] == "api"
        assert "prod/api" in seen

    def test_healthy_pdb_ignored(self):
        pdbs = {"items": [self._pdb("api", allowed=1)]}
        new, _ = drain_watch.extract_blocked_pdbs(pdbs, set())
        assert new == []

    def test_pdb_with_zero_expected_pods_ignored(self):
        # expectedPods=0 → 워크로드 없음, 차단 의미 없음
        pdbs = {"items": [self._pdb("api", allowed=0, expected=0)]}
        new, _ = drain_watch.extract_blocked_pdbs(pdbs, set())
        assert new == []

    def test_already_recorded_pdb_not_re_emitted(self):
        pdbs = {"items": [self._pdb("api", allowed=0)]}
        _, seen = drain_watch.extract_blocked_pdbs(pdbs, set())
        new2, _ = drain_watch.extract_blocked_pdbs(pdbs, seen)
        assert new2 == []

    def test_resolved_pdb_dropped_from_seen_so_recurrence_re_emits(self):
        # Arrange — blocked, recorded
        blocked = {"items": [self._pdb("api", allowed=0)]}
        _, seen = drain_watch.extract_blocked_pdbs(blocked, set())

        # Act 1 — resolved (allowed=1): seen에서 빠져야 함
        healthy = {"items": [self._pdb("api", allowed=1)]}
        _, seen2 = drain_watch.extract_blocked_pdbs(healthy, seen)
        assert "prod/api" not in seen2

        # Act 2 — blocked again → 재기록되어야 함
        new3, _ = drain_watch.extract_blocked_pdbs(blocked, seen2)
        assert len(new3) == 1


# ══════════════════════════════════════════════════════════════
# extract_bad_nodeclaims
# ══════════════════════════════════════════════════════════════
class TestExtractBadNodeclaims:
    def _nc(self, name, ready_status, reason="Drifted"):
        conds = []
        if ready_status is not None:
            conds.append({"type": "Ready", "status": ready_status, "reason": reason, "message": "msg"})
        return {"metadata": {"name": name}, "status": {"conditions": conds}}

    def test_not_ready_nodeclaim_detected(self):
        ncs = {"items": [self._nc("nc-1", "False")]}
        new, _ = drain_watch.extract_bad_nodeclaims(ncs, set())
        assert len(new) == 1
        assert new[0]["name"] == "nc-1"

    def test_ready_nodeclaim_ignored(self):
        ncs = {"items": [self._nc("nc-1", "True")]}
        new, _ = drain_watch.extract_bad_nodeclaims(ncs, set())
        assert new == []

    def test_missing_ready_condition_held(self):
        # condition 미설정 → 판단 보류 (아직 프로비저닝 중)
        ncs = {"items": [self._nc("nc-1", None)]}
        new, _ = drain_watch.extract_bad_nodeclaims(ncs, set())
        assert new == []

    def test_already_recorded_nodeclaim_not_re_emitted(self):
        ncs = {"items": [self._nc("nc-1", "False")]}
        _, seen = drain_watch.extract_bad_nodeclaims(ncs, set())
        new2, _ = drain_watch.extract_bad_nodeclaims(ncs, seen)
        assert new2 == []


# ══════════════════════════════════════════════════════════════
# watch_loop (의존성 주입)
# ══════════════════════════════════════════════════════════════
class TestWatchLoop:
    def _run_one_cycle(self, audit_log, poll_events, poll_pdb=None, poll_nc=None,
                       max_duration=10):
        """clock을 [0, 0, 1000]으로 주입해 정확히 1 사이클만 돌린다."""
        clock_values = iter([0, 0, 1000])
        return drain_watch.watch_loop(
            phase="P5", audit_log=str(audit_log), interval=1,
            max_duration=max_duration, scope="all",
            poll_events=poll_events,
            poll_pdb=poll_pdb or (lambda: {"items": []}),
            poll_nc=poll_nc or (lambda: {"items": []}),
            sleep_fn=lambda _s: None,
            clock=lambda: next(clock_values),
        )

    def test_fail_event_returns_exit_1_and_records_audit(self, tmp_path):
        # Arrange
        audit_log = tmp_path / "audit.log"
        fail_event = {
            "items": [{
                "type": "Warning", "reason": "FailedDrain", "count": 1,
                "metadata": {"uid": "u1", "namespace": "prod"},
                "involvedObject": {"name": "node-a", "namespace": "prod"},
                "message": "cannot evict",
            }]
        }

        # Act
        rc = self._run_one_cycle(audit_log, poll_events=lambda: fail_event)

        # Assert
        assert rc == 1
        content = audit_log.read_text(encoding="utf-8")
        assert "DRAIN-P5" in content
        assert "FailedDrain" in content
        assert "FAIL" in content

    def test_no_events_returns_exit_0(self, tmp_path):
        audit_log = tmp_path / "audit.log"
        rc = self._run_one_cycle(audit_log, poll_events=lambda: {"items": []})
        assert rc == 0
        content = audit_log.read_text(encoding="utf-8")
        # 시작/종료 INFO는 남아야 함
        assert "DrainWatch started" in content
        assert "DrainWatch finished" in content

    def test_kubectl_failure_returns_none_does_not_crash(self, tmp_path):
        # poll이 None(kubectl 일시 오류)을 반환해도 루프가 죽지 않아야 함
        audit_log = tmp_path / "audit.log"
        rc = self._run_one_cycle(audit_log, poll_events=lambda: None)
        assert rc == 0

    def test_stop_file_terminates_loop(self, tmp_path):
        # Arrange — stop-file을 미리 만들어두면 첫 사이클 진입 전 종료
        audit_log = tmp_path / "audit.log"
        stop_file = tmp_path / "stop"
        stop_file.write_text("")
        called = {"n": 0}

        def poll():
            called["n"] += 1
            return {"items": []}

        clock_values = iter([0, 0, 0, 0])

        # Act
        rc = drain_watch.watch_loop(
            phase="P4", audit_log=str(audit_log), interval=1,
            max_duration=3600, scope="all",
            poll_events=poll, poll_pdb=lambda: {"items": []},
            poll_nc=lambda: {"items": []},
            sleep_fn=lambda _s: None, clock=lambda: next(clock_values),
            stop_file=str(stop_file),
        )

        # Assert — 폴링이 한 번도 실행되지 않고 종료
        assert rc == 0
        assert called["n"] == 0

    def test_blocked_pdb_recorded_as_warn(self, tmp_path):
        audit_log = tmp_path / "audit.log"
        pdb = {"items": [{
            "metadata": {"name": "api", "namespace": "prod"},
            "status": {"disruptionsAllowed": 0, "expectedPods": 2},
        }]}
        rc = self._run_one_cycle(
            audit_log, poll_events=lambda: {"items": []},
            poll_pdb=lambda: pdb,
        )
        assert rc == 0
        content = audit_log.read_text(encoding="utf-8")
        assert "DisruptionBlocked(PDB)" in content
        assert "prod/api" in content
