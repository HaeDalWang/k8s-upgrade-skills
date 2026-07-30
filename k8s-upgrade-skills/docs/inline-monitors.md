# Inline Monitors — Why They Are Not Sub-Agents

> Reference document. `drain_watch.py` and `service_watch.py` are **launched by the main agent**
> with `run_in_background: true`. There is no sub-agent to invoke, and this file is not an agent
> definition — do not try to launch anything described here via the Agent tool.

---

## Why the sub-agent approach was retired

Drain and service monitoring were originally specified as sub-agents behind a `⛔ HARD GATE`, but
**neither ran in any of the 4 production-grade upgrades** that first exercised this skill. Two root
causes, both structural:

1. **Permission boundary** — a sub-agent's Bash (`python3 audit_event.py`) runs under a separate
   permission scope, so every audit write triggered a fresh prompt and was denied. The first upgrade
   abandoned the sub-agent and fell back to inline handling, which worked.
2. **Execution-model mismatch (the deeper one)** — Claude Code agents are **synchronous
   call-return**. A sub-agent cannot stream a "STOP now" signal to the main agent *while* it watches;
   it only returns one final message. So "watch in real time and interrupt the apply on
   `FailedDrain`" is structurally impossible in the sub-agent model. `kubectl --watch` (infinite
   blocking) makes it worse: the main agent blocks, or the sub-agent returns immediately.

Both kinds of monitoring are fundamentally **periodic snapshot polling**, not streams. Polling fits
the main agent's `run_in_background` model exactly, reuses the main session's tool permissions, and
costs no extra agent context.

Service-aware monitoring in particular was **never exercised** in those 4 upgrades, because no
recipe defined a `services` field. Dry-run it before relying on it for a real-traffic upgrade.

---

## `scripts/drain_watch.py`

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

It writes `DRAIN-{PHASE}` entries to audit.log via the shared `lib.audit_append()` (fcntl-locked —
safe to write concurrently with the gate scripts).

### What it detects each cycle

| Source | Signal | Severity |
|--------|--------|----------|
| Warning events | `FailedDrain`, `NodeClaimTerminationFailed` | FAIL |
| Warning events | `DisruptionBlocked`, `ExceededGracePeriod`, `FailedKillPod`, `NodeNotReady`, `NodeNotSchedulable`, `OOMKilling`, `FailedMount`, `NodeClaimNotFound`, `Evicted` | WARN |
| PDB status | `disruptionsAllowed == 0` (expectedPods > 0) — drain blocked | WARN |
| NodeClaim status (Phase 5) | `Ready != True` with a reason | WARN |

**Intentionally excluded**: `BackOff` — it fires constantly from CrashLoop/ImagePull unrelated to
draining and would flood audit.log. drain_watch focuses on genuine drain-risk signals.

De-duplication: events are keyed by `uid:count` (a higher count = a genuine recurrence, re-emitted).
PDB/NodeClaim are state-based — recorded once while active, dropped from the seen-set when resolved
so a recurrence is recorded again.

---

## `scripts/service_watch.py`

Active **only when the recipe contains a `services` field.** The main agent extracts that field,
serializes it to JSON, and launches:

```bash
python3 scripts/service_watch.py --phase P4 --audit-log audit.log \
  --services-json '[{"name":"my-api","namespace":"prod","min_endpoints":2,"health_check_url":"https://api/health"}]'
```

- Launch with **`run_in_background: true`** at the start of Phase 4 / 5, alongside the drain monitor.
- Poll interval 30s; `--max-duration` (default 3600s) is a safety stop.
- Terminate after the phase gate passes: KillShell, or `--stop-file`.

Each cycle, per service:

| Check | Condition | Record |
|-------|-----------|--------|
| EndpointSlice ready count | `ready < min_endpoints` | `SVC-{PHASE}` WARN |
| HTTP health (`health_check_url` set) | non-2xx or timeout | `SVC-{PHASE}` WARN |

A service **without** `health_check_url` is monitored EndpointSlice-only and logged once as a
**BestEffort** INFO at startup (true zero-downtime cannot be guaranteed without an HTTP probe).

On startup each service's existence is verified with `kubectl get svc`; a service that is not found
is logged WARN and excluded from monitoring — so populate `services` from live
`kubectl get svc -n <ns>`, not from helm values alone.

De-duplication is state-based: a degradation is recorded once while it persists, and dropped from the
seen-set on recovery so a relapse is recorded again. Writes go through `lib.audit_append()`
(fcntl-locked).

---

## Hard constraints (enforced by the scripts, not the LLM)

1. **Read-only** — `drain_watch.py` only runs `kubectl get`; `service_watch.py` only runs
   `kubectl get endpointslices` and `curl` health probes. Neither drains, cordons, deletes, or
   mutates anything.
2. **No interpretation** — they record raw signals. The decision to STOP or proceed stays with the
   main agent reading the audit log and background output.
3. **Audit via shared helper** — they never hand-write audit lines; they call `lib.audit_append()`.
