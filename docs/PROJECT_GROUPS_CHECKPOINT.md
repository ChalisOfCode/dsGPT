# Related project groups checkpoint

Item 4 implementation is isolated on `work/project-groups-111df67`. Focused native/browser
acceptance passed; main integration remains pending.

Groups are references to already imported history, Work tasks and original Work
inputs. Owner review happens after the existing import validation/save, in History
and retrieval. Existing import limits and omission notices remain unchanged; this
is not a new full-archive backup or automatic archive execution path.

The planner inspects bounded inert text and metadata for exact GitHub repository
and distinctive package identifiers, or weak title matches. Generic names do not
link unrelated inputs. Multiple identifiers remain explicitly ambiguous. No hint
applies itself, executes content, calls a model or opens a URL. Arbitrary archive
metadata is not trusted as a project mapping. An explicit owner selection and group
name supply a reviewed mapping when identifiers are missing or conflicting.

Migration 31 adds independent group/link/request tables. Preview tokens bind source
versions, source visibility/revisions, rule version, current decisions and the
selected group revision. Apply is atomic and idempotent; changing the request under
the same UUID conflicts. Retry receipts never recreate deleted objects. Manual
accept/reject/leave-ungrouped decisions survive restart. Multiple links keep mixed
conversations intact; no automatic split, merge, deletion or memory promotion occurs.
Changing originals makes old links unavailable until reviewed again. Source removal
clears its associations; group deletion leaves originals and memories untouched.

Only the owner can edit. Read APIs recheck source scopes. A mixed history/Work group
requires both scopes, including its name, and adding a kind only tightens that
requirement. Grouping cannot grant source access. Hidden/removed sources are omitted.
Links contain identities/hashes/decisions, not copied messages or evidence excerpts.
Fingerprints mean normalized imported identity, Work revision metadata, or original
input bytes according to source kind; they are not a full-archive backup hash.
The desktop supports review/correction/rename/removal; Android is read-only and
clears its displayed metadata on connection changes or backgrounding.

Bounds: 50 selected references per review and 50 source/group rows per page,
256 live groups, 4096 links and 4096 durable mutation receipts. The owner can delete
or ungroup references; receipts remain to prevent replay. Text hints inspect at most
64 KiB per selected source; supported text input files only. Binary/ZIP contents are
not unpacked by grouping. The UI states that hints are not complete inspection.

103 focused group/history/affected-account checks passed in 6.02 seconds with two
expected platform skips; the new grouping module subsequently passed all eight
checks including concurrent identical-request replay. Existing source normalized
hashes, message rows, memories and original file bytes are compared before/after.
A v30 database migration preserves old records. Real desktop and Android focused
checks are authored but not yet run; the generated desktop API types must be
reconciled from the disposable-runner output before main promotion.

Focused run `43289109215` on `efd73dc` compiled the Android application/test
and passed the one real Compose group browsing/connection clearing check. All
eight backend grouping checks and desktop TypeScript build passed. The desktop
browser then failed to find the selector by its exact accessible name after groups
loaded. The correction supplies a stable explicit accessible name; the test is
unchanged. The follow-up workflow selects only the affected desktop check and
keeps the generated API types even if browser validation fails. Android source is
unchanged, so its successful focused check is reused. Item 4 remains open.

Desktop retry `43289697441` on `88ef7a8f14dac6187ac2836b0fea0a603794ee17`
passed all eight backend checks in 1.43s, generated the API contract, built the
desktop bundle and passed the actual-backend Chrome workflow in 4.96s (one expected,
zero failed/skipped/flaky). It reviewed the exact repository hint, required explicit
application, linked two sources, renamed the group, rejected one association, left
the other ungrouped and removed the group; original requirements stayed unchanged.
The unchanged Android source retains its compilation/Compose pass from `43289109215`.
Generated TypeScript declarations are reconciled byte-for-byte from the verified
report artifact. The API, browser and Android checks are separate observations,
not a physical-device end-to-end result or universal archive classification.

Original desktop report ZIP: 12360 bytes, SHA256
`649c6c9deefcb3b94a43a482b8838cced31cd257b9a94205660d972be1722c38`.
Private report/log bundle `dsGPT-group-desktop-evidence-43289697441.zip`:
23000 bytes, SHA256 `caa89adb8a19ef3070335c97343b5b3f9eb9017e4a507a190daa1a7500711498`.

Main integration `43290205949` exposed five legacy fixture failures: the v19–v22
fixtures started with a current database but had not removed the new v31 grouping
tables/triggers before setting an older user_version. The production migration
correctly rejected that inconsistent fixture with `table already exists`. Four
fixture setup functions now use the existing explicit grouping-schema removal
helper. All five affected upgrade cases pass locally in 1.04s with their original
backup, content, schema, foreign-key and replay assertions unchanged. No production
code, schema migration, client code or acceptance criteria changed in this repair.
Do not treat the failed integration run as a pass.
