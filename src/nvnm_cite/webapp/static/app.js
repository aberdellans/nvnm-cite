"use strict";
/* NVNM Cite web demo.
 *
 * Trust model in one paragraph: this page never sees a private key and
 * never encodes chain data itself. The local server prepares calldata
 * with the project's golden-tested codec; the user's wallet signs; the
 * chain decides. Dynamic data (case names, chain metadata) is rendered
 * exclusively via textContent — never innerHTML.
 *
 * DOM vocabulary (classes/shapes) follows the 2026-06-12 design handoff;
 * the integration contract ids/classes are unchanged.
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
let RPC_URL = CHAIN_PARAMS.rpcUrls[0];

const STATUS_WORD = { V: "VERIFIED", N: "NOT_FOUND", C: "NOT_COVERED", A: "AMBIGUOUS_JURISDICTION", U: "UNPARSEABLE" };
const STATUS_ORDER = ["VERIFIED", "NOT_FOUND", "NOT_COVERED", "AMBIGUOUS_JURISDICTION", "UNPARSEABLE"];
const CHIP_LABEL = {
  VERIFIED: "Verified",
  NOT_FOUND: "Not found",
  NOT_COVERED: "Not covered",
  AMBIGUOUS_JURISDICTION: "Ambiguous",
  UNPARSEABLE: "Unparseable",
};
const SUM_LABEL = {
  VERIFIED: "verified",
  NOT_FOUND: "not found",
  NOT_COVERED: "not covered",
  AMBIGUOUS_JURISDICTION: "ambiguous",
  UNPARSEABLE: "unparseable",
};

/* ---------- tiny DOM + format helpers ---------- */

const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

function icon(ref, cls) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "ic" + (cls ? " " + cls : ""));
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#" + ref);
  svg.appendChild(use);
  return svg;
}

function copyBtn(payload, what) {
  const b = el("button", "copy-btn", "copy");
  b.type = "button";
  b.setAttribute("aria-label", `Copy ${what || "value"} to clipboard`);
  b.addEventListener("click", () => {
    if (navigator.clipboard) navigator.clipboard.writeText(payload);
    b.textContent = "copied";
    b.classList.add("copied");
    setTimeout(() => { b.textContent = "copy"; b.classList.remove("copied"); }, 1400);
  });
  return b;
}

function chipFor(status, big) {
  return el("span", `chip chip-${status}${big ? " chip-big" : ""}`, CHIP_LABEL[status] || status);
}

function nameMark(kind) {
  if (kind === "match" || kind === "m") return el("span", "name-m", "match");
  if (kind === "mismatch" || kind === "x") return el("span", "name-x", "MISMATCH");
  return el("span", "name-u", "—");
}

function fmtBytes(n) {
  return n.toLocaleString("en-US") + " bytes";
}

function shortHex(h, keep = 8) {
  return h && h.length > 2 * keep + 3 ? `${h.slice(0, keep + 2)}…${h.slice(-keep)}` : h;
}

/* kv row per the design vocabulary: .row > .k + .v(.mono) [+ copy-btn][+ hint] */
function kvRow(box, key, value, opts) {
  opts = opts || {};
  const row = el("div", "row");
  row.appendChild(el("span", "k", key));
  const v = el("span", "v" + (opts.mono ? " mono" : ""));
  if (value instanceof Node) v.appendChild(value); else v.textContent = value;
  if (opts.copy) v.appendChild(copyBtn(opts.copy, key));
  if (opts.hint) v.appendChild(el("span", "hint", " " + opts.hint));
  row.appendChild(v);
  box.appendChild(row);
  return row;
}

function regLink(href, text) {
  const a = el("a", "reg-link", text);
  if (/^https:\/\//.test(href)) { a.href = href; a.target = "_blank"; a.rel = "noopener"; }
  a.appendChild(icon("i-linkout"));
  return a;
}

function banner(tone, iconRef, title, subText) {
  const b = el("div", `result-banner result-${tone}`);
  const head = el("div", "rb-head");
  head.appendChild(icon(iconRef));
  head.appendChild(el("span", "rb-title", title));
  b.appendChild(head);
  if (subText) b.appendChild(el("p", "rb-sub", subText));
  return b;
}

function calloutWarnNote(strongText, pText, iconRef) {
  const c = el("div", "callout callout-warn");
  c.appendChild(icon(iconRef || "i-alert"));
  const d = el("div");
  d.appendChild(el("strong", null, strongText));
  d.appendChild(el("p", null, pText));
  c.appendChild(d);
  return c;
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
  document.querySelectorAll(".tab").forEach((t) => {
    const active = t.dataset.tab === name;
    t.classList.toggle("active", active);
    t.setAttribute("aria-selected", active ? "true" : "false");
  });
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
  if (st.constants) {
    if (st.constants.explorer) EXPLORER = st.constants.explorer;
    if (st.constants.rpc_url) RPC_URL = st.constants.rpc_url;
  }

  const badge = $("chain-badge");
  if (st.chain && st.chain.rpc_ok) {
    badge.textContent = `chain ${st.chain.chain_id} · block ${st.chain.head_block.toLocaleString("en-US")}`;
    badge.className = st.chain.chain_id_ok ? "badge badge-ok" : "badge badge-bad";
  } else {
    badge.textContent = "chain RPC unreachable";
    badge.className = "badge badge-bad";
  }

  const bannerBox = $("global-banner");
  const notes = [];
  if (st.loader && st.loader.bulk_load_running) {
    notes.push("Registry bulk load in progress: the on-chain registries are still filling, so a live chain re-check may show NOT_FOUND for real citations until it completes. Local checks are unaffected.");
  }
  if (st.registries && st.registries["receipts-v1"] && !st.registries["receipts-v1"].exists) {
    notes.push("The receipts-v1 registry has not been created on chain yet — the record step will offer the one-time setup transaction.");
  }
  if (notes.length) { bannerBox.textContent = notes.join("  ·  "); bannerBox.classList.remove("hidden"); }
  else { bannerBox.classList.add("hidden"); }

  // About panel: live status
  const box = clear($("about-status"));
  if (st.chain && st.chain.rpc_ok) {
    const rpcV = el("span");
    rpcV.appendChild(el("span", "mono", RPC_URL));
    rpcV.appendChild(document.createTextNode("  ·  responding"));
    kvRow(box, "RPC", rpcV);
    kvRow(box, "Chain id", `${st.chain.chain_id} (expected ${st.chain.expected_chain_id})`, { mono: true });
    kvRow(box, "Head block", st.chain.head_block.toLocaleString("en-US"), { mono: true });
  } else {
    kvRow(box, "RPC", `unreachable — ${(st.chain && st.chain.error) || "unknown error"}`);
  }
  for (const [name, reg] of Object.entries(st.registries || {})) {
    kvRow(box, name, reg.exists
      ? `registry id ${reg.id} · created ${String(reg.created_at).slice(0, 10)}`
      : "not created yet", { mono: true });
  }
  kvRow(box, "Bulk load", st.loader && st.loader.bulk_load_running ? "running (tranche 1)" : "not running");
  if (st.constants) {
    kvRow(box, "Anchoring precompile", st.constants.precompile, { mono: true, copy: st.constants.precompile });
  }

  const vbox = clear($("about-versions"));
  if (st.versions) {
    kvRow(vbox, "Normalizer", st.versions.normalizer, { mono: true });
    kvRow(vbox, "Citation spec", st.versions.citation_spec, { mono: true });
    kvRow(vbox, "Record schema", st.versions.record_schema, { mono: true });
    kvRow(vbox, "Receipt schema", st.versions.receipt_schema, { mono: true, hint: "draft until Phase 4 locks v1" });
  }

  const tbody = clear($("coverage-table").querySelector("tbody"));
  (st.index && st.index.registries ? st.index.registries : []).forEach((r) => {
    const tr = el("tr");
    const t1 = el("td"); t1.appendChild(el("span", "cite-canon", r.registry)); tr.appendChild(t1);
    tr.appendChild(el("td", null, r.source === "chain-index" ? "chain index" : `corpus snapshot ${r.snapshot || ""}`));
    tr.appendChild(el("td", "num", (r.records || 0).toLocaleString("en-US")));
    const detail = r.source === "chain-index"
      ? `synced to block ${r.synced_block.toLocaleString("en-US")} at ${r.synced_at}`
      : (r.note || "CourtListener-derived snapshot");
    tr.appendChild(el("td", null, detail));
    tbody.appendChild(tr);
  });
  const receipts = st.registries && st.registries["receipts-v1"];
  if (receipts) {
    const tr = el("tr");
    const t1 = el("td"); t1.appendChild(el("span", "cite-canon", "receipts-v1")); tr.appendChild(t1);
    tr.appendChild(el("td", null, "live chain"));
    tr.appendChild(el("td", "num", "—"));
    tr.appendChild(el("td", null, receipts.exists
      ? `filing receipts · registry id ${receipts.id}`
      : "filing receipts · not created yet (one-time setup in the record step)"));
    tbody.appendChild(tr);
  }
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
  const title = el("div", "doc-title");
  title.appendChild(icon("i-doc"));
  title.appendChild(el("span", null, doc.filename || "document"));
  card.appendChild(title);
  const kv = el("div", "kv");
  kvRow(kv, "SHA-256", doc.sha256, { mono: true, copy: doc.sha256 });
  kvRow(kv, "Size", fmtBytes(doc.bytes));
  if (doc.extraction) {
    kvRow(kv, "Extraction", `${doc.extraction.method} · ${doc.extraction.chars.toLocaleString("en-US")} characters`);
  }
  card.appendChild(kv);
}

function renderCheck(report) {
  lastReport = report;
  docCard($("check-doc"), report.document);

  const chips = clear($("check-summary"));
  const oc = el("div", "sum-chip");
  oc.appendChild(el("span", "n", String(report.summary.occurrences)));
  oc.appendChild(el("span", "l", "occurrences"));
  chips.appendChild(oc);
  STATUS_ORDER.forEach((s) => {
    const n = report.summary.by_status[s] || 0;
    if (!n && s !== "VERIFIED" && s !== "NOT_FOUND") return;
    const c = el("div", `sum-chip sum-${s}`);
    c.appendChild(el("span", "n", String(n)));
    c.appendChild(el("span", "l", SUM_LABEL[s]));
    chips.appendChild(c);
  });

  const warnBox = clear($("check-warning"));
  if (report.document.extraction && report.document.extraction.warning) {
    warnBox.appendChild(calloutWarnNote("Extraction warning.", report.document.extraction.warning));
  }
  if (report.summary.name_mismatches > 0) {
    warnBox.appendChild(calloutWarnNote(
      "A party-name mismatch was detected.",
      `${report.summary.name_mismatches} verified citation(s) are attributed in the brief to a different case name than the registry records. A real citation paired with an invented case name is the other classic hallucination.`,
    ));
  }

  const tbody = clear($("check-table").querySelector("tbody"));
  report.citations.forEach((c) => {
    const tr = el("tr");
    const tdS = el("td"); tdS.appendChild(chipFor(c.status)); tr.appendChild(tdS);

    const tdC = el("td");
    tdC.appendChild(el("span", "cite-canon", c.canonical || c.as_written));
    if (c.canonical && c.as_written && c.as_written !== c.canonical) {
      tdC.appendChild(el("span", "cite-sub", `${c.as_written} (as written)`));
    }
    const partyBits = [c.plaintiff, c.defendant].filter(Boolean).join(" v. ");
    if (partyBits) tdC.appendChild(el("span", "cite-sub", partyBits + (c.year ? ` (${c.year})` : "")));
    if (c.reason) tdC.appendChild(el("span", "cite-reason", c.reason));
    tr.appendChild(tdC);

    const tdR = el("td");
    if (c.record && c.record.cases.length) {
      const primary = c.record.cases[0];
      const line = el("span", "reg-line");
      line.appendChild(el("span", "reg-name", primary.name || "(unnamed)"));
      if (primary.year) {
        line.appendChild(document.createTextNode(" "));
        line.appendChild(el("span", "reg-year", `(${primary.year})`));
      }
      tdR.appendChild(line);
      tdR.appendChild(regLink(c.record.uri, "CourtListener "));
      const extra = (c.record.cases.length - 1) + (c.record.more_cases || 0);
      if (extra > 0) {
        tdR.appendChild(el("span", "collision-note", `+${extra} more decision${extra > 1 ? "s" : ""} share this first page`));
      }
      tdR.appendChild(el("span", "source-tag", `${c.registry} · ${c.record.source}`));
    } else {
      tdR.appendChild(el("span", "cell-empty", "—"));
    }
    tr.appendChild(tdR);

    const tdN = el("td"); tdN.appendChild(nameMark(c.name_check)); tr.appendChild(tdN);
    tr.appendChild(el("td", "num", `${c.occurrences}×`));
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
  btn.className = "btn btn-outline btn-wallet";
  btn.disabled = false;
  if (!eth) {
    btn.textContent = "No wallet detected";
    btn.disabled = true;
    btn.title = "Install MetaMask (metamask.io) to record receipts. Checking and verifying never need a wallet.";
    wallet = { address: null, chainOk: false };
    syncRecordPanel();
    return;
  }
  const accounts = await eth.request({ method: "eth_accounts" }).catch(() => []);
  wallet.address = accounts[0] || null;
  if (wallet.address) {
    const chainHex = await eth.request({ method: "eth_chainId" }).catch(() => null);
    wallet.chainOk = chainHex && parseInt(chainHex, 16) === CHAIN_ID;
    btn.classList.add("connected");
    if (wallet.chainOk) {
      btn.textContent = shortHex(wallet.address, 5);
    } else {
      btn.classList.add("wrong-network");
      btn.textContent = `${shortHex(wallet.address, 5)} · wrong network`;
    }
  } else {
    wallet.chainOk = false;
    btn.textContent = "Connect wallet";
  }
  syncRecordPanel();
}

async function connectWallet() {
  const eth = providerOrNull();
  if (!eth) return;
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
  const rs = $("step-report-state");
  rs.textContent = haveDoc ? "done" : "not yet";
  rs.classList.toggle("ok", haveDoc);
  const ws = $("step-wallet-state");
  if (wallet.address && wallet.chainOk) { ws.textContent = shortHex(wallet.address, 5); ws.classList.add("ok"); }
  else if (wallet.address) { ws.textContent = "wrong network"; ws.classList.remove("ok"); }
  else { ws.textContent = "not yet"; ws.classList.remove("ok"); }
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
  hide("prepare-result", "prepare-error");
  clear($("anchor-status"));
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
  kvRow(meta, "Checked at block", p.chain.checked_at_block.toLocaleString("en-US"), { mono: true });
  kvRow(meta, "Registries", p.chain.registries.map((r) => `${r.name} (id ${r.id})`).join(" · "), { mono: true });
  kvRow(meta, "Schema", p.receipt.schema, { mono: true, hint: "draft until Phase 4 locks v1" });
  kvRow(meta, "Timestamp", p.receipt.timestamp, { mono: true, hint: "server clock; the chain time at anchoring is the authoritative timestamp" });

  const tbody = clear($("prepare-table").querySelector("tbody"));
  p.results.forEach((r) => {
    const differs = r.chain_status !== r.local_status;
    const tr = el("tr", differs ? "diff" : null);
    const tdC = el("td");
    tdC.appendChild(el("span", "cite-canon", r.canonical || r.as_written || "—"));
    if (r.registry) tdC.appendChild(el("span", "cite-sub", r.registry));
    tr.appendChild(tdC);
    const tdL = el("td"); tdL.appendChild(chipFor(r.local_status)); tr.appendChild(tdL);
    const tdK = el("td"); tdK.appendChild(chipFor(r.chain_status)); tr.appendChild(tdK);
    const tdN = el("td"); tdN.appendChild(nameMark(r.name_check)); tr.appendChild(tdN);
    const tdNote = el("td");
    if (differs) tdNote.appendChild(el("span", "diff-note", "differs from the local check — on-chain registry state is what the receipt records"));
    else tdNote.appendChild(el("span", "cell-empty", "—"));
    tr.appendChild(tdNote);
    tbody.appendChild(tr);
  });

  $("receipt-json").querySelector("code").textContent = p.receipt.json;

  const meter = $("size-meter");
  const pct = Math.min(100, (p.receipt.bytes / p.receipt.cap) * 100);
  meter.querySelector(".size-value").textContent =
    `${p.receipt.bytes.toLocaleString("en-US")} of ${p.receipt.cap.toLocaleString("en-US")} bytes`;
  const fill = meter.querySelector(".size-fill");
  fill.style.width = `${pct}%`; /* sanctioned CSSOM exception */
  const tight = p.receipt.bytes > p.receipt.cap * 0.85;
  fill.classList.toggle("tight", tight);
  const note = meter.querySelector(".size-note");
  note.className = "hint size-note" + (tight ? " tight-note" : "");
  const compaction = p.receipt.compactions.length ? `Compaction applied: ${p.receipt.compactions.join("; ")}.` : "";
  note.textContent = tight
    ? `Near the ${p.receipt.cap.toLocaleString("en-US")}-byte anchoring limit. ${compaction}`.trim()
    : compaction;

  const setupBox = $("setup-box");
  const probeBox = clear($("probe-box"));
  const anchorBtn = $("anchor-btn");
  anchorBtn.disabled = true;

  if (!p.receipts_registry.exists) {
    setupBox.classList.remove("hidden");
    const code = setupBox.querySelector("pre code");
    if (code) {
      code.textContent =
        `addRegistry("${p.setup.registry}",\n  ${JSON.stringify(p.setup.description)},\n  '${p.setup.metadata}')`;
    }
    const oldBtn = setupBox.querySelector("button");
    if (oldBtn) {
      const btn = oldBtn.cloneNode(true); // drops stale listeners
      oldBtn.replaceWith(btn);
      btn.addEventListener("click", createReceiptsRegistry);
    }
    const inner = setupBox.querySelector("div");
    const oldNote = inner.querySelector(".setup-probe-note");
    if (oldNote) oldNote.remove();
    if (p.setup.probe && !p.setup.probe.ok) {
      inner.appendChild(el("p", "hint setup-probe-note",
        `Note: creation simulated as failing for this wallet — ${p.setup.probe.message}`));
    }
  } else {
    setupBox.classList.add("hidden");
    const probe = p.write_probe || {};
    if (probe.ok) {
      const box = el("div", "probe-ok");
      box.appendChild(icon("i-shield"));
      const d = el("div");
      d.appendChild(el("strong", null, "This wallet may write to receipts-v1."));
      const para = el("p", null, "Simulation passed. Estimated cost: ");
      para.appendChild(el("span", "mono", `~${probe.gas.toLocaleString("en-US")} gas ≈ ${(probe.gas * 45e-9).toFixed(4)} wmantraUSD`));
      para.appendChild(document.createTextNode(" at 45 gwei."));
      d.appendChild(para);
      box.appendChild(d);
      probeBox.appendChild(box);
      anchorBtn.disabled = false;
    } else if (probe.kind === "unauthorized") {
      const box = el("div", "probe-bad");
      box.appendChild(icon("i-alert"));
      const d = el("div");
      d.appendChild(el("strong", null, "No editor rights on receipts-v1."));
      const para = el("p", null, "Chain writes are deny-by-default: this wallet cannot write to the receipts registry. Its admin (on this pilot, the wallet that created the registry) must run ");
      const regId = p.receipts_registry.id != null ? p.receipts_registry.id : "<registryId>";
      para.appendChild(el("span", "mono", `grantRole(${regId}, ${shortHex(wallet.address || "0x…", 5)}, "editor")`));
      para.appendChild(document.createTextNode(" once before anchoring."));
      d.appendChild(para);
      box.appendChild(d);
      probeBox.appendChild(box);
    } else {
      const box = el("div", "probe-bad");
      box.appendChild(icon("i-alert"));
      const d = el("div");
      d.appendChild(el("strong", null, "Write simulation failed."));
      d.appendChild(el("p", null, probe.message || "The dry-run transaction reverted. Check the chain status and try preparing again."));
      box.appendChild(d);
      probeBox.appendChild(box);
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
    if (err && err.code === 4001) {
      box.appendChild(calloutWarnNote(
        "Signature request declined in wallet.",
        "Nothing was sent and nothing was recorded. Press “Sign & anchor” again when ready.",
        "i-info",
      ));
    } else {
      box.appendChild(el("div", "error", `Wallet error: ${(err && err.message) || err}`));
    }
    return;
  }
  const wait = el("div", "txwait");
  wait.appendChild(el("span", "spinner"));
  const msg = el("span", null, "Submitted ");
  msg.appendChild(el("span", "mono", shortHex(hash, 8)));
  msg.appendChild(document.createTextNode(" — waiting for confirmation…"));
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
  clear(msg);
  msg.appendChild(document.createTextNode(`Still pending after 150 s — track it at ${EXPLORER}/tx/${hash}`));
}

async function createReceiptsRegistry() {
  if (!prepared || !prepared.setup) return;
  await sendTx(prepared.setup.tx, "anchor-status", (box, info) => {
    if (info.success) {
      const b = banner("ok", "i-seal", "receipts-v1 created",
        `Confirmed in block ${info.block.toLocaleString("en-US")} at ${info.block_time}. Re-preparing the receipt…`);
      box.appendChild(b);
      setTimeout(prepareReceipt, 1200);
    } else {
      box.appendChild(banner("bad", "i-alert", "Registry creation failed",
        "The creation transaction reverted. Check the chain status and try again."));
    }
  });
}

function anchorReceipt() {
  if (!prepared) return;
  return sendTx(prepared.tx, "anchor-status", (box, info, hash) => {
    if (!info.success) {
      const b = banner("bad", "i-alert", "Transaction reverted", "");
      const sub = b.querySelector(".rb-sub");
      sub.appendChild(document.createTextNode("Anchoring transaction "));
      sub.appendChild(el("span", "mono", shortHex(hash, 6)));
      sub.appendChild(document.createTextNode(" was mined but reverted. Nothing was recorded and no receipt exists. Re-run the write-permission probe and try again."));
      box.appendChild(b);
      return;
    }
    const b = banner("ok", "i-seal", "Verification recorded on NVNM Chain",
      "The receipt below is now immutable and publicly verifiable.");
    const kv = el("div", "kv");
    kvRow(kv, "Transaction", hash, { mono: true, copy: hash });
    kvRow(kv, "Block · time", `${info.block.toLocaleString("en-US")} · ${info.block_time}`, { mono: true, hint: "the immutable timestamp" });
    kvRow(kv, "Document SHA-256", lastReport ? lastReport.document.sha256 : "", { mono: true, copy: lastReport ? lastReport.document.sha256 : "" });
    if (info.gas_used) {
      kvRow(kv, "Gas", `${info.gas_used.toLocaleString("en-US")} @ ${info.gas_price_gwei} gwei (≈ ${(info.gas_used * info.gas_price_gwei * 1e-9).toFixed(4)} wmantraUSD)`, { mono: true });
    }
    b.appendChild(kv);
    const actions = el("div", "rb-actions");
    const a1 = el("a", "btn btn-outline", "View on Blockscout ");
    a1.href = `${EXPLORER}/tx/${hash}`; a1.target = "_blank"; a1.rel = "noopener";
    a1.appendChild(icon("i-linkout"));
    actions.appendChild(a1);
    const a2 = el("button", "btn btn-outline", "Verify it now (free lookup)"); a2.type = "button";
    a2.addEventListener("click", () => {
      activateTab("verify");
      $("hash-input").value = lastReport.document.sha256;
      lookupHash(lastReport.document.sha256);
    });
    actions.appendChild(a2);
    const a3 = el("button", "btn btn-outline", "Decode the transaction"); a3.type = "button";
    a3.addEventListener("click", () => { activateTab("inspect"); $("tx-input").value = hash; inspectTx(hash); });
    actions.appendChild(a3);
    b.appendChild(actions);
    box.appendChild(b);
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

function receiptCard(v, latestIndex, total) {
  const card = el("div", "receipt-card");
  const head = el("div", "rc-head");
  head.appendChild(el("span", "rc-when", `Recorded (chain time) ${v.chain_timestamp}`));
  head.appendChild(el("span", "rc-version", `record ${v.record_id} · version ${v.index} of ${latestIndex}`));
  card.appendChild(head);

  const r = v.receipt;
  const kv = el("div", "kv");
  if (r && typeof r === "object") {
    if (r.agent && r.agent.address) {
      const att = el("span");
      att.appendChild(el("span", "mono", r.agent.address));
      if (r.agent.kya_id) {
        att.appendChild(document.createTextNode("  ·  KYA "));
        att.appendChild(el("span", "mono", r.agent.kya_id));
      }
      kvRow(kv, "Attested by", att);
    }
    if (r.checked_at_block) kvRow(kv, "Checked at block", r.checked_at_block.toLocaleString("en-US"), { mono: true });
    if (r.normalizer_version) kvRow(kv, "Normalizer", r.normalizer_version, { mono: true });
    if (r.schema) kvRow(kv, "Schema", r.schema, { mono: true });
    card.appendChild(kv);

    if (Array.isArray(r.results)) {
      const counts = {};
      r.results.forEach((e) => { const w = STATUS_WORD[e.s] || "UNPARSEABLE"; counts[w] = (counts[w] || 0) + 1; });
      if (r.verified_omitted) counts.VERIFIED = (counts.VERIFIED || 0) + r.verified_omitted;
      const chips = el("div", "summary-chips");
      STATUS_ORDER.forEach((s) => {
        if (!counts[s]) return;
        const c = el("div", `sum-chip sum-${s}`);
        c.appendChild(el("span", "n", String(counts[s])));
        c.appendChild(el("span", "l", SUM_LABEL[s]));
        chips.appendChild(c);
      });
      card.appendChild(chips);

      const scroll = el("div", "table-scroll");
      const table = el("table", "cite-table");
      const thead = el("thead");
      const hr = el("tr");
      ["Status", "Citation", "Names", "Seen"].forEach((h, i) => {
        const th = el("th", i === 3 ? "num" : null, h);
        th.scope = "col";
        hr.appendChild(th);
      });
      thead.appendChild(hr); table.appendChild(thead);
      const tbody = el("tbody");
      r.results.forEach((e) => {
        const tr = el("tr");
        const tdS = el("td"); tdS.appendChild(chipFor(STATUS_WORD[e.s] || "UNPARSEABLE")); tr.appendChild(tdS);
        const tdC = el("td");
        tdC.appendChild(el("span", "cite-canon", e.c || e.w || "—"));
        if (e.w && e.c && e.w !== e.c) tdC.appendChild(el("span", "cite-sub", `${e.w} (as written)`));
        const regName = typeof e.g === "number" && r.registries && r.registries[e.g]
          ? r.registries[e.g].name : (typeof e.g === "string" ? e.g : null);
        if (regName) tdC.appendChild(el("span", "cite-sub", regName));
        if (e.k) tdC.appendChild(el("span", "cite-sub", `CourtListener cluster ${e.k}`));
        tr.appendChild(tdC);
        const tdN = el("td"); tdN.appendChild(nameMark(e.n)); tr.appendChild(tdN);
        tr.appendChild(el("td", "num", `${e.o || 1}×`));
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      scroll.appendChild(table);
      card.appendChild(scroll);

      const mismatches = r.results.filter((e) => e.n === "x").length;
      if (mismatches) {
        card.appendChild(el("p", "hint", `${mismatches} result(s) were flagged as a party-name MISMATCH at check time.`));
      }
      if (r.verified_omitted) {
        card.appendChild(el("p", "hint", `${r.verified_omitted} VERIFIED results were collapsed into a count in the on-chain record to fit the byte budget.`));
      }
    }
  } else {
    kvRow(kv, "Metadata", "did not parse as a receipt; raw payload below");
    card.appendChild(kv);
  }

  const det = el("details", "json-details");
  det.appendChild(el("summary", null, "Raw on-chain record"));
  const pre = el("pre", "codeblock");
  pre.appendChild(el("code", null, v.metadata_raw));
  det.appendChild(pre);
  card.appendChild(det);
  return card;
}

function renderLookup(res) {
  const box = clear($("verify-result"));

  if (!res.registry_exists) {
    const b = banner("warn", "i-info", "The receipts registry has not been created yet",
      "No receipts-v1 registry exists on this chain, so no receipts can exist for any document. This is expected early in the pilot; the record step offers the one-time setup.");
    box.appendChild(b);
  } else if (res.found) {
    const latestIndex = Math.max(...res.versions.map((v) => v.index));
    const b = banner("ok", "i-seal", "Receipt found for this fingerprint", "");
    const sub = b.querySelector(".rb-sub");
    sub.appendChild(document.createTextNode("Document "));
    sub.appendChild(el("span", "mono", `${res.sha256.slice(0, 12)}…${res.sha256.slice(-8)}`));
    sub.appendChild(document.createTextNode(
      ` has ${latestIndex} recorded citation-check receipt${latestIndex > 1 ? " versions" : ""} on NVNM Chain` +
      ` (chain head ${res.head_block.toLocaleString("en-US")} at lookup).`));
    box.appendChild(b);
    [...res.versions].sort((a, c) => c.index - a.index).forEach((v) => box.appendChild(receiptCard(v, latestIndex, res.versions.length)));
    box.appendChild(el("p", "honesty-line",
      "A receipt proves this exact document was citation-checked at a point in time — existence, not good law. Whether each authority still stands is the reader’s judgment."));
  } else {
    const b = banner("bad", "i-alert", "No receipt for this fingerprint",
      "No citation-check receipt exists on NVNM Chain for this exact file. Note: a one-byte change — re-saving, stamping, flattening — produces a different fingerprint and breaks the match. If you expected a receipt, confirm you have the file as filed.");
    const kv = el("div", "kv");
    kvRow(kv, "Fingerprint", res.sha256, { mono: true, copy: res.sha256 });
    kvRow(kv, "Chain head at lookup", res.head_block.toLocaleString("en-US"), { mono: true });
    b.appendChild(kv);
    box.appendChild(b);
  }

  if (res.proof) {
    const curl = `curl -s -X POST ${RPC_URL} \\\n  -H 'Content-Type: application/json' \\\n  -H 'User-Agent: nvnm-cite-verify' \\\n  -d '${JSON.stringify({ jsonrpc: "2.0", id: 1, method: res.proof.request.method, params: res.proof.request.params })}'`;
    $("replay-curl").textContent = curl;
    $("replay-details").classList.remove("hidden");
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
  $("hash-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("hash-lookup").click(); });
}

/* ---------- inspect ---------- */

const DECODE_HINTS = {
  "cite-canonical-v1": "the citation string itself — stored as plaintext",
  sha256: "the checked document’s fingerprint",
};

function renderInspect(info) {
  const box = clear($("inspect-result"));
  if (!info.found) {
    box.appendChild(banner("warn", "i-info", "Transaction not found",
      `No transaction with this hash exists on chain ${CHAIN_ID}. It may belong to another network, or it may not have been broadcast.`));
    show("inspect-result");
    return;
  }

  const kv = el("div", "kv");
  const st = el("span");
  if (info.pending) st.appendChild(el("span", "tx-status-pending", "Pending — not yet mined"));
  else if (info.success) st.appendChild(el("span", "tx-status-ok", "Confirmed"));
  else st.appendChild(el("span", "tx-status-bad", "✗ REVERTED"));
  kvRow(kv, "Status", st);
  if (info.block) kvRow(kv, "Block · time", `${info.block.toLocaleString("en-US")} · ${info.block_time}`, { mono: true });
  kvRow(kv, "From", info.from, { mono: true, copy: info.from });
  const to = el("span");
  to.appendChild(el("span", "mono", info.to || "—"));
  if (info.is_anchoring_precompile) to.appendChild(el("span", "precompile-tag", "NVNM anchoring precompile"));
  kvRow(kv, "To", to);
  if (info.gas_used) {
    kvRow(kv, "Gas", `${info.gas_used.toLocaleString("en-US")} @ ${info.gas_price_gwei} gwei (≈ ${(info.gas_used * info.gas_price_gwei * 1e-9).toFixed(4)} wmantraUSD)`, { mono: true });
  }
  box.appendChild(kv);

  const d = info.decoded;
  if (d && d.function) {
    const sec = el("div", "decoded-section");
    sec.appendChild(el("h3", "overline", "Decoded"));
    sec.appendChild(el("span", "decoded-fn", `${d.function}()`));
    const dkv = el("div", "kv");
    if (d.function === "addRecord" && d.args && d.args.record) {
      const rec = d.args.record;
      kvRow(dkv, "registry", rec.registry, { mono: true });
      kvRow(dkv, "uri", rec.uri, { mono: true });
      kvRow(dkv, "checksum", rec.checksum, { mono: true, hint: DECODE_HINTS[rec.checksumAlgo] });
      kvRow(dkv, "checksumAlgo", rec.checksumAlgo, { mono: true });
      kvRow(dkv, "status", rec.status, { mono: true });
      sec.appendChild(dkv);
      sec.appendChild(el("h3", "overline", "Metadata"));
      const pre = el("pre", "codeblock");
      pre.appendChild(el("code", null, d.metadata_json ? JSON.stringify(d.metadata_json, null, 2) : rec.metadata));
      sec.appendChild(pre);
    } else if (d.function === "addRegistry" && d.args) {
      kvRow(dkv, "name", d.args.name, { mono: true });
      kvRow(dkv, "description", d.args.description);
      sec.appendChild(dkv);
      sec.appendChild(el("h3", "overline", "Metadata"));
      const pre = el("pre", "codeblock");
      pre.appendChild(el("code", null, d.metadata_json ? JSON.stringify(d.metadata_json, null, 2) : String(d.args.metadata || "")));
      sec.appendChild(pre);
    } else if (d.function === "grantRole" && d.args) {
      kvRow(dkv, "registryId", String(d.args.registryId), { mono: true });
      kvRow(dkv, "account", d.args.account, { mono: true });
      kvRow(dkv, "role", d.args.role, { mono: true });
      if (d.args.checksum) kvRow(dkv, "checksum", d.args.checksum, { mono: true });
      sec.appendChild(dkv);
    } else {
      Object.entries(d.args || {}).forEach(([k, v]) => {
        if (typeof v !== "object" || v === null) kvRow(dkv, k, String(v), { mono: true });
      });
      sec.appendChild(dkv);
    }
    box.appendChild(sec);
  } else if (d) {
    const sec = el("div", "decoded-section");
    sec.appendChild(el("h3", "overline", "Decoded"));
    const c = el("div", "callout");
    c.appendChild(icon("i-info"));
    const dd = el("div");
    dd.appendChild(el("strong", null, `Unknown function selector ${d.selector}.`));
    dd.appendChild(el("p", null,
      info.is_anchoring_precompile
        ? "This transaction calls the anchoring precompile but does not match any nvnm-cite function signature. The raw calldata is shown below, unframed."
        : "This transaction does not target the anchoring precompile, and its selector does not match any nvnm-cite function signature."));
    c.appendChild(dd);
    sec.appendChild(c);
    if (info.input_preview) {
      const pre = el("pre", "codeblock");
      pre.appendChild(el("code", null, info.input_preview));
      sec.appendChild(pre);
    }
    box.appendChild(sec);
  }

  const c2 = el("div", "callout");
  c2.appendChild(icon("i-info"));
  const d2 = el("div");
  d2.appendChild(el("strong", null, "Why block explorers show garbled text"));
  d2.appendChild(el("p", null, "The record is plaintext, but it travels inside ABI encoding — length prefixes and 32-byte padding. A generic explorer’s UTF-8 view renders that framing as noise. This decoder strips the framing; what remains is exactly the text above."));
  c2.appendChild(d2);
  box.appendChild(c2);

  const link = el("p");
  link.appendChild(regLink(info.explorer, "View on Blockscout "));
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
