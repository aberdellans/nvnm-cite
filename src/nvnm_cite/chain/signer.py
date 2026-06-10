"""EIP-155 legacy (type-0) transaction signing. Stdlib only.

V1 signs type-0 transactions exclusively (DECISIONS.md 2026-06-10): the
chain accepts EIP-1559, but at a fixed 40 gwei floor the typed envelope
buys nothing. chain_id is a required parameter everywhere; nothing in
this module defaults to a particular network.
"""

from __future__ import annotations

from dataclasses import dataclass

from nvnm_cite.chain import secp256k1
from nvnm_cite.chain.keccak import keccak_256
from nvnm_cite.chain.rlp import rlp_encode


def parse_private_key(value: str) -> int:
    """Parse a hex private key, with or without the 0x prefix.

    MetaMask exports bare hex; tooling usually writes 0x-prefixed. Both
    are accepted (DECISIONS / plan task 0.6). Returns the key as an int,
    validated against the curve order.
    """
    body = value.strip()
    if body[:2] in ("0x", "0X"):
        body = body[2:]
    if len(body) != 64:
        raise ValueError("private key must be 64 hex characters (optionally 0x-prefixed)")
    try:
        key = int(body, 16)
    except ValueError:
        raise ValueError("private key contains non-hex characters") from None
    if not 1 <= key < secp256k1.SECP256K1.n:
        raise ValueError("private key out of range for secp256k1")
    return key


def _address_bytes(to: str) -> bytes:
    if to == "":
        return b""  # contract creation; unused here but valid RLP
    body = to[2:] if to[:2] in ("0x", "0X") else to
    if len(body) != 40:
        raise ValueError(f"address must be 20 bytes of hex, got {to!r}")
    return bytes.fromhex(body)


@dataclass(frozen=True)
class LegacyTransaction:
    nonce: int
    gas_price: int
    gas_limit: int
    to: str  # 0x-hex address; "" means contract creation
    value: int
    data: bytes = b""

    def _base_fields(self) -> list:
        return [
            self.nonce,
            self.gas_price,
            self.gas_limit,
            _address_bytes(self.to),
            self.value,
            self.data,
        ]


@dataclass(frozen=True)
class SignedTransaction:
    raw: bytes  # RLP bytes for eth_sendRawTransaction
    hash: bytes  # transaction hash: keccak-256 of raw
    v: int
    r: int
    s: int

    @property
    def raw_hex(self) -> str:
        return "0x" + self.raw.hex()

    @property
    def hash_hex(self) -> str:
        return "0x" + self.hash.hex()


def signing_hash(tx: LegacyTransaction, chain_id: int) -> bytes:
    """EIP-155 sighash: keccak of the RLP of the six tx fields + (chain_id, 0, 0)."""
    if chain_id < 1:
        raise ValueError("chain_id must be a positive integer")
    return keccak_256(rlp_encode(tx._base_fields() + [chain_id, 0, 0]))


def sign_transaction(
    tx: LegacyTransaction, private_key: int, chain_id: int
) -> SignedTransaction:
    """Sign deterministically (RFC-6979, low-s) under EIP-155 replay protection.

    v = 35 + 2*chain_id + recovery_id, which binds the signature to one
    chain: the same transaction signed for testnet 787111 is invalid
    everywhere else.
    """
    digest = signing_hash(tx, chain_id)
    r, s, recovery_id = secp256k1.sign(digest, private_key)
    v = 35 + 2 * chain_id + recovery_id
    raw = rlp_encode(tx._base_fields() + [v, r, s])
    return SignedTransaction(raw=raw, hash=keccak_256(raw), v=v, r=r, s=s)
