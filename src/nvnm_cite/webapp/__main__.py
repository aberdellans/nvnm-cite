"""Run the web app: ``uv run python -m nvnm_cite.webapp``"""

from __future__ import annotations

import argparse
import signal
from pathlib import Path

from nvnm_cite.config import get_network, load_dotenv
from nvnm_cite.webapp.server import build_server


def main() -> None:
    parser = argparse.ArgumentParser(description="nvnm-cite web server")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787, help="port (default 8787)")
    parser.add_argument(
        "--network",
        choices=["mainnet", "testnet"],
        default=None,
        help="which NVNM Chain network to serve against (default: mainnet, or NVNM_NETWORK)",
    )
    parser.add_argument("--rpc", default=None, help="EVM RPC URL (default: the selected network's)")
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
    network = get_network(args.network)
    rpc_url = args.rpc or network.rpc_url()
    data_dir = Path(args.data_dir)
    telemetry_path = Path(args.telemetry) if args.telemetry else None

    server = build_server(
        args.host, args.port, network, rpc_url, data_dir, telemetry_path=telemetry_path
    )
    print(f"nvnm-cite web: http://{args.host}:{args.port}/")
    print(f"  network: {network.label} (chain {network.chain_id})")
    print(f"  RPC: {rpc_url}")
    print(f"  data: {data_dir.resolve()}")
    print("  uploads are processed in memory and discarded with the response;")
    print("  drafting checks read NVNM Chain live (item 0) — point-to-point, never published")
    if telemetry_path:
        print(f"  telemetry: ON — aggregate by-citation counts at {telemetry_path}")
    # Container runtimes stop with SIGTERM, which would otherwise kill the
    # process mid-request; route it onto the same clean path as Ctrl-C.
    def _terminate(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        server.shutdown()


if __name__ == "__main__":
    main()
