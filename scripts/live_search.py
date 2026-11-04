"""Run a pinned SearXNG source checkout as a temporary local integration fixture."""

import argparse
import hashlib
import json
import os
import secrets
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from dsgpt.storage import utcnow
from dsgpt.web_retrieval import LocalSearch


def main():
    import asyncio

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--environment-proxy-fixture", action="store_true")
    parser.add_argument("--research-inputs", type=Path)
    parser.add_argument("--research-output", type=Path)
    parser.add_argument("--model-asset", default="qwen3-1-7b-q8-0")
    args = parser.parse_args()
    report = {
        "started_at": utcnow(),
        "upstream_commit": "1c10abe2d3e4ab7ddcc4e9da1a7d07dc7ca7f8f4",
        "environment_proxy_fixture": args.environment_proxy_fixture,
        "native_windows_tested": False,
        "requirements_sha256": hashlib.sha256(
            (args.source / "requirements.txt").read_bytes()
        ).hexdigest(),
    }
    with tempfile.TemporaryDirectory(prefix="dsgpt-searxng-") as temp:
        root = Path(temp)
        settings = {
            "use_default_settings": {
                "engines": {"keep_only": ["brave", "duckduckgo", "wikipedia"]}
            },
            "general": {"debug": False},
            "server": {
                "port": 18888,
                "bind_address": "127.0.0.1",
                "secret_key": secrets.token_hex(32),
                "limiter": False,
                "public_instance": False,
            },
            "search": {"formats": ["json", "html"]},
            "outgoing": {"request_timeout": 10.0, "max_request_timeout": 15.0},
        }
        if args.environment_proxy_fixture:
            settings["outgoing"].update(
                {
                    "verify": ssl.get_default_verify_paths().cafile,
                    "proxies": {"all://": [os.environ["HTTPS_PROXY"]]},
                }
            )
        path = root / "settings.yml"
        path.write_text(json.dumps(settings))
        path.chmod(0o600)
        env = {
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "LANG", "SSL_CERT_FILE", "SSL_CERT_DIR", "TMPDIR"}
        }
        env["SEARXNG_SETTINGS_PATH"] = str(path)
        log = (root / "process.log").open("w+")
        child = subprocess.Popen(
            [str(args.python.absolute()), "-m", "searx.webapp"],
            cwd=args.source.resolve(),
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            with httpx.Client(trust_env=False, timeout=2) as client:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise RuntimeError("SearXNG startup exited")
                    try:
                        if client.get("http://127.0.0.1:18888/healthz").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("SearXNG startup timeout")
            result = asyncio.run(
                LocalSearch("http://127.0.0.1:18888").search(
                    "llama.cpp server github documentation"
                )
            )
            report.update(
                search=result, actual_self_hosted_search=True, success=bool(result["results"])
            )
            if args.research_inputs:
                if not args.research_output:
                    parser.error("--research-output is required for integrated research")
                subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).with_name("live_research.py")),
                        "--inputs",
                        str(args.research_inputs),
                        "--output",
                        str(args.research_output),
                        "--model-asset",
                        args.model_asset,
                        "--search-origin",
                        "http://127.0.0.1:18888",
                    ],
                    check=True,
                )
                report["integrated_research_passed"] = True
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
            log.close()
            if child.returncode not in (0, -15):
                import re

                print(
                    re.sub(
                        r"https?://\S+",
                        "[url redacted]",
                        (root / "process.log").read_text()[-3000:],
                    )
                )
            report["finished_at"] = utcnow()
            args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "success": report["success"],
                "results": len(result["results"]),
                "engine_failures": result["engine_failures"],
            }
        )
    )


if __name__ == "__main__":
    main()
