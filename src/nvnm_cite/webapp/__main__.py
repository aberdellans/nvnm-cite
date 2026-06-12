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
    args = parser.parse_args()

    load_dotenv()
    rpc_url = args.rpc or testnet_rpc()
    data_dir = Path(args.data_dir)

    server = build_server(args.host, args.port, rpc_url, data_dir)
    print(f"nvnm-cite web demo: http://{args.host}:{args.port}/")
    print(f"  RPC: {rpc_url} (chain 787111, NVNM testnet)")
    print(f"  data: {data_dir.resolve()}")
    print("  uploads are processed in memory; drafting-time checks make no RPC calls")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        server.shutdown()


if __name__ == "__main__":
    main()
