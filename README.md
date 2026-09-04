# codex-dispatcher

Generic **Codex Dispatcher**: dry-run ticket extract + assess, dependency-firewalled from CopyMoney measurement/trading/runtime.

## Purpose

Port/refactor reusable dry-run orchestration seams out of [`dexsword/copymoney`](https://github.com/dexsword/copymoney) into a product-agnostic package. **Extract means port/refactor into generic equivalents** — not wholesale copy of CopyMoney-coupled modules.

## Posture (hard)

- **Dry-run only** via `CODEX_DISPATCHER_DRY_RUN` (default `true`). Non-dry-run is refused.
- **Fail closed:** missing ticket validator, safety policy, repository allowlist, or duplicate-check → `blocked` (never `eligible`).
- **Opaque tickets:** after unambiguous JSON-object extraction, eligibility comes only from injected validators/policies.
- **GitHub GET-only** issue retrieval. No mutation methods. No generic request-method escape hatch.
- **Ledger seam:** read-only duplicate-check interface only (no append / filesystem mutation).
- **No ProcessLock** in this package yet (Task D / F). Lock stub is intentionally empty of ProcessLock.
- **No PR #20 / paired-shadow work.** Do not edit `dexsword/copymoney` from this repo’s tasks.
- **No deploy, secrets, wallets, adapter enablement, or live trading hooks.**

## Extractability map

[`dexsword/copymoney` `docs/CODEX_DISPATCHER_EXTRACTABILITY_MAP.md`](https://github.com/dexsword/copymoney/blob/main/docs/CODEX_DISPATCHER_EXTRACTABILITY_MAP.md)

## Offline dry-run (explicit allowlist only)

Repository network calls are optional. Offline examples under `examples/` require an **explicit** `--allowlist` (fail closed if omitted):

```bash
python -m pip install -e .
export CODEX_DISPATCHER_DRY_RUN=true

# Missing allowlist → blocked
codex-dispatcher --ticket-file examples/ticket.valid.json

# Explicit allowlist + repository → eligible (pass-through policies)
codex-dispatcher \
  --ticket-file examples/ticket.valid.json \
  --allowlist acme/demo \
  --repository acme/demo

# Injected safety deny-key → blocked
codex-dispatcher \
  --ticket-file examples/ticket.denied.json \
  --allowlist acme/demo \
  --repository acme/demo \
  --deny-key live_trading
```

Do not rely on hardcoded product allowlists. Supply allowlists explicitly for demos and tests.

## Package layout

```
codex_dispatcher/
  github/   # extract_ticket + GET-only GitHubIssueSource
  worker/   # dry-run assess + CLI
  safety/   # SafetyPolicy protocol
  ledger/   # DuplicateChecker only
  schema/   # opaque ticket object helper
  lock/     # reserved (no ProcessLock here)
  adapter/  # reserved (disabled / future)
```

## Dependency firewall

AST scan over every `.py` under `codex_dispatcher/` fails closed on import roots:

`copymoney`, `measurement`, `agents`, `execution`, `trading`

## Develop / CI

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Runtime dependencies: **none** (`dependencies = []`).
