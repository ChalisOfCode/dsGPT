"""Authorized exact old Windows EXE and previously verified Android candidate only.

Reuses bounded multipart AES-GCM transport; this is a separate cryptographic
protocol domain and branch prefix. No signing keys, backups or user data.
"""
import upgrade_binary_transfer as transfer

transfer.FILES = {
    "baseline-setup.exe": (
        65609007, "99d879e7f7f4e415fb2e54a0ed4c45c184196235c119f6e58b6686dc38b13a9a"),
    "candidate.apk": (
        7769952, "d3ce920b2ee1e7d5110f959d9c663c3e284619a234e7f35f73975feef8c512db"),
}
transfer.MAX_ENVELOPE = 100 * 1024 * 1024
transfer.DOMAIN = b"dsGPT disposable Windows upgrade transfer v1\x00"
transfer.TRANSFER_PREFIX = "windows"

if __name__ == "__main__":
    transfer.main()
