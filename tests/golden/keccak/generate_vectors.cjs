// Regenerates vectors.json using ethers as an oracle INDEPENDENT of
// src/nvnm_cite/chain/keccak.py. Run with:
//   node generate_vectors.cjs /path/to/node_modules/ethers
// The lengths deliberately straddle the 136-byte sponge rate (135/136/137
// and 271/272/273) because padding bugs live exactly there. Byte content
// is the deterministic pattern (i*7+13) % 256 so the file is reproducible.
"use strict";

const fs = require("fs");
const path = require("path");

const ethersPath = process.argv[2];
if (!ethersPath) {
  console.error("usage: node generate_vectors.cjs /path/to/node_modules/ethers");
  process.exit(1);
}
const { keccak256, version } = require(ethersPath);

const LENGTHS = [
  0, 1, 2, 7, 8, 9, 55, 56, 57, 63, 64, 65,
  134, 135, 136, 137, 138, 200, 271, 272, 273,
  400, 544, 1000, 2048, 2720,
];

function pattern(n) {
  const b = Buffer.alloc(n);
  for (let i = 0; i < n; i++) b[i] = (i * 7 + 13) % 256;
  return b;
}

const vectors = [];
for (const n of LENGTHS) {
  const data = pattern(n);
  vectors.push({
    desc: `pattern-${n}B`,
    input_hex: data.toString("hex"),
    keccak256: keccak256(data),
  });
}
for (const s of ["abc", "testing", "The quick brown fox jumps over the lazy dog"]) {
  const data = Buffer.from(s, "utf8");
  vectors.push({
    desc: `utf8:${s}`,
    input_hex: data.toString("hex"),
    keccak256: keccak256(data),
  });
}

const out = {
  generator: `ethers ${version} keccak256 (oracle independent of nvnm_cite)`,
  content_rule: "pattern vectors use byte[i] = (i*7+13) % 256",
  vectors,
};
fs.writeFileSync(path.join(__dirname, "vectors.json"), JSON.stringify(out, null, 1) + "\n");
console.log(`wrote ${vectors.length} vectors (${out.generator})`);
