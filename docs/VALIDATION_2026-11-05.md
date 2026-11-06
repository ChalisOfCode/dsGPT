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
