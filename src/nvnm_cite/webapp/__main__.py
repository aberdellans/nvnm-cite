"""Run the web demo: ``uv run python -m nvnm_cite.webapp``"""

from __future__ import annotations

import argparse
from pathlib import Path

from nvnm_cite.config import load_dotenv, testnet_rpc
from nvnm_cite.webapp.server import build_server


def main() -> None:
    parser = argparse.ArgumentParser(description="nvnm-cite web demo server")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787, help="port (default 8787)")
    parser.add_argument("--rpc", default=None, help="EVM RPC URL (default: NVNM_TESTNET_RPC or the public testnet RPC)")
    parser.add_argument("--data-dir", default="data", help="directory holding corpus.sqlite / chain_index.sqlite")
    parser.add_argument(
        "--telemetry",
        default=None,
        metavar="PATH",
        help="opt in to aggregate by-citation query telemetry, written to this SQLite "
        "path (off by default; counts only, never the document or who asked — item 2b)",
    )
    args = parser.parse_args()

    load_dotenv()
    rpc_url = args.rpc or testnet_rpc()
    data_dir = Path(args.data_dir)
    telemetry_path = Path(args.telemetry) if args.telemetry else None

    server = build_server(args.host, args.port, rpc_url, data_dir, telemetry_path=telemetry_path)
    print(f"nvnm-cite web demo: http://{args.host}:{args.port}/")
    print(f"  RPC: {rpc_url} (chain 787111, NVNM testnet)")
    print(f"  data: {data_dir.resolve()}")
    print("  uploads are processed in memory and discarded with the response;")
    print("  drafting checks read NVNM Chain live (item 0) — point-to-point, never published")
    if telemetry_path:
        print(f"  telemetry: ON — aggregate by-citation counts at {telemetry_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        server.shutdown()


if __name__ == "__main__":
    main()
