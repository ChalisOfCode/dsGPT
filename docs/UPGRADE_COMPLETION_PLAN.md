# Remaining dsGPT upgrade completion

The owner requested these five items in order, with no next upgraded ZIP delivered
until all five are complete. Latest delivered release: 0.9.2. This is an active
engineering checkpoint, not a release or a claim of universal model reliability.

## 1. Media evidence and bounded APK/EXE smoke — in progress

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

## 2. Signed-in website and account workflows — queued after 1

Implement explicit session setup, scoped permissions and durable account access
without exposing credentials to the model. Validate read and allowed interaction
flows, session persistence, revocation and observable failures. Account access,
CAPTCHA/MFA and external writes require the owner's applicable authorization.

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
