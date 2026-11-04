"""Trusted fixture build recipe, run only inside the checked Android container."""

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

tools = Path("/opt/android/build-tools")
platform = "/opt/android/platform/android.jar"


def run(*args):
    subprocess.run(list(args), check=True)


for directory in ("classes", "dex"):
    Path(directory).mkdir()
run(
    "javac",
    "-encoding",
    "UTF-8",
    "-source",
    "8",
    "-target",
    "8",
    "-bootclasspath",
    platform,
    "-d",
    "classes",
    "MainActivity.java",
)
run(
    str(tools / "d8"),
    "--release",
    "--min-api",
    "26",
    "--thread-count",
    "2",
    "--lib",
    platform,
    "--output",
    "dex",
    "classes/org/dsgpt/fixture/MainActivity.class",
)
run(str(tools / "aapt2"), "compile", "--dir", "res", "-o", "resources.zip")
run(
    str(tools / "aapt2"),
    "link",
    "-I",
    platform,
    "--manifest",
    "AndroidManifest.xml",
    "-o",
    "base.apk",
    "resources.zip",
)
with zipfile.ZipFile("base.apk", "a", compression=zipfile.ZIP_STORED) as archive:
    archive.write("dex/classes.dex", "classes.dex")
run(str(tools / "zipalign"), "-f", "4", "base.apk", "aligned.apk")
# This ephemeral test-only key is created in tmpfs, is not the app's signing key,
# and is never collected as an artifact or included in the toolchain image.
run(
    "keytool",
    "-genkeypair",
    "-keystore",
    "fixture.jks",
    "-storepass",
    "android",
    "-keypass",
    "android",
    "-alias",
    "fixture",
    "-dname",
    "CN=dsGPT Test Fixture",
    "-keyalg",
    "RSA",
    "-keysize",
    "2048",
    "-validity",
    "1",
    "-noprompt",
)
run(
    str(tools / "apksigner"),
    "sign",
    "--ks",
    "fixture.jks",
    "--ks-pass",
    "pass:android",
    "--key-pass",
    "pass:android",
    "--ks-key-alias",
    "fixture",
    "--out",
    "fixture.apk",
    "aligned.apk",
)
run(str(tools / "apksigner"), "verify", "--verbose", "--print-certs", "fixture.apk")
run(str(tools / "zipalign"), "-c", "4", "fixture.apk")
run(str(tools / "aapt2"), "dump", "badging", "fixture.apk")
data = Path("fixture.apk").read_bytes()
print(
    json.dumps(
        {
            "apksigner_verified": True,
            "zipalign_verified": True,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "native_execution": False,
            "ephemeral_fixture_signing": True,
        }
    )
)
