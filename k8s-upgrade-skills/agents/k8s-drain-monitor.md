---
name: k8s-drain-monitor
description: >
  DEPRECATED — do NOT launch this as a sub-agent. Drain monitoring for EKS upgrades
  is now done inline: the MAIN agent runs `scripts/drain_watch.py` with
  run_in_background during Phase 2 / 4 / 5. This file documents the rationale and
  the drain_watch.py usage. It is kept for reference, not for invocation.
---

# k8s Drain Monitor — Inline Polling (sub-agent retired)

> ⚠️ **This is no longer a sub-agent.** Do not launch it via the Agent tool.
> The main agent runs `scripts/drain_watch.py` directly with `run_in_background: true`.

---

## Why the sub-agent approach was retired

The sub-agent model was specified as a `⛔ HARD GATE` but **failed to run in all 4 production-grade upgrades (2026-06-19)**. Two root causes:

1. **Permission boundary** — a sub-agent's Bash (`python3 audit_event.py`) runs under a separate permission scope, so every audit write triggered a fresh prompt and was denied. The 1st upgrade abandoned the sub-agent and fell back to inline handling (which worked).
2. **Execution-model mismatch (the deeper one)** — Claude Code agents are **synchronous call-return**. A sub-agent cannot stream a "STOP now" signal to the main agent *while* it watches; it only returns one final message. So "watch in real time and interrupt the apply on `FailedDrain`" is structurally impossible in the sub-agent model. `kubectl --watch` (infinite blocking) makes this worse.

Drain monitoring is fundamentally **periodic snapshot polling**, not a stream. Polling fits the main agent's `run_in_background` model perfectly, reuses the main session's tool permissions, and costs no extra agent context.

---

## Replacement: `scripts/drain_watch.py`

The main agent launches this in the background at the start of Phase 2 / 4 / 5:

```bash
# Phase 2 (Control Plane) — kube-system scope
python3 scripts/drain_watch.py --phase P2 --scope kube-system --audit-log audit.log

# Phase 4 (MNG rolling) / Phase 5 (Karpenter) — all namespaces
python3 scripts/drain_watch.py --phase P4 --scope all --audit-log audit.log
python3 scripts/drain_watch.py --phase P5 --scope all --audit-log audit.log
```

- Launch with **`run_in_background: true`**.
- Poll interval defaults to 30s; `--max-duration` (default 3600s) is a safety stop so it never runs forever.
- Check progress with BashOutput. A `FAIL`-severity line means **STOP and investigate**.
- Terminate after the phase gate passes: KillShell, or pass `--stop-file <path>` and `touch` it.

It writes `DRAIN-{PHASE}` entries to audit.log via the shared `lib.audit_append()` (fcntl-locked — safe to write concurrently with the gate scripts).

---

## What drain_watch.py detects each cycle

| Source | Signal | Severity |
|--------|--------|----------|
| Warning events | `FailedDrain`, `NodeClaimTerminationFailed` | FAIL |
| Warning events | `DisruptionBlocked`, `ExceededGracePeriod`, `FailedKillPod`, `NodeNotReady`, `NodeNotSchedulable`, `OOMKilling`, `FailedMount`, `NodeClaimNotFound`, `Evicted` | WARN |
| PDB status | `disruptionsAllowed == 0` (expectedPods > 0) — drain blocked | WARN |
| NodeClaim status (Phase 5) | `Ready != True` with a reason | WARN |

**Intentionally excluded**: `BackOff` — it fires constantly from CrashLoop/ImagePull unrelated to draining and would flood audit.log (the original rule only reported it ">3 occurrences"). drain_watch focuses on genuine drain-risk signals.

De-duplication: events are keyed by `uid:count` (a higher count = a genuine recurrence, re-emitted). PDB/NodeClaim are state-based — recorded once while active, dropped from the seen-set when resolved so a recurrence is recorded again.

---

## Hard constraints (enforced by the script, not the LLM)

1. **Read-only** — drain_watch.py only runs `kubectl get`; it never drains, cordons, or deletes.
2. **No interpretation** — it records raw signals. The decision to STOP/proceed stays with the main agent reading the audit/output.
3. **Audit via shared helper** — it never hand-writes audit lines; it calls `lib.audit_append()`.
</content>
