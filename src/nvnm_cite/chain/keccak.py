"""Keccak-256 with ORIGINAL Keccak padding, as used by Ethereum.

This is not hashlib.sha3_256: FIPS-202 SHA-3 appends domain byte 0x06,
original Keccak appends 0x01, so the two produce different digests for
every input. Ethereum predates the NIST change and uses the original
padding. The golden suite pins the distinction with a negative test.

Pure standard-library implementation: Keccak-f[1600] permutation under
a sponge with rate 1088 bits / capacity 512 bits, 256-bit output.
"""

from __future__ import annotations

_MASK64 = (1 << 64) - 1

# Round constants for the iota step, one per round of Keccak-f[1600].
_ROUND_CONSTANTS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)

# Rotation offsets for the rho step, indexed by lane position x + 5*y.
_ROTATIONS = (
    0, 1, 62, 28, 27,
    36, 44, 6, 55, 20,
    3, 10, 43, 25, 39,
    41, 45, 15, 21, 8,
    18, 2, 61, 56, 14,
)

_RATE_BYTES = 136  # 1088-bit rate for 256-bit output
_LANES_PER_BLOCK = _RATE_BYTES // 8


def _rotl64(value: int, shift: int) -> int:
    return ((value << shift) | (value >> (64 - shift))) & _MASK64


def _keccak_f1600(state: list[int]) -> None:
    """Apply the 24-round Keccak-f[1600] permutation to `state` in place.

    `state` is 25 64-bit lanes indexed x + 5*y.
    """
    for round_constant in _ROUND_CONSTANTS:
        # theta
        c = [
            state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
            for x in range(5)
        ]
        d = [c[(x - 1) % 5] ^ _rotl64(c[(x + 1) % 5], 1) for x in range(5)]
        for i in range(25):
            state[i] ^= d[i % 5]

        # rho and pi: B[y, 2x+3y] = rotl(A[x, y], r[x, y])
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                source = x + 5 * y
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl64(
                    state[source], _ROTATIONS[source]
                )

        # chi
        for y in range(0, 25, 5):
            row = b[y : y + 5]
            for x in range(5):
                state[y + x] = row[x] ^ ((row[(x + 1) % 5] ^ _MASK64) & row[(x + 2) % 5])

        # iota
        state[0] ^= round_constant


def keccak_256(data: bytes) -> bytes:
    """Return the 32-byte Keccak-256 digest of `data` (original padding)."""
    # pad10*1 with the original 0x01 domain byte. When exactly one pad
    # byte fits, it carries both markers: 0x01 | 0x80 = 0x81.
    padded = bytearray(data)
    padded.append(0x01)
    padded.extend(b"\x00" * (-len(padded) % _RATE_BYTES))
    padded[-1] |= 0x80

    state = [0] * 25
    for offset in range(0, len(padded), _RATE_BYTES):
        for lane in range(_LANES_PER_BLOCK):
            start = offset + lane * 8
            state[lane] ^= int.from_bytes(padded[start : start + 8], "little")
        _keccak_f1600(state)

    return b"".join(state[lane].to_bytes(8, "little") for lane in range(4))


def keccak_256_hex(data: bytes) -> str:
    """Keccak-256 digest as a 0x-prefixed hex string."""
    return "0x" + keccak_256(data).hex()
