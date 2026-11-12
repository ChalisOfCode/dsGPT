Warning: truncated output (original token count: 50772)
Total output lines: 3176

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
Neither compilation nor complex-app completion pas…20772 tokens truncated…einstall/data preservation and
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
