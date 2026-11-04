"""Exercise real automatic Ollama installation/download with the exact portable kit."""

import argparse
from pathlib import Path

from dsgpt_acceptance.__main__ import Runner, command, require


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.ci, args.no_phone = False, True
    runner = Runner(args)
    try:
        runner.check("Kit file integrity", runner.integrity)
        require(runner.report["checks"][-1]["status"] == "PASS", "Kit integrity failed")
        runner.check("Actual Windows Ollama setup", runner.discover_models)
        require(runner.report["checks"][-1]["status"] == "PASS", "Automatic setup failed")

        def unattended():
            setup = runner.report["local_runtime_setup"]
            require(
                setup["strategy"] == "standalone_cli", "Fresh worker did not exercise CLI setup"
            )
            require(
                not setup["desktop_app_launched"] and not setup["account_required"],
                "Setup must not launch desktop onboarding",
            )
            result = command(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "@(Get-Process -Name 'OllamaSetup','ollama app' "
                    "-ErrorAction SilentlyContinue).Count",
                ]
            )
            require(
                result.returncode == 0 and result.stdout.strip() == b"0",
                "An Ollama installer or desktop app was launched",
            )
            # A second run must reuse the verified download/extraction without a wizard.
            require(runner.install_ollama_runtime(), "Verified runtime reuse failed")
            return {
                "standalone_cli": True,
                "no_installer_or_desktop_process": True,
                "no_account_required": True,
                "verified_cache_reused": True,
            }

        runner.check("Unattended engine with no desktop onboarding", unattended)
        require(runner.report["checks"][-1]["status"] == "PASS", "Setup was not unattended")

        def inference():
            # Use dsGPT's actual request path. A direct Ollama call with think=False
            # previously passed while hiding the missing control in LocalInference.
            runner.models[0]["output_tokens"] = 64
            runner.start_backend()
            _, _, run = runner.submit(runner.models[0]["id"], "Reply with OK only.")
            reply = runner.wait_run(run, 180)
            evidence = runner.run_evidence(reply)
            require(reply["status"] == "completed", "Local inference through dsGPT failed")
            require(
                evidence["metrics"].get("thinking_chunks") == 0,
                "Reasoning consumed the answer budget despite the explicit off control",
            )
            require(
                "output_limit" not in evidence["warnings"], "Short reply used its entire budget"
            )
            return {
                "local_cpu_inference": True,
                "completed_through_dsgpt": True,
                "output_token_limit": 64,
                "run": evidence,
                "gpu_acceptance": False,
            }

        runner.check("Actual Windows local model inference", inference)
        require(runner.report["checks"][-1]["status"] == "PASS", "Local model did not run")
    finally:
        # Avoid opening a browser on the build worker; remove any setup RunOnce explicitly.
        from dsgpt_acceptance.setup import resume_after_reboot

        resume_after_reboot(runner.kit, False)
        runner.args.ci = True
        runner.finish()


if __name__ == "__main__":
    main()
