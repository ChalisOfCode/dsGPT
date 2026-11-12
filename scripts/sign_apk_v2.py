"""Offline RSA APK-v2 envelope using existing cryptography primitives.

Format: https://source.android.com/docs/security/features/apksigning/v2
No key transfer or dependency installation. Caller supplies the existing key in
memory and exact input/certificate pins. Android SDK apksigner verification and
emulator update acceptance remain mandatory; this function is not their substitute.
Only unsigned, single-disk, non-ZIP64 inputs for Android 7+ are supported.
"""

import hashlib
import io
import struct
import zipfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

MAGIC = b"APK Sig Block 42"
ALGORITHM = 0x0103
V2_ID = 0x7109871A
MAX_APK = 64 * 1024**2


def u32(value):
    return struct.pack("<I", value)


def sized(value):
    return u32(len(value)) + value


def unsigned_sections(data):
    if not 22 <= len(data) <= MAX_APK or not data.startswith(b"PK\x03\x04"):
        raise ValueError("Unsupported APK size or prefix")
    end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if end < 0 or end + 22 > len(data):
        raise ValueError("ZIP end record missing")
    disk, start_disk, disk_count, count, size, offset, comment = struct.unpack_from(
        "<HHHHIIH", data, end + 4
    )
    if (disk or start_disk or disk_count != count or count in (0, 65535)
            or offset + size != end or offset < 30 or end + 22 + comment != len(data)
            or data[end - 20:end - 16] == b"PK\x06\x07"):
        raise ValueError("Unsupported ZIP layout")
    if data[offset - 16:offset] == MAGIC:
        raise ValueError("Input already has an APK signing block")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if len(names) != count or len(names) != len(set(names)):
            raise ValueError("Ambiguous ZIP entries")
        if "AndroidManifest.xml" not in names:
            raise ValueError("Android manifest missing")
        if any(n.upper().startswith("META-INF/") and (
                n.upper().endswith((".SF", ".RSA", ".DSA", ".EC"))
                or n.upper() == "META-INF/MANIFEST.MF") for n in names):
            raise ValueError("Input already has JAR signatures")
        if sum(e.file_size for e in entries) > 512 * 1024**2:
            raise ValueError("Expanded APK exceeds bound")
        if any(e.flag_bits & 1 or e.header_offset >= offset for e in entries):
            raise ValueError("Unsupported encrypted or overlapping ZIP")
        if archive.testzip() is not None:
            raise ValueError("ZIP entry checksum mismatch")
    return data[:offset], data[offset:end], data[end:]


def content_digest(sections):
    chunks = []
    for section in sections:
        for position in range(0, len(section), 1024**2):
            chunk = section[position:position + 1024**2]
            chunks.append(hashlib.sha256(b"\xa5" + u32(len(chunk)) + chunk).digest())
    return hashlib.sha256(b"\x5a" + u32(len(chunks)) + b"".join(chunks)).digest()


def sign(data, key, certificate_der, *, input_sha256, certificate_sha256):
    if hashlib.sha256(data).hexdigest() != input_sha256:
        raise ValueError("Unsigned APK hash mismatch")
    if hashlib.sha256(certificate_der).hexdigest() != certificate_sha256:
        raise ValueError("Signing certificate pin mismatch")
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise ValueError("Supported existing RSA key required")
    certificate = x509.load_der_x509_certificate(certificate_der)
    public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if certificate.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    ) != public:
        raise ValueError("Certificate and signing key differ")
    sections = unsigned_sections(data)
    digests = sized(u32(ALGORITHM) + sized(content_digest(sections)))
    signed_data = sized(digests) + sized(sized(certificate_der)) + sized(b"")
    signature = key.sign(signed_data, padding.PKCS1v15(), hashes.SHA256())
    key.public_key().verify(signature, signed_data, padding.PKCS1v15(), hashes.SHA256())
    signer = sized(signed_data) + sized(sized(u32(ALGORITHM) + sized(signature))) + sized(public)
    value = sized(sized(signer))
    pair = struct.pack("<Q", 4 + len(value)) + u32(V2_ID) + value
    block_size = len(pair) + 24
    block = struct.pack("<Q", block_size) + pair + struct.pack("<Q", block_size) + MAGIC
    end = bytearray(sections[2])
    struct.pack_into("<I", end, 16, len(sections[0]) + len(block))
    result = sections[0] + block + sections[1] + end
    if len(result) > MAX_APK:
        raise ValueError("Signed APK exceeds bound")
    return result
