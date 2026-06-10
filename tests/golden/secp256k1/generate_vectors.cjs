// Regenerates vectors.json using ethers as an oracle INDEPENDENT of
// src/nvnm_cite/chain/secp256k1.py. Run with:
//   node generate_vectors.cjs /path/to/node_modules/ethers
// ethers signs with RFC-6979 deterministic nonces and canonical low-s,
// exactly like our implementation with low_s=True, so r and s must match
// byte for byte, not just verify. recovery_id = v - 27.
"use strict";

const fs = require("fs");
const path = require("path");

const ethersPath = process.argv[2];
if (!ethersPath) {
  console.error("usage: node generate_vectors.cjs /path/to/node_modules/ethers");
  process.exit(1);
}
const { SigningKey, computeAddress, keccak256, toUtf8Bytes, version } = require(ethersPath);

const PRIVATE_KEYS = [
  "0x0000000000000000000000000000000000000000000000000000000000000001",
  "0x0000000000000000000000000000000000000000000000000000000000000002",
  "0x4646464646464646464646464646464646464646464646464646464646464646", // EIP-155 example key
  "0x7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f",
  "0x00000000000000000000000000000000000000000000000000000000deadbeef",
];

function patternDigest(n) {
  const b = Buffer.alloc(n);
  for (let i = 0; i < n; i++) b[i] = (i * 7 + 13) % 256;
  return keccak256(b);
}

const DIGESTS = [
  keccak256(toUtf8Bytes("sample")),
  keccak256(toUtf8Bytes("test")),
  keccak256(toUtf8Bytes("nvnm-cite")),
  patternDigest(136),
];

const keys = PRIVATE_KEYS.map((priv) => {
  const sk = new SigningKey(priv);
  return {
    private_key: priv,
    public_key_uncompressed: SigningKey.computePublicKey(priv, false),
    address: computeAddress(priv),
  };
});

const signatures = [];
for (const priv of PRIVATE_KEYS) {
  const sk = new SigningKey(priv);
  for (const digest of DIGESTS) {
    const sig = sk.sign(digest);
    signatures.push({
      private_key: priv,
      digest,
      r: sig.r,
      s: sig.s,
      recovery_id: sig.v - 27,
    });
  }
}

const out = {
  generator: `ethers ${version} SigningKey (oracle independent of nvnm_cite)`,
  note: "ethers signs RFC-6979 deterministic + low-s, so r/s must match exactly",
  keys,
  signatures,
};
fs.writeFileSync(path.join(__dirname, "vectors.json"), JSON.stringify(out, null, 1) + "\n");
console.log(`wrote ${keys.length} keys, ${signatures.length} signatures (${out.generator})`);
