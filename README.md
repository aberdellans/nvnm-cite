# nvnm-cite

Citation existence verification and filing receipts on [NVNM Chain](https://docs.nvnmchain.io).

A per-jurisdiction registry of canonical US case citations stored in plaintext on NVNM Chain, plus a verifier that extracts citations from a legal brief, checks each one against the chain live, and anchors a verification receipt at filing time. The receipt binds the document's SHA-256 to the chain state consulted, a non-identifying status tally, and the attesting wallet — never the list of cited cases, so a brief's authorities are not published on chain.

It never asserts that a case supports a proposition or is good law. It proves the check happened, against what, and by whom. Provenance, not truth.

**Status:** MAINNET is live — the full corpus (2,114 US court registries, 11.94M citation records, registry ids 69–2182) is on NVNM Chain mainnet (1611), and the codebase runs the anchoring v1.2.0 id-keyed interface (registry names are not unique on chain; the pinned manifests in `src/nvnm_cite/chain/` are the name→id trust anchor). The webapp is the production surface (`uv run python -m nvnm_cite.webapp`, mainnet by default) and the `nvnm-cite` CLI does `check | anchor | verify | stats | manifest-verify` (plus operator commands), reading the chain live. Receipts anchor to per-firm-per-case registries via a two-step create→anchor flow whose discovery line carries the registry #id. Pilot history (phases 0–4.5, testnet) is tagged `phase-0-done` … `phase-4-done`. See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) and DECISIONS 2026-07-31.

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
3. Chain WRITES from development run against NVNM **testnet** (chain id 787111) only; reads default to **mainnet** (chain id 1611), which now holds the full 2,114-registry corpus. Mainnet is never written from a session (`config.signing_context` enforces it).

## Web demo

`uv run python -m nvnm_cite.webapp` serves a lawyer-facing page at
http://127.0.0.1:8787 — check a brief's citations (local, nothing leaves the
machine), anchor a filing receipt with your own wallet, verify a document
hash for free, and decode anchoring transactions to readable plaintext.
Details and the privacy model: [docs/web-demo.md](docs/web-demo.md).

## Deployment

The public instance runs the Docker image `ghcr.io/nvnm-chain/nvnm-cite`,
built and smoke-tested by [CI](.github/workflows/ci.yml) from this repo
(linux/amd64 + linux/arm64). One stateless container, no database, no
server-side keys; TLS and the domain live at the ingress. Ops details —
health checks, ingress requirements, Kubernetes notes:
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Data attribution

Case data comes from [CourtListener](https://www.courtlistener.com), a project of the [Free Law Project](https://free.law). Citation parsing builds on Free Law Project's eyecite, reporters-db, and courts-db.

## Layout

- `src/nvnm_cite/`: the package (`chain/`, `normalizer/`, `loader/`, `verifier/`, `receipts/`, `webapp/`)
- `src/nvnm_cite/chain/anchoring.json`: vendored NVNM anchoring precompile ABI (v1.2.0, functions + events)
- `src/nvnm_cite/webapp/static/`: the web UI plus the agent-facing docs served at the site root (`llms.txt`, `agents.md`, `openapi.json`)
- `tests/`: pytest suites; `tests/golden/` holds the signer and normalizer contracts
- `scripts/`: operator tools (registry-manifest and reporter-map builders)
- `docs/`: `canonical-citation-spec.md`, `record-schema.md`, `web-demo.md`, `brief-for-firms.md`; `docs/ARCHIVE/` for superseded plans and historical material
