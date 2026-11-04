# Using dsGPT

Install an approved `dsGPT-Setup.exe` normally. Existing conversations, settings,
models and device credentials are kept outside the application directory. Updates
must retain them. Windows releases are unsigned unless their release notes explicitly
identify a verified publisher signature. A test installer is not a released upgrade.

The app discovers compatible local runtimes and installs the reviewed free tools it
needs. Ollama runs the local model; Docker provides isolated tools for Work. Ollama
does not require an account or its desktop onboarding. Windows may require consent
for a prerequisite or a reboot; save work and restart only when requested. Docker
sign-in can be skipped when its installer permits local use without an account.

The phone app connects to the desktop backend over authenticated HTTPS/Tailscale.
Normal Chat and Work do not require USB or wireless debugging. Wireless debugging
allows optional automatic APK installation/update and targeted diagnostics. Turning
it off removes those ADB capabilities, not an already paired app's normal connection.

Use only a production APK whose release report confirms the previous signing
certificate. Do not uninstall the existing app to solve a signing mismatch. The
separate acceptance app is for disposable testing and cannot replace dsGPT Mobile.

Chat and Work offer the same familiar composer. Work adds task status, source files,
tool results and completed downloads. Model effort choices depend on the model's
actual support. Web search gathers source evidence; sources can be incomplete, and
a local model may need multiple tool steps to answer. Read the capability report
for verified behavior and remaining limits; a saved task is not a completed build.
