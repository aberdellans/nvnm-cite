import json
from pathlib import Path

import pytest

from nvnm_cite.chain.rlp import rlp_encode

GOLDEN = Path(__file__).parent / "golden" / "rlp" / "vectors.json"

LOREM = b"Lorem ipsum dolor sit amet, consectetur adipisicing elit"

# Worked examples from the Ethereum RLP specification, independent of the
# ethers-generated vectors.
PUBLISHED: list[tuple[object, str]] = [
    (b"dog", "83646f67"),
    ([b"cat", b"dog"], "c88363617483646f67"),
    (b"", "80"),
    ([], "c0"),
    (0, "80"),
    (15, "0f"),
    (1024, "820400"),
    (LOREM, "b838" + LOREM.hex()),
    ([[], [[]], [[], [[]]]], "c7c0c1c0c3c0c1c0"),
]


def _from_hex_tree(node: object) -> object:
    """Convert the JSON vector shape (nested hex strings) to rlp_encode input."""
    if isinstance(node, str):
        return bytes.fromhex(node.removeprefix("0x"))
    assert isinstance(node, list)
    return [_from_hex_tree(child) for child in node]


def load_vectors() -> list[dict[str, object]]:
    return json.loads(GOLDEN.read_text())["vectors"]


@pytest.mark.parametrize("item,expected", PUBLISHED, ids=lambda v: str(v)[:24])
def test_published_spec_examples(item: object, expected: str) -> None:
    assert rlp_encode(item).hex() == expected


@pytest.mark.parametrize("vector", load_vectors(), ids=lambda v: v["desc"])
def test_ethers_oracle_vectors(vector: dict[str, object]) -> None:
    item = _from_hex_tree(vector["item"])
    expected = str(vector["rlp"]).removeprefix("0x")
    assert rlp_encode(item).hex() == expected


def test_boundary_cases_present() -> None:
    descs = {v["desc"] for v in load_vectors()}
    assert {
        "single-0x7f", "single-0x80", "string-55B", "string-56B",
        "list-payload-55B", "list-payload-56B", "string-70000B",
    } <= descs


def test_int_encoding_matches_minimal_bytes() -> None:
    # Ints must encode exactly like their minimal big-endian byte string.
    for value in (0, 1, 127, 128, 255, 256, 1024, 2**64 - 1):
        as_bytes = value.to_bytes((value.bit_length() + 7) // 8, "big") if value else b""
        assert rlp_encode(value) == rlp_encode(as_bytes)


def test_rejected_types() -> None:
    with pytest.raises(ValueError):
        rlp_encode(-1)
    with pytest.raises(TypeError):
        rlp_encode(True)
    with pytest.raises(TypeError):
        rlp_encode("strings must be bytes")  # type: ignore[arg-type]
