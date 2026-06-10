"""Minimal Ethereum ABI codec for the anchoring precompile. Stdlib only.

Implements head/tail encoding per the Solidity ABI spec for exactly the
types the vendored ABI (anchoring.json) uses: uintN, bool, address,
string, bytes, tuple, and dynamic arrays of tuples. Entries are the ABI
JSON dicts themselves ({"type": ..., "components": [...]}), so the JSON
file stays the single source of truth.
"""

from __future__ import annotations

from typing import Any

from nvnm_cite.chain.keccak import keccak_256

Entry = dict[str, Any]

_WORD = 32


def canonical_type(entry: Entry) -> str:
    """The signature form of a type: tuples expand to their components."""
    kind = entry["type"]
    if kind.startswith("tuple"):
        inner = ",".join(canonical_type(c) for c in entry["components"])
        return f"({inner})" + kind[len("tuple") :]
    return kind


def function_signature(fn: Entry) -> str:
    args = ",".join(canonical_type(i) for i in fn["inputs"])
    return f"{fn['name']}({args})"


def function_selector(fn: Entry) -> bytes:
    return keccak_256(function_signature(fn).encode("ascii"))[:4]


def _is_dynamic(entry: Entry) -> bool:
    kind = entry["type"]
    if kind.endswith("[]") or kind in ("string", "bytes"):
        return True
    if kind.startswith("tuple"):
        return any(_is_dynamic(c) for c in entry["components"])
    return False


def _static_width(entry: Entry) -> int:
    if entry["type"].startswith("tuple"):
        return sum(_static_width(c) for c in entry["components"])
    return _WORD


def _head_width(entry: Entry) -> int:
    return _WORD if _is_dynamic(entry) else _static_width(entry)


def _uint_word(value: int) -> bytes:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"expected a non-negative int, got {value!r}")
    return value.to_bytes(_WORD, "big")  # raises OverflowError past 2**256


def _pad32(data: bytes) -> bytes:
    return data + b"\x00" * (-len(data) % _WORD)


def _element_entry(entry: Entry) -> Entry:
    inner = dict(entry)
    inner["type"] = entry["type"][:-2]
    return inner


def _encode_static(entry: Entry, value: Any) -> bytes:
    kind = entry["type"]
    if kind.startswith("tuple"):
        return b"".join(
            _encode_static(c, v)
            for c, v in zip(entry["components"], value, strict=True)
        )
    if kind.startswith("uint"):
        word = _uint_word(value)
        bits = int(kind[4:] or 256)
        if value.bit_length() > bits:
            raise ValueError(f"{value} does not fit {kind}")
        return word
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"expected bool, got {value!r}")
        return _uint_word(int(value))
    if kind == "address":
        body = value[2:] if value[:2] in ("0x", "0X") else value
        if len(body) != 40:
            raise ValueError(f"address must be 20 bytes of hex, got {value!r}")
        return bytes(12) + bytes.fromhex(body)
    raise ValueError(f"unsupported static type {kind}")


def _encode_dynamic(entry: Entry, value: Any) -> bytes:
    kind = entry["type"]
    if kind == "string":
        if not isinstance(value, str):
            raise ValueError(f"expected str, got {value!r}")
        raw = value.encode("utf-8")
        return _uint_word(len(raw)) + _pad32(raw)
    if kind == "bytes":
        if not isinstance(value, (bytes, bytearray)):
            raise ValueError(f"expected bytes, got {value!r}")
        return _uint_word(len(value)) + _pad32(bytes(value))
    if kind.endswith("[]"):
        element = _element_entry(entry)
        return _uint_word(len(value)) + encode_values([element] * len(value), value)
    if kind == "tuple":
        return encode_values(entry["components"], value)
    raise ValueError(f"unsupported dynamic type {kind}")


def encode_values(entries: list[Entry], values: list[Any]) -> bytes:
    """Head/tail-encode `values` against the ABI `entries` for one block.

    Offsets are relative to the block start, which makes this directly
    reusable for tuple bodies and array element blocks.
    """
    if len(entries) != len(values):
        raise ValueError(f"expected {len(entries)} values, got {len(values)}")
    head_width = sum(_head_width(e) for e in entries)
    heads: list[bytes] = []
    tails: list[bytes] = []
    tail_length = 0
    for entry, value in zip(entries, values, strict=True):
        if _is_dynamic(entry):
            heads.append(_uint_word(head_width + tail_length))
            tail = _encode_dynamic(entry, value)
            tails.append(tail)
            tail_length += len(tail)
        else:
            heads.append(_encode_static(entry, value))
    return b"".join(heads) + b"".join(tails)


def encode_call(fn: Entry, values: list[Any]) -> bytes:
    """Selector + encoded arguments: complete calldata for `fn`."""
    return function_selector(fn) + encode_values(fn["inputs"], values)


# --- decoding ---


def _decode_static(entry: Entry, blob: bytes) -> Any:
    kind = entry["type"]
    if kind.startswith("tuple"):
        values = []
        pos = 0
        for component in entry["components"]:
            width = _static_width(component)
            values.append(_decode_static(component, blob[pos : pos + width]))
            pos += width
        return values
    word = blob[:_WORD]
    if kind.startswith("uint"):
        return int.from_bytes(word, "big")
    if kind == "bool":
        return bool(int.from_bytes(word, "big"))
    if kind == "address":
        return "0x" + word[12:].hex()
    raise ValueError(f"unsupported static type {kind}")


def _decode_dynamic(entry: Entry, blob: bytes) -> Any:
    kind = entry["type"]
    if kind == "string":
        length = int.from_bytes(blob[:_WORD], "big")
        return blob[_WORD : _WORD + length].decode("utf-8")
    if kind == "bytes":
        length = int.from_bytes(blob[:_WORD], "big")
        return bytes(blob[_WORD : _WORD + length])
    if kind.endswith("[]"):
        count = int.from_bytes(blob[:_WORD], "big")
        element = _element_entry(entry)
        return decode_values([element] * count, blob[_WORD:])
    if kind == "tuple":
        return decode_values(entry["components"], blob)
    raise ValueError(f"unsupported dynamic type {kind}")


def decode_values(entries: list[Entry], blob: bytes) -> list[Any]:
    """Decode one block of values; mirror of encode_values."""
    values: list[Any] = []
    pos = 0
    for entry in entries:
        if _is_dynamic(entry):
            offset = int.from_bytes(blob[pos : pos + _WORD], "big")
            pos += _WORD
            values.append(_decode_dynamic(entry, blob[offset:]))
        else:
            width = _static_width(entry)
            values.append(_decode_static(entry, blob[pos : pos + width]))
            pos += width
    return values


def decode_result(fn: Entry, data: bytes) -> list[Any]:
    """Decode an eth_call return blob against `fn`'s outputs."""
    return decode_values(fn["outputs"], data)
