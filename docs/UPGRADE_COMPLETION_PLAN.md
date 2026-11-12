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

## 2. Signed-in website and account workflows — focused acceptance passed

The implemented supported scope is explicit owner sign-in and same-origin form
interaction, encrypted saved browser profiles, and task/device-scoped plain-text
reads. Account data stays outside model context, research, task persistence and
ordinary diagnostics. No everyday browser profile is imported.

- The local authenticated owner enrolls a configured HTTPS origin/page, opens a
  five-minute isolated screenshot/input handoff, and explicitly saves or discards.
  Passwords/MFA bypass model tools and logs. Stale handoff generations cannot act
  on a replacement session. Remote and paired clients cannot control owner login.
- Real Chromium runs in an owned, validated networkless Docker container. The
  bounded host broker checks the exact HTTPS origin, public DNS and TLS hostname.
  Guest controls use private pipes, with no debugging port or arbitrary evaluation.
- Clean shutdown captures selected cookie/localStorage/IndexedDB files. Current-user
  Windows DPAPI protects the snapshot with owner/session/origin/revision binding.
  Failed protection, tampering, abrupt shutdown or stale replacement fails closed.
- Each supported form requires a fresh observed page and a one-use owner decision.
  Durable opaque receipts precede network dispatch. A lost response blocks retries
  until a fresh owner observation verifies remote state; old action IDs never replay.
- Saved-profile read grants bind exact task revision, device, page, profile revision
  and expiry. Delegated reads permit one GET and bounded plain text only; redirects,
  HTML, cookie rotation and known reflected credentials are rejected. Revocation
  cancels active work and suppresses late text. Desktop and Android views keep text
  ephemeral and clear it on lifecycle, task, connection and permission changes.

### Recorded acceptance boundaries

| Boundary | Verified evidence |
| --- | --- |
| Android account presentation and transport | `43266192022` / `30ef476`: app/test Kotlin compiled; all 10 focused checks passed, zero skips/errors/failures; Gradle 2m22s. |
| Production Docker guest and broker | `43269409156` / `6341616`: exact production recipe, unchanged DockerSandbox and guest; two checks passed in 8.94s. Controlled TLS login/MFA, cookie/localStorage/IndexedDB restore, lost-write duplicate denial, real public DNS/TLS through the guest, revocation and owned cleanup. |
| Owner controller with real browser | `43270310226` / `72fa47b`: two checks passed in 6.18s. Actual input/review/decision/save, backend-service restart, scoped read, expiry, cross-task/device denial and revoke. Uses explicit container, endpoint and protection fixtures. |
| Native Windows protection | `43270956531` / `452085b`: native DPAPI plus owner API grants, separate-process restoration, stale profile-revision denial, durable uncertain receipts, tamper rejection and revoke cascades; one check passed in 1.78s, zero skips/errors/failures. |
| Desktop/native and regression baseline | Main `4b87ed1`, CI `42974018414`, passed all nine jobs; desktop 29 and private browser 43 checks passed. The installed Windows application checks use a separate inference fixture and do not complete item 5. |

These boundaries are separate observations, not one end-to-end physical-device
run. Controlled login uses a test-only loopback TLS mapping and test protection on
Linux. The additional public transport case has no endpoint/resolver/trust override.
Neither alters production network or credential protections. Windows protection is
validated natively; physical owner hardware remains unverified.

Compatibility is deliberately bounded: one configured origin, supported top-level
form-encoded submissions, and explicitly approved plain-text task pages. Complex
federation, passkeys, anti-automation gates, arbitrary site APIs and universal logout
are not promised. Revoking dsGPT access does not undo an already-sent request or
log out a remote website. Previously viewed content cannot be recalled remotely.

The reconciled main candidate `89803c2` passed all nine integration jobs in
`43271693885`. The single terminal item-2 alert was delivered by run `43273894623`
in issue 1. Item 3 implementation has started; final installers remain gated on
items 3–5. All preserved report hashes are recorded in the validation log.

## 3. Document layout and spreadsheet formula validation — focused acceptance passed

Render generated documents independently, inspect page images and structural
problems, and recalculate supported workbook formulas with a real engine. Preserve
original files, report unsupported formulas/formatting, and verify exported results.

The candidate adds bounded typed render, recalculation and page-extraction tools.
Run `43278654806` on `b83c47f` passed actual production LibreOffice/Poppler checks
(3 in 12.66 seconds), desktop build/Chrome presentation and Android compilation/
Compose presentation. All six DOCX/PDF/PPTX page images were inspected individually:
normal document content/page breaks preserved; deliberate slide clipping observed
and reported. Actual exported workbook formulas/caches match independent expected
values; intentional formula errors and a rewrite remain explicit failures.
Original preservation, malformed/encrypted/active input rejection, stale receipt
invalidation and interruption/cleanup failure are covered. See
`OFFICE_VALIDATION_CHECKPOINT.md` for exact hashes and observation boundaries.

Clients distinguish rendering, structural findings, page-review coverage and
calculation. Coverage is not a layout pass. Native text-only inference cannot review
images; vision remains required for automatic image inspection. Office/font fidelity
is not universal and workbook formatting preservation is not certified.
Integration into main is pending; no final installers are produced at this stage.

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


### Focused production HTTPS transport evidence

Run `42988030561` on isolated source `77dbd08` passed the unchanged production
account broker and PublicHTTPS transport against a hash-pinned public repository
file in 0.264 seconds. There was no substituted endpoint, resolver, TLS trust or
response and no credential was sent. This exercises actual public DNS pinning,
TLS hostname verification and bounded byte delivery on that route. It does not
replace authenticated production Docker or Android acceptance.
