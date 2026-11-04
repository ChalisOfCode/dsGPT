"""Exercise the actual NSIS installer and installed managed backend on a fresh CI user."""

import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path


def wait_for(function, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = function()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("Installed application did not become ready")


def native_ui(setup):
    from dsgpt_acceptance.__main__ import port
    from dsgpt_acceptance.cdp import CDP

    from dsgpt import managed
    from dsgpt.bootstrap import WindowsVault

    identifier = uuid.uuid4().hex
    debug_port = port()
    # The normal vault is checked below; this isolated WebView uses the exact same
    # owner wiring function and native keyring encoding without retaining CI chats.
    managed.wire_desktop(
        WindowsVault(setup.directory),
        WindowsVault(
            setup.directory,
            target="backend-connection.dsGPT-acceptance-" + identifier,
            encoding="utf-16-le",
        ),
    )
    env = dict(
        os.environ,
        DSGPT_ACCEPTANCE_RUN_ID=identifier,
        DSGPT_ACCEPTANCE_DEBUG_PORT=str(debug_port),
        DSGPT_ACCEPTANCE_PROFILE=str(setup.private / ("webview-" + identifier)),
    )
    child = subprocess.Popen([str(setup.kit / "client/dsGPT.exe")], env=env)
    cdp = None
    try:

        def connect():
            try:
                pages = setup.http.get(f"http://127.0.0.1:{debug_port}/json/list").json()
                page = next(v for v in pages if v.get("type") == "page")
                return CDP(page["webSocketDebuggerUrl"])
            except Exception:
                return None

        cdp = wait_for(connect, 60)

        def evaluate(js):
            return cdp.evaluate(js)

        wait_for(lambda: evaluate("!!document.querySelector('textarea[aria-label=Message]')"))
        assert evaluate("window.__TAURI_INTERNALS__.invoke('restore_connection')") == managed.ORIGIN
        evaluate("document.querySelector('button[aria-label=\"New chat\"]').click()")
        evaluate(
            "(() => {const t=document.querySelector('textarea[aria-label=Message]'); "
            "Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')"
            ".set.call(t,'Reply with READY only.'); "
            "t.dispatchEvent(new Event('input',{bubbles:true}));})()"
        )
        wait_for(
            lambda: evaluate(
                "!!document.querySelector('button[aria-label=\"Send ↑\"]:not(:disabled)')"
            )
        )
        evaluate("document.querySelector('button[aria-label=\"Send ↑\"]:not(:disabled)').click()")
        wait_for(
            lambda: evaluate(
                "[...document.querySelectorAll('article')].some(a=>a.innerText.includes('READY'))"
            ),
            180,
        )
        return {
            "native_window_opened": True,
            "managed_credential_auto_restored": True,
            "actual_local_model_reply_in_ui": True,
        }
    finally:
        if cdp:
            try:
                cdp.evaluate("window.__TAURI_INTERNALS__.invoke('disconnect')")
            finally:
                cdp.close()
        child.terminate()
        child.wait(timeout=20)


def phase(args):
    from dsgpt_application.__main__ import Setup

    from dsgpt import installation, managed
    from dsgpt.bootstrap import WindowsVault
    from dsgpt.startup import startup

    setup = Setup(args.install_dir, ci=False, launch=False)
    receipt = args.output / "private-receipt.json"
    evidence = {}
    try:
        evidence["integrity"] = setup.integrity()
        if args.phase == "first":
            evidence["dependencies"] = setup.desktop_dependencies()
            evidence["model_setup"] = setup.local_setup()
            evidence["backend"] = setup.prepare_backend()
            owner = WindowsVault(setup.directory).read()
            client = WindowsVault(
                setup.directory, target=managed.CLIENT_TARGET, encoding="utf-16-le"
            ).read()
            assert client == {"origin": managed.ORIGIN, "token": owner["token"]}
            evidence["normal_credential_wired"] = True
            chat = setup.request(
                "POST", "/v1/conversations", {"title": "Installer persistence fixture"}
            )
            setup.request(
                "POST",
                "/v1/conversations/" + chat["id"] + "/messages",
                {
                    "request_id": str(uuid.uuid4()),
                    "content": "Reply with READY only.",
                    "model_id": setup.state["model_ids"][0],
                },
            )

            def replied():
                rows = setup.request("GET", "/v1/conversations/" + chat["id"] + "/messages")
                return rows if len(rows) == 2 and rows[-1]["status"] == "completed" else None

            rows = wait_for(replied, 180)
            assert rows[-1]["content"].strip()
            evidence["actual_installed_local_reply"] = True
            receipt.write_text(
                json.dumps(
                    {
                        "chat_id": chat["id"],
                        "owner_sha256": hashlib.sha256(owner["token"].encode()).hexdigest(),
                        "reply_sha256": hashlib.sha256(rows[-1]["content"].encode()).hexdigest(),
                    }
                )
            )
            evidence["native_ui"] = native_ui(setup)
            managed.stop(setup.directory)
            startup(setup.kit, "enable", confirm=True)
            assert managed.main(["start"]) == 0
            evidence["scheduled_backend_restart"] = (
                managed.verify_running(owner["token"]) is not None
            )
            assert evidence["scheduled_backend_restart"]
        else:
            old = json.loads(receipt.read_text())
            assert managed.main(["start"]) == 0
            owner = WindowsVault(setup.directory).read()
            assert hashlib.sha256(owner["token"].encode()).hexdigest() == old["owner_sha256"]
            rows = setup.request("GET", "/v1/conversations/" + old["chat_id"] + "/messages")
            assert hashlib.sha256(rows[-1]["content"].encode()).hexdigest() == old["reply_sha256"]
            evidence["owner_and_chat_survive_reinstall"] = True
        state = installation.load(setup.directory)
        assert state.get("model_ids")
        evidence["models_persisted"] = True
    finally:
        managed.stop(setup.directory)
        setup.http.close()
    (args.output / (args.phase + ".json")).write_text(json.dumps(evidence, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=["first", "restart"])
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError(
            "This install/uninstall check is restricted to the disposable CI account"
        )
    args.output.mkdir(parents=True, exist_ok=True)
    if args.phase:
        phase(args)
        return
    data = Path(os.environ["LOCALAPPDATA"]) / "dsGPT/managed/data"
    assert not (data / "application-setup.json").exists(), (
        "CI account must start without an application profile"
    )
    for step in ("first", "restart"):
        subprocess.run(
            # NSIS parses /D as an unquoted command-line tail, including spaces.
            # Passing a Python argument list quotes it and silently loses the override.
            subprocess.list2cmdline([str(args.installer.resolve()), "/S", "/NOSETUP"])
            + " /D="
            + str(args.install_dir.resolve()),
            check=True,
            timeout=180,
        )
        assert (args.install_dir / "Uninstall.exe").is_file()
        subprocess.run(
            [
                str(args.install_dir / "python/python.exe"),
                "-B",
                "-I",
                str(Path(__file__).resolve()),
                "--phase",
                step,
                "--install-dir",
                str(args.install_dir),
                "--output",
                str(args.output),
            ],
            check=True,
            timeout=600,
        )
    databases = list(data.glob("*.db")) + list(data.glob("*.sqlite*"))
    assert databases, "Persistent database missing"
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in databases if p.is_file()}
    subprocess.run(
        subprocess.list2cmdline([str(args.install_dir / "Uninstall.exe"), "/S"])
        + " _?="
        + str(args.install_dir.resolve()),
        check=True,
        timeout=120,
    )
    wait_for(lambda: not (args.install_dir / "python/python.exe").exists(), 30)
    assert all(
        (data / name).is_file() and hashlib.sha256((data / name).read_bytes()).hexdigest() == value
        for name, value in hashes.items()
    )
    evidence = {
        "first_install": json.loads((args.output / "first.json").read_text()),
        "reinstall": json.loads((args.output / "restart.json").read_text()),
        "uninstall_removes_program_preserves_data": True,
        "scope": "Real installed app, Windows credential and startup APIs, local Ollama reply. "
        "Docker Linux/Tailscale/Pixel require the physical target "
        "and are not claimed by this CI run.",
    }
    (args.output / "application-installation.json").write_text(json.dumps(evidence, indent=2))
    (args.output / "private-receipt.json").unlink()
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
