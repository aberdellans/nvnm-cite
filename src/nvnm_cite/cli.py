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
import json
import sys
from pathlib import Path

from nvnm_cite.chain.rpc import EvmRpc, RpcError
from nvnm_cite.config import load_dotenv, testnet_rpc
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nvnm-cite",
        description="Citation existence verification on NVNM Chain (provenance, not truth).",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
