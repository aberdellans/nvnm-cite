import hashlib
import json
from pathlib import Path

import pytest

from nvnm_cite.chain.keccak import keccak_256, keccak_256_hex

GOLDEN = Path(__file__).parent / "golden" / "keccak" / "vectors.json"

# Documented Keccak-256 digests from the literature, independent of the
# ethers-generated vectors (which repeat these inputs, so a bad constant
# here would surface as a conflict between the two suites).
PUBLISHED = {
    b"": "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470",
    b"abc": "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45",
    b"The quick brown fox jumps over the lazy dog": (
        "4d741b6f1eb29cb2a9b9911c82f56fa8d73b04959d3d9d222895df6c0b28aa15"
    ),
}


def load_vectors() -> list[dict[str, str]]:
    return json.loads(GOLDEN.read_text())["vectors"]


@pytest.mark.parametrize("data,expected", PUBLISHED.items(), ids=lambda v: repr(v)[:20])
def test_published_digests(data: bytes, expected: str) -> None:
    assert keccak_256(data).hex() == expected


@pytest.mark.parametrize("vector", load_vectors(), ids=lambda v: v["desc"])
def test_ethers_oracle_vectors(vector: dict[str, str]) -> None:
    data = bytes.fromhex(vector["input_hex"])
    assert keccak_256_hex(data) == vector["keccak256"]


def test_rate_boundary_lengths_present() -> None:
    # The padding edge cases must stay in the golden file: 135 bytes forces
    # the single-byte 0x81 pad, 136 a full extra pad block, 137 a spillover.
    lengths = {len(bytes.fromhex(v["input_hex"])) for v in load_vectors()}
    assert {135, 136, 137, 271, 272, 273} <= lengths


def test_differs_from_nist_sha3() -> None:
    # hashlib.sha3_256 is FIPS-202 (domain byte 0x06); Keccak-256 uses the
    # original 0x01 padding. They must never agree.
    for data in (b"", b"abc", b"nvnm-cite", bytes(200)):
        assert keccak_256(data) != hashlib.sha3_256(data).digest()


def test_digest_shape() -> None:
    digest = keccak_256(b"shape")
    assert isinstance(digest, bytes) and len(digest) == 32
    assert keccak_256_hex(b"shape") == "0x" + digest.hex()
