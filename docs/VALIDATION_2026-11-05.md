# Validation checkpoint, 2026-11-05 UTC

Item 1 is incomplete; items 2–5 remain queued. No release is authorized by this
checkpoint.

- Actual 9B run 41949242982 tested 4b476e0718d90554e1ce91593d06823f8d1e8e62.
  It ended at step 37 with no_progress. The initial app task did not complete;
  generated APK/EXE native checks were skipped. Restart preservation passed.
- Evidence ZIP SHA-256:
  9b6116583f0128b10aa6354ae1ef145f11c5d3a8e82f957b5b7fc44920fd9ee9.
  The original ZIP is preserved separately, not published in source history.
- The last source reads covered overlapping parts of a 3096-character file.
  Prompt assembly clipped source pages even when they fit and omitted the prior
  page of the same file. This checkpoint retains a full observed page when it
  fits, keeps the prior current page, and recognizes complete contiguous coverage
  only when its hash equals the current source. Gaps, stale hashes and conflicting
  overlaps do not suppress reads. Model actions and acceptance criteria are unchanged.
- Routine run 41953848304 on 605bc6dbd1eedc593faadb4e970a868c16114909 passed
  backend, frontend, browser and source audit. Android and Windows native builds
  reached their artifact guards and failed there; downstream installation and
  emulator checks did not run.
- Public artifact inventory (all 100 entries, second page empty) totals 304202442
  unexpired bytes. The existing 300 MiB guard is unchanged. Earliest listed expiry
  is 2026-11-05T18:05:37Z. No artifacts were deleted and no budget was raised.
  Do not blindly retry storage-blocked CI: verify available headroom first.
- This source change is published with push CI skipped to avoid another known
  storage failure. After retention frees sufficient capacity, manually dispatch
  routine CI and a fresh original-request complex-model test on the exact new SHA.
  Neither live test has passed this change yet. Do not rerun an older failed
  workflow expecting it to include the new source.
- Owner hardware and production APK signing/upgrade behavior remain unverified.

Local checks: 183 focused Work/project tests passed. The first broader run passed
1083 tests and 6 subtests, failing only the process-kill fixture: the parent observed
file creation and killed the child before its write finished. The fixture now waits
for the complete effect before killing the child; durable interruption/no replay
assertions remain unchanged. This is a fixture synchronization repair, not a
production crash-recovery success claim. Changed files received manual diff review
and the tracked snapshot passed the pinned Gitleaks scan.
The broader rerun passed 1084 tests plus 6 subtests before the fixture
synchronization edit was loaded; all 15 build tests passed after that edit.
Ruff and diff whitespace checks passed. Archive Actions disablement was reverified
in repository settings; no archive settings or contents were changed.

## Fresh run on 46b6cd9 and diagnostic recovery

- Run 42086380632 on 46b6cd928f08d54fecc5ac7533727dfddca54835 completed
  with failure. Runtime/toolchain setup and bounded evidence upload passed; the
  model stopped at step 30 with no_progress. Native follow-up checks were skipped.
  Restart preservation passed. This is not a completed complex-app acceptance.
- Original evidence ZIP SHA-256:
  bd92625e02fa1e6cce8c7bcc6abf9e9c123495e353631600d5df753eae0f668e.
  The downloaded ZIP matched GitHub's artifact digest and was preserved separately
  before expiry. No source archive, production signing material or owner diagnostics
  are added to this public checkpoint.
- The model attempted to execute a Gradle configuration file, later corrected its
  tool choice, then encountered an unresolved class in a test it had written.
  Subsequent reads of the test, activity and manifest repeated without implementing
  the class. Prompt inspection found that latest execution stderr/stdout retained
  only their tails after the build action left the two-step history. This lost the
  compiler's initial diagnostic while retaining a generic subprocess traceback.
- The recovery change keeps bounded UTF-8 head/tail excerpts with explicit full-log
  pointers and retains failed-execution guidance during source inspection. It marks
  diagnostics as current or old using the source snapshot hash. Successful completed
  tasks keep completion priority. No model actions, request text, fixture app code,
  no-progress limits or acceptance checks were replaced or weakened.
- Public inventory after the run: 50 artifacts, 82542681 unexpired bytes. The
  storage guard passed for this run. The earlier expiry was not a mandatory waiting
  period; redundant artifact copies can be considered after verified preservation.
  There is now room for the required routine CI and next fresh model run without
  changing budgets, storage limits, runner types, retention or cache policy.
- Local validation for this recovery: 108 focused tests passed; full suite passed
  1089 tests plus 6 subtests. The five diagnostic regressions also passed after the
  final conditional-guidance wording adjustment. Ruff, whitespace and static CI
  policy checks passed. Manual review covered all three changed files; pinned
  Gitleaks scanned the tracked working snapshot (about 3.67 MB) and found no leaks.
  This scan does not establish that the entire application is secure. A fresh
  actual-model pass is still required; regression fixtures do not prove it.

## Routine platform success and invalid-action feedback recovery

Routine CI 42102598215 passed all nine jobs on
8b65f1346b25bdf4e6e3e9e1dd83a23ad13ad4cc, including disposable Windows installer
acceptance and Android emulator lifecycle instrumentation. This does not verify
owner hardware or production Android signing continuity.

Fresh actual-model run 42102733380 failed at step 17 with invalid_action. The model
emitted the same incomplete JSON edit three times, with repeated import text, and
no rejected edit executed. The source-history query used a SQL comparison on the
missing tool field in invalid-output records; NULL excluded those records from the
next prompt. The correction includes these validation failures while continuing
to exclude specification-review records. It gives bounded repair guidance and
retains the three-failure stop. No malformed response is repaired or executed by
the controller, and acceptance requirements remain unchanged.

Original evidence ZIP SHA-256:
757cd929baf5dbb93c7040725bd2ac938b154879e37acfcba41751b025776e8c.
The digest matched GitHub; the original ZIP was saved separately before expiry.
The new regressions verify malformed JSON and unknown actions remain visible as
errors, raw rejected text stays out of prompts, source bytes stay unchanged, and
three invalid attempts still block. Focused recovery tests: 28 passed; Ruff clean.
Full regression suite: 1091 tests and 6 subtests passed. Manual review covered the
three changed files; the pinned tracked-source Gitleaks scan found no leaks in
about 3.68 MB. This is a limited source scan, not a security certification.
Public inventory before retry: 51 artifacts, 75221919 unexpired bytes. No jobs
were active and no artifacts, signing material or source history were deleted.

## Tight-context rejection feedback and controller retry checks

Routine CI 42114760303 passed all nine jobs on
f153f7006c6b076752c415ea50b959decf92ea42. The original Windows and Android
diagnostic artifact ZIPs were SHA-256 verified and saved together before expiry.
Combined evidence ZIP SHA-256:
43ec276332c5d56ee4bcbcfdf3dca4eec9ed01083b31177c85ab1106c8a74084.
Windows installation/reinstallation preserved credentials, chats and models;
Android lifecycle instrumentation passed. These are routine platform checks,
not production-signing, owner-hardware or actual 9B complex-app completion evidence.

A new controller-level regression exposed another feedback loss: if the separate
history messages could not fit the configured context, the fallback discarded
validation details and restored generic guidance to read source/build logs. An
invalid response has executed neither a source operation nor a build. The fallback
now retains the rejection guidance and up to three bounded validator fields in
the context. The complete rejected output stays in its original step record and
is not replayed to the model. Original requirements remain saved and pageable.

Four streamed-response controller cases cover 8192 and 16384 context settings,
both a valid subsequent edit and three rejected responses. They check the final
prompt budget, no mutation by rejected responses, actual application of the valid
edit and the unchanged three-failure stop. These use an explicit inference fixture;
they do not establish real-model recovery. All six rejection tests passed; the
full suite passed 1095 tests plus 6 subtests in 86.70 seconds. Ruff passed. Manual
review covers the three changed files; the pinned tracked-source Gitleaks scan
found no leaks in approximately 3.68 MB. This is not a security certification.

The fresh actual 9B run 42114834765 remains on f153f70 and is left undisturbed;
this follow-up change is not part of that run and cannot inherit its outcome.
Before publishing, public storage inventory was 61 artifacts, 91354358 unexpired
bytes; no duplicate model acceptance run or artifact deletion was initiated.

## Acceptance harness follow-up audit

Read-only progress logging now classifies the last persisted action and result,
and counts consecutive identical actions. It never logs prompt/source text,
paths, validator messages or model summaries. This does not modify model requests,
actions, the task database, budgets or acceptance decisions.

A regression reproduced a KeyError in the compiler-repair checker when a rejected
response appeared in follow-up history. Rejections lack an action tool field.
The checker now skips these non-executed entries while still requiring an actual
marker compiler failure followed by a successful build. Tests also reject histories
with only rejections or a missing failed/successful build. No app implementation or
model action was substituted.

The harness suite passed 41 focused cases, including log-data exclusion, nonzero
compiler exits and rejected-action repair history. The full suite before the final
two log-classifier cases passed 1099 tests plus 6 subtests in 93.56 seconds. Ruff and
whitespace checks passed. The four-file diff was manually reviewed and the pinned
tracked-source secret scanner found no leaks; this is a limited scan, not a proof
of general security. The f153f70 actual-model run remains unchanged and its result
must be assessed independently of these later harness changes.

## Candidate requirement navigation

The earlier 8b65f13 model evidence contains a Task data class with String IDs and
unrequested due-date fields, contrary to the later exact domain contract. This
was not a completed application or a failed independent domain-test result.
Inspection showed guided prompts include only the current section and a short
overview; the already-reviewed section notes were accessible only by an explicit
list_requirements call. Missing cross-section context is a recovery hypothesis,
not an established explanation of the model's reasoning.

The candidate adds a bounded page of section IDs and existing navigation notes
only when it fits after current source and error evidence. Notes are explicitly
non-authoritative; exact originals still require read_requirements. It preserves
all original bytes, coverage requirements and tool feedback, has next/previous
index offsets, and cannot cross task boundaries. When no index fits, the existing
prompt is returned unchanged. The live f153f70 run has not been altered.

Three navigation regressions passed. Full candidate suite: 1104 tests plus six
subtests passed in 112.00 seconds; Ruff and whitespace checks passed. Separately,
the complete published 893deb6 suite passed 1101 tests plus six subtests in
104.42 seconds. Candidate real-model behavior remains unverified. Keep this
candidate separate until the active run's outcome is reviewed; do not launch a
duplicate acceptance job to test it concurrently.

## Actual f153f70 outcome and retained-source recovery

Fresh original-request actual 9B run 42114834765 on
f153f7006c6b076752c415ea50b959decf92ea42 finished with failure. Initial step 16
stopped with no_progress after three reads of the unchanged MainActivity source.
Step 13 rejected an existing-file write, step 14 read that source, and step 15
rejected incomplete JSON without executing an edit. Step 16 then requested the
same source again. This run did not validate later runtime or harness changes.
Generated-app Windows/Android/native-join jobs were skipped, not passed.

Original evidence artifact 13459147047 was downloaded and its digest verified:
106470 bytes, SHA256
`00070f30dd72838a8d60efe8c578e2ab16ef32439a11cc92c5304928f8113452`.
It was preserved durably as `libfile_77637d3c33308191bac4acac0aaf351c`.
The model phase took 2858.445 seconds. No model action or app implementation was
replaced. No completed TaskLedger APK/EXE is claimed.

The controller retained the rejection but dropped the preceding source page, and
its recovery instruction told the model to read the intended file. The correction
keeps an observed, unchanged source page across consecutive rejected responses
when it fits alongside the validator feedback. Hash validation gates reuse. Only
complete visible bytes can suppress a redundant read in the action schema;
partial/stale/absent pages remain readable. An intervening non-rejection operation
stops this carry-forward. The unchanged repeated-failure limits still apply.

Five focused regressions cover current source, consecutive rejections, changed
bytes, partial pages and intervening operations. The combined recovery, source-read
and navigation suites passed 24 tests, including the existing 8192/16384-context
streamed-response checks. An initial longer instruction exceeded the tight-context
case; shortening it resolved that regression without dropping validator feedback.
These tests use explicit fixtures and do not prove actual 9B recovery.

The requirement-navigation candidate ee9d7bc is incorporated in the next retry:
its bounded navigation notes may help avoid inconsistent cross-section choices,
but exact requirements and completion evidence remain authoritative. Public
inventory before this retry was 72 artifacts totaling 107594178 unexpired bytes;
no storage cleanup or duplicate acceptance run was needed.

Final combined tree validation: 1109 tests plus 6 subtests passed in 97.10 seconds;
Ruff and whitespace checks passed. Manual publication review covered the three
changed files and the previously audited navigation candidate. The pinned
tracked-source Gitleaks scan reported no leaks in approximately 3.71 MB. This
limited scan does not certify the whole project secure. Current owner hardware
and actual-model recovery on this new tree remain unverified pending fresh runs.

## 5e3e396 routine CI and fresh acceptance checkpoint

Published runtime commit `5e3e39613e445e2005bc969fdb419755e21b69fe`
(tree `3d32c1b564fed47ed6d80ea2c2e58af05eb7aa83`) passed all nine routine CI jobs
in run 42123850503. Backend JUnit reports 1115 cases (1109 tests plus six subtests),
zero failures/errors/skips. Windows regressions report 138 cases with one skip,
zero failures/errors. Android instrumentation reports one passed lifecycle and
diagnostics case. Browser and Android unit-test reports were retained too.

The actual installed Windows-app receipt confirms native-window launch, Credential
Manager restoration, a local reply, scheduled backend restart and owner/chat/model
preservation through reinstall. Its qwen3:1.7b installation fixture is separate
from the actual 9B complex application acceptance and does not replace it. The
legacy inventory stage records a local-inference BLOCKED entry, while the dedicated
installed-app acceptance succeeded; production/physical usability remains REVIEW.
No owner PC/Pixel/GPU, Docker Linux or Tailscale behavior is claimed by this run.

Five original report ZIPs were digest-verified and preserved in
`dsGPT-ci-test-evidence-5e3e396.zip`, 43018 bytes, SHA256
`d95edfcac563ce3c3add58bcf76b83fb94d12e3efeb65ec455578dc8a9c34f3d`,
durable file `libfile_d1b3403d25388191828dd53d11a64a73`. The included manifest records
artifact IDs and original archive digests. These are test reports, not a release.

Fresh original-request actual 9B complex run 42123898744 is running on that exact
5e3e396 commit. The model loaded and began reviewing the original request. Native
TaskLedger completion and later items remain unverified until actual results exist.
The active run is not cancelled, duplicated or altered by these documentation notes.

## Actual 5e3e396 outcome and local-inference timeout recovery

Fresh original-request actual 9B complex run 42123898744 on
`5e3e39613e445e2005bc969fdb419755e21b69fe` failed before its first
implementation decision. The model reviewed all eight saved requirement sections,
created the Android scaffold at step 9, and survived the planned normal backend
restart with unchanged requirements and source hashes. The next structured action
never completed: dsGPT's local HTTP client disconnected after its fixed 180-second
read timeout while Ollama was still evaluating the 2,500-token prompt on four CPU
threads. Ollama recorded the POST ending with status 500 at exactly three minutes.
The task was then blocked as `runtime_unavailable`. No invalid model action or
repeated-read loop caused this run, and the generated-app Windows/Android jobs were
skipped rather than passed.

Original evidence artifact 13461467005 was downloaded and its digest verified:
94877 bytes, SHA256
`6faa77d7bc16004284e0ce0ad124f4b3ac221ab473e56844773562098095e632`.
It is preserved durably as `libfile_9b620c106d448191be284c5439f25af7`.
The report records 1113.406 seconds overall. The exact model, digest, 16384 context,
4096 output budget, original request, scaffold action and runtime logs are retained.
No model action or application implementation was substituted.

The correction increases only the loopback local-inference HTTP read timeout from
180 to a bounded 900 seconds, below Work's task timeout. Connect, write and pool
timeouts remain 10, 30 and 10 seconds. This permits slow CPU prompt evaluation to
emit its first stream byte without removing cancellation, task deadlines, context
checks or output limits. A regression asserts all four configured timeout bounds.
The focused inference and Work recovery suites passed 37 tests. Ruff and whitespace
checks passed. The pinned tracked-source Gitleaks scan found no leaks in about
3.71 MB; this limited scan is not a security certification.

Before the next run, public storage contained 67 unexpired artifacts totaling
94666388 bytes, and no workflow run was active. No artifact deletion was required.

Final combined-tree regression result: 1110 tests plus 6 subtests passed in
105.24 seconds. Manual publication review covered the two code/test changes and
new validation evidence. Owner hardware remains unverified, and actual 9B recovery
on this new timeout requires a fresh original-request run.
