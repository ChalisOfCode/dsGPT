# Client acceptance scope

Routine CI checks backend behavior, browser UI, Android unit tests and emulator
lifecycle, and the native Windows client on a disposable GitHub runner. Installer
acceptance uses a disposable Windows user with separate test data and exercises
install, launch, restart, reinstall and uninstall without deleting user data.

Required evidence includes exact source/artifact hashes and observed outcomes.
Actual-model inference, compiler success, independent app behavior, native controls
and physical-device behavior are distinct results. Fixture responses do not prove
model reasoning; an emulator does not prove behavior on an owner's phone.

The remaining five-item upgrade is tracked in `docs/UPGRADE_COMPLETION_PLAN.md`.
No physical phone, owner PC heartbeat, Tailscale configuration or GPU benchmark is
a prerequisite for routine CI or packaging. Targeted hardware tests remain optional
and unverified until observed. A production update must preserve the signing key.
