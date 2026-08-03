"use strict";
/* NVNM Cite web app.
 *
 * Trust model in one paragraph: this page never sees a private key and
 * never encodes chain data itself. The local server prepares calldata
 * with the project's golden-tested codec; the user's wallet signs; the
 * chain decides. Dynamic data (case names, chain metadata) is rendered
 * exclusively via textContent — never innerHTML.
 *
 * Network identity (chain id, RPC, explorer, gas token) is SERVER-FED via
 * /api/status's `network` block — nothing chain-specific is hardcoded
 * here, so the same page serves mainnet (the production default) and
 * testnet. Wallet actions are gated until that block has loaded.
 *
 * Anchoring v1.2.0: registry names are NOT unique on chain; the numeric
 * registry #id is the canonical reference. The discovery line on a filing
 * carries the #id, and a NEW registry's id exists only after its creation
 * tx confirms (recovered from the AddRegistry event via /api/tx), so the
 * record flow is: setup tx → confirmed #id → re-prepare → anchor.
 *
 * DOM vocabulary (classes/shapes) follows the 2026-06-12 design handoff
 * plus the round-2 contract delta (the r2 bundle, 2026-07; in git history
 * and DECISIONS 2026-07-15): verdict banner, severity-grouped table with
 * a NOT COVERED disclosure, chips-as-filters, the registry-line step,
 * wallet callouts, stepper tones, sticky tab bar, and coverage states.
 */

let NET = null;  // /api/status `network` block; null until the first load
let EXPLORER = "";
let RPC_URL = "";

function netChainId() { return NET ? NET.chain_id : null; }

function chainParams() {
  // wallet_addEthereumChain params, built from the server-fed network block.
  return {
    chainId: NET.chain_id_hex,
    chainName: NET.key === "mainnet" ? "NVNM Chain" : "NVNM Chain Testnet",
    nativeCurrency: {
      name: NET.gas_token.name,
      symbol: NET.gas_token.symbol,
      decimals: NET.gas_token.decimals,
    },
    rpcUrls: [NET.public_rpc],
    blockExplorerUrls: [NET.explorer],
  };
}

function gasCostText(gas, priceGwei) {
  const gwei = priceGwei || (NET && NET.gas_price_gwei) || 40;
  const token = NET ? NET.gas_token.symbol : "";
  return `~${gas.toLocaleString("en-US")} gas ≈ ${(gas * gwei * 1e-9).toFixed(4)} ${token} at ${gwei} gwei`;
}

const STATUS_ORDER = ["VERIFIED", "NOT_FOUND", "NOT_COVERED", "AMBIGUOUS_JURISDICTION", "UNPARSEABLE"];
/* Severity order for the regrouped results table (round 2, P0-1); NOT_COVERED
   renders last behind a disclosure row. */
const SEVERITY_ORDER = ["NOT_FOUND", "AMBIGUOUS_JURISDICTION", "UNPARSEABLE", "VERIFIED"];
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
// Receipt summary tally keys ↔ the five statuses (receipts/schema.py TALLY_KEYS).
const TALLY_STATUS = {
  VERIFIED: "verified", NOT_FOUND: "not_found", NOT_COVERED: "not_covered",
  AMBIGUOUS_JURISDICTION: "ambiguous", UNPARSEABLE: "unparseable",
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

/* Non-identifying status tally → summary chips (shared by the receipt
   preview and the verify view). `summary` is the locked receipt tally. */
function renderTally(box, summary) {
  clear(box);
  const total = el("div", "sum-chip");
  total.appendChild(el("span", "n", String(summary.checked)));
  total.appendChild(el("span", "l", "checked"));
  box.appendChild(total);
  STATUS_ORDER.forEach((s) => {
    const n = summary[TALLY_STATUS[s]] || 0;
    if (!n && s !== "VERIFIED" && s !== "NOT_FOUND") return;
    const c = el("div", `sum-chip sum-${s}`);
    c.appendChild(el("span", "n", String(n)));
    c.appendChild(el("span", "l", SUM_LABEL[s]));
    box.appendChild(c);
  });
  if (summary.name_mismatches) {
    const c = el("div", "sum-chip sum-NOT_FOUND");
    c.appendChild(el("span", "n", String(summary.name_mismatches)));
    c.appendChild(el("span", "l", "name mismatch"));
    box.appendChild(c);
  }
  return box;
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
  // Always create .rb-sub (empty when no subText): several callers build a
  // banner with no subText, then append rich content into .rb-sub.
  b.appendChild(el("p", "rb-sub", subText || ""));
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

async function apiPostBytes(path, bytes, filename, extraHeaders) {
  const res = await fetch(path, {
    method: "POST",
    headers: Object.assign(
      { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(filename || "upload") },
      extraHeaders || {},
    ),
    body: bytes,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}

/* ---------- state ---------- */

let lastReport = null;   // last /api/check report (page memory only)
let lastFile = null;     // {bytes, name} of the last checked file (re-sent to prepare a receipt)
let lastSource = "file"; // "file" | "paste" | "sample" — drives the paste warning + sample tag
let prepared = null;     // last /api/receipt/prepare response
let chosenRegistryId = null; // pinned receipts-registry #id (picker choice or post-create)
let wallet = { address: null, chainOk: false, detected: false };
let filterSet = new Set();      // statuses the summary-chip filters keep visible
let coveredExpanded = false;    // NOT COVERED disclosure state

/* ---------- tabs (sticky bar + overflow cues, round 2 P1-3/P1-4) ---------- */

const tabsEl = document.getElementById("tabs");
const tabsShell = tabsEl.parentElement;   // .tabs-shell
const tabsBar = tabsShell.parentElement;  // .tabs-bar

function scrollActiveTabIntoView() {
  const t = tabsEl.querySelector(".tab.active");
  if (!t) return;
  tabsEl.scrollLeft = Math.max(0, t.offsetLeft - (tabsEl.clientWidth - t.offsetWidth) / 2);
}

function updStuck() {
  tabsBar.classList.toggle("stuck", tabsBar.getBoundingClientRect().top <= 0 && window.scrollY > 0);
}

function updFades() {
  const max = tabsEl.scrollWidth - tabsEl.clientWidth;
  tabsShell.setAttribute("data-fade-l", tabsEl.scrollLeft > 4 ? "1" : "0");
  tabsShell.setAttribute("data-fade-r", max - tabsEl.scrollLeft > 4 ? "1" : "0");
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((t) => {
    const active = t.dataset.tab === name;
    t.classList.toggle("active", active);
    t.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
  if (history.replaceState) history.replaceState(null, "", `#${name}`);
  scrollActiveTabIntoView();
  updFades();
}

function initTabs() {
  tabsEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (btn) activateTab(btn.dataset.tab);
  });
  const fromHash = location.hash.replace("#", "");
  if (["check", "record", "verify", "inspect", "about"].includes(fromHash)) activateTab(fromHash);
  window.addEventListener("scroll", updStuck, { passive: true });
  tabsEl.addEventListener("scroll", updFades, { passive: true });
  window.addEventListener("resize", updFades);
  updFades();
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
  if (st.network) {
    NET = st.network;
    EXPLORER = NET.explorer;
    RPC_URL = (NET.rpc_urls && NET.rpc_urls[0]) || NET.public_rpc;
  } else if (st.constants) {
    if (st.constants.explorer) EXPLORER = st.constants.explorer;
    if (st.constants.rpc_url) RPC_URL = st.constants.rpc_url;
  }

  // Network badge (next to the wordmark): mainnet vs testnet, server-fed.
  const netBadge = $("net-badge");
  if (netBadge && NET) {
    netBadge.textContent = NET.key === "mainnet" ? "Mainnet" : "Testnet";
    netBadge.className = "badge " + (NET.key === "mainnet" ? "badge-mainnet" : "badge-testnet");
  }

  const badge = $("chain-badge");
  if (st.chain && st.chain.rpc_ok) {
    badge.textContent = `chain ${st.chain.chain_id} · block ${st.chain.head_block.toLocaleString("en-US")}`;
    badge.className = st.chain.chain_id_ok ? "badge badge-ok" : "badge badge-bad";
  } else {
    badge.textContent = "chain RPC unreachable";
    badge.className = "badge badge-bad";
  }
  // The wallet button may have rendered before the network block arrived.
  refreshWalletState();

  const bannerBox = $("global-banner");
  const notes = [];
  if (st.loader && st.loader.bulk_load_running) {
    notes.push("Registry bulk load in progress: the on-chain registries are still filling, so a live check may show NOT FOUND for a real citation until it completes.");
  }
  if (notes.length) { bannerBox.textContent = notes.join("  ·  "); bannerBox.classList.remove("hidden"); }
  else { bannerBox.classList.add("hidden"); }

  // Telemetry disclosure (item 2b): shown in the Check privacy callout only when
  // the operator has turned it on (off by default).
  const telNote = $("check-telemetry-note");
  if (telNote) {
    if (st.telemetry && st.telemetry.enabled) {
      telNote.textContent = "As the RPC operator we also keep aggregate, by-citation lookup counts — to see which cases are checked most. These counts are never tied to your document or to who asked.";
      telNote.classList.remove("hidden");
    } else {
      telNote.classList.add("hidden");
    }
  }

  // Footer network line (server-fed; nothing hardcoded).
  const footChain = $("footer-chain");
  if (footChain && NET) {
    footChain.textContent = `${NET.label} · chain id ${NET.chain_id}`;
  }

  // About panel: live status
  const box = clear($("about-status"));
  if (NET) kvRow(box, "Network", NET.label, { mono: true });
  if (st.chain && st.chain.rpc_ok) {
    const rpcV = el("span");
    rpcV.appendChild(el("span", "mono", RPC_URL));
    rpcV.appendChild(document.createTextNode("  ·  responding"));
    kvRow(box, "RPC", rpcV);
    kvRow(box, "Chain id", `${st.chain.chain_id} (expected ${st.chain.expected_chain_id})`, { mono: true });
    kvRow(box, "Head block", st.chain.head_block.toLocaleString("en-US"), { mono: true });
    if (NET && NET.gas_price_gwei) {
      kvRow(box, "Gas price", `${NET.gas_price_gwei} gwei (${NET.gas_token.symbol})`, { mono: true });
    }
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
    kvRow(vbox, "Receipt schema", st.versions.receipt_schema, { mono: true });
  }

  renderCoverage(st);
}

/* Coverage rendering: the authoritative coverage figure is the pinned
   registry MANIFEST (st.coverage — creator-verified name→id map; 2,114
   registries on mainnet). The local-index table below it shows only the
   locally synced/mirrored subset, honestly labeled. */
function renderCoverage(st) {
  const rows = st.index && st.index.registries ? st.index.registries : [];
  const liveNames = Object.keys(st.registries || {});
  const coveredNames = rows.length ? rows.map((r) => r.registry) : liveNames;
  const manifest = st.coverage || null;
  const covSummary = manifest && manifest.count > 2
    ? `${manifest.count.toLocaleString("en-US")} US court registries`
    : coveredNames.join(", ");

  const legendCov = $("legend-coverage");
  if (legendCov && covSummary) legendCov.textContent = covSummary;

  const tbody = clear($("coverage-table").querySelector("tbody"));
  const lede = $("about-coverage-lede");
  const emptyBox = $("coverage-empty");
  let totalRecords = 0;
  let snapshot = "";

  if (rows.length) {
    emptyBox.classList.add("hidden");
    rows.forEach((r) => {
      totalRecords += r.records || 0;
      if (r.snapshot) snapshot = r.snapshot;
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
    if (lede) {
      const manifestBit = manifest && manifest.count > 2
        ? `NVNM Cite checks against ${manifest.count.toLocaleString("en-US")} US court registries on NVNM Chain ` +
          `(pinned name→id manifest, block ${Number(manifest.generated_at_block || 0).toLocaleString("en-US")}). `
        : "";
      lede.textContent =
        manifestBit +
        `This instance additionally mirrors ${totalRecords.toLocaleString("en-US")} citation keys across ` +
        `${rows.length} locally synced ${rows.length === 1 ? "registry" : "registries"} (${coveredNames.join(", ")})` +
        (snapshot ? `, from CourtListener public bulk data (snapshot ${snapshot})` : "") +
        ". Citations to courts without a registry are reported honestly as “not covered” rather than guessed at.";
    }
  } else {
    // No local index on this instance: honest state, never "loading".
    emptyBox.classList.toggle("hidden", liveNames.length === 0 && !(manifest && manifest.count));
    liveNames.forEach((name) => {
      const reg = st.registries[name];
      const tr = el("tr");
      const t1 = el("td"); t1.appendChild(el("span", "cite-canon", name)); tr.appendChild(t1);
      tr.appendChild(el("td", null, "live sentinel probe"));
      tr.appendChild(el("td", "num", "—"));
      tr.appendChild(el("td", null, reg.exists
        ? `registry id ${reg.id} · created ${String(reg.created_at).slice(0, 10)}`
        : "not created yet"));
      tbody.appendChild(tr);
    });
    if (lede) {
      lede.textContent = manifest && manifest.count
        ? `NVNM Cite checks against ${manifest.count.toLocaleString("en-US")} US court registries on NVNM Chain ` +
          `(pinned name→id manifest, block ${Number(manifest.generated_at_block || 0).toLocaleString("en-US")}). ` +
          "Lookups read the chain live; this instance keeps no local mirror. Citations to courts without a " +
          "registry are reported honestly as “not covered”."
        : (liveNames.length
          ? "This instance has no local index, so citation-key counts are unavailable; the registries below are read live from the chain and lookups are unaffected."
          : "The chain RPC is unreachable, so coverage cannot be shown right now.");
    }
  }

  // Check-tab scope line (server-filled from the manifest).
  const scope = $("coverage-scope");
  if (scope && manifest && manifest.count) {
    scope.textContent = manifest.count > 2
      ? `the canonical citation record of ${manifest.count.toLocaleString("en-US")} US court registries`
      : `the canonical record across ${coveredNames.join(", ")} during the pilot`;
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

function docCard(box, doc, source) {
  const card = clear(box);
  const title = el("div", "doc-title");
  title.appendChild(icon("i-doc"));
  title.appendChild(el("span", null, doc.filename || "document"));
  if (source === "sample") title.appendChild(el("span", "sample-tag", "sample document"));
  card.appendChild(title);
  const kv = el("div", "kv");
  kvRow(kv, "SHA-256", doc.sha256, { mono: true, copy: doc.sha256 });
  kvRow(kv, "Size", fmtBytes(doc.bytes));
  if (doc.extraction) {
    kvRow(kv, "Extraction", `${doc.extraction.method} · ${doc.extraction.chars.toLocaleString("en-US")} characters`);
  }
  card.appendChild(kv);
}

/* Progress affordance (round 2, P1-2). Indeterminate until the server can
   stream per-citation progress; the determinate mode is wired and waiting
   ("Checking citation 12 of 63…" + #check-progress-fill width, sanctioned
   CSSOM exception #2). */
function setCheckProgress(on, done, total) {
  const box = $("check-progress");
  box.classList.toggle("hidden", !on);
  if (!on) return;
  const bar = box.querySelector(".progress-bar");
  const fill = $("check-progress-fill");
  if (Number.isFinite(done) && Number.isFinite(total) && total > 0) {
    bar.classList.remove("indeterminate");
    $("check-progress-text").textContent = `Checking citation ${done} of ${total} against NVNM Chain…`;
    fill.style.width = `${Math.round((done / total) * 100)}%`;
  } else {
    bar.classList.add("indeterminate");
    $("check-progress-text").textContent = "Checking citations against NVNM Chain…";
    fill.style.width = "";
  }
}

/* Verdict banner (round 2, P0-1): the result view leads with the answer the
   lawyer came for. Red repeats the NOT_FOUND rows so they are never scrolled
   for; green stays honest about coverage; amber makes no claim either way. */
function buildVerdict(report) {
  const box = clear($("check-verdict"));
  if (!report || !report.citations.length) return;
  const counts = report.summary.by_status;
  const nf = report.citations.filter((c) => c.status === "NOT_FOUND");
  const nVerified = counts.VERIFIED || 0;
  const nOutside = counts.NOT_COVERED || 0;

  const v = el("div", "verdict");
  const head = el("div", "verdict-head");
  const body = el("div");
  const title = el("div", "verdict-title");
  const sub = el("p", "verdict-sub");
  body.appendChild(title);
  body.appendChild(sub);

  if (nf.length > 0) {
    v.classList.add("verdict-bad");
    head.appendChild(icon("i-alert"));
    title.textContent = `${nf.length} ${nf.length === 1 ? "citation" : "citations"} could not be found — review ${nf.length === 1 ? "it" : "these"} before filing.`;
    title.setAttribute("data-print", `${nf.length} NOT FOUND`);
    // Honesty tiering (v1.2.0 full coverage): a miss in the pilot-proven
    // federal-appellate registries reads as presumptively fabricated; a miss
    // in newly-expanded coverage is a flag to verify, never proof.
    const nExpanded = nf.filter((c) => c.confidence === "expanded-coverage").length;
    if (nExpanded === 0) {
      sub.textContent = "No registry record exists. Treat as presumptively fabricated until proven otherwise.";
    } else if (nExpanded === nf.length) {
      sub.textContent = "No registry record exists — but all of these are in newly-expanded coverage, where citation formats are still being proven. Verify each yourself; never delete a citation on this signal alone.";
    } else {
      sub.textContent = `No registry record exists. ${nExpanded} of these are in newly-expanded coverage (marked below) — treat those as flags to verify, never proof of fabrication.`;
    }
    head.appendChild(body);
    v.appendChild(head);
    const list = el("div", "verdict-list");
    nf.forEach((c) => {
      const item = el("div", "verdict-item");
      item.appendChild(el("span", "vc-cite", c.canonical || c.as_written));
      item.appendChild(el("span", "vc-reason",
        (c.reason || "") + (c.confidence === "expanded-coverage" ? " · newly-expanded coverage — verify, don't assume" : "")));
      list.appendChild(item);
    });
    v.appendChild(list);
  } else if (nVerified > 0) {
    v.classList.add("verdict-ok");
    head.appendChild(icon("i-seal"));
    title.textContent = "Every covered citation verified.";
    title.setAttribute("data-print", "ALL VERIFIED");
    const verifiedBit = `${nVerified} ${nVerified === 1 ? "citation has" : "citations have"} a registry record. `;
    sub.textContent = nOutside > 0
      ? verifiedBit + `${nOutside} ${nOutside === 1 ? "citation is" : "citations are"} outside pilot coverage — no conclusion either way. Existence only; good-law status remains your judgment.`
      : verifiedBit + "Existence only; good-law status remains your judgment.";
    head.appendChild(body);
    v.appendChild(head);
  } else {
    v.classList.add("verdict-warn");
    head.appendChild(icon("i-info"));
    title.textContent = "No covered citations to verify.";
    title.setAttribute("data-print", "OUTSIDE COVERAGE");
    sub.textContent = "Every citation found is outside pilot coverage or could not be read as a citation. The check makes no claim either way about this document.";
    head.appendChild(body);
    v.appendChild(head);
  }
  box.appendChild(v);
}

/* Summary chips as filters (round 2, P0-1): pressing a status chip narrows
   the table to the kept statuses; occurrences stays a plain stat. */
function buildSummaryChips(report) {
  const chips = clear($("check-summary"));
  const oc = el("div", "sum-chip");
  oc.appendChild(el("span", "n", String(report.summary.occurrences)));
  oc.appendChild(el("span", "l", "occurrences"));
  chips.appendChild(oc);
  STATUS_ORDER.forEach((s) => {
    const n = report.summary.by_status[s] || 0;
    if (!n && s !== "VERIFIED" && s !== "NOT_FOUND") return;
    const canFilter = n > 0;
    const c = el(canFilter ? "button" : "div", `sum-chip sum-${s}`);
    if (canFilter) {
      c.type = "button";
      c.setAttribute("aria-pressed", filterSet.has(s) ? "true" : "false");
      c.addEventListener("click", () => {
        if (filterSet.has(s)) filterSet.delete(s);
        else filterSet.add(s);
        if (filterSet.has("NOT_COVERED")) coveredExpanded = true;
        renderCheckTable(report);
        buildSummaryChips(report);
      });
    }
    c.appendChild(el("span", "n", String(n)));
    c.appendChild(el("span", "l", SUM_LABEL[s]));
    chips.appendChild(c);
  });
  // 1.2.0 accounting chips: what the table deliberately excludes is still
  // counted, never silently dropped.
  const refs = report.unresolved_references;
  if (refs && refs.count) {
    const c = el("div", "sum-chip");
    c.title = refs.note;
    c.appendChild(el("span", "n", String(refs.count)));
    c.appendChild(el("span", "l", "Id./supra unresolved"));
    chips.appendChild(c);
  }
  const sections = report.summary.law_sections_out_of_scope;
  if (sections && sections.count) {
    const c = el("div", "sum-chip");
    c.title = "Statute and regulation section references. Registries hold case citations only.";
    c.appendChild(el("span", "n", String(sections.count)));
    c.appendChild(el("span", "l", "§ out of scope"));
    chips.appendChild(c);
  }
}

function checkRow(c, collapsed) {
  const tr = el("tr", collapsed ? "row-collapsed" : null);
  tr.dataset.status = c.status;
  const tdS = el("td"); tdS.appendChild(chipFor(c.status)); tr.appendChild(tdS);

  const tdC = el("td");
  tdC.appendChild(el("span", "cite-canon", c.canonical || c.as_written));
  if (c.canonical && c.as_written && c.as_written !== c.canonical) {
    tdC.appendChild(el("span", "cite-sub", `${c.as_written} (as written)`));
  }
  const partyBits = [c.plaintiff, c.defendant].filter(Boolean).join(" v. ");
  if (partyBits) {
    // Round 2, P1-7: the brief-side attribution (eyecite's loose metadata) is
    // labeled so a discrepancy reads as the brief's, not the registry's.
    tdC.appendChild(el("span", "attr-label", "as attributed in the brief"));
    tdC.appendChild(el("span", "cite-sub", partyBits + (c.year ? ` (${c.year})` : "")));
  }
  if (c.reason) tdC.appendChild(el("span", "cite-reason", c.reason));
  if (c.caution) tdC.appendChild(el("span", "cite-caution", "⚠ " + c.caution));
  if (c.parallels && c.parallels.length) {
    // 1.2.0: one authority cited by several reporters in a run renders as
    // one row; the other members stay visible here, never hidden.
    tdC.appendChild(el("span", "attr-label", "parallel citations of this authority"));
    c.parallels.forEach((p) => {
      tdC.appendChild(el("span", "cite-sub",
        `${p.canonical || p.as_written} · ${SUM_LABEL[p.status] || p.status}`));
    });
  }
  if (c.snippet) {
    const sn = el("span", "cite-snippet");
    sn.appendChild(el("span", "snip-label", "source text"));
    sn.appendChild(document.createTextNode(c.snippet));
    tdC.appendChild(sn);
  }
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
  return tr;
}

/* Severity-grouped table (round 2, P0-1): NOT_FOUND first, NOT_COVERED
   collapsed behind a disclosure row; chip filters hide rows via
   .row-filtered (print forces both visible). */
function renderCheckTable(report) {
  const tbody = clear($("check-table").querySelector("tbody"));
  const rows = report.citations;
  const filtered = (s) => filterSet.size > 0 && !filterSet.has(s);

  SEVERITY_ORDER.forEach((s) => {
    rows.filter((c) => c.status === s).forEach((c) => {
      const tr = checkRow(c, false);
      if (filtered(s)) tr.classList.add("row-filtered");
      tbody.appendChild(tr);
    });
  });

  const covered = rows.filter((c) => c.status === "NOT_COVERED");
  if (covered.length > 0 && !filtered("NOT_COVERED")) {
    const trG = el("tr", "group-row");
    const td = el("td");
    td.colSpan = 5;
    const btn = el("button", "group-btn");
    btn.type = "button";
    btn.setAttribute("aria-expanded", coveredExpanded ? "true" : "false");
    btn.appendChild(chipFor("NOT_COVERED"));
    btn.appendChild(el("span", null,
      `${covered.length} ${covered.length === 1 ? "citation" : "citations"} outside pilot coverage — ${coveredExpanded ? "hide" : "show"}`));
    btn.addEventListener("click", () => { coveredExpanded = !coveredExpanded; renderCheckTable(report); });
    td.appendChild(btn);
    trG.appendChild(td);
    tbody.appendChild(trG);
    covered.forEach((c) => tbody.appendChild(checkRow(c, !coveredExpanded)));
  }
}

function renderCheck(report) {
  lastReport = report;
  filterSet = new Set();
  coveredExpanded = false;
  docCard($("check-doc"), report.document, lastSource);

  const empty = report.citations.length === 0;
  buildVerdict(empty ? null : report);
  $("check-empty").classList.toggle("hidden", !empty);
  $("check-summary").classList.toggle("hidden", empty);
  $("check-table").closest(".table-scroll").classList.toggle("hidden", empty);
  document.querySelector("#panel-check .legend").classList.toggle("hidden", empty);
  document.querySelector("#panel-check .next-step").classList.toggle("hidden", empty);

  const warnBox = clear($("check-warning"));
  if (report.document.extraction && report.document.extraction.warning) {
    warnBox.appendChild(calloutWarnNote("Extraction warning.", report.document.extraction.warning));
  }
  if (!empty && report.summary.name_mismatches > 0) {
    warnBox.appendChild(calloutWarnNote(
      "A party-name mismatch was detected.",
      `${report.summary.name_mismatches} verified citation(s) are attributed in the brief to a different case name than the registry records. A real citation paired with an invented case name is the other classic hallucination.`,
    ));
  }

  if (!empty) {
    buildSummaryChips(report);
    renderCheckTable(report);
  }

  // Replay affordance (item 0 / 4.5a): each keyed citation carries the exact
  // eth_call, so the verdict is non-repudiable — anyone re-runs it.
  const replayList = clear($("check-replay-list"));
  const replayable = report.citations.filter((c) => c.query);
  if (replayable.length) {
    replayable.forEach((c) => {
      const item = el("div", "replay-item");
      const lbl = el("div");
      lbl.appendChild(el("span", "cite-canon", c.canonical || c.as_written));
      if (c.registry) lbl.appendChild(el("span", "cite-sub", c.registry));
      item.appendChild(lbl);
      const pre = el("pre", "codeblock");
      pre.appendChild(el("code", null, JSON.stringify({ method: c.query.method, params: c.query.params })));
      item.appendChild(pre);
      replayList.appendChild(item);
    });
    $("check-replay").classList.remove("hidden");
  } else {
    $("check-replay").classList.add("hidden");
  }

  setCheckProgress(false);
  hide("check-error");
  show("check-result");
  syncRecordPanel();
}

async function runCheck(bytes, filename, source) {
  hide("check-result", "check-error");
  setCheckProgress(true);
  try {
    const report = await apiPostBytes("/api/check", bytes, filename);
    lastFile = { bytes, name: filename };  // retained in page memory to prepare a receipt
    lastSource = source || "file";
    prepared = null;           // a new document invalidates any prepared receipt
    chosenRegistryId = null;   // ...and any pinned registry choice
    renderCheck(report);
  } catch (err) {
    setCheckProgress(false);
    showError("check-error", err);
  }
}

async function runSample() {
  hide("check-result", "check-error");
  setCheckProgress(true);
  try {
    const res = await fetch("/sample-mata-avianca.txt");
    if (!res.ok) throw new Error(`could not load the bundled sample (${res.status})`);
    const bytes = await res.arrayBuffer();
    await runCheck(bytes, "mata-v-avianca-sample.txt", "sample");
  } catch (err) {
    setCheckProgress(false);
    showError("check-error", err);
  }
}

function initCheck() {
  wireDropzone("check-drop", "check-file", async (f) => runCheck(await f.arrayBuffer(), f.name, "file"));
  $("paste-toggle").addEventListener("click", () => $("paste-area").classList.toggle("hidden"));
  $("paste-check").addEventListener("click", () => {
    const text = $("paste-text").value;
    if (text.trim()) runCheck(new TextEncoder().encode(text), "pasted-text.txt", "paste");
  });
  $("sample-run").addEventListener("click", runSample);
  $("to-record").addEventListener("click", () => activateTab("record"));
}

/* ---------- wallet ---------- */

function providerOrNull() { return window.ethereum || null; }

async function refreshWalletState() {
  const eth = providerOrNull();
  const btn = $("wallet-btn");
  btn.className = "btn btn-outline btn-wallet";
  btn.disabled = false;
  wallet.detected = !!eth;
  if (!eth) {
    btn.textContent = "No wallet detected";
    btn.disabled = true;
    btn.title = "Install MetaMask (metamask.io) to record receipts. Checking and verifying never need a wallet.";
    wallet.address = null;
    wallet.chainOk = false;
    syncRecordPanel();
    return;
  }
  if (!NET) {
    // Network identity not loaded yet: never guess a chain id.
    btn.textContent = "Connect wallet";
    btn.disabled = true;
    btn.title = "Waiting for the server's network identity…";
    wallet.address = null;
    wallet.chainOk = false;
    syncRecordPanel();
    return;
  }
  const accounts = await eth.request({ method: "eth_accounts" }).catch(() => []);
  wallet.address = accounts[0] || null;
  if (wallet.address) {
    const chainHex = await eth.request({ method: "eth_chainId" }).catch(() => null);
    wallet.chainOk = chainHex && parseInt(chainHex, 16) === netChainId();
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
  if (!eth || !NET) return;
  try {
    await eth.request({ method: "eth_requestAccounts" });
    const chainHex = await eth.request({ method: "eth_chainId" });
    if (parseInt(chainHex, 16) !== netChainId()) await switchNetwork();
  } catch (err) {
    if (err && err.code !== 4001) alert(`Wallet error: ${err.message || err}`);
  }
  refreshWalletState();
}

async function switchNetwork() {
  const eth = providerOrNull();
  if (!NET) return;
  try {
    await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: NET.chain_id_hex }] });
  } catch (err) {
    if (err && (err.code === 4902 || /unrecognized|not added/i.test(err.message || ""))) {
      await eth.request({ method: "wallet_addEthereumChain", params: [chainParams()] });
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

function slugify(s) {
  return (s || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function registryNameFromInputs() {
  const firm = slugify($("firm-input").value), c = slugify($("case-input").value);
  return firm && c ? `${firm}--${c}` : null;
}

/* The registry line (round 2, P0-2; amended for v1.2.0): shown BEFORE
   anchoring — the filed document must already carry it, because the receipt
   binds the exact bytes (item 3's discovery ordering). The canonical line
   carries the registry #id (names are not unique on chain); until the
   registry exists the id is shown as pending. */
function reglineFor(registryId, name) {
  const chain = NET ? NET.chain_id : "…";
  return `Citation verifications: NVNM Chain (chain ${chain}) registry #${registryId} — ${name}`;
}

function updRegline() {
  const t = $("regline-text");
  const registry = registryNameFromInputs();
  const id = prepared && prepared.registry_id ? prepared.registry_id : chosenRegistryId;
  const complete = !!(registry && id);
  t.classList.toggle("pending", !complete);
  $("regline-copy").disabled = !complete;
  if (complete) {
    t.textContent = reglineFor(id, registry);
  } else if (registry) {
    t.textContent = reglineFor("(assigned at registry creation)", registry) +
      "  — the #id is filled in once this matter's registry exists; prepare below to resolve or create it.";
  } else {
    t.textContent = "Enter the filer and case above — the registry line is generated from them.";
  }
  setSteps();
}

function stepState(id, cls, text) {
  const s = $(id);
  s.className = "step-state" + (cls ? " " + cls : "");
  s.textContent = text;
}

/* Stepper states (round 2): every step reports where the flow actually is;
   step 4 is driven by the anchor lifecycle in anchorReceipt(). */
function setSteps() {
  const haveDoc = !!(lastReport && lastFile);

  if (!haveDoc) stepState("step-report-state", "", "not yet");
  else if (lastSource === "paste") stepState("step-report-state", "warn", "pasted text");
  else stepState("step-report-state", "ok", "done");

  if (!haveDoc) stepState("step-line-state", "", "not yet");
  else if (prepared && prepared.registry_line_found) {
    if (prepared.registry_line_found === "id") stepState("step-line-state", "ok", "on filing");
    else if (prepared.registry_line_found === "name") stepState("step-line-state", "warn", "name only — add the #id");
    else stepState("step-line-state", "warn", "not on filing");
  } else if (registryNameFromInputs()) stepState("step-line-state", "", "copy it now");
  else stepState("step-line-state", "", "not yet");

  if (wallet.address && wallet.chainOk) stepState("step-wallet-state", "ok", shortHex(wallet.address, 5));
  else if (wallet.address) stepState("step-wallet-state", "warn", "wrong network");
  else if (!wallet.detected) stepState("step-wallet-state", "", "no wallet");
  else stepState("step-wallet-state", "", "not yet");
}

/* Wallet guidance on the Record tab (round 2, P0-3): the no-wallet lawyer
   gets a path, not a dead end. */
function buildWalletCallout() {
  const box = clear($("wallet-callout"));
  if (wallet.address && wallet.chainOk) return;
  const wrong = !!wallet.address && !wallet.chainOk;
  const c = el("div", "callout" + (wrong ? " callout-warn" : ""));
  c.appendChild(icon(wrong ? "i-alert" : "i-info"));
  const d = el("div");
  if (!wallet.detected) {
    d.appendChild(el("strong", null, "No wallet detected."));
    const p = el("p", null, "Recording is normally done by your firm’s filing tool or agent. To record manually from this browser, install ");
    const a = el("a", null, "MetaMask");
    a.href = "https://metamask.io"; a.target = "_blank"; a.rel = "noopener";
    p.appendChild(a);
    p.appendChild(document.createTextNode(". Checking and verifying never need a wallet."));
    d.appendChild(p);
  } else if (wrong) {
    d.appendChild(el("strong", null, "Wallet connected to the wrong network."));
    d.appendChild(el("p", null, `Signing needs ${NET ? NET.label : "NVNM Chain"} (chain id ${netChainId() || "…"}). Switch networks to continue.`));
    const b = el("button", "btn btn-outline", "Switch to NVNM Chain");
    b.type = "button";
    b.addEventListener("click", async () => { await switchNetwork().catch(() => {}); refreshWalletState(); });
    d.appendChild(b);
  } else {
    d.appendChild(el("strong", null, "Wallet not connected."));
    d.appendChild(el("p", null, "Use “Connect wallet” in the header to sign the receipt. Checking and verifying never need a wallet."));
  }
  c.appendChild(d);
  box.appendChild(c);
}

function syncRecordPanel() {
  const haveDoc = !!(lastReport && lastFile);
  $("record-nodoc").classList.toggle("hidden", haveDoc);
  $("record-main").classList.toggle("hidden", !haveDoc);
  if (haveDoc) {
    docCard($("record-doc"), lastReport.document, lastSource);
    // Round 2, P0-4: a receipt over pasted bytes never matches a filed file.
    $("paste-warning").classList.toggle("hidden", lastSource !== "paste");
  }
  const agentEl = $("record-agent");
  if (agentEl) agentEl.textContent = wallet.address ? wallet.address : "— connect a wallet —";

  // Round 2, P0-3: prepare is gated on the stepper's prerequisites (the
  // filer/case fields still validate on click — they name the registry).
  const gateOk = haveDoc && !!wallet.address && wallet.chainOk;
  $("prepare-btn").disabled = !gateOk;
  $("prepare-gate").classList.toggle("hidden", gateOk);
  const myRegBtn = $("my-registries-btn");
  if (myRegBtn) myRegBtn.disabled = !wallet.address;

  buildWalletCallout();
  updRegline();
}

async function prepareReceipt() {
  if (!lastReport || !lastFile) {
    showError("prepare-error", new Error("Check a document file first — a receipt anchors the exact bytes you will file."));
    return;
  }
  if (!wallet.address) {
    showError("prepare-error", new Error("Connect a wallet first — the receipt records the attesting address."));
    return;
  }
  const firm = $("firm-input").value.trim();
  const matter = $("case-input").value.trim();
  if (!firm || !matter) {
    showError("prepare-error", new Error("Enter the filer/firm and the case/matter — together they name the receipt registry."));
    return;
  }
  hide("prepare-result", "prepare-error");
  clear($("anchor-status"));
  stepState("step-anchor-state", "", "waiting");
  show("prepare-busy");
  try {
    const headers = {
      "X-Firm": encodeURIComponent(firm),
      "X-Case": encodeURIComponent(matter),
      "X-Agent": encodeURIComponent(wallet.address),
    };
    // Pin the target registry when known (picker choice, or the id recovered
    // from a just-confirmed creation tx). Without it the server resolves by
    // creator + name, and surfaces any same-name ambiguity for a human pick.
    if (chosenRegistryId) headers["X-Registry-Id"] = String(chosenRegistryId);
    prepared = await apiPostBytes("/api/receipt/prepare", lastFile.bytes, lastFile.name, headers);
    renderPrepared(prepared);
    setSteps();
  } catch (err) {
    showError("prepare-error", err);
  } finally {
    hide("prepare-busy");
  }
}

/* Registry-line status in the prepare result (round 2, P0-2; v1.2.0 tiers):
   a warning, never a blocker — the tier comes from the server's text
   extraction of the exact uploaded bytes. "id" = the canonical #id is in
   the document; "name" = only the name (a weak pointer, since names are
   not unique on chain); "none" = neither. */
function buildReglineStatus(tier) {
  const box = clear($("regline-status"));
  const found = tier === "id";
  const d = el("div", "regline-status " + (found ? "regline-found" : "regline-missing"));
  d.appendChild(icon(found ? "i-seal" : "i-alert"));
  const body = el("div");
  if (found) {
    body.appendChild(el("strong", null, "Registry line (with its #id) found in the document."));
    body.appendChild(el("p", null, "The filing already carries its registry line; anchoring this exact file keeps the fingerprint match intact."));
  } else if (tier === "name") {
    body.appendChild(el("strong", null, "The document names the registry but not its #id."));
    body.appendChild(el("p", null, "Registry names are not unique on this chain — a verifier needs the #id. Add the full line, re-export, and re-check the final file before anchoring."));
  } else {
    body.appendChild(el("strong", null, "Registry line not found in the document."));
    body.appendChild(el("p", null, "You can still anchor — but if you add the line afterwards, the filed document will no longer match this receipt. Add it now, re-export, and re-check the final file."));
  }
  d.appendChild(body);
  box.appendChild(d);
}

/* Same-name ambiguity (v1.2.0): the server never picks among same-name
   registries; the human does. */
function renderAmbiguous(p) {
  const meta = clear($("prepare-meta"));
  clear($("regline-status"));
  clear($("prepare-tally"));
  $("receipt-json").querySelector("code").textContent = "";
  $("setup-box").classList.add("hidden");
  clear($("probe-box"));
  $("anchor-btn").disabled = true;

  const c = el("div", "callout callout-warn");
  c.appendChild(icon("i-alert"));
  const d = el("div");
  d.appendChild(el("strong", null, `This wallet created ${p.candidates.length} registries named “${p.registry}”.`));
  d.appendChild(el("p", null, "Registry names are not unique on chain. Pick the #id that is printed on this matter's filings:"));
  p.candidates.forEach((cand) => {
    const b = el("button", "btn btn-outline", `Use #${cand.id} (created ${String(cand.created_at).slice(0, 10)})`);
    b.type = "button";
    b.addEventListener("click", () => { chosenRegistryId = cand.id; prepareReceipt(); });
    d.appendChild(b);
  });
  c.appendChild(d);
  meta.appendChild(c);
  show("prepare-result");
}

/* Receipt size meter (round-1 design, adopted in round 2): the locked v1
   receipt is non-enumerating, so it sits far under the cap by construction. */
function setSizeMeter(bytes, cap) {
  const meter = $("size-meter");
  const pct = Math.min(100, Math.round((bytes / cap) * 1000) / 10);
  meter.querySelector(".size-value").textContent =
    `${bytes.toLocaleString("en-US")} of ${cap.toLocaleString("en-US")} bytes`;
  const fill = meter.querySelector(".size-fill");
  fill.style.width = pct + "%"; /* sanctioned CSSOM exception */
  const tight = pct > 85;
  fill.classList.toggle("tight", tight);
  const note = meter.querySelector(".size-note");
  note.className = "hint size-note" + (tight ? " tight-note" : "");
  note.textContent = tight
    ? `Near the ${cap.toLocaleString("en-US")}-byte anchoring limit.`
    : "Minimal and non-enumerating — the receipt never lists the cited cases, so it always sits well within the on-chain limit.";
}

function renderPrepared(p) {
  if (p.ambiguous) { renderAmbiguous(p); return; }

  const meta = clear($("prepare-meta"));
  const regDisplay = p.registry_id ? `#${p.registry_id} — ${p.registry}` : p.registry;
  const regV = el("span");
  regV.appendChild(el("span", "mono", regDisplay));
  kvRow(meta, "Receipt registry", regV, {
    copy: regDisplay,
    hint: p.registry_exists
      ? "exists on chain — your wallet writes the receipt"
      : "will be created — your wallet becomes its admin; the chain assigns its #id on confirmation",
  });
  if (p.name_matches === false) {
    meta.appendChild(el("p", "hint",
      "⚠ The chain's name for this #id differs from <firm>--<case>. Double-check the id if that is unexpected."));
  }
  kvRow(meta, "Attesting as", p.agent.address, { mono: true, copy: p.agent.address });
  kvRow(meta, "Checked at block", p.checked_at_block.toLocaleString("en-US"), { mono: true });
  kvRow(meta, "Registries read", (p.registries_read || []).map((r) => `${r.name} (id ${r.id})`).join(" · ") || "—", { mono: true });
  kvRow(meta, "Schema", p.receipt.schema, { mono: true });
  kvRow(meta, "Timestamp", p.receipt.timestamp, { mono: true, hint: "server clock; the chain time at anchoring is authoritative" });
  if (p.already_anchored) {
    meta.appendChild(el("p", "hint", "A receipt for this exact document already exists in this registry. Anchoring again records a new version; the prior one stays."));
  }

  if (p.registry_id) buildReglineStatus(p.registry_line_found || "none");
  else clear($("regline-status"));
  renderTally($("prepare-tally"), p.receipt.summary);

  $("receipt-json").querySelector("code").textContent = p.receipt.json;
  setSizeMeter(p.receipt.bytes, p.receipt.cap);

  const setupBox = $("setup-box");
  const probeBox = clear($("probe-box"));
  const anchorBtn = $("anchor-btn");
  anchorBtn.disabled = true;

  if (p.setup) {
    setupBox.classList.remove("hidden");
    const code = setupBox.querySelector("pre code");
    if (code) {
      code.textContent =
        `addRegistry("${p.setup.name}",\n  ${JSON.stringify(p.setup.description)},\n  '${p.setup.metadata}')`;
    }
    const oldBtn = setupBox.querySelector("button");
    if (oldBtn) {
      const btn = oldBtn.cloneNode(true); // drops stale listeners
      oldBtn.replaceWith(btn);
      btn.addEventListener("click", createReceiptRegistry);
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
      d.appendChild(el("strong", null, `This wallet may write to ${regDisplay}.`));
      const para = el("p", null, "Simulation passed. Estimated cost: ");
      para.appendChild(el("span", "mono", gasCostText(probe.gas)));
      para.appendChild(document.createTextNode("."));
      d.appendChild(para);
      box.appendChild(d);
      probeBox.appendChild(box);
      anchorBtn.disabled = false;
    } else if (probe.kind === "unauthorized") {
      const box = el("div", "probe-bad");
      box.appendChild(icon("i-alert"));
      const d = el("div");
      d.appendChild(el("strong", null, `No write rights on ${p.registry}.`));
      d.appendChild(el("p", null, "This registry exists but is owned by another wallet. Receipts are written by the registry's owner (or an editor it grants); use the wallet that created this matter's registry."));
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
    return false;
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
      return true;
    }
  }
  clear(msg);
  msg.appendChild(document.createTextNode(`Still pending after 150 s — track it at ${EXPLORER}/tx/${hash}`));
  return false;
}

async function createReceiptRegistry() {
  if (!prepared || !prepared.setup) return;
  await sendTx(prepared.setup.tx, "anchor-status", (box, info) => {
    if (info.success && info.registry_id) {
      // v1.2.0: the record calldata keys on the numeric #id, which only
      // exists NOW — the server decoded it from the AddRegistry event in
      // this tx's receipt. Pin it and genuinely re-prepare: the next
      // prepare builds the id-keyed addRecord and the full registry line.
      chosenRegistryId = info.registry_id;
      $("setup-box").classList.add("hidden");
      box.appendChild(banner("ok", "i-seal",
        `Registry #${info.registry_id} (${prepared.registry}) created`,
        `Confirmed in block ${info.block.toLocaleString("en-US")}. Put the registry line (with #${info.registry_id}) on the filing, then the receipt below re-prepares against the new registry.`));
      prepareReceipt();
    } else if (info.success) {
      box.appendChild(banner("bad", "i-alert", "Created, but the id could not be read",
        "The creation confirmed but no AddRegistry event was found in the receipt. Use “My registries” to find the new #id, then prepare again."));
    } else {
      box.appendChild(banner("bad", "i-alert", "Registry creation failed",
        "The creation transaction reverted. Check the chain status and try again."));
    }
  });
}

async function anchorReceipt() {
  if (!prepared) return;
  stepState("step-anchor-state", "busy", "anchoring…");
  let outcome = null; // "ok" | "bad" set by onMined
  await sendTx(prepared.tx, "anchor-status", (box, info, hash) => {
    if (!info.success) {
      outcome = "bad";
      const b = banner("bad", "i-alert", "Transaction reverted", "");
      const sub = b.querySelector(".rb-sub");
      sub.appendChild(document.createTextNode("Anchoring transaction "));
      sub.appendChild(el("span", "mono", shortHex(hash, 6)));
      sub.appendChild(document.createTextNode(" was mined but reverted. Nothing was recorded and no receipt exists. Re-run the write-permission probe and try again."));
      box.appendChild(b);
      return;
    }
    outcome = "ok";
    const sha = prepared.document_sha256;
    const registryRef = `#${prepared.registry_id}`;
    const regDisplay = `${registryRef} — ${prepared.registry}`;
    const b = banner("ok", "i-seal", "Verification recorded on NVNM Chain",
      "The receipt below is now immutable and publicly verifiable.");
    const kv = el("div", "kv");
    kvRow(kv, "Receipt registry", regDisplay, { mono: true, copy: regDisplay });
    if (prepared.registry_line) {
      kvRow(kv, "Filing line", prepared.registry_line, { mono: true, copy: prepared.registry_line });
    }
    kvRow(kv, "Transaction", hash, { mono: true, copy: hash });
    kvRow(kv, "Block · time", `${info.block.toLocaleString("en-US")} · ${info.block_time}`, { mono: true, hint: "the immutable timestamp" });
    kvRow(kv, "Document SHA-256", sha, { mono: true, copy: sha });
    if (info.gas_used) {
      kvRow(kv, "Gas", gasCostText(info.gas_used, info.gas_price_gwei), { mono: true });
    }
    b.appendChild(kv);

    // Round 2, P0-2: confirmation, never instruction. The registry line was
    // taught BEFORE anchoring; here we only confirm (or warn) about what the
    // anchored bytes actually contain.
    const lineOk = prepared.registry_line_found === "id";
    const note = el("div", "rb-note " + (lineOk ? "rb-note-ok" : "rb-note-warn"));
    if (lineOk) {
      note.appendChild(el("strong", null, "Your filing already carries the registry line."));
      note.appendChild(el("p", null, "File the document exactly as anchored — no further edits."));
    } else if (prepared.registry_line_found === "name") {
      note.appendChild(el("strong", null, "The anchored file names the registry but not its #id."));
      note.appendChild(el("p", null, "A verifier needs the #id (names are not unique on chain). If you add it now, the filed document will no longer match this receipt — add the full line, re-export, then re-check and re-anchor the final file."));
    } else {
      note.appendChild(el("strong", null, "The anchored file does not contain the registry line."));
      note.appendChild(el("p", null, "If you add it now, the filed document will no longer match this receipt. Add the line, re-export, then re-check and re-anchor the final file."));
    }
    b.appendChild(note);

    const actions = el("div", "rb-actions");
    const a1 = el("a", "btn btn-outline", "View on Blockscout ");
    a1.href = `${EXPLORER}/tx/${hash}`; a1.target = "_blank"; a1.rel = "noopener";
    a1.appendChild(icon("i-linkout"));
    actions.appendChild(a1);
    const a2 = el("button", "btn btn-outline", "Verify it now (free lookup)"); a2.type = "button";
    a2.addEventListener("click", () => {
      activateTab("verify");
      $("verify-registry").value = registryRef;
      $("hash-input").value = sha;
      lookupHash(registryRef, sha);
    });
    actions.appendChild(a2);
    const a3 = el("button", "btn btn-outline", "Decode the transaction"); a3.type = "button";
    a3.addEventListener("click", () => { activateTab("inspect"); $("tx-input").value = hash; inspectTx(hash); });
    actions.appendChild(a3);
    b.appendChild(actions);
    box.appendChild(b);
  });
  if (outcome === "ok") stepState("step-anchor-state", "ok", "done");
  else if (outcome === "bad") stepState("step-anchor-state", "bad", "failed");
  else stepState("step-anchor-state", "", "waiting"); // declined or still pending
}

async function showMyRegistries() {
  const box = clear($("my-registries-box"));
  if (!wallet.address) return;
  box.appendChild(el("p", "hint", "Looking up this wallet's registries…"));
  let res;
  try {
    res = await apiGet(`/api/receipt/registries?creator=${encodeURIComponent(wallet.address)}`);
  } catch (err) {
    clear(box);
    box.appendChild(el("p", "hint", `Could not list registries: ${err.message || err}`));
    return;
  }
  clear(box);
  if (!res.registries.length) {
    box.appendChild(el("p", "hint", "This wallet has not created any registries on this chain yet — the one-time setup below will create this matter's."));
    return;
  }
  const kv = el("div", "kv");
  res.registries.forEach((r) => {
    const v = el("span");
    v.appendChild(el("span", "mono", r.name));
    v.appendChild(el("span", "hint", ` created ${String(r.created_at).slice(0, 10)} `));
    const use = el("button", "btn btn-outline", "Use this");
    use.type = "button";
    use.addEventListener("click", () => { chosenRegistryId = r.id; updRegline(); prepareReceipt(); });
    v.appendChild(use);
    kvRow(kv, `#${r.id}`, v);
  });
  box.appendChild(kv);
}

function initRecord() {
  $("record-gocheck").addEventListener("click", () => activateTab("check"));
  $("paste-gocheck").addEventListener("click", () => activateTab("check"));
  $("prepare-btn").addEventListener("click", prepareReceipt);
  $("anchor-btn").addEventListener("click", anchorReceipt);
  const myRegBtn = $("my-registries-btn");
  if (myRegBtn) myRegBtn.addEventListener("click", showMyRegistries);
  $("firm-input").addEventListener("input", () => { chosenRegistryId = null; updRegline(); });
  $("case-input").addEventListener("input", () => { chosenRegistryId = null; updRegline(); });
  $("regline-copy").addEventListener("click", () => {
    if (navigator.clipboard) navigator.clipboard.writeText($("regline-text").textContent);
    $("regline-copy").textContent = "Copied";
    setTimeout(() => { $("regline-copy").textContent = "Copy line"; }, 1400);
  });
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
    if (r.agent && r.agent.address) kvRow(kv, "Attested by", r.agent.address, { mono: true, copy: r.agent.address });
    if (r.document_sha256) kvRow(kv, "Document SHA-256", r.document_sha256, { mono: true, copy: r.document_sha256 });
    if (r.checked_at_block) kvRow(kv, "Checked at block", r.checked_at_block.toLocaleString("en-US"), { mono: true });
    if (Array.isArray(r.registries) && r.registries.length) {
      kvRow(kv, "Registries read", r.registries.map((g) => `${g.name} (id ${g.id})`).join(" · "), { mono: true });
    }
    if (r.normalizer_version) kvRow(kv, "Normalizer", r.normalizer_version, { mono: true });
    if (r.schema) kvRow(kv, "Schema", r.schema, { mono: true });
    card.appendChild(kv);

    if (r.summary && typeof r.summary === "object") {
      card.appendChild(renderTally(el("div", "summary-chips"), r.summary));
    }
    card.appendChild(el("p", "hint",
      "This receipt records the tally above and the document's fingerprint — not the list of cited cases. " +
      "Anyone with the exact file can reproduce every verdict by re-running the check at the recorded block."));
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
  const regLabel = res.registry_id != null
    ? `#${res.registry_id}${res.registry ? " — " + res.registry : ""}`
    : `“${res.registry}”`;

  if (res.ambiguous) {
    const b = banner("warn", "i-alert", "Several registries share this name", "");
    const sub = b.querySelector(".rb-sub");
    sub.appendChild(document.createTextNode(
      `${res.candidates.length} registries are named “${res.registry}” — names are not unique on this chain. ` +
      "Pick the #id from the filing's verification line:"));
    b.appendChild(sub);
    const actions = el("div", "rb-actions");
    res.candidates.forEach((cand) => {
      const btn = el("button", "btn btn-outline",
        `#${cand.id} · created ${String(cand.created_at).slice(0, 10)}`);
      btn.type = "button";
      btn.addEventListener("click", () => {
        $("verify-registry").value = `#${cand.id}`;
        lookupHash(`#${cand.id}`, res.sha256);
      });
      actions.appendChild(btn);
    });
    b.appendChild(actions);
    box.appendChild(b);
    show("verify-result");
    return;
  }

  if (!res.registry_exists) {
    const b = banner("warn", "i-info", "No such registry on this chain",
      `Registry ${regLabel} does not exist on this chain, so no receipt can be found there. Check the citation-verification line printed on the filing — it carries the registry #id.`);
    box.appendChild(b);
  } else if (res.found) {
    const latestIndex = Math.max(...res.versions.map((v) => v.index));
    const b = banner("ok", "i-seal", "Receipt found for this fingerprint", "");
    const sub = b.querySelector(".rb-sub");
    sub.appendChild(document.createTextNode("Document "));
    sub.appendChild(el("span", "mono", `${res.sha256.slice(0, 12)}…${res.sha256.slice(-8)}`));
    sub.appendChild(document.createTextNode(
      ` has ${latestIndex} recorded citation-check receipt${latestIndex > 1 ? " versions" : ""} in registry `));
    sub.appendChild(el("span", "mono", regLabel));
    sub.appendChild(document.createTextNode(` (chain head ${res.head_block.toLocaleString("en-US")} at lookup).`));
    box.appendChild(b);
    if (res.note) box.appendChild(el("p", "hint", res.note));
    [...res.versions].sort((a, c) => c.index - a.index).forEach((v) => box.appendChild(receiptCard(v, latestIndex, res.versions.length)));
    box.appendChild(el("p", "honesty-line",
      "A receipt proves this exact document was citation-checked at a point in time — existence, not good law. Whether each authority still stands is the reader’s judgment."));
  } else {
    const b = banner("bad", "i-alert", "No receipt for this fingerprint",
      `No citation-check receipt exists in registry ${regLabel} for this exact file. A one-byte change — re-saving, stamping, flattening — produces a different fingerprint and breaks the match. If you expected a receipt, confirm you have the file as filed and the correct registry #id.`);
    const kv = el("div", "kv");
    kvRow(kv, "Registry", regLabel, { mono: true });
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

async function lookupHash(registry, sha) {
  hide("verify-result", "verify-error");
  show("verify-busy");
  try {
    renderLookup(await apiGet(`/api/receipt/lookup?registry=${encodeURIComponent(registry)}&sha256=${encodeURIComponent(sha)}`));
  } catch (err) {
    showError("verify-error", err);
  } finally {
    hide("verify-busy");
  }
}

function verifyRegistryOrError() {
  // The canonical reference is the registry #id from the filing's
  // verification line; the raw input goes to the server as-is — it accepts
  // "#4711", "4711", the whole pasted line, or a legacy registry name.
  const registry = $("verify-registry").value.trim();
  if (!registry) {
    showError("verify-error", new Error("Enter the registry #id from the filing's verification line first."));
    return null;
  }
  return registry;
}

function initVerify() {
  wireDropzone("verify-drop", "verify-file", async (f) => {
    const registry = verifyRegistryOrError();
    if (!registry) return;
    hide("verify-result", "verify-error");
    show("verify-busy");
    try {
      const sha = await sha256HexOf(await f.arrayBuffer());
      $("hash-input").value = sha;
      await lookupHash(registry, sha);
    } catch (err) {
      hide("verify-busy");
      showError("verify-error", err);
    }
  });
  $("hash-toggle").addEventListener("click", () => $("hash-area").classList.toggle("hidden"));
  $("hash-lookup").addEventListener("click", () => {
    const registry = verifyRegistryOrError();
    if (!registry) return;
    const sha = $("hash-input").value.trim().toLowerCase();
    if (/^[0-9a-f]{64}$/.test(sha)) lookupHash(registry, sha);
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
      `No transaction with this hash exists on chain ${netChainId() || "…"}. It may belong to another network, or it may not have been broadcast.`));
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
    kvRow(kv, "Gas", gasCostText(info.gas_used, info.gas_price_gwei), { mono: true });
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
      kvRow(dkv, "registryId", `#${rec.registryId}`, { mono: true });
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
      if (info.registry_id) {
        kvRow(dkv, "assigned #id", `#${info.registry_id}`, {
          mono: true, hint: "from the AddRegistry event in this tx's receipt",
        });
      }
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
  d2.appendChild(el("strong", null, "Stored as plain text"));
  d2.appendChild(el("p", null, "This record is stored as plain, readable text on the chain; the panel above shows its full contents."));
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
