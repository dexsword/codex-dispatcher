# codex-dispatcher

Generic **Codex Dispatcher** package skeleton extracted from reusable orchestration seams in [`dexsword/copymoney`](https://github.com/dexsword/copymoney).

## Purpose

Provide an inert, dependency-firewalled package that later tasks can fill with ported/refactored dispatcher mechanisms (ticket extract, dry-run assess, ledger, safety scanners, coding-agent adapter) **without** importing CopyMoney measurement, trading, or agent runtime.

## Posture (hard)

- **Dry-run only.** No activation, no mutation phase, no claim/PR automation in this repo yet.
- **No adapter enablement** (`verified_noninteractive` stays product-side / future work).
- **No ProcessLock semantic changes** in CopyMoney (Task F is William-gated and separate).
- **No PR #20 work.** Paired-shadow / capture paths stay frozen in `dexsword/copymoney`.
- **No deploy, secrets, wallets, or live trading hooks.**

## Extractability map

Source of truth for extract / stay / wrap (including William’s port/refactor semantics):

[`dexsword/copymoney` `docs/CODEX_DISPATCHER_EXTRACTABILITY_MAP.md`](https://github.com/dexsword/copymoney/blob/main/docs/CODEX_DISPATCHER_EXTRACTABILITY_MAP.md)

## Package layout (stubs only)

```
codex_dispatcher/
  github/    # Issue → ticket extract / GET-only source (future)
  lock/      # Process exclusion API (future; secure lock is separate/gated)
  ledger/    # Append-only hash-chained JSONL (future)
  safety/    # Policy protocol + scanners (future; deny-all defaults)
  adapter/   # CodingAgentAdapter (future; disabled by default)
  worker/    # Dry-run assess loop (future)
  schema/    # Generic JSON-schema helpers (future)
```

All modules are inert stubs in Task B.

## Dependency firewall

CI runs an AST scan over every `.py` file under `codex_dispatcher/` and **fails closed** if any import root is one of:

`copymoney`, `measurement`, `agents`, `execution`, `trading`

## Develop / CI locally

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Runtime dependencies: **none** (`pyproject.toml` `dependencies = []`).
