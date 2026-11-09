# Remaining dsGPT upgrade completion

The owner requested these five items in order, with no next upgraded ZIP delivered
until all five are complete. Latest delivered release: 0.9.2. This is an active
engineering checkpoint, not a release or a claim of universal model reliability.

## 1. Media evidence and bounded APK/EXE smoke — passed

The owner reduced release testing on 2026-11-09. The multi-hour original
Task Ledger scenario remains historical evidence and is no longer a release
gate. Do not dispatch another long run.

- Reuse the verified actual-model short and multi-window media evidence from
  run 41891667443; repeat only a focused affected check if media code changes.
- Start with fresh standard Android and Windows scaffolds. Use the pinned
  actual 9B model for two short edit responses: change a visible label in each
  app, then revise it. The combined inference cap is six minutes. No retries
  within a run, mocked answers or generated fixture implementations.
- Compile the resulting source through the production Docker build path.
  Independently install/launch both exact APK and EXE revisions on disposable
  runners and observe each label. Match artifact hashes and check Android
  signing continuity for the smoke project.
- This samples local model edits, compilation and native launch. It does not
  establish autonomous long-task completion, complex Task Ledger behavior,
  production update continuity or arbitrary app reliability. The separate
  production upgrade and reconnect checks remain item 5.

The bounded acceptance passed on commit `0a995a8` in run `42637730273`.
Both revisions were independently built and launched on Windows and Android.
Actual model inference totaled 106.684 seconds. This is smoke-test evidence,
not the final dsGPT installers or physical-device validation.

## 2. Signed-in website and account workflows — in progress

Implement explicit session setup, scoped permissions and durable account access
without exposing credentials to the model. Validate read and allowed interaction
flows, session persistence, revocation and observable failures. Account access,
CAPTCHA/MFA and external writes require the owner's applicable authorization.

The first backend slice is separate from public research and the model. A
local desktop owner can provision, list, read, and revoke an explicitly
scoped session. One opaque session cookie is encrypted under Windows DPAPI
and bound to the owner, session, origin and exact read path. The broker
sends only a bounded GET to that path over public HTTPS, never follows
redirects, and returns plain text to an explicitly authorized caller. No cookie, page
content or headers are retained in Work, diagnostics or model context.
Local revocation does not sign the user out of the remote website.

The local owner can now issue and revoke read grants bound to an exact task
revision and active device. Grants expire after at most one hour and survive
backend restart. Every read checks current authorization before the request
and before releasing text. Revocation no longer waits for network I/O; an
in-flight response is discarded after revocation, expiry or task modification.
Already-sent network requests cannot be undone. Account reads are serialized
and overlapping requests are rejected, with the existing 12-second network cap.
These are explicit API permissions, not automatic model access or write approval.

Settings now provides owner-facing account and grant revocation, task/device
selection, explicit read consent and refreshed permission review after uncertain
mutation responses. Browser sign-in remains unavailable; this interface never
asks for pasted credentials. UI fixture coverage is separate from real sign-in.

The private browser network component now validates one public HTTPS origin,
preserves browser cookie headers and security policy, and bounds requests and
responses. It accepts form POSTs only with fresh, single-use approval for the
exact destination and body. It does not follow redirects or retry submissions.
This component is not exposed to the application yet: the isolated browser,
owner handoff and encrypted profile still need integration. Form dispatch now
requires a durable receipt committed before network I/O. An interrupted request
remains uncertain after restart; even a received HTTP response requires remote
state verification before another form submission in that session. Receipt IDs
cannot be replayed within the session. These internal receipts store only opaque
identifiers, status and timestamps, never URLs, request hashes, credentials or
response content. Owner verification controls and page/task binding still need
integration; this is not yet an end-to-end recovery workflow. Focused transport
and storage tests do not count as browser acceptance.

A separate internal profile vault now protects bounded regular-file snapshots with
current-user Windows DPAPI. Session/owner/origin/revision binding and atomic
revision checks prevent cross-session restoration and stale overwrites. Migration
29 stores only the encrypted envelope. A dedicated guest worker now restores
selected profile files into a fresh directory and captures them only after
Chromium acknowledges shutdown and exits cleanly. The worker uses private OS
pipes for Chromium control and requires a loopback-only Linux namespace in
production. A real Chromium fixture restored a persistent HttpOnly cookie,
local storage and IndexedDB across a vault round trip. That fixture uses an
injected test protector and intercepted synthetic responses. An internal bridge
now connects the guest to a dedicated validated Docker sandbox, the host request
broker and the vault, using bounded private pipes. It exposes only navigation,
screenshots and a small input allowlist, never raw CDP or evaluation. The bridge
rechecks live origin and owner authority, requires logging disabled, and saves
only after clean browser and guest exits. It currently denies all POSTs, including
broker approvals made outside the controller. Real Chromium tests exercise the
actual guest/host pipe, cookie forwarding, profile restart, request denial and
interrupted cleanup using a synthetic transport and explicit container fixture.
Production Docker/HTTPS, owner controls, task access and page-bound write approval
still require acceptance. Startup and active exchanges are now cancelled and
joined before abort cleanup completes. Aborted bridge instances cannot restart;
concurrent close is rejected without terminating an already active operation.

Remaining for item 2: owner-facing browser login/MFA handoff,
user-approved writes with interrupted-write recovery, task tool integration and
controlled browser acceptance. The backend slices are not a complete signed-in workflow.

## 3. Document layout and spreadsheet formula validation — queued after 2

Render generated documents independently, inspect page images and structural
problems, and recalculate supported workbook formulas with a real engine. Preserve
original files, report unsupported formulas/formatting, and verify exported results.

## 4. Group related imported projects — queued after 3

Recognize and propose coherent projects from related imports using observable
metadata/content, preserving originals and letting the owner correct associations.
Validate duplicates, unrelated inputs and conflicting project identities.

## 5. Software upgrade/reconnect and empty-response diagnosis — queued after 4

Automate runtime metrics and failure diagnosis, tool readiness, data/credential
preservation through software upgrades, and paired-device reconnect regression
checks. Run normal installation/reinstallation tests on disposable Windows and
Android emulator environments. Do not require a local worker, PC heartbeat,
Tailscale setup, GPU benchmark or physical Pixel for development or packaging.

Physical PC/Pixel/GPU behavior requires actual observations before making those
claims, but those targeted tests are optional and not a routine release gate.
Record hardware behavior as unverified when not observed. The 2026-11-03 public
build authorization supersedes the former mandatory physical-device handoff.
Signing identity and data-preservation acceptance remain required.
