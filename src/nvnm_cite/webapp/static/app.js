"use strict";
/* NVNM Cite web demo.
 *
 * Trust model in one paragraph: this page never sees a private key and
 * never encodes chain data itself. The local server prepares calldata
 * with the project's golden-tested codec; the user's wallet signs; the
 * chain decides. Dynamic data (case names, chain metadata) is rendered
 * exclusively via textContent — never innerHTML.
 */

const CHAIN_ID = 787111;                 // nvnm-testnet-1
const CHAIN_ID_HEX = "0x" + CHAIN_ID.toString(16); // 0xc02a7
const CHAIN_PARAMS = {
  chainId: CHAIN_ID_HEX,
  chainName: "NVNM Chain Testnet",
  nativeCurrency: { name: "wmantraUSD", symbol: "wmantraUSD", decimals: 18 },
  rpcUrls: ["https://evm.testnet.nvnmchain.io"],
  blockExplorerUrls: ["https://explorer.evm.testnet.nvnmchain.io"],
};
let EXPLORER = "https://explorer.evm.testnet.nvnmchain.io";

const STATUS_WORD = { V: "VERIFIED", N: "NOT_FOUND", C: "NOT_COVERED", A: "AMBIGUOUS_JURISDICTION", U: "UNPARSEABLE" };
const STATUS_ORDER = ["VERIFIED", "NOT_FOUND", "NOT_COVERED", "AMBIGUOUS_JURISDICTION", "UNPARSEABLE"];

/* ---------- tiny DOM + format helpers ---------- */

const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

function chipFor(status, big) {
  return el("span", `chip chip-${status}${big ? " chip-big" : ""}`, status === "AMBIGUOUS_JURISDICTION" ? "AMBIGUOUS" : status);
}

function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(2)} MB`;
}

function shortHex(h, keep = 8) {
  return h && h.length > 2 * keep + 3 ? `${h.slice(0, keep + 2)}…${h.slice(-keep)}` : h;
}

function kvRow(box, key, value, mono) {
  const row = el("div", "row");
  row.appendChild(el("span", "k", key));
  const v = el("span", mono === false ? "" : "v");
  if (value instanceof Node) v.appendChild(value); else v.textContent = value;
  row.appendChild(v);
  box.appendChild(row);
  return row;
}

function extLink(href, text) {
  const a = el("a", null, text);
  if (/^https:\/\//.test(href)) { a.href = href; a.target = "_blank"; a.rel = "noopener"; }
  return a;
}

function showError(id, err) {
  const box = $(id);
  box.textContent = err && err.message ? err.message : String(err);
  box.classList.remove("hidden");
}

function hide(...ids) { ids.forEach((i) => $(i).classList.add("hidden")); }
function show(...ids) { ids.forEach((i) => $(i).classList.remove("hidden")); }

/* ---------- API ---------- */

async function apiGet(path) {
  const res = await fetch(path);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}

async function apiPostBytes(path, bytes, filename) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(filename || "upload") },
    body: bytes,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}

async function apiPostJson(path, obj) {
  const res = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(obj),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}

/* ---------- state ---------- */

let lastReport = null;   // last /api/check report (page memory only)
let prepared = null;     // last /api/receipt/prepare response
let wallet = { address: null, chainOk: false };

/* ---------- tabs ---------- */

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
  if (history.replaceState) history.replaceState(null, "", `#${name}`);
}

function initTabs() {
  $("tabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (btn) activateTab(btn.dataset.tab);
  });
  const fromHash = location.hash.replace("#", "");
  if (["check", "record", "verify", "inspect", "about"].includes(fromHash)) activateTab(fromHash);
}

/* ---------- status (header, banners, about) ---------- */

async function loadStatus() {
  let st;
  try { st = await apiGet("/api/status"); }
  catch (err) {
    $("chain-badge").textContent = "server unreachable";
    $("chain-badge").className = "badge badge-bad";
    return;
  }
  if (st.constants && st.constants.explorer) EXPLORER = st.constants.explorer;

  const badge = $("chain-badge");
  if (st.chain && st.chain.rpc_ok) {
    badge.textContent = `chain ${st.chain.chain_id} · block ${st.chain.head_block.toLocaleString()}`;
    badge.className = st.chain.chain_id_ok ? "badge badge-ok" : "badge badge-bad";
  } else {
    badge.textContent = "chain RPC unreachable";
    badge.className = "badge badge-bad";
  }

  const banner = $("global-banner");
  const notes = [];
  if (st.loader && st.loader.bulk_load_running) {
    notes.push("Registry bulk load in progress: the on-chain registries are still filling, so a live chain re-check may show NOT_FOUND for real citations until it completes. Local checks are unaffected.");
  }
  if (st.registries && st.registries["receipts-v1"] && !st.registries["receipts-v1"].exists) {
    notes.push("The receipts-v1 registry has not been created on chain yet — the record step will offer the one-time setup transaction.");
  }
  if (notes.length) { banner.textContent = notes.join(" "); banner.classList.remove("hidden"); }

  // About panel: live status
  const box = clear($("about-status"));
  if (st.chain && st.chain.rpc_ok) {
    kvRow(box, "RPC", "reachable", false);
    kvRow(box, "Chain id", `${st.chain.chain_id} (expected ${st.chain.expected_chain_id})`);
    kvRow(box, "Head block", st.chain.head_block.toLocaleString());
  } else {
    kvRow(box, "RPC", `unreachable — ${(st.chain && st.chain.error) || "unknown error"}`, false);
  }
  for (const [name, reg] of Object.entries(st.registries || {})) {
    kvRow(box, `Registry ${name}`, reg.exists ? `id ${reg.id} · created ${reg.created_at.slice(0, 19)}` : "not created yet");
  }
  kvRow(box, "Bulk load", st.loader && st.loader.bulk_load_running ? "running (tranche 1)" : "not running", false);
  kvRow(box, "Anchoring precompile", st.constants ? st.constants.precompile : "");

  const vbox = clear($("about-versions"));
  if (st.versions) {
    kvRow(vbox, "Normalizer", st.versions.normalizer);
    kvRow(vbox, "Citation spec", st.versions.citation_spec);
    kvRow(vbox, "Record schema", st.versions.record_schema);
    kvRow(vbox, "Receipt schema", `${st.versions.receipt_schema} (locks at Phase 4)`);
  }

  const tbody = clear($("coverage-table").querySelector("tbody"));
  (st.index && st.index.registries ? st.index.registries : []).forEach((r) => {
    const tr = el("tr");
    tr.appendChild(el("td", "cite-canon", r.registry));
    tr.appendChild(el("td", null, r.source));
    tr.appendChild(el("td", null, (r.records || 0).toLocaleString()));
    const detail = r.source === "chain-index"
      ? `synced to block ${r.synced_block.toLocaleString()} at ${r.synced_at}`
      : `CourtListener snapshot ${r.snapshot}${r.note ? " — " + r.note : ""}`;
    tr.appendChild(el("td", null, detail));
    tbody.appendChild(tr);
  });
}

/* ---------- 1 · check ---------- */

function wireDropzone(zoneId, inputId, onFile) {
  const zone = $(zoneId), input = $(inputId);
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { if (input.files[0]) onFile(input.files[0]); input.value = ""; });
  ["dragover", "dragenter"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("dragover"); }));
  zone.addEventListener("drop", (e) => { const f = e.dataTransfer.files && e.dataTransfer.files[0]; if (f) onFile(f); });
}

function docCard(box, doc) {
  const card = clear(box);
  card.appendChild(el("h3", null, doc.filename || "document"));
  const kv = el("div", "kv");
  kvRow(kv, "SHA-256", doc.sha256);
  kvRow(kv, "Size", fmtBytes(doc.bytes), false);
  if (doc.extraction) kvRow(kv, "Text extraction", `${doc.extraction.method} · ${doc.extraction.chars.toLocaleString()} characters`, false);
  card.appendChild(kv);
}

function renderCheck(report) {
  lastReport = report;
  docCard($("check-doc"), report.document);

  const chips = clear($("check-summary"));
  const oc = el("div", "sum-chip");
  oc.appendChild(el("span", "n", String(report.summary.occurrences)));
  oc.appendChild(el("span", "l", "citation occurrences"));
  chips.appendChild(oc);
  STATUS_ORDER.forEach((s) => {
    const n = report.summary.by_status[s] || 0;
    if (!n && s !== "VERIFIED" && s !== "NOT_FOUND") return;
    const c = el("div", `sum-chip sum-${s}`);
    c.appendChild(el("span", "n", String(n)));
    c.appendChild(el("span", "l", s === "AMBIGUOUS_JURISDICTION" ? "ambiguous" : s.toLowerCase().replace("_", " ")));
    chips.appendChild(c);
  });

  const warnBox = clear($("check-warning"));
  if (report.document.extraction && report.document.extraction.warning) {
    const w = el("div", "callout callout-warn");
    w.textContent = `Extraction warning: ${report.document.extraction.warning}`;
    warnBox.appendChild(w);
  }
  if (report.summary.name_mismatches > 0) {
    const w = el("div", "callout callout-warn");
    w.textContent = `${report.summary.name_mismatches} citation(s) carry party names that do not match the registry's case name — a real citation paired with an invented case name is the other classic hallucination.`;
    warnBox.appendChild(w);
  }

  const tbody = clear($("check-table").querySelector("tbody"));
  report.citations.forEach((c) => {
    const tr = el("tr");
    const tdS = el("td"); tdS.appendChild(chipFor(c.status)); tr.appendChild(tdS);

    const tdC = el("td");
    tdC.appendChild(el("div", "cite-canon", c.canonical || c.as_written));
    if (c.canonical && c.as_written && c.as_written !== c.canonical) {
      tdC.appendChild(el("div", "cite-sub", `as written: ${c.as_written}`));
    }
    const partyBits = [c.plaintiff, c.defendant].filter(Boolean).join(" v. ");
    if (partyBits) tdC.appendChild(el("div", "cite-sub", partyBits + (c.year ? ` (${c.year})` : "")));
    if (c.reason) tdC.appendChild(el("div", "cite-reason", c.reason));
    tr.appendChild(tdC);

    const tdR = el("td");
    if (c.record && c.record.cases.length) {
      c.record.cases.forEach((k) => {
        const line = el("div");
        line.appendChild(document.createTextNode(`${k.name}${k.year ? ` (${k.year})` : ""} `));
        tdR.appendChild(line);
      });
      if (c.record.more_cases) tdR.appendChild(el("div", "cite-sub", `+${c.record.more_cases} more decisions share this first page`));
      const src = el("div", "cite-sub");
      src.appendChild(extLink(c.record.uri, "CourtListener ↗"));
      src.appendChild(document.createTextNode(` · ${c.record.source}`));
      tdR.appendChild(src);
    } else if (c.registry) {
      tdR.appendChild(el("div", "cite-sub", c.registry));
    } else {
      tdR.appendChild(el("div", "cite-sub", "—"));
    }
    tr.appendChild(tdR);

    const tdN = el("td");
    if (c.name_check === "match") tdN.appendChild(el("span", "name-m", "match"));
    else if (c.name_check === "mismatch") tdN.appendChild(el("span", "name-x", "MISMATCH"));
    else tdN.appendChild(el("span", "name-u", "—"));
    tr.appendChild(tdN);

    tr.appendChild(el("td", null, String(c.occurrences)));
    tbody.appendChild(tr);
  });

  hide("check-busy", "check-error");
  show("check-result");
  syncRecordPanel();
}

async function runCheck(bytes, filename) {
  hide("check-result", "check-error");
  show("check-busy");
  try {
    renderCheck(await apiPostBytes("/api/check", bytes, filename));
  } catch (err) {
    hide("check-busy");
    showError("check-error", err);
  }
}

function initCheck() {
  wireDropzone("check-drop", "check-file", async (f) => runCheck(await f.arrayBuffer(), f.name));
  $("paste-toggle").addEventListener("click", () => $("paste-area").classList.toggle("hidden"));
  $("paste-check").addEventListener("click", () => {
    const text = $("paste-text").value;
    if (text.trim()) runCheck(new TextEncoder().encode(text), "pasted-text.txt");
  });
  $("to-record").addEventListener("click", () => activateTab("record"));
}

/* ---------- wallet ---------- */

function providerOrNull() { return window.ethereum || null; }

async function refreshWalletState() {
  const eth = providerOrNull();
  const btn = $("wallet-btn");
  if (!eth) { btn.textContent = "No wallet detected"; wallet = { address: null, chainOk: false }; syncRecordPanel(); return; }
  const accounts = await eth.request({ method: "eth_accounts" }).catch(() => []);
  wallet.address = accounts[0] || null;
  if (wallet.address) {
    const chainHex = await eth.request({ method: "eth_chainId" }).catch(() => null);
    wallet.chainOk = chainHex && parseInt(chainHex, 16) === CHAIN_ID;
    btn.textContent = `${shortHex(wallet.address, 5)}${wallet.chainOk ? "" : " · wrong network"}`;
  } else {
    wallet.chainOk = false;
    btn.textContent = "Connect wallet";
  }
  syncRecordPanel();
}

async function connectWallet() {
  const eth = providerOrNull();
  if (!eth) {
    alert("No EVM wallet detected. Install MetaMask (metamask.io), then reload this page.");
    return;
  }
  try {
    await eth.request({ method: "eth_requestAccounts" });
    const chainHex = await eth.request({ method: "eth_chainId" });
    if (parseInt(chainHex, 16) !== CHAIN_ID) await switchNetwork();
  } catch (err) {
    if (err && err.code !== 4001) alert(`Wallet error: ${err.message || err}`);
  }
  refreshWalletState();
}

async function switchNetwork() {
  const eth = providerOrNull();
  try {
    await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: CHAIN_ID_HEX }] });
  } catch (err) {
    if (err && (err.code === 4902 || /unrecognized|not added/i.test(err.message || ""))) {
      await eth.request({ method: "wallet_addEthereumChain", params: [CHAIN_PARAMS] });
    } else if (err && err.code !== 4001) {
      throw err;
    }
  }
}

function initWallet() {
  $("wallet-btn").addEventListener("click", connectWallet);
  const eth = providerOrNull();
  if (eth && eth.on) {
    eth.on("accountsChanged", refreshWalletState);
    eth.on("chainChanged", refreshWalletState);
  }
  refreshWalletState();
}

/* ---------- 2 · record ---------- */

function syncRecordPanel() {
  const haveDoc = !!lastReport;
  $("step-report-state").textContent = haveDoc
    ? `✓ ${lastReport.document.filename} (${lastReport.summary.distinct} distinct citations)` : "— run a check first";
  $("step-report-state").classList.toggle("ok", haveDoc);
  const ws = $("step-wallet-state");
  if (wallet.address && wallet.chainOk) { ws.textContent = `✓ ${shortHex(wallet.address, 5)} on NVNM testnet`; ws.classList.add("ok"); }
  else if (wallet.address) { ws.textContent = "connected, but on the wrong network — click the wallet button to switch"; ws.classList.remove("ok"); }
  else { ws.textContent = "— not connected"; ws.classList.remove("ok"); }
  $("record-nodoc").classList.toggle("hidden", haveDoc);
  $("record-main").classList.toggle("hidden", !haveDoc);
  if (haveDoc) docCard($("record-doc"), lastReport.document);
}

function receiptEntriesFromReport(report) {
  return report.citations.map((c) => ({
    registry: c.registry, canonical: c.canonical, as_written: c.as_written,
    occurrences: c.occurrences, plaintiff: c.plaintiff, defendant: c.defendant, status: c.status,
  }));
}

async function prepareReceipt() {
  if (!lastReport) return;
  if (!wallet.address) { showError("prepare-error", new Error("Connect a wallet first — the receipt records the attesting address.")); return; }
  hide("prepare-result", "prepare-error", "anchor-status");
  show("prepare-busy");
  try {
    prepared = await apiPostJson("/api/receipt/prepare", {
      document_sha256: lastReport.document.sha256,
      results: receiptEntriesFromReport(lastReport),
      agent: { address: wallet.address, kya_id: $("kya-id").value.trim() || undefined },
    });
    renderPrepared(prepared);
  } catch (err) {
    showError("prepare-error", err);
  } finally {
    hide("prepare-busy");
  }
}

function renderPrepared(p) {
  const meta = clear($("prepare-meta"));
  kvRow(meta, "Checked at block", String(p.chain.checked_at_block));
  kvRow(meta, "Registries consulted", p.chain.registries.map((r) => `${r.name} (id ${r.id})`).join(", "), false);
  kvRow(meta, "Receipt schema", `${p.receipt.schema} — draft until Phase 4 locks v1`, false);
  kvRow(meta, "Timestamp (server)", `${p.receipt.timestamp} — the chain's own block time becomes the authoritative timestamp once anchored`, false);

  const tbody = clear($("prepare-table").querySelector("tbody"));
  p.results.forEach((r) => {
    const tr = el("tr");
    const tdC = el("td");
    tdC.appendChild(el("div", "cite-canon", r.canonical || r.as_written || "—"));
    if (r.registry) tdC.appendChild(el("div", "cite-sub", r.registry));
    tr.appendChild(tdC);
    const tdL = el("td"); tdL.appendChild(chipFor(r.local_status)); tr.appendChild(tdL);
    const tdK = el("td");
    tdK.appendChild(chipFor(r.chain_status));
    if (r.chain_status !== r.local_status) tdK.appendChild(el("div", "cite-reason", "differs from the local check — on-chain registry state is what the receipt records"));
    tr.appendChild(tdK);
    const tdN = el("td");
    if (r.name_check === "match") tdN.appendChild(el("span", "name-m", "match"));
    else if (r.name_check === "mismatch") tdN.appendChild(el("span", "name-x", "MISMATCH"));
    else tdN.appendChild(el("span", "name-u", "—"));
    tr.appendChild(tdN);
    tbody.appendChild(tr);
  });

  $("receipt-json").textContent = p.receipt.json;
  const meter = clear($("size-meter"));
  meter.appendChild(document.createTextNode(`Receipt size: ${p.receipt.bytes} of ${p.receipt.cap} bytes (on-chain metadata cap)`));
  if (p.receipt.compactions.length) meter.appendChild(el("div", "cite-sub", `compaction applied: ${p.receipt.compactions.join("; ")}`));
  const bar = el("div", "size-bar");
  const fill = el("div", `size-fill${p.receipt.bytes > p.receipt.cap * 0.85 ? " tight" : ""}`);
  fill.style.width = `${Math.min(100, (p.receipt.bytes / p.receipt.cap) * 100)}%`;
  bar.appendChild(fill); meter.appendChild(bar);

  const setupBox = $("setup-box"); const probeBox = clear($("probe-box"));
  const anchorBtn = $("anchor-btn");
  anchorBtn.disabled = true;
  if (!p.receipts_registry.exists) {
    setupBox.classList.remove("hidden");
    clear(setupBox);
    setupBox.appendChild(el("strong", null, "One-time setup needed: "));
    setupBox.appendChild(document.createTextNode(p.setup.note + " The creation strings are fixed by the locked record schema: "));
    const pre = el("pre", "codeblock", `addRegistry("${p.setup.registry}",\n  "${p.setup.description}",\n  '${p.setup.metadata}')`);
    setupBox.appendChild(pre);
    const btn = el("button", "btn btn-primary", "Create receipts-v1 with wallet");
    btn.addEventListener("click", createReceiptsRegistry);
    setupBox.appendChild(btn);
    if (p.setup.probe && !p.setup.probe.ok) {
      setupBox.appendChild(el("div", "probe-bad", `Note: creation simulated as failing for this wallet: ${p.setup.probe.message}`));
    }
  } else {
    setupBox.classList.add("hidden");
    const probe = p.write_probe || {};
    if (probe.ok) {
      probeBox.appendChild(el("div", "probe-ok", `✓ This wallet may write to receipts-v1 (simulated: ~${probe.gas.toLocaleString()} gas ≈ ${(probe.gas * 45e-9).toFixed(4)} wmantraUSD at 45 gwei).`));
      anchorBtn.disabled = false;
    } else if (probe.kind === "unauthorized") {
      probeBox.appendChild(el("div", "probe-bad",
        "✗ This wallet has no editor rights on receipts-v1 (chain writes are deny-by-default). " +
        "The registry's admin must run grantRole(registryId, yourAddress, \"editor\") once — on this pilot, that is the wallet that created the registry."));
    } else {
      probeBox.appendChild(el("div", "probe-bad", `✗ Write simulation failed: ${probe.message || "unknown error"}`));
    }
  }
  show("prepare-result");
}

async function sendTx(tx, statusBoxId, onMined) {
  const eth = providerOrNull();
  const box = clear($(statusBoxId));
  box.classList.remove("hidden");
  let hash;
  try {
    hash = await eth.request({
      method: "eth_sendTransaction",
      params: [{ from: wallet.address, to: tx.to, data: tx.data, value: tx.value || "0x0" }],
    });
  } catch (err) {
    box.appendChild(el("div", "error", err.code === 4001 ? "Transaction rejected in wallet." : `Wallet error: ${err.message || err}`));
    return;
  }
  const wait = el("div", "txwait");
  wait.appendChild(el("div", "spinner"));
  const msg = el("span", null, `Submitted ${shortHex(hash, 10)} — waiting for confirmation…`);
  wait.appendChild(msg);
  box.appendChild(wait);
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 2500));
    let info;
    try { info = await apiGet(`/api/tx?hash=${hash}`); } catch { continue; }
    if (info.found && !info.pending) {
      box.removeChild(wait);
      onMined(box, info, hash);
      return;
    }
  }
  msg.textContent = `Still pending after 150s — track it at ${EXPLORER}/tx/${hash}`;
}

async function createReceiptsRegistry() {
  if (!prepared || !prepared.setup) return;
  await sendTx(prepared.setup.tx, "anchor-status", (box, info) => {
    const banner = el("div", `result-banner ${info.success ? "result-ok" : "result-bad"}`);
    banner.appendChild(el("h3", null, info.success ? "receipts-v1 created" : "Registry creation failed"));
    if (info.success) banner.appendChild(el("p", null, `Confirmed in block ${info.block} at ${info.block_time}. Re-preparing the receipt…`));
    box.appendChild(banner);
    if (info.success) setTimeout(prepareReceipt, 1200);
  });
}

async function anchorReceipt() {
  if (!prepared) return;
  await sendTx(prepared.tx, "anchor-status", (box, info, hash) => {
    const banner = el("div", `result-banner ${info.success ? "result-ok" : "result-bad"}`);
    banner.appendChild(el("h3", null, info.success ? "Verification recorded on NVNM Chain" : "Transaction reverted"));
    const kv = el("div", "kv");
    kvRow(kv, "Transaction", hash);
    kvRow(kv, "Block", `${info.block} — ${info.block_time} (the immutable timestamp)`, false);
    kvRow(kv, "Document SHA-256", lastReport ? lastReport.document.sha256 : "");
    kvRow(kv, "Gas used", info.gas_used ? info.gas_used.toLocaleString() : "?", false);
    banner.appendChild(kv);
    const links = el("p");
    links.appendChild(extLink(`${EXPLORER}/tx/${hash}`, "View on Blockscout ↗"));
    links.appendChild(document.createTextNode("  ·  "));
    const verifyBtn = el("button", "btn", "Verify it now (free lookup)");
    verifyBtn.addEventListener("click", () => {
      activateTab("verify");
      $("hash-input").value = lastReport.document.sha256;
      lookupHash(lastReport.document.sha256);
    });
    links.appendChild(verifyBtn);
    const inspectBtn = el("button", "btn", "Decode the transaction");
    inspectBtn.addEventListener("click", () => { activateTab("inspect"); $("tx-input").value = hash; inspectTx(hash); });
    links.appendChild(document.createTextNode("  ·  "));
    links.appendChild(inspectBtn);
    banner.appendChild(links);
    box.appendChild(banner);
  });
}

function initRecord() {
  $("record-gocheck").addEventListener("click", () => activateTab("check"));
  $("prepare-btn").addEventListener("click", prepareReceipt);
  $("anchor-btn").addEventListener("click", anchorReceipt);
}

/* ---------- verify (free lookup) ---------- */

async function sha256HexOf(buffer) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function renderReceiptVersion(container, v, idx, total) {
  const card = el("div", "doc-card");
  card.appendChild(el("h3", null, total > 1 ? `Receipt version ${v.index}${v.is_latest ? " (latest)" : ""}` : "Receipt"));
  const kv = el("div", "kv");
  kvRow(kv, "Recorded (chain time)", v.chain_timestamp, false);
  kvRow(kv, "Record id / version", `${v.record_id} / ${v.index}`, false);
  const r = v.receipt;
  if (r && typeof r === "object") {
    if (r.agent) kvRow(kv, "Attested by", `${r.agent.address}${r.agent.kya_id ? ` (${r.agent.kya_id})` : ""}`);
    if (r.checked_at_block) kvRow(kv, "Checked at block", String(r.checked_at_block));
    if (r.normalizer_version) kvRow(kv, "Normalizer", r.normalizer_version, false);
    if (r.schema) kvRow(kv, "Schema", r.schema, false);
    card.appendChild(kv);
    if (Array.isArray(r.results)) {
      const counts = {};
      r.results.forEach((e) => { const w = STATUS_WORD[e.s] || "?"; counts[w] = (counts[w] || 0) + 1; });
      if (r.verified_omitted) counts.VERIFIED = (counts.VERIFIED || 0) + r.verified_omitted;
      const chips = el("div", "summary-chips");
      STATUS_ORDER.forEach((s) => {
        if (!counts[s]) return;
        const c = el("div", `sum-chip sum-${s}`);
        c.appendChild(el("span", "n", String(counts[s])));
        c.appendChild(el("span", "l", s === "AMBIGUOUS_JURISDICTION" ? "ambiguous" : s.toLowerCase().replace("_", " ")));
        chips.appendChild(c);
      });
      card.appendChild(chips);
      const mismatches = r.results.filter((e) => e.n === "x");
      if (mismatches.length) {
        card.appendChild(el("div", "probe-bad", `${mismatches.length} result(s) were flagged as name MISMATCH at check time.`));
      }
      const tbl = el("table", "cite-table");
      const thead = el("thead"); const hr = el("tr");
      ["Status", "Citation", "Registry", "Names", "×"].forEach((h) => hr.appendChild(el("th", null, h)));
      thead.appendChild(hr); tbl.appendChild(thead);
      const tb = el("tbody");
      r.results.forEach((e) => {
        const tr = el("tr");
        const td0 = el("td"); td0.appendChild(chipFor(STATUS_WORD[e.s] || "UNPARSEABLE")); tr.appendChild(td0);
        const td1 = el("td");
        td1.appendChild(el("div", "cite-canon", e.c || e.w || "—"));
        if (e.w && e.c && e.w !== e.c) td1.appendChild(el("div", "cite-sub", `as written: ${e.w}`));
        if (e.k) td1.appendChild(el("div", "cite-sub", `CourtListener cluster ${e.k}`));
        tr.appendChild(td1);
        const regName = typeof e.g === "number" && r.registries && r.registries[e.g] ? r.registries[e.g].name : (typeof e.g === "string" ? e.g : "—");
        tr.appendChild(el("td", "cite-sub", regName));
        const td3 = el("td");
        if (e.n === "m") td3.appendChild(el("span", "name-m", "match"));
        else if (e.n === "x") td3.appendChild(el("span", "name-x", "MISMATCH"));
        else td3.appendChild(el("span", "name-u", "—"));
        tr.appendChild(td3);
        tr.appendChild(el("td", null, String(e.o || 1)));
        tb.appendChild(tr);
      });
      tbl.appendChild(tb);
      card.appendChild(tbl);
      if (r.verified_omitted) card.appendChild(el("p", "hint", `${r.verified_omitted} VERIFIED results were collapsed into a count to fit the on-chain size cap.`));
    }
  } else {
    kvRow(kv, "Metadata", "did not parse as a receipt; raw payload below", false);
    card.appendChild(kv);
  }
  const det = el("details", "json-details");
  det.appendChild(el("summary", null, "Raw on-chain record"));
  det.appendChild(el("pre", "codeblock", v.metadata_raw));
  card.appendChild(det);
  container.appendChild(card);
}

function renderLookup(res) {
  const box = clear($("verify-result"));
  const kv = el("div", "kv");
  kvRow(kv, "SHA-256 queried", res.sha256);
  kvRow(kv, "Chain head at lookup", String(res.head_block));
  box.appendChild(kv);

  if (!res.registry_exists) {
    const b = el("div", "result-banner result-warn");
    b.appendChild(el("h3", null, "Receipts registry not deployed"));
    b.appendChild(el("p", null, res.note));
    box.appendChild(b);
  } else if (res.found) {
    const b = el("div", "result-banner result-ok");
    b.appendChild(el("h3", null, "✓ A verification receipt exists for this exact document"));
    b.appendChild(el("p", null,
      "A citation check of the byte-for-byte identical file was attested on NVNM Chain. " +
      "The chain timestamp below is immutable; the SHA-256 key makes the receipt about this file and no other."));
    box.appendChild(b);
    res.versions.forEach((v) => renderReceiptVersion(box, v, v.index, res.versions.length));
    box.appendChild(el("p", "hint",
      "Remember what this does not say: it does not certify the document's arguments, " +
      "and a VERIFIED citation is a claim of existence, not of good law."));
  } else {
    const b = el("div", "result-banner result-bad");
    b.appendChild(el("h3", null, "✗ No receipt for this fingerprint"));
    b.appendChild(el("p", null,
      "Either no citation check was attested for this document, or the file you have differs " +
      "from the checked one — even a one-byte change produces a different SHA-256."));
    box.appendChild(b);
  }

  if (res.proof) {
    const det = el("details", "json-details");
    det.appendChild(el("summary", null, "Don't trust this page? Replay the lookup yourself"));
    const curl = `curl -s -X POST ${CHAIN_PARAMS.rpcUrls[0]} -H 'Content-Type: application/json' -H 'User-Agent: nvnm-cite-verify' -d '${JSON.stringify({ jsonrpc: "2.0", id: 1, method: res.proof.request.method, params: res.proof.request.params })}'`;
    det.appendChild(el("pre", "codeblock", curl));
    det.appendChild(el("p", "hint", "Any NVNM testnet RPC returns the same record; this page adds nothing you cannot reproduce."));
    box.appendChild(det);
  }
  show("verify-result");
}

async function lookupHash(sha) {
  hide("verify-result", "verify-error");
  show("verify-busy");
  try {
    renderLookup(await apiGet(`/api/receipt/lookup?sha256=${encodeURIComponent(sha)}`));
  } catch (err) {
    showError("verify-error", err);
  } finally {
    hide("verify-busy");
  }
}

function initVerify() {
  wireDropzone("verify-drop", "verify-file", async (f) => {
    hide("verify-result", "verify-error");
    show("verify-busy");
    try {
      const sha = await sha256HexOf(await f.arrayBuffer());
      $("hash-input").value = sha;
      await lookupHash(sha);
    } catch (err) {
      hide("verify-busy");
      showError("verify-error", err);
    }
  });
  $("hash-toggle").addEventListener("click", () => $("hash-area").classList.toggle("hidden"));
  $("hash-lookup").addEventListener("click", () => {
    const sha = $("hash-input").value.trim().toLowerCase();
    if (/^[0-9a-f]{64}$/.test(sha)) lookupHash(sha);
    else showError("verify-error", new Error("That is not a 64-character hex SHA-256."));
  });
}

/* ---------- inspect ---------- */

function renderInspect(info) {
  const box = clear($("inspect-result"));
  if (!info.found) {
    box.appendChild(el("div", "result-banner result-warn", "No transaction with that hash on this chain."));
    show("inspect-result");
    return;
  }
  const kv = el("div", "kv");
  kvRow(kv, "Status", info.pending ? "pending" : info.success ? "confirmed ✓" : "REVERTED ✗", false);
  if (info.block) kvRow(kv, "Block / time", `${info.block} — ${info.block_time}`, false);
  kvRow(kv, "From", info.from);
  kvRow(kv, "To", `${info.to}${info.is_anchoring_precompile ? "  (NVNM anchoring precompile)" : ""}`);
  if (info.gas_used) kvRow(kv, "Gas", `${info.gas_used.toLocaleString()} @ ${info.gas_price_gwei} gwei`, false);
  box.appendChild(kv);

  const d = info.decoded;
  if (d && d.function) {
    box.appendChild(el("h3", null, `Decoded: ${d.function}()`));
    const flat = d.function === "addRecord" ? d.args.record : d.args;
    const kv2 = el("div", "kv");
    Object.entries(flat).forEach(([k, v]) => {
      if (typeof v === "object" && v !== null) return;
      kvRow(kv2, k, String(v));
    });
    box.appendChild(kv2);
    if (d.metadata_json) {
      box.appendChild(el("p", "hint", "metadata, decoded as JSON — the plaintext a generic explorer cannot show you:"));
      box.appendChild(el("pre", "codeblock", JSON.stringify(d.metadata_json, null, 2)));
    }
    box.appendChild(el("p", "hint",
      "Decoded with the project's vendored precompile ABI and versioned codec. The strings above " +
      "are stored on chain in plaintext (the project's core invariant) — explorer UTF-8 views look " +
      "garbled only because ABI length-prefixes and padding sit between them."));
  } else if (d) {
    box.appendChild(el("p", "hint", `Selector ${d.selector} is not an anchoring-precompile method this codec knows.`));
  }
  const link = el("p");
  link.appendChild(extLink(info.explorer, "View on Blockscout ↗"));
  box.appendChild(link);
  show("inspect-result");
}

async function inspectTx(hash) {
  hide("inspect-result", "inspect-error");
  show("inspect-busy");
  try {
    renderInspect(await apiGet(`/api/tx?hash=${encodeURIComponent(hash)}`));
  } catch (err) {
    showError("inspect-error", err);
  } finally {
    hide("inspect-busy");
  }
}

function initInspect() {
  $("tx-inspect").addEventListener("click", () => {
    const h = $("tx-input").value.trim().toLowerCase();
    if (/^0x[0-9a-f]{64}$/.test(h)) inspectTx(h);
    else showError("inspect-error", new Error("Expected a 0x-prefixed 64-hex-character transaction hash."));
  });
  $("tx-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("tx-inspect").click(); });
}

/* ---------- boot ---------- */

initTabs();
initCheck();
initWallet();
initRecord();
initVerify();
initInspect();
loadStatus();
setInterval(loadStatus, 60000);
