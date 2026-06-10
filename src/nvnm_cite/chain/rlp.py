"""RLP encoding (Recursive Length Prefix), as defined by the Ethereum spec.

Encode-only: transaction signing serializes outbound payloads and never
needs to parse RLP coming back. Items are bytes, non-negative ints, or
(possibly nested) lists of items. Ints are encoded big-endian with no
leading zero bytes; zero encodes as the empty byte string, per the spec.
"""

from __future__ import annotations

RlpItem = bytes | int | list["RlpItem"]


def _int_to_min_bytes(value: int) -> bytes:
    if value < 0:
        raise ValueError("RLP cannot encode negative integers")
    if value == 0:
        return b""
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def _encode_length(length: int, short_offset: int) -> bytes:
    """Length prefix: short form (<=55) or long form with a length-of-length."""
    if length <= 55:
        return bytes([short_offset + length])
    length_bytes = _int_to_min_bytes(length)
    return bytes([short_offset + 55 + len(length_bytes)]) + length_bytes


def rlp_encode(item: RlpItem) -> bytes:
    """RLP-encode bytes, a non-negative int, or a nested list of items."""
    if isinstance(item, bool):
        # Reject before the int branch: True/False are almost certainly a bug
        # in the caller, not an attempt to encode 1/0.
        raise TypeError("RLP cannot encode bool")
    if isinstance(item, int):
        item = _int_to_min_bytes(item)
    if isinstance(item, (bytes, bytearray)):
        data = bytes(item)
        if len(data) == 1 and data[0] < 0x80:
            return data
        return _encode_length(len(data), 0x80) + data
    if isinstance(item, (list, tuple)):
        payload = b"".join(rlp_encode(element) for element in item)
        return _encode_length(len(payload), 0xC0) + payload
    raise TypeError(f"RLP cannot encode {type(item).__name__}")
