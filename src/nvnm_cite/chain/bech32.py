"""Bech32 (BIP-173) address conversion between EVM 0x and Cosmos nvnm1... forms.

The anchoring precompile returns registry creators as bech32 strings while
the EVM side (wallets, tx senders) speaks 0x addresses. Both encode the same
20-byte payload. Stdlib only, like the rest of chain/.
"""

from __future__ import annotations

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_GEN = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)

DEFAULT_HRP = "nvnm"


def _polymod(values: list[int]) -> int:
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= _GEN[i] if ((b >> i) & 1) else 0
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data: bytes | list[int], frombits: int, tobits: int, pad: bool) -> list[int]:
    acc = 0
    bits = 0
    out: list[int] = []
    maxv = (1 << tobits) - 1
    for value in data:
        if value < 0 or value >> frombits:
            raise ValueError("invalid value for base conversion")
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)
    if pad:
        if bits:
            out.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        raise ValueError("invalid padding in base conversion")
    return out


def bech32_encode(hrp: str, payload: bytes) -> str:
    data = _convertbits(payload, 8, 5, True)
    checksum_input = _hrp_expand(hrp) + data + [0, 0, 0, 0, 0, 0]
    polymod = _polymod(checksum_input) ^ 1
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_CHARSET[d] for d in data + checksum)


def bech32_decode(addr: str) -> tuple[str, bytes]:
    if addr != addr.lower() and addr != addr.upper():
        raise ValueError("mixed-case bech32 string")
    addr = addr.lower()
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr):
        raise ValueError("malformed bech32 string")
    hrp, data_part = addr[:pos], addr[pos + 1 :]
    data = []
    for c in data_part:
        idx = _CHARSET.find(c)
        if idx == -1:
            raise ValueError(f"invalid bech32 character {c!r}")
        data.append(idx)
    if _polymod(_hrp_expand(hrp) + data) != 1:
        raise ValueError("bad bech32 checksum")
    payload = bytes(_convertbits(data[:-6], 5, 8, False))
    return hrp, payload


def eth_to_bech32(address: str, hrp: str = DEFAULT_HRP) -> str:
    raw = address.lower().removeprefix("0x")
    if len(raw) != 40:
        raise ValueError(f"expected a 20-byte 0x address, got {address!r}")
    return bech32_encode(hrp, bytes.fromhex(raw))


def bech32_to_eth(address: str, hrp: str = DEFAULT_HRP) -> str:
    got_hrp, payload = bech32_decode(address)
    if got_hrp != hrp:
        raise ValueError(f"expected hrp {hrp!r}, got {got_hrp!r}")
    if len(payload) != 20:
        raise ValueError(f"expected a 20-byte payload, got {len(payload)}")
    return "0x" + payload.hex()
