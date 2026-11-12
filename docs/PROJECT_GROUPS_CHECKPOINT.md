# Related project groups checkpoint

Item 4 implementation is isolated on `work/project-groups-111df67`. Native/browser
acceptance is pending; do not mark the item complete from backend fixtures alone.

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
