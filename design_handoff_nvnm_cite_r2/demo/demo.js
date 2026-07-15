/* ════════════════════════════════════════════════════════════════════
   DEV ONLY — demo.js (round 2)
   Stands in for the real app.js so every state in the round-2 brief can
   be previewed. It uses ONLY the contract ids/classes (round-1 §8 plus
   the round-2 contract delta in HANDOFF-R2.md) and injects all dynamic
   text via textContent / createElement, mirroring the XSS posture of
   the real driver. Delete this file (and demo/devbar.css) and load
   app.js for production.
   ════════════════════════════════════════════════════════════════════ */

(function () {
  "use strict";

  /* ── tiny DOM helpers ─────────────────────────────────────────── */
  const $ = (id) => document.getElementById(id);

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  const CHIP_LABEL = {
    VERIFIED: "Verified",
    NOT_FOUND: "Not found",
    NOT_COVERED: "Not covered",
    AMBIGUOUS_JURISDICTION: "Ambiguous",
    UNPARSEABLE: "Unparseable",
  };

  function chip(status, big) {
    return el("span", "chip chip-" + status + (big ? " chip-big" : ""), CHIP_LABEL[status]);
  }

  function nameMark(kind) {
    if (kind === "m") return el("span", "name-m", "match");
    if (kind === "x") return el("span", "name-x", "MISMATCH");
    return el("span", "name-u", "—");
  }

  function icon(ref, cls) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ic" + (cls ? " " + cls : ""));
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#" + ref);
    svg.appendChild(use);
    return svg;
  }

  function copyBtn(payload) {
    const b = el("button", "copy-btn", "copy");
    b.type = "button";
    b.addEventListener("click", () => {
      navigator.clipboard && navigator.clipboard.writeText(payload);
      b.textContent = "copied";
      b.classList.add("copied");
      setTimeout(() => { b.textContent = "copy"; b.classList.remove("copied"); }, 1400);
    });
    return b;
  }

  function kvRow(k, v, opts) {
    opts = opts || {};
    const row = el("div", "row");
    row.appendChild(el("span", "k", k));
    const val = el("span", "v" + (opts.mono ? " mono" : ""));
    if (v instanceof Node) val.appendChild(v); else val.textContent = v;
    if (opts.copy) val.appendChild(copyBtn(opts.copy));
    if (opts.hint) val.appendChild(el("span", "hint", " " + opts.hint));
    row.appendChild(val);
    return row;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  /* ── shared sample data ───────────────────────────────────────── */
  const SHA = "0bc0ce36db4f005da90c200ce9018319ecb52567ef9bb5b4257b1e55bcead9b2";

  const RECEIPT_JSON = JSON.stringify({
    agent: { address: "0xaf63…", kya_id: "kya:demo-agent" },
    chain_id: 787111,
    checked_at_block: 1616300,
    document_sha256: "0bc0…",
    normalizer_version: "1.0.0",
    registries: [
      { head_block: 1616300, id: 737, name: "us-scotus" },
      { head_block: 1616300, id: 738, name: "us-ca11" },
    ],
    results: [
      { c: "410 U.S. 113", g: 0, k: 108713, n: "m", o: 3, s: "V" },
      { c: "925 F.3d 1339", g: 1, s: "N" },
    ],
    schema: "nvnm-cite-receipt/v1-draft",
    timestamp: "2026-06-12T16:05:09Z",
  }, null, 2);

  const ROWS = [
    {
      status: "VERIFIED", cite: "410 U.S. 113", asWritten: "410 U. S. 113 (as written)",
      attr: "Roe v. Wade (1973)", reason: null,
      reg: { name: "Roe v. Wade", year: "1973", link: "https://www.courtlistener.com/opinion/108713/roe-v-wade/", source: "us-scotus" },
      names: "m", seen: 3,
    },
    {
      status: "NOT_FOUND", cite: "925 F.3d 1339",
      asWritten: null, attr: "Varghese v. China Southern Airlines Co., Ltd. (11th Cir. 2019)",
      reason: "no record for this citation in the us-ca11 registry (first-page canonical keys)",
      reg: null, names: "u", seen: 1,
    },
    {
      status: "NOT_COVERED", cite: "100 F.3d 200", asWritten: null, attr: null,
      reason: "us-ca2 is outside pilot coverage (us-scotus, us-ca11)",
      reg: null, names: "u", seen: 1,
    },
    {
      status: "AMBIGUOUS_JURISDICTION", cite: "12 F.3d 34", asWritten: null, attr: null,
      reason: "F.3d alone cannot place the court; cite the court parenthetical",
      reg: null, names: "u", seen: 1,
    },
    {
      status: "UNPARSEABLE", cite: "§", asWritten: null, attr: null,
      reason: "not recognized as a citation — likely a fragment of a secondary-source cite",
      snippet: "…17 N.Y. Jur. 2d Carriers § 542 (2023)…",
      reg: null, names: "u", seen: 1,
    },
  ];

  const ROWS_CLEAN = ROWS.filter((r) => r.status !== "NOT_FOUND");
  const ROWS_AMBER = ROWS.filter((r) => r.status === "NOT_COVERED" || r.status === "UNPARSEABLE");

  /* severity order for the regrouped table (P0-1) */
  const SEVERITY = ["NOT_FOUND", "AMBIGUOUS_JURISDICTION", "UNPARSEABLE", "VERIFIED"];

  /* ── tabs ─────────────────────────────────────────────────────── */
  const tabsEl = $("tabs");
  const tabsShell = tabsEl.parentElement; /* .tabs-shell */
  const tabsBar = tabsShell.parentElement; /* .tabs-bar */

  function scrollActiveTabIntoView() {
    const t = tabsEl.querySelector(".tab.active");
    if (!t) return;
    const target = t.offsetLeft - (tabsEl.clientWidth - t.offsetWidth) / 2;
    tabsEl.scrollLeft = Math.max(0, target);
  }

  function goTab(name) {
    document.querySelectorAll(".tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.tab === name));
    document.querySelectorAll(".panel").forEach((p) =>
      p.classList.toggle("active", p.id === "panel-" + name));
    scrollActiveTabIntoView();
  }

  tabsEl.addEventListener("click", (e) => {
    const t = e.target.closest(".tab");
    if (t) goTab(t.dataset.tab);
  });

  $("to-record").addEventListener("click", () => goTab("record"));
  $("record-gocheck").addEventListener("click", () => goTab("check"));
  $("paste-gocheck").addEventListener("click", () => goTab("check"));

  /* sticky elevation (P1-3) — engineering wires .stuck the same way */
  function updStuck() {
    tabsBar.classList.toggle("stuck", tabsBar.getBoundingClientRect().top <= 0 && window.scrollY > 0);
  }
  window.addEventListener("scroll", updStuck, { passive: true });

  /* overflow fade cues (P1-4) */
  function updFades() {
    const max = tabsEl.scrollWidth - tabsEl.clientWidth;
    tabsShell.setAttribute("data-fade-l", tabsEl.scrollLeft > 4 ? "1" : "0");
    tabsShell.setAttribute("data-fade-r", max - tabsEl.scrollLeft > 4 ? "1" : "0");
  }
  tabsEl.addEventListener("scroll", updFades, { passive: true });
  window.addEventListener("resize", updFades);

  /* disclosures */
  $("paste-toggle").addEventListener("click", () => $("paste-area").classList.toggle("hidden"));
  $("hash-toggle").addEventListener("click", () => $("hash-area").classList.toggle("hidden"));

  /* dropzone feel */
  ["check-drop", "verify-drop"].forEach((id) => {
    const dz = $(id);
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("dragover"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("dragover"); });
  });

  /* ── masthead states ──────────────────────────────────────────── */
  function setChain(state) {
    const b = $("chain-badge");
    b.className = "badge";
    if (state === "loading") { b.classList.add("badge-muted"); b.textContent = "chain …"; }
    if (state === "healthy") { b.classList.add("badge-ok"); b.textContent = "chain 787111 · block 1,616,300"; }
    if (state === "error") { b.classList.add("badge-bad"); b.textContent = "chain RPC unreachable"; }
  }

  function setWallet(state) {
    const w = $("wallet-btn");
    w.className = "btn btn-outline btn-wallet";
    w.disabled = false;
    if (state === "connect") w.textContent = "Connect wallet";
    if (state === "none") { w.textContent = "No wallet detected"; w.disabled = true; }
    if (state === "connected") { w.classList.add("connected"); w.textContent = "0x1f2e3…9c0d"; }
    if (state === "wrong") { w.classList.add("connected", "wrong-network"); w.textContent = "0x1f2e3…9c0d · wrong network"; }
  }

  const BANNER_BULK = "Registry bulk load in progress: us-ca11 is still being written to chain. A live chain re-check may show NOT_FOUND for real citations until it completes.";
  const BANNER_HEAD = "Testnet maintenance window Sat 02:00–04:00 UTC; anchoring may be delayed.";

  function setBanner(state) {
    const b = $("global-banner");
    b.className = "banner";
    if (state === "hidden") { b.classList.add("hidden"); b.textContent = ""; }
    if (state === "bulk") b.textContent = BANNER_BULK;
    if (state === "two") b.textContent = BANNER_HEAD + "  ·  " + BANNER_BULK;
  }

  /* ── doc card builder ─────────────────────────────────────────── */
  function docCard(target, kind) {
    const card = $(target);
    clear(card);
    const title = el("div", "doc-title");
    title.appendChild(icon("i-doc"));
    if (kind === "sample") {
      title.appendChild(el("span", null, "Mata v. Avianca — bundled sample brief"));
      title.appendChild(el("span", "sample-tag", "sample document"));
    } else if (kind === "pasted") {
      title.appendChild(el("span", null, "pasted-text.txt"));
    } else {
      title.appendChild(el("span", null, "appellant-brief-draft-3.pdf"));
    }
    card.appendChild(title);
    const kv = el("div", "kv");
    kv.appendChild(kvRow("SHA-256", SHA, { mono: true, copy: SHA }));
    if (kind === "pasted") {
      kv.appendChild(kvRow("Size", "18,204 bytes"));
      kv.appendChild(kvRow("Extraction", "pasted text (no page structure)"));
    } else {
      kv.appendChild(kvRow("Size", "412,338 bytes"));
      kv.appendChild(kvRow("Extraction", "PDF text layer (38 pages)"));
    }
    card.appendChild(kv);
  }

  /* ── CHECK: verdict banner (P0-1) ─────────────────────────────── */
  function buildVerdict(rows) {
    const box = $("check-verdict");
    clear(box);
    if (!rows) return;

    const nf = rows.filter((r) => r.status === "NOT_FOUND");
    const verified = rows.filter((r) => r.status === "VERIFIED");
    const outside = rows.filter((r) => r.status === "NOT_COVERED");

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
      title.textContent = nf.length + (nf.length === 1 ? " citation" : " citations") +
        " could not be found — review " + (nf.length === 1 ? "it" : "these") + " before filing.";
      title.setAttribute("data-print", nf.length + " NOT FOUND");
      sub.textContent = "No registry record exists. Treat as presumptively fabricated until proven otherwise.";
      head.appendChild(body);
      v.appendChild(head);
      const list = el("div", "verdict-list");
      nf.forEach((r) => {
        const item = el("div", "verdict-item");
        item.appendChild(el("span", "vc-cite", r.cite));
        item.appendChild(el("span", "vc-reason", r.reason));
        list.appendChild(item);
      });
      v.appendChild(list);
    } else if (verified.length > 0) {
      v.classList.add("verdict-ok");
      head.appendChild(icon("i-seal"));
      title.textContent = "Every covered citation verified.";
      title.setAttribute("data-print", "ALL VERIFIED");
      sub.textContent = outside.length > 0
        ? verified.length + (verified.length === 1 ? " citation has" : " citations have") +
          " a registry record. " + outside.length + (outside.length === 1 ? " citation is" : " citations are") +
          " outside pilot coverage — no conclusion either way. Existence only; good-law status remains your judgment."
        : verified.length + (verified.length === 1 ? " citation has" : " citations have") +
          " a registry record. Existence only; good-law status remains your judgment.";
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

  /* ── CHECK: summary chips as filters (P0-1 optional) ──────────── */
  let filterSet = new Set();
  let currentRows = null;
  let coveredExpanded = false;

  function summaryFromRows(rows) {
    const count = (s) => rows.filter((r) => r.status === s).length;
    const occurrences = rows.reduce((a, r) => a + r.seen, 0);
    return [
      ["occurrences", occurrences, null],
      ["verified", count("VERIFIED"), "VERIFIED"],
      ["not found", count("NOT_FOUND"), "NOT_FOUND"],
      ["not covered", count("NOT_COVERED"), "NOT_COVERED"],
      ["ambiguous", count("AMBIGUOUS_JURISDICTION"), "AMBIGUOUS_JURISDICTION"],
      ["unparseable", count("UNPARSEABLE"), "UNPARSEABLE"],
    ];
  }

  function buildSummary(target, data, interactive) {
    const wrap = typeof target === "string" ? $(target) : target;
    clear(wrap);
    data.forEach(([label, n, status]) => {
      const canFilter = interactive && status && n > 0;
      const c = el(canFilter ? "button" : "div", "sum-chip" + (status ? " sum-" + status : ""));
      if (canFilter) {
        c.type = "button";
        c.setAttribute("aria-pressed", filterSet.has(status) ? "true" : "false");
        c.addEventListener("click", () => {
          if (filterSet.has(status)) filterSet.delete(status);
          else filterSet.add(status);
          if (filterSet.has("NOT_COVERED")) coveredExpanded = true;
          renderCheckTable();
          buildSummary(target, data, true);
        });
      }
      c.appendChild(el("span", "n", String(n)));
      c.appendChild(el("span", "l", label));
      wrap.appendChild(c);
    });
  }

  /* ── CHECK: regrouped table with disclosure row (P0-1) ────────── */
  function citeCell(r) {
    const td = el("td");
    td.appendChild(el("span", "cite-canon", r.cite));
    if (r.asWritten) td.appendChild(el("span", "cite-sub", r.asWritten));
    if (r.attr) {
      td.appendChild(el("span", "attr-label", "as attributed in the brief"));
      td.appendChild(el("span", "cite-sub", r.attr));
    }
    if (r.reason) td.appendChild(el("span", "cite-reason", r.reason));
    if (r.snippet) {
      const sn = el("span", "cite-snippet");
      sn.appendChild(el("span", "snip-label", "source text"));
      sn.appendChild(document.createTextNode(r.snippet));
      td.appendChild(sn);
    }
    return td;
  }

  function checkRow(r, collapsed) {
    const tr = el("tr", collapsed ? "row-collapsed" : null);
    tr.dataset.status = r.status;
    const tdS = el("td"); tdS.appendChild(chip(r.status)); tr.appendChild(tdS);
    tr.appendChild(citeCell(r));

    const tdR = el("td");
    if (r.reg) {
      const line = el("span", "reg-line");
      line.appendChild(el("span", "reg-name", r.reg.name));
      line.appendChild(document.createTextNode(" "));
      line.appendChild(el("span", "reg-year", "(" + r.reg.year + ")"));
      tdR.appendChild(line);
      const a = el("a", "reg-link", "CourtListener");
      a.href = r.reg.link; a.rel = "noopener";
      a.appendChild(icon("i-linkout"));
      tdR.appendChild(a);
      if (r.cite === "410 U.S. 113")
        tdR.appendChild(el("span", "collision-note", "+2 more decisions share this first page"));
      tdR.appendChild(el("span", "source-tag", r.reg.source));
    } else {
      tdR.appendChild(el("span", "cell-empty", "—"));
    }
    tr.appendChild(tdR);

    const tdN = el("td"); tdN.appendChild(nameMark(r.names)); tr.appendChild(tdN);
    tr.appendChild(el("td", "num", r.seen + "×"));
    return tr;
  }

  function renderCheckTable() {
    const rows = currentRows || [];
    const tbody = $("check-table").querySelector("tbody");
    clear(tbody);

    const bySeverity = [];
    SEVERITY.forEach((s) => rows.forEach((r) => { if (r.status === s) bySeverity.push(r); }));
    const covered = rows.filter((r) => r.status === "NOT_COVERED");

    const filtered = (s) => filterSet.size > 0 && !filterSet.has(s);

    bySeverity.forEach((r) => {
      const tr = checkRow(r, false);
      if (filtered(r.status)) tr.classList.add("row-filtered");
      tbody.appendChild(tr);
    });

    if (covered.length > 0 && !filtered("NOT_COVERED")) {
      const trG = el("tr", "group-row");
      const td = el("td");
      td.colSpan = 5;
      const btn = el("button", "group-btn");
      btn.type = "button";
      btn.setAttribute("aria-expanded", coveredExpanded ? "true" : "false");
      btn.appendChild(chip("NOT_COVERED"));
      btn.appendChild(el("span", null,
        covered.length + (covered.length === 1 ? " citation" : " citations") +
        " outside pilot coverage — " + (coveredExpanded ? "hide" : "show")));
      btn.addEventListener("click", () => { coveredExpanded = !coveredExpanded; renderCheckTable(); });
      td.appendChild(btn);
      trG.appendChild(td);
      tbody.appendChild(trG);
      covered.forEach((r) => tbody.appendChild(checkRow(r, !coveredExpanded)));
    }
  }

  function buildCheckWarnings(show) {
    const box = $("check-warning");
    clear(box);
    if (!show) return;
    const w1 = el("div", "callout callout-warn");
    w1.appendChild(icon("i-alert"));
    const d1 = el("div");
    d1.appendChild(el("strong", null, "Pages 12–14 appear to be image-only scans."));
    d1.appendChild(el("p", null, "No text layer was found on those pages; citations there were not checked. Re-run after OCR if those pages contain authority."));
    w1.appendChild(d1);
    box.appendChild(w1);

    const w2 = el("div", "callout callout-warn");
    w2.appendChild(icon("i-alert"));
    const d2 = el("div");
    d2.appendChild(el("strong", null, "A party-name mismatch was detected."));
    d2.appendChild(el("p", null, "One verified citation is attributed in the brief to a different case name than the registry records. Mismatched names can indicate a transposed citation."));
    w2.appendChild(d2);
    box.appendChild(w2);
  }

  function setProgress(mode) {
    const box = $("check-progress");
    const bar = box.querySelector(".progress-bar");
    const fill = $("check-progress-fill");
    box.classList.toggle("hidden", !mode);
    if (!mode) return;
    if (mode === "determinate") {
      bar.classList.remove("indeterminate");
      $("check-progress-text").textContent = "Checking citation 12 of 63 against NVNM Chain…";
      fill.style.width = "19%"; /* sanctioned CSSOM exception #2 */
    } else {
      bar.classList.add("indeterminate");
      $("check-progress-text").textContent = "Checking citations against NVNM Chain…";
      fill.style.width = "";
    }
  }

  function setCheck(state) {
    $("check-busy").classList.toggle("hidden", state !== "busy");
    setProgress(state === "progress" ? "determinate" : (state === "progress-indet" ? "indet" : null));
    $("check-error").classList.toggle("hidden", state !== "error");
    $("check-drop").classList.toggle("dragover", state === "dragover");
    if (state === "error")
      $("check-error").textContent = "Unsupported file type .gif; supported: .pdf, .docx, .txt, .md.";

    const resultStates = ["result", "result-warn", "result-clean", "result-amber", "result-empty", "result-sample"];
    const showing = resultStates.includes(state);
    $("check-result").classList.toggle("hidden", !showing);
    if (!showing) return;

    const empty = state === "result-empty";
    filterSet = new Set();
    coveredExpanded = false;
    currentRows =
      state === "result-clean" ? ROWS_CLEAN :
      state === "result-amber" ? ROWS_AMBER :
      empty ? [] : ROWS;

    docCard("check-doc", state === "result-sample" ? "sample" : "file");
    buildVerdict(empty ? null : currentRows);
    buildCheckWarnings(state === "result-warn");

    $("check-empty").classList.toggle("hidden", !empty);
    $("check-summary").classList.toggle("hidden", empty);
    $("check-table").closest(".table-scroll").classList.toggle("hidden", empty);
    document.querySelector("#panel-check .legend").classList.toggle("hidden", empty);
    document.querySelector("#panel-check .next-step").classList.toggle("hidden", empty);
    if (empty) return;

    buildSummary("check-summary", summaryFromRows(currentRows), true);
    renderCheckTable();
  }

  /* sample affordance (P1-8) */
  $("sample-run").addEventListener("click", () => {
    STATE.check = "result-sample";
    setCheck("result-sample");
    syncDevbar();
  });

  /* ── RECORD: registry line (P0-2) ─────────────────────────────── */
  function updRegline() {
    const filer = $("filer-input").value.trim();
    const matter = $("matter-input").value.trim();
    const t = $("regline-text");
    const ready = filer && matter;
    t.classList.toggle("pending", !ready);
    $("regline-copy").disabled = !ready;
    t.textContent = ready
      ? "[ENGINEERING: registry line — deterministic from filer \u201C" + filer + "\u201D + matter \u201C" + matter + "\u201D]"
      : "Enter filer and matter above — the registry line is generated from them.";
  }
  $("filer-input").addEventListener("input", () => { updRegline(); setSteps(); });
  $("matter-input").addEventListener("input", () => { updRegline(); setSteps(); });
  $("regline-copy").addEventListener("click", () => {
    navigator.clipboard && navigator.clipboard.writeText($("regline-text").textContent);
    $("regline-copy").textContent = "Copied";
    setTimeout(() => { $("regline-copy").textContent = "Copy line"; }, 1400);
  });

  function buildReglineStatus(found) {
    const box = $("regline-status");
    clear(box);
    const d = el("div", "regline-status " + (found ? "regline-found" : "regline-missing"));
    d.appendChild(icon(found ? "i-seal" : "i-alert"));
    const body = el("div");
    if (found) {
      body.appendChild(el("strong", null, "Registry line found in the document."));
      body.appendChild(el("p", null, "The filing already carries its registry line; anchoring this exact file keeps the fingerprint match intact."));
    } else {
      body.appendChild(el("strong", null, "Registry line not found in the document."));
      body.appendChild(el("p", null, "You can still anchor — but if you add the line afterwards, the filed document will no longer match this receipt. Add it now, re-export, and re-check the final file."));
    }
    d.appendChild(body);
    box.appendChild(d);
  }

  /* ── RECORD: wallet callout (P0-3) ────────────────────────────── */
  function buildWalletCallout(wallet) {
    const box = $("wallet-callout");
    clear(box);
    if (wallet === "connected") return;
    const c = el("div", "callout" + (wallet === "wrong" ? " callout-warn" : ""));
    c.appendChild(icon(wallet === "wrong" ? "i-alert" : "i-info"));
    const d = el("div");
    if (wallet === "none") {
      d.appendChild(el("strong", null, "No wallet detected."));
      const p = el("p", null, "Recording is normally done by your firm\u2019s filing tool or agent. To record manually from this browser, install ");
      const a = el("a", null, "MetaMask");
      a.href = "https://metamask.io"; a.rel = "noopener";
      p.appendChild(a);
      p.appendChild(document.createTextNode(". Checking and verifying never need a wallet."));
      d.appendChild(p);
    } else if (wallet === "wrong") {
      d.appendChild(el("strong", null, "Wallet connected to the wrong network."));
      const p = el("p", null, "Signing needs NVNM Chain (chain id 787111). Switch networks to continue.");
      d.appendChild(p);
      const b = el("button", "btn btn-outline", "Switch to NVNM Chain");
      b.type = "button";
      b.addEventListener("click", () => { STATE.wallet = "connected"; setWallet("connected"); setRecord(STATE.record); syncDevbar(); });
      d.appendChild(b);
    } else {
      d.appendChild(el("strong", null, "Wallet not connected."));
      d.appendChild(el("p", null, "Use \u201CConnect wallet\u201D in the header to sign the receipt. Checking and verifying never need a wallet."));
    }
    c.appendChild(d);
    box.appendChild(c);
  }

  /* ── RECORD: stepper (P0-2 / P0-3) ────────────────────────────── */
  function stepState(id, cls, text) {
    const s = $(id);
    s.className = "step-state" + (cls ? " " + cls : "");
    s.textContent = text;
  }

  function setSteps() {
    const nodoc = STATE.record === "nodoc";
    const prepared = !["nodoc", "ready", "prepare-busy", "prepare-error"].includes(STATE.record);

    /* 1 · checked document */
    stepState("step-report-state", nodoc ? "" : "ok", nodoc ? "not yet" : (STATE.docsrc === "pasted" ? "pasted text" : "done"));
    if (!nodoc && STATE.docsrc === "pasted") stepState("step-report-state", "warn", "pasted text");

    /* 2 · registry line on filing */
    const fieldsReady = $("filer-input").value.trim() && $("matter-input").value.trim();
    if (nodoc) stepState("step-line-state", "", "not yet");
    else if (prepared) {
      if (STATE.regline === "found") stepState("step-line-state", "ok", "on filing");
      else stepState("step-line-state", "warn", "not on filing");
    }
    else if (fieldsReady) stepState("step-line-state", "", "copy it now");
    else stepState("step-line-state", "", "not yet");

    /* 3 · wallet */
    if (STATE.wallet === "connected") stepState("step-wallet-state", "ok", "0x1f2e3…9c0d");
    else if (STATE.wallet === "wrong") stepState("step-wallet-state", "warn", "wrong network");
    else if (STATE.wallet === "none") stepState("step-wallet-state", "", "no wallet");
    else stepState("step-wallet-state", "", "not yet");

    /* 4 · re-verify & sign */
    if (STATE.record === "txwait") stepState("step-anchor-state", "busy", "anchoring…");
    else if (STATE.record === "success") stepState("step-anchor-state", "ok", "done");
    else if (STATE.record === "reverted") stepState("step-anchor-state", "bad", "failed");
    else stepState("step-anchor-state", "", "waiting");
  }

  /* ── RECORD: prepare & anchor ─────────────────────────────────── */
  function buildPrepareMeta() {
    const kv = $("prepare-meta");
    clear(kv);
    kv.appendChild(kvRow("Checked at block", "1,616,300", { mono: true }));
    kv.appendChild(kvRow("Registries", "us-scotus (id 737) · us-ca11 (id 738)", { mono: true }));
    kv.appendChild(kvRow("Schema", "nvnm-cite-receipt/v1-draft", { mono: true, hint: "draft until Phase 4 locks v1" }));
    kv.appendChild(kvRow("Timestamp", "2026-06-12T16:05:09Z", { mono: true, hint: "server clock; the chain time at anchoring is the authoritative timestamp" }));
  }

  function buildPrepareTable(withDiff) {
    const tbody = $("prepare-table").querySelector("tbody");
    clear(tbody);
    ROWS.forEach((r) => {
      const diff = withDiff && r.cite === "410 U.S. 113";
      const tr = el("tr", diff ? "diff" : null);
      const tdC = el("td");
      tdC.appendChild(el("span", "cite-canon", r.cite));
      tr.appendChild(tdC);
      const tdL = el("td"); tdL.appendChild(chip(r.status)); tr.appendChild(tdL);
      const tdCh = el("td"); tdCh.appendChild(chip(diff ? "NOT_FOUND" : r.status)); tr.appendChild(tdCh);
      const tdN = el("td"); tdN.appendChild(nameMark(diff ? "u" : r.names)); tr.appendChild(tdN);
      const tdNote = el("td");
      if (diff) tdNote.appendChild(el("span", "diff-note", "differs from the local check — on-chain registry state is what the receipt records"));
      else tdNote.appendChild(el("span", "cell-empty", "—"));
      tr.appendChild(tdNote);
      tbody.appendChild(tr);
    });
  }

  function setSize(bytes, compacted) {
    const max = 2048;
    const pct = Math.round((bytes / max) * 1000) / 10;
    $("size-meter").querySelector(".size-value").textContent =
      bytes.toLocaleString("en-US") + " of " + max.toLocaleString("en-US") + " bytes";
    const fill = $("size-meter").querySelector(".size-fill");
    fill.style.width = pct + "%"; /* sanctioned CSSOM exception */
    const tight = pct > 85;
    fill.classList.toggle("tight", tight);
    const note = $("size-meter").querySelector(".size-note");
    note.className = "hint size-note" + (tight ? " tight-note" : "");
    note.textContent = tight
      ? "Near the 2,048-byte anchoring limit. Compaction applied: 6 VERIFIED results collapsed into a count."
      : (compacted ? "Compaction applied: 6 VERIFIED results collapsed into a count." : "");
  }

  function buildProbe(state) {
    const box = $("probe-box");
    clear(box);
    if (state === "ok") {
      const p = el("div", "probe-ok");
      p.appendChild(icon("i-shield"));
      const d = el("div");
      d.appendChild(el("strong", null, "This wallet may write to receipts-v1."));
      d.appendChild(el("p", null, "Simulation passed. Estimated cost: "));
      d.lastChild.appendChild(el("span", "mono", "~99,000 gas ≈ 0.0045 wmantraUSD"));
      d.lastChild.appendChild(document.createTextNode("."));
      p.appendChild(d);
      box.appendChild(p);
      $("anchor-btn").disabled = false;
    } else if (state === "norights") {
      const p = el("div", "probe-bad");
      p.appendChild(icon("i-alert"));
      const d = el("div");
      d.appendChild(el("strong", null, "No editor rights on receipts-v1."));
      const para = el("p", null, "This wallet cannot write to the receipts registry. The registry’s admin must run ");
      para.appendChild(el("span", "mono", "grantRole(EDITOR_ROLE, 0x1f2e3…9c0d)"));
      para.appendChild(document.createTextNode(" before anchoring."));
      d.appendChild(para);
      p.appendChild(d);
      box.appendChild(p);
      $("anchor-btn").disabled = true;
    } else if (state === "fail") {
      const p = el("div", "probe-bad");
      p.appendChild(icon("i-alert"));
      const d = el("div");
      d.appendChild(el("strong", null, "Write simulation failed."));
      d.appendChild(el("p", null, "The dry-run transaction reverted without a reason string. Check the chain status and try preparing again."));
      p.appendChild(d);
      box.appendChild(p);
      $("anchor-btn").disabled = true;
    }
  }

  function buildAnchorStatus(state, reglineFound) {
    const box = $("anchor-status");
    clear(box);
    if (state === "txwait") {
      const w = el("div", "txwait");
      w.appendChild(el("span", "spinner"));
      const s = el("span", null, "Submitted ");
      s.appendChild(el("span", "mono", "0xab12…"));
      s.appendChild(document.createTextNode(" — waiting for confirmation…"));
      w.appendChild(s);
      box.appendChild(w);
    } else if (state === "success") {
      const b = el("div", "result-banner result-ok");
      const head = el("div", "rb-head");
      head.appendChild(icon("i-seal"));
      head.appendChild(el("span", "rb-title", "Verification recorded on NVNM Chain"));
      b.appendChild(head);
      b.appendChild(el("p", "rb-sub", "The receipt below is now immutable and publicly verifiable."));
      const kv = el("div", "kv");
      kv.appendChild(kvRow("Transaction", "0xab12f4c89e771b03d6a45c2210fe9b8d4c1a0f6e2b9d83745a1c6e0f9b27d501", { mono: true, copy: "0xab12f4c89e771b03d6a45c2210fe9b8d4c1a0f6e2b9d83745a1c6e0f9b27d501" }));
      kv.appendChild(kvRow("Block · time", "1,616,412 · 2026-06-12 16:05:42 +0000 UTC", { mono: true, hint: "the immutable timestamp" }));
      kv.appendChild(kvRow("Document SHA-256", SHA, { mono: true, copy: SHA }));
      kv.appendChild(kvRow("Gas", "99,214 (0.0045 wmantraUSD)", { mono: true }));
      b.appendChild(kv);

      /* P0-2: confirmation, not instruction */
      const note = el("div", "rb-note " + (reglineFound ? "rb-note-ok" : "rb-note-warn"));
      if (reglineFound) {
        note.appendChild(el("strong", null, "Your filing already carries the registry line."));
        note.appendChild(el("p", null, "File the document exactly as anchored — no further edits."));
      } else {
        note.appendChild(el("strong", null, "The anchored file does not contain the registry line."));
        note.appendChild(el("p", null, "If you add it now, the filed document will no longer match this receipt. Add the line, re-export, then re-check and re-anchor the final file."));
      }
      b.appendChild(note);

      const actions = el("div", "rb-actions");
      const a1 = el("a", "btn btn-outline", "View on Blockscout ");
      a1.href = "#"; a1.appendChild(icon("i-linkout"));
      const a2 = el("button", "btn btn-outline", "Verify it now (free lookup)"); a2.type = "button";
      a2.addEventListener("click", () => { goTab("verify"); STATE.verify = "found"; setVerify("found"); syncDevbar(); });
      const a3 = el("button", "btn btn-outline", "Decode the transaction"); a3.type = "button";
      a3.addEventListener("click", () => { goTab("inspect"); STATE.inspect = "result"; setInspect("result"); syncDevbar(); });
      actions.appendChild(a1); actions.appendChild(a2); actions.appendChild(a3);
      b.appendChild(actions);
      box.appendChild(b);
    } else if (state === "reverted") {
      const b = el("div", "result-banner result-bad");
      const head = el("div", "rb-head");
      head.appendChild(icon("i-alert"));
      head.appendChild(el("span", "rb-title", "Transaction reverted"));
      b.appendChild(head);
      const p = el("p", "rb-sub", "Anchoring transaction ");
      p.appendChild(el("span", "mono", "0xab12…"));
      p.appendChild(document.createTextNode(" was mined but reverted. Nothing was recorded and no receipt exists. Re-run the write-permission probe and try again."));
      b.appendChild(p);
      box.appendChild(b);
    } else if (state === "rejected") {
      const c = el("div", "callout callout-warn");
      c.appendChild(icon("i-info"));
      const d = el("div");
      d.appendChild(el("strong", null, "Signature request declined in wallet."));
      d.appendChild(el("p", null, "Nothing was sent and nothing was recorded. Press “Sign & anchor” again when ready."));
      c.appendChild(d);
      box.appendChild(c);
    }
  }

  function setRecord(state) {
    const nodoc = state === "nodoc";
    $("record-nodoc").classList.toggle("hidden", !nodoc);
    $("record-main").classList.toggle("hidden", nodoc);
    setSteps();
    if (nodoc) return;

    docCard("record-doc", STATE.docsrc === "pasted" ? "pasted" : "file");

    /* P0-4: paste-provenance warning */
    $("paste-warning").classList.toggle("hidden", STATE.docsrc !== "pasted");

    /* P0-3: wallet callout + prepare gating */
    buildWalletCallout(STATE.wallet);
    const walletReady = STATE.wallet === "connected";
    $("prepare-btn").disabled = !walletReady;
    $("prepare-gate").classList.toggle("hidden", walletReady);

    updRegline();

    $("prepare-busy").classList.toggle("hidden", state !== "prepare-busy");
    $("prepare-error").classList.toggle("hidden", state !== "prepare-error");
    if (state === "prepare-error")
      $("prepare-error").textContent = "Live re-check failed: RPC timeout after 20 s (rpc.testnet.nvnm.network). The chain may be unreachable from this network.";

    const prepared = ["prepared", "prepared-diff", "size-tight", "probe-norights", "probe-fail", "setup", "txwait", "success", "reverted", "rejected"].includes(state);
    $("prepare-result").classList.toggle("hidden", !prepared);
    if (!prepared) return;

    buildPrepareMeta();
    buildReglineStatus(STATE.regline === "found");
    buildPrepareTable(state === "prepared-diff");
    $("receipt-json").querySelector("code").textContent = RECEIPT_JSON;
    setSize(state === "size-tight" ? 1861 : 1407, false);

    $("setup-box").classList.toggle("hidden", state !== "setup");
    if (state === "setup") { clear($("probe-box")); $("anchor-btn").disabled = true; }
    else if (state === "probe-norights") buildProbe("norights");
    else if (state === "probe-fail") buildProbe("fail");
    else buildProbe("ok");

    buildAnchorStatus(
      ["txwait", "success", "reverted", "rejected"].includes(state) ? state : null,
      STATE.regline === "found"
    );
  }

  /* ── VERIFY states ────────────────────────────────────────────── */
  function receiptCard() {
    const card = el("div", "receipt-card");
    const head = el("div", "rc-head");
    head.appendChild(el("span", "rc-when", "Recorded (chain time) 2026-06-12 16:05:42 +0000 UTC"));
    head.appendChild(el("span", "rc-version", "record 41 · version 1 of 1"));
    card.appendChild(head);

    const kv = el("div", "kv");
    const att = el("span", null, "");
    att.appendChild(el("span", "mono", "0x1f2e3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9c0d"));
    att.appendChild(document.createTextNode("  ·  KYA "));
    att.appendChild(el("span", "mono", "kya:demo-agent"));
    kv.appendChild(kvRow("Attested by", att));
    kv.appendChild(kvRow("Checked at block", "1,616,300", { mono: true }));
    kv.appendChild(kvRow("Normalizer", "1.0.0", { mono: true }));
    kv.appendChild(kvRow("Schema", "nvnm-cite-receipt/v1-draft", { mono: true }));
    card.appendChild(kv);

    const chips = el("div", "summary-chips");
    buildSummary(chips, summaryFromRows(ROWS), false);
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
    ROWS.forEach((r) => {
      const tr = el("tr");
      const tdS = el("td"); tdS.appendChild(chip(r.status)); tr.appendChild(tdS);
      const tdC = el("td"); tdC.appendChild(el("span", "cite-canon", r.cite)); tr.appendChild(tdC);
      const tdN = el("td"); tdN.appendChild(nameMark(r.names)); tr.appendChild(tdN);
      tr.appendChild(el("td", "num", r.seen + "×"));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    scroll.appendChild(table);
    card.appendChild(scroll);

    card.appendChild(el("p", "hint", "6 VERIFIED results were collapsed into a count in the on-chain record to fit the byte budget; they are shown expanded here."));

    const det = el("details", "json-details");
    det.appendChild(el("summary", null, "Raw on-chain record"));
    const pre = el("pre", "codeblock");
    pre.appendChild(el("code", null, RECEIPT_JSON));
    det.appendChild(pre);
    card.appendChild(det);
    return card;
  }

  function setVerify(state) {
    $("verify-busy").classList.toggle("hidden", state !== "busy");
    $("verify-error").classList.toggle("hidden", state !== "error");
    if (state === "error")
      $("verify-error").textContent = "Lookup failed: the RPC endpoint did not respond. Your document was not sent anywhere; only the lookup failed.";
    const box = $("verify-result");
    clear(box);
    box.classList.toggle("hidden", !["found", "notfound", "noregistry"].includes(state));

    if (state === "found") {
      const b = el("div", "result-banner result-ok");
      const head = el("div", "rb-head");
      head.appendChild(icon("i-seal"));
      head.appendChild(el("span", "rb-title", "Receipt found for this fingerprint"));
      b.appendChild(head);
      const sub = el("p", "rb-sub", "Document ");
      sub.appendChild(el("span", "mono", SHA.slice(0, 12) + "…" + SHA.slice(-8)));
      sub.appendChild(document.createTextNode(" has 1 recorded citation-check receipt on NVNM Chain."));
      b.appendChild(sub);
      box.appendChild(b);
      box.appendChild(receiptCard());
      box.appendChild(el("p", "honesty-line",
        "A receipt proves this exact document was citation-checked at a point in time — existence, not good law. Whether each authority still stands is the reader’s judgment."));
    } else if (state === "notfound") {
      const b = el("div", "result-banner result-bad");
      const head = el("div", "rb-head");
      head.appendChild(icon("i-alert"));
      head.appendChild(el("span", "rb-title", "No receipt for this fingerprint"));
      b.appendChild(head);
      b.appendChild(el("p", "rb-sub",
        "No citation-check receipt exists on NVNM Chain for this exact file. Note: a one-byte change — re-saving, stamping, flattening — produces a different fingerprint and breaks the match. If you expected a receipt, confirm you have the file as filed."));
      const kv = el("div", "kv");
      kv.appendChild(kvRow("Fingerprint", SHA, { mono: true, copy: SHA }));
      b.appendChild(kv);
      box.appendChild(b);
    } else if (state === "noregistry") {
      const b = el("div", "result-banner result-warn");
      const head = el("div", "rb-head");
      head.appendChild(icon("i-info"));
      head.appendChild(el("span", "rb-title", "The receipts registry has not been created yet"));
      b.appendChild(head);
      b.appendChild(el("p", "rb-sub",
        "No receipts-v1 registry exists on this chain, so no receipts can exist for any document. This is expected early in the pilot; check back once the first receipt has been anchored."));
      box.appendChild(b);
    }
  }

  /* ── INSPECT states ───────────────────────────────────────────── */
  const META_JSON = JSON.stringify(
    { cluster: 97778, name: "Porto Rico v. Rosaly Y Castillo", year: 1913 }, null, 2);

  function setInspect(state) {
    $("inspect-busy").classList.toggle("hidden", state !== "busy");
    $("inspect-error").classList.toggle("hidden", state !== "error");
    if (state === "error")
      $("inspect-error").textContent = "That does not look like a transaction hash: expected 66 characters beginning 0x.";
    const box = $("inspect-result");
    clear(box);
    box.classList.toggle("hidden", !["result", "reverted", "notfound", "unknown"].includes(state));

    if (state === "notfound") {
      const b = el("div", "result-banner result-warn");
      const head = el("div", "rb-head");
      head.appendChild(icon("i-info"));
      head.appendChild(el("span", "rb-title", "Transaction not found"));
      b.appendChild(head);
      b.appendChild(el("p", "rb-sub", "No transaction with this hash exists on chain 787111. It may belong to another network, or it may not have been broadcast."));
      box.appendChild(b);
      return;
    }

    const kv = el("div", "kv");
    const st = el("span");
    if (state === "reverted") st.appendChild(el("span", "tx-status-bad", "✗ REVERTED"));
    else st.appendChild(el("span", "tx-status-ok", "Confirmed"));
    kv.appendChild(kvRow("Status", st));
    kv.appendChild(kvRow("Block · time", "1,615,584 · 2026-06-12T15:26:42Z", { mono: true }));
    kv.appendChild(kvRow("From", "0x1f2e3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9c0d", { mono: true, copy: "0x1f2e3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9c0d" }));
    const to = el("span");
    to.appendChild(el("span", "mono", "0x0000000000000000000000000000000000000808"));
    to.appendChild(el("span", "precompile-tag", "NVNM anchoring precompile"));
    kv.appendChild(kvRow("To", to));
    kv.appendChild(kvRow("Gas", "86,757 @ 45 gwei (0.0039 wmantraUSD)", { mono: true }));
    box.appendChild(kv);

    const sec = el("div", "decoded-section");
    if (state === "unknown") {
      sec.appendChild(el("h3", "overline", "Decoded"));
      const c = el("div", "callout");
      c.appendChild(icon("i-info"));
      const d = el("div");
      d.appendChild(el("strong", null, "Unknown function selector 0x9f3c11ab."));
      d.appendChild(el("p", null, "This transaction calls the anchoring precompile but does not match any nvnm-cite function signature. The raw calldata is shown below, unframed."));
      c.appendChild(d);
      sec.appendChild(c);
      const pre = el("pre", "codeblock");
      pre.appendChild(el("code", null, "0x9f3c11ab0000000000000000000000000000000000000000000000000000000000000040…"));
      sec.appendChild(pre);
    } else {
      sec.appendChild(el("h3", "overline", "Decoded"));
      sec.appendChild(el("span", "decoded-fn", "addRecord()"));
      const dkv = el("div", "kv");
      dkv.appendChild(kvRow("registry", "us-scotus", { mono: true }));
      dkv.appendChild(kvRow("uri", "https://www.courtlistener.com/opinion/97778/porto-rico-v-rosaly-y-castillo/", { mono: true }));
      dkv.appendChild(kvRow("checksum", "33 S. Ct. 352", { mono: true, hint: "the citation string itself — stored as plaintext" }));
      dkv.appendChild(kvRow("checksumAlgo", "cite-canonical-v1", { mono: true }));
      sec.appendChild(dkv);
      sec.appendChild(el("h3", "overline", "Metadata"));
      const pre = el("pre", "codeblock");
      pre.appendChild(el("code", null, META_JSON));
      sec.appendChild(pre);
    }
    box.appendChild(sec);

    const c2 = el("div", "callout");
    c2.appendChild(icon("i-info"));
    const d2 = el("div");
    d2.appendChild(el("strong", null, "Why block explorers show garbled text"));
    d2.appendChild(el("p", null, "The record is plaintext, but it travels inside ABI encoding — length prefixes and 32-byte padding. A generic explorer’s UTF-8 view renders that framing as noise. This decoder strips the framing; what remains is exactly the text above."));
    c2.appendChild(d2);
    box.appendChild(c2);

    const a = el("a", "reg-link", "View on Blockscout ");
    a.href = "#"; a.rel = "noopener";
    a.appendChild(icon("i-linkout"));
    box.appendChild(a);
  }

  /* ── ABOUT (P1-1: full vs counts-unavailable) ─────────────────── */
  function buildAbout(mode) {
    const nocounts = mode === "nocounts";
    const st = $("about-status");
    clear(st);
    const rpcV = el("span");
    rpcV.appendChild(el("span", "mono", "https://rpc.testnet.nvnm.network"));
    rpcV.appendChild(document.createTextNode("  ·  responding"));
    st.appendChild(kvRow("RPC", rpcV));
    st.appendChild(kvRow("Chain id", "787111", { mono: true }));
    st.appendChild(kvRow("Head block", "1,616,300", { mono: true }));
    st.appendChild(kvRow("us-scotus", "registry id 737 · created 2026-05-02", { mono: true }));
    st.appendChild(kvRow("us-ca11", "registry id 738 · created 2026-05-09", { mono: true }));
    st.appendChild(kvRow("receipts-v1", "not created yet", { mono: true }));
    st.appendChild(kvRow("Bulk load", "not running"));
    st.appendChild(kvRow("Anchoring precompile", "0x0000000000000000000000000000000000000808", { mono: true, copy: "0x0000000000000000000000000000000000000808" }));

    $("coverage-empty").classList.toggle("hidden", !nocounts);

    const tbody = $("coverage-table").querySelector("tbody");
    clear(tbody);
    (nocounts
      ? [
          ["us-scotus", "live status (names and ids only)", "—", "U.S. Reports — first-page canonical keys"],
          ["us-ca11", "live status (names and ids only)", "—", "F.2d / F.3d / F.4th — Eleventh Circuit first-page keys"],
          ["receipts-v1", "live chain", "—", "filing receipts; created on first anchor"],
        ]
      : [
          ["us-scotus", "local snapshot 2026-05-01", "218,775", "U.S. Reports — first-page canonical keys, vols. 1–600"],
          ["us-ca11", "local snapshot 2026-05-01", "54,310", "F.2d / F.3d / F.4th — Eleventh Circuit first-page keys"],
          ["receipts-v1", "live chain", "—", "filing receipts; created on first anchor"],
        ]
    ).forEach(([a1, b1, c1, d1]) => {
      const tr = el("tr");
      const t1 = el("td"); t1.appendChild(el("span", "cite-canon", a1)); tr.appendChild(t1);
      tr.appendChild(el("td", null, b1));
      tr.appendChild(el("td", "num", c1));
      tr.appendChild(el("td", null, d1));
      tbody.appendChild(tr);
    });

    const v = $("about-versions");
    clear(v);
    v.appendChild(kvRow("Normalizer", "1.0.0", { mono: true }));
    v.appendChild(kvRow("Citation spec", "cite-canonical-v1", { mono: true }));
    v.appendChild(kvRow("Record schema", "v1", { mono: true }));
    v.appendChild(kvRow("Receipt schema", "nvnm-cite-receipt/v1-draft", { mono: true }));
  }

  /* ── dev bar ──────────────────────────────────────────────────── */
  const STATE = {
    chain: "healthy", wallet: "connected", banner: "hidden",
    check: "result", record: "prepared", regline: "found", docsrc: "file",
    verify: "found", inspect: "result", about: "full",
  };

  const DEV_CONTROLS = [
    ["chain", "chain", ["loading", "healthy", "error"], setChain],
    ["wallet", "wallet", ["connect", "none", "connected", "wrong"], (v) => { setWallet(v); setRecord(STATE.record); }],
    ["banner", "banner", ["hidden", "bulk", "two"], setBanner],
    ["check", "check", ["empty", "dragover", "busy", "progress", "progress-indet", "error", "result", "result-warn", "result-clean", "result-amber", "result-empty", "result-sample"], setCheck],
    ["record", "record", ["nodoc", "ready", "prepare-busy", "prepare-error", "prepared", "prepared-diff", "size-tight", "setup", "probe-norights", "probe-fail", "txwait", "success", "reverted", "rejected"], setRecord],
    ["regline", "regline", ["found", "missing"], () => setRecord(STATE.record)],
    ["docsrc", "docsrc", ["file", "pasted"], () => setRecord(STATE.record)],
    ["verify", "verify", ["empty", "busy", "error", "found", "notfound", "noregistry"], setVerify],
    ["inspect", "inspect", ["empty", "busy", "error", "notfound", "result", "reverted", "unknown"], setInspect],
    ["about", "about", ["full", "nocounts"], buildAbout],
  ];

  let devSelects = {};

  function buildDevbar() {
    const bar = el("div", "devbar");
    bar.appendChild(el("span", "devbar-tag", "DEV · states"));
    DEV_CONTROLS.forEach(([key, label, options, apply]) => {
      const lab = el("label", null, label + " ");
      const sel = el("select");
      options.forEach((o) => {
        const opt = el("option", null, o);
        opt.value = o;
        if (o === STATE[key]) opt.setAttribute("selected", "");
        sel.appendChild(opt);
      });
      sel.value = STATE[key];
      sel.addEventListener("change", () => { STATE[key] = sel.value; apply(sel.value); });
      devSelects[key] = sel;
      lab.appendChild(sel);
      bar.appendChild(lab);
    });
    document.body.appendChild(bar);
  }

  function syncDevbar() {
    Object.keys(devSelects).forEach((k) => { devSelects[k].value = STATE[k]; });
  }

  /* ── boot ─────────────────────────────────────────────────────── */
  setChain(STATE.chain);
  setWallet(STATE.wallet);
  setBanner(STATE.banner);
  setCheck(STATE.check);
  setRecord(STATE.record);
  setVerify(STATE.verify);
  setInspect(STATE.inspect);
  buildAbout(STATE.about);
  buildDevbar();
  updFades();
  updStuck();
})();
