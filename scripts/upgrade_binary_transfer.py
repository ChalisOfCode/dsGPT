"""Confidential, hash-bound APK transfer to one disposable acceptance runner.

Only APK bytes are transferred; never signing keys, backups, credentials or logs.
The receiver key exists only in the job's private temporary directory. The public
challenge must be obtained from the verified job artifact, not an untrusted URL.
Ciphertext may travel through an isolated public branch; it is not a release.
"""
import argparse
import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FILES = {
    "baseline.apk": (10598294, "d60013f75a657f022681b97ee6925719b80fc573ab4c30f5b2cc95aeb7bbcb41"),
    "candidate.apk": (7769952, "d3ce920b2ee1e7d5110f959d9c663c3e284619a234e7f35f73975feef8c512db"),
}
MAX_ENVELOPE = 26 * 1024 * 1024
DOMAIN = b"dsGPT disposable APK transfer v1\x00"
TRANSFER_PREFIX = "android"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def oaep():
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=DOMAIN)


def check_files(files):
    if set(files) != set(FILES):
        raise ValueError("Unexpected transfer entries")
    for name, content in files.items():
        size, digest = FILES[name]
        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Transfer bytes differ from reviewed APK")


def validate_challenge(challenge, run, source, now=None):
    now = int(time.time()) if now is None else now
    if (set(challenge) != {"format", "run", "source", "expires", "public_key"}
            or challenge["format"] != 1 or challenge["run"] != str(run)
            or challenge["source"] != source or len(source) != 40
            or any(c not in "0123456789abcdef" for c in source)
            or type(challenge["expires"]) is not int
            or not now < challenge["expires"] <= now + 1200):
        raise ValueError("Stale or mismatched receiver challenge")
    key = serialization.load_pem_public_key(challenge["public_key"].encode())
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size != 3072:
        raise ValueError("Unexpected receiver key")
    return key


def seal(challenge, files, run, source):
    recipient = validate_challenge(challenge, run, source)
    check_files(files)
    plaintext = canonical({name: base64.b64encode(data).decode() for name, data in files.items()})
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    aad = DOMAIN + canonical(challenge)
    header = canonical({"wrapped": base64.b64encode(recipient.encrypt(key, oaep())).decode(),
                        "nonce": base64.b64encode(nonce).decode()})
    return len(header).to_bytes(4, "big") + header + AESGCM(key).encrypt(nonce, plaintext, aad)


def unseal(envelope, challenge, private_key, run, source):
    validate_challenge(challenge, run, source)
    if len(envelope) > MAX_ENVELOPE or len(envelope) < 32:
        raise ValueError("Invalid transfer size")
    count = int.from_bytes(envelope[:4], "big")
    if not 1 <= count <= 1024:
        raise ValueError("Invalid transfer header")
    header = json.loads(envelope[4:4 + count])
    if set(header) != {"wrapped", "nonce"}:
        raise ValueError("Invalid transfer header")
    key = private_key.decrypt(base64.b64decode(header["wrapped"], validate=True), oaep())
    plaintext = AESGCM(key).decrypt(base64.b64decode(header["nonce"], validate=True),
                                    envelope[4 + count:], DOMAIN + canonical(challenge))
    value = json.loads(plaintext)
    files = {name: base64.b64decode(data, validate=True) for name, data in value.items()}
    check_files(files)
    return files


def runner_directory(path):
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != "ChalisOfCode/dsGPT"):
        raise RuntimeError("Receiver requires the disposable public repository runner")
    root = Path(os.environ["RUNNER_TEMP"]).resolve()
    if path.resolve() == root or not path.resolve().is_relative_to(root):
        raise ValueError("Receiver files must remain in runner temporary storage")


def fetch_envelope(url):
    # Fixed-size transport parts avoid connector request-size limits. Only
    # ciphertext is exposed. AES-GCM and the reviewed APK hashes still decide
    # authenticity; this public manifest never supplies trusted plaintext paths.
    with urllib.request.urlopen(url + "/manifest.json", timeout=15) as response:
        raw = response.read(4097)
    if len(raw) > 4096:
        raise ValueError("Transfer manifest too large")
    manifest = json.loads(raw)
    if (set(manifest) != {"format", "bytes", "sha256", "parts"}
            or manifest["format"] != 1 or type(manifest["bytes"]) is not int
            or not 32 <= manifest["bytes"] <= MAX_ENVELOPE
            or type(manifest["parts"]) is not int
            or manifest["parts"] != (manifest["bytes"] + 393215) // 393216
            or not isinstance(manifest["sha256"], str)
            or len(manifest["sha256"]) != 64):
        raise ValueError("Invalid transfer manifest")
    output = bytearray()
    for index in range(manifest["parts"]):
        with urllib.request.urlopen(url + f"/part-{index:03d}.bin", timeout=15) as response:
            part = response.read(393217)
        expected = min(393216, manifest["bytes"] - len(output))
        if len(part) != expected:
            raise ValueError("Incomplete transfer part")
        output.extend(part)
    if hashlib.sha256(output).hexdigest() != manifest["sha256"]:
        raise ValueError("Transfer ciphertext changed")
    return bytes(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "receive", "seal"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--challenge", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "seal":
        challenge = json.loads(args.challenge.read_bytes())
        files = {name: (args.directory / name).read_bytes() for name in FILES}
        envelope = seal(challenge, files, args.run, args.source)
        with args.output.open("xb") as stream:
            stream.write(envelope)
        print("Encrypted reviewed APK pair for the verified disposable receiver.")
        return
    runner_directory(args.directory)
    key_path = args.directory / "receiver.pem"
    if args.mode == "prepare":
        args.directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        with key_path.open("xb") as stream:
            os.chmod(key_path, 0o600)
            stream.write(private.private_bytes(serialization.Encoding.PEM,
                         serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        challenge = {"format": 1, "run": args.run, "source": args.source,
                     "expires": int(time.time()) + 1200,
                     "public_key": private.public_key().public_bytes(
                         serialization.Encoding.PEM,
                         serialization.PublicFormat.SubjectPublicKeyInfo).decode()}
        validate_challenge(challenge, args.run, args.source)
        args.challenge.parent.mkdir(parents=True, exist_ok=True)
        args.challenge.write_bytes(canonical(challenge))
        return
    challenge = json.loads(args.challenge.read_bytes())
    private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    # Fixed repo/branch/file only, bounded response; never a caller-supplied URL.
    if not args.run.isdigit():
        raise ValueError("Invalid run")
    url = ("https://raw.githubusercontent.com/ChalisOfCode/dsGPT/"
           f"transfer/{TRANSFER_PREFIX}-{args.run}")
    deadline = time.monotonic() + 600
    try:
        while time.monotonic() < deadline:
            try:
                envelope = fetch_envelope(url)
                files = unseal(envelope, challenge, private, args.run, args.source)
                for name, data in files.items():
                    with (args.directory / name).open("xb") as stream:
                        os.chmod(args.directory / name, 0o600)
                        stream.write(data)
                print("Exact APK pair decrypted and hash verified; no private key transferred.")
                return
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise RuntimeError("Transfer endpoint failed") from None
            time.sleep(10)
        raise RuntimeError("Bounded encrypted input window expired")
    finally:
        key_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
