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

## Actual 9c994ca outcome and acceptance-client timeout recovery

Fresh original-request actual 9B run 42131332005 on
`9c994cabafd35060b51f9db934242799c108c956` again reviewed all eight saved
requirement sections and created the Android scaffold at step 9. Its next action
call still stopped as `runtime_unavailable`. The new production 900-second read
timeout was present, but the acceptance-only CPU-control client independently
replaced it with its old hard-coded 180-second read timeout. Ollama processed the
2,484-token retry normally through 2,420 prompt tokens, then recorded status 500
at exactly three minutes when that client disconnected. No model action was
rejected and no repeated-read limit caused this failure. Generated-app Windows,
Android and native-join jobs were skipped rather than passed.

Original evidence artifact 13463789468 was downloaded and its digest verified:
95010 bytes, SHA256
`a85592013f39909cefc3ce1551ed59ce838b192429c7e45b3808ea6ff7bd73d7`.
It is preserved durably as `libfile_1ba3f4b20aec81919af38c47b80ebdf9`.
The routine CI evidence for this same commit is preserved as
`dsGPT-ci-test-evidence-9c994ca.zip`, 43250 bytes, SHA256
`099937c712bb143e5c8bcfdc620790d6e1c8f686552997c151ee10b4adb18a49`,
durable file `libfile_90e272fa71bc819183001f5ee963198c`. All nine routine
jobs passed, including disposable Windows installation and Android lifecycle.

The correction makes the acceptance client reuse the production
`LOCAL_INFERENCE_READ_TIMEOUT` constant while preserving its explicit CPU-thread,
memory-mapping and batch controls. Connect, write and pool bounds remain unchanged.
Regression coverage now checks both the generic local-inference client and the
actual measured acceptance client so a test-only override cannot silently restore
the obsolete three-minute limit. This change does not alter prompts, model actions,
context, output limits, task deadlines or acceptance criteria.

The focused inference, complex-harness and acceptance-oracle suites passed 65
tests. The complete tree passed 1111 tests plus 6 subtests in 89.75 seconds.
Ruff and whitespace checks passed. Manual publication review covered the three
changed files, and the pinned tracked-source Gitleaks scan reported no leaks in
approximately 3.71 MB. This limited scan is not a security certification. A fresh
original-request actual 9B run is still required on the corrected acceptance
client; neither this failed run nor the fixture regressions establish completion.

## Actual 951f8fb outcome: inventory/requirements loop

Original-request 9B run 42135202651 completed with failure on exact source
`951f8fba3d6b4243c7b5a24e6d34678319b45d10`. All eight requirement reviews and
Android scaffolding succeeded; inference continued past the former client timeout.
Steps 10–15 alternated requirement reads and unchanged inventory listings. The
third identical listing correctly stopped with `no_progress`; no generated-app
Windows/Android native jobs ran. This does not establish complex-app completion.

Original artifact 13467606070 is 102622 bytes, verified SHA256
`34c949428fc03b7c6cb13d163b423541befdf716c67b8b437ee31f971af407a8`,
preserved as `libfile_533d4ce7ea9081919c6580bf544de606`.
Routine CI 42135038622 passed all nine jobs, including disposable Windows
installation and Android lifecycle. Its report bundle is 42722 bytes, SHA256
`1b2210edff41f2fd4148bca0cf36a8c880b27ff22403b2e0d8091eaec0fd3a3a`,
preserved as `libfile_4021e1809e38819185267c766793873c`.

Source review found that clipped listings always suggested another listing but
could leave `next_offset` null, while listing results had no source-implementation
guidance. Requirement EOF guidance also explicitly suggested listing again.
The correction gives clipped inventory its actual continuation offset, omits
continuation advice at EOF, and directs existing-file inspection/implementation
after listings/scaffolds. It does not execute any model action, create feature
code, mark coverage or change no-progress thresholds. Three new regression cases
cover complete, clipped and final inventory pages. Owner hardware is unverified.

Validation of the inventory correction: 1114 tests plus 6 subtests passed in
90.95 seconds; Ruff, whitespace and CI-policy checks passed. The pinned Gitleaks
scan of the tracked candidate source found no leaks in approximately 3.72 MB.
Manual review covered the code, synthetic tests and validation notes. This limited
scan is not a security certification; actual-model acceptance of the correction
remains required.

## Actual c9e34a9 outcome: rejected overwrite recovery

Original-request actual 9B run 42143897057 on
`c9e34a991f87340520343247aea2e5f500a49650` failed at step 17 with
`no_progress`. The model reviewed the requirements, scaffolded Android, read
source and executed a targeted edit at step 12. That edit only changed a
placeholder string; its summary did not establish implemented behavior.
After reading the updated file, two attempts to overwrite that existing file
were correctly rejected as `existing_file_requires_targeted_edit`. Neither
replacement executed. The old recovery message explicitly requested another
read, while the prompt did not retain that source after this rejection. The
third identical read stopped the task. Generated Windows/Android native jobs
were skipped, not passed.

Original evidence artifact 13471976986 was digest-verified: 106361 bytes, SHA256
`1ea6f1c893154a896321d05209d890e863a16e7976147f731fdb39df949ae358`,
preserved as `libfile_623f89991fbc8191b61eabf7de8e37cf`.
Routine CI 42143897137 on the same commit passed all nine jobs. Its five report
archives (Windows installed-app, Android runtime/unit, backend and browser)
were individually digest-verified and preserved together as
`dsGPT-ci-test-evidence-c9e34a9.zip`: 44636 bytes, SHA256
`d683547720d37d91302512ae8d097e5566cda618f066e59ec9cc12ad1a25d53b`,
durable file `libfile_96babedc9c70819188f4415ff4179b85`.

The correction extends unchanged-source retention to rejected existing-file
writes, including consecutive nonmutating rejections. Only previously observed
source with a still-current hash is retained, within the model's input budget;
intervening successful tools and stale bytes remain excluded. Complete retained
pages also participate in the existing immediate redundant-read suppression.
Recovery explicitly asks for a targeted edit, distinguishes rejected proposals
from saved source, and keeps its error guidance when history cannot fit.
The overwrite protection, model choices, original request, no-progress thresholds
and completion requirements remain unchanged. Fixture tests cover stale/partial
pages, intervening tools, consecutive rejections, tight-context feedback, unchanged
source after rejection and a subsequent explicitly chosen valid targeted edit.
These fixtures do not establish real-model recovery. Owner hardware is unverified.

Validation of this correction: all 1123 tests plus 6 subtests passed in 88.37
seconds; 40 focused recovery/completion tests also passed. Ruff, whitespace and
static CI-policy checks passed. Pinned tracked-source Gitleaks found no leaks in
approximately 3.73 MB. Manual publication review covered the four changed source,
test, request-marker and evidence-note files; no private diagnostics or generated
fixture implementations were added. This limited audit is not a security
certification. Before dispatch, public inventory was 80 artifacts totaling
114078920 bytes, with no active run among the latest workflow results. No storage
deletion was needed. Fresh actual-model acceptance remains required.

## 05551b7 routine platform verification

Routine CI 42151902310 passed all nine jobs on exact commit
`05551b713414e9ea06b906f27e6cf5b9f119cbba`, tree
`e699fceb6436c114f048e7fddfb266b61095badf`. Five report archives were
digest-verified and preserved as `dsGPT-ci-test-evidence-05551b7.zip`:
44157 bytes, SHA256
`fbb0f2d89f8f2942ecac751ad79a2d60ff37eb0e760ed9050a6eb529efa1aa9b`,
durable file `libfile_dc9cf9e6e7988191b772a99e073abf05`.
The installed Windows app passed native UI/local-reply, Credential Manager,
startup/restart, reinstall owner/chat/model preservation and data-preserving
uninstall checks. This routine installation fixture used its existing 1.7B
model, not as a substitute for the separate actual 9B complex-app test.
Android instrumentation reported OK for its native lifecycle/diagnostic test.
Neither routine job establishes complete item-5 acceptance or owner hardware
behavior.

Fresh original-request 9B run 42151902349, model job 127676866076, is active on
this same exact commit. Pinned runtime/model load and production Docker toolchain
steps passed; the actual model-decision step is in progress. Its completion,
follow-up and generated-app native results remain unverified. Do not duplicate
or cancel this run, and do not attribute later code changes to it.

## Actual 05551b7 outcome: alternating source pages

Original-request actual 9B run 42151902349 ended with `no_progress` at initial
step 17. The model wrote a new 4647-character module, then alternated its first
and final source pages without editing. The module was incomplete; no generated
native application jobs ran. Original evidence artifact 13474466721 is 106831
bytes, SHA256 `c2c2b7bc986e68433517198484236dd8735960b2bb319110ae3679c63e152aeb`,
preserved as `libfile_45f952e6a9048191b56f9087d36f923f`.

Local replay of the recorded actions reproduced the missing preceding source
page: the current result fit, but the companion did not. Spare space was later
filled with requirement navigation, leaving the source incomplete in the prompt.
The correction tries compacting inventory and requirement previews before
omitting inspected source. It retains an explicit requirement reader pointer,
original requirement hash and real inventory continuation. No saved requirements
or source are changed. The same replay now contains both full observed pages
within the original 16384-context/4096-output configuration (12164 estimated
input tokens). This is a controller replay, not new model acceptance.
The added synthetic regression covers the large-inventory case with Unicode
page offsets and checks that the original requirement digest remains unchanged.

Validation: 1124 tests plus 6 subtests passed in 83.76 seconds; the focused
source/rejection suite passed 30 tests. Ruff, whitespace, CI-policy and pinned
tracked-source Gitleaks passed. Manual review covered all four changed files,
including the previously uncommitted platform evidence notes. No private archive
content, signing material or generated app implementation was published. The
limited source scan is not a security certification. Before dispatch there were
91 public artifacts totaling 130320546 bytes; all in-progress, queued, waiting
and pending run counts were zero. No artifact deletion was necessary.

## f837816 routine CI and live acceptance observation

Routine CI 42156601269 passed all nine jobs on exact commit
`f837816d835b5ed8e8e4cdde4cdf5033e7c5fb8b`, tree
`beadb76a59f24f17d2e91254a0c7434908d95aeb`. Five report archives were
digest-verified and preserved as `dsGPT-ci-test-evidence-f837816.zip`:
43922 bytes, SHA256
`73310989eeab903eddcdfb28a56fa80c0071a77362d8f868ca45f3a94d672272`,
durable file `libfile_af93ff667d808191a17d965c514d7dbc`.
Windows installed-app reports confirm native UI/reply, Credential Manager,
restart, reinstall data preservation and data-preserving uninstall. Android
lifecycle instrumentation reports OK (one test). The Windows installation's
separate 1.7B fixture is not a substitute for the actual 9B complex-app test;
these routine jobs do not complete item 5 or verify owner hardware.

At 2026-11-06 04:17 UTC, actual-model run 42156601199, job 127692123377,
remained active. The recovered browser could read the live decision log: initial
step 14, last action read_file, recorded result. Step 12 had a write_file tool
error, followed by recorded reads at steps 13 and 14. The log does not identify
the error's underlying payload; no diagnosis or success claim is inferred from
these action categories. Completed job logs still returned BlobNotFound during
this active run. No duplicate run, cancellation, source change or acceptance
relaxation was made. Browser access also freshly confirmed the archive remains
private with repository-wide Disable actions selected. No archive settings or
content were changed, and historical storage inventory remains unverified.

At 2026-11-06 04:24 UTC, the same actual-model run had advanced to
initial step 16: step 15 edit_file was recorded, followed by read_requirements.
No completed-app or native acceptance result was available. Both local and
remote main remained f837816; only these evidence notes were modified.
The account budget UI showed $0.00 limits and Usage blocked for Actions,
Packages, Codespaces, Git LFS and all AI Credit SKUs. The archive's Actions
settings still selected Disable actions; its artifact retention setting was
90 days (no change made). Fresh public inventory contained 101 artifacts,
146455387 bytes, none expired; no deletion was needed.

The live log at 04:30 UTC had advanced to initial step 17 (read_file,
recorded) after the step-15 edit. It remained in progress; no completed build
or follow-up/native result was available. The existing continuation automation
remains enabled with the updated checkpoint.

## Actual f837816 outcome: unchanged edit recovery

Run 42156601199 failed at initial step 23 with no_progress. The actual model
made an initial edit, reread requirements/source, then submitted identical
old_text/new_text at step 22. No bytes changed. The next repeated source read
stopped the task; no generated-app native jobs ran. Original artifact
13478083990 (115835 bytes) was SHA256-verified:
`ce4c642edfeed0f40aaccfae2bcf3cb898a4fa2b8441cb4a645cd3eacc182f5d`,
preserved as `libfile_113ce81b4ce48191bf392526c846f70b`.

The recovery prompt attached the first page after an unchanged edit but did
not retain the previously inspected second page. The correction permits the
existing hash-checked companion-page retention for this nonmutating result,
compacts duplicate guidance, and describes the rejected edit as unchanged
instead of repeating the model's implementation claim. Original actions stay
in the step log; source bytes, context/output limits and acceptance are unchanged.
A synthetic two-page regression now verifies full visible source, stale-hash
rejection, unchanged-edit feedback and no false completion. Focused checks: 31
passed. This is controller validation, not actual-model acceptance.

Full suite: 1125 tests plus 6 subtests passed in 77.14 seconds. Ruff, whitespace
and CI-policy checks passed. Pinned tracked-source Gitleaks found no leaks in
approximately 3.74 MB. Manual review covered the four changed files, including
preserved platform notes; no private data or generated fixture implementations
were added. This limited review is not a security certification. Before retry,
all active/queued/waiting/pending counts were zero; public inventory held 102
artifacts totaling 146571222 bytes. No deletion was needed. Fresh actual-model
acceptance is still required. Owner hardware remains unverified.

## 5160533 routine platform verification

Routine CI 42170959002 passed all nine jobs on exact commit
`5160533850966c91edf0105d4f1024533b39d254`, tree
`9ff9f7f42152214be9745281306283a71e645127`. Five report ZIPs were
digest-verified and preserved as `dsGPT-ci-test-evidence-5160533.zip`,
43745 bytes, SHA256
`f711c2e5e8fb39bf8ed3ed2ab3319ba524af93b881a45eff3e870417f1f3d7e7`,
durable file `libfile_fde3_f-4eeceff1b6b48191ac34280d76865fb7_0e1c3d7a1ce08191b900cc9270ea7257`.
Windows installed-app reports verify actual native UI/reply, Credential Manager,
restart, reinstall owner/chat/model preservation and data-preserving uninstall.
That routine fixture uses qwen3:1.7b, not a substitute for actual 9B complex-app
acceptance. Android instrumentation reports OK (one lifecycle/diagnostics test).
These results do not establish complete item 5 or owner-hardware behavior.

At 2026-11-06 06:25 UTC, actual 9B run 42170958913, job 127738398541,
remained in progress on the same source. Pinned model/runtime preparation and
production Docker toolchain passed; unchanged-request model decisions were
still in progress. No completion/follow-up/generated-native result was available.
No duplicate, cancellation, acceptance relaxation or product source edit was made.

## Actual 5160533 outcome: alternating complete visible files

Run 42170958913 failed at initial step 17 no_progress. After an edit at step
12, the model alternated complete MainActivity and manifest reads. The read
summaries incorrectly described finding domain/UI code in the manifest. No
generated-app native jobs ran. Artifact 13483292494, 104774 bytes, was
digest-verified SHA256
`5c3f2595e7d4dba2f0dee055fbb3884470e715b64de4a5efdb7da470454929ad`
and preserved as `libfile_fde3_f-55b1224e85f881918f7ddecaef7be83a_0e1c3d7a1ce08191b900cc9270ea7257`.

The grammar suppressed only the last complete visible file, even when a
second complete current file was retained in the same prompt. The correction
collects both fully displayed hash-verified files for read suppression.
Partial, stale and corrupted observations remain readable; edits stay available.
The model still chooses its own implementation and tools. No loop limit,
original request, acceptance check or model was changed. Four focused cases
cover complete/partial/stale/corrupt companion data; focused suite passed 35.
This is controller validation, not actual-model completion evidence.
Before retry active/queued/waiting/pending counts were all zero; inventory
was 113 artifacts totaling 162811118 bytes. No deletion was necessary.

Full suite passed 1129 tests plus 6 subtests in 84.39 seconds. Ruff,
whitespace and CI-policy checks passed. Pinned tracked-source Gitleaks
reported no leaks. Manual publication review covered all five changed files
including preserved platform evidence notes; no private diagnostics, signing
data or fixture implementation was added. This limited audit is not a
security certification. Actual-model acceptance of the fix remains required.

## 047b852 routine platform verification

Routine CI 42184430342 passed all nine jobs on exact commit
`047b852b35d9d436014f9b3fe6e5c69abe9cd6c3`, tree
`9e4ffd514aa1f17fa54ea6aa8b1bfcc125870efc`. Five report ZIPs were
digest-verified and preserved as `dsGPT-ci-test-evidence-047b852.zip`,
44263 bytes, SHA256
`f556199d12eb424524f30a48cb53561feb88c64922607ede7063694e940eb8d2`,
durable file `libfile_fde3_f-7c2de57ad210819195a479cad58c0ce6_0e1c3d7a1ce08191b900cc9270ea7257`.
Windows reports verify native UI/local reply, Credential Manager, restart,
reinstall owner/chat/model preservation and data-preserving uninstall. Its
qwen3:1.7b fixture is separate from the actual 9B complex-app acceptance.
Android instrumentation reports OK (one lifecycle/diagnostics test). These
routine results do not establish complete item 5 or owner hardware behavior.

At 2026-11-06 08:23 UTC, actual 9B run 42184430301, job 127781305042,
remained in progress on the same source. Pinned model/runtime and production
Docker toolchain steps passed; original-request model decisions were active.
No completion/follow-up/generated-native result was available. No source
change, duplicate run, cancellation or acceptance relaxation was made.

## 047b852 actual-model requirement-offset failure and recovery

Actual original-request 9B run 42184430301 on
`047b852b35d9d436014f9b3fe6e5c69abe9cd6c3` failed initial step 19
with `no_progress`. Model/runtime and production toolchain setup passed.
Generated Windows/Android native jobs were skipped; complex completion and
follow-up acceptance remain unverified. Original artifact 13490296556 is
106128 bytes, SHA256
`946f592c8247ec1cdd20fcaa99dfdf9b48ac3771f82626de33a8c069435c413b`,
digest-verified and preserved as `dsGPT-complex-evidence-42184430301.zip`,
durable file `libfile_fde3_f-a2cc9b531a1c81919e3e5368ed72449d_0e1c3d7a1ce08191b900cc9270ea7257`.

Observed step 12 changed MainActivity; step 14 proposed an identical-text edit
and was rejected. Steps 15–18 then requested requirement section 2 at offset
900 and section 3 at offsets 2229/3735, beyond their section lengths (869 and
1506 characters). The reader returned empty successful pages and the controller
called them completed. Step 19 repeated the empty section read and stopped.
This is distinct from the prior alternating source-file read failure.

The reader now labels section-relative character offsets and rejects offsets
outside the selected section with explicit recovery at offset 0 of that same
requirement_id. Exact end-of-section reads remain valid EOF. Guidance preserves
the distinction between whole-document provenance and section-local navigation,
including when the full history pair cannot fit. Original requirements and model
actions are preserved; no implementation, acceptance threshold, model, output
budget, context size or loop limit was substituted or relaxed.

Four new cases cover invalid offsets, exact original preservation, prompt feedback,
a later Unicode section with nonzero provenance, and valid EOF. The combined
requirement/source-recovery suites passed 49 tests. A trial addition to the global
system prompt displaced a companion source page in an existing regression;
that addition was removed. Guidance is now localized to requirement reads and
all focused source-retention checks pass. These are controller tests, not actual
9B completion evidence; a fresh original-request acceptance is still required.

Full suite passed 1133 tests plus 6 subtests in 82.29 seconds. Ruff, whitespace,
static CI-policy and pinned tracked-source Gitleaks checks passed. Manual review
covered all five changed files, including the preserved platform notes. No private
diagnostics, conversations, signing material, device addresses or fixture
implementation were added. This bounded review is not a security certification.
Before dispatch, in_progress/queued/waiting/pending counts were all zero;
124 public artifacts totaled 179053146 bytes, none expired. No deletion was needed.

## 00cc809 routine platform verification

Routine CI 42200997504 passed all nine jobs on exact commit
`00cc8096cbf0a6fce6708350128a19bded3302a0`, tree
`769135156be33c364df341d1d119fd8785deff4c`. Five report ZIPs were
digest-verified and preserved as `dsGPT-ci-test-evidence-00cc809.zip`,
44109 bytes, SHA256
`a4dbc491943e93fec14de8c6c1a8898e4e87128b1f5101b7d17bb718fb9b53d9`,
durable file `libfile_fde3_f-703b365446948191a18285de132d50fd_0e1c3d7a1ce08191b900cc9270ea7257`.
Windows reports verify native UI/local reply, Credential Manager, scheduled
backend restart, model persistence, owner/chat preservation through reinstall,
and data-preserving uninstall. Its qwen3:1.7b fixture remains separate from
actual 9B complex-app acceptance. Android instrumentation reports OK (one
lifecycle/diagnostics test). These checks do not establish complete item 5,
production signing continuity or physical owner hardware behavior.

On 2026-11-06, actual original-request run 42200997722, job 127835965060,
remained in progress on the same commit. Pinned exact-model preparation and
production Docker toolchain steps passed; actual model decisions were active.
No completion/follow-up/native generated-app result was available. The run was
not duplicated, cancelled or modified. These notes preserve new evidence
without creating another build or changing the source under test.

## 00cc809 actual requirement/source comparison failure

Original-request actual 9B run 42200997722 on
`00cc8096cbf0a6fce6708350128a19bded3302a0` failed initial step 25
with `no_progress`; generated native jobs were skipped. The model created a
4165-character TaskLedger.kt module, inspected its pages, reread a requirement,
and then repeated the first source-page read. Steps 22 and 23 read offsets 0 and
3000; step 24 read requirement 1, displacing both observed source pages from
the next prompt. Step 25 repeated the unchanged source read. No generated
application completion or follow-up/native acceptance is claimed.

Original artifact 13500436160 is 125874 bytes, SHA256
`47dc2e50579fc4fcb1afdc891c8d32b83d612893412fbef5b54cd3fa830463d0`,
digest-verified and preserved as `dsGPT-complex-evidence-42200997722.zip`,
durable file `libfile_fde3_f-419371bd00e08191a03a75448bb258f8_0e1c3d7a1ce08191b900cc9270ea7257`.

The controller now retains up to two distinct recently observed source pages
across requirement comparisons, only when their hashes match current files and
the prompt fits. It compacts navigable metadata if needed, keeps the actual
requirement result, and validates combined displayed pages before suppressing
redundant complete-file reads. Partial, stale or corrupt bytes do not count as
a complete visible file. Four regression cases exercise multi-page retention, stale-source exclusion,
and leaving partial pages readable when a larger comparison cannot fit. The
focused source-guidance suite passed 20 tests.
No model action, original request, generated implementation, acceptance check,
context/output budget or repeated-failure limit was changed. These controller
checks do not establish actual-model completion.

An isolated replay using the failed run's original requirements, section notes,
observed source and step history confirms both TaskLedger source pages remain
visible after step 24. Estimated input plus reserved output is 15799 within the
unchanged 16384 limit. Generated notes/overview and duplicate section previews
are deferred with explicit navigation pointers when necessary; the exact latest
requirement text remains. This replay uses saved observations, not a new model
response, and is not actual-model acceptance. A larger synthetic comparison still
cannot retain the whole file; its partial source remains readable rather than
being falsely classified as complete. The original acceptance remains unchanged.

Final full suite passed 1137 tests plus 6 subtests in 86.31 seconds. Ruff,
whitespace, CI-policy and pinned tracked-source Gitleaks passed. Manual review
covered all four changed files and preserved earlier platform evidence notes;
no private diagnostics, signing material, personal conversations or fixture
implementation were added. This limited review is not a security certification.
Fresh pre-dispatch checks found zero active/queued/waiting/pending runs.
Inventory contained 135 artifacts totaling 195314876 bytes; no deletion needed.

## 56dfed1 routine platform verification

Routine CI 42220803883 passed all nine jobs on exact commit
`56dfed168838ee4a3dddd5ba106a019022c90bf1`, tree
`e8d4bb88a2adac3149a168e62268abc2cf7cb5be`. Five report ZIPs were
digest-verified and preserved as `dsGPT-ci-test-evidence-56dfed1.zip`,
45111 bytes, SHA256
`d2ad498258df84b8daf03f54a7e721047b9269ebb03962ab87ff696d4e93637e`,
durable file `libfile_fde3_f-7df79e0bbcd88191b1fcde55e0263d24_0e1c3d7a1ce08191b900cc9270ea7257`.
Windows reports confirm native UI/local reply, Credential Manager, scheduled
backend restart, persisted models, owner/chat preservation through reinstall,
and data-preserving uninstall. Its separate qwen3:1.7b fixture does not establish
actual 9B complex-app acceptance. Android instrumentation reports OK (one
lifecycle/diagnostics test). Complete item 5, production signing continuity and
owner hardware behavior remain unverified by these routine checks.

On 2026-11-06, actual 9B run 42220803700, job 127902062686, remains active
on the same source in the unchanged-request model-decision step. No completed
complex-app, follow-up or generated native result is available. The run was
left undisturbed; no source change or duplicate acceptance was dispatched.

## 56dfed1 repeated visible requirement-page failure

Actual original-request run 42220803700 on
`56dfed168838ee4a3dddd5ba106a019022c90bf1` failed initial step 15 with
`no_progress`. After scaffolding and reading source, step 12 wrote Task.kt.
Steps 13 and 14 read requirement 3 at section-relative offset 900; step 15
requested that identical page again. The exact page was already displayed,
but requirement navigation had no equivalent of the visible-source read guard.
No generated-app native or follow-up checks ran.

Original artifact 13504974572 is 101644 bytes, SHA256
`94a24ab7bf379ce0f9b6c8b91e33f88066007114ab957775e37c3f2178534b40`,
digest-verified and preserved as `dsGPT-complex-evidence-42220803700.zip`,
durable file `libfile_fde3_f-39de502106d081919ef3129feba5fa7e_0e1c3d7a1ce08191b900cc9270ea7257`.

The action schema now excludes the single identical requirement-ID/offset pair
only when its nonempty displayed text matches the saved original section and
its provenance/offset match the last read. Other sections and explicit offsets
remain selectable. Missing, corrupt, stale or empty observations leave the
normal reader available. The model still chooses all implementation actions;
no code is substituted and the original request, model, context/output limits,
repeated-failure guard and independent acceptance remain unchanged. Seven new
cases cover exact-page exclusion and invalid-observation recovery; 60 focused
requirement/source tests passed. This validates controller behavior, not a
successful actual 9B complex-app run.

Final suite passed 1144 tests plus 6 subtests in 94.30 seconds. Omitted offset
retains its default-zero semantics unless zero is the already-visible offset.
A saved-result replay identifies the observed requirement 3/offset 900 pair;
this is not fresh inference. Ruff, whitespace, CI policy and pinned tracked-source
Gitleaks passed. Manual review covered all five changed files, including newly
tracked tests and earlier platform notes. No private diagnostics, signing data,
personal conversations or generated-app implementation were added. This bounded
review is not a security certification. Before dispatch all active/queued/waiting/
pending counts were zero. Inventory was 146 artifacts totaling 211553836 bytes;
no deletion was necessary.

## 25f5b67 routine platform verification

Routine CI 42235222953 passed all nine jobs on exact commit
`25f5b678dcb2e8f9cf001491b13a9ae68e4215c3`, tree
`c829de3a6437e25907aa5a6b9af0d08db3443a07`. Five report ZIPs were
digest-verified and preserved as `dsGPT-ci-test-evidence-25f5b67.zip`,
45137 bytes, SHA256
`d73330bc42c629b24ae2a68fada31ddff43dcd43a907576a53fc0ff550cbfffe`,
durable file `libfile_fde3_f-6e9a295d23f08191965e99b8b9979f6b_0e1c3d7a1ce08191b900cc9270ea7257`.
Windows reports verify native UI/local reply, Credential Manager, scheduled
backend restart, model persistence, owner/chat preservation through reinstall,
and data-preserving uninstall. Its separate qwen3:1.7b fixture does not establish
actual 9B complex-app acceptance. Android instrumentation reports OK (one
lifecycle/diagnostics test). Complete item 5, production signing continuity and
owner hardware behavior remain unverified by these routine checks.

On 2026-11-06, original-request actual 9B run 42235222902, job 127950958616,
remains active on this source in the unchanged-request model-decision step.
No completed complex-app, follow-up or generated native result is available.
No source mutation, duplicate acceptance or cancellation was performed.

## 25f5b67 actual-model failure and multi-file source retention

Original-request actual 9B run 42235222902 completed with failure on exact
`25f5b678dcb2e8f9cf001491b13a9ae68e4215c3`. Model loading and the production
Docker toolchain passed. Initial step 28 stopped with `no_progress`: after an
unchanged edit rejection and requirement comparison, steps 24–27 cycled through
the manifest, Task.kt and MainActivity.kt; step 28 requested Task.kt again.
Generated Windows/Android native checks and follow-up did not run.

Original artifact 13519913547 was downloaded and its GitHub digest verified:
126571 bytes, SHA256
`c75b5e73d6d720ea2bbec49ac97a2353086b96f56bafad360d01acec6c84d579`.
It is preserved as `dsGPT-complex-evidence-42235222902.zip`, durable file
`libfile_fde3_f-c3627f5768a88191b9352c528d910ff8_0e1c3d7a1ce08191b900cc9270ea7257`.
This supersedes the preceding active-run observation, not the passing routine CI.

The controller retained only the immediately preceding source read after each
new source read. Thus a three-file cycle evicted an observed page even when all
three could fit. It now considers distinct pages from the existing eight-step
history, requires matching current file hashes and action/result paths, and adds
only pages that fit the unchanged budget. Stale, partial or omitted source stays
readable; edit actions remain available. Original requirements and step logs are
unchanged. The existing bounded repeated-action stop is unchanged.

Four synthetic regressions cover three-file retention, interleaved requirement
reads and genuine edits invalidating old observations. The focused suites passed
31 tests. A diagnostic replay using the failed run's saved source, requirements,
notes and history through step 27 retains all three complete source files at an
estimated 16080/16384 total budget, including the unchanged 4096 output reserve.
This replay is not fresh model inference, app implementation or acceptance.

Full local suite passed 1148 tests plus 6 subtests in 86.43 seconds. Ruff,
whitespace, CI-policy and pinned tracked-source Gitleaks checks passed. Manual
publication review covered the four changed files, preserving earlier platform
notes and excluding original private diagnostics, conversations, credentials,
signing material and generated-app implementation. This limited review is not a
security certification. Before dispatch all active/queued/waiting/pending counts
were zero; 157 artifacts totaled 227818265 bytes, none expired. No deletion was
needed. Earlier account usage-blocking and private archive disablement checks
remain the administrative evidence; historical private storage stays unverified.

## 192e6f1 routine platform verification

Routine CI 42257120120 passed all nine jobs on exact commit
`192e6f12f069ff1a760ff71a657b14e088cf8a4f`, tree
`a6383f959867cda2cc2b0fc116bc7f1d0e8d65b6`. Five report archives were
GitHub-digest-verified and preserved as `dsGPT-ci-test-evidence-192e6f1.zip`,
45060 bytes, SHA256
`fa51d6c373fee019accd5f30c4f5fa6a01384b990155ed7cd099dbbbe97450d5`,
durable file `libfile_fde3_f-028ae7ea305481918f98f30598b46541_0e1c3d7a1ce08191b900cc9270ea7257`.
The installed Windows report verifies native UI/local reply, Credential Manager,
scheduled backend restart, model persistence, owner/chat preservation through
reinstall and data-preserving uninstall. This uses separate qwen3:1.7b fixture
inference, not the actual 9B complex-app acceptance. The staged report still
labels inference setup BLOCKED and production/physical usability REVIEW; those
labels are not converted into passes by the independent installed-app result.
Android lifecycle/diagnostics instrumentation reports OK (one test).
Complete item 5, production signing and owner hardware remain unverified.

On 2026-11-06, original-request actual 9B run 42257120073, job 128027141540,
remains in progress on this exact commit. Pinned model loading and production
Docker toolchain setup passed; the unchanged-request model decision step is
active. No completed complex-app/follow-up/generated-native result is available.
No duplicate acceptance, cancellation or product source change was performed.

At 2026-11-06 19:13 UTC the live browser log for job 128027141540 showed
initial step 31 (`write_file`, `recorded`), with the job still running. Step 17
was a validation-rejected response (17107 characters); step 20 recorded an edit.
These are bounded action categories, not proof of feature correctness or a
specific underlying tool error. No completed/follow-up/native result exists yet.
The active run was not cancelled, duplicated or altered.

## 192e6f1 completed complex-run failure and empty-page recovery

Original-request actual 9B run 42257120073 on exact
`192e6f12f069ff1a760ff71a657b14e088cf8a4f` failed at initial step 61,
`no_progress`. This supersedes the preceding live observations. The model made
source changes, including an edit at step 51, but did not complete the app.
Steps 57 and 59 read requirement section 3 at offset 0; step 58 read its exact
EOF (1506) and got a valid empty page, then step 60 requested offset 3000 and
received the explicit out-of-range error. Step 61 repeated offset 0 and stopped.
Generated Windows/Android and follow-up jobs were skipped. This is not an
acceptance pass or evidence that the generated implementation is correct.

Original evidence artifact 13541152353 is 178288 bytes, SHA256
`ae827774d70b74525586b42c0ea72d70b91a1ae69274dc2b83d125338818f9b1`.
Its GitHub digest was verified and the unchanged ZIP preserved as
`dsGPT-complex-evidence-42257120073.zip`, durable file
`libfile_fde3_f-dbf03e489b9c819193be05b98d0a729b_0e1c3d7a1ce08191b900cc9270ea7257`.

The controller now retains the most recent observed nonempty page of the same
requirement section after an empty EOF/error result, only when it matches the
saved original and fits the unchanged budget. The latest empty/error response
remains visible. The existing identical-page grammar guard recognizes this
explicitly displayed, provenance-validated page; other sections/offsets remain
available. Missing, stale, corrupt or omitted pages do not suppress reading.
Exact EOF behavior and original action logs remain unchanged.

Two synthetic regressions cover exact EOF and invalid-offset recovery, including
stale/corrupt provenance and an omitted page under a tight budget. The combined
focused suites passed 33 tests. A diagnostic replay of saved evidence through
step 60 retains section 3 offset 0 at estimated 15917/16384 total budget,
including the original 4096 output reserve. Replay is not fresh model acceptance.
Before dispatch, active/queued/waiting/pending counts were all zero; 156 public
artifacts totaled 227738859 bytes, none expired. No deletion was needed.

Full local suite passed 1150 tests plus 6 subtests in 78.31 seconds. The final
focused run additionally verifies omitted-page behavior under a tight budget.
Ruff, whitespace, CI-policy and pinned tracked-source Gitleaks checks passed.
Manual publication review covered the four changed files, including preserved
platform notes and the dispatch request; no private diagnostics, conversations,
device addresses, credentials, signing material or generated-app implementation
were added. The tracked-source scan and limited manual review are not a security
certification. A new actual-model run is still required on the published source;
none of these local checks establishes complex-app completion.

## c58a223 routine platform verification

Routine CI 42298079219 passed all nine jobs on exact commit
`c58a223fff96d18e8343c622af6f125c23aaf58c`, tree
`6cf364d93699a93100eef9e1deba02730f6d4265`. Five report ZIPs were
GitHub-digest-verified and preserved as `dsGPT-ci-test-evidence-c58a223.zip`,
44084 bytes, SHA256
`9403fbf395c35031aae6ea8c825f2bd795e1ba46677097d9d5dcd1a46d0bd15c`,
durable file `libfile_fde3_f-7d9787a6aef881918f44eb41911bb498_0e1c3d7a1ce08191b900cc9270ea7257`.
The installed Windows report verifies native UI/local reply, Credential Manager,
scheduled backend restart, model persistence, reinstall owner/chat preservation
and data-preserving uninstall. It uses separate qwen3:1.7b fixture inference,
not actual 9B complex-app acceptance. The staged report retains inference BLOCKED
and production/physical usability REVIEW labels. Android lifecycle/diagnostics
instrumentation reports OK (one test). Complete item 5, production signing and
owner hardware remain unverified.

On 2026-11-06, original-request actual 9B run 42298079310, job 128168402828,
remains in progress on this exact commit. Exact model loading and production
Docker setup passed; the unchanged-request model-decision step is active.
No completed complex-app, follow-up or generated-native result is available.
The run was left undisturbed; no duplicate run or source change was made.

## c58a223 completed complex failure and compiler/source handoff

Original-request actual 9B run 42298079310 on exact
`c58a223fff96d18e8343c622af6f125c23aaf58c` failed initial step 22,
`no_progress`. This supersedes the preceding active observation. Step 21 ran the
production build and received Android compiler errors, including unresolved
`remember` and `title` references. Step 22 requested its third unchanged
MainActivity source read and stopped. Generated native/follow-up jobs skipped.
Neither compilation nor complex-app completion passed.

Original artifact 13547052678, 123345 bytes, was GitHub-digest-verified:
SHA256 `ca5e4570157c4292ffc3cb283272d62503e99dc8ed7c77947d125dfab26582f1`.
The unchanged `dsGPT-complex-evidence-42298079310.zip` is preserved as durable
file `libfile_fde3_f-85ed1aa0f5648191a3b9f31a7432f90d_0e1c3d7a1ce08191b900cc9270ea7257`.

The prompt previously retained observed source across reads/rejections but not
failed builds. It now applies the same bounded current-hash source retention
after `build_project` returns `command_failed`, alongside the exact latest
compiler response. No model code/action was substituted. Changed or omitted
source remains readable; the existing no-progress limit, budgets and acceptance
criteria remain unchanged. Two synthetic tests verify current versus stale source
and preservation of compiler diagnostics; focused suite passed 28 tests.
A replay of saved evidence through step 21 retains MainActivity and Task source
with the compiler response at estimated 15379/16384 budget including the unchanged
4096 output reserve. This is diagnostic replay, not fresh actual-model acceptance.

Full suite passed 1152 tests plus 6 subtests in 84.17 seconds. Ruff, whitespace,
CI-policy and pinned tracked-source Gitleaks passed. Manual publication review
covered all four changed files and preserved prior platform notes; no private
conversations, diagnostics, device addresses, credentials, signing material or
generated-app implementation were added. This limited review is not a security
certification. Before dispatch all active/queued/waiting/pending counts were zero;
124 public artifacts totaled 179170610 bytes, none expired. No deletion needed.
Historical private storage remains unverified, archive Actions disabled and
account usage blocking unchanged from the recorded administrative checks.

## 114db75 routine platform verification

Routine CI 42314308021 passed all nine jobs on exact commit
`114db758553784d7f5a66ffa685e2b4eb11cac0a`, tree
`cd43938da2dec56ee6525dd92f5ad93f8bd963dd`. Five report ZIPs were
GitHub-digest-verified and preserved as `dsGPT-ci-test-evidence-114db75.zip`,
44214 bytes, SHA256
`3f061a4ed1fabff7cd8ea9320ef513c71244661097b692ffb79945e1723be374`,
durable file `libfile_fde3_f-634c07478bd88191801a857c9015cb89_0e1c3d7a1ce08191b900cc9270ea7257`.
Installed Windows native UI/local reply, Credential Manager, scheduled restart,
reinstall owner/chat/model preservation and data-preserving uninstall passed.
This uses separate qwen3:1.7b fixture inference, not actual 9B complex acceptance.
The staged report retains inference BLOCKED and production/physical usability
REVIEW labels. Android lifecycle/diagnostics instrumentation reports OK (one test).
Complete item 5, production signing and owner hardware remain unverified.

At the 2026-11-07 00:11 UTC check, original-request actual 9B run 42314308022,
job 128223080445, remains in progress on this exact commit. Exact model loading
and production Docker setup passed; unchanged-request decisions are active.
No completed complex-app/follow-up/generated-native result is available.
No source change, duplicate acceptance or cancellation was performed.

## 114db75 completed complex failure and rejected-response requirement recovery

Original-request actual 9B run 42314308022 on exact
`114db758553784d7f5a66ffa685e2b4eb11cac0a` failed initial step 19,
`no_progress`. This supersedes the preceding active observation. After source
edit step 12, section 2 reads at steps 14/16 were separated by incomplete JSON
at step 15. Step 17 used an invalid section offset, step 18 produced another
incomplete JSON response, and step 19 repeated section 2 offset 0 and stopped.
Neither rejected JSON response executed. Generated native/follow-up jobs skipped.

Original artifact 13553436454 is 117615 bytes, SHA256
`abce471371a5722046c2e1deebfa819946a9fc1fc8fcc2a8f83d7a34e1043edc`.
The GitHub digest was verified; unchanged `dsGPT-complex-evidence-42314308022.zip`
is preserved as durable file
`libfile_fde3_f-f0bf4b0e89248191b82352b9fe3e27e0_0e1c3d7a1ce08191b900cc9270ea7257`.

Invalid-action responses retained source but displaced the inspected requirement.
The existing bounded requirement retention now also applies after invalid_action:
keep the most recent observed nonempty exact original page if it fits alongside
the latest validation feedback. The visible-page guard then prevents repeating
that same displayed page; omitted/stale pages remain readable. This changes no
model action, generated implementation, output/context budget, loop limit or
acceptance criterion. Two synthetic regressions cover one/consecutive rejected
responses, validation-feedback retention, stale originals and tight-budget
omission. Focused suite passed 30 tests. Diagnostic replay through step 18 retains
section 2 offset 0 at estimated 13550/16384 including 4096 output reserve. Replay
is not actual-model completion or a fresh acceptance pass.

Full suite passed 1154 tests plus 6 subtests in 75.41 seconds. Ruff, whitespace,
CI-policy and pinned tracked-source Gitleaks passed. Manual four-file publication
review preserved prior platform notes and excluded private diagnostics,
conversations, device addresses, credentials, signing material and generated-app
implementation. This limited review is not a security certification. Before
dispatch active/queued/waiting/pending counts were zero; 110 public artifacts
totaled 162572824 bytes, none expired. No deletion needed. Earlier archive
privacy/Actions-disablement and $0 usage-blocking checks remain the recorded
administrative evidence; historical private storage remains unverified.

## 61895e0 routine platform verification

Routine CI 42325936463 passed all nine jobs on exact commit
`61895e0e1cff9637e5afd1d5807ea394c9ac111f`, tree
`38c6cb40f8596fc1b72ec3fec5ec2dbc47d98534`. Five report ZIPs were
GitHub-digest-verified and preserved as `dsGPT-ci-test-evidence-61895e0.zip`,
44347 bytes, SHA256
`71cb3b99bcfc93dcf21df34545be60b22e52ee0167562f7b59a02b357b0d6e98`,
durable file `libfile_fde3_f-dcfdf1cc038c81918d6ef38c6269da21_0e1c3d7a1ce08191b900cc9270ea7257`.
Installed Windows native UI/local reply, Credential Manager, scheduled restart,
reinstall owner/chat/model preservation and data-preserving uninstall passed.
Separate qwen3:1.7b fixture inference is not actual 9B complex acceptance.
The staged report retains inference BLOCKED and production/physical usability
REVIEW labels. Android lifecycle/diagnostics instrumentation reports OK (one test).
Complete item 5, production signing and owner hardware remain unverified.

At the 2026-11-07 02:17 UTC check, original-request actual 9B run 42325936995,
job 128261113950, remains in progress on this exact commit, in the unchanged
request's model-decision step. No completed complex-app/follow-up/generated-native
result is available. No source change, duplicate run or cancellation was made.

## 61895e0 completed complex failure and bounded requirement navigation

Original-request actual 9B run 42325936995 on exact
`61895e0e1cff9637e5afd1d5807ea394c9ac111f` failed initial step 23,
`no_progress`. This supersedes the preceding active observation. The model made
MainActivity edits and wrote a new 12435-byte TaskLedger module at step 20.
Steps 21/22 requested section 2 offset 900 despite its length being 869 and
received explicit out-of-range errors. Step 23 proposed another write_file to the
existing module, was rejected, and the bounded failure stop fired. Generated
native/follow-up jobs skipped. Source writes do not establish feature correctness.

Original artifact 13558190302 is 120439 bytes, SHA256
`f953f27731a500e83131b194ecc232f7c4f2eef9bceb37f85ff40fb57705e898`.
Its GitHub digest was verified; unchanged `dsGPT-complex-evidence-42325936995.zip`
is preserved as durable file
`libfile_fde3_f-e444fb8ef2e081919850669dd8b5e60a_0e1c3d7a1ce08191b900cc9270ea7257`.

The action schema now uses the saved original's section lengths to constrain
requirement IDs and section-relative offsets. Every valid offset, including exact
EOF and omitted offset=0, remains available except an exact already-visible page.
Other sections and edit tools remain available. Runtime validation remains in
place. No model action, generated implementation, budget, loop limit or acceptance
criterion changed. Three synthetic cases cover no visible page, visible offset0,
and visible EOF; focused suites passed 40 tests. A saved-request schema check
confirms section2 allows 0..869 and excludes the observed invalid offset900.
This is a schema check, not a fresh actual-model acceptance result.

Full suite passed 1157 tests plus 6 subtests in 74.43 seconds. Ruff, whitespace,
CI-policy and pinned tracked-source Gitleaks passed. Manual five-file publication
review preserved prior platform notes and excluded private conversations,
diagnostics, device addresses, credentials, signing material and generated-app
implementation. This limited review is not a security certification. Before
dispatch active/queued/waiting/pending counts were zero; 99 public artifacts
totaled 146339336 bytes, none expired. No deletion needed. Historical private
storage remains unverified; earlier archive disablement and $0 usage-blocking
observations remain the recorded administrative evidence.

## Rejected overwrite after a requirement comparison (2026-11-07 UTC)

Routine CI 42334618636 passed all nine jobs on exact
`43b855c73716e02200f236ec2469849c636ccdc9`. The five original report ZIPs
were individually checked against GitHub's SHA256 digests and bundled as
`dsGPT-ci-test-evidence-43b855c.zip`, 43623 bytes, SHA256
`1f036f59f8dc473fb0f465a3f67f028918070d285cd8b9bbb58845047836716f`.
Durable evidence:
`libfile_fde3_f-7380949fc1948191b8157e71884a09b1_0e1c3d7a1ce08191b900cc9270ea7257`.
Installed Windows native UI/local reply, Credential Manager, scheduled restart,
reinstall/data preservation passed. Android lifecycle/diagnostics instrumentation
reported OK (1 test). Windows uses the separate qwen3:1.7b fixture, not actual 9B
complex acceptance or complete item 5. The staged inference BLOCKED and production
REVIEW labels remain in the original evidence. Owner hardware remains unverified.

Original-request actual 9B run 42334618633 on that same commit failed initial
step 24, no_progress. Step 19 proposed an edit with a wrong hash and was rejected;
step 20 read unchanged MainActivity; step 21 proposed an identical-text edit and
was rejected. Step 22 read requirement 3, step 23 attempted a whole-file overwrite
and was rejected, and step 24 requested the third unchanged source read. No
rejected edit executed. Generated native and follow-up jobs skipped.

Original artifact 13559579232, 117196 bytes, SHA256
`5b59f1bfba76e9c548ba58b1fce8fee6bbecff68cbd82f18d82a0c82f9a8ce2f`,
was digest-verified and preserved unchanged as
`dsGPT-complex-evidence-42334618633.zip`, durable file
`libfile_fde3_f-5c613eebf2ec8191bf037ba167e8bbe1_0e1c3d7a1ce08191b900cc9270ea7257`.

The rejection recovery search stopped at the intervening requirement result,
even though the previously inspected file still matched its current hash. The
fix searches the existing bounded history for the latest qualifying source read,
retaining it only if it fits alongside the rejection feedback. Non-source results
are not substituted for source. Partial/stale/omitted content stays readable;
edit tools remain available. No model actions, generated source, loop limits,
context/output budgets or acceptance criteria changed.

Saved-result replay through step 23 previously omitted MainActivity and now
retains its complete hash-verified text at estimated 15022/16384 including the
unchanged 4096 output reserve. This is a controller replay, not fresh model
acceptance. Synthetic cases cover intervening inventory, requirements, no-op edit
plus comparison, and stale source after comparison for both rejected JSON and
rejected overwrites.

Full suite passed 1163 tests plus 6 subtests in 84.27 seconds; focused rejection
and requirement suites passed 35 tests. Ruff, whitespace, CI-policy and pinned
tracked-source Gitleaks passed. Manual review of the four changed files found no
private conversations, credentials, signing material, device addresses, private
diagnostics or generated-app implementation for publication. This limited review
is not a security certification. Before dispatch active/queued/waiting/pending
counts were zero; 110 public artifacts totaled 162594396 bytes, none expired.
No deletion was necessary. Historical private storage remains unverified; prior
archive disablement and $0 usage-blocking observations remain the administrative
evidence. Item 1 remains open; items 2–5 and the upgrade release remain gated.

## Rejected overwrite target selection (2026-11-07 UTC)

Routine CI 42338395352 passed all nine jobs on exact
`b357c6b01139614296930c9feca5448ce9b15936`. Five original report ZIPs were
verified against GitHub SHA256 digests and preserved in
`dsGPT-ci-test-evidence-b357c6b.zip`, 43869 bytes, SHA256
`f63d28b1154158eb72a28abc27eb5e2fb02de01d90a0e9a73eb6706bd5c409b0`,
durable file
`libfile_fde3_f-3a568548e240819197ca6deacf968d56_0e1c3d7a1ce08191b900cc9270ea7257`.

Actual original-request 9B run 42338395466 failed initial step 17, no_progress.
Whole-file MainActivity writes at steps 11, 13 and 16 were rejected. Read 14
showed MainActivity, read 15 showed build.gradle despite the model summary naming
MainActivity. After rejection 16, recovery retained the newer unrelated Gradle
read, not the target source. Step 17 repeated unchanged MainActivity and stopped.
Generated native and follow-up jobs skipped. No rejected write executed.
Original artifact 13560733606, 108515 bytes, SHA256
`82351d2a060f3242c2a4e5f5ad135fecfe0e2065da86842e5bb3781cde4c3c87`
was digest-verified and preserved as `dsGPT-complex-evidence-42338395466.zip`,
durable file
`libfile_fde3_f-9ccb5925cb78819188dc4f3ccd70e211_0e1c3d7a1ce08191b900cc9270ea7257`.

Recovery from an existing-file overwrite rejection now selects an observed read
of that exact target path from the existing bounded history, subject to the same
current-hash and prompt-budget checks. Generic invalid JSON recovery is unchanged.
Synthetic tests cover a newer unrelated read, stale target and partial target;
changed or incompletely displayed files remain readable. Saved-result replay
through step 16 retains complete MainActivity at estimated 14294/16384 including
the unchanged 4096 output reserve. This is not actual-model acceptance. No model
actions, generated implementation, request, budgets, loop limits or acceptance
criteria were substituted.

The platform reports confirm installed Windows native UI/local reply, Credential
Manager, restart and reinstall/data preservation; Android instrumentation OK
(1 lifecycle/diagnostics test). The separate qwen3:1.7b Windows fixture does not
establish actual 9B acceptance or complete item 5. Staged inference BLOCKED and
production REVIEW labels remain, and owner hardware is unverified. Before the
next dispatch, active/queued/waiting/pending counts were zero; 110 public artifacts
totaled 162601160 bytes, none expired. No deletion was needed. Prior archive
Private/Actions-disabled and $0 usage-blocking observations remain the recorded
administrative evidence; historical archive storage remains unverified.

Full suite passed 1166 tests plus 6 subtests in 75.74 seconds; focused rejection
suite passed 28 tests. Ruff, whitespace, CI-policy and pinned tracked-source
Gitleaks passed. Manual four-file publication review excluded credentials,
signing material, private conversations/diagnostics/device addresses and generated
application source. This limited scan/review is not a security certification.
Item 1 still requires fresh actual-model completion; later items and release
remain gated by their unchanged acceptance criteria.

## Visible requirement suffix guard (2026-11-07 UTC)

Routine CI 42345187824 passed all nine jobs on exact
`56e6b570da44d06fc892f0eedd51bf5f3026decd`. Five report ZIPs were individually
verified against GitHub digests and bundled as `dsGPT-ci-test-evidence-56e6b57.zip`,
44526 bytes, SHA256
`a8e1d3f6a3e8db850596f4dc9a16283b949d39ab71e6f0143613306fb99d340b`,
durable file
`libfile_fde3_f-7ba0e7f17cd4819181de3c3bb9184c0f_0e1c3d7a1ce08191b900cc9270ea7257`.
Installed Windows native UI/local reply, Credential Manager, restart/reinstall/data
preservation passed; Android lifecycle instrumentation OK (1 test). Separate
qwen3:1.7b fixture is not actual 9B acceptance or complete item 5. Staged inference
BLOCKED/production REVIEW labels remain; owner hardware remains unverified.

Original-request actual 9B run 42345187823 failed initial step 19, no_progress.
Step 14 wrote a new Task module. Steps 15–18 alternated requirement 3 offsets
900/901, reading virtually identical suffixes ending at character 1506; step 19
requested offset 900 again and stopped. Generated native/follow-up jobs skipped.
Original artifact 13563559930, 107822 bytes, SHA256
`aff14140a7089233dc88441c136aab893347162573c7db4dfd6d3a7c1edf8193`,
was digest-verified and preserved as `dsGPT-complex-evidence-42345187823.zip`,
durable file
`libfile_fde3_f-4ae43fda04d88191b11ade96d7b6b574_0e1c3d7a1ce08191b900cc9270ea7257`.

When exact displayed requirement text extends to the saved section's end, grammar
now excludes offsets within that already-visible suffix. Unseen prefix, other
sections and exact EOF remain available. Partial pages exclude only their exact
start because later reads could reveal new text; missing/corrupt/stale observations
remain readable. Retained verified suffixes receive the same treatment. Runtime
validation and model actions remain unchanged. No request, generated code,
context/output budget, loop limit or acceptance substitution.

Saved-observation schema check identifies section 3's visible 900..1505 suffix,
leaving ranges 0..899 and exact EOF 1506. This is not actual-model acceptance.
Focused suites passed 42 tests, including suffix, partial, corrupt and retained
observations with and without bounded section lengths. Before dispatch all active,
queued, waiting and pending counts were zero; 121 public artifacts totaled
178847815 bytes, none expired. No deletion needed. Prior archive disablement and
$0 usage-blocking observations remain recorded; historical archive storage remains
unverified.

Full suite passed 1170 tests plus 6 subtests in 78.93 seconds. Ruff, whitespace,
CI-policy, pinned tracked-source Gitleaks and manual five-file review passed.
Publication excludes private conversations, credentials, signing material,
device addresses, private diagnostics and generated-app implementation. This
limited scan/review is not a security certification. Item 1 remains open;
items 2–5 and final delivery remain gated by their unchanged acceptance criteria.

## Platform evidence on the visible-suffix checkpoint (2026-11-07 UTC)

Routine CI 42347937506 passed all nine jobs on exact
`5eb1402951d1e2748ebe03f43910cddac9d61754`. Five original report ZIPs were
individually verified against GitHub SHA256 digests and preserved in
`dsGPT-ci-test-evidence-5eb1402.zip`, 43897 bytes, SHA256
`826873b8a1165f6da3a20f3a506612ea019562a19d0474f23ee4360e0b47105d`.
Installed Windows native UI/local reply, Credential Manager, scheduled restart,
reinstall/data preservation passed. Android lifecycle/diagnostics instrumentation
reported OK (1 test). The separate qwen3:1.7b Windows fixture is not actual 9B
complex acceptance or complete item 5. Staged inference BLOCKED and production
REVIEW labels remain; owner hardware remains unverified.

Actual original-request 9B run 42347937357, job 128329642596, remains active in
unchanged-request model decisions after successful pinned model loading and
production Docker toolchain setup. No final model/native result is claimed.
No duplicate run was dispatched and the active run was not altered or cancelled.
Durable platform evidence:
`libfile_fde3_f-08471624ea048191bb72fc8824de8e63_0e1c3d7a1ce08191b900cc9270ea7257`.

## Observed requirement EOF recovery (2026-11-07 UTC)

Actual original-request 9B run 42347937357 on exact
`5eb1402951d1e2748ebe03f43910cddac9d61754` failed initial step 45,
no_progress, superseding the active observation above. Step 38 rejected a wrong-hash
source edit. Requirement 3 reads then moved through offsets 900, 90, 9 and 0.
Steps 43/44 read exact EOF 1506 and returned empty successful pages; step 45
repeated that EOF and stopped. Generated native/follow-up jobs skipped.
Original artifact 13567976308, 144731 bytes, SHA256
`5a22ad9734a4886897e829e7313d2a5ea75bca8d65e61e61188e50d0c13a04f2`,
was verified against GitHub's digest and preserved unchanged as
`dsGPT-complex-evidence-42347937357.zip`, durable file
`libfile_fde3_f-c9fac9be08e48191a6f717015a97df88_0e1c3d7a1ce08191b900cc9270ea7257`.

The grammar guard now recognizes an explicitly observed empty EOF only when its
section provenance, offset, total length and terminal paging fields match the
saved original. It excludes repeating that already-observed EOF. If the matching
verified suffix is also retained in the actual prompt, both are excluded together.
The first EOF read remains available, as do unseen prefixes and other sections.
Corrupt/nonterminal empty observations do not qualify. No actions are rewritten;
runtime validation, request, context/output budgets, loop limits and acceptance
criteria remain unchanged.

Saved-result replay through step 44 retains section 3 and excludes its observed
0..1506 range within estimated 15798/16384 including the unchanged 4096 output
reserve. This is a controller replay, not fresh model acceptance. Focused suites
passed 46 tests, covering standalone EOF, retained suffix plus EOF, incorrect
length and empty non-EOF cases. Prior platform evidence above remains preserved;
its separate 1.7B Windows fixture does not establish actual 9B acceptance or
complete item 5. Owner hardware remains unverified.

Before dispatch active/queued/waiting/pending counts were zero; 121 public
artifacts totaled 178888797 bytes, none expired. No deletion was needed. Prior
archive Private/Actions-disabled and $0 usage-blocking observations remain the
administrative evidence; historical archive storage remains unverified.

Full suite passed 1174 tests plus 6 subtests in 78.01 seconds. Ruff, whitespace,
CI-policy, pinned tracked-source Gitleaks and manual four-file review passed.
Prior uncommitted platform evidence notes are preserved. Publication excludes
private conversations, diagnostics, device addresses, credentials, signing
material and generated application source. This limited scan/review is not a
security certification. Actual-model item 1 and later release gates remain open.

### Platform evidence for d5d85de (2026-11-07)

Routine CI 42356556206 passed all nine jobs on exact source
`d5d85defb61fadc4cbe371f58659f1bfc6b52f2d`. Five original report ZIPs
(Windows, Android unit/runtime, backend, browser) were verified against GitHub's
SHA256 digests and preserved in `dsGPT-ci-test-evidence-d5d85de.zip`
(44661 bytes; SHA256
`7a01f5c9a23736e5e4a3ae4684493ce193b2a26a4192f30dc8d04dec32e1ec59`).
Durable evidence: `libfile_fde3_f-c256c0d4e10c819182ed481e8204b19f_0e1c3d7a1ce08191b900cc9270ea7257`.
Installed Windows native UI/local reply, Credential Manager, scheduled restart,
reinstall and data preservation passed using separate `qwen3:1.7b` fixture.
Android lifecycle/diagnostics instrumentation reports OK (1 test).
Staged inference BLOCKED and production REVIEW labels remain; installed-app
checks do not erase them. Owner hardware remains unverified. These results are
not actual 9B complex acceptance or full item 5 completion.
Original-request run 42356556204, job 128355801805, remains in progress after
pinned model load and production Docker setup passed. No duplicate dispatched.

### Actual model failure and idempotent prompt compaction (2026-11-07)

Original-request run 42356556204 on exact
`d5d85defb61fadc4cbe371f58659f1bfc6b52f2d` failed after initial step 25 with
`work_step_failed`; generated native/follow-up jobs skipped. Step 23 rejected an
identical-text edit, step 24 read requirement 1, and step 25 read its exact EOF.
No rejected edit executed. A saved-state replay including the original scaffold
inventory and build profile reproduces `KeyError: inputs` in
`compact_asset_context`: requirement recovery attempted to compact an already
compacted asset catalog. This is a controller exception, not `no_progress`.

Original artifact 13570103070 (118014 bytes) was verified against GitHub SHA256
`cd470bb78d89d43e3be320e801042bc1386718af3cbda7130c69fb7b18971afa` and preserved as
`dsGPT-complex-evidence-42356556204.zip`, durable evidence
`libfile_fde3_f-0d2f1d5e9b908191a6f3f01637333e29_0e1c3d7a1ce08191b900cc9270ea7257`.

The fix leaves already-compacted catalogs intact instead of indexing their removed
`inputs` array. Repeated fitting preserves counts, digest and navigation pointers;
exact results and all acceptance limits remain unchanged. Two regression cases
cover empty/nonempty input inventories and repeated fitting. The saved-state
replay now completes prompt assembly at estimated 15539/16384 including the
unchanged 4096 output reserve. This replay is not fresh model acceptance.

Validation: 1176 tests plus 6 subtests passed in 82.65 seconds; focused suite
48 passed. Ruff, whitespace, CI policy, pinned tracked-source Gitleaks and manual
four-file publication review passed. Pre-dispatch active/queued/waiting/pending
counts were all zero; 121 public artifacts totaled 178883427 bytes, none expired.
No deletion needed. Archive/admin settings unchanged; historical private storage
remains unverified. Publish with expected-head lease; fresh original acceptance
must establish actual-model behavior independently of this replay and regressions.

### Platform evidence for b4e34fc (2026-11-07)

Routine CI 42363614217 passed all nine jobs on exact source
`b4e34fc899c20a9d3b3e080a5b16bd68465a7686`. Five original report ZIPs
(Windows, Android unit/runtime, backend, browser) were verified against GitHub's
SHA256 digests and preserved in `dsGPT-ci-test-evidence-b4e34fc.zip`
(45373 bytes; SHA256
`c1c3d343869ad473f3ed1fb252eac76b7da404c849238101bab917b6fd8a118b`).
Durable evidence: `libfile_fde3_f-c663a29c35d8819182aedb99ca106881_0e1c3d7a1ce08191b900cc9270ea7257`.
Installed Windows native UI/local reply, Credential Manager, scheduled restart,
reinstall and data preservation passed using separate `qwen3:1.7b` fixture.
Android lifecycle/diagnostics instrumentation reports OK (1 test).
Staged inference BLOCKED and production REVIEW labels remain; installed-app
checks do not erase them. Owner hardware remains unverified. These results are
not actual 9B complex acceptance or full item 5 completion.
Original-request run 42363614200, job 128376916580, remains in progress in the
unchanged-request decision step. No duplicate dispatched or active run altered.

### Actual wrong-hash rejection recovery (2026-11-07)

Original-request run 42363614200 on exact
`b4e34fc899c20a9d3b3e080a5b16bd68465a7686` failed initial step 46 with
`no_progress`. The model reached compiler repair but did not complete the app.
Step 44 read MainActivity, step 45 proposed an edit using the Gradle properties
hash and received `file_changed_read_before_overwrite`; step 46 requested its
third unchanged MainActivity read. The rejected edit did not execute. Generated
native/follow-up jobs were skipped.

Original artifact 13576537299 (160789 bytes) was verified against GitHub SHA256
`683e36c979513fc702a30e30f20b6c9bff31fa910b9cc44e629bc4c7a7835ad4` and preserved as
`dsGPT-complex-evidence-42363614200.zip`, durable evidence
`libfile_fde3_f-f51511cd372c8191b81234fa5404c852_0e1c3d7a1ce08191b900cc9270ea7257`.

Treat wrong-hash rejection as nonmutating for prompt recovery and seek an observed
read of the exact target, not a newer unrelated file. Retain only current-hash
observed bytes when they fit; stale/partial/omitted source stays readable.
Runtime hash enforcement, model actions, original request and budgets unchanged.
Three added cases cover current, stale and partial target observations after a
newer unrelated source read. Saved-history replay through step 45 now retains
complete MainActivity and suppresses its redundant read at estimated
15866/16384 including the unchanged 4096 output reserve. Replay is diagnostic,
not actual-model acceptance.

Validation: 1179 tests plus 6 subtests passed in 84.23 seconds; focused suite
31 passed. Ruff, whitespace, CI policy, pinned tracked-source Gitleaks and manual
four-file publication review passed. Pre-dispatch active/queued/waiting/pending
counts were zero; 121 public artifacts totaled 178944370 bytes, none expired.
No deletion needed. Archive/admin settings unchanged; historical private storage
remains unverified. Publish with an expected-head lease and require fresh actual
model acceptance for this source.

### Actual EOF/suffix cycle and browser result (2026-11-07)

Original-request run 42381612392 on exact
`ddaf261255e9dcdec37a2cfb1da0e110115dfc94` failed initial step 25 with
`no_progress`. Requirement 1 EOF offset 1360 was read at steps 21 and 23,
interleaved with suffix reads at offsets 136 and 135; step 25 requested EOF
again and stopped. Generated native/follow-up jobs were skipped. The empty EOF
receipt was not retained after a nonempty suffix read, making the already
observed empty result selectable again.

Original artifact 13580110922 (118178 bytes) was digest-verified against GitHub:
`0f8297c8dbfb5a41d6c5ceb4dae15605bce7e8cb7762a3456d4bba8c52eba952`.
Durable evidence:
`libfile_fde3_f-0f5429b6e6e48191892de5405021c058_0e1c3d7a1ce08191b900cc9270ea7257`.

Routine CI 42381612436 on the same source FAILED the browser and required jobs;
the other seven jobs passed. The DOCX search test expected a completed reply but
observed running when its default five-second poll elapsed. All other 25 browser
tests passed. Keep that failure distinct from the passing installed Windows UI,
local reply, Credential Manager, scheduled restart, reinstall/data preservation
and Android lifecycle/diagnostics instrumentation (one test). Windows uses the
separate qwen3:1.7b fixture, not actual 9B app acceptance or complete item 5.
Staged inference BLOCKED / production REVIEW labels remain. Owner hardware
remains unverified.

All five report ZIPs, including the failed browser report, were digest-verified
and preserved as `dsGPT-ci-test-evidence-ddaf261.zip`, 46078 bytes, SHA256
`98ca0d2cb675b9ef6af79892448b3abbae861d15de90d600a1dbcbb99b3f361f`,
durable evidence
`libfile_fde3_f-631cee9a6ec0819181edf4775d8991c2_0e1c3d7a1ce08191b900cc9270ea7257`.

Recovery now retains a matching verified observed empty EOF receipt from the
existing bounded history alongside a latest suffix, only when it fits. The
grammar combines their adjacent verified ranges. A one-character suffix is not
mistaken for empty EOF. Unseen prefixes/other sections remain available;
corrupt, nonterminal, wrong-section or omitted receipts do not block reads.
Runtime checks, actual-model request, model, loop limits and context/output
budgets remain unchanged. Eight regression cases cover these boundaries and
tight-budget omission. Saved-history replay through step 24 includes section 1
suffix 135..1359 plus previously observed EOF 1360 at estimated 15905/16384,
including the unchanged 4096 output reserve. Replay is not model acceptance.

The DOCX search test now uses the same bounded 12-second completion wait as the
existing DOCX lifecycle test, retaining every completion, provenance, hidden
scope and deletion assertion. No fixture response or production inference limit
changed. Initial local browser execution lacked the pinned Chromium binary;
installing that test dependency was necessary before browser validation.

Local browser validation: all 26 Playwright tests passed (2.7 minutes), including
the exact previously failed DOCX search path. Final focused recovery/guard suite:
56 passed. Publication review covers the five changed source/test/evidence/request
files only, with no private history, signing material or diagnostic payloads.
Pre-dispatch inventory: active/queued/waiting/pending counts all zero; 121 public
artifacts totaled 178937907 bytes, none expired. No deletion was needed. Archive
and billing settings untouched; historical private storage remains unverified.

Final full suite: 1187 tests plus 6 subtests passed in 213.99 seconds. Ruff,
whitespace, static CI policy, pinned tracked-source Gitleaks and manual five-file
publication review passed. Publish with an expected-head lease from ddaf261;
fresh actual-model and platform CI evidence is still required for the new source.

### Fresh platform CI on e697429 (2026-11-07)

Routine CI 42387568748 passed all nine jobs on exact
`e697429e17ee77edf7847a101ac017ecc6de60e1`. All 26 public-runner browser tests
passed without retries or skips, including the previously failed DOCX search.
Five original report ZIPs were digest-verified and preserved in
`dsGPT-ci-test-evidence-e697429.zip`, 45096 bytes, SHA256
`9684b26f580c79fecda7189c38821a4acb2da97a8ec92650b2cb32e813a5ebac`,
durable evidence
`libfile_fde3_f-b2465652f8e0819195e7fd7384aa2784_0e1c3d7a1ce08191b900cc9270ea7257`.

Installed Windows native UI/local reply, Credential Manager, scheduled backend
restart, reinstall and data preservation passed. Android lifecycle/diagnostics
instrumentation reports OK (one test). Windows uses its separate qwen3:1.7b
fixture, not the actual 9B complex-app acceptance or complete item 5. The staged
inference BLOCKED / production REVIEW labels remain; owner hardware is unverified.

Actual original-request run 42387568715, model job 128448098687, remains active
on the same source after exact model loading and production Docker setup passed.
Unchanged-request model decisions are in progress; no native generated-app
acceptance or overall app completion is claimed. No duplicate run dispatched.

Live browser observation at 2026-11-07 16:11 UTC reached initial step 12:
step 11 write_file recorded, step 12 read_requirements recorded. These bounded
action categories do not establish correct implementation or a completed build.

### Actual 9B result on e697429 and new-file grammar recovery (2026-11-07)

Original-request run 42387568715 failed at initial step 53 with `no_progress`.
After the step-50 TaskLedger source read, step 51 proposed an existing-file
write and was rejected; step 52 proposed identical old/new text and was rejected.
Step 53 ran the production compiler, which reported undefined `TextLedger` and
reassignment of a Kotlin `val`; this third consecutive error stopped the task.
Neither rejected edit executed. The model's prose claimed successful compilation,
but the recorded compiler failure is authoritative. Generated Android/Windows
native and follow-up jobs were skipped. This is not completed item 1.

Original artifact 13585042754 was downloaded and digest-verified: 167788 bytes,
SHA256 `f57063cd91a6af4531903a3a522af91681f73a6888be892b67c3fcd49512132c`.
The original ZIP is preserved as `dsGPT-complex-evidence-42387568715.zip`, durable
file `libfile_fde3_f-73bbeac4a34c8191918f6fbd416d3214_0e1c3d7a1ce08191b900cc9270ea7257`.

The guided action schema previously allowed `write_file` to select existing paths,
even though guided execution always rejects them. It now expresses that same
existing constraint in the grammar using a prefix trie of exact current paths.
No lookahead or unsupported schema negation is required. New names, prefixes,
extensions and Unicode remain selectable; targeted edits and source reads retain
their original contracts. The pattern independently bounds names to 1..240
characters because runtime converters may not combine pattern/length keywords.
Execution checks, original request, model, context/output budgets and loop/error
limits are unchanged. No generated implementation or model action was substituted.

Parser compatibility was checked against the actual Ollama v0.40.13 upstream
pin: llama.cpp b11963, commit `39febd2adb947b70da35e95f9351b3bf58ad170a`.
A scratch-only converter built from its unchanged JSON/schema/grammar sources
converted the observed six-path action schema, 240-character boundary case and
Unicode/special-character paths without warnings. Initial draft escaping and
deep nesting produced converter warnings and were corrected before publication;
the final trie flattens four characters per group and uses supported class escapes.
This parser check and saved-step-51 exclusion are diagnostic checks, not model
inference, compiler repair or app acceptance.

Before publication: main still e697429; active/queued/waiting/pending run counts
were all zero. Public inventory contained 121 artifacts totaling 178928710 bytes,
none expired. No deletion was needed. Archive and billing settings were untouched;
historical archive storage remains unverified and cache writes remain disabled.

Final validation: 1194 tests plus 6 subtests passed in 97.37 seconds; the focused
new-file/recovery/completion suite passed 56 tests in 4.08 seconds. Ruff, whitespace,
static CI policy, pinned tracked-source Gitleaks and manual four-file publication
review passed. Publish with expected-head lease from e697429. Fresh actual-model
and platform CI results remain required; the old run did not test this fix.

### Fresh platform CI on 23688cc (2026-11-07)

Routine CI 42401331977 passed all nine jobs on exact
`23688cc12eeed7651a752c6243f8af38f2678c5a`. Browser reports 26 expected,
zero skipped, unexpected or flaky tests. Five original report ZIPs were
individually digest-verified and preserved as `dsGPT-ci-test-evidence-23688cc.zip`,
45457 bytes, SHA256
`51e2e4d69ee6587af7e5d30ff1d1d71605d8bfda57ece86831fbc8819f3c4c0a`,
durable evidence
`libfile_fde3_f-44fc4cb2d5008191b5fd12b1f7a7e5ed_0e1c3d7a1ce08191b900cc9270ea7257`.

Installed Windows native UI/local reply, Credential Manager, scheduled backend
restart, reinstall and data preservation passed. Android lifecycle/diagnostics
instrumentation reports OK (one test). Windows uses separate qwen3:1.7b; this is
not actual 9B complex-app acceptance or complete item 5. Staged inference BLOCKED
and production REVIEW labels remain. Owner hardware remains unverified.

Original-request actual 9B run 42401331943, job 128489520609, is still active on
this source. Pinned model loading and production Docker setup passed; unchanged
request model decisions are in progress. No generated-app completion is claimed.

### Actual-model runtime grammar failure on 23688cc (2026-11-07)

Original-request run 42401331943 failed on exact
`23688cc12eeed7651a752c6243f8af38f2678c5a` after initial step 9 scaffolded
Android. The next inference request failed with `runtime_unavailable`; Ollama's
log explicitly reports that repeated expanded grammar rules exceed its complexity
bound. No subsequent model action ran; generated native/follow-up jobs skipped.
Original artifact 13586197809 was digest-verified and preserved as
`dsGPT-complex-evidence-42401331943.zip`, 99269 bytes, SHA256
`eab278f7efd65039cc0569c742402eb52bf41b2e92fe575be8797b128fe2a312`,
durable evidence
`libfile_fde3_f-bbfb64527c3c819183e6b9f3f8db4fad_0e1c3d7a1ce08191b900cc9270ea7257`.

The previous schema-conversion check was insufficient: conversion passed, but
runtime grammar parsing failed. A local driver built against unchanged pinned
llama.cpp b11963 (`39febd2adb947b70da35e95f9351b3bf58ad170a`, selected by
Ollama v0.40.13) reproduced the same failure with the previous grammar. Optional
subtree groups exceeded the parser's expansion guard. Flatten path alternatives
so only individual characters repeat; keep exact existing-path exclusion, new
names, prefixes, neighboring names, Unicode, 240-character bounds and targeted
edits. Runtime validation and all model/request/context/output/loop/error limits
remain unchanged.

The corrected full scaffold schema and prior observed schema pass both conversion
and runtime parsing without warnings, as do maximum-length and special-character
cases. This is parser verification, not fresh actual-model acceptance. A regression
covers scaffold prefix/extension semantics and forbids repeating expanded groups.
Full suite: 1195 tests plus 6 subtests passed in 96.73 seconds. Eight focused
new-file tests, Ruff, whitespace and static CI policy passed. Pinned tracked-source
Gitleaks and manual four-file publication review passed. Publish with an expected-head
lease from 23688cc; fresh actual-model and CI results remain required.
Before dispatch: main remained 23688cc; in-progress/queued/waiting/pending counts
were all zero. Public inventory: 132 artifacts, 195168518 bytes, none expired.
No deletion was needed. Historical private storage remains unverified and untouched.

### Fresh platform CI on 329d140 (2026-11-07)

Routine CI 42403711351 passed all nine jobs on exact
`329d1409b955182d4b70f3b6c81d2adc62a9e8d3`. Browser reports 26 expected,
zero skipped, unexpected or flaky tests. Five original report ZIPs were
individually digest-verified and preserved as `dsGPT-ci-test-evidence-329d140.zip`,
45158 bytes, SHA256
`41b2309fbb17a61d1b9c012316e57704bcb66a4c8712666db68545c3c317020c`,
durable evidence
`libfile_fde3_f-cb7d6049d58c8191aa31047b6e8550ba_0e1c3d7a1ce08191b900cc9270ea7257`.

Installed Windows native UI/local reply, Credential Manager, scheduled backend
restart, reinstall and data preservation passed. Android lifecycle/diagnostics
instrumentation reports OK (one test). Windows uses separate qwen3:1.7b; this is
not actual 9B complex-app acceptance or complete item 5. Staged inference BLOCKED
and production REVIEW labels remain. Owner hardware remains unverified.

Original-request actual 9B run 42403711453, job 128496789437, is still active on
this source after exact model load and production Docker setup passed. Unchanged
request decisions are active; no generated-app completion is claimed.

### Candidate: bind guided edit paths to their current revisions

Prepared locally while actual-model run 42403711453 continues unchanged on
`329d1409b955182d4b70f3b6c81d2adc62a9e8d3`. This candidate is not part of that run.
The independent path/hash enums admitted the exact wrong-file hash from saved
run 42363614200 step 45. Per-path edit variants now exclude that combination and
retain the correct edit. Runtime compare-and-swap checks remain unchanged.

Three regressions cover distinct/shared hashes, Unicode, restricted selectable
paths, controller refresh, and a concurrent source change that must still reject
an already-generated stale edit. Focused revision/new-file suite: 11 passed.
Full backend suite: 1198 tests plus 6 subtests passed in 120.64 seconds.
Pinned unchanged llama.cpp b11963 conversion and runtime parsing passed observed,
maximum-length and special-character schemas with no warnings (50764, 62478 and
10025 rules respectively). Saved-action/schema replay and parser checks are not
actual-model acceptance. No model action, original request, budget, loop limit,
runtime validation, or native acceptance check was substituted or weakened.

### Actual 329d140 timeout and serialized path boundary recovery (2026-11-08)

Original-request actual 9B run 42403711453 completed with failure after initial
step 74 and 18000.359 seconds. The acceptance deadline raised TimeoutError:
"Acceptance budget reached; task paused without inventing completion". This was
not a no-progress stop. No build_project action occurred; generated native and
follow-up acceptance did not run. Steps 38 and 68 used a different file's hash for
MainActivity edits and were correctly rejected, confirming the prepared paired
path/revision schema addresses an observed failure in this run too.

Original artifact 13595529038 was digest-verified and preserved as
`dsGPT-complex-evidence-42403711453.zip`, 189093 bytes, SHA256
`e1993bd580546dd1a68a3d05aab6b501bb145f7db7f5dd539057936598322302`,
durable evidence
`libfile_fde3_f-58ace56275648191b2bbea2cc15d0c15_0e1c3d7a1ce08191b900cc9270ea7257`.

Existing-file writes at steps 11, 42 and 70 were also rejected at execution despite
the schema's intended exclusion. Investigation reproduced a concrete semantic
hole with unchanged production llama.cpp b11963: regex wildcards operate on raw
serialized JSON and can consume quotation marks. A response with path "new"
followed by a second path "foo.kt" is accepted by the old full action grammar,
then JSON decoding selects the existing file. Parsed saved actions include extra
fields; raw response text was not retained, so this reproduction does not prove
the exact serialization route used by those three actions.

Restrict both trie-divergence characters and remaining path characters to exclude
quotes, backslashes and ASCII controls. These are already rejected in file paths
at execution. Pinned production grammar semantic acceptance now rejects the
reproduced duplicate-path response and exact existing paths, while accepting
Unicode new paths and existing-name extensions. Six regressions cover serialized
field boundaries, escaped-path bypasses and controls. Runtime validation, model
choices, original request, context/output budgets, loop limits and acceptance
checks remain unchanged. Parser semantic checks are not actual-model acceptance.

Final combined validation: 1204 tests plus 6 subtests passed in 75.89 seconds;
17 focused new-file/revision tests passed. Pinned unchanged b11963 observed,
maximum-length and special-character schemas convert and parse without warnings.
Ruff, whitespace, static CI policy, pinned tracked-source Gitleaks and manual
five-file source/evidence review passed. No source, signing material or unique
artifact was deleted. Pre-dispatch main remained 329d140; all in-progress, queued,
waiting and pending counts were zero. Public inventory: 121 artifacts, 178980160
bytes, none expired. Historical private storage remains unverified and untouched.
Publish with an expected-head lease from 329d140, preserving candidate 1963113
as an ancestor. Fresh actual-model acceptance is still required.

### Fresh platform CI on d257834 (2026-11-08 UTC)

Routine CI 42428425166 passed all nine jobs on exact
`d257834ef65a180443fa2cba4582f503a8facff0`. Browser report: 26 expected,
zero skipped, unexpected or flaky tests. Five original report archives were
individually digest-verified and preserved as `dsGPT-ci-test-evidence-d257834.zip`,
45723 bytes, SHA256
`6128a30c9a75d5d6518ffc9231317e4c2fc256ff1697eb01880e562d5acd0b1f`,
durable evidence
`libfile_fde3_f-897f983fefe88191a47249b9b4409a74_0e1c3d7a1ce08191b900cc9270ea7257`.

Installed Windows native UI/local reply, Credential Manager, scheduled backend
restart, reinstall/data preservation and uninstall-preserves-data passed.
Android lifecycle/diagnostics instrumentation reports OK (one test).
Windows uses separate qwen3:1.7b, not the exact 9B complex-app acceptance or
complete item 5. Staged inference BLOCKED/production REVIEW labels remain;
owner hardware remains unverified.

Actual 9B run 42428425205, job 128571686556, remains in progress on this exact
source after pinned model loading and production Docker toolchain setup passed.
The unchanged original-request model decisions are active. No duplicate run was
started or canceled; no final complex-app result or release is claimed.

Live browser observation at 2026-11-08 01:41 UTC: actual run 42428425205
remained in initial model decisions through step 28. Progress categories recorded
write_file at 15 and edit_file at 19/23; no tool_error or validation_rejected was
shown through 28. These categories do not establish source correctness, compilation,
or native acceptance. Complete final evidence is still pending.

### Actual d257834 result and observed-source priority repair (2026-11-08 UTC)

Actual 9B run 42428425205 completed failure after initial step 42 in 7883.437
seconds (`no_progress`). Generated native and follow-up jobs were skipped; no
`build_project` action occurred. Step 29 created a distinct file whose name ends
in `MainActivity.kt}`. Steps 34–41 then cycled through that file, MainActivity,
Task and the manifest; step 42 requested MainActivity for the third unchanged
read. These were actual model actions, not compiler or native acceptance.

Original artifact 13599779272 was size/digest verified and preserved as
`dsGPT-complex-evidence-42428425205.zip`, 139837 bytes, SHA256
`9c84f207a3a4868b478e2bfca627ef335de5b61affd08d907b0651f47f255f82`,
durable evidence
`libfile_fde3_f-f4c8852bacbc81918b32e35431f24671_0e1c3d7a1ce08191b900cc9270ea7257`.

Replay through step 41 reconstructs saved original requirements, section notes,
the cumulative overview recovered from the review action, observed source bytes,
build target and bounded action history. Baseline retains three source files but
omits MainActivity: the generated overview consumes the space needed for that
page. An earlier replay without the saved overview incorrectly retained all four;
it was corrected before selecting the repair. This is diagnostic replay, not a
fresh model run or proof of generated application correctness.

The repair defers the generated overview with requirement navigation when needed
to retain observed source. Current-hash checks, bounded history, partial-page
handling, authoritative saved requirements and source edit tools are unchanged.
Corrected replay retains all four complete current source files at estimated
15829/16384 tokens including the unchanged 4096 output reserve. No model action,
generated implementation, request, model, context/output budget, loop limit,
runtime validation or acceptance check is substituted or relaxed.

Two regression cases cover overview/source competition and a changed source;
the unchanged-source case fails on baseline. Tight-context assertions verify that
omitted source remains readable and saved requirements remain byte-for-byte
unchanged. Focused source/edit grammar suites: 43 passed. Public inventory before
publication: 121 artifacts, 179001960 bytes, none expired; active, queued, waiting
and pending run counts all zero. No deletion needed. Prior private-archive
privacy/Actions disablement and account usage-blocking observations remain the
administrative baseline; historical private storage is still unverified/untouched.

Full suite: 1206 tests plus six subtests passed in 86.77 seconds. Ruff, whitespace,
CI policy and pinned tracked-source Gitleaks passed. Manual four-file review
confirmed the change only prioritizes displayed observed source over a generated
overview, with two regressions, preserved evidence notes and the narrow acceptance
request trigger. Fresh actual-model acceptance is required; item 1 remains open.

### Actual ebaeeb3 failure and partial-source read recovery (2026-11-08 UTC)

Actual 9B run 42440608986 failed initial step 17 with `no_progress` after
2337.177 seconds. Step 11 wrote a 3995-character Task module. Reads 13/15 returned
only its first 3000 characters, correctly reporting `has_more` and `next_offset`.
Edits 14/16 invented text around the page boundary and were rejected with zero
matches. Step 17 requested the unchanged first page a third time. No rejected
edit executed; no compiler or generated native/follow-up job ran.

Original artifact 13602721675: 107984 bytes, SHA256
`5a09b73bc075b8f7b82aab7e89adac982fec5e8576d69d371081e38639d87765`.
It and five routine-CI report ZIPs were individually size/digest checked and
preserved together in `dsGPT-evidence-ebaeeb3.zip`, 152756 bytes, SHA256
`3a30fef54f17b28be8b579c26825f263f16339495a0e2608f81a6c61fe131a81`,
durable evidence
`libfile_fde3_f-74f9f8bec270819193b810e73f2aaf63_0e1c3d7a1ce08191b900cc9270ea7257`.
Routine CI 42440608984 passed all nine jobs. Browser: 26 expected, zero
skipped/unexpected/flaky. Installed Windows UI/local reply, Credential Manager,
restart/reinstall/data preservation passed; Android lifecycle instrumentation
reports OK (one test). The separate qwen3:1.7b fixture is not actual 9B acceptance
or full item 5. Staged inference BLOCKED/production REVIEW labels remain;
owner hardware is unverified.

Recovery now retains the latest observed matching target page after an unmatched
edit rejection, within the same history/context bounds. Guided read grammar
excludes only exact offsets of displayed partial pages whose content, hash,
length and continuation match current saved source. Other offsets (including
next_offset), unseen files and edits remain available. Missing, stale, corrupt,
empty or omitted pages do not qualify. No full file is injected into the prompt;
current source is used only to verify displayed bytes. Edit feedback explicitly
explains page boundaries and continuation. Runtime validation is unchanged.

Saved-history replay through step 16 identifies the displayed Task offset 0 at
estimated 16364/16384 including the unchanged 4096 output reserve. This is
replay, not fresh actual-model acceptance. Eight regressions cover byte/hash
verification, omission, changed files, offset grammar, retained partial source,
rejected-edit atomicity and tight budgets. Focused suites: 51 passed. The unchanged
pinned b11963 converter/parser accepted the new schema without warnings; semantic
driver rejects observed offsets 0/30 and accepts unseen offset 3000. No model,
request, context/output/loop limits, generated actions or acceptance was replaced.
Public inventory: 121 artifacts, 178996249 bytes, zero expired. Active/queued/
waiting/pending runs all zero before publication; no deletion needed. Private
archive and billing settings remain unchanged; historical private storage unverified.

Full suite: 1214 tests plus six subtests passed in 79.69 seconds. Ruff, whitespace,
CI policy and pinned tracked-source Gitleaks passed. Manual five-file review
confirmed exact displayed-byte verification and preserved runtime limits. Publish
with an expected-head lease from ebaeeb3; fresh actual-model acceptance remains
required and all five-item release gates remain in force.

### Routine platform evidence on 187ab3d (2026-11-08 UTC)

Routine CI 42445714392 passed all nine jobs on exact
187ab3d23bbec7b916d0637dbc0d58f1efd6c331. Browser report: 26 expected,
zero skipped/unexpected/flaky. Backend report: 1220 cases, zero errors/failures/
skips. Windows installed native UI/local reply, Credential Manager, scheduled
restart, reinstall and data preservation passed. Android lifecycle instrumentation
reports OK (one test). The separate qwen3:1.7b fixture is not actual 9B acceptance
or complete item 5. Staged inference BLOCKED/production REVIEW remain; physical
owner hardware is unverified.

Five original report ZIPs were individually size/digest verified and preserved in
`dsGPT-ci-test-evidence-187ab3d.zip`, 45392 bytes, SHA256
`eec38d40f7c42f1be1155ddb0554021ba363f33c0828030802ad7c8ece29334b`,
durable evidence
`libfile_fde3_f-58812d5824a88191b614ed74c647282b_0e1c3d7a1ce08191b900cc9270ea7257`.
Actual 9B run 42445714304, job 128624081250, remains in progress on this exact
source after pinned model load and production Docker setup passed. Its unchanged
request decision step is active; no final model acceptance is claimed. No duplicate
run was dispatched and no active run was cancelled.

### Actual 187ab3d failure and source/requirement comparison recovery

Actual 9B run 42445714304 failed initial step 46 with `no_progress` in
7760.025 seconds. Requirement 1 offset 0 reads at 40/42 were separated by
source inspection; reads 43–45 paged MainActivity at 0/3000/6000. Step 46
requested the same unchanged requirement page a third time. No build_project
occurred; generated native/follow-up jobs skipped. Earlier edit 27 was rejected
as unchanged. No rejected edit was executed.

Original artifact 13607162584, 149075 bytes, SHA256
`b121bb9faccf49a47185aa614c5939024b1506ff2ef8ddce95d4c4d94e73dcf8`,
verified and durably preserved as `dsGPT-complex-evidence-42445714304.zip`,
`libfile_fde3_f-4ca99705523c8191a5598092ede64a2b_0e1c3d7a1ce08191b900cc9270ea7257`.

Source reads now retain the latest verified observed requirement page from the
existing bounded history when it fits. Generated overview/section previews may
be deferred with navigation; older retained pages of unrelated files may be
omitted to fit the exact comparison. Latest tool result and retained pages of
its target stay intact. Omitted source remains readable. Missing/corrupt/stale
requirements do not qualify. Runtime checks, model, original request, context,
output reserve, loop limits and acceptance remain unchanged.

Saved-history diagnostic through step 45 reconstructs hash-verified scaffold
files, successful edits, saved section notes and cumulative overview. Baseline
shows no retained requirement at estimated 16103 tokens including output reserve;
candidate retains section 1 offset 0 through 1359 at 15605/16384, including the
unchanged 4096 reserve. This is diagnostic replay, not model acceptance.
Four regressions cover verified comparison, corrupt/stale text, omitted text and
budget-driven unrelated-source omission while retaining latest source result.
Public storage before publication: 99 artifacts, 146510050 bytes, none expired;
active/queued/waiting/pending counts all zero. No deletion needed. Private archive,
billing and cache settings remain unchanged; historical private storage unverified.

Final full suite: 1218 tests plus six subtests passed in 81.80 seconds. Focused
comparison/source/requirement suite: 62 passed. Ruff, whitespace, CI policy and
pinned tracked-source Gitleaks passed. Manual four-file review confirmed observed
text only, unchanged runtime enforcement, preserved evidence and narrow dispatch.
No action schema or grammar syntax changed. Fresh actual-model acceptance required.

### Routine platform evidence on 3ec2706 (2026-11-08 UTC)

Routine CI 42462245444 passed all nine jobs on exact
3ec270678e0dd57231ee02cf9c66e1b6345b779c. Browser report: 26 expected,
zero skipped/unexpected/flaky. Backend report: 1224 cases, zero errors/failures/
skips. Windows installed native UI/local reply, Credential Manager, scheduled
restart, reinstall and data preservation passed. Android lifecycle instrumentation
reports OK (one test). The separate qwen3:1.7b fixture is not actual 9B acceptance
or complete item 5. Staged inference BLOCKED/production REVIEW remain; physical
owner hardware is unverified.

Five original report ZIPs were individually size/digest verified and preserved in
`dsGPT-ci-test-evidence-3ec2706.zip`, 46060 bytes, SHA256
`00251104aa5267bdad12fc00b38fce9f11e808f1c23a1c8aaa38250a15c5ebaf`,
durable evidence
`libfile_fde3_f-da718cfb93708191b0f9f403f04e7972_0e1c3d7a1ce08191b900cc9270ea7257`.
Actual 9B run 42462245456, job 128673835688, remains in progress on this exact
source after pinned model load and production Docker setup passed. Its unchanged
request decision step is active; no final model acceptance is claimed. No duplicate
run was dispatched and no active run was cancelled. These notes do not alter the
source under acceptance; the ordered release gates remain in force.

### Actual 3ec2706 failure and same-file page retention

Actual 9B run 42462245456 failed initial step 25 with no_progress in
5177.197 seconds. Step 21 edit_match_not_unique rejected invented source;
22 read TaskLedger.kt offset 0, 23 read distinct TaskLedger.kt} offset 0,
24 read TaskLedger.kt offset 3000, then 25 repeated its unchanged offset 0.
No build_project occurred; generated native/follow-up jobs skipped.
Original artifact 13612143009, 118130 bytes, SHA256
`bbc78f34aeaf7b40c990fc6594ac59efb1ae24df81e18a7fde60a1a72f60d5bd`
is verified and durably preserved as dsGPT-complex-evidence-42462245456.zip,
`libfile_fde3_f-94f824914aa88191b069aa0d113b8082_0e1c3d7a1ce08191b900cc9270ea7257`.

Saved-state replay through step 24 reconstructs verified scaffold, successful
writes/edits, section notes and cumulative overview. Baseline retained the newer
unrelated TaskLedger.kt} page at estimated 15356/16384 including output reserve,
omitting the target prefix. Candidate prioritizes observed pages matching the
latest source result before unrelated pages, preserving recency within each group.
It retains TaskLedger.kt offset 0 at 15335/16384 including unchanged 4096 reserve.
Latest continuation stays intact. Current-hash checks and runtime enforcement are
unchanged; stale/omitted pages remain readable. This is replay, not model acceptance.
Two regressions exercise constrained retention and stale-prefix exclusion.
No grammar syntax, model, original request, context/output or loop limits changed.
Public inventory: 99 artifacts, 146513826 bytes, none expired; active/queued/waiting/
pending all zero. No deletion needed; private archive/billing/cache settings untouched.

Full suite: 1220 tests plus six subtests passed in 82.92 seconds. Focused source
retention/grammar/comparison suite: 14 passed in 1.87 seconds. Ruff, whitespace,
CI policy and pinned tracked-source Gitleaks passed. Manual four-file review
confirmed observed source only, unchanged validation and acceptance, preserved
prior notes and the narrow single-run trigger. Fresh model acceptance is required.

### 854e7f4 setup failures before model execution

Actual run 42470474691 failed during pinned Ollama archive download with HTTP504.
No application model decisions, Docker builds or generated native checks ran.
Routine CI 42470474829 failed source-audit on the Gitleaks download HTTP504 and
Android on the Gradle distribution download's 10000ms read timeout. Backend,
browser, frontend and Windows native compilation passed; downstream Windows and
Android runtime acceptance skipped. Backend: 1226 cases, zero failures/errors/skips;
browser: 26 expected, zero skipped/flaky/unexpected. These are setup failures,
not evidence that the source-retention fix passed or failed actual-model acceptance.

Original model artifact 13612818207, 4878 bytes, SHA256
`c2c6a0c21bc239e7ac0652bae1d936036b2cbde6313271ecf944dfccf64b0067`;
two original test ZIPs individually size/digest verified and three failed-job logs
preserved in `dsGPT-setup-evidence-854e7f4.zip`, 54925 bytes, SHA256
`701326393d990d023323cfe948ef89f233c3e9cc7f9d8fcb76788cf759cbd0bb`,
durable evidence
`libfile_fde3_f-3603364687ac8191ac3d09d46775b3d1_0e1c3d7a1ce08191b900cc9270ea7257`.

Pinned runtime/scanner archive opens now retry HTTP502/503/504 only, at most three
attempts with 1/2-second backoff before writing any bytes. Other HTTP errors,
stream failures, sizes and digest mismatches remain fatal. Gradle's distribution
network timeout is 60000ms; its URL and pinned checksum remain unchanged. No model,
request, inference budgets, loop limits, acceptance timeouts or cache writes change.
Focused download/preflight suite: 20 passed; retries and exhaustion tested without
network or sleeping. This does not count as actual-model acceptance.

Full suite: 1222 tests plus six subtests passed in 78.72 seconds. Ruff, whitespace,
CI policy and pinned tracked-source Gitleaks passed. Manual six-file review kept
all digest/size checks and acceptance arguments intact. Public inventory before
publication: 94 artifacts, 135828053 bytes, none expired; active/queued/waiting/
pending all zero. No deletion needed. Archive/billing/cache settings untouched.

### 0c5859f production-toolchain setup failure

Actual 9B run 42473436414 failed production Docker setup before application model
execution. The pinned exact-model load and cold-load preflight passed. SDK/Gradle
and voice inputs downloaded successfully, then apktool's response-open operation
raised TimeoutError after the existing 120-second socket timeout. No model task,
build_project, generated native or follow-up acceptance ran. This is setup failure,
not evidence for or against the source-page retention fix.

Original artifact 13614622341, 64631 bytes, SHA256
`f531cd78c8dd27132b8fae3ed9b3baf8e3feb4c0452ad27d0518e0ee2b25e3ed`.
It and five original CI report ZIPs were individually size/digest verified and
preserved in `dsGPT-evidence-0c5859f.zip`, 110494 bytes, SHA256
`b91b2f65d7d1046e2b01997c05e39108b195c5e8156be21c91fa37473049f6ba`,
durable evidence
`libfile_fde3_f-867568cb63248191800714dee2a17711_0e1c3d7a1ce08191b900cc9270ea7257`.

Routine CI 42473436405 passed all nine jobs on exact
0c5859f811001d9814c6190395e0e39360e184a3. Backend: 1228 cases, zero failures,
errors or skips; browser: 26 expected, zero skipped/unexpected/flaky. Windows
installed native UI/local reply, Credential Manager, scheduled restart, reinstall
and data preservation passed; Android lifecycle instrumentation reports OK (one
test). The separate qwen3:1.7b fixture is not actual 9B acceptance or complete
item 5. Staged inference BLOCKED/production REVIEW remain; owner hardware unverified.

Asset response opens now retry direct or wrapped TimeoutError and HTTP502/503/504
at most three times, with 1/2-second backoff. The 120-second timeout, URLs, pinned
sizes/digests and extraction checks remain unchanged. Other open errors, stream
failures and integrity failures remain fatal. Regressions cover recovery,
exhaustion, permanent errors, retries before file creation, successful verified
installation, partial streams, size and digest rejection. Focused asset/release
suite: 11 passed. No model/request/context/output/loop/acceptance limit changed;
no cache writes added. Fresh actual-model acceptance is still required.

Full suite: 1231 tests plus six subtests passed in 81.81 seconds. Ruff, whitespace,
CI policy and pinned tracked-source Gitleaks passed. Manual four-file review
confirmed bounded response-open retries only, unchanged integrity enforcement,
no private log contents in source, and the unchanged-request single-run trigger.
Before publication: active/queued/waiting/pending all zero; 105 public artifacts,
152035174 bytes, none expired. No deletion needed. Private archive, billing and
cache settings remain untouched.

### 954004d observed alternating requirement reads

Actual 9B run 42476228169 passed exact-model and production Docker setup, then
failed initial step 27 with no_progress in 4468.404 seconds. Requirement section 4
was read at steps 22/25 and section 1 at 24/26; step 27 repeated section 4 a third
time. No build_project occurred; generated native/follow-up checks skipped.
Step 18 also wrote a distinct MainActivity.kt} path; step 20 invalid path was
rejected. Those observations do not prove complete source correctness.

Original artifact 13618077583, 126366 bytes, SHA256
`fea1d52fe05ce967eb668bbf15342f37479b0875738bf9366695c38c9aa8856d`;
original plus two CI report ZIPs individually size/digest verified and Android
failure log preserved in dsGPT-evidence-954004d.zip, 158273 bytes, SHA256
`6b2d0d114b0c77a296a96e315b6bc4b6c2c0aad404c5ba54fe1c44bb79ab0ccb`,
durable evidence
`libfile_fde3_f-f0d1fed9f2508191bf668ee428c8d57e_0e1c3d7a1ce08191b900cc9270ea7257`.
Routine CI 42476228144 failed Android on Gradle distribution HTTP502, before
compilation; required failed and downstream Windows/Android runtime skipped.
Source audit/backend/browser/frontend/Windows native compilation passed.

Section comparisons now retain the latest verified observed different section
from bounded history when it fits, deferring generated overview/preview as needed.
Empty reads retain the existing same-section recovery behavior. Corrupt/stale
observations remain unreadable as evidence, and latest result stays intact.
Saved-history replay through step 26 includes hash-verified scaffold, successful
edits and cumulative overview: baseline only section 1 at 15884/16384; candidate
also retains section 4 at 15433/16384 including unchanged 4096 output reserve.
Replay is diagnostic, not actual-model acceptance. Model/request/context/output/
loop/runtime checks and grammar syntax are unchanged. No cache writes added.

Final full suite: 1233 tests plus six subtests passed in 81.11 seconds; focused
comparison/requirement/read suite: 64 passed. An initial candidate broke existing
beyond-EOF recovery; corrected before publication, with that assertion unchanged.
Ruff, whitespace, CI policy and pinned tracked-source Gitleaks passed. Manual
four-file review verified observed-text-only retention and unchanged acceptance.
Routine evidence: 1237 backend cases with no failures/errors/skips; 26 browser
expected with zero skipped/unexpected/flaky. Before publication all active/queued/
pending/waiting counts were zero; 111 public artifacts, 157771249 bytes, none
expired. No deletion needed; archive/billing/cache settings untouched.

### Routine platform evidence on 83cd085 (2026-11-08 UTC)

Routine CI 42483782726 passed all nine jobs on exact
83cd085c47022d2113b5e001c942108978e232e5. Backend: 1239 cases, zero failures,
errors or skips; browser: 26 expected, zero skipped/unexpected/flaky. Windows
installed native UI/local reply, Credential Manager, scheduled restart, reinstall
and data preservation passed. Android lifecycle instrumentation reports OK (one
test). Separate qwen3:1.7b fixture evidence is not actual 9B acceptance or complete
item 5. Staged inference BLOCKED/production REVIEW remain; owner hardware unverified.

Five original report ZIPs individually size/digest verified and preserved as
`dsGPT-ci-test-evidence-83cd085.zip`, 45694 bytes, SHA256
`a3310d2bcc4fbe36ed20bb5b4bb15310c1a822fbc6a4c749d73ce80ecc00c755`,
durable evidence
`libfile_fde3_f-b62f29b798c0819191ea718b7aece3df_0e1c3d7a1ce08191b900cc9270ea7257`.
At this platform checkpoint, actual 9B run 42483782694, job 128741133081, was
in progress after exact-model load and production Docker setup passed.
No final model acceptance is claimed. No duplicate or cancelled run; no source,
acceptance, private archive, billing or cache settings changed.


### 83cd085 observed no-change edit and partial read cycle

Actual 9B run 42483782694 completed with failure at initial step 68, no_progress,
in 16699.114 seconds. Exact-model and production Docker setup passed. Step 21
attempted build_project and failed Kotlin compilation (including redeclaration
and unresolved references). Step 25 invoked Gradle directly and failed loading
its native library; the model read that failure at step 26. Neither result is a
successful application build. Generated native checks and follow-up skipped.

At step 61 the model changed Task.kt to 3170 characters. Reads 64/66 returned
its first 3000 characters with next_offset 3000. Edits 65/67 supplied identical
old/new text and were rejected as edit_has_no_change, with that same current
source page attached. Step 68 repeated the unchanged first-page read and stopped.
Other generated source issues remain unverified; this diagnosis does not claim
that the model's implementation satisfies the requested domain API or behavior.

Original artifact 13627549482, 202831 bytes, SHA256
`a3ac5aead117d89359579541427b6b57c578df4d6fa1b93cbeefbcda7a4bbc09`,
size/digest verified and preserved as `dsGPT-complex-evidence-42483782694.zip`,
durable evidence
`libfile_fde3_f-fb0063ed7cb88191a667c581983e5ee1_0e1c3d7a1ce08191b900cc9270ea7257`.

Partial-page guidance now recognizes the exact page attached to a recorded
no-change edit when the adjacent action is edit_file for that same path. All
existing byte/hash/length/offset/continuation checks remain required. Other
errors, mismatched actions and stale/corrupt/omitted text remain readable.
Unseen offsets and edits remain available. No grammar syntax, runtime validation,
model, original request, context/output budgets, loop limits or acceptance changes.

Saved-history replay through step 67 reconstructed hash-verified scaffold and
successful edits, including saved notes and cumulative overview. Both prompts
use estimated 16045/16384 including unchanged 4096 output reserve. Baseline
recognizes no displayed partial page after the no-change edit; candidate recognizes
Task.kt offset 0 and leaves offset 3000 available. Replay is diagnostic only,
not actual-model acceptance. Focused source/read/feedback tests: 88 passed.

Final full suite: 1242 tests plus six subtests passed in 81.33 seconds. Ruff,
whitespace, CI policy and pinned tracked-source Gitleaks passed. Manual four-file
review confirmed the matching-action and current-source checks, preserved prior
platform evidence and unchanged acceptance trigger. Before publication all
active/queued/waiting/pending counts were zero; 100 public artifacts, 141552045
bytes, none expired. No deletion needed. Archive/billing/cache settings untouched.

### Routine platform evidence on 92187c7 (2026-11-08 UTC)

Routine CI 42507901096 passed all nine jobs on exact
92187c7ebca2c7be136785116ddeb9c61e9d7e26. Backend: 1248 cases, no failures,
errors or skips. Browser: 26 expected, zero skipped/unexpected/flaky. Installed
Windows native UI/local reply, Credential Manager, scheduled restart, reinstall
and data preservation passed. Android lifecycle instrumentation: OK (one test).
Separate qwen3:1.7b fixture evidence is not actual 9B acceptance or complete item 5.
Staged inference BLOCKED/production REVIEW remain; owner hardware unverified.

Five original report ZIPs individually size/digest verified and preserved as
`dsGPT-ci-test-evidence-92187c7.zip`, 46276 bytes, SHA256
`32e884bd081297777bd2ab3d4f0e6d1fa4060898efb4266b1c2bad09c454f69d`,
durable evidence
`libfile_fde3_f-fc37d0395100819187b53c178d5def9b_0e1c3d7a1ce08191b900cc9270ea7257`.
Actual 9B run 42507901320, job 128814418461, remains in progress after exact-model
load and production Docker setup passed, with original-request decisions active.
No final model acceptance claimed. No duplicate/cancelled run or source, acceptance,
private archive, billing or cache changes.

### Actual-model failure and rejected-edit context recovery (2026-11-08 UTC)

Run 42507901320 on exact 92187c7 completed with initial task no_progress at
step 50 after 9935.173 seconds. Exact model and production Docker setup passed.
Step 24 build_project failed Kotlin compilation. Subsequent edits did not produce
another build. Step 45 changed a lambda type annotation, step 47 reverted it;
reads 44 and 48 therefore observed the same source again. Step 49 proposed an
unmatched unchanged replacement (zero matches); step 50 repeated that read and
correctly hit the existing loop guard. Generated native and follow-up jobs skipped.
No item 1 acceptance, deliverable correctness, or item 5 completion is claimed.

Original artifact 13633424454 verified at 168971 bytes, SHA256
`24e2bacef01bb456b0ea4a4f08c1bf9c1c05a60c982c1026dd13dbc75e2dc026`,
preserved as `dsGPT-complex-evidence-42507901320.zip`, durable evidence
`libfile_fde3_f-7bb2faea6c4481919ecd883040f8e39a_0e1c3d7a1ce08191b900cc9270ea7257`.

The bounded rejection prompt could omit the latest observed exact source while
retaining generated requirement overview/preview. Add a fallback that defers that
preview when necessary to fit the source and rejection feedback together. Current
hash and observed-page checks, latest result, source bytes and full saved requirements
remain intact. No model/request/runtime/context/output/loop/grammar/acceptance changes.
An initial candidate removing rejected proposal text was discarded: a replay missing
build state and session summary did not reproduce the actual pressure.

Corrected saved-history replay through 49 reconstructs verified scaffold/edits,
review notes/overview, recorded failed build and latest session summary. Baseline
omits the source at 16331/16384 estimated tokens including 4096 output reserve;
candidate retains complete MainActivity.kt at 15745/16384 (before wording cleanup).
Replay is diagnostic only. Regression test fails on baseline and passes with the
fallback; stale observed source remains rejected. Focused feedback/source tests:
50 passed. Before publication, active/queued/waiting/pending all zero; 89 public
artifacts, 125295382 bytes, none expired. No deletion needed. Archive, billing and
cache settings untouched.

Final full suite: 1244 tests plus six subtests passed in 86.19 seconds. Ruff,
whitespace, CI policy and pinned tracked-source Gitleaks passed. Manual four-file
review passed. Final replay remains 15745/16384 including output reserve. Original
request and all runtime/model/acceptance limits remain unchanged.

## c74fa73 platform evidence and actual-model outcome

Routine CI 42528136497 passed all nine jobs on exact c74fa73. Backend: 1250 cases
including subtests, no failures/errors/skips; browser: 26 expected, no flaky,
skipped or unexpected results. Windows regressions: 139 cases, no failures/errors,
one POSIX-only fixture skip with separate Windows CLI acceptance. Disposable
Windows installed UI/local reply/Credential Manager/scheduled restart/reinstall/data
preservation and Android lifecycle instrumentation (OK, one test) passed. Separate
qwen3:1.7b fixture is not actual9B acceptance or complete item 5; staged inference
BLOCKED/production REVIEW and owner-hardware unverified limitations remain.
Five individually verified report ZIPs were preserved in dsGPT-ci-test-evidence-c74fa73.zip,
46806 bytes, SHA256 4aa0c60b9b9d8fbfe11128943a16e1c96956ab764efb52a0a0fe11fd5b535bb1.
These notes reconstruct the prior uncommitted platform evidence after workspace
maintenance removed the checkout; committed source was recovered from public main.

Actual9B run 42528136541 passed pinned model and production Docker setup, then
failed initial step 58 with no_progress after 9695.123 seconds. No build_project
occurred; native checks and follow-up were skipped. Steps 53/56 read section 3;
55/57 read section 1; step 58 attempted section 3 again. Earlier malformed-looking
but distinct source paths were created; generated source remains unverified.
Original artifact 13641623457 was verified and durably preserved as
 dsGPT-complex-evidence-42528136541.zip (171141 bytes), SHA256
99653f83535f0fe6cd48a2ce090431566f3db114f2e676c56709803617e6e485.

A hash-checked diagnostic replay through step 57 restored scaffold bytes and edits,
recorded review notes, cumulative overview and latest session summary. Baseline
already retained section 3 (offset 0, 1506 characters) alongside latest section 1,
at 16322/16384 estimated tokens including 4096 output reserve. This was not another
missing-section defect: EOF guidance suggested starting any other section despite
visible retained text. Candidate guidance instead reuses retained pages and reads
another section only for missing text. Candidate replay retains section 3 and the
observed section 1 EOF receipt at 16343/16384. Replay is diagnostic, not acceptance.
Model, original request, grammar syntax and all runtime/context/output/loop/native
acceptance limits remain unchanged. Focused requirement checks: 24 passed.
Full suite: 1244 tests plus six subtests passed in 80.72 seconds. Ruff, whitespace,
static CI policy and pinned tracked-source Gitleaks passed; manual four-file review
found no private data or acceptance changes. Before dispatch: active, queued,
waiting and pending all zero; 89 public artifacts, 125329318 bytes, none expired.
Local disk has 50 GiB available; no artifact deletion needed. Private archive,
billing, cache settings and signing material remain untouched.

## e4b6860 routine platform evidence

CI 42545441117 passed all nine jobs on exact e4b68603e17678497d745f7e622474f27bd919cd.
Backend: 1250 cases including subtests, no failures/errors/skips. Browser: 26
expected, zero flaky/skipped/unexpected. Windows regressions: 139 cases, zero
failures/errors and one POSIX fixture skip; separate Windows CLI acceptance passed.
Android unit tests: 24 cases, zero failures/errors/skips. Android lifecycle
instrumentation: OK (one test). Disposable Windows installed native UI, local
reply, Credential Manager, scheduled restart, reinstall/data preservation and
uninstall preserving data all passed. Separate qwen3:1.7b fixture is not actual9B
acceptance or complete item 5. Staged inference remains BLOCKED, production REVIEW;
physical owner hardware remains unverified.
Five report ZIPs individually verified against GitHub size/digest/source commit
were preserved in dsGPT-ci-test-evidence-e4b6860.zip, 45990 bytes, SHA256
4a1a4f3de0b1646f4693f37394fb3af5e0b17a10e1a42f342b3f96c491b04b4b.
Actual9B run 42545441112, job 128929305804, remains in progress after exact model
and production Docker setup succeeded. No final actual-model artifact yet; no
additional acceptance run dispatched or cancelled.

## e4b6860 actual-model failure and path-error guidance

Actual9B run 42545441112 passed pinned model and production Docker setup, then
failed initial step 26 with no_progress after 4916.596 seconds. No build_project
occurred; generated native checks and follow-up were skipped. Rejected writes
used paths with appended formatting or trailing whitespace. Steps 21/24 read
section 2 at EOF (offset 869); step 26 attempted the same empty page again.
Step 22 had read the unchanged scaffold source; no generated implementation was
verified. Original artifact 13645694988 was size/digest checked and durably
preserved as dsGPT-complex-evidence-42545441112.zip (128029 bytes), SHA256
2bdbc194c7122e7b56924f41b9b6653cfb9a426b7730793d7ab44b8f5cdbdf41.

The validation result identified invalid_project_path, but next-step guidance
emphasized incomplete JSON. Candidate guidance specifically directs copying the
observed path without appended formatting, using edit_file for existing files,
and distinguishes requirement text from source old_text. It neither repairs nor
executes rejected actions. Path validation, grammar, model, original request,
runtime/context/output budgets, loop limits and acceptance remain unchanged.
Two regression cases fail on baseline and pass candidate; focused suite: 35 passed.
Hash-checked saved-history replay through step 25 reconstructs scaffold, actions,
review notes, cumulative overview and latest valid session summary. Baseline and
candidate both retain the exact source and requirement section 2 at offset 0.
Baseline uses 15864/16384 estimated tokens including 4096 output reserve; candidate
uses 15924. Replay is diagnostic only, not actual-model acceptance.
Full suite: 1246 tests plus six subtests passed in 82.37 seconds. Ruff, whitespace,
static CI policy and pinned tracked-source Gitleaks passed. Manual four-file review
found no private material or changed acceptance. Before retry: active, queued,
waiting and pending all zero; 89 artifacts, 125350642 bytes, none expired. No
artifact deletion needed. Archive settings, billing and signing remain untouched.

## 554fd34 routine platform evidence

CI 42556287281 passed all nine jobs on exact 554fd34d47359fcb657bb2ed4a08fbe24a67c22e.
Backend: 1252 cases including subtests, no failures/errors/skips. Browser: 26
expected, zero flaky/skipped/unexpected. Windows regressions: 139 cases, zero
failures/errors and one POSIX fixture skip; separate Windows CLI acceptance passed.
Android unit tests: 24 cases, zero failures/errors/skips. Android lifecycle
instrumentation: OK (one test). Disposable Windows installed native UI, local
reply, Credential Manager, scheduled restart, reinstall/data preservation and
uninstall preserving data all passed. Separate qwen3:1.7b fixture is not actual9B
acceptance or complete item 5. Staged inference remains BLOCKED, production REVIEW;
physical owner hardware remains unverified.
Five report ZIPs individually verified against GitHub size/digest/source commit
were preserved in dsGPT-ci-test-evidence-554fd34.zip, 46701 bytes, SHA256
28c6277afdce7dce4a43190b9054512e083937399a4d00fd6a2458a899189539.
Actual9B run 42556287336, job 128962614111, remains in progress after exact model
and production Docker setup succeeded. No final actual-model artifact yet; no
additional acceptance run dispatched or cancelled.

## Exact-model run 42556287336 and source-comparison retention (2026-11-09)

- Source `554fd34d47359fcb657bb2ed4a08fbe24a67c22e`: pinned exact-model load
  and production Docker setup passed. The unchanged original request failed at
  initial step 53 with `no_progress` after 12497.692 seconds. Step 36 failed Kotlin
  compilation; there was no subsequent build. Steps 40/45 changed then reverted
  source; 49 proposed identical old/new text and was rejected. Reads 46/51/53
  repeated the unchanged Task source, separated by other reads. Native and
  follow-up acceptance were skipped; generated code remains incorrect/unverified.
- Original artifact 13655022715: 167018 bytes, SHA-256
  `d31966091ec742e6dac56f6dd58dafd65918e32a59f1e68cc61b257d6fb4e7e1`.
  The original ZIP was verified and durably preserved without publishing raw logs.
- Hash-checked diagnostic replay through step 52 reconstructs scaffold, edits,
  reviewed requirements, latest summary and the failed execution snapshot. Baseline
  retains the compiler diagnostic but drops previously inspected Task source while
  adding an older requirement page during a different source-file read. Candidate
  prevents that eviction during source inspection; requirement-comparison reads
  retain their existing behavior. Exact Task source and latest MainActivity source
  fit at 16025/16384 estimated tokens including the 4096 output reserve, versus
  baseline 16177 with Task omitted. This replay is diagnostic, not actual acceptance.
- The focused regression fails on baseline and passes candidate. Existing hash
  validation, original request, grammar, model, runtime/context/output/loop limits
  and acceptance checks are unchanged. No generated action or source is substituted.
- Updated the prior eviction-expectation regression to require exact comparison
  source retention across context sizes. This changes prompt-selection behavior,
  not generated-application acceptance; corruption/staleness checks remain intact.
- Before retry: active, queued, waiting and pending runs all zero; 89 public
  artifacts total 125371039 bytes, none expired. No deletion was needed. Archive,
  billing, signing and cache settings were untouched.
- Final validation: 1247 tests plus six subtests passed in 88.11 seconds; focused
  diagnostic/source/invalid-feedback checks passed. Ruff, whitespace, static CI
  policy, pinned tracked-source Gitleaks and manual five-file privacy review passed.

## 0b5ba9c routine platform evidence

CI 42584930443 passed all nine jobs on exact 0b5ba9c9325d798c29bc3d096203d05853f83c84.
Backend: 1253 cases including subtests, no failures/errors/skips. Browser: 26
expected, zero flaky/skipped/unexpected. Windows regressions: 139 cases, zero
failures/errors and one POSIX fixture skip; separate Windows CLI acceptance passed.
Android unit tests: 24 cases, zero failures/errors/skips. Android lifecycle
instrumentation: OK (one test). Disposable Windows installed native UI, local
reply, Credential Manager, scheduled restart, reinstall/data preservation and
uninstall preserving data all passed. Separate qwen3:1.7b fixture is not actual9B
acceptance or complete item 5. Staged inference remains BLOCKED, production REVIEW;
physical owner hardware remains unverified.
Five report ZIPs individually verified against GitHub size/digest/source commit
were preserved in dsGPT-ci-test-evidence-0b5ba9c.zip, 45941 bytes, SHA256
bd41a0afed97319cf863b9f98b26afe1ebaa7a76a5507e13b2e68e0a16740d2f.
Actual9B run 42584930569, job 129052364526, remains in progress after exact model
and production Docker setup succeeded. No final actual-model artifact yet; no
additional acceptance run dispatched or cancelled.

## 0b5ba9c actual-model outcome and section-end guidance

- Actual9B run 42584930569 completed with initial step 28 `no_progress` after
  5398.587 seconds. Pinned exact-model load and production Docker setup passed.
  No build_project action occurred; generated native and follow-up checks skipped.
- Section 7 offset 0 returned all 1596 characters at step 20 with has_more=false
  and next_offset=null. Steps 21/24/28 nevertheless requested offset 1596, returning
  empty text; the third unchanged read stopped. Steps 22/23 inspected DataStore
  pages; steps 25/26 inspected section 8 suffix/end; step 27 read section 7 offset
  15. Generated source remains incorrect/unverified, with no compilation evidence.
- Original artifact 13663827518 was size/digest verified and durably preserved as
  dsGPT-complex-evidence-42584930569.zip, 121903 bytes, SHA256
  40e1df4336458ca76145595c243f947ef6de33c687eb283e5f89345accf9fcb5.
- Section-end feedback now explicitly identifies next_offset=null as no next page
  and explains that using total_characters as the next offset returns empty text.
  It distinguishes reaching the end from having inspected an earlier prefix.
  No automatic action repair, generated source substitution or acceptance change.
- Three new prompt cases cover full-page, suffix and empty EOF results. They fail
  baseline and pass candidate while preserving exact returned text and budget.
  Nine source/requirement comparison cases passed. Hash-checked saved-history replay
  through step 27 reconstructs scaffold, edits, review notes and latest summary.
  Both versions retain inspected DataStore source and the latest section 7 suffix;
  baseline uses 16155 and candidate 16372 of 16384 estimated tokens, including the
  unchanged 4096 output reserve. Replay is diagnostic only, not model acceptance.
- Before dispatch: in_progress/queued/waiting/pending all zero; 83 public artifacts
  total 119761461 bytes, none expired. No deletion needed. Private archive, signing,
  billing and cache settings untouched. Prior routine platform notes preserved.
- Final local validation: 1250 tests plus six subtests passed in 86.07 seconds.
  Ruff, whitespace and static CI policy passed; pinned tracked-source Gitleaks
  passed. Manual four-file review found only guidance/tests, public evidence notes
  and the narrow acceptance request trigger. Model/grammar/runtime/request/context/
  output/loop limits and all generated-application acceptance checks are unchanged.

## 49ab25f routine platform evidence

CI 42601516729 passed all nine jobs on exact
49ab25f0b441510f271fc5191402b655cb5dee84. Backend: 1256 cases including
subtests, no failures/errors/skips. Browser: 26 expected, zero flaky/skipped/
unexpected. Windows regressions: 139 cases, zero failures/errors, one POSIX
fixture skip. Android: 24 unit cases, no failures/errors/skips; lifecycle
instrumentation OK (one test, 5.493 seconds).
Disposable Windows installed native UI, local reply, Credential Manager,
scheduled restart, reinstall/data preservation and uninstall preserving data
passed. Separate qwen3:1.7b fixture is not actual9B acceptance or complete item 5.
Staged inference remains BLOCKED and production REVIEW; physical owner hardware
remains unverified.
Five report ZIPs were individually checked against GitHub size/digest and exact
source commit, then durably preserved as dsGPT-ci-test-evidence-49ab25f.zip,
46685 bytes, SHA256
0d89d386ea8f20cca0fd08f48b288fca4f06ba2c56e14c0b724981b5f8a452a5.
Actual9B run 42601516703, job 129106880481, remains in progress after pinned
model load and production Docker setup passed. No duplicate run dispatched,
cancelled or substituted; no item 1 completion claim.

## 49ab25f actual-model outcome and compiler-source retention

- Original-request actual9B run 42601516703 completed with failure on exact
  49ab25f0b441510f271fc5191402b655cb5dee84. Pinned exact-model loading and
  production Docker setup passed. Initial phase stopped at step 34 with
  no_progress after 7766.371 seconds. Step 27 build_project failed Kotlin
  compilation; no later build or repair occurred. Steps 32/33/34 requested the
  same unchanged source suffix at character offset 7200. Native/follow-up checks
  were skipped. Generated source remains incorrect and unverified.
- Original artifact 13676315116 was size/digest verified and durably preserved as
  dsGPT-complex-evidence-42601516703.zip, 147823 bytes, SHA256
  7ffd7243965ecb66422fd46304ee7b339b3ed29132e3fdf7aec280c774c03e44.
- Saved-history reconstruction through step 33 verifies scaffold/write hashes and
  the failed build snapshot, restores reviews/overview/latest summary, and uses
  the unchanged 16384 context with 4096 output reserve. Baseline retains the
  compiler diagnostic but drops the earlier source page containing its location,
  favoring newer suffix pages. Candidate retains the exact previously inspected
  first 3000 source characters and latest 143-character suffix. Baseline total
  estimate is 16371; candidate is 15712. Replay is diagnostic, not acceptance.
- Source retention now prioritizes observed, current-hash pages containing line
  locations in the displayed failed-build diagnostic. It requires the failed
  execution's current snapshot, exact path and observed bytes. Stale/successful
  builds keep normal ordering. No uninspected source, source repair, model action,
  new compiler invocation or acceptance result is substituted.
- The new context-pressure regression fails on the pinned 49ab25f baseline and
  passes on the candidate. Focused diagnostics tests: 13 passed, including stale
  and successful executions, Unicode character offsets, altered bytes/hashes,
  unrelated paths/actions, unseen source and invalid line locations.
- Full local suite: 1257 tests plus six subtests passed in 87.04 seconds. Ruff,
  whitespace and static CI policy passed; pinned tracked-source Gitleaks passed.
  Manual four-file review covered source ordering, regressions, public validation
  notes and the narrow retry trigger. Grammar, model, request, runtime, context,
  output reserve, loop limits and acceptance criteria remain unchanged.
- Before dispatch: in_progress/queued/waiting/pending all zero; 66 public artifacts
  total 97763956 bytes, none expired. No deletion needed. Private archive, signing,
  billing and cache settings untouched; prior platform evidence notes preserved.

## Owner-directed acceptance scale reduction

The original-request retry prepared after 42601516703 was not dispatched.
On 2026-11-09 the owner replaced multi-hour acceptance with a representative
smoke test. Keep the exact local 9B model and real Windows/Android outputs.
Cap total inference at 360 seconds across two responses, versus the former
18000-second budget. Production build and native setup time are separate and
bounded. Record the actual elapsed times; a timeout does not count as a pass.
The smoke scope is two visible label revisions, independent compilation and
native observation on exact artifact hashes. It does not prove Task Ledger
feature coverage or owner-device behavior. Production signing/data checks
remain in item 5.
The reduced harness passed 91 focused checks, static CI policy and lint.
A local wiring check compiled the C++ source-label assertion and verified it
rejects a wrong label; that check used a model test double and is not
acceptance evidence. Actual 9B and native results require the bounded run.

Run 42635618525 loaded the pinned model and built the production Docker toolchain.
The first model response failed hash validation at 113.065 inference seconds.
No app build or native check ran. Evidence artifact 13682818266 (76059 bytes),
SHA256 dc7e623ca0f17e68a5505c57117445ca3c6c28e60587f7c083b3ffddebaa468a.
The retry schema binds each editable path to its observed source hash, and
validation rejects a mismatched pair without rewriting any response. The
360-second cap and exact model, compilation, signing and native gates remain.

The corrected bounded run 42637730273 passed the real 9B model edits, both
independent Docker builds, exact-binary native launches on disposable Windows
and Android, and evidence join. Inference totaled 106.684 seconds. The four
original artifacts were individually hash-verified and preserved together:
dsGPT-bounded-acceptance-42637730273.zip, 19365845 bytes, SHA256
7e4690bb632b7b79270ff1d30451c1f2db668851d6e3552a05e3635d837d4f0a.
The artifact scope is bounded smoke, not production installer acceptance.
The ten-minute watcher 42638471588 observed success; the completion alert
42639362081 posted issue 1. Item 1 passed; item 2 began.

## Item 2: task/device read grants

The next backend slice binds an owner-issued account grant to one task revision,
one active Work device and the session's exact HTTPS read destination. The
default lifetime is 15 minutes, with a one-hour maximum and 64 grants per session.
General Work authorization does not grant account access. There are no external
write operations or model account tools in this slice.

Revoking a session or grant does not wait for an outstanding network read.
Authorization is checked before network dispatch and again before releasing text.
Session/grant/device revocation, task revision changes and expiry discard an
in-flight result. Revocation cannot retract an already-sent request or previously
returned content. Overlapping reads are rejected; the 12-second network bound
and bounded response size remain unchanged.

Focused account, migration, API recovery and adjacent regressions: 92 passed,
one Windows-only DPAPI test skipped on Linux, in 9.95 seconds. Tests use a fake
transport/protector except the explicitly marked native protection check; they
do not establish real-browser sign-in or item 2 completion. The schema-26 upgrade
test preserves existing protected session bytes. Desktop type generation/build,
Ruff, whitespace and static CI policy passed. Browser login/MFA handoff, permission
UI, approved writes/recovery and controlled real-browser acceptance remain.

Prior slice `60c6ef5`: routine CI 42644299735 passed all nine jobs. Backend XML
contains 1261 cases including subtests, no failures/errors and one native-only
skip. Windows XML contains 142 cases, no failures/errors and one POSIX-only
skip; the native DPAPI encryption/binding check passed. Browser: 26 expected,
zero unexpected/flaky/skipped. Android: 24 unit cases and lifecycle instrumentation
OK (1 test). Installed Windows native UI/local reply, Credential Manager,
scheduled restart and reinstall data preservation passed. The separate 1.7B
installer fixture is not item 1 model acceptance or complete item 5 evidence;
staged inference remains BLOCKED and production release remains REVIEW.
Five original report ZIPs were individually size/digest verified and preserved
as dsGPT-ci-test-evidence-60c6ef5.zip, 46297 bytes, SHA256
726430011ae7555945fbca8f464eb0147884ba26aac387bd18636c6f4a3df5b7.
Pinned tracked-source secret scanning and manual change review passed for the
grant slice. No private archive, account, signing, billing or cache settings changed.

## Item 2: owner permission controls

Routine CI 42647100427 on bc129d1 passed all nine jobs. This is backend/platform
regression evidence, not completed account/browser acceptance.

Settings now shows connected sessions and their exact approved page, task revision
and device selection, explicit 15-minute read consent, and account/grant revocation.
The panel refreshes authoritative permission state after uncertain mutation responses
without automatically repeating mutations. Browser and native transports accept
successful empty HTTP 204 responses. No password/cookie input or sign-in claim is
added; secure owner browser handoff remains outstanding.

Focused checks: nine backend account checks passed with one Windows-only skip;
11 frontend unit tests passed; one real Chromium UI test with mocked account
responses passed in 4.3 seconds including startup. The test verifies explicit
consent, task-revision/device binding in requests, inert account labels, grant
revocation and lost-response reconciliation. It is UI fixture evidence, not a
real signed-in website test. Desktop build passed. Native transport compilation
remains for the standard Windows CI job. Item 2 remains in progress.


## Item 2: durable private submission receipts

The isolated account-browser transport now requires a receipt committed before
form dispatch. Receipts contain only opaque operation/session IDs, timestamps and
state. Uncertain and response-received operations block further forms in that
session until trusted owner verification of remote state; neither verification
nor restart rearms an operation ID. The transport still requires a single-use
30-second approval of the exact origin, destination and form body. The ledger
checks session ownership, active owner status and origin, serializes competing
submissions transactionally, and limits receipts to 128 per session. Session
revocation removes its receipts; it does not undo remote effects.

Migration 28 preserves protected session bytes and existing grants. Focused
transport, receipt, account and affected migration checks: 108 passed, one
Windows-only protection check skipped locally, in 10.66 seconds. Cases include
remote-effect fixtures followed by timeout/cancellation/revocation, a rejected
redirect, successful HTTP response without semantic-success claims, failed receipt
storage, a real subprocess abrupt exit, concurrent dispatch attempts, wrong-owner
and wrong-origin denial, tamper-free migration preservation and credential/URL
sentinels absent from SQLite/WAL and captured logs. The receipt tests are included
in the disposable Windows regression selection. Ruff, whitespace, static CI policy
and the pinned tracked-source secret scan passed. No full local/model rerun.

This is internal transport/storage behavior, not completed browser acceptance.
No browser worker, owner handoff/control route or model tool invokes this yet.
The owner controller must quiesce dispatch and independently inspect remote state
before verifying a receipt; HTTP status alone is insufficient. Page-generation
and task/device binding, encrypted browser-profile restoration, controlled real
browser acceptance and the user-facing verification flow remain outstanding.

Prior source `1beb55b`: routine CI 42674663998 passed all nine jobs, including
Windows installer and required join. Backend XML has 1276 cases including subtests,
no failures/errors and one Windows-only skip. Browser has 27 expected, zero
unexpected/flaky/skipped. Android has 24 unit cases. Windows XML has 142 cases,
no failures/errors and one POSIX-only skip. This remains regression evidence;
the separate installer inference fixture is not item 1 acceptance or complete
item 5 evidence. Staged inference remains BLOCKED, production review remains
REVIEW, and owner hardware is unverified. Five original report ZIPs were
individually size/digest verified and preserved as
`dsGPT-ci-test-evidence-1beb55b.zip`, 47483 bytes, SHA256
`594d6cd37aad0b7bc2c5a81f4151b8a725f88261a7ecea6593d13bbf45511f61`.


## Item 2: protected browser profile storage

Internal profile vault added with current-user Windows DPAPI and explicit
owner/session/origin/revision binding. It accepts at most 512 regular-file entries
and 8 MiB of decoded data, rejects unsafe paths and parent/file collisions,
atomically replaces only the expected revision, and retains previous encrypted
state on protection failure. The host never extracts or writes plaintext profile
files. Migration 29 retains existing sessions and write receipts; revocation
cascades removal of the encrypted profile. No API, model or browser controller
uses the vault yet. Clean Chromium stop, isolated restore, persistent cookies,
local storage and IndexedDB require real-browser acceptance before completion.

Focused account/profile/receipt/migration checks: 111 passed, one native Windows
profile protection test skipped locally, in 10.19 seconds. Additional local
fail-closed coverage checks that unavailable Windows protection cannot write a
plaintext fallback. Native DPAPI profile save, separate-process restore and
ciphertext tampering tests are in the existing Windows CI selection. Linux
storage fixtures are explicitly not production encryption evidence.

Prior `653ac68` routine CI 42676620327 passed all nine jobs. Backend report has
1290 cases including subtests, no failures/errors and one Windows-only skip;
Windows has 156 cases, no failures/errors and one POSIX-only skip. Browser: 27
expected, zero flaky/unexpected/skipped. Android: 24 unit cases and the lifecycle
job passed. Five original report ZIPs were individually size/digest verified and
preserved as dsGPT-ci-test-evidence-653ac68.zip, 48104 bytes, SHA256
1fa92fccdcf5c6370a2a2051b122ba5c2e3d7d0db8067f2906264ded38a75613.
Routine installer fixtures remain separate from item 1 and complete item 5;
owner hardware remains unverified. No final production release is authorized
by these results. No model rerun or full local suite was performed.


## Item 2: private Chromium profile lifecycle

The guest driver launches Chromium against a fresh dedicated profile with
private debugging pipes, no debugging listener and host resolution denied.
It requires a loopback-only Linux namespace and an unprivileged guest UID;
the enclosing Docker sandbox still needs to be connected by the controller.
Restore accepts selected profile files only. Capture rejects links and special
files, stays within the vault's byte and entry limits, and runs only after a
successful browser close and process exit. Abrupt exit cannot save a snapshot.

A real Chromium 141.0.7390.37 fixture exercised two separate browser processes.
An intercepted synthetic HTTPS response set an HttpOnly persistent cookie;
the page wrote local storage and IndexedDB. All three survived a clean snapshot,
vault round trip and restoration into a fresh directory. The cookie remained
invisible to page JavaScript. The fixture uses an injected test protector and
explicitly bypasses only the guest namespace check; it does not exercise
production Docker, DNS/TLS brokerage, login/MFA or owner/task authorization.
No personal accounts or external sites were contacted. Existing browser CI
now repeats the focused restart test using its already installed Chromium.

Prior ad28f20 routine CI 42682748060 passed all nine jobs. Windows ran the native
DPAPI profile test, including separate-process restore and ciphertext tampering.
Windows XML: 171 cases, two expected platform skips, no failures/errors. Backend:
1305 cases, two Windows-only skips, no failures/errors. Browser: 27 expected,
zero unexpected/flaky/skipped; Android: 24 unit cases and lifecycle job passed.
Five original report ZIPs were individually size/digest verified and preserved
as dsGPT-ci-test-evidence-ad28f20.zip, 48443 bytes, SHA256
ba53f0cef9b13c028cd7299f5ef7c68706103fff7fda290a6110241d55c1f8c8.
Routine installer fixtures do not establish complete item 5 or owner hardware
behavior. Item 2 remains in progress; no final installers were released.


## Item 2: private container/browser bridge

The internal account bridge now creates a dedicated owned DockerSandbox, validates
its isolation and disabled logging, streams only audited standard-library guest
source into guest tmpfs, and attaches a bounded binary stdin/stdout channel.
Profiles, page input, cookies and screenshots do not enter argv, host plaintext
files, Work artifacts, model tools or diagnostics. The existing sandbox CLI now
shares its pinned-executable/environment setup with this private spawn path;
normal Work execution keeps its existing output capture and limits.

The guest enables interception before navigation. Exact-origin GET/HEAD requests
use the account network broker, with Chromium-selected cookies transferred only
inside the private channel. Cross-origin requests are denied. This bridge denies
all POSTs pending owner page/task-bound approval integration, even if the separate
broker has an approval. Unsupported popups, workers and WebSockets cannot obtain
direct network access in the required networkless container. Operations accept
only navigation, bounded PNG frames, coordinates, text input and a small key
allowlist; there is no arbitrary evaluation or exposed CDP endpoint.

Live authority and profile-origin checks precede input and response release.
Concurrent operations are rejected. Each exchange is capped at 25 seconds;
network requests retain the existing 12-second bound. Frames are length-bounded,
and profile capture requires both clean Chromium shutdown and successful guest
exit before atomic revision-checked vault save. Cancellation, revocation, guest
failure and malformed control requests abort without saving. Cleanup checks
container ownership and is shielded from cancellation.

Real Chromium fixture coverage now executes the actual shipped guest modules in
a separate Python process without site packages, through the real private pipe
and host broker. Two clean starts restore an HttpOnly persistent cookie, local
storage and IndexedDB. Independent fixture request assertions confirm all three,
HttpOnly invisibility to page JavaScript, blocked cross-origin requests and blocked
unapproved POSTs. Additional cases cover in-flight cancellation, revocation,
abrupt guest exit, concurrent input, malformed frames, raw-CDP rejection, origin
mismatch and rejection of a container configured to log. The fixture explicitly
substitutes container creation and HTTPS transport; it is not production Docker,
TLS, owner sign-in/MFA, Windows encryption or complete item 2 acceptance. No
personal accounts or external sites are used. Browser CI reuses installed Chromium.

Prior 595f3ed routine CI 42692882643 passed all nine jobs, including the real
Chromium restart fixture. Backend XML: 1313 cases including subtests, no failures
or errors, three expected platform/browser-fixture skips; Windows: 171 cases,
no failures/errors and two expected platform skips. Browser: 27 expected, zero
flaky/unexpected/skipped. Android: 24 unit cases and lifecycle OK (1 test).
Five original report ZIPs were individually size/digest verified and preserved as
dsGPT-ci-test-evidence-595f3ed.zip, 48535 bytes, SHA256
90ab2fca4d16ecfd69a1903727ad54bd572bfd39552e53f5d4cbfe9dc0729862.
Installed Windows native UI/local reply, Credential Manager, scheduled restart,
reinstall and data preservation passed in the separate fixture. Its 1.7B model
is not item 1 acceptance or complete item 5; staged inference remains BLOCKED and
production release REVIEW. Owner hardware remains unverified. Item 1 was not
rerun, no full local suite was run, and no final installers were released.

Focused bridge/worker/profile/broker/receipt/sandbox checks: 82 passed and one
Windows-only DPAPI check skipped locally in 3.45 seconds. Ruff, whitespace,
static CI policy and the pinned tracked-source secret scan passed.


## Item 2: quiescent browser lifecycle before owner controls

Review found startup could outlive a simultaneous abort: abort had no startup
task to cancel/join, so a later container/pipe could become live after cleanup.
Close also ran abort in its finally block when another operation was merely busy.
The bridge now latches stopped state, cancels and joins startup and active exchanges,
rejects reuse after abort, and rejects concurrent close before its cleanup block.
A closing flag prevents new input during clean shutdown/profile commit. Live
checks also reject responses after abort. No owner API or write capability was
added; owner login/MFA, task integration and production acceptance remain open.

Five deterministic lifecycle regressions fail the prior 4d07981 implementation.
Candidate bridge/lifecycle/profile checks passed 33 cases in 2.04 seconds with one
Windows-only DPAPI skip. Real Chromium coverage also verifies external abort of
an in-flight request discards the response and leaves the vault unchanged. These
are synthetic transport/container fixtures, not production Docker/HTTPS evidence.

Prior 4d07981 CI 42698303776 passed all nine jobs. Backend: 1326 XML cases including
subtests, zero failures/errors, eight expected platform/browser skips. Windows:
171 cases, zero failures/errors, two expected platform skips. Browser UI: 27
expected, zero unexpected/flaky/skipped. Separate private-browser XML: 15 cases,
zero failures/errors/skips. Android: 24 unit cases; lifecycle job passed.
Five original report ZIPs were individually size/digest verified and preserved as
dsGPT-ci-test-evidence-4d07981.zip, 48643 bytes, SHA256
64ffe0da1f5d2dc6e2497744288bf789160e0669c54dd7abe808f4e6594c3126.
Item 1 was not rerun, owner hardware remains unverified, and no final installers
were released. Routine platform CI does not establish complete item 2 or item 5.


## Item 2: authenticated local owner handoff API

Browser enrollment requires no pasted cookie. The owner-only loopback API
starts a single five-minute handoff against the exact configured HTTPS origin
and page using the prepared isolated tool runtime. An opaque handoff identifier
gates private no-store PNG frames, bounded clicks, text and keys, save and
discard. Old identifiers cannot operate a reopened browser. Expiry, revocation
and backend shutdown discard the active browser. Secret input is not part of
session rows or Work tools. Legacy cookie sessions retain their existing
behavior; new browser sessions reject legacy reads and Work grants.

Focused API, session, lifecycle and real Chromium fixture checks: 23 passed,
one native Windows-only skip, in 2.71 seconds. The API tests use an injected
bridge and verify loopback/owner restrictions, no-store frames, typed input,
save/reopen, stale IDs and revocation. The separate Chromium tests still use
the documented synthetic transport/container. Neither is end-to-end login or
production Docker/HTTPS acceptance. The desktop pop-out and page-bound form
approval are not yet wired; the browser continues to block POSTs.

Prior d9468e5 CI 42705120389 passed all nine jobs. Backend: 1332 cases including
subtests, no failures/errors, nine expected platform/browser skips. Windows:
171 cases, no failures/errors, two expected platform skips. Desktop browser:
27 expected, zero flaky/unexpected/skipped. Private browser: 21 cases, zero
failures/errors/skips. Android unit and lifecycle jobs passed. Five original
report ZIPs were individually size/digest verified and preserved as
dsGPT-ci-test-evidence-d9468e5.zip, 48900 bytes, SHA256
859a32c0ac4c388f4eb6ee3b8fdc69855f537354b3ea00376c40ed4670705ff4.
No owner hardware was tested and no final installers were released.

## Item 2: desktop private browser view

The desktop can now enroll a cookie-free browser account and open an owner-only
modal view. A dedicated native binary command authenticates using the stored
backend connection, accepts only loopback origins and UUID-bound frame endpoints,
rejects redirects and non-PNG/non-no-store responses, and caps decoded frames at
1.5 MiB with a fixed 1024 by 768 IHDR. The frontend repeats the byte/dimension
checks and renders only an in-memory image; no remote page enters the webview.
The guest bridge now checks the same PNG dimensions before releasing a frame.

The view serializes clicks, a fixed key allowlist, masked text submission and
refresh. Text clears before sending and errors do not retry input. Expiry removes
images and text and prevents a late response restoring an expired image. Closing
or navigating away discards; saving explicitly requests a clean encrypted profile
snapshot. Stale discard is idempotent without touching a newer handoff. Browser
profiles are identified in account metadata so the UI does not offer incompatible
legacy Work grants. No website POST is enabled: login/form approval, remote-state
verification, task integration and real production acceptance remain outstanding.

Focused checks cover native-command selection, MIME/cache/size/dimension rejection,
UI enrollment, scaled clicks, key input, interrupted text without replay, explicit
save/discard and expiry. Backend fixture checks include stale discard, profile
metadata and malformed PNG rejection; real Chromium pipe/restore fixtures still
use synthetic transport and container isolation. Native Rust tests are included
in the existing Windows CI selection; local native compilation was unavailable.
Local results: 20 focused backend cases passed in 2.50 seconds, with one native
Windows-only skip; four transport checks passed in 0.212 seconds. Two focused
browser UI scenarios passed; the handoff scenario also checks delayed frames
arriving after simulated expiry. Desktop production build, Ruff and CI policy
checks passed. These are not production Docker/HTTPS/login/MFA or item 2 acceptance.

Prior 6f29277 routine CI 42708371935 passed all nine jobs. Backend: 1334 cases
including subtests, zero failures/errors, nine expected platform/browser skips.
Windows: 171 cases, zero failures/errors, two expected platform skips. Desktop
browser: 27 expected, zero flaky/unexpected/skipped. Private browser: 21 cases,
zero failures/errors/skips. Android: 24 unit cases and lifecycle OK (1 test).
Five original ZIP reports were separately size/digest verified and privately
preserved as dsGPT-ci-test-evidence-6f29277.zip, 49855 bytes, SHA256
17557757c15fd0d61fc012d69717457ee6dbe8804e58c7fd5a727f9025fff7ce.
The separate installer fixture does not complete item 5; owner hardware remains
unverified. Item 1 was not rerun. No final installers were released.

### Owner form review and interrupted submission

The local owner's explicit opt-in allows one click or Enter to pause a supported
same-origin top-level form. A fresh single-use screenshot observation and the
Chromium document identity bind the input. The view shows the destination and
requires a separate approve or reject decision for the exact paused request.
The deadline is bounded; ordinary input, delayed requests outside the reviewed
exchange, and unsupported forms cannot send a POST. The native transport adds
only the observation UUID to its bounded binary frame response.

A dispatch creates an opaque durable receipt before network I/O. If an approved
request is interrupted, the receipt remains uncertain and blocks another
submission. Even after a website response, the owner must inspect the current
page and explicitly record the outcome. Verification consumes a fresh
observation after the operation has quiesced and cannot replay the old form.

Focused Linux backend checks: 67 passed and two native Windows checks skipped.
Real Chromium with synthetic network/container fixtures covers approval,
rejection and interruption after dispatch; two desktop browser fixture
scenarios and four transport unit checks passed. The desktop production bundle
built locally. This is not production website login/MFA, native Windows execution
of this revision, or full item 2 acceptance. Work grants remain unavailable for
browser profiles.

Prior exact 83b174b run 42714023491: six jobs passed. Windows native compiled
and its frame unit test passed, but the unchanged 300 MiB artifact guard blocked
the Windows client upload; installer acceptance was skipped and the aggregate
check failed. Four available report ZIPs were individually checked against
their Actions sizes and SHA256 digests. Private evidence bundle:
dsGPT-ci-test-evidence-83b174b.zip, 43,125 bytes, SHA256
5183dcd26a66a853df0a4405c23855d49cd2c490eec14abe64be35a0d241afe8.
No guard change, artifact deletion, paid runner, or final installer release.

### Delegated saved-profile account reads

Schema v30 pins browser grants to one saved profile revision. An owner must
review the current saved revision before granting a task/device access. Existing
cookie grants, encrypted profiles and interrupted-write receipts migrate without
rewriting them. Replacing a profile, editing the task, expiring the grant or
revoking the device, session or grant prevents a subsequent read. An active
read rechecks authority and aborts its disposable browser before returning.

A delegated browser can fetch only the configured exact HTTPS page, once, using
the relevant cookie from the saved profile. It rejects redirects, HTML, cookie
rotation and known credential reflections. The guest receives no private page
content or remote headers, and delegated reads never save the profile. Results
are bounded plain text for the requesting device. Desktop Work only lists or
reads grants on explicit request and clears the view on task revision change.
Nothing is added to model context, public research, task files or logs.

Local validation: 91 focused backend checks passed and two Windows-only checks
were skipped. A real Chromium fixture restored a saved HttpOnly cookie through
a fresh backend and exercised the paired-device API; transport and container
were synthetic. Separate fixture cases cover in-flight revocation, scope,
migration and refused responses. Three desktop Chromium UI fixture scenarios
passed and the production web bundle built. Production Docker/TLS, MFA,
Windows DPAPI and the Android presentation still need acceptance. Item 2
remains open. No paid services, guard changes, artifact deletion or installers.

### Paired Android account-read draft — native checks pending

The Android Work view now has a separate private-page dialog. Grant discovery
and reads require explicit input. Responses use a dedicated no-retry, no-redirect
client without diagnostic listeners, a 30-second call deadline and a 256 KiB
streaming response cap. Metadata is type checked; text is limited to 12,000
Unicode code points. Fractional expiry timestamps and legacy cookie grants are
preserved. Task revision and connection generation are checked before and after
requests. View disposal cancels the network call. Dialog state is not saved,
exported or passed to the model, and the window requests Android secure display.
Backgrounding, close, revision/connection changes, grant expiry and a five-minute
view deadline remove the private view or its content.

Ten focused parser, loopback HTTP transport and Compose tests were authored for
limits, consent, cancellation, stale results and fixed error text. They have NOT
passed or established native behavior. A bounded local Gradle attempt failed
first at network setup; after correcting the environment proxy it began dependency
setup. Automatic approval review then rejected continuation because it wrote a
Gradle dependency cache contrary to the no-cache-writes requirement. The test
session was no longer available, and only this attempt's reproducible local
dependency and Gradle directories were removed. No attempt was made to bypass
the rejection. Native compilation and the ten tests remain pending.

Source whitespace, static CI policy, pinned tracked-source Gitleaks and manual
ten-file privacy review passed. This draft is preserved
on a separate isolated branch; the previously tested account-form-review branch
and public main remain unchanged. No acceptance run, installer, storage-guard
change, artifact deletion or budget change was made. Item 2 remains open.

### Controlled HTTPS acceptance-site preparation

Added a test-only, loopback-bound TLS site with ephemeral certificates and
synthetic credentials. Password and MFA stages precede a Secure HttpOnly cookie.
CSRF and exact Origin checks protect updates. An independent effect counter
deliberately counts duplicate submissions; a dropped-response route applies one
update then closes the socket, so client retries cannot be hidden by server
deduplication. The restoration probe only reads localStorage/IndexedDB markers;
it does not reset them and thereby mask missing profile data. Temporary TLS keys
are deleted on context exit and neither requests nor client addresses are logged.

Three focused real HTTPS/socket tests passed in under one second using existing
dependencies with Python bytecode and pytest cache writes disabled. They cover
login/MFA, cookie attributes, CSRF/origin denial, expiry, untrusted-certificate
rejection and an observable effect after response loss. Script presence was
checked; JavaScript execution and profile restoration were NOT tested here.
This is test-site validation, not production Docker, Chromium, DNS broker,
Windows DPAPI or item 2 acceptance. Android validation remains blocked as above.
No new Actions runs, cache writes, guard changes or final installers.

### Production broker/ledger against the controlled TLS site

Two focused integration cases exercise the actual account request broker and
write ledger over real TLS sockets: a received response and a connection lost
after an applied update. After reopening the ledger, both the original action
and a new action are blocked until remote-state verification. Verifying the
observed change never rearms the old action. The independent server count stays
exactly one. Synthetic login/MFA credentials, cookies and CSRF values are absent
from captured logs and the SQLite files.

The test transport explicitly maps the configured public origin to the loopback
TLS fixture and trusts its ephemeral certificate. No production code or network
validation was changed. This tests broker/ledger integration, NOT PublicHTTPS
DNS pinning, Docker isolation, Chromium, owner UI approval or Windows DPAPI.
Initial test setup mistakes (old editable source path and an appended empty URL
query) were corrected in the test invocation/mapping, not in production behavior.
The two cases passed in 0.44 seconds with existing dependencies, bytecode disabled
and pytest caching disabled. Android validation remains unverified and blocked
as previously recorded. No additional Actions run or release was dispatched.

### Combined Chromium/TLS driver prepared; native results pending

The controlled site now has a read-only restoration proof request and an
interrupted-update form. Its browser script sends the restoration proof only
after observing the existing localStorage and IndexedDB markers and checking
that the session cookie is hidden from JavaScript. The proof endpoint requires
the signed-in cookie. The drafted integration test drives actual guest input,
separate form review, password/MFA, profile close/reopen, lost-response writes
and denial of a newly approved duplicate after ledger restart. It uses existing
explicit container/vault fixtures and the real-TLS endpoint mapping; it does not
establish production Docker, public DNS/TLS or native Windows protection.

Five focused TLS/site/ledger cases passed in 0.96 seconds; the new browser case
was skipped without a configured browser. Attempts to run the pre-existing form
fixture with the installed Chromium failed before account requests. A pristine
about:blank launch isolated the cause: the execution host denied Chromium's
process-singleton socket. No production security settings were weakened and no
browser dependency was downloaded. The new browser driver is UNVERIFIED; it is
selected in the existing CI browser job for a later tested-source run.

Read-only public artifact inventory subsequently returned zero artifacts and no
active/queued/waiting/pending runs. Main was advanced from exact `83b174b` to the
previously tested `4b87ed1` using a non-force expected-head lease. Routine CI
`42974018414` was observed running on that exact source. The newer Android and
TLS-driver draft remains on its isolated branch and was not promoted as tested.
No item 2 acceptance result or final installer is claimed.


### Platform results and bounded TLS/browser integration

Routine CI `42974018414` passed all nine jobs on exact `4b87ed1`.
Five original report ZIPs were independently size/digest verified and preserved
privately as a 52,906-byte bundle, SHA256
`94e4e8c0724903d29aa2e29b6131174115eafb2896338052c7a92ab299e19ce4`.
Backend: 1,351 cases, 13 expected skips; Windows: 171 cases, two expected skips;
desktop browser: 29 expected; private browser: 43 cases; Android: 24 unit cases
and lifecycle OK (1 test). No failures/errors. Windows installed-app/local-reply
checks use the separate 1.7B fixture; production review and owner hardware remain
unverified. This is not full item 5 acceptance.

A separate six-minute Ubuntu check used the runner's existing Chrome and locked
Python dependencies with cache writes disabled. No Gradle, model, installer or
full-suite rerun. First run `42982154387` failed to observe login form review.
Fixed coordinates in run `42982471990` still failed because the controlled site's
CSP blocked inline layout styles. The test site now explicitly permits its own
inline styles. Failure traces are short, and form diagnostics contain only fixed
booleans, never request values. No product security setting was weakened.

Run `42982778303` on exact isolated source `3ea2859` passed all six tests, no
skips/errors/failures, in 7.671 seconds. Actual guest input submitted password/MFA,
restored cookies/localStorage/IndexedDB after clean shutdown, and blocked a newly
approved duplicate after a lost response and ledger restart. The independent
server recorded exactly one update. The original 587-byte report ZIP is preserved
privately, SHA256 `14756670ddbce09e57f7066d02f9767ce9f28904889f2213148c55d5c6a01d4c`.
These checks still use explicit container, vault and endpoint-mapping fixtures.
They do not establish production Docker isolation, public DNS pinning or native
Windows protection. Android draft validation remains pending; item 2 stays open.


### Live production account HTTPS transport

Isolated run `42988030561`, exact source `77dbd08`, passed one focused case with
zero skips/errors/failures in 0.264 seconds. AccountBrowserNetwork used its default
PublicHTTPS transport without resolver, endpoint, certificate-trust or response
injection to fetch the public REQUIREMENTS.md at pinned source `4b87ed1`.
The body matched SHA256 `e9663679a315c30d2d00b3a56e9d59e0d6200026877e25fc0c9deee8fc00fe1e`;
authority checks and one-request accounting were observed. No cookies or private
content were sent. This establishes the live public transport path, not every
network scenario, browser/Docker isolation or full item 2 acceptance.

The one-day 378-byte original report ZIP was size/digest verified and preserved
privately: SHA256 `3b0fbd153bc293554ef16a5a81dffe19968d5d95904dbacdc5af0e5d628489a4`.
The existing six-minute standard Ubuntu check ran only this new test, installed
locked dependencies without cache writes, and did not repeat browser/model/
installer/Gradle checks. Source audits passed. Main and Android runtime status are
unchanged; the earlier local Gradle approval rejection was not bypassed.


### Focused Android account presentation — 2026-11-12

Run `43266192022`, job `131350279931`, passed on exact `30ef476`. App and
test Kotlin compiled; 10 selected account transport/parser/Compose checks passed
with zero failures, errors or skips. Gradle reported 2 minutes 22 seconds.
The preceding run compiled successfully but its truncation-notice assertion
looked for an offscreen LazyColumn item; the corrected check scrolls to the
item and still requires it to be displayed. No acceptance requirement was removed.
The owner authorized disposable-runner build dependencies with no shared cache
upload or budget change. This job used standard public Ubuntu and no artifact
uploads. Its log and summary were preserved privately in a 5,823-byte bundle,
SHA256 `5c1aedde4c3c1c8ee408bfc09463d5b8945ddaab464904069312e012f7fc3571`.
This is focused Android evidence, not full account-workflow or release acceptance.

The next opt-in driver uses unchanged DockerSandbox and guest modules with the
exact production tool image. The controlled login scenario retains explicit TLS
endpoint mapping and a test vault, and a separate case uses unchanged public
DNS/TLS through the actual guest. The driver has not yet run on Docker. Linux
checks cannot establish native Windows DPAPI. No final installers are released.


### Production account Docker and owner-controller evidence — 2026-11-12

Run `43269409156`, job `131361597023`, passed both opt-in Docker checks on
`6341616` in 8.94 seconds after the production image build. Recipe SHA256
`57d6b095721edd3103a2f675a2ff1ed76423c7f6365dceb24ede021d96b131d6`;
image `sha256:e961941baff974e31b1c2116a18736d8299b1b364700420a684dea3a5c5e1b81`.
The unchanged sandbox enforced its real isolation checks and streamed the audited
guest through private pipes. Controlled login/MFA, clean profile restoration and
interrupted-write retry denial passed with independent effect count one. The
separate guest/public transport case used real DNS/TLS with no endpoint override,
checked pinned bytes, revoked authority and confirmed cleanup. All test cases
passed with no skips, failures or errors. The image was removed afterward, with
no image/cache/artifact publication. The private 81,241-byte log/summary bundle has
SHA256 `7d9f19be93c1a2eaa58f729a83f770b134dec7f8cda8a93814600cae38701bcd`.

Run `43270310226`, job `131364763884`, passed both owner-controller checks on
`72fa47b` in 6.18 seconds, with zero skips/errors/failures. Real Chromium and TLS
exercised owner observation, single-use form decisions, pending-outcome blocking,
clean save, service restart, authorized task/device reads, wrong-scope rejection,
expiry and revoke. Browser plaintext never becomes model or task content. This
case retains explicit container, endpoint and vault fixtures; it does not claim
native Windows encryption. The private 9,612-byte log/summary bundle has SHA256
`f10cd18dc90c8a851cfaefc1c098a4ad79d3e99a5ee5a21599356c0b0bbca9ad`.

A separate native Windows check on `452085b` passed. It uses default real DPAPI
with synthetic profile data and checks persisted API grants, process restart,
profile revision invalidation, uncertain receipt preservation, tamper rejection
and revoke cascades. It is separate from actual Chromium/Docker observations.

Run `43270956531`, job `131367024166`, passed the native Windows account boundary
in 1.78 seconds: one test, zero skips/errors/failures. The private 8,910-byte
log/summary bundle has SHA256
`dc852a042b687b586783b6dad013c41c9c300ac97ceb5c05f4eee2ff45b6d389`.
All four new focused runs used standard public runners, bounded runtime and no
artifact/cache uploads. Earlier native and browser evidence remains applicable:
no production backend or desktop behavior changed during these test additions.
The Android source compiled and its new focused cases passed. Account acceptance
is scoped to the documented supported same-origin interactions and plain-text
grants; it does not claim universal website compatibility or physical devices.
Reconciled main integration CI remains the final check before the item-2 alert.


### 2026-11-12 item 2 integration completed and item 3 candidate

Main `89803c25089e3d8a517bd749bddaf1c429e9cb7e`, integration run
`43271693885`, passed all nine jobs. Backend 1369 cases (19 explicit optional
skips), desktop browser 29 and private browser 45 (zero unexpected/flaky/skips),
Android 34 unit cases plus lifecycle OK (1 test), Windows 172 cases (two expected
platform skips). Windows installed native UI/reply, Credential Manager, scheduled
restart, reinstall and data preservation passed using the separate 1.7B fixture.
That fixture does not replace item 1 or complete item 5; staged inference remains
BLOCKED and production physical usability REVIEW, owner hardware unverified.
Five original report ZIPs were each size/digest checked and preserved privately
as `dsGPT-ci-test-evidence-89803c2.zip`, 53586 bytes, SHA256
`3c4897b903d25fd85b1211ee35a7c866ce78fc75d1bdb4e2a44d942844dfe000`.
Terminal item-2 alert `43273894623` passed and posted one owner mention in issue 1
(comment 6831505823). Integration monitor `43271832772` remains run scoped.

Item 3 candidate: fixed isolated render/recalculate/extract-page actions, separate
outputs, bounded OOXML inspection, macro/link-update denial, independent exported
formula/cache checks, and transitive invalidation of stale validation receipts.
73 focused parser/orchestration/build-context/Work checks passed in 5.90 seconds,
with two opt-in Docker checks explicitly skipped locally. The additional affected
receipt checks passed (39 selected cases in 2.06 seconds).
These are not engine or visual acceptance. No final installers or model reruns.


### Item 3 integration completion and item 4 initial client check

Main `111df671be24e180b4c1e23d8843e4a3895a08eb`, tree
`5ad8fe148f61a93d5ee3354e5234caf8d81a0776`, passed all nine integration jobs
in `43280663340`. Backend: 1382 cases including subtests, no failures/errors,
22 expected skips. Desktop: 30 expected, no flaky/unexpected/skipped. Private
browser: 45 passed. Android: 35 unit cases and lifecycle `OK (1 test)`. Windows:
172 cases, no failures/errors, two platform skips; installed native UI/reply,
Credential Manager, scheduled restart, reinstall and data preservation passed.
The separate 1.7B installer fixture is not item 1 or complete item 5 acceptance;
staged inference remains BLOCKED, production REVIEW and owner hardware unverified.
Five original report ZIPs independently size/digest verified; private combined
`dsGPT-ci-test-evidence-111df67.zip`: 53996 bytes, SHA256
`86e5ec57e94df646f6ecf160fa7a938093506a112b58845159dcf2b3cd0deb70`.
Monitor `43280869724` passed. One item-3 completion alert `43288787309` passed
and posted issue 1 comment `6833526633`; do not duplicate.

Grouping run `43289109215` on `efd73dc44075389b0b282fad4ad27ced90fa002a`
passed eight backend checks (1.45s), desktop TypeScript/Vite build and native
Android app/test compilation with one Compose check, no failures/errors/skips
(Gradle 1m56s). Desktop Chrome failed after link creation while selecting the
project by exact accessible name. The corrected selector has an explicit stable
accessible name; the test stays unchanged. The follow-up targets only desktop.
Original report artifact `13976637303`: 2503 bytes, SHA256
`621fb27e1ff31c886ddce6e135b011fe19ee78188ecb1ac6bca3d15b86bd1fce`.
Original ZIP plus decoded desktop/Android job logs preserved privately as
`dsGPT-group-check-evidence-43289109215.zip`: 19161 bytes, SHA256
`5807d672bc7b83c0f698735ff6bb38fed922f8d200ac8a220b2e275b22380185`.
These are separate boundaries; item 4 remains open pending browser acceptance
and integration of the generated API contract.

Desktop grouping correction passed in `43289697441` on exact `88ef7a8`: eight
backend checks in 1.43s, desktop build and one actual-backend Chrome UI workflow
in 4.96s, zero failed/flaky/skipped. Original artifact `13975908223`, 12360 bytes,
SHA256 `649c6c9deefcb3b94a43a482b8838cced31cd257b9a94205660d972be1722c38`.
Generated API declarations reconciled from that artifact. Private original/report
log bundle `dsGPT-group-desktop-evidence-43289697441.zip`, 23000 bytes, SHA256
`caa89adb8a19ef3070335c97343b5b3f9eb9017e4a507a190daa1a7500711498`.
No unchanged Android rerun, no model/office rerun, and no terminal item-4 alert
before main integration.

Integration `43290205949` on `f58a6bc` failed five legacy migration fixtures;
the other source/frontend/browser/Android/native Windows compilation jobs passed.
The installer was skipped and the required join failed. Backend: 1390 cases
including subtests, five failures, zero errors, 22 expected skips. Desktop Chrome:
31 expected, zero flaky/unexpected/skipped; private browser: 45 passed. Android:
36 unit cases and lifecycle `OK (1 test)`. This is not an integration pass.
Four original report ZIPs were individually size/digest verified and retained
with a bounded backend failure excerpt in private
`dsGPT-ci-failure-evidence-f58a6bc.zip`, 60842 bytes, SHA256
`15515f24cb21b1f69736caa9f1980e313bc61e3b812280dfd090d63328d06f5e`.
The five-case fixture-only repair is `5638a5d`; its integration result must be
observed separately. No product migration or assertion was weakened.

Grouping integration repair `43292113633` on exact
`5638a5df6984403db1d6a0d5418e0c1f2455b72b` passed all nine jobs. Backend 1390
cases including subtests, zero failures/errors, 22 expected skips; desktop 31
expected and private browser 45 passed without flaky/unexpected/skipped cases.
Android 36 unit cases and lifecycle `OK (1 test)` passed. Windows 172 cases,
zero failures/errors, two platform skips, and native installation/credential/
restart/reinstall/data checks passed with the separate qwen3:1.7b fixture.
That fixture is not item 1 or full item 5; owner hardware remains unverified.
Five original report ZIPs were individually size/digest verified, then preserved
privately as `dsGPT-ci-test-evidence-5638a5d.zip`, 53910 bytes, SHA256
`756be374f0836f036738fea828dab6ccc447f17d6a3b57162c3184ac175f09c1`.
Item-4 alert `43294611261` on `c69ff0c2b1c30e5348330418a3ec37ef8f92bc9e`
passed and posted issue 1 comment `6834304747`; do not duplicate.

### Item 5 bounded Work inference diagnostics (2026-11-12)

Isolated `a38dc68f06bbb7c7c96609443d3bc71cef49f8ff` (tree
`74997084b04ecda111a10b98b2bc546d6ba35168`) passed focused Windows run
`43296765243`, job `131457027574`: 37 checks, zero failures/errors/skips,
27.259 seconds. Original artifact `13979926068`, 1,057 bytes, SHA-256
`535a19a5e655ae06e22b9d932d945feedee4c43efe9d7d95a6ee25e661e65656`,
was size/digest verified. The job used a standard public Windows runner,
six-minute cap, locked uncached dependencies and a bounded one-day JUnit report.
No model, Gradle, installer or full-suite rerun. Per-attempt metrics remain
private reviewed diagnostics; stream completion is not action success.
Item 5 remains open for real old-to-candidate upgrades and reconnect/signing
acceptance. No item-5 terminal alert or final installers have been released.

### Independent offline signing-format boundary (2026-11-12)

Run `43298591745`, job `131463379733`, exact isolated
`1f26082c4a7077e13838894244585c41b674a2c8` (tree
`cc3a3278776fbc0c3b8a5769c9fcc76ea98bf0cf`), passed seven checks in 4.791 seconds
with zero failures/errors/skips. A synthetic RSA key and bounded multi-chunk ZIP
were signed offline using existing cryptographic primitives. Independent Android
SDK 35.0.0 apksigner verified the v2 envelope/certificate and rejected a changed
payload. Original artifact `13979454260`, 552 bytes, SHA-256
`1ea9775bd80876cce777796d7a5b22060d586dfbc143bf230f5a880c0f6c0573`,
was independently size/digest checked and preserved privately.

No production key, account credential, model run, Gradle build, emulator or final
installer was used. This is a signing-format boundary check, not production APK
signing-continuity or item-5 acceptance. The original key remains private outside
GitHub. The six-minute public Ubuntu job used uncached disposable dependencies,
the preinstalled Android SDK and only a bounded one-day JUnit artifact.

### Exact production APK signatures (2026-11-12)

Run `43326864291`, exact source `dad8a8c4fed5d3e56ed958edaf1979811b56b665`,
passed independent SDK signature verification of the prior delivered APK and the
unchanged privately signed candidate. Both match the original certificate and
`com.dsgpt.mobile`; versions are 23 and 24. Original artifact `13993646462`,
702 bytes, SHA-256
`cc904cc61f1dc67703124b34e01f5d3dd3d1e0c764bbaf4a0896c621482d339f`,
was size/digest checked and privately preserved. The authorized encrypted pair
was bound to a fresh ephemeral receiver; cleanup succeeded. No signing key,
backup or plaintext APK was published, and no APK was rebuilt or resigned.
This is signature continuity only. Installed Android and Windows upgrades,
credential/data preservation and reconnect still gate item 5 and delivery.


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


Retained-installer diagnostic `43399256671` on `eb4d01a` reproduced the
baseline failure at `native_history` line 121 (native process exited), after
successful retained-source/hash verification and encrypted input receipt.
The driver supplied `upgrade-native-profile`, but the existing native acceptance
contract explicitly requires `webview-<32-hex-run-id>` and aborts otherwise.
The driver now uses that required isolated profile name. No application, installer,
assertion, credential seeding rule or candidate byte changed; the next check reuses
the same source-6ae installer. Diagnostic cleanup succeeded. Original report:
241 bytes, SHA256 `446ee79c1d02d58bc305014ff5425ff02590ac73bf3290adb115cd1f0b7e9736`.
This diagnosis is not installed acceptance or item-5 completion.


Corrected-profile run `43400463285` on `f78043a` progressed through both actual
installed native clients, old history visibility, credential/paired authority and
model-directory preservation. It then failed in candidate `check_snapshot` line 55:
the driver's identifier guard rejected valid schema column names containing digits
(such as SHA256 fields). This occurred before row comparison, not evidence of lost
data. The guard now accepts SQL identifiers with digits after the first character;
exact comparisons remain unchanged. A fixture with a retained sha256 column passes,
while malformed/injected identifiers still fail. Six local guards pass (0.04 seconds).
Original 238-byte report SHA256:
`7818faee84338f265b05378667f7653b902176da39f3a30bcd98c5b46ff6b371`.
Receiver and cleanup succeeded. The retained source-6ae EXE and signed APK are
unchanged; no rebuild or final acceptance is claimed.
