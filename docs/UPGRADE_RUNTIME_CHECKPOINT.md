# Upgrade and runtime diagnosis checkpoint

Item 5 is in progress. This is not final installer or upgrade acceptance.

The first slice adds bounded inference-attempt receipts for Work actions,
specification reviews, input/asset image reviews and Work research planning.
Schema 32 is additive; migration preserves prior group/source records and creates
the existing checked pre-upgrade backup. Receipts are independent of action steps,
so recording an empty reply cannot claim an action ran or alter prior evidence.

Each attempt freezes the selected runtime, hashed model references, configured
digest pin, context/output limits, reasoning setting, task revision and next step.
No endpoint, filename, prompt, generated content or reasoning text is retained.
Context accounting distinguishes runtime tokenization from an upper estimate.
Allowlisted runtime counters keep their original units; visible UTF-8 byte counts,
first-visible-text latency and wall duration are independent measurements.
The configured digest is not an observed runtime measurement. Unknown metrics
remain absent. A completed stream does not establish valid JSON or tool success.

Empty/output-limited responses, runtime/consumer errors and cancellation retain
observed counts. The start, context, metrics and terminal states are durable;
partial byte counters checkpoint at most once per second. Abrupt exit therefore
retains a lower bound, not an invented final duration or token count. Backend
startup marks unfinished receipts interrupted before existing Work recovery.
At most 200 receipts are retained globally, and diagnostics exposes the latest 50
under its existing permission and reviewed-export controls. Existing inference
requests, grammar, model decisions, output limits and retry behavior are unchanged.

Focused protocol, cancellation, separate-process abrupt-exit recovery, privacy,
retention and v31 upgrade checks are distinct from actual-model acceptance.
Item 1 remains accepted and is not rerun. Native Windows verification of this
slice is required before integration. Real old-to-candidate EXE/APK upgrades,
Android signing/data continuity and reconnect acceptance remain outstanding.

The prior delivered baseline binaries have been recovered privately and matched
against their original delivery manifest. The recovered original Android key's
certificate matches the public signing policy and the prior APK certificate.
This is preparation only; no installation or signing-continuity acceptance has
been claimed. Private backups/keys are excluded from source and public artifacts.

Focused native Windows run `43296765243` on `a38dc68` passed all 37 checks,
zero failures/errors/skips, in 27.259 seconds. The original 1,057-byte JUnit ZIP
has SHA-256 `535a19a5e655ae06e22b9d932d945feedee4c43efe9d7d95a6ee25e661e65656`.
This checks runtime protocol faults and installed-platform process behavior;
it is not a real-model or old-installer upgrade result.

`check_application_upgrade.py` prepares a separate old-to-candidate Windows
boundary check. It pins the prior delivered EXE hash, requires fresh disposable
runner paths, invokes each installed bundled Python with isolated imports,
checks payload provenance, seeds inert old-schema records, and checks exact
original values, migration backup, Credential Manager and paired-token reconnect
across candidate installation and backend restart. Private receipts are outside
public reports. No dependency/model setup is invoked. Three local driver guards
check altered rows, stale provenance/payloads and non-runner denial. Actual
execution with both installers is still pending; this driver does not prove
native UI, model-file preservation, Android or physical Tailscale behavior.

A separate offline-signing route keeps the original key outside GitHub. The
bounded `sign_apk_v2.py` utility uses existing cryptographic primitives, verifies
input/certificate pins and key agreement, refuses existing signatures/ambiguous
ZIPs, preserves entry bytes and emits a v2 envelope. It is limited to Android 7+
(the application minimum is Android 8). No new local dependencies or production
key were used for its test. Official Android format reference:
https://source.android.com/docs/security/features/apksigning/v2

Independent SDK run `43298591745` on `1f26082` passed all seven checks with zero
failures/errors/skips in 4.791 seconds. Android SDK 35.0.0 `apksigner` accepted
the synthetic signature and rejected changed payload bytes. The original
552-byte report ZIP has SHA-256
`1ea9775bd80876cce777796d7a5b22060d586dfbc143bf230f5a880c0f6c0573`.
This does not establish production certificate continuity, application validity,
or installed upgrade behavior. Those gates still require the actual candidate
APK, the original private key, independent SDK verification and emulator update
without uninstall/data reset. No repository signing secrets are required by the
offline format test; no signing material is included in source or artifacts.

The exact Android 0.10.0 unsigned candidate from run `43301766498` was hash-
checked and signed privately with the existing original key. No key was exported
or transferred to GitHub. Independent SDK verification of those exact APK bytes
is still pending. A bounded confidential transfer driver prepares a fresh RSA
receiver key on one disposable public runner, binds AES-GCM ciphertext to its
verified run/source challenge, and accepts only two fixed APK hashes. Only the
public challenge and encrypted APK bytes cross public storage; signing keys,
backups and credentials are excluded. Receiver secrets and plaintext copies are
deleted on exit. The protocol's three synthetic checks pass locally; this is
not APK, installed upgrade, AndroidKeyStore or reconnect acceptance.

The independent exact-APK receiver run `43317969336` on `ea97b6f` passed
tracked-source scanning and generated its one-run public challenge. Binary
transfer did not occur; exact APK signature/install checks remain unexecuted.
The receiver has a bounded input wait and always deletes its temporary key.
Do not retry that input route without resolving transfer authorization.

The Windows upgrade driver additionally pins the candidate installer digest,
seeds original Work source text through the old application API and compares
its stored rows, and checks paired role/scopes as well as identity before and
after restart. Four local driver guards pass (0.02 seconds). This remains
unexecuted installed acceptance, not a replacement for actual old-to-new tests.

Independent exact-APK verification passed in run `43326864291` on `dad8a8c`.
Both production APKs passed SDK verification with the original certificate and
application ID; version code increased from 23 to 24. Receiver cleanup passed.
The 702-byte original report archive has SHA-256
`cc904cc61f1dc67703124b34e01f5d3dd3d1e0c764bbaf4a0896c621482d339f`.
This establishes signature continuity, not installed data/reconnect acceptance.

The isolated `check_android_upgrade.py` driver targets the exact verified pair
without rebuilding either APK. A fresh API28 emulator uses test-only system
trust and DNS for a controlled HTTPS fixture. The production automatic-pairing
activity saves the initial credential through AndroidKeyStore. `adb install -r`
must retain the UID and encrypted preference bytes. Subsequent automatic setup
uses deliberately invalid pairing codes: only authenticated reuse can succeed.
Two cold starts and a temporary HTTP503 outage/recovery must preserve the same
credential; the fixture rejects any second pairing. The harness's three focused
negative-control checks pass, including a real local TLS server test. Emulator
execution is still required. These are not real backend/Tailscale or physical
Pixel tests. Keys generated here are disposable TLS fixture keys, never app
signing material. Reports contain no fixture token, saved ciphertext or key.
