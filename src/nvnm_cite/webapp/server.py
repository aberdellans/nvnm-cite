"""Stdlib HTTP server for the web demo. No frameworks, no new deps.

Privacy posture, enforced here: request bodies are never logged (the
access log carries method + path without query strings + status only),
uploads are read into memory, handed to the service, and fall out of
scope with the request. The server binds 127.0.0.1 unless told
otherwise.
"""

from __future__ import annotations

import json
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from nvnm_cite.chain.registrymap import load_manifest
from nvnm_cite.chain.rpc import EvmRpc, RpcError
from nvnm_cite.config import Network
from nvnm_cite.verifier.resolver import ChainResolver
from nvnm_cite.verifier.telemetry import SqliteTelemetry
from nvnm_cite.webapp.localindex import LocalIndex
from nvnm_cite.webapp.service import (
    ChainGateway,
    CheckService,
    ReceiptService,
    StatusService,
    TxService,
    WebAppError,
)

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_JSON_BYTES = 1 * 1024 * 1024
# The status panel must fail fast on a dead/slow RPC (task 4.5e): a short
# timeout, distinct from the default the check path uses.
STATUS_RPC_TIMEOUT = 4.0
# Interactive receipt/tx/lookup paths (prepare re-check, anchor confirmation
# polling, verify lookup) use a moderate timeout so a slow public RPC surfaces a
# retryable error in seconds instead of freezing the flow for the 30 s default.
INTERACTIVE_RPC_TIMEOUT = 12.0

_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",  # vendored font licenses, llms.txt, robots.txt
    ".json": "application/json; charset=utf-8",  # openapi.json (agent-facing API contract)
    ".md": "text/markdown; charset=utf-8",  # agents.md (agent-facing tutorial)
}
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "form-action 'none'; base-uri 'none'; frame-ancestors 'none'"
)


class Services:
    def __init__(
        self,
        network: Network,
        rpc_url: str,
        data_dir: Path,
        telemetry_path: Path | None = None,
    ):
        self.network = network
        self.rpc_url = rpc_url
        index = LocalIndex(data_dir)  # status panel only; not the check authority
        # The pinned name->id manifest: coverage AND the trust anchor for
        # court-registry resolution (names are non-unique under v1.2.0).
        manifest = load_manifest(network.key)
        registry_ids = manifest.all_registries()
        # Fail fast on a network/manifest mismatch rather than serving wrong ids.
        if manifest.chain_id != network.chain_id:
            raise RuntimeError(
                f"manifest chain_id {manifest.chain_id} != network {network.chain_id}"
            )
        # Receipt prepare/lookup + tx polling go through this gateway; a moderate
        # timeout keeps a slow RPC from freezing the anchor flow.
        gateway = ChainGateway(lambda: EvmRpc(rpc_url, timeout=INTERACTIVE_RPC_TIMEOUT))
        # Opt-in aggregate, by-citation lookup telemetry (item 2b): off unless
        # the operator passes --telemetry. One shared sink (thread-safe) feeds
        # the drafting-time check resolver; disclosed in the privacy copy.
        self.telemetry = SqliteTelemetry(telemetry_path) if telemetry_path else None
        # Drafting checks read the chain LIVE (item 0): a fresh EvmRpc per call
        # keeps the resolver safe under the threaded server.
        self.check = CheckService(
            ChainResolver(lambda: EvmRpc(rpc_url), telemetry=self.telemetry),
            registry_ids,
        )
        self.receipt = ReceiptService(gateway, network, registry_ids)
        self.tx = TxService(gateway, network)
        # The status panel probes through a SHORT-timeout gateway so a dead or
        # slow RPC fails fast instead of stalling page load (task 4.5e).
        status_gateway = ChainGateway(lambda: EvmRpc(rpc_url, timeout=STATUS_RPC_TIMEOUT))
        self.status = StatusService(
            status_gateway, index, data_dir, network, manifest, rpc_url=rpc_url,
            telemetry_enabled=telemetry_path is not None,
        )


class Handler(BaseHTTPRequestHandler):
    services: Services  # injected by build_server
    protocol_version = "HTTP/1.1"
    server_version = "nvnm-cite-web/0.2.0"

    # --- plumbing ---

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        path = self.path.split("?", 1)[0]
        sys.stderr.write(f"{self.address_string()} {self.command} {path} {args[-1] if args else ''}\n")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int) -> None:
        self._send_json({"error": message}, status=status)

    def _read_body(self, cap: int) -> bytes | None:
        length = self.headers.get("Content-Length")
        if length is None:
            self._send_error_json("Content-Length required", 411)
            return None
        try:
            n = int(length)
        except ValueError:
            self._send_error_json("bad Content-Length", 400)
            return None
        if n > cap:
            self._send_error_json(f"body too large (max {cap // (1024 * 1024)} MB)", 413)
            return None
        return self.rfile.read(n)

    def _serve_static(self, name: str) -> None:
        # Whitelisted flat filenames only: no path handling, no traversal.
        if "/" in name or name.startswith("."):
            self._send_error_json("not found", 404)
            return
        root = resources.files("nvnm_cite.webapp").joinpath("static")
        candidate = root.joinpath(name)
        suffix = Path(name).suffix
        if suffix not in _STATIC_TYPES or not candidate.is_file():
            self._send_error_json("not found", 404)
            return
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _STATIC_TYPES[suffix])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if suffix == ".html":
            self.send_header("Content-Security-Policy", _CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    # --- routes ---

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if route in ("/", "/index.html"):
                self._serve_static("index.html")
            elif route.startswith("/api/"):
                self._get_api(route, query)
            else:
                self._serve_static(route.lstrip("/"))
        except WebAppError as err:
            self._send_error_json(str(err), err.http_status)
        except RpcError as err:
            self._send_error_json(f"chain RPC error: {err}", 502)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError as err:
            # Transport failure reaching the chain RPC (connection refused,
            # timeout, ...): surface it; a dead RPC is never a chain answer.
            self._send_error_json(f"could not reach the chain RPC: {err}", 502)
        except Exception:
            traceback.print_exc()
            self._send_error_json("internal error", 500)

    def _get_api(self, route: str, query: dict[str, list[str]]) -> None:
        if route == "/api/status":
            self._send_json(self.services.status.status())
        elif route == "/api/receipt/lookup":
            registry = (query.get("registry") or [""])[0]
            sha = (query.get("sha256") or [""])[0]
            self._send_json(self.services.receipt.lookup(registry, sha))
        elif route == "/api/receipt/registries":
            creator = (query.get("creator") or [""])[0]
            self._send_json(self.services.receipt.registries_for_creator(creator))
        elif route == "/api/tx":
            tx_hash = (query.get("hash") or [""])[0]
            self._send_json(self.services.tx.inspect(tx_hash))
        else:
            self._send_error_json("not found", 404)

    def do_POST(self) -> None:  # noqa: N802
        route = urllib.parse.urlparse(self.path).path
        try:
            if route == "/api/check":
                body = self._read_body(MAX_UPLOAD_BYTES)
                if body is None:
                    return
                filename = urllib.parse.unquote(self.headers.get("X-Filename", "upload"))
                self._send_json(self.services.check.check(body, filename))
            elif route == "/api/receipt/prepare":
                # The receipt re-checks the EXACT bytes pinned to a block, so
                # the document is re-uploaded here (parsed in memory, discarded
                # with the response — same posture as /api/check). The filer/
                # case labels name the per-firm-per-case registry; the agent is
                # the connected wallet. All travel as headers alongside the body.
                body = self._read_body(MAX_UPLOAD_BYTES)
                if body is None:
                    return
                filename = urllib.parse.unquote(self.headers.get("X-Filename", "upload"))
                firm = urllib.parse.unquote(self.headers.get("X-Firm", ""))
                case = urllib.parse.unquote(self.headers.get("X-Case", ""))
                agent = urllib.parse.unquote(self.headers.get("X-Agent", ""))
                # X-Registry-Id pins the target receipts registry (set after
                # the setup tx confirms, or when the picker chose one). Absent
                # means: resolve by creator+name, or return the setup step.
                raw_id = self.headers.get("X-Registry-Id", "").strip()
                registry_id = int(raw_id) if raw_id.isdigit() else None
                self._send_json(
                    self.services.receipt.prepare(
                        body, filename, firm=firm, case=case, agent_address=agent,
                        registry_id=registry_id,
                    )
                )
            else:
                self._send_error_json("not found", 404)
        except WebAppError as err:
            self._send_error_json(str(err), err.http_status)
        except RpcError as err:
            self._send_error_json(f"chain RPC error: {err}", 502)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError as err:
            # Transport failure reaching the chain RPC (connection refused,
            # timeout, ...): surface it; a dead RPC is never a chain answer.
            self._send_error_json(f"could not reach the chain RPC: {err}", 502)
        except Exception:
            traceback.print_exc()
            self._send_error_json("internal error", 500)


def build_server(
    host: str,
    port: int,
    network: Network,
    rpc_url: str,
    data_dir: Path,
    telemetry_path: Path | None = None,
) -> ThreadingHTTPServer:
    services = Services(network, rpc_url, data_dir, telemetry_path=telemetry_path)
    handler = type("BoundHandler", (Handler,), {"services": services})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
