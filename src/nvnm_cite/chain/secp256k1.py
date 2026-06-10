"""ECDSA over secp256k1 with RFC-6979 deterministic nonces. Stdlib only.

The arithmetic is generic short-Weierstrass (y^2 = x^3 + ax + b), so the
RFC 6979 Appendix A test vectors (curve P-256) exercise the exact same
code paths production uses; SECP256K1 is the only curve the rest of the
package ever touches.

Ethereum conventions when low_s=True (the default): s is canonicalized
to the lower half-order (EIP-2) and the recovery id reflects the flip.
The recovery id ignores the r >= n overflow bit, which cannot occur in
practice (probability ~2^-128); ethers and friends make the same call.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from nvnm_cite.chain.keccak import keccak_256

# An affine point; None is the point at infinity.
Point = tuple[int, int] | None


@dataclass(frozen=True)
class Curve:
    p: int  # field prime
    a: int  # curve coefficient a
    b: int  # curve coefficient b
    gx: int  # generator x
    gy: int  # generator y
    n: int  # generator (group) order

    @property
    def g(self) -> Point:
        return (self.gx, self.gy)


SECP256K1 = Curve(
    p=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F,
    a=0,
    b=7,
    gx=0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    gy=0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
    n=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141,
)


def is_on_curve(curve: Curve, point: Point) -> bool:
    if point is None:
        return True
    x, y = point
    return (y * y - (x * x * x + curve.a * x + curve.b)) % curve.p == 0


def point_add(curve: Curve, p1: Point, p2: Point) -> Point:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if (y1 + y2) % curve.p == 0:
            return None  # p2 is p1's inverse
        slope = (3 * x1 * x1 + curve.a) * pow(2 * y1, -1, curve.p)
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, curve.p)
    slope %= curve.p
    x3 = (slope * slope - x1 - x2) % curve.p
    y3 = (slope * (x1 - x3) - y1) % curve.p
    return (x3, y3)


def scalar_mult(curve: Curve, k: int, point: Point) -> Point:
    if k < 0:
        raise ValueError("scalar must be non-negative")
    result: Point = None
    addend = point
    while k:
        if k & 1:
            result = point_add(curve, result, addend)
        addend = point_add(curve, addend, addend)
        k >>= 1
    return result


# --- RFC 6979 deterministic nonce (HMAC-SHA256) ---


def _bits2int(data: bytes, qlen: int) -> int:
    value = int.from_bytes(data, "big")
    excess = len(data) * 8 - qlen
    return value >> excess if excess > 0 else value


def rfc6979_nonce(digest: bytes, private_key: int, order: int) -> int:
    """Deterministic k per RFC 6979 with HMAC-SHA256.

    `digest` is the already-hashed message (h1). `order` is the curve
    group order, passed in so the RFC's P-256 vectors validate this
    machinery directly.
    """
    qlen = order.bit_length()
    rolen = (qlen + 7) // 8
    h1 = _bits2int(digest, qlen) % order  # bits2octets, first half
    seed = private_key.to_bytes(rolen, "big") + h1.to_bytes(rolen, "big")

    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + seed, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + seed, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()

    while True:
        t = b""
        while len(t) < rolen:
            v = hmac.new(k, v, hashlib.sha256).digest()
            t += v
        candidate = _bits2int(t, qlen)
        if 1 <= candidate < order:
            return candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


# --- ECDSA ---


def sign(
    digest: bytes,
    private_key: int,
    curve: Curve = SECP256K1,
    low_s: bool = True,
) -> tuple[int, int, int]:
    """Sign a 32-byte digest. Returns (r, s, recovery_id).

    Deterministic (RFC 6979), so the same key and digest always produce
    the same signature. low_s=True applies Ethereum's EIP-2 canonical
    form; pass low_s=False only to reproduce raw RFC vectors.
    """
    if len(digest) != 32:
        raise ValueError("digest must be exactly 32 bytes")
    if not 1 <= private_key < curve.n:
        raise ValueError("private key out of range for curve")

    z = _bits2int(digest, curve.n.bit_length()) % curve.n
    k = rfc6979_nonce(digest, private_key, curve.n)
    point = scalar_mult(curve, k, curve.g)
    assert point is not None  # k in [1, n) guarantees a finite point
    rx, ry = point
    r = rx % curve.n
    s = (z + r * private_key) * pow(k, -1, curve.n) % curve.n
    if r == 0 or s == 0:
        # Probability ~2^-256; the RFC's retry path is unreachable in
        # practice and deliberately not implemented.
        raise ArithmeticError("degenerate signature; retry with a new digest")

    recovery_id = ry & 1
    if low_s and s > curve.n // 2:
        s = curve.n - s
        recovery_id ^= 1
    return r, s, recovery_id


def verify(
    digest: bytes,
    signature: tuple[int, int],
    public_key: tuple[int, int],
    curve: Curve = SECP256K1,
) -> bool:
    r, s = signature
    if not (1 <= r < curve.n and 1 <= s < curve.n):
        return False
    if not is_on_curve(curve, public_key):
        return False
    z = _bits2int(digest, curve.n.bit_length()) % curve.n
    s_inv = pow(s, -1, curve.n)
    u1 = z * s_inv % curve.n
    u2 = r * s_inv % curve.n
    point = point_add(
        curve, scalar_mult(curve, u1, curve.g), scalar_mult(curve, u2, public_key)
    )
    if point is None:
        return False
    return point[0] % curve.n == r


# --- Ethereum key and address helpers ---


def derive_public_key(private_key: int, curve: Curve = SECP256K1) -> tuple[int, int]:
    if not 1 <= private_key < curve.n:
        raise ValueError("private key out of range for curve")
    point = scalar_mult(curve, private_key, curve.g)
    assert point is not None
    return point


def public_key_to_address(public_key: tuple[int, int]) -> str:
    """Ethereum address: last 20 bytes of keccak-256(x || y), EIP-55 checksummed."""
    x, y = public_key
    digest = keccak_256(x.to_bytes(32, "big") + y.to_bytes(32, "big"))
    return _eip55_checksum(digest[12:])


def address_from_private_key(private_key: int) -> str:
    return public_key_to_address(derive_public_key(private_key))


def _eip55_checksum(address_bytes: bytes) -> str:
    plain = address_bytes.hex()
    mask = keccak_256(plain.encode("ascii")).hex()
    chars = [
        c.upper() if c.isalpha() and int(mask[i], 16) >= 8 else c
        for i, c in enumerate(plain)
    ]
    return "0x" + "".join(chars)
