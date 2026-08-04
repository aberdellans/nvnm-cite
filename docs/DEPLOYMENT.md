# Deploying NVNM Cite

Ops handoff for running the public instance (nvnmcite.com). The app is one
stateless container; NVNM Chain is the backend. Nothing here requires a
database, a volume, a secret, or a backup.

## Image

- `ghcr.io/nvnm-chain/nvnm-cite` — built and pushed by
  [.github/workflows/ci.yml](../.github/workflows/ci.yml). Every push to
  `main` publishes `latest` plus a `sha-<commit>` tag; `v*` git tags publish
  semver tags. Platforms: `linux/amd64` and `linux/arm64`.
- Before anything is pushed, CI runs the full test suite and a container
  smoke test: the image must boot, serve `/`, and report a reachable
  mainnet RPC, the right chain id, full manifest coverage, and telemetry off.
- The GHCR package is created under the NVNM-Chain org on first push and
  starts org-visible; an org admin can make it public or grant pull access.

Local run, no Kubernetes needed:

```bash
docker run --rm -p 8787:8787 ghcr.io/nvnm-chain/nvnm-cite:latest
```

## Runtime shape

- Single process: `python -m nvnm_cite.webapp --host 0.0.0.0 --port 8787
  --data-dir /app/data` (the image CMD). Container port **8787**, plain HTTP;
  TLS belongs to the ingress.
- Stateless. Uploads are parsed in memory and discarded with the response;
  nothing is persisted server-side.
- **No secrets.** The server never holds keys and never signs anything; the
  one write path (recording a filing receipt) is signed in the user's own
  browser wallet, with the user's own gas. Never mount a `.env` into it.
- Only runtime dependency: the public NVNM Chain mainnet RPC
  `https://evm.nvnmchain.io`. Chain reads are free. MANTRA knows this site
  reads their mainnet RPC.
- Runs as non-root (uid 10001) and handles SIGTERM with a clean shutdown.
  `readOnlyRootFilesystem` is fine; if enabled, mount an emptyDir at `/tmp`
  (PDF parsing may use it).
- `/app/data` is an optional read-only mount for a local index
  (`corpus.sqlite` / `chain_index.sqlite`). It only adds status-panel counts;
  the chain is always the lookup authority. The public instance runs without it.

## Configuration

All optional — the image defaults are the production configuration.

| Variable | Default | Notes |
|---|---|---|
| `NVNM_NETWORK` | `mainnet` | `testnet` runs an instance against NVNM testnet. |
| `NVNM_MAINNET_RPC` | `https://evm.nvnmchain.io` | RPC URL override. |

Telemetry (aggregate by-citation lookup counts) is **off** because the image
CMD passes no `--telemetry` flag. Leave it off; turning it on is a product
decision, not an ops setting.

A staging hostname can run the exact production image unchanged — reads are
free and read-only, so rehearsing a real filing against mainnet is safe.

## Health and monitoring

- `GET /api/status` is the health check. It returns **HTTP 200 whenever the
  process is healthy**; chain health is reported in the JSON body (cached
  10 s, probed with a 4 s RPC timeout so it fails fast instead of hanging).
- **The alert that matters is RPC reachability**:
  `.chain.rpc_ok == false` (RPC unreachable) or
  `.chain.chain_id_ok == false` (RPC serving something other than chain 1611).
- `.registries["us-scotus"].name_matches_manifest == true` is a live
  integrity check of the pinned registry manifest; false means the chain and
  the app's trust anchor disagree and is alert-worthy.
- Liveness/readiness probes: `GET /api/status` expecting HTTP 200 (or `GET /`,
  which is static and makes no RPC call). Do not key readiness on the
  `rpc_ok` body field: when the RPC is down, user-facing check endpoints
  already fail loudly with 502 rather than answering wrong, and restarting or
  unrouting pods cannot fix an upstream RPC.

## Ingress / reverse proxy requirements

TLS at the domain root; the app must be mounted at `/`, never under a path
prefix.

- Upload body limit **≥ 30 MB** (the app enforces its own 30 MB cap and
  answers 413 beyond it).
- Read timeout **≥ 60 s** (drafting checks make live chain reads; large
  briefs take tens of seconds).
- Pass the app's `Cache-Control: no-store` through unchanged — no proxy
  cache, no CDN.
- Keep query strings out of any retained access logs (receipt lookups carry
  a document SHA-256 in the query string; the app's own access log already
  strips them). Log the path only, or disable access logging for this host.
- No CORS configuration; the app is same-origin only and sends a strict CSP.

ingress-nginx annotations that satisfy the above:

```yaml
nginx.ingress.kubernetes.io/proxy-body-size: "32m"
nginx.ingress.kubernetes.io/proxy-read-timeout: "75"
nginx.ingress.kubernetes.io/proxy-send-timeout: "75"
```

## Kubernetes notes

- One Deployment, 1–2 replicas (stateless, safe to scale horizontally).
  No PVC, no ConfigMap, no Secret.
- Starting resources: requests `100m` / `256Mi`, limits `1` / `1Gi`
  (parsing a 30 MB PDF is the peak; tune from observed usage).
- DNS: `nvnmcite.com` is in Inveniam's GoDaddy account (transferred
  2026-08-04); point it at the ingress when ready.
