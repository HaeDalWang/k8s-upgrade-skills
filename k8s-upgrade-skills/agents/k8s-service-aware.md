---
name: k8s-service-aware
description: >
  DEPRECATED — do NOT launch this as a sub-agent. Service availability monitoring for
  EKS upgrades is now done inline: the MAIN agent runs `scripts/service_watch.py` with
  run_in_background during Phase 4 / 5 when the recipe defines a `services` field. This
  file documents the rationale and the service_watch.py usage. Reference only, not invocation.
---

# k8s Service-Aware Monitor — Inline Polling (sub-agent retired)

> ⚠️ **This is no longer a sub-agent.** Do not launch it via the Agent tool.
> The main agent runs `scripts/service_watch.py` directly with `run_in_background: true`.

---

## Why the sub-agent approach was retired

Same root causes as the drain monitor (see `k8s-drain-monitor.md`):

1. **Permission boundary** — a sub-agent's Bash (`python3 audit_event.py`) runs under a separate permission scope and gets prompted/denied per call.
2. **Execution-model mismatch** — Claude Code agents are synchronous call-return. A sub-agent cannot stream a "service is degraded NOW" signal mid-poll to the main agent driving the rolling update. Service monitoring is inherently periodic polling, which fits the main agent's `run_in_background` model.

Service-aware monitoring was **never exercised in the 4 production-grade upgrades (2026-06-19)** because no recipe defined `services`. It is unvalidated and must be dry-run before the first real-traffic upgrade.

---

## Replacement: `scripts/service_watch.py`

Active **only when the recipe contains a `services` field.** The main agent extracts that field, serializes it to JSON, and launches:

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

A service **without** `health_check_url` is monitored EndpointSlice-only and logged once as a **BestEffort** INFO at startup (true zero-downtime cannot be guaranteed without an HTTP probe).

De-duplication is state-based: a degradation is recorded once while it persists, and dropped from the seen-set on recovery so a relapse is recorded again. Writes go through `lib.audit_append()` (fcntl-locked).

---

## Hard constraints (enforced by the script)

1. **Read-only** — only `kubectl get endpointslices` and `curl` health probes; never mutates.
2. **No interpretation** — records raw signals; the STOP/proceed decision stays with the main agent.
3. **Audit via shared helper** — never hand-writes audit lines; calls `lib.audit_append()`.
</content>
