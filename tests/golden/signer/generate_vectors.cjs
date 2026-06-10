// Regenerates vectors.json using ethers as an oracle INDEPENDENT of
// src/nvnm_cite/chain/signer.py. Run with:
//   node generate_vectors.cjs /path/to/node_modules/ethers
// ethers signs RFC-6979 deterministic + low-s, so the unsigned hash, the
// fully serialized raw transaction, and the tx hash must all match our
// output byte for byte. Cases include the EIP-155 spec example (chain 1)
// and NVNM-testnet-shaped calls (chain 787111, precompile target).
"use strict";

const fs = require("fs");
const path = require("path");

const ethersPath = process.argv[2];
if (!ethersPath) {
  console.error("usage: node generate_vectors.cjs /path/to/node_modules/ethers");
  process.exit(1);
}
const { Transaction, SigningKey, version } = require(ethersPath);

const PRECOMPILE = "0x0000000000000000000000000000000000000A00";

function patternHex(n) {
  const b = Buffer.alloc(n);
  for (let i = 0; i < n; i++) b[i] = (i * 7 + 13) % 256;
  return "0x" + b.toString("hex");
}

const CASES = [
  {
    desc: "eip155-spec-example",
    chainId: 1, nonce: 9, gasPrice: "20000000000", gasLimit: 21000,
    to: "0x3535353535353535353535353535353535353535",
    value: "1000000000000000000", data: "0x",
    privateKey: "0x4646464646464646464646464646464646464646464646464646464646464646",
  },
  {
    desc: "nvnm-addRegistry-shape",
    chainId: 787111, nonce: 0, gasPrice: "40000000000", gasLimit: 150000,
    to: PRECOMPILE, value: "0", data: "0x318b38b1" + "00".repeat(96),
    privateKey: "0x7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f",
  },
  {
    desc: "nvnm-plain-transfer",
    chainId: 787111, nonce: 7, gasPrice: "40000000000", gasLimit: 21000,
    to: "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf", value: "1", data: "0x",
    privateKey: "0x00000000000000000000000000000000000000000000000000000000deadbeef",
  },
  {
    desc: "nvnm-large-calldata",
    chainId: 787111, nonce: 123456, gasPrice: "40000000000", gasLimit: 800000,
    to: PRECOMPILE, value: "0", data: patternHex(600),
    privateKey: "0x0000000000000000000000000000000000000000000000000000000000000001",
  },
];

const vectors = CASES.map((c) => {
  const tx = Transaction.from({
    type: 0,
    chainId: c.chainId,
    nonce: c.nonce,
    gasPrice: c.gasPrice,
    gasLimit: c.gasLimit,
    to: c.to,
    value: c.value,
    data: c.data,
  });
  tx.signature = new SigningKey(c.privateKey).sign(tx.unsignedHash);
  return {
    desc: c.desc,
    chain_id: c.chainId,
    nonce: c.nonce,
    gas_price: c.gasPrice,
    gas_limit: c.gasLimit,
    to: c.to,
    value: c.value,
    data: c.data,
    private_key: c.privateKey,
    unsigned_hash: tx.unsignedHash,
    raw: tx.serialized,
    tx_hash: tx.hash,
  };
});

const out = {
  generator: `ethers ${version} Transaction (oracle independent of nvnm_cite)`,
  vectors,
};
fs.writeFileSync(path.join(__dirname, "vectors.json"), JSON.stringify(out, null, 1) + "\n");
console.log(`wrote ${vectors.length} signed-tx vectors (${out.generator})`);
