// Regenerates vectors.json using ethers encodeRlp as an oracle INDEPENDENT
// of src/nvnm_cite/chain/rlp.py. Run with:
//   node generate_vectors.cjs /path/to/node_modules/ethers
// Items are nested arrays of hex strings (ethers encodeRlp's input model);
// the Python test mirrors that shape with bytes. Lengths straddle the
// 55-byte short/long form boundary for both strings and list payloads,
// and include the 0x7f/0x80 single-byte edge.
"use strict";

const fs = require("fs");
const path = require("path");

const ethersPath = process.argv[2];
if (!ethersPath) {
  console.error("usage: node generate_vectors.cjs /path/to/node_modules/ethers");
  process.exit(1);
}
const { encodeRlp, version } = require(ethersPath);

function patternHex(n) {
  const b = Buffer.alloc(n);
  for (let i = 0; i < n; i++) b[i] = (i * 7 + 13) % 256;
  return "0x" + b.toString("hex");
}

const items = [
  { desc: "empty-string", item: "0x" },
  { desc: "single-0x00", item: "0x00" },
  { desc: "single-0x7f", item: "0x7f" },
  { desc: "single-0x80", item: "0x80" },
  { desc: "single-0xff", item: "0xff" },
  { desc: "string-2B", item: patternHex(2) },
  { desc: "string-54B", item: patternHex(54) },
  { desc: "string-55B", item: patternHex(55) },
  { desc: "string-56B", item: patternHex(56) },
  { desc: "string-57B", item: patternHex(57) },
  { desc: "string-300B", item: patternHex(300) },
  { desc: "string-70000B", item: patternHex(70000) },
  { desc: "empty-list", item: [] },
  { desc: "list-of-empties", item: ["0x", "0x", "0x"] },
  { desc: "set-theoretic", item: [[], [[]], [[], [[]]]] },
  { desc: "list-payload-55B", item: [patternHex(26), patternHex(27)] },
  { desc: "list-payload-56B", item: [patternHex(26), patternHex(28)] },
  { desc: "list-payload-long", item: [patternHex(300), patternHex(56), "0x7f"] },
  { desc: "nested-mixed", item: ["0x0a", [patternHex(3), ["0x", "0x80"]], patternHex(55)] },
  {
    desc: "legacy-tx-shape",
    item: [
      "0x09",
      "0x09184e72a000",
      "0x5208",
      "0x3535353535353535353535353535353535353535",
      "0x0de0b6b3a7640000",
      "0x",
      "0x0c0a87",
      "0x",
      "0x",
    ],
  },
];

const vectors = items.map(({ desc, item }) => ({
  desc,
  item,
  rlp: encodeRlp(item),
}));

const out = {
  generator: `ethers ${version} encodeRlp (oracle independent of nvnm_cite)`,
  content_rule: "pattern strings use byte[i] = (i*7+13) % 256",
  vectors,
};
fs.writeFileSync(path.join(__dirname, "vectors.json"), JSON.stringify(out, null, 1) + "\n");
console.log(`wrote ${vectors.length} vectors (${out.generator})`);
