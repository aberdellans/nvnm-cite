import hashlib
import json
from pathlib import Path

import pytest

from nvnm_cite.chain.secp256k1 import (
    SECP256K1,
    Curve,
    address_from_private_key,
    derive_public_key,
    is_on_curve,
    point_add,
    rfc6979_nonce,
    scalar_mult,
    sign,
    verify,
)

GOLDEN = Path(__file__).parent / "golden" / "secp256k1" / "vectors.json"

# Curve P-256 domain parameters (FIPS 186). RFC 6979 Appendix A.2.5 runs on
# this curve; deriving the RFC's published public key from its private key
# (test below) proves these constants before anything else relies on them.
P256 = Curve(
    p=0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF,
    a=-3,
    b=0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B,
    gx=0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
    gy=0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5,
    n=0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551,
)

# RFC 6979 Appendix A.2.5 values, verbatim from rfc-editor.org (2026-06-10).
RFC_PRIVATE = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721
RFC_PUBLIC = (
    0x60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6,
    0x7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299,
)
RFC_SHA256_VECTORS = {
    b"sample": {
        "k": 0xA6E3C57DD01ABE90086538398355DD4C3B17AA873382B0F24D6129493D8AAD60,
        "r": 0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716,
        "s": 0xF7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8,
    },
    b"test": {
        "k": 0xD16B6AE827F17175E040871A1C7EC3500192C4C92677336EC2537ACAEE0008E0,
        "r": 0xF1ABB023518351CD71D881567B1EA663ED3EFCF6C5132B354F28D3B0B7D38367,
        "s": 0x019F4113742A2B14BD25926B49C649155F267E60D3814B4C0CC84250E46F0083,
    },
}


def load_golden() -> dict:
    return json.loads(GOLDEN.read_text())


def _hex_to_int(value: str) -> int:
    return int(value, 16)


# --- RFC 6979 (P-256): curve params, nonce machinery, full signing equation ---


def test_p256_public_key_derivation_matches_rfc() -> None:
    assert derive_public_key(RFC_PRIVATE, P256) == RFC_PUBLIC


@pytest.mark.parametrize("message", RFC_SHA256_VECTORS, ids=lambda m: m.decode())
def test_rfc6979_nonce_vectors(message: bytes) -> None:
    digest = hashlib.sha256(message).digest()
    expected = RFC_SHA256_VECTORS[message]["k"]
    assert rfc6979_nonce(digest, RFC_PRIVATE, P256.n) == expected


@pytest.mark.parametrize("message", RFC_SHA256_VECTORS, ids=lambda m: m.decode())
def test_rfc6979_signature_vectors(message: bytes) -> None:
    digest = hashlib.sha256(message).digest()
    expected = RFC_SHA256_VECTORS[message]
    # low_s=False: the RFC publishes raw signatures without EIP-2 canonicalization.
    r, s, _ = sign(digest, RFC_PRIVATE, curve=P256, low_s=False)
    assert (r, s) == (expected["r"], expected["s"])
    assert verify(digest, (r, s), RFC_PUBLIC, curve=P256)


# --- ethers oracle (secp256k1): keys, addresses, exact signatures ---


@pytest.mark.parametrize("entry", load_golden()["keys"], ids=lambda e: e["address"][:10])
def test_ethers_key_vectors(entry: dict) -> None:
    private_key = _hex_to_int(entry["private_key"])
    x, y = derive_public_key(private_key)
    uncompressed = "0x04" + x.to_bytes(32, "big").hex() + y.to_bytes(32, "big").hex()
    assert uncompressed == entry["public_key_uncompressed"]
    assert address_from_private_key(private_key) == entry["address"]


@pytest.mark.parametrize(
    "entry",
    load_golden()["signatures"],
    ids=lambda e: f"{e['private_key'][-4:]}-{e['digest'][2:8]}",
)
def test_ethers_signature_vectors_exact_match(entry: dict) -> None:
    digest = bytes.fromhex(entry["digest"].removeprefix("0x"))
    r, s, recovery_id = sign(digest, _hex_to_int(entry["private_key"]))
    assert r == _hex_to_int(entry["r"])
    assert s == _hex_to_int(entry["s"])
    assert recovery_id == entry["recovery_id"]


# --- properties and negatives ---


def test_sign_verify_roundtrip_and_tamper() -> None:
    private_key = 0xDEADBEEF
    public_key = derive_public_key(private_key)
    digest = hashlib.sha256(b"round trip").digest()
    r, s, _ = sign(digest, private_key)
    assert verify(digest, (r, s), public_key)
    assert not verify(hashlib.sha256(b"other").digest(), (r, s), public_key)
    assert not verify(digest, (r, s + 1), public_key)
    assert not verify(digest, (r, s), derive_public_key(private_key + 1))


def test_low_s_is_canonical() -> None:
    for i, entry in enumerate(load_golden()["signatures"]):
        digest = bytes.fromhex(entry["digest"].removeprefix("0x"))
        _, s, _ = sign(digest, _hex_to_int(entry["private_key"]))
        assert s <= SECP256K1.n // 2, f"high s leaked at vector {i}"


def test_group_order_arithmetic() -> None:
    g = SECP256K1.g
    assert scalar_mult(SECP256K1, SECP256K1.n, g) is None  # n*G = infinity
    n_minus_1 = scalar_mult(SECP256K1, SECP256K1.n - 1, g)
    assert point_add(SECP256K1, n_minus_1, g) is None  # (n-1)G + G = infinity
    assert is_on_curve(SECP256K1, n_minus_1)


def test_invalid_inputs_rejected() -> None:
    digest = bytes(32)
    for bad_key in (0, SECP256K1.n, SECP256K1.n + 5):
        with pytest.raises(ValueError):
            sign(digest, bad_key)
        with pytest.raises(ValueError):
            derive_public_key(bad_key)
    with pytest.raises(ValueError):
        sign(b"short digest", 1)
