# nvnm-cite

Citation existence verification and filing receipts on [NVNM Chain](https://docs.nvnmchain.io).

A per-jurisdiction registry of canonical US case citations stored in plaintext on NVNM Chain, plus a verifier that extracts citations from a legal brief, checks them against the registries, and anchors a verification receipt on chain at filing time. The receipt binds a document hash to the citation list, the registry state consulted, the per-citation results, and the verifying agent's identity.

It never asserts that a case supports a proposition or is good law. It proves the check happened, against what, and by whom. Provenance, not truth.

**Status:** bootstrap complete (2026-06-10). Phase 0 (signer + precompile characterization) is next. See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Working on this project (the multi-session protocol)

This project is built across many Claude Code sessions. All state lives in three repo files: `CLAUDE.md` (rules), `IMPLEMENTATION_PLAN.md` (position), `DECISIONS.md` (memory). Git history is the session log.

To continue work, open a Claude Code session **on this folder** and paste:

```
Read CLAUDE.md, IMPLEMENTATION_PLAN.md, and DECISIONS.md. Then tell me:
(1) the current phase and last completed task, (2) the next 1-3 unchecked
tasks, (3) any constraint from DECISIONS.md that bears on them. Propose a
plan for this session and wait for my OK before writing code or sending
any transaction.
```

End every session by saying "wrap up". The ritual in CLAUDE.md then updates the state files, commits, and pushes without further prompting.

Session cadence: **one phase per session**. Open a fresh session at each phase boundary; tasks within the same phase continue in the same session, even a long one (the auto-summarized context plus these state files carry the thread).

Two phases deserve an extra line pasted after the kickoff prompt: Phase 0 (paste the experiment matrix (a)-(i) from the plan so nothing gets silently skipped) and the Phase 2 bulk-load (paste the tranche scope and budget numbers from DECISIONS.md). Before any chain transaction is sent, the session must present its plan and get an explicit OK.

## Setup

1. [uv](https://docs.astral.sh/uv/) manages the environment (`uv sync`, `uv run pytest`).
2. Copy `.env.example` to `.env` and fill in the values yourself. Never paste keys into chat; never commit `.env`.
3. All development runs against NVNM **testnet** (chain id 787111). Mainnet is never written from a session.

## Data attribution

Case data comes from [CourtListener](https://www.courtlistener.com), a project of the [Free Law Project](https://free.law). Citation parsing builds on Free Law Project's eyecite, reporters-db, and courts-db.

## Layout

- `src/nvnm_cite/chain/anchoring.json`: vendored NVNM anchoring precompile ABI (5 methods, from the NVNM_MCP_Server project)
- `src/nvnm_cite/`: the package (`chain/`, `normalizer/`, `loader/`, `verifier/`, `receipts/` land phase by phase)
- `tests/`: pytest suites; `tests/golden/` holds the signer and normalizer contracts
- `docs/`: `canonical-citation-spec.md` and `record-schema.md` (Phase 1); `docs/ARCHIVE/` for superseded plans
