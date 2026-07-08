// Regenerates vectors.json using ethers Interface as an oracle INDEPENDENT
// of src/nvnm_cite/chain/abi.py, driven by the SAME vendored anchoring.json.
// Run with:
//   node generate_vectors.cjs /path/to/node_modules/ethers
// Covers: all five selectors, calldata for every method (including unicode
// strings, empty strings, and a non-empty pagination key), and
// encodeFunctionResult blobs the Python decoder must read back exactly.
"use strict";

const fs = require("fs");
const path = require("path");

const ethersPath = process.argv[2];
if (!ethersPath) {
  console.error("usage: node generate_vectors.cjs /path/to/node_modules/ethers");
  process.exit(1);
}
const { Interface, version } = require(ethersPath);

const abiJson = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, "..", "..", "..", "src", "nvnm_cite", "chain", "anchoring.json"),
    "utf8"
  )
);
const iface = new Interface(abiJson);

const selectors = {};
for (const fn of [
  "addRecord",
  "addRegistry",
  "grantRole",
  "records",
  "registries",
  "revokeRole",
  "updateRecordStatus",
]) {
  selectors[fn] = iface.getFunction(fn).selector;
}

const ROE_RECORD = [
  "us-scotus",
  "https://www.courtlistener.com/c/US/410/113/",
  "410 U.S. 113",
  "cite-canonical-v1",
  '{"cluster":108713,"name":"Roe v. Wade","year":1973}',
  "",
  "Active",
  0,
  0,
  false,
];

const UNICODE_RECORD = [
  "dev-probe",
  "",
  "925 F.3d 1339",
  "cite-canonical-v1",
  'unicode test: Variación № ñ §410 “quotes” ☺',
  "",
  "Active",
  0,
  0,
  false,
];

const CALLS = [
  {
    desc: "addRegistry-us-scotus",
    fn: "addRegistry",
    args: ["us-scotus", "Canonical citations: Supreme Court of the United States", ""],
  },
  { desc: "addRecord-roe", fn: "addRecord", args: [ROE_RECORD] },
  { desc: "addRecord-unicode", fn: "addRecord", args: [UNICODE_RECORD] },
  {
    desc: "grantRole-editor",
    fn: "grantRole",
    args: [3, "", "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf", "editor"],
  },
  {
    desc: "records-keyed-existence",
    fn: "records",
    args: ["us-scotus", "410 U.S. 113", 0, 0, ["0x", 0, 100, true, false]],
  },
  {
    desc: "records-paged-resume",
    fn: "records",
    args: ["", "", 0, 0, ["0xdeadbeef00aa", 7, 50, false, true]],
  },
  {
    desc: "registries-by-name",
    fn: "registries",
    args: [0, "us-ca11", ["0x", 0, 25, false, false]],
  },
  {
    desc: "revokeRole-editor",
    fn: "revokeRole",
    args: [3, "", "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf", "editor"],
  },
  {
    desc: "updateRecordStatus-supersede",
    fn: "updateRecordStatus",
    args: [733, 1, 1, "Superseded"],
  },
];

const RESULTS = [
  { desc: "addRegistry-result", fn: "addRegistry", values: [7] },
  { desc: "addRecord-result", fn: "addRecord", values: [123456] },
  {
    desc: "records-result-two-rows",
    fn: "records",
    values: [
      [
        [
          "us-scotus",
          "https://www.courtlistener.com/c/US/410/113/",
          "410 U.S. 113",
          "cite-canonical-v1",
          '{"cluster":108713,"name":"Roe v. Wade","year":1973}',
          "2026-06-10T12:00:00Z",
          "Active",
          42,
          0,
          true,
        ],
        [
          "us-scotus",
          "",
          "347 U.S. 483",
          "cite-canonical-v1",
          'unicode: Brown v. Board ☺ §483',
          "2026-06-10T12:00:05Z",
          "Active",
          43,
          1,
          false,
        ],
      ],
      ["0x6e657874", 999],
    ],
  },
  { desc: "records-result-empty", fn: "records", values: [[], ["0x", 0]] },
  {
    desc: "registries-result",
    fn: "registries",
    values: [
      [[11, "us-scotus", "Canonical citations: SCOTUS", "nvnm1creator", "2026-06-10", ""]],
      ["0x", 3],
    ],
  },
];

const out = {
  generator: `ethers ${version} Interface (oracle independent of nvnm_cite)`,
  selectors,
  calls: CALLS.map((c) => ({ ...c, calldata: iface.encodeFunctionData(c.fn, c.args) })),
  results: RESULTS.map((r) => ({
    ...r,
    blob: iface.encodeFunctionResult(r.fn, r.values),
  })),
};
fs.writeFileSync(path.join(__dirname, "vectors.json"), JSON.stringify(out, null, 1) + "\n");
console.log(
  `wrote ${Object.keys(selectors).length} selectors, ${out.calls.length} calls, ${out.results.length} results (${out.generator})`
);
