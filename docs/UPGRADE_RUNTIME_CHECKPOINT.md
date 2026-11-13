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

The owner subsequently authorized only the encrypted original/candidate APK pair
on an isolated public branch, including ciphertext history retention. Keys,
backups, credentials and plaintext binaries remain excluded. The multipart
receiver on `dad8a8c` completed run `43326864291`: independent Android SDK
verification passed for both exact APKs, the pinned original certificate and
production identity matched, and version 23 increased to 24. The temporary
receiver key and plaintext copies were destroyed successfully. Original signature
receipts: 702 bytes, SHA-256
`cc904cc61f1dc67703124b34e01f5d3dd3d1e0c764bbaf4a0896c621482d339f`.
This establishes SDK signature continuity, not installed upgrade acceptance.

The next driver uses those unchanged APKs on a disposable API-28 emulator.
It installs a temporary fixture CA and synthetic hostname in the emulator's
system image; APK trust policies remain unchanged. The old app pairs with the
actual backend over TLS. The driver observes the app's encrypted preferences,
updates with `adb install -r` without uninstall/data injection, and checks UID,
AndroidKeyStore-backed authenticated reconnect, same device/scopes/token,
visible prior chat, offline credential preservation and fresh-backend reconnect.
Private observations never become public reports. Only fixed outcome fields are
retained. The controlled CA/hostname is not physical Tailscale evidence.
Two local driver guard/TLS fixture checks pass; installed checks remain pending.

Installed run `43328679346` on `4bcc913` passed input verification, emulator
preparation, prior-release pairing, real `adb install -r`, unchanged UID/encrypted
preferences, candidate authenticated reuse and native history visibility, and
offline credential preservation. It then failed within the combined fresh-backend
restart stage. Cleanup succeeded. Original 217-byte report SHA-256:
`48d43e457cd5f73b693ad39a5dfa3f6fbf0d505be77834fd40c50f5a6884801b`.
No complete upgrade pass is claimed. A local actual-TLS/backend restart check
preserves paired authority and task/chat data; it does not reproduce the installed
failure. The next bounded diagnostic run separates restart identity, token,
scopes, vault, data, native history and shutdown checks without changing assertions
or either APK. It reports only fixed stage/type labels, never exception content.

The Windows upgrade driver additionally pins the candidate installer digest,
seeds original Work source text through the old application API and compares
its stored rows, and checks paired role/scopes as well as identity before and
after restart. Four local driver guards pass (0.02 seconds). This remains
unexecuted installed acceptance, not a replacement for actual old-to-new tests.

The pending Windows driver now also opens both installed native clients and
requires the prior conversation title in each real window. Its isolated native
credential is seeded only before the old install observation and must survive
the candidate phase without repair. An inert file in the model directory is
hash/size checked across the update; this tests byte preservation, not a usable
model or new inference. Five local driver guards pass in 0.02 seconds. Actual
Windows installed upgrade execution is still pending.

The pending Windows/backend package metadata is aligned to 0.10.0, including
the native/web package locks and Windows uninstall registry version. Dependency
versions are unchanged. The already built Android 0.10.0 APK remains byte-for-byte
unchanged. This metadata preparation is not a new build, installation or release.


Android retry 43330237220 on 12afe58 passed the separate restarted backend
identity, token, scopes, encrypted vault, original chat/Work/message and native
history assertions, then failed at backend_restart_shutdown (RuntimeError).
The fixed receipt is privately preserved: 239 bytes, SHA256
fd83e7019263079cc1b69cdf44b7315579a53abd2bac7d7f2b75e7bfedb80498.
Fixture Uvicorn previously had no graceful-shutdown deadline. It now cancels
in-flight requests after two seconds, while still requiring the server thread
to exit. An actual TLS held-request test confirms cancellation, reader and server
exit, and rebinding the same listener with retained owner authority. Three local
driver tests pass; this is not a substitute for the pending installed retry.
The same already SDK-verified APK pair is retained without rebuilding/signing.


Installed Android acceptance 43332013571 on cd1f3bdfcc48df268d6a29fa2e6edabaf122a2d5
passed, including disposal of the receiver key, decrypted APKs and emulator data.
Exact production APKs, unchanged from standalone SDK verification 43326864291,
passed install-r version 23 to 24, unchanged UID/encrypted preferences, successful
AndroidKeyStore decryption through authenticated API access, paired identity/token/
scopes, prior native chat history, original backend data, offline credential
preservation and fresh-backend reconnect. The test uses an isolated API-28 emulator
and controlled system CA/hostname; physical Tailscale and owner hardware remain
unverified. No model/Gradle build or re-signing was repeated.
Original bounded report ZIP: 519 bytes, SHA256
cc6e48d31be0091629e91c8c9fadf41aae1e9c1b87c8dc2a37902b20c443fce4.
Item 5 remains open for actual Windows old-to-new installation and final source/
packaging integration. No final installers or terminal item-5 alert are released.

The owner authorized the encrypted prior Windows installer transfer after the
Android pass. The isolated Windows workflow builds the backend/native client
once, receives only the hash-pinned prior EXE and already verified candidate APK,
and assembles a fresh pinned runtime. It uses the unchanged production packager
and original Android signature receipt. The old-to-new test checks installed
provenance, original rows/imports, native prior-chat visibility, credentials,
paired identity/scopes, migration backup and inert model-directory bytes.
The candidate installer is retained with source/hash provenance even if upgrade
acceptance fails, avoiding unnecessary rebuilds. This is not a final release.
The confidential transport uses a separate Windows cryptographic domain and
branch prefix, with 100 MiB envelope limit and the existing 384 KiB parts.
Ten focused local transport/driver checks pass. Native execution remains pending.


Windows source e7e4408 run 43384210506 compiled the backend/web/native client
successfully, then the ten-minute encrypted input window expired. The actual
installer build/upgrade did not run; cleanup succeeded. No compiled output was
retained by that revision. The next workflow preserves hash-bound wheel, native
client and frontend outputs before opening the receiver, under the unchanged
one-day/300MiB repository guard. These are build inputs, not accepted installers.
Bounded failure evidence: 764 bytes, SHA256
555c6e49b1813efb52ad32f6581cc0c93f77ad5a7f0bff7d4e6cbf1cb5a51718.


Windows run `43396872188` on `6ae57f4` successfully received the authorized
hash-pinned inputs, compiled once and built the production 0.10.0 installer.
Installed acceptance failed in the old-release baseline phase with AssertionError;
the candidate upgrade phase did not run. Cleanup succeeded. The next bounded
check reports only fixed driver function/line and exception type, never values,
locals or raw traceback. It reuses the exact retained installer without compilation
or packaging and keeps every acceptance assertion unchanged.

Original candidate artifact: 60,583,629 bytes, SHA256
`3a279c418088d5a871d5110b49c375af2ec25ca89a2d275675169065521979a6`.
Contained EXE: 60,431,157 bytes, SHA256
`a6f20d1b517120b962b1c023bed47eab523d72dbc09cbc1d432941d35ad18331`.
Compiled-input original artifact: 5,676,718 bytes, SHA256
`7b35d0ac1bf9209f02f932b3939c911c19dbdb273fb460f95f1ca565d4bdec09`.
All source manifests/file hashes and ZIP integrity were checked; both archives
are privately preserved. Original failure report: 206 bytes, SHA256
`afc9523fac0d0dc85c5c8c134047817b4b243906475996f0c37a545028dc0c68`.
Six focused driver/privacy guards pass locally (0.03 seconds). This is not
installed acceptance, item-5 completion or final delivery. Main is unchanged.
