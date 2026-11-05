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
