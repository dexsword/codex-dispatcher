# DESIGN: Task F SecureProcessLock + first DexTech website canary

**Stage:** DESIGN ONLY — rev 2
**Issue:** https://github.com/dexsword/codex-dispatcher/issues/14
**Owner:** Geordi (Architecture and Design)
**Coordinator:** Picard
**Authorized by:** Will (2026-09-05 PT) — design only
**Will decisions:** 2026-09-05 PT incorporated (W1–W11 DECIDED)
**Implementation:** NOT authorized until Astra final review + Will authorize F1+

**Prerequisite (accepted):** A–E CLOSED — PR #13; origin/main `7358bc4292bad1a21d3c74a9083dcedd8e6d0c94`; verified tree `54f61c4af20bec3e4f76be6587265b08f41a23cb`; DexServe PASS; CopyMoney + ProcessLock + PR #20 frozen / completely untouched.

**Destination packages/repos:**
- Lock + dispatcher mutation-stage seams: `dexsword/codex-dispatcher`
- First canary target website: `dexsword/dextech` (exact allowlist singleton — W6 DECIDED)
- Canary tickets: `dexsword/dextech` with label `dispatcher-canary` (W1 DECIDED)
- Task F engineering: `dexsword/codex-dispatcher` (W1 DECIDED)

**Artifact path:** `/workspace/codex-dispatcher-design/TASK-F-AND-DEXTECH-CANARY.md`

**Adjacent blocker:** W9 — cloudflare.key / cloudflare.pem potentially exposed in dextech; tracked at https://github.com/dexsword/dextech/issues/3. Blocks OPS1 and CANARY1.

---

## 0. Governing constraints

1. Fail-closed everywhere: missing config, busy lock, allowlist miss, path miss, failed checks, incorrect lock ownership/permissions/symlinks → block; never soft-allow.
2. Do not change CopyMoney `orchestration.lock.ProcessLock` semantics.
3. Do not touch `dexsword/copymoney`, PR #20, measurement/capture locks, wallets, trading, or live activation. **CopyMoney, ProcessLock, and PR #20 are completely untouched.**
4. Do not auto-merge or production-deploy the website. Dispatcher must not merge or deploy.
5. **Branch-only stop (W2/W10 DECIDED):** First canary changes exactly one dedicated harmless status file, pushes a review branch, writes evidence, then STOPS. Dispatcher does **not** open a draft PR. Picard routes an independently authorized Grok GitHub bot or human to open the draft PR after branch push + evidence.
6. Execution remains default-disabled; explicit multi-gate activation required (Will-approved). First enablement is supervised and one-shot (W8) — no persistent daemon or unattended polling.
7. Usage policy: correctness/safety/evidence over savings (`/workspace/policies/USAGE_EFFICIENCY.md`).
8. **W9 blocks OPS1 and CANARY1:** Potential exposure of cloudflare.key/cloudflare.pem must be validated (without displaying contents), rotated/revoked, removed safely, ignored + secret-scanning enabled, with history rewrite proposed separately. F1–F5 may proceed after design + Astra approval; **no provisioning or canary execution until W9 is resolved.**
9. **Sequence gate (mandatory):**
   1. Revised design approval (this rev 2 pack)
   2. Astra final review
   3. F1–F5 (engineering in codex-dispatcher)
   4. W9 resolution (dextech#3)
   5. OPS1 (Scotty provisioning)
   6. Supervised CANARY1 (one-shot)
10. **Deploy-trigger non-fire gate:** Before any live canary push is authorized, verify that pushing a canary branch cannot trigger GitHub Actions, external webhooks, Cloudflare deployment, or any other deploy mechanism.
11. No fallback lock root to `/tmp` or the repository (W3).
12. No automatic worktree/branch deletion in v1 (W4). Process locks must still release normally.

---

## 1. Architecture and data flow

### 1.1 Logical flow

Grok/crew submits structured GitHub ticket (dextech + label `dispatcher-canary`) → Dispatcher on DexServe (canary profile, supervised one-shot) reads issue → acquires SecureProcessLock pair → assess + SafetyPolicy → dedicated worktree → Codex CLI one constrained edit → validate diff (exact one-file, regular-file, realpath containment) → **push `agent/canary/...` branch + write evidence only** → STOP. Picard independently routes Grok GitHub bot or human to open draft PR. No merge/deploy by automation. Dispatcher has **no** GitHub API credential.

### 1.2 Phases

| Phase | Actor | Lock held? | Mutates |
|---|---|---|---|
| P0 Submit | Grok/crew | n/a | GitHub issue body only (dextech + `dispatcher-canary`) |
| P1 Claim/assess | Dispatcher | global + implementation | optional ledger append; no website files yet |
| P2 Worktree prepare | Dispatcher | yes | isolated checkout/worktree |
| P3 Agent edit | Codex CLI via adapter | yes | only permitted canary path |
| P4 Validate | Dispatcher | yes | none (read diff + checks + deploy-trigger non-fire evidence) |
| **P5 Publish review** | **Dispatcher/git** | yes | **push review branch + evidence only — NO PR open by dispatcher** |
| **P6 Draft PR (external)** | **Picard routes Grok GitHub bot or human** | locks already released | **open draft PR using independently authorized PR-write identity — not the deploy key; not the dispatcher** |
| P7 Stop | Human | n/a | merge/deploy forbidden for automation |

### 1.3 Separation from CopyMoney

| Concern | Canary / Task F | CopyMoney |
|---|---|---|
| Repo | codex-dispatcher + dextech | copymoney frozen |
| Lock type | New SecureProcessLock in dispatcher | ProcessLock unchanged; PR #20 SecureCaptureLock untouched |
| Lock namespace | `/run/lock/codex-dispatcher/` (W3 DECIDED) | copymoney agent locks + paired-capture dir |
| Safety tables | Website canary SafetyRuleConfig | Product tables deferred to facade |
| Trading/live | Out of scope | Frozen |
| Credentials | Dedicated repo deploy key (branch push only); no GitHub API | Untouched |

### 1.4 P5 / P6 boundary (critical)

- **P5 (dispatcher):** `git push` of `agent/canary/*` via SSH deploy key; write audit evidence; mark ledger `awaiting_human_review` (branch pushed, PR not opened by dispatcher); release locks.
- **P6 (outside dispatcher):** Picard confirms evidence, then routes separately authorized Grok GitHub bot **or** human to open draft PR. Deploy key cannot open PRs. Dispatcher must not call GitHub API, must not embed `gh`, must not hold App private key / `GITHUB_TOKEN`.

---

## 2. Threat model

### 2.1 Assets

DexServe integrity; git/SSH deploy key material; website content and booking/payment code; TLS material; dispatcher audit trail; CopyMoney isolation; GitHub Actions / webhook / Cloudflare deploy surfaces.

### 2.2 Threats and mitigations

| ID | Threat | Mitigation |
|---|---|---|
| T1 | Symlink/lock swap on ProcessLock-style open | New SecureProcessLock: O_NOFOLLOW, private 0700 dir, fstat regular/euid/nlink==1/0600, flock before truncate; do not modify CopyMoney ProcessLock |
| T2 | Namespace collision with paired-capture | Reject paths under `/run/lock/copymoney-paired-capture/`; use `/run/lock/codex-dispatcher/` |
| T3 | Concurrent jobs | Dual locks; fail-closed busy; one job |
| T4 | Codex edits beyond canary file | Task E SafetyPolicy; post-diff unexpected/denied/protected; abort before push; exact staged diff = one file (W7) |
| T5 | Ticket social engineering | Schema + phrases; path authority from structured fields not prose; label `dispatcher-canary` |
| T6 | Credential exfiltration | No secrets in ticket/prompt; deny key/pem/env paths; dedicated canary git identity; backups exclude private keys/tokens (W11) |
| T7 | Auto-merge/deploy | Branch-only stop; no PR open by dispatcher; no merge/deploy automation |
| T8 | Crash mid-job | flock drops on death; ledger failed; no main touch; locks release even if worktree retained (W4) |
| T9 | Trading bleed | Firewall; no copymoney imports in canary profile |
| T10 | Secrets already in dextech tree (W9) | cloudflare.key/cloudflare.pem potentially exposed — dextech#3. Canary denies those paths. Validity check without displaying contents; rotate/revoke; remove safely; ignore + secret-scanning; history rewrite proposed separately. **Blocks OPS1/CANARY1.** |
| T11 | Over-broad GitHub credential | Dedicated repo deploy key for **branch push ONLY**; repo rules prevent direct main changes; dispatcher gets **NO GitHub API credential**; deploy key cannot open PRs (W2) |
| T12 | Canary branch triggers deploy | Explicit non-fire verification gate: prove push of `agent/canary/*` does not trigger GitHub Actions, external webhooks, Cloudflare deployment, or other deploy mechanisms before CANARY1 |
| T13 | Lock root fallback abuse | Fail closed on incorrect ownership/permissions/symlinks; **no fallback to `/tmp` or the repository** (W3) |
| T14 | Target path symlink escape | Must already exist as regular file; reject symlinks; verify real-path containment; final staged diff exactly that one file (W7) |
| T15 | Unattended enablement | Supervised one-shot only; no persistent daemon; no unattended polling (W8) |

### 2.3 Trust boundaries

GitHub issue text untrusted. Codex output untrusted until policy+path matrix pass. Branch push is not a production trust upgrade. Human (or independently authorized bot under Picard routing) draft PR is review visibility only. Human merge is the only production trust upgrade.

---

## 3. Task F — SecureProcessLock interfaces

### 3.1 Principles

- New type only in `codex_dispatcher.lock` (or `.lock.secure`).
- Never modify CopyMoney ProcessLock or PR #20 SecureCaptureLock.
- Reuse Task D LockPathConfig + paired-capture rejection.
- Semantics inspired by SecureCaptureLock (PR20-reaudit-9ade0d5d).

### 3.2 Identity and location (W3 DECIDED)

| Item | Decision |
|---|---|
| Lock root | `/run/lock/codex-dispatcher/` — provisioned at boot, owned by dedicated **non-root** dispatcher account |
| Dir mode | `0700` |
| Lock files | `0600` |
| Global agent lock | `/run/lock/codex-dispatcher/agent.lock` |
| Implementation lock | `/run/lock/codex-dispatcher/implementation.lock` |
| Ownership fail-closed | Incorrect ownership, permissions, or symlinks → refuse acquire; **no fallback** to `/tmp` or the repository |
| File contents | pid/job_id/started_at after secure open (informational; not used for steal) |
| Busy | Non-blocking exclusive flock; AlreadyLocked / blocked disposition |
| Cross-host | Not supported (document) |

### 3.3 Path defenses

1. Ensure root via mkdir 0700 with directory-fd + O_NOFOLLOW/O_DIRECTORY; refuse unsafe roots rather than chmod through symlinks.
2. Verify root ownership == dedicated dispatcher euid; mode exactly 0700 (or at least no group/other bits); not a symlink.
3. Open lock with O_RDWR|O_CREAT|O_NOFOLLOW.
4. fstat: regular file, st_uid==euid, st_nlink==1, mode 0600 (fchmod on fd if needed).
5. flock before any ftruncate/write.
6. Reject if outside lock root or under paired-capture.
7. If any check fails → fail closed; do not fall back.

### 3.4 Lifetime

Hold both locks from P1 through P5. Acquire global then implementation; release reverse in `finally`.

### 3.5 Crash / cancellation / retained worktrees (W4 DECIDED)

| Action | Behavior |
|---|---|
| Crash | flock released by kernel; next job may acquire |
| Cancel | Stop child; no push if incomplete; ledger cancelled; release locks |
| Stale PID text | Ignored; flock is source of truth |
| Orphan worktree / branch | **No automatic deletion in v1.** Scotty inventories worktrees/branches; cleanup only after Will approves |
| Lock vs retention | **Process locks must still release normally** and must **not** persist with retained worktrees |

### 3.6 API sketch

```python
class AlreadyLocked(RuntimeError): ...

class SecureProcessLock:
    def __init__(self, path: Path, *, job_id: str) -> None: ...
    def __enter__(self) -> SecureProcessLock: ...
    def __exit__(self, *exc: object) -> None: ...

@dataclass(frozen=True)
class SecureLockPair:
    global_agent: SecureProcessLock
    implementation: SecureProcessLock
```

---

## 4. Canary ticket schema, phrases, allow/deny

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
  "label": "dispatcher-canary",
  "affected_paths": ["canary/DISPATCHER_STATUS.md"],
  "primary_change": {"description": "Update dispatcher canary status marker only."},
  "stop_condition": "review_branch_and_evidence_only",
  "acceptance_phrases": [
    "Change is limited to canary/DISPATCHER_STATUS.md",
    "No merge and no production deploy are requested",
    "CopyMoney and trading systems are out of scope"
  ]
}
```

TicketValidator = shape/phrases. SafetyPolicy = paths/actions/diff (Task E).

### 4.3 Locked acceptance phrases

1. "Change is limited to `canary/DISPATCHER_STATUS.md`."
2. "No merge and no production deploy are requested."
3. "CopyMoney and trading systems are out of scope."

### 4.4 Allowlist (W6 DECIDED)

`frozenset({"dexsword/dextech"})` only.

### 4.5 Permitted path (W7 DECIDED — with conditions)

- Only permitted path: `canary/DISPATCHER_STATUS.md`.
- Must **already exist** as a **regular file** (human-seeded on main — W5).
- **Reject symlinks.**
- Verify **real-path containment** inside the worktree / repo root.
- **Final staged diff must be exactly that one file.**

### 4.6 Human-seed (W5 DECIDED)

- Human-seed `canary/DISPATCHER_STATUS.md` on main in a **separate reviewed commit**.
- Confirm inert: **not rendered or deployed as website content**.

### 4.7 Denied paths (never touch)

`.env`, `.env.*`, `bookings.json`, db/sqlite, `server.js`, `gcal-auth.js`, `stripe-import.js`, `stripe-products.json`, `admin.html`, `package.json`, `package-lock.json`, `.git/**`, `.github/**`, `node_modules/**`, credential-like names.
Also deny: `cloudflare.key` and `cloudflare.pem` and patterns `*.key` / `*.pem`.

### 4.8 Protected paths (must not change in diff)

index.html, script.js, style.css, tests.js, legal/support/cancel HTML, images, AGENTS.md, README.md.

### 4.9 Prohibited actions
Dispatcher must not merge, deploy, open PRs via API, or activate CopyMoney/trading.
Also prohibited: rewriting history on remote, default-branch checkout publish, host service control, credentialed env edits, hosting publish hooks, registry publish, empty SafetyRuleConfig treated as safe.

Use non-empty RuleBasedSafetyPolicy (Task E N2).

---

## 5. DexServe worktree, Codex CLI, git/SSH — EXACT proposed permissions

### 5.1 Worktree

| Item | Proposal |
|---|---|
| Mirror | `/var/lib/codex-dispatcher/mirrors/dextech.git` |
| Job worktree | `/var/lib/codex-dispatcher/worktrees/canary-<job_id>/` |
| Create | git worktree add -b branch from origin/main |
| Dispose | Keep for audit by default; Scotty inventories; delete only after Will approves (W4) |
| Modes | worktree/audit roots 0700; owned by codex-dispatcher non-root user |

### 5.2 Codex CLI gates

All required: canary_execution_enabled=true, verified_noninteractive=true, explicit canary-run entrypoint, non-empty website SafetyRuleConfig, LockPathConfig under codex-dispatcher lock root, allowlist+permitted path as above. Sandbox workspace-write limited to worktree. One attempt, hard timeout (proposed 15 min). Prompt includes path+stop; no credentials; no merge/deploy ask; no open-PR ask.

### 5.3 Git/SSH — exact proposed permissions (W2 DECIDED)

| Item | Decision |
|---|---|
| Credential type | Dedicated repo deploy key for branch push ONLY |
| Main protection | Repo rules prevent direct main changes |
| Dispatcher GitHub API | NONE — no GITHUB_TOKEN, no gh auth, no App private key |
| Deploy key PR capability | Cannot open PRs |
| After branch push | Picard routes independently authorized Grok GitHub bot or human to open draft PR |
| Dispatcher merge/deploy | Must not merge or deploy |
| Fetch | Read-only mirror fetch credential OR same deploy key with fetch |
| Push scope | Write to refs/heads/agent/canary/* only if platform allows; else write non-main + rely on branch protection blocking main |
| Forbidden scopes | NO repo admin; NO Actions; NO Secrets; NO Environments; NO webhook admin |
| Transport | git remote SSH only |
| Key mode | 0600; never in repo/tickets/logs/backups |
| Author | codex-dispatcher-canary with Job-Id/Ticket-Url/Dispatcher-SHA trailers |
| Forbidden ops | No history rewrite push; no push to main/master; no Will personal credentials |

See section 16 for the full permissions appendix.

### 5.4 Branch naming

`agent/canary/<task_id>-<yyyymmdd>-<shortsha>`

Draft PR (opened externally in P6) title suggestion: `canary: dispatcher status marker (no merge)`

---

## 6. Test/build and non-fire verification gate

### 6.1 Canary pre-push checks
dextech browser tests.js only; no server start for canary v1.
Mandatory before push checks follow.
1. Target exists as regular file (not symlink); realpath inside worktree.
2. Changed paths == exactly canary/DISPATCHER_STATUS.md.
3. Final staged diff is exactly that one file.
4. SafetyPolicy validate_candidate_diff PASS.
5. Content max 8 KiB UTF-8 without credential-like substrings.
6. Optional node --check server.js only if unchanged.

### 6.2 Non-fire gate (mandatory before CANARY1)

Verify that pushing a canary branch cannot trigger:
- GitHub Actions workflows (especially deploy workflows)
- External webhooks
- Cloudflare deployment / Pages / Workers publish
- Any other deploy mechanism

Record evidence in OPS1 / pre-CANARY1 audit pack. Remediate before supervised CANARY1. Fail closed until non-fire is proven.
Human: Worf or Will review draft PR (opened in P6) before any merge.

---

## 7. Audit evidence

`/var/lib/codex-dispatcher/audit/<job_id>/` (mode 0700) contains:
- ticket.json, assess.json, diff.patch, changed_paths.txt, safety.json
- git.json (remote redacted; branch name, commit SHA, push result — not PR URL from dispatcher)
- deploy_trigger_nonfire.json (pre-CANARY1 evidence reference)
- result.json

result status enum: blocked | failed | cancelled | awaiting_human_review | abandoned
(awaiting_human_review means branch pushed + evidence ready; PR opening is P6 external.)
Never merged/deployed from automation.
Ledger: append-only job id, ticket url, branch, commit, status — no secrets.

### 7.1 Backups (W11 DECIDED)

Scotty owns provisioning + audit-evidence backup. Backups exclude private keys/tokens; retain fingerprints, config hashes, logs, verification evidence. Credential create/rotate needs Will approval.

---

## 8. Failure cleanup and retry (W4)

| Failure | Cleanup | Retry |
|---|---|---|
| Assess blocked | No worktree; release locks | New ticket/job |
| Safety fail / symlink / non-regular / multi-file | No push; keep worktree; ledger failed; release locks | New job id only |
| Timeout | Kill child; no push; release locks | Manual requeue after Picard/Will |
| Push fail | Keep local commit/worktree; release locks | After credential fix + Will |
| Busy lock | Blocked | Wait; no queue jump |
| Abort mid-job | Release locks; mark cancelled/failed; retain worktree | Will-directed |

No automatic deletion of worktrees/branches in v1. Scotty inventories; cleanup only after Will approves.
No automatic infinite retry. No history-rewrite recovery.

---

## 9. Manual approval + default-disabled + supervised one-shot (W8)

Automation may (when gated): create branch, edit permitted file, push branch, write evidence.
Automation must not: open PRs, merge, dismiss reviews, change protection, deploy, restart website, DNS, Cloudflare, poll unattended, run as daemon.
Activation requires ALL gates in section 5.2. Missing any → refuse. Dry-run assess remains available without activation.
First enablement: supervised and one-shot. No persistent daemon. No unattended polling.

---

## 10. Configuration summary

| Knob | Default | Notes |
|---|---|---|
| global_agent_lock | /run/lock/codex-dispatcher/agent.lock | Injected; non-root owned |
| implementation_lock | /run/lock/codex-dispatcher/implementation.lock | Distinct |
| lock_root_fallback | none | Fail closed; never /tmp or repo |
| allowed_repositories | inject nonempty | Canary: dexsword/dextech only |
| permitted_paths | canary/DISPATCHER_STATUS.md | Regular file; reject symlink |
| canary_execution_enabled | false | Will flip for supervised one-shot |
| verified_noninteractive | false | Will flip for canary profile |
| open_draft_pr | false / absent | Dispatcher must not open PRs (W10) |
| CODEX_DISPATCHER_DRY_RUN | true | false only inside gated canary-run |
| Git SSH deploy key | unset → refuse push | Branch-only write |
| GITHUB_TOKEN / gh / App key | must be unset in dispatcher env | Fail if present in canary profile |
| Worktree root | /var/lib/codex-dispatcher/worktrees | Scotty; 0700 |
| Audit root | /var/lib/codex-dispatcher/audit | 0700 |
| auto_delete_worktrees | false | W4 |

Do not read CopyMoney ORCHESTRATOR_* or copymoney lock defaults in canary profile.

---

## 11. Allow/deny checklist

Allow:
- Read issues for allowlisted repo with label dispatcher-canary
- Edit only existing regular file canary/DISPATCHER_STATUS.md
- Push agent/canary/* via deploy key
- Write audit evidence

Deny:
- Any other path; symlinked target; multi-file staged diff
- Main push; merge; deploy
- Opening PRs from dispatcher / deploy key
- GitHub API credentials in dispatcher process
- Host service control; secrets; CopyMoney; ProcessLock; PR #20; trading
- Runtime allowlist expansion; bypass flags; empty SafetyRuleConfig as safe
- Lock fallback to /tmp or repository
- Automatic worktree/branch deletion
- OPS1 / CANARY1 before W9 resolution
- Persistent daemon / unattended polling

---

## 12. Acceptance-test matrix

### Task F (SecureProcessLock)
| ID | Case | Expected |
|---|---|---|
| F1 | Fresh acquire under correct ownership | Success; 0600 file; 0700 dir |
| F2 | Second acquire | AlreadyLocked |
| F3 | Symlink lock path | Refuse |
| F4 | Paired-capture path | LockPathError |
| F5 | Crash then reacquire | Success |
| F6 | flock before truncate | Proven in tests |
| F7 | CopyMoney ProcessLock untouched | Goldens unchanged |
| F8 | Wrong ownership / mode on lock root | Fail closed; no /tmp fallback |
| F9 | Lock release while worktree retained | Locks free; worktree remains |

### Canary
| ID | Case | Expected |
|---|---|---|
| C1 | Missing phrases | blocked |
| C2 | Wrong repo | blocked |
| C3 | Wrong declared path | blocked |
| C4 | Touches server.js | safety fail; no push |
| C5 | Only status file (regular, contained) | pass validate |
| C6 | Default activation | refuse |
| C7 | Busy lock | second blocked |
| C8 | Successful canary path | branch pushed + evidence; awaiting_human_review; NO PR opened by dispatcher (branch-only) |
| C9 | Prohibited action in patch | ACTION_PROHIBITED |
| C10 | Empty SafetyRuleConfig prod | refuse start |
| C11 | Target is symlink | reject (W7) |
| C12 | Target missing (not pre-seeded) | reject |
| C13 | Realpath escapes worktree | reject |
| C14 | Staged diff has extra file | reject; no push |
| C15 | Dispatcher env has GITHUB_TOKEN | refuse canary-run |
| C16 | Non-fire gate not proven | block CANARY1 |
| C17 | W9 unresolved | block OPS1 and CANARY1; F1-F5 may proceed after Astra |
| C18 | Unattended/daemon mode | refuse (W8 one-shot only) |

---

## 13. Task/PR decomposition with sequence and W9 gate

Mandatory sequence:
1. Revised design approval (this rev 2)
2. Astra final review
3. Will authorize F1+
4. F1-F5 engineering
5. W9 resolution (dextech#3) — BLOCKS OPS1 and CANARY1
6. OPS1 provisioning (Scotty)
7. Supervised CANARY1 (one-shot)

| Task | Title | Owner | Depends / Gate |
|---|---|---|---|
| DESIGN-rev2 | This pack | Geordi | Will decisions 2026-09-05 PT |
| ASTRA | Final design review | Astra | DESIGN-rev2 |
| F1 | SecureProcessLock + tests; ProcessLock untouched | OBrien | Astra + Will authorize F1+ |
| F2 | Canary profile config (allowlist, paths, gates default off, branch-only) | OBrien | F1 |
| F3 | Worktree + audit writer (no Codex invoke; no PR open) | OBrien | F2 |
| F4 | Wire Codex invoke behind multi-gate supervised canary-run | OBrien | F3 + Will enablement ceremony |
| F5 | Fixtures: ticket examples + website SafetyRuleConfig | OBrien/Geordi | F2 |
| W9 | Validate/rotate/revoke/remove cloudflare key/pem materials; ignore + secret-scanning; propose history rewrite | Scotty/Worf + Will | Tracks dextech#3; blocks OPS1/CANARY1 |
| WEB0 | Human-seed canary/DISPATCHER_STATUS.md on dextech main (reviewed commit; confirm inert) | OBrien or Will | W5; before CANARY1 |
| OPS1 | Provision lock/worktree/audit dirs + deploy key (branch-only) + non-root account | Scotty | W9 resolved + Will |
| CANARY1 | Supervised first live canary — branch push + evidence only | Picard routes | F4+OPS1+WEB0+non-fire+Will go; W9 resolved |
| P6-PR | Open draft PR via Grok GitHub bot or human | Picard routes | After CANARY1 branch+evidence |

Worf reviews each implementation PR for bypass/fail-open, path confinement, branch-only stop, and absence of GitHub API credentials in dispatcher.
F1-F5 may proceed after design + Astra approval. No provisioning or canary execution until W9 resolved.

---

## 14. Will decisions W1-W11 — DECIDED table

| ID | Status | Decision | Notes |
|---|---|---|---|
| W1 | DECIDED — APPROVE | Canary tickets in dexsword/dextech with label dispatcher-canary. Task F engineering in codex-dispatcher. | Ticket inbox separated from engineering repo |
| W2 | DECIDED — AMEND | Dedicated repo deploy key for branch push ONLY. Repo rules prevent direct main changes. Dispatcher gets NO GitHub API credential. Deploy key cannot open PRs. After branch push + evidence, Picard routes independently authorized Grok GitHub bot or human to open draft PR. Dispatcher must not merge or deploy. | Narrowest credential; PR opening is out-of-process |
| W3 | DECIDED — APPROVE WITH CONDITIONS | Lock root /run/lock/codex-dispatcher/, provisioned at boot, owned by dedicated non-root dispatcher account. Dir 0700; lock files 0600. Fail closed on incorrect ownership, permissions, or symlinks. No fallback to /tmp or the repository. | Hardened lock namespace |
| W4 | DECIDED — AMEND | No automatic deletion in v1. Scotty inventories worktrees/branches; cleanup only after Will approves. Process locks must still release normally and must not persist with retained worktrees. | Evidence retention over auto-cleanup |
| W5 | DECIDED — APPROVE | Human-seed canary/DISPATCHER_STATUS.md on main in separate reviewed commit. Confirm inert (not rendered or deployed as website content). | Predictable regular-file target |
| W6 | DECIDED — APPROVE | Exact allowlist dexsword/dextech only. | Minimal blast radius |
| W7 | DECIDED — APPROVE WITH CONDITIONS | Only permitted path canary/DISPATCHER_STATUS.md. Must already exist as regular file. Reject symlinks; verify real-path containment; final staged diff exactly that one file. | Symlink/escape hardened |
| W8 | DECIDED — APPROVE | First enablement supervised and one-shot. No persistent daemon or unattended polling. | Human-in-the-loop activation |
| W9 | DECIDED — AMEND; BLOCKS OPS1 AND CANARY1 | cloudflare.key/pem potentially exposed. Tracked at https://github.com/dexsword/dextech/issues/3. Validity without displaying contents; rotate/revoke; remove safely; ignore + secret-scanning; propose history rewrite separately. F1-F5 may proceed after design+Astra approval; no provisioning or canary execution until W9 resolved. | Security blocker adjacent to canary |
| W10 | DECIDED — AMEND | Dispatcher branch-only for v1 (align with W2). No draft-PR open by dispatcher. | P5 = branch+evidence; P6 = external |
| W11 | DECIDED — APPROVE WITH CONDITIONS | Scotty owns provisioning + audit-evidence backup. Backups exclude private keys/tokens; retain fingerprints, config hashes, logs, verification evidence. Credential create/rotate needs Will approval. | Least privilege backups |

---

## 15. Explicit ROLLBACK procedure

Apply on failed canary, bad push, abort mid-job, post-push before PR, or after mistaken PR by human/bot.

### 15.1 Always (every abort / failure)

1. Release locks always (process locks must not persist with retained worktrees).
2. Do not delete worktree or branch without Will approval (W4).
3. Mark ledger failed or cancelled with reason; preserve audit dir.
4. Never rewrite remote history. Never reset main. Never merge. Never deploy.

### 15.2 Abort mid-job (before push)

1. Stop Codex child if running.
2. Release locks.
3. Mark ledger failed/cancelled.
4. Retain worktree for Scotty inventory; Will decides cleanup.

### 15.3 Bad or unwanted branch push (post-push, before PR)

1. Release locks if still held.
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

If canary/DISPATCHER_STATUS.md seed must be reverted: only via normal reviewed PR — never history rewrite; never direct main edit from dispatcher.

### 15.6 Credential / W9 incident rollback

If deploy key suspected compromised: Will-approved revoke/rotate (W11); Scotty updates fingerprints in backups; dispatcher config points to new key; old key destroyed.
W9 cloudflare material: follow dextech#3 — validate without displaying contents; rotate/revoke; remove safely; ignore + secret-scanning; history rewrite only as separately proposed/approved work.

### 15.7 ROLLBACK checklist (summary)

| Step | Action |
|---|---|
| 1 | Release SecureProcessLock pair |
| 2 | Stop child processes |
| 3 | Ledger → failed/cancelled |
| 4 | Retain worktree/audit (no auto delete) |
| 5 | If branch pushed → leave branch; optional human delete after Will |
| 6 | If draft PR exists → close without merge after Will |
| 7 | Never rewrite history; never reset main; never auto-merge/deploy |
| 8 | Revert seed only via reviewed PR if needed |
| 9 | Picard notifies Will; Scotty inventories remnants |

---

## 16. Exact proposed permissions appendix

### 16.1 OS account and directories

| Object | Proposed |
|---|---|
| Dispatcher OS user | codex-dispatcher (non-root) |
| Group | As Scotty defines (dedicated group preferred) |
| Lock root /run/lock/codex-dispatcher/ | Owned by codex-dispatcher; mode 0700; provisioned at boot; not a symlink |
| Lock files (agent.lock, implementation.lock) | Owned by codex-dispatcher; mode 0600 |
| Worktree root /var/lib/codex-dispatcher/worktrees/ | Owned by codex-dispatcher; 0700; no world-writable |
| Audit root /var/lib/codex-dispatcher/audit/ | Owned by codex-dispatcher; 0700; no world-writable |
| Mirror root | Owned by codex-dispatcher (or read-only service account Scotty defines); not world-writable |
| Fail closed | Incorrect ownership, permissions, or symlinks → refuse; no /tmp or repo fallback |

### 16.2 Git / deploy key scopes

| Capability | Deploy key / git identity |
|---|---|
| Fetch | Read-only mirror fetch credential OR same deploy key with fetch |
| Push | Write to refs/heads/agent/canary/* only if platform allows; else write non-main + branch protection blocks main |
| Main / default branch push | Denied (repo rules + protection) |
| Repo admin | NO |
| Actions admin | NO |
| Secrets | NO |
| Environments | NO |
| Webhook admin | NO |
| Open / merge PRs | NO (deploy key cannot open PRs) |
| History-rewrite push | NO |

### 16.3 Dispatcher process must NOT have

- GITHUB_TOKEN
- gh auth / logged-in gh host state for API mutation
- GitHub App private key for API
- Repo admin / Actions / Secrets / Environments / webhook credentials
- Ability to merge or deploy
- World-writable lock/worktree/audit dirs
- Automatic delete authority over remote branches/worktrees
- CopyMoney credentials or lock paths

Dispatcher git remote: SSH only using the deploy key.

### 16.4 PR opening identity (P6 — not dispatcher)

Separate Grok GitHub bot or human with PR-write permission — not the deploy key; not embedded in the dispatcher process. Picard routes after branch push + evidence.

### 16.5 Backups (W11)

- Include: fingerprints, config hashes, logs, verification evidence, audit artifacts (redacted)
- Exclude: private keys, tokens, deploy key private material, cloudflare key/pem contents
- Credential create/rotate: Will approval required

---

## 17. Decision log + changelog rev1→rev2

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

### 17.2 Changelog rev1 → rev2

| Change | Rev1 | Rev2 |
|---|---|---|
| Stage header | DESIGN ONLY | DESIGN ONLY rev 2; Will decisions incorporated; Astra gate |
| W1-W11 | Open questions | All DECIDED (approve / amend / conditions) |
| P5 | Push branch + open draft PR | Push review branch + evidence only (NO PR by dispatcher) |
| P6 | Human stop | Picard routes Grok GitHub bot or human for draft PR |
| W2 credential | Deploy key or App; branch+PR write | Deploy key branch-only; no API credential in dispatcher |
| W3 lock | Proposed | Non-root ownership; 0700/0600; fail closed; no /tmp fallback |
| W4 cleanup | Ops TTL optional | No auto delete; locks still release |
| W7 path | Create or modify | Must exist as regular file; reject symlink; realpath; exact one-file diff |
| W8 enablement | Supervised required | Supervised one-shot; no daemon/polling |
| W9 | Adjacent note | BLOCKS OPS1 and CANARY1; F1-F5 ok after Astra |
| W10 | Draft PR on | Branch-only aligns W2 |
| Sequence | After Will approve | Design → Astra → F1-F5 → W9 → OPS1 → CANARY1 |
| Non-fire gate | Implicit | Explicit verification before CANARY1 |
| ROLLBACK | Not dedicated | Section 15 explicit ROLLBACK procedure |
| Permissions | Sketch | Section 16 exact proposed permissions appendix |
| Acceptance C8 | Draft PR | Branch-only + evidence; no dispatcher PR |
| New tests | — | C11-C18 (symlink, realpath, token absence, W9 gate, one-shot, non-fire) |

---

## 18. Hand-off (Picard → GitHub #14 / docs/design for Astra)

| Role | Action |
|---|---|
| Geordi | This rev 2 design pack (docs only) at /workspace/codex-dispatcher-design/TASK-F-AND-DEXTECH-CANARY.md |
| Picard | Publish to GitHub issue #14 and/or docs/design for Astra final review; collect any residual Will notes; do not authorize implementation until Astra + Will authorize F1+ |
| Astra | Final design review (branch-only P5, W9 gating, permissions, ROLLBACK, deploy non-fire) |
| Will | Authorize F1+ only after Astra; authorize OPS1/CANARY1 only after W9 resolved |
| Worf | Review implement PRs for fail-open/bypass; confirm ProcessLock/PR #20/CopyMoney untouched |
| OBrien | Implement F1-F5 only after Picard post-Astra/Will assignment |
| Scotty | Provision OPS1 only after W9 resolved + Will; own backups per W11; inventory worktrees (no auto delete) |

**Status:** DESIGN ONLY rev 2 complete for Astra final review — no implementation started; no dispatcher run; no provisioning; CopyMoney untouched.

**Return path:** Geordi → Picard → Astra → Will → (F1-F5) → (W9) → OPS1 → supervised CANARY1.

**Prerequisite SHAs (unchanged):** main `7358bc4292bad1a21d3c74a9083dcedd8e6d0c94`; tree `54f61c4af20bec3e4f76be6587265b08f41a23cb`.

