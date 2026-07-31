// Regenerates vectors.json using ethers Interface as an oracle INDEPENDENT
// of src/nvnm_cite/chain/abi.py, driven by the SAME vendored anchoring.json
// (anchoring-module v1.2.0: id-keyed records/registries/addRecord, non-unique
// registry names, event entries included).
// Run with:
//   node generate_vectors.cjs /path/to/node_modules/ethers
// Covers: all seven selectors, event topic hashes, calldata for every method
// (including unicode strings, empty strings, and a non-empty pagination key),
// encodeFunctionResult blobs the Python decoder must read back exactly, and
// an encoded AddRegistry log-data blob for the event decoder.
"use strict";

const fs = require("fs");
const path = require("path");

const ethersPath = process.argv[2];
if (!ethersPath) {
  console.error("usage: node generate_vectors.cjs /path/to/node_modules/ethers");
  process.exit(1);
}
const { Interface, AbiCoder, version } = require(ethersPath);

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

const eventTopics = {};
for (const ev of ["AddRegistry", "AddRecord", "UpdateRecordStatus", "GrantRole", "RevokeRole"]) {
  eventTopics[ev] = iface.getEvent(ev).topicHash;
}

// v1.2.0 Record submit tuple: (uri, checksum, checksumAlgo, metadata,
// timestamp, status, recordId, index, isLatest, registryId).
// Registry ids are the live-verified ones: mainnet us-scotus=82,
// testnet dev-probe=733.
const ROE_RECORD = [
  "https://www.courtlistener.com/c/US/410/113/",
  "410 U.S. 113",
  "cite-canonical-v1",
  '{"cluster":108713,"name":"Roe v. Wade","year":1973}',
  "",
  "Active",
  0,
  0,
  false,
  82,
];

const UNICODE_RECORD = [
  "",
  "925 F.3d 1339",
  "cite-canonical-v1",
  'unicode test: Variación № ñ §410 “quotes” ☺',
  "",
  "Active",
  0,
  0,
  false,
  733,
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
    args: [82, "410 U.S. 113", 0, 0, ["0x", 0, 100, true, false]],
  },
  {
    desc: "records-paged-resume",
    fn: "records",
    args: [82, "", 0, 0, ["0xdeadbeef00aa", 7, 50, false, true]],
  },
  {
    desc: "registries-by-id",
    fn: "registries",
    args: [71, ["0x", 0, 25, false, false]],
  },
  {
    desc: "registries-enumerate",
    fn: "registries",
    args: [0, ["0x", 400, 200, false, false]],
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
          "https://www.courtlistener.com/c/US/410/113/",
          "410 U.S. 113",
          "cite-canonical-v1",
          '{"cluster":108713,"name":"Roe v. Wade","year":1973}',
          "2026-06-10T12:00:00Z",
          "Active",
          42,
          0,
          true,
          82,
        ],
        [
          "",
          "347 U.S. 483",
          "cite-canonical-v1",
          'unicode: Brown v. Board ☺ §483',
          "2026-06-10T12:00:05Z",
          "Active",
          43,
          1,
          false,
          82,
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
      [[82, "us-scotus", "Canonical citations: SCOTUS", "nvnm1creator", "2026-07-30", ""]],
      ["0x", 3],
    ],
  },
];

// AddRegistry log data (non-indexed fields: uint64 registryId, string name),
// as eth_getTransactionReceipt would deliver it.
const coder = AbiCoder.defaultAbiCoder();
const LOGS = [
  {
    desc: "logdata-AddRegistry",
    event: "AddRegistry",
    values: { registryId: 4711, name: "acme-llp--smith-v-jones" },
    data: coder.encode(["uint64", "string"], [4711, "acme-llp--smith-v-jones"]),
  },
];

const out = {
  generator: `ethers ${version} Interface (oracle independent of nvnm_cite)`,
  selectors,
  eventTopics,
  calls: CALLS.map((c) => ({ ...c, calldata: iface.encodeFunctionData(c.fn, c.args) })),
  results: RESULTS.map((r) => ({
    ...r,
    blob: iface.encodeFunctionResult(r.fn, r.values),
  })),
  logs: LOGS,
};
fs.writeFileSync(path.join(__dirname, "vectors.json"), JSON.stringify(out, null, 1) + "\n");
console.log(
  `wrote ${Object.keys(selectors).length} selectors, ${Object.keys(eventTopics).length} event topics, ${out.calls.length} calls, ${out.results.length} results (${out.generator})`
);
