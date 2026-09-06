# DESIGN: Task F SecureProcessLock + first DexTech website canary

**Stage:** DESIGN ONLY — rev 3
**Issue:** https://github.com/dexsword/codex-dispatcher/issues/14
**Owner:** Geordi (Architecture and Design)
**Coordinator:** Picard
**Authorized by:** Will (2026-09-05 PT) — design only
**Will decisions:** 2026-09-05 PT incorporated (W1–W11 DECIDED)
**Astra:** final review CHANGES REQUIRED addressed in this rev 3 pack
**Implementation:** F1+ NOT authorized until Picard publishes immutable commit and Astra re-reviews + Will authorizes
**Prior published rev2:** commit `89cbbc35825cf8cde4283c742c6d26c9d7cd3486`

**Prerequisite (accepted):** A–E CLOSED — PR #13; origin/main `7358bc4292bad1a21d3c74a9083dcedd8e6d0c94`; verified tree `54f61c4af20bec3e4f76be6587265b08f41a23cb`; DexServe PASS; CopyMoney + ProcessLock + PR #20 frozen / completely untouched.

**Destination packages/repos:**
- Lock + dispatcher mutation-stage seams: `dexsword/codex-dispatcher`
- First canary target website: `dexsword/dextech` (exact allowlist singleton — W6 DECIDED)
- Canary tickets: `dexsword/dextech` with label `dispatcher-canary` (W1 DECIDED)
- Task F engineering: `dexsword/codex-dispatcher` (W1 DECIDED)

**Artifact path:** `/workspace/codex-dispatcher-design/TASK-F-AND-DEXTECH-CANARY.md`

**Adjacent blocker:** W9 — cloudflare.key / cloudflare.pem potentially exposed in dextech; tracked at https://github.com/dexsword/dextech/issues/3. Blocks OPS1 and CANARY1.

**Live GitHub fact (Astra A1):** As of Astra final review, DexTech `main` is unprotected; no rulesets configured. Branch protection / rulesets are an unmet prerequisite before write deploy key install or OPS1.

---

## 0. Governing constraints

1. Fail-closed everywhere: missing config, busy lock, allowlist miss, path miss, failed checks, incorrect lock ownership/permissions/symlinks → block; never soft-allow.
2. Do not change CopyMoney `orchestration.lock.ProcessLock` semantics.
3. Do not touch `dexsword/copymoney`, PR #20, measurement/capture locks, wallets, trading, or live activation. **CopyMoney, ProcessLock, and PR #20 are completely untouched.**
4. Do not auto-merge or production-deploy the website. Dispatcher must not merge or deploy.
5. **Branch-only stop (W2/W10 DECIDED):** First canary changes exactly one dedicated harmless status file, pushes a review branch, writes evidence, then STOPS. Dispatcher does **not** open a draft PR. Picard routes an independently authorized Grok GitHub bot or human to open the draft PR after branch push + evidence.
6. Execution remains default-disabled; explicit multi-gate activation required (Will-approved). First enablement is supervised and one-shot (W8) — no persistent daemon or unattended polling.
7. Usage policy: correctness/safety/evidence over savings (`/workspace/policies/USAGE_EFFICIENCY.md`).
8. **W9 blocks OPS1 and CANARY1:** Potential exposure of cloudflare.key/cloudflare.pem must be validated (without displaying contents), rotated/revoked, removed safely, ignored + secret-scanning enabled, with history rewrite proposed separately. F1–F5 may proceed after design + Picard immutable publish + Astra re-review + Will authorize F1+; **no provisioning or canary execution until W9 is resolved.**
9. **Sequence gate (mandatory — rev 3):**
   1. Design rev3 approval (this pack)
   2. Picard publishes immutable commit of this design
   3. Astra re-reviews the published immutable commit
   4. Will authorizes F1+
   5. F1–F5 (engineering in codex-dispatcher)
   6. W9 resolution (dextech#3)
   7. Main-protection configured + independently verified (A1) **before** write deploy key install or OPS1
   8. OPS1 (Scotty provisioning) — only after W9 + main-protection verified
   9. Supervised CANARY1 (one-shot)
10. **Deploy-trigger non-fire gate:** Before any live canary push is authorized, verify that pushing a canary branch cannot trigger GitHub Actions, external webhooks, Cloudflare deployment, DexServe hooks, or any other deploy mechanism. Absence of `.github/workflows` alone is **not** proof (A8).
11. No fallback lock root to `/tmp` or the repository (W3).
12. No automatic worktree/branch deletion in v1 (W4). Process locks must still release normally.
13. **Main protection = unmet prerequisite (Astra A1):** Branch protection/rulesets MUST be configured and independently verified BEFORE installing a write deploy key or beginning OPS1. Protection must deny dispatcher/deploy-key identity from: direct pushes to `main`; force pushes; branch deletion; bypassing required review. Record GitHub configuration evidence in OPS1 pack. Do **NOT** attempt a potentially mutating test push to prove protection. Evidence = settings/API **read** of rulesets/protection, not a push probe.
14. **Isolate untrusted Codex from publication credentials (Astra A2):** Codex must never read deploy-key private file; inherit SSH-agent socket; access authenticated Git config; or invoke publisher credential. Workspace-write alone is insufficient. Prefer separate OS identities (`codex-runner` vs `codex-publisher`) or equivalent isolation. Network disabled for Codex during canary. Trusted publisher receives validated output only AFTER Codex exits. Tests must prove child cannot read/inherit publication credentials.
15. **Protect trusted Git state from Codex (Astra A3):** Codex must not modify `.git`, worktree admin metadata, mirror, Git config, hooks, audit evidence, or publisher checkout. Preferred pattern: credential-free staging dir → Codex edits staging copy → validate → trusted supervisor copies into fresh trusted worktree → diff/commit/push ONLY from trusted worktree.
16. **SecureProcessLock creation semantics (Astra A4):** OPS1—not runtime—pre-creates `/run/lock/codex-dispatcher/`. Runtime verifies and fails closed; must NOT create/repair root with mkdir/chmod/fallback. Use dirfd `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`; open lock files relative to that dirfd with `O_NOFOLLOW|O_CLOEXEC`; exact 0700 dir and 0600 files; no silent fchmod of incorrectly configured existing lock file; release first lock if second fails; neither lock FD inherited by Codex/children.
17. **Ticket validation (Astra A5):** Verify real `dispatcher-canary` label from GitHub issue metadata — do not trust JSON label field. Sample JSON acceptance phrases must be byte-identical to locked phrases (including backticks and punctuation). Prefer byte-identical samples in fixtures; no silent normalization unless formally defined+tested (rev3 prefers byte-identical).
18. **Constrain status-file contents (Astra A6):** 8 KiB + credential substring scan insufficient. Exact permitted schema only; reject arbitrary additional content.
19. **Timeout handling (Astra A7):** Launch Codex in dedicated process group/session. On timeout/cancel: terminate entire process tree, wait/reap, verify no child remains, only then release locks. Descendant-process regression test required.
20. **Editorial rename (rev3):** Implementation packets remain **F1–F5** (and OPS1, WEB0, CANARY1, ASTRA). SecureProcessLock acceptance tests renamed **SPL-T1…** (was F1–F7 style). Canary tests stay **C1…** / **CAN-T***. This rename is explicit to prevent confusing task IDs with test IDs.

### 0.1 Astra design constraints index (A1–A8)

| ID | Constraint | Section(s) |
|---|---|---|
| A1 | Main protection unmet prerequisite; evidence via settings/API read only | §0 #13, §9, §13, §16 |
| A2 | Isolate untrusted Codex from publication credentials | §1, §2 T6/T16, §5, §16 |
| A3 | Protect trusted Git state; staging → validate → trusted publish | §1, §2 T17, §5, §15 |
| A4 | SecureProcessLock dirfd semantics; OPS1 pre-create; no runtime mkdir | §3, SPL-T* |
| A5 | Real label metadata; byte-identical phrases | §4, C*/CAN-T* |
| A6 | Exact status-file schema | §4.10, §6, C*/CAN-T* |
| A7 | Process group/session; tree kill before lock release | §5, §8, C*/CAN-T* |
| A8 | Deploy non-fire evidence checklist beyond missing workflows | §6.2, OPS1 |

---
## 1. Architecture and data flow

### 1.1 Logical flow (rev3 — staging + trusted publisher split)

Grok/crew submits structured GitHub ticket (dextech + label `dispatcher-canary`) → Dispatcher supervisor on DexServe (canary profile, supervised one-shot) reads issue → verifies **real** issue label metadata (not JSON field) → acquires SecureProcessLock pair → assess + SafetyPolicy → prepares **credential-free staging directory** containing ONLY the permitted file copy → launches Codex CLI as `codex-runner` (no deploy key, no `SSH_AUTH_SOCK`, no GitHub tokens, network disabled, no access to `.git`/mirror/publisher checkout) → Codex edits staging copy only → Codex exits → supervisor validates schema/diff → **trusted publisher** (`codex-publisher`) receives validated bytes only after Codex exit → copies into **fresh trusted worktree** → diff/commit/push `agent/canary/...` ONLY from trusted worktree with sanitized Git env → write evidence → STOP. Picard independently routes Grok GitHub bot or human to open draft PR. No merge/deploy by automation. Dispatcher has **no** GitHub API credential.

**Critical (A2/A3):** Codex never runs inside the publisher worktree that has credentials. Staging is not a Git worktree with remotes/keys. Publication credentials exist only in the trusted publisher boundary after Codex has fully exited and descendants are reaped.

### 1.2 Phases (updated for staging / publisher)

| Phase | Actor | Lock held? | Mutates |
|---|---|---|---|
| P0 Submit | Grok/crew | n/a | GitHub issue body only (dextech + `dispatcher-canary`) |
| P1 Claim/assess | Dispatcher supervisor | global + implementation | optional ledger append; verify real label metadata; no website files yet |
| P2 Staging prepare | Dispatcher supervisor | yes | credential-free staging dir with ONLY permitted file copy; **not** a credentialed Git worktree |
| P3 Agent edit | Codex CLI as `codex-runner` | yes | only staging copy of permitted canary path; no network; no publication creds; no `.git` |
| P4 Validate | Dispatcher supervisor | yes | none on repo; read staging output + schema + SafetyPolicy + one-file checks; Codex must already be exited/reaped |
| P4b Trusted copy | Trusted supervisor / `codex-publisher` prep | yes | copy validated bytes into fresh trusted worktree (new checkout; Codex never present) |
| **P5 Publish review** | **`codex-publisher` / trusted git** | yes | **diff/commit/push review branch + evidence only — NO PR open by dispatcher**; sanitized Git env; hooks disabled; non-force push to validated `refs/heads/agent/canary/*` |
| **P6 Draft PR (external)** | **Picard routes Grok GitHub bot or human** | locks already released | **open draft PR using independently authorized PR-write identity — not the deploy key; not the dispatcher** |
| P7 Stop | Human | n/a | merge/deploy forbidden for automation |

### 1.3 Separation from CopyMoney

| Concern | Canary / Task F | CopyMoney |
|---|---|---|
| Repo | codex-dispatcher + dextech | copymoney frozen |
| Lock type | New SecureProcessLock in dispatcher | ProcessLock unchanged; PR #20 SecureCaptureLock untouched |
| Lock namespace | `/run/lock/codex-dispatcher/` (W3 DECIDED; OPS1 pre-creates) | copymoney agent locks + paired-capture dir |
| Safety tables | Website canary SafetyRuleConfig | Product tables deferred to facade |
| Trading/live | Out of scope | Frozen |
| Credentials | Dedicated repo deploy key (branch push only) held only by `codex-publisher`; no GitHub API; Codex/`codex-runner` never sees them | Untouched |
| OS identities | Prefer `codex-runner` (untrusted) vs `codex-publisher` (trusted) | Untouched |

### 1.4 P5 / P6 boundary (critical)

- **P5 (trusted publisher only):** `git push` of `agent/canary/*` via SSH deploy key from trusted worktree; write audit evidence; mark ledger `awaiting_human_review` (branch pushed, PR not opened by dispatcher); release locks only after Codex tree reaped.
- **P6 (outside dispatcher):** Picard confirms evidence, then routes separately authorized Grok GitHub bot **or** human to open draft PR. Deploy key cannot open PRs. Dispatcher must not call GitHub API, must not embed `gh`, must not hold App private key / `GITHUB_TOKEN`.

### 1.5 Preferred one-file canary pattern (A3)

1. Human-seeded `canary/DISPATCHER_STATUS.md` exists on main as regular file (W5).
2. Supervisor creates staging directory owned for `codex-runner`, mode 0700, containing **only** a copy of that file (no `.git`, no keys, no other repo files).
3. Codex (`codex-runner`) edits the staging copy under workspace-write limited to staging; network disabled.
4. On Codex exit: reap process group; verify no descendants; validate exact schema (A6); SafetyPolicy; size; no unexpected lines.
5. Trusted path: copy validated content into fresh trusted worktree checked out by `codex-publisher` from mirror; stage exactly that one path; commit with trailers; push non-force to `refs/heads/agent/canary/<name>` against canonical remote validated by config hash/fingerprint.
6. Alternate mechanisms (namespaces, containers, Landlock, etc.) must provide **equivalent** isolation and acceptance tests proving Codex cannot touch `.git`/keys/audit/publisher checkout.

### 1.6 Data-flow diagram (textual)

```
[GitHub issue + real label dispatcher-canary]
        |
        v
[Supervisor: assess + SecureProcessLock pair]
        |
        v
[Staging dir: ONLY canary/DISPATCHER_STATUS.md copy]
        |
        v
[codex-runner / Codex CLI] --no network-- no SSH_AUTH_SOCK -- no deploy key
        |  (exits; process group reaped)
        v
[Validate: schema + SafetyPolicy + one-file + realpath]
        |
        v
[codex-publisher: fresh trusted worktree + sanitized git]
        |
        v
[Non-force push refs/heads/agent/canary/*] --> evidence --> STOP
        |
        v
[P6 external: draft PR by bot/human] --> human merge only
```

---
## 2. Threat model

### 2.1 Assets

DexServe integrity; git/SSH deploy key material; website content and booking/payment code; TLS material; dispatcher audit trail; CopyMoney isolation; GitHub Actions / webhook / Cloudflare deploy surfaces; trusted Git state (`.git`, hooks, config, mirror); lock file descriptors; process-group integrity.

### 2.2 Threats and mitigations

| ID | Threat | Mitigation |
|---|---|---|
| T1 | Symlink/lock swap on ProcessLock-style open | New SecureProcessLock: dirfd `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`; open locks relative to dirfd with `O_NOFOLLOW\|O_CLOEXEC`; private 0700 dir; fstat regular/euid/nlink==1/0600; flock before truncate; do not modify CopyMoney ProcessLock; no silent fchmod of wrong-mode existing file (A4) |
| T2 | Namespace collision with paired-capture | Reject paths under `/run/lock/copymoney-paired-capture/`; use `/run/lock/codex-dispatcher/` |
| T3 | Concurrent jobs | Dual locks; fail-closed busy; one job; if second lock fails, immediately release/close first |
| T4 | Codex edits beyond canary file | Staging contains only permitted file; Task E SafetyPolicy; post-diff unexpected/denied/protected; abort before publish; exact staged diff = one file (W7) |
| T5 | Ticket social engineering | Schema + byte-identical phrases; path authority from structured fields not prose; **real** GitHub label `dispatcher-canary` from issue metadata (A5) — do not trust JSON `label` field |
| T6 | Credential exfiltration (**updated A2**) | No secrets in ticket/prompt; deny key/pem/env paths; dedicated canary git identity held only by `codex-publisher`; Codex/`codex-runner` cannot read deploy-key private file, inherit `SSH_AUTH_SOCK`, access authenticated Git config, or invoke publisher credential; network disabled for Codex; backups exclude private keys/tokens (W11); tests prove non-inheritance |
| T7 | Auto-merge/deploy | Branch-only stop; no PR open by dispatcher; no merge/deploy automation |
| T8 | Crash mid-job | flock drops on death; ledger failed; no main touch; locks release even if worktree/staging retained (W4); process group reaped |
| T9 | Trading bleed | Firewall; no copymoney imports in canary profile |
| T10 | Secrets already in dextech tree (W9) | cloudflare.key/cloudflare.pem potentially exposed — dextech#3. Canary denies those paths. Validity check without displaying contents; rotate/revoke; remove safely; ignore + secret-scanning; history rewrite proposed separately. **Blocks OPS1/CANARY1.** |
| T11 | Over-broad GitHub credential / unprotected main (**updated A1**) | Dedicated repo deploy key for **branch push ONLY**; **main branch protection/rulesets MUST exist and be independently verified before write deploy key or OPS1**; protection denies dispatcher/deploy-key from direct main push, force push, branch deletion, bypassing required review; evidence via settings/API read — **no mutating push probe**; dispatcher gets **NO GitHub API credential**; deploy key cannot open PRs (W2) |
| T12 | Canary branch triggers deploy | Explicit non-fire verification gate with full checklist (A8): GitHub Actions + repo settings; webhooks; Cloudflare Pages/Workers build + branch-deployment settings; DexServe or external deployment hooks — before CANARY1 |
| T13 | Lock root fallback abuse | Fail closed on incorrect ownership/permissions/symlinks; **no fallback to `/tmp` or the repository** (W3); runtime must not mkdir/repair root |
| T14 | Target path symlink escape | Must already exist as regular file; reject symlinks; verify real-path containment; final staged diff exactly that one file (W7) |
| T15 | Unattended enablement | Supervised one-shot only; no persistent daemon; no unattended polling (W8) |
| T16 | Codex credential exfil via inherited env/FD/agent (**new A2**) | Separate OS identities; strip env; `O_CLOEXEC` on lock FDs; no key path readable by runner; prove with tests |
| T17 | Codex tampers with `.git` / hooks / mirror / audit (**new A3**) | Staging-only access; publisher worktree created after Codex exit; deny `.git/**`; tests for tamper attempts |
| T18 | Lock FD leak to Codex/children (**new A4**) | `O_CLOEXEC`; neither lock FD inherited; acceptance tests for non-inheritance and partial pair acquire |
| T19 | Actions / deploy false-negative (**new A8**) | Non-fire checklist beyond absence of `.github/workflows`; inspect Actions settings, webhooks, Cloudflare, DexServe hooks |
| T20 | Timeout leaves orphan descendants holding resources (**new A7**) | Dedicated process group/session; kill tree; wait/reap; verify no child; only then release locks; regression test |
| T21 | Status-file payload smuggling (**new A6**) | Exact schema; reject free-form body, code fences with payloads, HTML, unexpected lines, encoded data |
| T22 | Phrase / label spoofing in ticket JSON (**new A5**) | Byte-identical locked phrases in fixtures; real label from GitHub metadata API/object |

### 2.3 Trust boundaries

GitHub issue text untrusted. Codex output untrusted until policy+path+schema matrix pass. Staging directory is untrusted workspace. Trusted publisher boundary begins only after Codex exit + reap + validation. Branch push is not a production trust upgrade. Human (or independently authorized bot under Picard routing) draft PR is review visibility only. Human merge is the only production trust upgrade. Main protection is a platform trust prerequisite, not something the dispatcher proves by pushing.

---
## 3. Task F — SecureProcessLock interfaces

### 3.1 Principles

- New type only in `codex_dispatcher.lock` (or `.lock.secure`).
- Never modify CopyMoney ProcessLock or PR #20 SecureCaptureLock.
- Reuse Task D LockPathConfig + paired-capture rejection.
- Semantics inspired by SecureCaptureLock (PR20-reaudit-9ade0d5d), **extended by Astra A4**.

### 3.2 Identity and location (W3 DECIDED + A4)

| Item | Decision |
|---|---|
| Lock root | `/run/lock/codex-dispatcher/` — **OPS1 pre-creates** at boot, owned by dedicated **non-root** dispatcher/publisher-capable account as Scotty defines |
| Runtime create/repair | **FORBIDDEN.** Runtime verifies existing root; must NOT `mkdir`/`chmod`/fallback to create or repair the root |
| Dir mode | exactly `0700` |
| Lock files | exactly `0600` |
| Global agent lock | `/run/lock/codex-dispatcher/agent.lock` |
| Implementation lock | `/run/lock/codex-dispatcher/implementation.lock` |
| Ownership fail-closed | Incorrect ownership, permissions, or symlinks → refuse acquire; **no fallback** to `/tmp` or the repository |
| File contents | pid/job_id/started_at after secure open (informational; not used for steal) |
| Busy | Non-blocking exclusive flock; AlreadyLocked / blocked disposition |
| Cross-host | Not supported (document) |
| FD inheritance | Neither lock FD inherited by Codex or children (`O_CLOEXEC`) |

### 3.3 Path defenses — dirfd semantics (A4 REQUIRED)

1. **OPS1** creates `/run/lock/codex-dispatcher/` with ownership and mode `0700` at provisioning/boot. Runtime never creates this root.
2. Runtime: `open` the lock root with **dirfd** flags `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`. Refuse if open fails or result is not a directory.
3. `fstat` that dirfd: ownership == expected euid (or dedicated lock owner as configured); mode **exactly** `0700` (no group/other bits); not a symlink (ensured by `O_NOFOLLOW` + `O_DIRECTORY`).
4. Open lock files **relative to that dirfd** (e.g. `openat`) with `O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC` (and without following links).
5. `fstat` each lock fd: must be regular file, `st_uid==euid`, `st_nlink==1`, mode **exactly** `0600`.
6. **Do not silently `fchmod`** an incorrectly configured existing lock file to "fix" it. Wrong mode/owner/nlink → fail closed.
7. `flock` (non-blocking exclusive) **before** any `ftruncate`/write.
8. Reject if path resolves outside lock root or under paired-capture.
9. Acquire order: global agent lock, then implementation lock. **If the second lock fails, immediately release and close the first** (partial pair must not leave a held orphan).
10. If any check fails → fail closed; do not fall back; do not mkdir/repair root.

### 3.4 Lifetime

Hold both locks from P1 through P5 (including staging, Codex, validate, trusted publish). Acquire global then implementation; release reverse in `finally` — **but only after** Codex process group is terminated, waited, and verified empty (A7).

### 3.5 Crash / cancellation / retained worktrees (W4 DECIDED + A7)

| Action | Behavior |
|---|---|
| Crash | flock released by kernel; next job may acquire |
| Cancel / timeout | Terminate entire Codex process group/session; wait/reap; verify no descendant remains; **only then** release locks; no push if incomplete; ledger cancelled |
| Stale PID text | Ignored; flock is source of truth |
| Orphan worktree / staging / branch | **No automatic deletion in v1.** Scotty inventories; cleanup only after Will approves |
| Lock vs retention | **Process locks must still release normally** and must **not** persist with retained worktrees/staging |

### 3.6 API sketch

```python
class AlreadyLocked(RuntimeError): ...
class LockConfigurationError(RuntimeError): ...  # wrong mode/owner/symlink/missing OPS1 root

class SecureProcessLock:
    def __init__(self, path: Path, *, job_id: str) -> None: ...
    def __enter__(self) -> SecureProcessLock: ...
    def __exit__(self, *exc: object) -> None: ...
    # Internals (design intent):
    # - open root dirfd with O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC
    # - openat lock with O_NOFOLLOW|O_CLOEXEC
    # - never mkdir root; never silent fchmod wrong file
    # - CLOEXEC so Codex cannot inherit lock FDs

@dataclass(frozen=True)
class SecureLockPair:
    global_agent: SecureProcessLock
    implementation: SecureProcessLock

    def __enter__(self) -> SecureLockPair: ...
    def __exit__(self, *exc: object) -> None: ...
    # If implementation acquire fails after global success:
    # immediately release/close global before propagating
```

### 3.7 Acceptance tests for locks

See §12 SPL-T* matrix (renamed from former F1–F7 style test IDs so they cannot be confused with implementation packets F1–F5).

---
## 4. Canary ticket schema, phrases, allow/deny, status-file schema

### 4.1 Ticket home (W1 DECIDED)

- Canary tickets live in **`dexsword/dextech`** with label **`dispatcher-canary`**.
- Task F engineering lives in **`dexsword/codex-dispatcher`**.

### 4.2 Ticket schema

```json
{
  "schema_version": 1,
  "task_id": "dextech-canary-001",
  "repository": "dexsword/dextech",
  "mode": "canary",
  "affected_paths": ["canary/DISPATCHER_STATUS.md"],
  "primary_change": {"description": "Update dispatcher canary status marker only."},
  "stop_condition": "review_branch_and_evidence_only",
  "acceptance_phrases": [
    "Change is limited to `canary/DISPATCHER_STATUS.md`.",
    "No merge and no production deploy are requested.",
    "CopyMoney and trading systems are out of scope."
  ]
}
```

**Notes (A5):**
- The JSON must **not** be the authority for the canary label. The dispatcher verifies the real GitHub issue has label `dispatcher-canary` via issue metadata (API/graphql/gh issue view JSON labels array from GitHub, not a free-form body field named `label`).
- Do **not** include a trusted `"label": "dispatcher-canary"` field as authorization. If a sample JSON shows a label-like field for documentation, it is informational only and **ignored** for authorization.
- `acceptance_phrases` in fixtures must be **byte-identical** to the locked phrases below (including backticks and trailing periods).

TicketValidator = shape/phrases/byte-identity. LabelGate = GitHub issue metadata. SafetyPolicy = paths/actions/diff (Task E). StatusFileValidator = exact schema (A6).

### 4.3 Locked acceptance phrases (byte-identical in fixtures)

These three strings are locked. Fixtures and sample tickets MUST use them **byte-identically** (prefer this approach over normalization — A5):

1. Change is limited to `canary/DISPATCHER_STATUS.md`.
2. No merge and no production deploy are requested.
3. CopyMoney and trading systems are out of scope.

| # | Exact UTF-8 phrase (byte-identical) |
|---|---|
| 1 | Change is limited to `canary/DISPATCHER_STATUS.md`. |
| 2 | No merge and no production deploy are requested. |
| 3 | CopyMoney and trading systems are out of scope. |

**Normalization:** Rev3 **prefers byte-identical samples in fixtures**. Do **not** introduce a normalization function unless a future design formally defines and tests it. Any whitespace/backtick drift → reject ticket.

### 4.4 Allowlist (W6 DECIDED)

`frozenset({"dexsword/dextech"})` only.

### 4.5 Permitted path (W7 DECIDED — with conditions)

- Only permitted path: `canary/DISPATCHER_STATUS.md`.
- Must **already exist** as a **regular file** (human-seeded on main — W5).
- **Reject symlinks.**
- Verify **real-path containment** inside the trusted worktree / repo root (and staging realpath under staging root).
- **Final staged diff must be exactly that one file.**

### 4.6 Human-seed (W5 DECIDED)

- Human-seed `canary/DISPATCHER_STATUS.md` on main in a **separate reviewed commit**.
- Confirm inert: **not rendered or deployed as website content**.
- Seed content must itself satisfy the status-file schema (§4.10) or a documented inert placeholder that WEB0 replaces with schema-valid baseline before CANARY1.

### 4.7 Denied paths (never touch)

`.env`, `.env.*`, `bookings.json`, db/sqlite, `server.js`, `gcal-auth.js`, `stripe-import.js`, `stripe-products.json`, `admin.html`, `package.json`, `package-lock.json`, `.git/**`, `.github/**`, `node_modules/**`, credential-like names.
Also deny: `cloudflare.key` and `cloudflare.pem` and patterns `*.key` / `*.pem`.
Also deny for Codex: deploy-key paths, SSH agent sockets, publisher worktree paths, mirror paths, audit dirs, lock root.

### 4.8 Protected paths (must not change in diff)

index.html, script.js, style.css, tests.js, legal/support/cancel HTML, images, AGENTS.md, README.md.

### 4.9 Prohibited actions

Dispatcher must not merge, deploy, open PRs via API, or activate CopyMoney/trading.
Also prohibited: rewriting history on remote, default-branch checkout publish, host service control, credentialed env edits, hosting publish hooks, registry publish, empty SafetyRuleConfig treated as safe, force push, mutating push probes for "proving" branch protection.

Use non-empty RuleBasedSafetyPolicy (Task E N2).

### 4.10 Exact status-file schema (Astra A6)

**File:** `canary/DISPATCHER_STATUS.md`

**Permitted structure:** Markdown document consisting of a fixed key-value section only. **No free-form body. No code fences with payloads. No HTML. No additional headings. No unexpected lines.**

Proposed tight schema (required keys only, exactly once each, in this order):

```markdown
# DISPATCHER_STATUS

- schema_version: 1
- task_id: <ticket task_id>
- job_id: <dispatcher job id>
- dispatcher_sha: <git sha of dispatcher software producing this status>
- timestamp_utc: <ISO-8601 UTC timestamp>
- status: canary_ok
```

**Rules:**
- `schema_version` must be the integer literal `1` (as shown).
- `status` must be exactly `canary_ok` for a successful canary marker (other status values are not permitted in v1 canary success path).
- `task_id`, `job_id`, `dispatcher_sha`, `timestamp_utc` must match tight regexes (no whitespace injection; no control chars; sha hex; timestamp UTC `Z`).
- Maximum file size remains ≤ 8 KiB UTF-8, but schema rejection is primary — size alone is insufficient.
- Credential substring scan still applied as defense-in-depth, not as the sole content control.
- Reject: extra keys, missing keys, reordered keys if order is mandated by validator, duplicate keys, code fences, HTML tags, raw URLs with credentials, base64 blobs, unexpected blank-line patterns if not in schema, any line not matching the schema grammar.

**Tests required:** malformed fields, unexpected lines, encoded data, credential-like content, code fences, HTML, extra keys, wrong status value, oversized file.

---
## 5. Worktree / staging / publisher isolation + Codex CLI + exact permissions

### 5.1 Staging vs trusted worktree (A2/A3)

| Item | Proposal |
|---|---|
| Mirror | `/var/lib/codex-dispatcher/mirrors/dextech.git` — readable by publisher; **not** writable/readable by `codex-runner` beyond what Scotty requires (prefer not readable by runner) |
| Staging root | `/var/lib/codex-dispatcher/staging/canary-<job_id>/` — credential-free; contains ONLY permitted file copy; owned for `codex-runner`; mode 0700; **no `.git`** |
| Trusted publisher worktree | `/var/lib/codex-dispatcher/worktrees/canary-<job_id>/` — created **after** Codex exits; only `codex-publisher` operates here |
| Create staging | Copy single file from mirror/export or trusted read of main blob; never hand Codex a full clone with remotes |
| Create trusted worktree | `git worktree add -b branch` from origin/main **by publisher** after validation |
| Dispose | Keep for audit by default; Scotty inventories; delete only after Will approves (W4) |
| Modes | staging/worktree/audit roots 0700; correct owners |

### 5.2 OS identity split (preferred)

| Identity | Role | Credentials |
|---|---|---|
| `codex-runner` | Runs Codex CLI only | **None** of: deploy key, `SSH_AUTH_SOCK`, GitHub tokens, authenticated Git config, publisher env |
| `codex-publisher` | Trusted git commit/push + evidence finalize | Deploy key path readable only by publisher; sanitized Git env |
| Supervisor (may be publisher or separate dispatcher account) | Orchestrates; holds locks; validates; never lets Codex inherit FDs | Lock FDs CLOEXEC; does not pass key material into Codex env |

Equivalent isolation (containers, user namespaces) acceptable if tests prove the same invariants.

### 5.3 Codex CLI gates

All required: `canary_execution_enabled=true`, `verified_noninteractive=true`, explicit canary-run entrypoint, non-empty website SafetyRuleConfig, LockPathConfig under codex-dispatcher lock root, allowlist+permitted path as above, **main-protection gate already recorded for OPS1** (not re-proved by push), W9 resolved before live CANARY1.

Sandbox: workspace-write limited to **staging dir only**. Network **disabled** for Codex during canary. One attempt, hard timeout (proposed 15 min). Prompt includes path+stop+schema; no credentials; no merge/deploy ask; no open-PR ask.

**Process group (A7):** Launch Codex in a dedicated process group/session (`setsid` / `start_new_session=True` or equivalent). On timeout/cancel: send signal to entire process group; wait/reap; verify `/proc` or equivalent shows no descendants; only then release locks.

### 5.4 Git/SSH — exact proposed permissions (W2 DECIDED + A1/A2/A3)

| Item | Decision |
|---|---|
| Credential type | Dedicated repo deploy key for branch push ONLY — readable by `codex-publisher` only |
| Main protection | **Prerequisite:** rulesets/protection configured + independently verified via settings/API **read** before write key install / OPS1; deny deploy-key identity direct main push, force push, branch deletion, review bypass; **no mutating push probe** |
| Dispatcher GitHub API | NONE — no GITHUB_TOKEN, no gh auth, no App private key |
| Deploy key PR capability | Cannot open PRs |
| After branch push | Picard routes independently authorized Grok GitHub bot or human to open draft PR |
| Dispatcher merge/deploy | Must not merge or deploy |
| Fetch | Read-only mirror fetch credential OR same deploy key with fetch — publisher only |
| Push scope | Hard-coded non-force push to validated `refs/heads/agent/canary/*` only; validate canonical remote; disable hooks |
| Forbidden scopes | NO repo admin; NO Actions; NO Secrets; NO Environments; NO webhook admin |
| Transport | git remote SSH only (publisher) |
| Key mode | 0600; never in repo/tickets/logs/backups; **not readable by `codex-runner`** |
| Author | codex-dispatcher-canary with Job-Id/Ticket-Url/Dispatcher-SHA trailers |
| Forbidden ops | No history rewrite push; no push to main/master; no Will personal credentials; no force push |
| Codex env | No `SSH_AUTH_SOCK`; no `GIT_*` auth; no key path; no network |

See section 16 for the full permissions appendix.

### 5.5 Publisher Git hygiene (A3)

Before commit/push from trusted worktree:
1. Sanitize Git environment/config for publisher (clear untrusted `GIT_CONFIG_*`, inject known-safe config).
2. Disable hooks (`core.hooksPath` to empty/null device pattern or `GIT_DIR/hooks` replaced with no-op path Scotty defines).
3. Validate canonical remote URL/fingerprint against OPS1-recorded expected value.
4. Hard-code non-force push (`git push` without `--force` / `--force-with-lease` as a force variant unless Will later designs otherwise — v1: plain non-force only) to refs matching `refs/heads/agent/canary/*` after local validation of ref name.
5. Refuse if HEAD is main/master or if ref does not match canary pattern.

### 5.6 Branch naming

`agent/canary/<task_id>-<yyyymmdd>-<shortsha>`

Draft PR (opened externally in P6) title suggestion: `canary: dispatcher status marker (no merge)`

### 5.7 Isolation acceptance tests (design intent)

- Runner cannot `open` deploy-key path (EACCES).
- Runner environment lacks `SSH_AUTH_SOCK`, `GITHUB_TOKEN`, and key path vars.
- Runner cannot write publisher worktree, mirror, `.git`, audit, or lock root.
- Lock FDs not present in Codex `/proc/self/fd`.
- After timeout simulation, no descendant processes remain before unlock.
- Codex cannot modify Git config/hooks in publisher tree because it never has that tree.

---

## 6. Test/build and deploy non-fire evidence checklist

### 6.1 Canary pre-push checks

dextech browser tests.js only; no server start for canary v1.
Mandatory before publish checks:

1. Target exists as regular file (not symlink); realpath inside trusted worktree.
2. Changed paths == exactly `canary/DISPATCHER_STATUS.md`.
3. Final staged diff is exactly that one file.
4. SafetyPolicy `validate_candidate_diff` PASS.
5. Status file matches **exact schema** (§4.10); ≤ 8 KiB UTF-8; credential-like substring scan PASS as secondary.
6. Real GitHub label `dispatcher-canary` was verified at assess time.
7. Acceptance phrases byte-identical.
8. Codex process group fully reaped.
9. Optional `node --check server.js` only if unchanged (should be unchanged).

### 6.2 Deploy non-fire evidence checklist (Astra A8 — mandatory before CANARY1)

**Absence of `.github/workflows` alone is NOT proof.** OPS1 / pre-CANARY1 evidence pack MUST inspect and record:

| # | Surface | What to inspect | Pass criteria (design) |
|---|---|---|---|
| NF1 | GitHub Actions | Actions enabled/disabled; any workflows (including outside default path if present); required workflows; "Allow GitHub Actions" repo settings | No workflow runs on `agent/canary/*` push; or Actions disabled for forks/branches as applicable; document settings screenshots/API reads |
| NF2 | Repo settings | Pages source; deploy keys list; environments; branch rules interaction with deploys | Pages not building from canary branches; environments not auto-deploying canary |
| NF3 | GitHub webhooks | All repo webhooks: URL, events (`push`, `create`, etc.) | No webhook delivers canary branch pushes to deploy systems; or deliveries proven inert |
| NF4 | Cloudflare Pages | Project build config; production branch; preview/branch deployments | Branch deployments disabled for canary pattern OR project not connected to auto-build canary branches |
| NF5 | Cloudflare Workers | Build/deploy hooks; Git integration | No Worker deploy on canary push |
| NF6 | DexServe hooks | Any local or remote deploy hooks listening to GitHub/git | No DexServe deploy unit triggered by canary refs |
| NF7 | External CI/CD | Any other known DexTech deploy integration | Documented none, or proven non-fire |

Record evidence artifacts under OPS1 pack (hashes, redacted API reads, settings exports). Fail closed until non-fire is proven. Human: Worf or Will review draft PR (opened in P6) before any merge.

**Do not** use a production-impacting push to "see what fires." Prefer settings/API reads, webhook inventory, Cloudflare dashboard/API reads, and controlled dry analysis.

---

## 7. Audit evidence + W11 backups

`/var/lib/codex-dispatcher/audit/<job_id>/` (mode 0700; not readable by `codex-runner`) contains:

- `ticket.json`, `assess.json` (include **label metadata proof**, not body-field trust)
- `diff.patch`, `changed_paths.txt`, `safety.json`
- `status_schema.json` (validator result for §4.10)
- `isolation.json` (runner env scrub summary; FD non-inheritance check result; network-disabled attestation)
- `git.json` (remote redacted; branch name, commit SHA, push result — not PR URL from dispatcher; hooks-disabled attestation; non-force attestation)
- `deploy_trigger_nonfire.json` (pre-CANARY1 evidence reference / checklist results)
- `main_protection.json` (OPS1 reference: rulesets/protection API/settings read evidence — **not** a push probe)
- `process_reap.json` (timeout/cancel path: pgid, signals, reap verification)
- `result.json`

result status enum: `blocked` | `failed` | `cancelled` | `awaiting_human_review` | `abandoned`  
(`awaiting_human_review` means branch pushed + evidence ready; PR opening is P6 external.)  
Never merged/deployed from automation.

Ledger: append-only job id, ticket url, branch, commit, status — no secrets.

### 7.1 Backups (W11 DECIDED)

Scotty owns provisioning + audit-evidence backup. Backups exclude private keys/tokens; retain fingerprints, config hashes, logs, verification evidence (including main-protection read evidence and non-fire checklist). Credential create/rotate needs Will approval.

Staging dirs and publisher worktrees are inventory targets under W4 — backups of audit evidence preferred over backing up staging contents that may contain untrusted Codex output (if backed up, treat as untrusted).

---

## 8. Failure cleanup and retry (W4 + A7)

| Failure | Cleanup | Retry |
|---|---|---|
| Assess blocked (incl. missing real label) | No staging; release locks | New ticket/job |
| Safety fail / symlink / non-regular / multi-file / schema fail | No push; keep staging/worktree; ledger failed; release locks **after** reap | New job id only |
| Timeout / cancel | Signal Codex **process group**; wait/reap; verify no child remains; **then** release locks; no push | Manual requeue after Picard/Will |
| Push fail | Keep local commit/trusted worktree; release locks after reap | After credential fix + Will |
| Busy lock | Blocked | Wait; no queue jump |
| Partial lock acquire (second fails) | Immediately release/close first; fail closed | Retry when free |
| Abort mid-job | Reap tree; release locks; mark cancelled/failed; retain staging/worktree | Will-directed |
| Isolation probe fail (runner can see key) | Hard fail; do not launch Codex; release locks | OPS fix + Will |

No automatic deletion of worktrees/branches/staging in v1. Scotty inventories; cleanup only after Will approves.  
No automatic infinite retry. No history-rewrite recovery.  
**ROLLBACK** distinguishes publisher worktree vs staging (see §15).

---
## 9. Activation W8 + main-protection gate

Automation may (when gated): create staging, edit permitted file via Codex runner, validate, copy into trusted worktree, push branch, write evidence.  
Automation must not: open PRs, merge, dismiss reviews, change protection, deploy, restart website, DNS, Cloudflare, poll unattended, run as daemon, force push, mutating protection probes.

Activation requires ALL gates in §5.3 plus:

- W9 resolved before OPS1/CANARY1
- **Main-protection gate (A1):** rulesets/protection configured; independently verified via settings/API read; evidence filed in OPS1 pack; write deploy key installed only **after** verification
- Non-fire checklist (A8) complete before CANARY1

Missing any → refuse. Dry-run assess remains available without activation.  
First enablement: supervised and one-shot. No persistent daemon. No unattended polling (W8).

---

## 10. Configuration summary

| Knob | Default | Notes |
|---|---|---|
| global_agent_lock | /run/lock/codex-dispatcher/agent.lock | Injected; OPS1 pre-created root |
| implementation_lock | /run/lock/codex-dispatcher/implementation.lock | Distinct |
| lock_root_fallback | none | Fail closed; never /tmp or repo; never runtime mkdir root |
| allowed_repositories | inject nonempty | Canary: dexsword/dextech only |
| permitted_paths | canary/DISPATCHER_STATUS.md | Regular file; reject symlink |
| status_schema | §4.10 exact | Reject free-form |
| canary_execution_enabled | false | Will flip for supervised one-shot |
| verified_noninteractive | false | Will flip for canary profile |
| open_draft_pr | false / absent | Dispatcher must not open PRs (W10) |
| CODEX_DISPATCHER_DRY_RUN | true | false only inside gated canary-run |
| Git SSH deploy key | unset → refuse push | Publisher only; branch-only write |
| GITHUB_TOKEN / gh / App key | must be unset in dispatcher **and** runner env | Fail if present in canary profile |
| SSH_AUTH_SOCK | must be unset for runner | Fail if present when launching Codex |
| Codex network | disabled | Canary profile |
| Staging root | /var/lib/codex-dispatcher/staging | Runner-writable; 0700 |
| Worktree root | /var/lib/codex-dispatcher/worktrees | Publisher; 0700 |
| Audit root | /var/lib/codex-dispatcher/audit | 0700; not runner-writable |
| auto_delete_worktrees | false | W4 |
| main_protection_evidence_path | OPS1 artifact | Required before key install |
| nonfire_evidence_path | OPS1 / pre-CANARY1 artifact | Required before CANARY1 |

Do not read CopyMoney `ORCHESTRATOR_*` or copymoney lock defaults in canary profile.

---

## 11. Allow/deny checklist

Allow:
- Read issues for allowlisted repo with **real** label `dispatcher-canary`
- Edit only existing regular file `canary/DISPATCHER_STATUS.md` via staging
- Push `agent/canary/*` via deploy key from trusted publisher worktree (non-force)
- Write audit evidence

Deny:
- Any other path; symlinked target; multi-file staged diff; schema-invalid status file
- Main push; force push; merge; deploy
- Opening PRs from dispatcher / deploy key
- GitHub API credentials in dispatcher or runner process
- Codex reading deploy key / `SSH_AUTH_SOCK` / authenticated Git / publisher checkout / `.git` / audit / mirror
- Host service control; secrets; CopyMoney; ProcessLock; PR #20; trading
- Runtime allowlist expansion; bypass flags; empty SafetyRuleConfig as safe
- Lock fallback to /tmp or repository; runtime mkdir/repair of lock root; silent fchmod of wrong-mode lock
- Automatic worktree/branch/staging deletion
- OPS1 / CANARY1 before W9 resolution
- Write deploy key install / OPS1 before main-protection verified
- Mutating push probe to "prove" branch protection
- Persistent daemon / unattended polling
- Treating absence of `.github/workflows` alone as non-fire proof

---

## 12. Acceptance-test matrix

**Editorial rename (rev3):** SecureProcessLock tests use **SPL-T*** IDs (not F1–F7). Implementation packets remain **F1–F5**. Canary tests use **C*** and may be referred to as **CAN-T*** equivalently in tooling; this document lists **C*** primary IDs with CAN-T aliases where helpful.

### 12.1 SecureProcessLock — SPL-T*

| ID | Case | Expected |
|---|---|---|
| SPL-T1 | Fresh acquire under correct OPS1-precreated ownership | Success; 0600 file; 0700 dir; dirfd path |
| SPL-T2 | Second acquire | AlreadyLocked |
| SPL-T3 | Symlink lock path | Refuse |
| SPL-T4 | Paired-capture path | LockPathError |
| SPL-T5 | Crash then reacquire | Success |
| SPL-T6 | flock before truncate | Proven in tests |
| SPL-T7 | CopyMoney ProcessLock untouched | Goldens unchanged |
| SPL-T8 | Wrong ownership / mode on lock root | Fail closed; no /tmp fallback; no runtime mkdir repair |
| SPL-T9 | Lock release while worktree/staging retained | Locks free; trees remain |
| SPL-T10 | Missing lock root (OPS1 not done) | Fail closed; must NOT create root |
| SPL-T11 | open root without O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC semantics violated | Refuse / test enforces flags behavior |
| SPL-T12 | Existing lock file wrong mode | Fail closed; **no silent fchmod** |
| SPL-T13 | Partial pair: second lock fails | First lock immediately released/closed |
| SPL-T14 | Lock FD not inherited by child | Child `/proc/self/fd` lacks lock FDs; CLOEXEC proven |
| SPL-T15 | openat relative to dirfd; escape attempt via crafted name | Refuse |

### 12.2 Canary — C* / CAN-T*

| ID | CAN-T alias | Case | Expected |
|---|---|---|---|
| C1 | CAN-T1 | Missing phrases | blocked |
| C2 | CAN-T2 | Wrong repo | blocked |
| C3 | CAN-T3 | Wrong declared path | blocked |
| C4 | CAN-T4 | Touches server.js | safety fail; no push |
| C5 | CAN-T5 | Only status file (regular, contained, schema-valid) | pass validate |
| C6 | CAN-T6 | Default activation | refuse |
| C7 | CAN-T7 | Busy lock | second blocked |
| C8 | CAN-T8 | Successful canary path | branch pushed + evidence; awaiting_human_review; NO PR opened by dispatcher (branch-only); publisher-only push |
| C9 | CAN-T9 | Prohibited action in patch | ACTION_PROHIBITED |
| C10 | CAN-T10 | Empty SafetyRuleConfig prod | refuse start |
| C11 | CAN-T11 | Target is symlink | reject (W7) |
| C12 | CAN-T12 | Target missing (not pre-seeded) | reject |
| C13 | CAN-T13 | Realpath escapes worktree/staging | reject |
| C14 | CAN-T14 | Staged diff has extra file | reject; no push |
| C15 | CAN-T15 | Dispatcher/runner env has GITHUB_TOKEN | refuse canary-run |
| C16 | CAN-T16 | Non-fire gate not proven | block CANARY1 |
| C17 | CAN-T17 | W9 unresolved | block OPS1 and CANARY1; F1–F5 may proceed after Picard publish + Astra re-review + Will |
| C18 | CAN-T18 | Unattended/daemon mode | refuse (W8 one-shot only) |
| C19 | CAN-T19 | JSON claims label but GitHub metadata lacks `dispatcher-canary` | blocked (A5) |
| C20 | CAN-T20 | Acceptance phrase punctuation/backtick drift | blocked (byte-identical) |
| C21 | CAN-T21 | Status file has free-form body / code fence / HTML / extra keys | reject (A6) |
| C22 | CAN-T22 | Status file credential-like or encoded blob | reject (A6) |
| C23 | CAN-T23 | Runner can read deploy-key path or SSH_AUTH_SOCK | refuse launch; isolation fail (A2) |
| C24 | CAN-T24 | Codex attempts to modify `.git` / hooks / audit | denied; no publish (A3) |
| C25 | CAN-T25 | Timeout leaves descendant process | fail test if descendant remains; production path must reap before unlock (A7) |
| C26 | CAN-T26 | Main-protection evidence missing | block OPS1 / key install (A1) |
| C27 | CAN-T27 | Non-fire only checked via missing workflows dir | insufficient; require full A8 checklist |
| C28 | CAN-T28 | Force push attempted by publisher path | refused / hard-coded non-force |
| C29 | CAN-T29 | Runner has network enabled in canary profile | refuse |
| C30 | CAN-T30 | Publisher hooks not disabled | refuse push |

---

## 13. Task/PR decomposition + sequence + W9 + main-protection before OPS1

### 13.1 Mandatory sequence (rev 3)

1. Design rev3 approval (this pack)
2. Picard publishes **immutable commit** of this design
3. Astra **re-reviews** the published immutable commit
4. Will authorizes F1+
5. F1–F5 engineering
6. W9 resolution (dextech#3) — **BLOCKS OPS1 and CANARY1**
7. **Main-protection configured + independently verified** (settings/API read evidence) — **BEFORE** write deploy key install or OPS1
8. OPS1 provisioning (Scotty) — includes lock root pre-create, identities, non-fire evidence start, main-protection evidence filed
9. WEB0 human-seed (ordering: before CANARY1; may proceed when safe relative to W9/main-protection as Will directs)
10. Supervised CANARY1 (one-shot)
11. P6 external draft PR

### 13.2 Task table

| Task | Title | Owner | Depends / Gate |
|---|---|---|---|
| DESIGN-rev3 | This pack | Geordi | Will W1–W11 + Astra CHANGES REQUIRED |
| PUBLISH | Picard immutable commit of rev3 | Picard | DESIGN-rev3 |
| ASTRA | Re-review published immutable commit | Astra | PUBLISH |
| F1 | SecureProcessLock + SPL-T* tests; ProcessLock untouched; dirfd/A4 semantics | OBrien | Astra re-review + Will authorize F1+ |
| F2 | Canary profile config (allowlist, paths, gates default off, branch-only, schema, isolation flags) | OBrien | F1 |
| F3 | Staging + audit writer + trusted worktree prep seams (no Codex invoke; no PR open) | OBrien | F2 |
| F4 | Wire Codex invoke as `codex-runner` behind multi-gate supervised canary-run; process group; publisher push path | OBrien | F3 + Will enablement ceremony |
| F5 | Fixtures: byte-identical phrases + website SafetyRuleConfig + status schema samples | OBrien/Geordi | F2 |
| W9 | Validate/rotate/revoke/remove cloudflare key/pem materials; ignore + secret-scanning; propose history rewrite | Scotty/Worf + Will | Tracks dextech#3; blocks OPS1/CANARY1 |
| WEB0 | Human-seed `canary/DISPATCHER_STATUS.md` on dextech main (reviewed commit; confirm inert; schema-ready) | OBrien or Will | W5; before CANARY1 |
| PROT | Configure + verify main branch protection/rulesets (read evidence; no push probe) | Scotty/Worf + Will | Before write deploy key / OPS1 |
| OPS1 | Pre-create lock/staging/worktree/audit dirs + OS identities + deploy key (branch-only, after PROT) + non-fire evidence | Scotty | W9 resolved + PROT verified + Will |
| CANARY1 | Supervised first live canary — staging→validate→trusted publish branch + evidence only | Picard routes | F4+OPS1+WEB0+non-fire+Will go; W9 resolved |
| P6-PR | Open draft PR via Grok GitHub bot or human | Picard routes | After CANARY1 branch+evidence |

Worf reviews each implementation PR for bypass/fail-open, path confinement, branch-only stop, isolation invariants, and absence of GitHub API credentials in dispatcher/runner.

F1–F5 may proceed after Picard immutable publish + Astra re-review + Will authorize F1+. No provisioning or canary execution until W9 resolved **and** main-protection verified before OPS1.

---

## 14. Will decisions W1–W11 — DECIDED table

W1–W11 decisions are **unchanged**. Astra items are recorded as design constraints A1–A8 (see §0.1), not as reopened Will questions.

| ID | Status | Decision | Notes |
|---|---|---|---|
| W1 | DECIDED — APPROVE | Canary tickets in dexsword/dextech with label dispatcher-canary. Task F engineering in codex-dispatcher. | Ticket inbox separated from engineering repo; **A5:** verify real label metadata |
| W2 | DECIDED — AMEND | Dedicated repo deploy key for branch push ONLY. Repo rules prevent direct main changes. Dispatcher gets NO GitHub API credential. Deploy key cannot open PRs. After branch push + evidence, Picard routes independently authorized Grok GitHub bot or human to open draft PR. Dispatcher must not merge or deploy. | Narrowest credential; PR opening is out-of-process; **A1:** protection must actually exist before key/OPS1; **A2:** key only on publisher |
| W3 | DECIDED — APPROVE WITH CONDITIONS | Lock root /run/lock/codex-dispatcher/, provisioned at boot, owned by dedicated non-root dispatcher account. Dir 0700; lock files 0600. Fail closed on incorrect ownership, permissions, or symlinks. No fallback to /tmp or the repository. | **A4:** OPS1 pre-creates; runtime verifies via dirfd; no runtime mkdir/repair |
| W4 | DECIDED — AMEND | No automatic deletion in v1. Scotty inventories worktrees/branches; cleanup only after Will approves. Process locks must still release normally and must not persist with retained worktrees. | Evidence retention over auto-cleanup; applies to staging too |
| W5 | DECIDED — APPROVE | Human-seed canary/DISPATCHER_STATUS.md on main in separate reviewed commit. Confirm inert (not rendered or deployed as website content). | Predictable regular-file target; schema-ready |
| W6 | DECIDED — APPROVE | Exact allowlist dexsword/dextech only. | Minimal blast radius |
| W7 | DECIDED — APPROVE WITH CONDITIONS | Only permitted path canary/DISPATCHER_STATUS.md. Must already exist as regular file. Reject symlinks; verify real-path containment; final staged diff exactly that one file. | Symlink/escape hardened; staging + publisher both enforce |
| W8 | DECIDED — APPROVE | First enablement supervised and one-shot. No persistent daemon or unattended polling. | Human-in-the-loop activation |
| W9 | DECIDED — AMEND; BLOCKS OPS1 AND CANARY1 | cloudflare.key/pem potentially exposed. Tracked at https://github.com/dexsword/dextech/issues/3. Validity without displaying contents; rotate/revoke; remove safely; ignore + secret-scanning; propose history rewrite separately. F1–F5 may proceed after design+Astra approval; no provisioning or canary execution until W9 resolved. | Security blocker adjacent to canary; **still hard blocker** |
| W10 | DECIDED — AMEND | Dispatcher branch-only for v1 (align with W2). No draft-PR open by dispatcher. | P5 = branch+evidence; P6 = external |
| W11 | DECIDED — APPROVE WITH CONDITIONS | Scotty owns provisioning + audit-evidence backup. Backups exclude private keys/tokens; retain fingerprints, config hashes, logs, verification evidence. Credential create/rotate needs Will approval. | Least privilege backups |

### 14.1 Astra additions as design constraints (not Will reopenings)

| ID | Constraint summary |
|---|---|
| A1 | Main protection unmet prerequisite; verify via settings/API read; before write key/OPS1 |
| A2 | Isolate Codex from publication credentials; runner vs publisher; no network; tests |
| A3 | Staging → validate → trusted publish; protect `.git`/hooks/mirror/audit |
| A4 | SecureProcessLock dirfd; OPS1 pre-create; no runtime mkdir; CLOEXEC; partial acquire |
| A5 | Real `dispatcher-canary` label metadata; byte-identical phrases |
| A6 | Exact status-file schema; reject free-form/fences/HTML |
| A7 | Process group/session; kill tree; reap before unlock; regression test |
| A8 | Non-fire checklist beyond missing workflows |

---
## 15. Explicit ROLLBACK procedure

Apply on failed canary, bad push, abort mid-job, post-push before PR, or after mistaken PR by human/bot.

**Note (rev3):** Distinguish **staging** (untrusted Codex output; never has publication creds) from **publisher worktree** (trusted git state). ROLLBACK must release locks only after process-group reap; must not confuse deleting staging with rewriting git history.

### 15.1 Always (every abort / failure)

1. Terminate Codex process group if any; wait/reap; verify no descendants.
2. Release locks always (process locks must not persist with retained worktrees/staging).
3. Do not delete staging, worktree, or branch without Will approval (W4).
4. Mark ledger failed or cancelled with reason; preserve audit dir.
5. Never rewrite remote history. Never reset main. Never merge. Never deploy. Never force-push cleanup.

### 15.2 Abort mid-job (before push)

1. Stop Codex process group if running; reap; verify clear.
2. Release locks.
3. Mark ledger failed/cancelled.
4. Retain staging and any publisher worktree for Scotty inventory; Will decides cleanup.
5. Staging contents are untrusted — do not promote them.

### 15.3 Bad or unwanted branch push (post-push, before PR)

1. Ensure Codex tree reaped; release locks if still held.
2. Mark ledger failed/cancelled or annotate awaiting_human_review superseded.
3. Leave the remote branch in place by default.
4. Optional: human deletes remote branch only after Will approves.
5. Do not rewrite history on the branch; do not rewrite main.

### 15.4 After mistaken draft PR opened by human/bot (P6)

1. After Will approval: close the draft PR without merge.
2. Leave or delete the branch per Will (default leave until Will says delete).
3. Do not use dispatcher or deploy key to close/merge; use the PR-authorized identity or human UI.
4. Record closure in audit notes / ledger annotation.

### 15.5 Seed file rollback (W5)

If `canary/DISPATCHER_STATUS.md` seed must be reverted: only via normal reviewed PR — never history rewrite; never direct main edit from dispatcher/publisher automation.

### 15.6 Credential / W9 / protection incident rollback

If deploy key suspected compromised: Will-approved revoke/rotate (W11); Scotty updates fingerprints in backups; publisher config points to new key; old key destroyed; confirm `codex-runner` never had access.
If main protection misconfigured: treat as OPS blocker; remove write deploy key until protection re-verified via settings/API read.
W9 cloudflare material: follow dextech#3 — validate without displaying contents; rotate/revoke; remove safely; ignore + secret-scanning; history rewrite only as separately proposed/approved work.

### 15.7 ROLLBACK checklist (summary)

| Step | Action |
|---|---|
| 1 | Kill Codex process group; wait/reap; verify no child |
| 2 | Release SecureProcessLock pair |
| 3 | Ledger → failed/cancelled |
| 4 | Retain staging + publisher worktree + audit (no auto delete) |
| 5 | If branch pushed → leave branch; optional human delete after Will |
| 6 | If draft PR exists → close without merge after Will |
| 7 | Never rewrite history; never reset main; never auto-merge/deploy; never force-push |
| 8 | Revert seed only via reviewed PR if needed |
| 9 | Picard notifies Will; Scotty inventories remnants (staging vs publisher noted separately) |

---

## 16. Exact proposed permissions appendix

### 16.1 OS accounts and directories (rev3 split)

| Object | Proposed |
|---|---|
| Untrusted runner OS user | `codex-runner` (non-root) |
| Trusted publisher OS user | `codex-publisher` (non-root) |
| Supervisor / lock holder | May be `codex-publisher` or dedicated dispatcher account; must not leak FDs/creds to runner |
| Group | As Scotty defines (dedicated groups preferred; runner not in publisher key group) |
| Lock root `/run/lock/codex-dispatcher/` | OPS1 pre-created; owned as designed for lock holder; mode **0700**; not a symlink; runtime does not create |
| Lock files (`agent.lock`, `implementation.lock`) | mode **0600**; CLOEXEC FDs; not inherited by Codex |
| Staging root `/var/lib/codex-dispatcher/staging/` | Owned for `codex-runner` (or ACL allowing runner only on job subdir); 0700; **no secrets**; no `.git` |
| Worktree root `/var/lib/codex-dispatcher/worktrees/` | Owned by `codex-publisher`; 0700; runner **denied** |
| Audit root `/var/lib/codex-dispatcher/audit/` | Owned by publisher/supervisor; 0700; runner **denied** |
| Mirror root | Publisher-readable; runner denied (preferred) |
| Deploy key file | 0600; `codex-publisher` only; path not readable by `codex-runner` |
| Fail closed | Incorrect ownership, permissions, or symlinks → refuse; no /tmp or repo fallback |

### 16.2 Codex / runner must NOT have

- Deploy-key private file readability
- `SSH_AUTH_SOCK` (must be unset)
- `GITHUB_TOKEN`, `gh` auth, App private key
- Authenticated Git config / credential helpers pointing at publication creds
- Network access during canary
- Access to publisher worktree, mirror (preferred), audit, lock root (write), `.git` of trusted trees
- Inherited lock FDs

### 16.3 Git / deploy key scopes (publisher only)

| Capability | Deploy key / git identity |
|---|---|
| Fetch | Read-only mirror fetch credential OR same deploy key with fetch |
| Push | Non-force write to `refs/heads/agent/canary/*` only if platform allows; else write non-main + **branch protection** blocks main |
| Main / default branch push | Denied (repo rules + protection) — **protection must exist before key install** |
| Force push | Denied |
| Branch deletion | Denied for deploy-key identity via protection/rulesets |
| Bypass required review | Denied |
| Repo admin | NO |
| Actions admin | NO |
| Secrets | NO |
| Environments | NO |
| Webhook admin | NO |
| Open / merge PRs | NO (deploy key cannot open PRs) |
| History-rewrite push | NO |

### 16.4 Main-protection evidence (A1) — OPS1 pack

Record (read-only):
- Rulesets and/or classic branch protection covering `main`
- Required reviewers / status checks as Will defines
- Explicit denial of force push and deletions as applicable
- Confirmation deploy-key/`codex-publisher` identity cannot push main, cannot force-push, cannot delete protected branches, cannot bypass review
- Timestamped API/settings export hashes

**Forbidden as evidence:** any potentially mutating test push.

### 16.5 PR opening identity (P6 — not dispatcher)

Separate Grok GitHub bot or human with PR-write permission — not the deploy key; not embedded in the dispatcher or runner process. Picard routes after branch push + evidence.

### 16.6 Backups (W11)

- Include: fingerprints, config hashes, logs, verification evidence, audit artifacts (redacted), main-protection read evidence, non-fire checklist
- Exclude: private keys, tokens, deploy key private material, cloudflare key/pem contents, raw `SSH_AUTH_SOCK` material
- Credential create/rotate: Will approval required

### 16.7 Publisher process Git env

- Sanitized env; hooks disabled; canonical remote validated; hard-coded non-force push to validated canary refs
- No Will personal credentials

---
## 17. Decision log + changelog

### 17.1 Standing design decisions

| ID | Decision | Rationale |
|---|---|---|
| D1 | Separate SecureProcessLock | Preserve ProcessLock / PR #20 |
| D2 | Lock under /run/lock/codex-dispatcher | Disjoint namespaces |
| D3 | Allowlist dextech only | Minimal blast radius |
| D4 | Single status file path | Clear policy subject |
| D5 | Multi-gate default-off | Prevent ambient enable |
| D6 | Reuse Task E SafetyPolicy | No second stack; honor N2 |
| D7 | No server start in canary v1 | Avoid loading prod secrets |
| D8 | Report in-repo key material via W9/dextech#3 | Safety honesty without scope creep into silent ignore |
| D9 | Staging → validate → trusted publish | Isolate untrusted Codex from Git credentials and `.git` (Astra) |
| D10 | `codex-runner` vs `codex-publisher` | Credential boundary (Astra) |
| D11 | Byte-identical acceptance phrases | Avoid normalization ambiguity (Astra) |
| D12 | Exact status schema | Prevent payload smuggling (Astra) |
| D13 | Process group kill before unlock | No orphan descendants (Astra) |
| D14 | Main protection before write key/OPS1 | Unmet prerequisite on live GitHub (Astra) |
| D15 | Test ID rename SPL-T* / C*|CAN-T* | Avoid confusion with packets F1–F5 |

### 17.2 Changelog rev1 → rev2 (retained summary)

| Change | Rev1 | Rev2 |
|---|---|---|
| Stage header | DESIGN ONLY | DESIGN ONLY rev 2; Will decisions incorporated; Astra gate |
| W1–W11 | Open questions | All DECIDED (approve / amend / conditions) |
| P5 | Push branch + open draft PR | Push review branch + evidence only (NO PR by dispatcher) |
| P6 | Human stop | Picard routes Grok GitHub bot or human for draft PR |
| W2 credential | Deploy key or App; branch+PR write | Deploy key branch-only; no API credential in dispatcher |
| W3 lock | Proposed | Non-root ownership; 0700/0600; fail closed; no /tmp fallback |
| W4 cleanup | Ops TTL optional | No auto delete; locks still release |
| W7 path | Create or modify | Must exist as regular file; reject symlink; realpath; exact one-file diff |
| W8 enablement | Supervised required | Supervised one-shot; no daemon/polling |
| W9 | Adjacent note | BLOCKS OPS1 and CANARY1; F1–F5 ok after Astra |
| W10 | Draft PR on | Branch-only aligns W2 |
| Sequence | After Will approve | Design → Astra → F1–F5 → W9 → OPS1 → CANARY1 |
| Non-fire gate | Implicit | Explicit verification before CANARY1 |
| ROLLBACK | Not dedicated | Section 15 explicit ROLLBACK procedure |
| Permissions | Sketch | Section 16 exact proposed permissions appendix |
| Acceptance C8 | Draft PR | Branch-only + evidence; no dispatcher PR |
| New tests | — | C11–C18 (symlink, realpath, token absence, W9 gate, one-shot, non-fire) |

### 17.3 Changelog rev2 → rev3

| Change | Rev2 | Rev3 |
|---|---|---|
| Stage header | DESIGN ONLY — rev 2 | DESIGN ONLY — rev 3; Astra CHANGES REQUIRED addressed; F1+ needs Picard immutable commit + Astra re-review + Will |
| Prior rev2 pointer | — | Published rev2 commit `89cbbc35825cf8cde4283c742c6d26c9d7cd3486` |
| Sequence | Design → Astra → F1–F5 → W9 → OPS1 → CANARY1 | Design rev3 → Picard immutable publish → Astra re-review → Will F1+ → F1–F5 → W9 → **main-protection verified** → OPS1 → CANARY1 |
| A1 main protection | Assumed "repo rules prevent main" | Live GitHub unprotected; **unmet prerequisite**; settings/API read evidence; no push probe; before write key/OPS1 |
| A2 Codex vs creds | Workspace-write + deny paths | `codex-runner` vs `codex-publisher`; no key/`SSH_AUTH_SOCK`/GitHub tokens/network; tests for non-inheritance |
| A3 Git state | Single worktree Codex edit | Staging-only Codex; trusted worktree after exit; protect `.git`/hooks/mirror/audit |
| A4 locks | Runtime mkdir 0700 sketch | OPS1 pre-create; runtime dirfd `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`; openat locks; no silent fchmod; partial acquire release; CLOEXEC; SPL-T10–T15 |
| A5 tickets | Label in JSON + phrases | Real GitHub label metadata; byte-identical phrases in fixtures |
| A6 status file | 8 KiB + credential scan | Exact schema keys only; reject free-form/fences/HTML; C21–C22 |
| A7 timeout | Kill child | Process group/session; reap tree; verify none; then unlock; C25 |
| A8 non-fire | Actions/webhooks/CF mentioned | Full checklist: Actions+settings, webhooks, CF Pages/Workers, DexServe/external; not just missing workflows |
| Architecture phases | P2 worktree → P3 Codex | P2 staging → P3 runner → P4 validate → P4b trusted copy → P5 publisher |
| Test ID rename | Lock tests F1–F9; canary C* | Lock tests **SPL-T***; packets remain **F1–F5**; canary **C*/CAN-T*** |
| Permissions appendix | Single dispatcher user | Runner vs publisher split; Codex no network; no SSH_AUTH_SOCK; key not runner-readable |
| ROLLBACK | Worktree-centric | Staging vs publisher distinguished; reap-before-unlock |
| Threat model | T1–T15 | Updated T6/T11; added T16–T22 |
| W1–W11 | DECIDED | Unchanged; A1–A8 noted as design constraints |
| CopyMoney | Untouched | Still completely untouched |

---

## 18. Hand-off (Picard → GitHub #14 / docs/design for Astra re-review)

| Role | Action |
|---|---|
| Geordi | This rev 3 design pack (docs only) at `/workspace/codex-dispatcher-design/TASK-F-AND-DEXTECH-CANARY.md` |
| Picard | Publish **immutable commit** of rev 3 to GitHub issue #14 and/or docs/design; do not authorize implementation until Astra re-reviews that commit + Will authorizes F1+ |
| Astra | Re-review published immutable commit (A1–A8 addressed: main-protection prerequisite, Codex/publisher isolation, staging pattern, dirfd locks, label/phrases, status schema, process group, non-fire checklist; branch-only P5; W9 gating; ROLLBACK; permissions) |
| Will | Authorize F1+ only after Picard publish + Astra re-review; authorize OPS1/CANARY1 only after W9 resolved **and** main-protection verified |
| Worf | Review implement PRs for fail-open/bypass; isolation; confirm ProcessLock/PR #20/CopyMoney untouched |
| OBrien | Implement F1–F5 only after Picard post-Astra/Will assignment; use SPL-T* / C* test IDs |
| Scotty | Configure/verify main protection (read evidence); provision OPS1 only after W9 + protection verified + Will; pre-create lock root; own backups per W11; inventory staging/worktrees (no auto delete); complete non-fire checklist |

**Status:** DESIGN ONLY — rev 3 complete for Picard immutable publish and Astra re-review — no implementation started; no dispatcher run; no provisioning; no credentials created; no canary executed; CopyMoney untouched.

**Return path:** Geordi → Picard (immutable commit) → Astra re-review → Will → (F1–F5) → (W9) → (main-protection verified) → OPS1 → supervised CANARY1.

**Prerequisite SHAs (unchanged):** main `7358bc4292bad1a21d3c74a9083dcedd8e6d0c94`; tree `54f61c4af20bec3e4f76be6587265b08f41a23cb`.

**Prior published rev2:** `89cbbc35825cf8cde4283c742c6d26c9d7cd3486`.

---

*End of DESIGN ONLY — rev 3 pack. This document authorizes no code, no provisioning, no credentials, no canary, and no CopyMoney changes.*
