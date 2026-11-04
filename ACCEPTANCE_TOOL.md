# Optional acceptance harness

This harness is for disposable CI environments or an explicitly targeted hardware
diagnostic session. It is not required for normal development, packaging or use of
an already configured app. Use separate test data; do not run installer/uninstaller
acceptance in an everyday Windows profile.

`python -m dsgpt_acceptance --kit <kit-directory> --ci --no-phone --output <results>`
runs the appropriate Windows fixture checks without a physical phone. The Android
acceptance app has its own application ID. Real-model checks, emulator checks and
physical-device checks are reported separately; skipped checks are never passes.

For an authorized hardware investigation, extract the complete kit and run its
wireless launcher normally. Windows permissions, reboot, Tailscale account login and
Android wireless-pairing approval must occur on their own trusted screens. Model
and SDK downloads can be large. The generated report is private until reviewed.
Never upload the whole diagnostic directory into a public repository or CI artifact.
