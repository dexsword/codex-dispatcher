# codex-dispatcher

Generic **Codex Dispatcher**: dry-run ticket extract + assess, dependency-firewalled from CopyMoney measurement/trading/runtime.

## Purpose

Port/refactor reusable dry-run orchestration seams out of [`dexsword/copymoney`](https://github.com/dexsword/copymoney) into a product-agnostic package. **Extract means port/refactor into generic equivalents** — not wholesale copy of CopyMoney-coupled modules.

## Posture (hard)

- **Dry-run only** via `CODEX_DISPATCHER_DRY_RUN` (default `true`). Non-dry-run is refused.
- **Fail closed:** missing ticket validator, safety policy, ticket safety surface, repository allowlist, or duplicate-check → `blocked` (never `eligible`). `None` safety is never substituted with DenyAll or empty rules.
- **Opaque tickets:** after unambiguous JSON-object extraction, eligibility comes only from injected validators/policies.
- **GitHub GET-only** issue retrieval. No mutation methods. No generic request-method escape hatch.
- **Ledger seam:** read-only duplicate-check interface only (no append / filesystem mutation).
- **Lock paths are injectable** (Task D) with **no defaults** into `/run/lock/copymoney-paired-capture/`. This package does **not** implement CopyMoney `ProcessLock` semantics (Task F is Will-gated).
- **No PR #20 / paired-shadow work.** Do not edit `dexsword/copymoney` from this repo’s tasks.
- **No deploy, secrets, wallets, adapter enablement, or live trading hooks.**

## Extractability map

[`dexsword/copymoney` `docs/CODEX_DISPATCHER_EXTRACTABILITY_MAP.md`](https://github.com/dexsword/copymoney/blob/main/docs/CODEX_DISPATCHER_EXTRACTABILITY_MAP.md)

## Offline dry-run (explicit allowlist + policies)

Repository network calls are optional. Offline examples under `examples/` require:

- a **nonempty** `--allowlist`
- a named `--repository` that appears in that allowlist
- **real injected policies**, or the unmistakable `--demo-pass-policies` flag for offline demos

`--allowlist` alone never synthesizes pass-through validator/safety/duplicate-check policies.

```bash
python -m pip install -e .
export CODEX_DISPATCHER_DRY_RUN=true

# Missing allowlist → blocked
codex-dispatcher --ticket-file examples/ticket.valid.json

# Allowlist + repository without policies → blocked (fail closed)
codex-dispatcher \
  --ticket-file examples/ticket.valid.json \
  --allowlist acme/demo \
  --repository acme/demo

# Offline demo eligible path (explicit demo flag; output marks policy_mode)
codex-dispatcher \
  --ticket-file examples/ticket.valid.json \
  --allowlist acme/demo \
  --repository acme/demo \
  --demo-pass-policies

# Demo base + injected safety deny-key → blocked
codex-dispatcher \
  --ticket-file examples/ticket.denied.json \
  --allowlist acme/demo \
  --repository acme/demo \
  --demo-pass-policies \
  --deny-key live_trading
```

Do not rely on hardcoded product allowlists. Supply allowlists explicitly. Prefer real policy injection over `--demo-pass-policies` outside demos.

## Allowlist + lock paths (Task D)

- **Allowlist:** injectable and **nonempty**. Missing/empty allowlist fails closed in `GitHubIssueSource`, `AdapterConfig`, and `assess()`.
- **No hardcoded** `dexsword/copymoney` inside the generic package — product facades inject their allowlist.
- **Lock paths:** inject `LockPathConfig(global_agent_lock=..., implementation_lock=...)`. There are **no** built-in defaults. Paths under `/run/lock/copymoney-paired-capture/` are rejected.
- **Scotty / ops invariant:** a later CopyMoney facade that wires lock paths must **not** loosen fail-closed lock-path equality (product defaults stay exact; dispatcher must not silently accept alternate paths). Keep dispatcher locks path-disjoint from PR #20 paired-capture locks.

Example (library injection — not activation):

```python
from pathlib import Path
from codex_dispatcher.adapter import AdapterConfig
from codex_dispatcher.lock import LockPathConfig

cfg = AdapterConfig(
    allowed_repositories=frozenset({"dexsword/copymoney"}),
    lock_paths=LockPathConfig(
        global_agent_lock=Path("/run/lock/copymoney-agent.lock"),
        implementation_lock=Path("/run/lock/copymoney-agent-implementation.lock"),
    ),
)
```


## SafetyPolicy engine (Task E)

Generic, fail-closed safety seam with **immutable injected** `SafetyRuleConfig` only.

**Acceptance posture (locked phrases):**

1. Injected synthetic policy produces exact expected decisions and stable violation codes.
2. The generic engine propagates every injected prohibited-action rule without bypass.
3. CopyMoney/live-trading parity is explicitly deferred to the CopyMoney facade integration.

**Package layout:**

```
codex_dispatcher/safety/
  __init__.py   # exports
  codes.py      # POLICY_DENY_ALL, PATH_*, ACTION_PROHIBITED, CONFIG_INVALID
  config.py     # PathRule, ActionRule, SafetyRuleConfig (no bypass fields)
  deny_all.py   # DenyAllSafetyPolicy (explicit inject only)
  engine.py     # RuleBasedSafetyPolicy + SafetyViolation + protocols
  normalize.py  # relative-path normalize; absolute / `..` → PATH_ESCAPE
```

**Behaviors:**

- `assess(..., safety_policy=None)` → blocked *"safety policy is not configured"* (Task C preserved; no auto-DenyAll).
- Missing `ticket_safety_surface` when a policy is present → blocked.
- `DenyAllSafetyPolicy` always raises `POLICY_DENY_ALL` on ticket and diff checks.
- `RuleBasedSafetyPolicy` collects **all** matching violations before raise; empty config = structural checks only (escape + unexpected), **not** a production-safe product default.
- Empty regex `pattern` → `CONFIG_INVALID` at construction.
- Public `CallableSafetyPolicy` removed (F11 — no silent-allow adapter).
- Diff validation (`validate_candidate_diff`) is exported for future candidate pipelines; dry-run `assess` does **not** call it.

**Worf F1–F13 (summary):** no bypass/skip/unsafe/permissive/allow_all; no None→allow; no auto-DenyAll on omit; no skipped ActionRules; no ticket-prose-as-diff; no CopyMoney/trading patterns in-tree; no adapter/mutation; no mutable registries; no soft-fail; no empty-config-as-safe production docs; no public silent-allow CallableSafetyPolicy; normalize-before-unexpected; empty pattern → CONFIG_INVALID.

Synthetic matrix tests live under `tests/safety/` (neutral names only).

## Package layout

```
codex_dispatcher/
  github/   # extract_ticket + GET-only GitHubIssueSource
  worker/   # dry-run assess + CLI
  safety/   # SafetyPolicy engine (codes, config, DenyAll, RuleBased, normalize)
  ledger/   # DuplicateChecker only
  schema/   # opaque ticket object helper
  lock/     # LockPathConfig injection (no ProcessLock semantics)
  adapter/  # AdapterConfig + disabled CodingAgentAdapter
  allowlist.py  # nonempty allowlist helpers
```

## Dependency firewall

AST scan over every `.py` under `codex_dispatcher/` fails closed on import roots:

`copymoney`, `measurement`, `agents`, `execution`, `trading`

## Develop / CI

### Public input and collaborator contracts

- Ticket extraction accepts one JSON object. Duplicate object keys (including
  nested and escaped-equivalent keys), `NaN`, `Infinity`, and `-Infinity` are
  rejected in both raw and fenced tickets before policy evaluation. Other
  object contents remain opaque; this is not a product schema.
- Supplied `paths` / `texts` must be non-scalar sequences of strings (for
  example, lists or tuples). Strings, bytes, mappings, nulls, nested collections,
  and non-string elements are rejected, never coerced. Omitted keys still mean
  empty sequences. Explicit empty sequences remain valid structural inputs.
  The same checks apply to custom safety-surface results and the public
  rule-policy ticket/diff methods. `patch_text` must be a string even with no
  action rules configured.
- Paths cannot contain NUL characters. Remaining normalization is **POSIX
  lexical**: absolute paths and parent segments are rejected by the rule engine;
  repeated separators and dot segments normalize before path matching. No
  backslash reinterpretation, Windows-drive interpretation, percent decoding,
  Unicode normalization, or filesystem symlink resolution occurs. Empty/dot
  paths, non-NUL control characters, and trailing separators retain their
  existing lexical behavior; A–E does not define a filesystem file-only schema.
- Repository allowlists must be nonempty sets/frozensets of nonempty strings,
  without whitespace or control characters. Membership is exact, with no case
  folding or substring matching. `normalize_allowlist` is an explicit helper
  that trims string entries and removes blanks; it never coerces non-strings.
  The CLI does not silently normalize allowlist spellings. GitHub issue sources
  additionally reject URL delimiters/escapes and dot components in `owner/name`
  identifiers so they cannot change the constructed API route.
- Duplicate-check methods must return an actual `bool`: `False` permits further
  assessment; `True` blocks. Other results block, including through the callable
  adapter. Validators and safety ticket checks must return `None` on success or
  raise on rejection; non-None returns are contract errors, not an alternate
  boolean/dictionary decision API.
- Rule configuration must contain tuples of the declared rule types, string
  patterns, nonblank rule IDs unique within each family, and integer regex flags.
  Invalid configuration raises `SafetyViolation` with `CONFIG_INVALID` when
  constructing `RuleBasedSafetyPolicy`. Empty tuples still provide structural
  checks only, not a production-safe default.

Malformed public input raises `codex_dispatcher.validation.ValidationError`
(a `ValueError`) from the shared structural helpers/policy methods; rule matches
continue to raise `SafetyViolation` with the existing stable codes. `assess`
blocks input/contract errors and expected collaborator failures
(`TicketValidationError`, `SafetyViolation`, `ValueError`, `TypeError`, `KeyError`,
`AttributeError`, `RuntimeError`, `OSError`). Other unexpected exceptions propagate
without producing eligibility; process-control exceptions are not swallowed.
Injected components remain trusted code. They still choose product policy;
A–E is not an arbitrary-plugin sandbox or an execution pipeline.

Both `assess` and the CLI enforce `CODEX_DISPATCHER_DRY_RUN` before calling
collaborators. Disabled dry-run raises `RuntimeError` from `assess`; the CLI
prints a structured `refused` result with exit code 2. CLI file/decode failures
also produce structured refusal with exit 2; extraction failures are `blocked`
with exit 2. Successful demo eligibility exits 0 and performs no mutation.

Protected-path checks remain diff-only, and assessment still does not invoke
diff validation. Requiring nonempty candidates, rejecting additional POSIX
filenames, resolving filesystem containment, and defining actual locking or
execution behavior require separate contracts beyond these A–E corrections.

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Runtime dependencies: **none** (`dependencies = []`).
