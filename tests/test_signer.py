import json
from pathlib import Path

import pytest

from nvnm_cite.chain.rlp import rlp_encode
from nvnm_cite.chain.secp256k1 import SECP256K1
from nvnm_cite.chain.signer import (
    LegacyTransaction,
    parse_private_key,
    sign_transaction,
    signing_hash,
)

GOLDEN = Path(__file__).parent / "golden" / "signer" / "vectors.json"

# EIP-155 worked example, verbatim from eips.ethereum.org/EIPS/eip-155
# (fetched 2026-06-10).
EIP155_TX = LegacyTransaction(
    nonce=9,
    gas_price=20 * 10**9,
    gas_limit=21000,
    to="0x3535353535353535353535353535353535353535",
    value=10**18,
    data=b"",
)
EIP155_KEY = parse_private_key(
    "0x4646464646464646464646464646464646464646464646464646464646464646"
)
EIP155_SIGNING_DATA = (
    "ec098504a817c800825208943535353535353535353535353535353535353535"
    "880de0b6b3a764000080018080"
)
EIP155_SIGNING_HASH = "daf5a779ae972f972197303d7b574746c7ef83eadac0f2791ad23db92e4c8e53"
EIP155_V = 37
EIP155_R = 18515461264373351373200002665853028612451056578545711640558177340181847433846
EIP155_S = 46948507304638947509940763649030358759909902576025900602547168820602576006531
EIP155_RAW = (
    "0xf86c098504a817c800825208943535353535353535353535353535353535353535880de0"
    "b6b3a76400008025a028ef61340bd939bc2195fe537567866003e1a15d3c71ff63e1590620"
    "aa636276a067cbe9d8997f761aecb703304b3800ccf555c9f3dc64214b297fb1966a3b6d83"
)


def load_vectors() -> list[dict]:
    return json.loads(GOLDEN.read_text())["vectors"]


# --- EIP-155 spec example, field by field ---


def test_eip155_signing_data_and_hash() -> None:
    encoded = rlp_encode(EIP155_TX._base_fields() + [1, 0, 0])
    assert encoded.hex() == EIP155_SIGNING_DATA
    assert signing_hash(EIP155_TX, chain_id=1).hex() == EIP155_SIGNING_HASH


def test_eip155_signature_and_raw_tx() -> None:
    signed = sign_transaction(EIP155_TX, EIP155_KEY, chain_id=1)
    assert signed.v == EIP155_V
    assert signed.r == EIP155_R
    assert signed.s == EIP155_S
    assert signed.raw_hex == EIP155_RAW


# --- ethers oracle vectors, including NVNM-testnet-shaped transactions ---


@pytest.mark.parametrize("vector", load_vectors(), ids=lambda v: v["desc"])
def test_ethers_transaction_vectors(vector: dict) -> None:
    tx = LegacyTransaction(
        nonce=vector["nonce"],
        gas_price=int(vector["gas_price"]),
        gas_limit=vector["gas_limit"],
        to=vector["to"],
        value=int(vector["value"]),
        data=bytes.fromhex(vector["data"].removeprefix("0x")),
    )
    chain_id = vector["chain_id"]
    assert signing_hash(tx, chain_id).hex() == vector["unsigned_hash"].removeprefix("0x")
    signed = sign_transaction(tx, parse_private_key(vector["private_key"]), chain_id)
    assert signed.raw_hex == vector["raw"]
    assert signed.hash_hex == vector["tx_hash"]


def test_eip155_v_binds_chain_id() -> None:
    signed = sign_transaction(EIP155_TX, EIP155_KEY, chain_id=787111)
    assert signed.v in (35 + 2 * 787111, 36 + 2 * 787111)
    # Same tx, different chain: everything about the signature changes.
    other = sign_transaction(EIP155_TX, EIP155_KEY, chain_id=1)
    assert (signed.r, signed.s) != (other.r, other.s)


# --- private key parsing (MetaMask exports bare hex) ---


def test_parse_private_key_accepts_both_prefixes() -> None:
    bare = "46" * 32
    assert parse_private_key(bare) == parse_private_key("0x" + bare) == EIP155_KEY
    assert parse_private_key("0X" + bare.upper()) == EIP155_KEY
    assert parse_private_key(f"  {bare}\n") == EIP155_KEY  # tolerate whitespace


@pytest.mark.parametrize(
    "bad",
    [
        "46" * 31,  # too short
        "46" * 33,  # too long
        "0x" + "zz" + "46" * 31,  # non-hex
        "00" * 32,  # zero
        f"{SECP256K1.n:064x}",  # exactly the curve order
        "",
    ],
)
def test_parse_private_key_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_private_key(bad)


def test_rejected_transaction_fields() -> None:
    with pytest.raises(ValueError):
        signing_hash(EIP155_TX, chain_id=0)
    with pytest.raises(ValueError):
        sign_transaction(
            LegacyTransaction(0, 1, 21000, "0x1234", 0, b""), EIP155_KEY, chain_id=1
        )
