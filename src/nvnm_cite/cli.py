"""``nvnm-cite`` command-line tool.

Phase 3 ships the ``check`` command: read a brief, find its citations, and
check each one against NVNM Chain LIVE (item 0). The verification logic is
the shared ``nvnm_cite.verifier`` core — the same code the web app calls —
so there is one normalizer and one set of statuses everywhere. Later phases
extend this subcommand scaffold (anchor, verify, sync, rebuild-index,
reconcile, stats, load — plan task 4.5).

Read-only: ``check`` makes ``eth_call`` reads only. It never writes to the
chain and spends no gas.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sqlite3
import sys
from pathlib import Path

from nvnm_cite.chain.rpc import EvmRpc, RpcError
from nvnm_cite.chain.secp256k1 import address_from_private_key
from nvnm_cite.config import TESTNET_EXPLORER, load_dotenv, testnet_private_key, testnet_rpc
from nvnm_cite.receipts.anchor import prepare_anchor
from nvnm_cite.receipts.anchor import send as anchor_send
from nvnm_cite.receipts.schema import ReceiptError
from nvnm_cite.receipts.verify import VERIFIED as VERIFY_OK
from nvnm_cite.receipts.verify import verify_document
from nvnm_cite.verifier.check import (
    AMBIGUOUS,
    NOT_COVERED,
    NOT_FOUND,
    STATUS_ORDER,
    UNPARSEABLE,
    VERIFIED,
    CheckError,
    check_document,
)
from nvnm_cite.verifier.resolver import ChainResolver

# Terminal labels for the locked statuses (the report keeps the enum values).
_STATUS_LABEL = {
    VERIFIED: "VERIFIED",
    NOT_FOUND: "NOT FOUND",
    NOT_COVERED: "NOT COVERED",
    AMBIGUOUS: "AMBIGUOUS",
    UNPARSEABLE: "UNPARSEABLE",
}
_SUMMARY_LABEL = {
    VERIFIED: "verified",
    NOT_FOUND: "not found",
    NOT_COVERED: "not covered",
    AMBIGUOUS: "ambiguous",
    UNPARSEABLE: "unparseable",
}


def _truncate(text: str, width: int) -> str:
    text = text or ""
    return text if len(text) <= width else text[: width - 1] + "…"


def _render(report: dict) -> str:
    doc = report["document"]
    cov = report["coverage"]
    lines: list[str] = []
    lines.append(f"nvnm-cite check — {doc['filename']}")
    lines.append(f"  SHA-256:    {doc['sha256']}")
    extraction = doc["extraction"]
    lines.append(
        f"  Extraction: {extraction['method']} · {extraction['chars']:,} characters"
    )
    if extraction.get("warning"):
        lines.append(f"  ⚠ {extraction['warning']}")
    lines.append(f"  Checked against: {cov['source']} — {', '.join(cov['covered'])}")
    lines.append("")

    citations = report["citations"]
    if not citations:
        lines.append("  No citations found in this document.")
    else:
        rows = []
        for c in citations:
            cite = c["canonical"] or c["as_written"]
            if c["status"] == VERIFIED and c["record"] and c["record"]["cases"]:
                primary = c["record"]["cases"][0]
                note = primary.get("name", "") or "(unnamed)"
                if primary.get("year"):
                    note += f" ({primary['year']})"
                extra = c["record"]["more_cases"]
                if extra:
                    note += f"  +{extra} more"
            else:
                note = c["reason"] or ""
            nm = {"match": "match", "mismatch": "MISMATCH"}.get(c["name_check"], "")
            rows.append(
                (
                    _STATUS_LABEL[c["status"]],
                    _truncate(cite, 22),
                    _truncate(note, 46),
                    nm,
                    f"{c['occurrences']}×",
                )
            )
        headers = ("STATUS", "CITATION", "CASE ON CHAIN / NOTE", "NAME", "OCC")
        widths = [
            max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))
        ]
        fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
        lines.append(fmt.format(*headers))
        lines.append("  " + "─" * (sum(widths) + 2 * (len(widths) - 1)))
        for r in rows:
            lines.append(fmt.format(*r))

    lines.append("")
    summary = report["summary"]
    parts = [
        f"{summary['by_status'][s]} {_SUMMARY_LABEL[s]}"
        for s in STATUS_ORDER
        if summary["by_status"][s]
    ]
    lines.append("  Summary: " + (" · ".join(parts) if parts else "no citations"))
    if summary["name_mismatches"]:
        lines.append(
            f"           {summary['name_mismatches']} party-name mismatch"
            f"{'es' if summary['name_mismatches'] > 1 else ''} "
            "(a real citation paired with a different case name)"
        )
    lines.append(
        f"  {summary['occurrences']} citation occurrence"
        f"{'s' if summary['occurrences'] != 1 else ''}, {summary['distinct']} distinct."
    )
    lines.append("")
    lines.append(
        "  Existence only: a match means the citation EXISTS on chain, not that the\n"
        "  case is good law or supports any proposition. Each VERIFIED/NOT FOUND result\n"
        "  is a live records() read you can replay against any NVNM RPC (see --json)."
    )
    return "\n".join(lines)


def cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    load_dotenv()
    rpc_url = args.rpc or testnet_rpc()
    resolver = ChainResolver(lambda: EvmRpc(rpc_url), block=args.block)

    try:
        report = check_document(data, path.name, resolver)
    except CheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (RpcError, OSError) as exc:
        # A keyed miss is handled inside the resolver as NOT_FOUND; reaching
        # here means the chain itself was unreachable or errored. We do NOT
        # pretend the citations are absent.
        print(
            f"error: could not reach NVNM Chain at {rpc_url} ({exc}). "
            "The check makes live reads; no verdict is produced when the chain "
            "is unreachable.",
            file=sys.stderr,
        )
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render(report))
    return 0


def _render_anchor_plan(plan) -> str:
    lines = [_render(plan.report), "", "  ── Receipt to anchor ──"]
    note = "" if plan.registry_exists else "  (will be CREATED — your wallet becomes its admin)"
    lines.append(f"  Registry:   {plan.registry}{note}")
    lines.append(f"  Document:   {plan.document_sha256}")
    lines.append(f"  At block:   {plan.checked_at_block:,}")
    lines.append(f"  Receipt:    {len(plan.receipt_json.encode('utf-8'))} bytes (cap 2048)")
    tally = ", ".join(f"{k}={v}" for k, v in plan.receipt["summary"].items())
    lines.append(f"  Tally:      {tally}")
    lines.append("")
    lines.append("  Receipt JSON (the on-chain record metadata):")
    lines.append(f"    {plan.receipt_json}")
    lines.append("")
    lines.append(f"  Transactions to send ({plan.writes}):")
    step = 1
    if plan.create_registry:
        lines.append(f"    {step}. addRegistry  {plan.create_registry['name']}")
        step += 1
    lines.append(f"    {step}. addRecord    receipt → {plan.registry}")
    if plan.already_anchored:
        lines.append("")
        lines.append("  ⚠ This document is ALREADY anchored here; re-anchoring adds a version (use --force).")
    return "\n".join(lines)


def _render_sent(sent: list[dict]) -> str:
    lines = ["", "  ── Anchored on NVNM Chain ──"]
    for s in sent:
        status = "ok" if s["ok"] else "FAILED"
        lines.append(f"  {s['label']}: {s['tx_hash']}")
        lines.append(f"     block {s['block']:,} · gas {s['gas_used']:,} · {status}")
        lines.append(f"     {TESTNET_EXPLORER}/tx/{s['tx_hash']}")
    return "\n".join(lines)


_VERDICT_LABEL = {
    "verified": "VERIFIED — receipt found, document unchanged, recheck reproduces the tally",
    "summary_drift": "FOUND, BUT THE TALLY DIFFERS — investigate",
    "found": "FOUND (could not recompute)",
    "not_found": "NO RECEIPT — the file matches no receipt here (altered, or never anchored)",
    "registry_not_found": "REGISTRY NOT FOUND — check the link printed on the filing",
    "bad_receipt": "A RECORD EXISTS but it is not a valid receipt",
}


def _render_verify(result) -> str:
    lines = [f"nvnm-cite verify — registry {result.registry}"]
    lines.append(f"  Document SHA-256: {result.document_sha256}")
    lines.append(f"  Result: {_VERDICT_LABEL.get(result.verdict, result.verdict)}")
    if result.found and result.receipt:
        r = result.receipt
        lines.append(f"  Anchored by:      {r.get('agent', {}).get('address', '?')}")
        if result.checked_at_block is not None:
            lines.append(f"  Checked at block: {result.checked_at_block:,}  ·  receipt time {r.get('timestamp', '?')}")
        stored = ", ".join(f"{k}={v}" for k, v in (r.get("summary") or {}).items())
        lines.append(f"  Stored tally:     {stored}")
        if result.recomputed_summary is not None:
            recomputed = ", ".join(f"{k}={v}" for k, v in result.recomputed_summary.items())
            lines.append(f"  Recomputed:       {recomputed}  ({'matches' if result.summary_matches else 'DIFFERS'})")
    for note in result.notes:
        lines.append(f"  • {note}")
    lines.append("")
    lines.append(f"  Replay: eth_call records({result.registry}, <sha256>) against any NVNM RPC (see --json).")
    return "\n".join(lines)


def cmd_anchor(args: argparse.Namespace) -> int:
    path = Path(args.path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    load_dotenv()
    rpc_url = args.rpc or testnet_rpc()
    rpc_factory = lambda: EvmRpc(rpc_url)  # noqa: E731

    key: int | None = None
    if args.agent:
        agent_address = args.agent
    else:
        try:
            key = testnet_private_key()
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        agent_address = address_from_private_key(key)

    try:
        plan = prepare_anchor(
            data, path.name, firm=args.firm, case=args.case,
            agent_address=agent_address, rpc_factory=rpc_factory,
        )
    except (ReceiptError, CheckError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (RpcError, OSError) as exc:
        print(f"error: could not reach NVNM Chain at {rpc_url} ({exc})", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(plan.to_display(), ensure_ascii=False, indent=2))
    else:
        print(_render_anchor_plan(plan))

    if not args.anchor:
        if not args.json:
            print("\n  Dry run — nothing was sent. Re-run with --anchor to write to the chain.")
        return 0

    if plan.already_anchored and not args.force:
        print("\n  Already anchored; not re-sending (use --force to add a new version).", file=sys.stderr)
        return 0

    if key is None:  # --agent was given without a matching key
        try:
            key = testnet_private_key()
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if address_from_private_key(key).lower() != agent_address.lower():
        print("error: the configured signing key does not match --agent", file=sys.stderr)
        return 2

    try:
        sent = anchor_send(plan, EvmRpc(rpc_url), key)
    except (RpcError, OSError) as exc:
        print(f"error: anchoring failed ({exc})", file=sys.stderr)
        return 2
    print(_render_sent(sent))
    return 0 if all(s["ok"] for s in sent) else 1


def cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2

    load_dotenv()
    rpc_url = args.rpc or testnet_rpc()
    rpc_factory = lambda: EvmRpc(rpc_url)  # noqa: E731

    try:
        result = verify_document(data, path.name, registry=args.registry, rpc_factory=rpc_factory)
    except (RpcError, OSError) as exc:
        print(f"error: could not reach NVNM Chain at {rpc_url} ({exc})", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
    else:
        print(_render_verify(result))
    return 0 if result.verdict == VERIFY_OK else 1


def _render_stats(payload: dict) -> str:
    lines = [f"nvnm-cite stats — {payload['db']}", f"  Source: {payload['source']}", ""]
    regs = payload["registries"]
    if not regs:
        lines.append("  (no synced registries yet — run sync or rebuild-index)")
        return "\n".join(lines)
    rows = [
        (reg, f"{d['records']:,}", f"{d['synced_block']:,}", d["synced_at"] or "?")
        for reg, d in regs.items()
    ]
    headers = ("REGISTRY", "RECORDS", "SYNCED BLOCK", "SYNCED AT")
    widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(4)]
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    lines.append(fmt.format(*headers))
    lines.append("  " + "─" * (sum(widths) + 6))
    for r in rows:
        lines.append(fmt.format(*r))
    lines.append("")
    lines.append(f"  Total: {payload['total_records']:,} records across {len(regs)} registries.")
    lines.append("  Counts are from the local index at the stated sync head, not the chain's countTotal (unreliable).")
    return "\n".join(lines)


def cmd_stats(args: argparse.Namespace) -> int:
    from nvnm_cite.chain.indexer import index_stats

    db = Path(args.db)
    if not db.is_file():
        print(
            f"error: no chain index at {db}; run 'nvnm-cite sync --registries …' or "
            "'nvnm-cite rebuild-index --registries …' first",
            file=sys.stderr,
        )
        return 2
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        stats = index_stats(conn)
        synced_at = dict(conn.execute("SELECT registry, synced_at FROM sync_state"))
    finally:
        conn.close()
    payload = {
        "db": str(db),
        "source": "local chain index (rebuildable audit cache via rebuild-index)",
        "registries": {
            reg: {"records": latest, "versions": total, "synced_block": head, "synced_at": synced_at.get(reg)}
            for reg, (latest, total, head) in sorted(stats.items())
        },
        "total_records": sum(latest for latest, _, _ in stats.values()),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render_stats(payload))
    return 0


# Operator commands delegate to their existing module CLIs (no logic
# duplication). They are intercepted before argparse, so `nvnm-cite sync --help`
# shows the indexer's own flags; `nvnm-cite --help` lists them in the epilog.
_DELEGATED = {"sync", "rebuild-index", "reconcile", "load", "update"}


def _delegate(argv: list[str]) -> int:
    cmd, rest = argv[0], argv[1:]
    if cmd in ("sync", "rebuild-index"):
        from nvnm_cite.chain import indexer

        return indexer.main([cmd, *rest])
    if cmd == "reconcile":
        from nvnm_cite.loader import reconcile

        return reconcile.main(rest)
    if cmd == "load":
        from nvnm_cite.loader import bulk_load

        return bulk_load.main(rest)
    if cmd == "update":
        from nvnm_cite.loader import update

        return update.main(rest)
    raise AssertionError(cmd)  # pragma: no cover


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nvnm-cite",
        description="Citation existence verification on NVNM Chain (provenance, not truth).",
        epilog=(
            "operator commands (run '<cmd> --help' for flags):\n"
            "  sync, rebuild-index   build/refresh the local chain index\n"
            "  reconcile             diff the load state against the chain index\n"
            "  load                  checkpointed bulk loader (prepare|run|status)\n"
            "  update                daily incremental corpus updater"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser(
        "check",
        help="check a document's citations against NVNM Chain (live, read-only)",
        description=(
            "Extract citations from a brief (.pdf, .docx, .txt) and check each "
            "against NVNM Chain with a live keyed records() read. Read-only: no "
            "chain writes, no gas."
        ),
    )
    check.add_argument("path", help="path to the document (.pdf, .docx, .txt, .md)")
    check.add_argument(
        "--rpc",
        default=None,
        help="EVM RPC URL (default: NVNM_TESTNET_RPC or the public testnet RPC)",
    )
    check.add_argument(
        "--block",
        default="latest",
        help="block tag for the reads (default: latest)",
    )
    check.add_argument("--json", action="store_true", help="emit the full JSON report")
    check.set_defaults(func=cmd_check)

    anchor = sub.add_parser(
        "anchor",
        help="anchor a filing receipt to a per-firm-per-case registry (WRITES to the chain)",
        description=(
            "Check a document, then record a minimal, non-enumerating receipt on "
            "NVNM Chain. Without --anchor this is a dry run that only shows the plan; "
            "with --anchor it sends the transaction(s), signing with NVNM_TESTNET_KEY."
        ),
    )
    anchor.add_argument("path", help="path to the document (.pdf, .docx, .txt, .md)")
    anchor.add_argument("--firm", required=True, help="filing firm/party label (part of the registry name)")
    anchor.add_argument("--case", required=True, help="case/matter label (part of the registry name)")
    anchor.add_argument("--agent", default=None, help="attesting wallet address (default: derived from NVNM_TESTNET_KEY)")
    anchor.add_argument("--rpc", default=None, help="EVM RPC URL (default: NVNM_TESTNET_RPC or the public testnet RPC)")
    anchor.add_argument("--anchor", action="store_true", help="actually send the transaction(s) (default: dry-run plan only)")
    anchor.add_argument("--force", action="store_true", help="re-anchor even if this document already has a receipt (adds a version)")
    anchor.add_argument("--json", action="store_true", help="emit the plan as JSON")
    anchor.set_defaults(func=cmd_anchor)

    verify = sub.add_parser(
        "verify",
        help="verify a filing receipt from (registry + file), read-only",
        description=(
            "Given the original file and the receipt registry from a filing's "
            "verification link, confirm a receipt exists for this exact document and "
            "re-run the check pinned to the receipt's block. Read-only."
        ),
    )
    verify.add_argument("path", help="path to the original document")
    verify.add_argument("--registry", required=True, help="receipt registry name from the filing's verification link")
    verify.add_argument("--rpc", default=None, help="EVM RPC URL (default: NVNM_TESTNET_RPC or the public testnet RPC)")
    verify.add_argument("--json", action="store_true", help="emit the full JSON result")
    verify.set_defaults(func=cmd_verify)

    stats = sub.add_parser(
        "stats",
        help="local index coverage (records per registry at the sync head)",
        description=(
            "Report records per registry from the local chain index, with its sync head "
            "stated. Read-only; counts come from the rebuildable local cache, never the "
            "chain's countTotal (unreliable per experiment 0.7(g))."
        ),
    )
    stats.add_argument("--db", default="data/chain_index.sqlite", help="chain index path")
    stats.add_argument("--json", action="store_true", help="emit JSON")
    stats.set_defaults(func=cmd_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _DELEGATED:
        return _delegate(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
