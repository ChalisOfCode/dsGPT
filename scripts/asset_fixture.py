"""Real native-tool regression fixture, executed inside the isolated container only."""

# ruff: noqa: E501
import hashlib
import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path

from PIL import Image

spec = importlib.util.spec_from_file_location("asset_worker", "/opt/dsgpt/asset_worker.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
root = Path.cwd()
sdk = Path("/opt/android")
tools = sdk / "build-tools/35.0.0"


def run(args):
    subprocess.run([str(x) for x in args], check=True)


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


fixture = root / "fixture"
(fixture / "res/values").mkdir(parents=True)
(fixture / "AndroidManifest.xml").write_text(
    """<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.dsgpt.fixture"><uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35"/><application android:label="@string/app_name"><activity android:name=".MainActivity" android:exported="true"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>"""
)
(fixture / "res/values/strings.xml").write_text(
    '<resources><string name="app_name">Original label</string></resources>'
)
(fixture / "MainActivity.java").write_text(
    """package org.dsgpt.fixture; public class MainActivity extends android.app.Activity { public String message(){return "original message";} public void onCreate(android.os.Bundle b){super.onCreate(b);android.widget.TextView t=new android.widget.TextView(this);t.setText(message());setContentView(t);} }"""
)
(fixture / "classes").mkdir()
(fixture / "dex").mkdir()
run(
    [
        "javac",
        "-source",
        "8",
        "-target",
        "8",
        "-classpath",
        sdk / "platforms/android-35/android.jar",
        "-d",
        fixture / "classes",
        fixture / "MainActivity.java",
    ]
)
run(
    [
        tools / "d8",
        "--lib",
        sdk / "platforms/android-35/android.jar",
        "--output",
        fixture / "dex",
        fixture / "classes/org/dsgpt/fixture/MainActivity.class",
    ]
)
original = root / "original.apk"
run(
    [
        tools / "aapt",
        "package",
        "-f",
        "-M",
        fixture / "AndroidManifest.xml",
        "-S",
        fixture / "res",
        "-I",
        sdk / "platforms/android-35/android.jar",
        "-F",
        original,
    ]
)
with zipfile.ZipFile(original, "a") as z:
    z.write(fixture / "dex/classes.dex", "classes.dex")
before = digest(original)
a.apk_decode(original, root / "decoded.zip")
a.apk_decode(original, root / "java.zip", True)
with zipfile.ZipFile(root / "java.zip") as z:
    assert any(b"original message" in z.read(n) for n in z.namelist() if n.endswith(".java"))
with zipfile.ZipFile(root / "decoded.zip") as z:
    edits = []
    for member, old, new in [
        ("res/values/strings.xml", "Original label", "Modified label"),
        ("smali/org/dsgpt/fixture/MainActivity.smali", "original message", "modified message"),
    ]:
        data = z.read(member)
        assert old.encode() in data
        edits.append(
            {"path": member, "sha256": hashlib.sha256(data).hexdigest(), "old": old, "new": new}
        )
(root / "apk-patches.json").write_text(json.dumps(edits))
apk_result = a.apk_rebuild(root / "decoded.zip", root / "apk-patches.json", root / "modified.apk")
a.apk_decode(root / "modified.apk", root / "modified-decoded.zip")
with zipfile.ZipFile(root / "modified-decoded.zip") as z:
    assert b"Modified label" in z.read("res/values/strings.xml")
    assert b"modified message" in z.read("smali/org/dsgpt/fixture/MainActivity.smali")
assert digest(original) == before
(root / "fixture.cpp").write_text(
    '#include <cstdio>\nvolatile int value=41;\nint main(){std::puts("ORIGINAL_MARKER");return value+1==42?0:1;}\n'
)
run(["x86_64-w64-mingw32-g++", "-O0", "-static", root / "fixture.cpp", "-o", root / "original.exe"])
exe_before = digest(root / "original.exe")
raw = (root / "original.exe").read_bytes()
offset = raw.index(b"ORIGINAL_MARKER")
(root / "exe-patches.json").write_text(
    json.dumps(
        {
            "sha256": exe_before,
            "patches": [
                {
                    "offset": offset,
                    "old_hex": b"ORIGINAL_MARKER".hex(),
                    "new_hex": b"MODIFIED_MARKER".hex(),
                }
            ],
        }
    )
)
pe_report = a.exe_inspect(root / "original.exe", root / "pe.json")
decompiled = a.exe_decompile(root / "original.exe", root / "native-source.zip")
with zipfile.ZipFile(root / "native-source.zip") as z:
    assert "functions.tsv" in z.namelist()
    assert any(name.endswith(".c") for name in z.namelist())
patched = a.exe_patch(root / "original.exe", root / "exe-patches.json", root / "modified.exe")
assert (
    digest(root / "original.exe") == exe_before
    and b"MODIFIED_MARKER" in (root / "modified.exe").read_bytes()
)
(root / "Managed.cs").write_text(
    'class Program { static void Main(){ System.Console.WriteLine("Original managed"); } }'
)
run(["mcs", "-out:managed.exe", root / "Managed.cs"])
a.exe_decompile(root / "managed.exe", root / "managed-source.zip")
with zipfile.ZipFile(root / "managed-source.zip") as z:
    il = z.read("program.il")
    assert b"Original managed" in il
(root / "il-patches.json").write_text(
    json.dumps(
        [
            {
                "path": "program.il",
                "sha256": hashlib.sha256(il).hexdigest(),
                "old": "Original managed",
                "new": "Modified managed",
            }
        ]
    )
)
run(
    [
        "/usr/bin/python3",
        "-I",
        "/opt/dsgpt/asset_worker.py",
        "exe-il-rebuild",
        "managed-source.zip",
        "il-patches.json",
        "managed-modified.exe",
    ]
)
assert (
    subprocess.check_output(["mono", str(root / "managed-modified.exe")]).strip()
    == b"Modified managed"
)
run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x180:rate=10",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=16000",
        "-t",
        "4",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-threads",
        "2",
        root / "original.mp4",
    ]
)
video_before = digest(root / "original.mp4")
frames = a.video_frames(root / "original.mp4", root / "storyboard.jpg", 0, 4, 6)
assert len(frames["frames"]) == 6 and 3.5 < float(frames["duration"]) < 4.5
(root / "video-edit.json").write_text(
    json.dumps({"start": 1, "duration": 2, "mode": "mp4", "width": 320, "fps": 10})
)
clip = a.video_edit(root / "original.mp4", root / "video-edit.json", root / "clip.mp4")
assert 1.8 < float(clip["media"]["format"]["duration"]) < 2.3
(root / "audio-edit.json").write_text(json.dumps({"start": 0, "duration": 2, "mode": "audio"}))
audio = a.video_edit(root / "original.mp4", root / "audio-edit.json", root / "audio.wav")
assert audio["media"]["streams"][0]["sample_rate"] == "16000"
(root / "gif-edit.json").write_text(
    json.dumps({"start": 0, "duration": 1, "mode": "gif", "width": 320, "fps": 5})
)
a.video_edit(root / "original.mp4", root / "gif-edit.json", root / "animation.gif")

with Image.open(root / "animation.gif") as animation:
    assert animation.n_frames >= 4
assert digest(root / "original.mp4") == video_before
report = {
    "apk": apk_result,
    "java_decompilation": True,
    "pe": pe_report,
    "native_decompilation": decompiled,
    "exe_patch": patched,
    "managed_decompilation": True,
    "managed_il_rebuild_and_runtime": True,
    "animated_gif": True,
    "video_frames": frames,
    "clip_duration": clip["media"]["format"]["duration"],
    "audio_extraction": True,
    "originals_unchanged": True,
}
(root / "asset-verification.json").write_text(json.dumps(report, indent=2))
with zipfile.ZipFile(root / "asset-evidence.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for name in [
        "asset-verification.json",
        "original.exe",
        "modified.exe",
        "storyboard.jpg",
        "clip.mp4",
        "audio.wav",
        "native-source.zip",
        "java.zip",
        "managed-source.zip",
        "managed-modified.exe",
        "animation.gif",
    ]:
        z.write(root / name, name)
print(json.dumps({"checks": "passed", "report": report}))
