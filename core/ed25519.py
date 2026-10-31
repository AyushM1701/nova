"""Ed25519 signatures (RFC 8032), in plain Python: Nova checks that a release's SHA256SUMS was signed by the key
pinned in core/update.py, with nothing to install. A signature takes a few milliseconds to check; this is used once
per update. The test vectors of the RFC are in tests.py."""
import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
I = pow(2, (P - 1) // 4, P)


def _inv(x):
    return pow(x, P - 2, P)


def _x_of(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * I % P
    if (x * x - x2) % P:
        return None
    return P - x if x & 1 != sign else x


_Gy = 4 * _inv(5) % P
_Gx = _x_of(_Gy, 0)
G = (_Gx, _Gy, 1, _Gx * _Gy % P)


def _add(a, b):
    (x1, y1, z1, t1), (x2, y2, z2, t2) = a, b
    A, B = (y1 - x1) * (y2 - x2) % P, (y1 + x1) * (y2 + x2) % P
    C, E2 = 2 * t1 * t2 * D % P, 2 * z1 * z2 % P
    E, F, G_, H = B - A, E2 - C, E2 + C, B + A
    return E * F % P, G_ * H % P, F * G_ % P, E * H % P


def _mul(scalar, point):
    result = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _same(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


def _decode(data):
    y = int.from_bytes(data, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _x_of(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _encode(point):
    zi = _inv(point[2])
    x, y = point[0] * zi % P, point[1] * zi % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _expand(seed):
    digest = hashlib.sha512(seed).digest()
    a = int.from_bytes(digest[:32], "little") & ((1 << 254) - 8) | (1 << 254)
    return a, digest[32:]


def _hash(*parts):
    return int.from_bytes(hashlib.sha512(b"".join(parts)).digest(), "little") % L


def public_key(seed):
    """The 32-byte public key of a 32-byte secret seed."""
    return _encode(_mul(_expand(seed)[0], G))


def sign(seed, message):
    a, prefix = _expand(seed)
    public = _encode(_mul(a, G))
    r = _hash(prefix, message)
    R = _encode(_mul(r, G))
    return R + ((r + _hash(R, public, message) * a) % L).to_bytes(32, "little")


def verify(public, message, signature):
    """True if `signature` (64 bytes) is `public`'s (32 bytes) signature of `message`."""
    if len(public) != 32 or len(signature) != 64:
        return False
    A, R = _decode(public), _decode(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if A is None or R is None or s >= L:
        return False
    return _same(_mul(s, G), _add(R, _mul(_hash(signature[:32], public, message), A)))
