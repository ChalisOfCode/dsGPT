# Account sessions and project grouping: queued design

**Planning only. Items 2 and 4 are queued until item 1's fresh application/media
reliability work is complete.** This document records source review and proposed
acceptance criteria. It does not claim these capabilities are implemented or
validated. No personal chats, accounts or website credentials were inspected.

## Item 2: signed-in websites and account workflows

### Existing boundaries

- `src/dsgpt/public_browser.py` brokers bounded public GET requests through
  `downloads.PublicHTTPS`, clears cookies, strips authentication state and records
  public rendering receipts. `web_retrieval.py` validates public URLs.
- `src/dsgpt/browser_worker.py` launches an ephemeral Chromium profile in the
  networkless tool container. The Work `browser` action operates project HTML;
  it does not expose an authenticated website session.
- `src/dsgpt/security.py` hashes device tokens and gates device scopes.
  `clients/desktop/src-tauri/src/main.rs` uses Windows Credential Manager for the
  desktop's backend connection. Neither is a website-session vault.
- `src/dsgpt/work_web.py` already has durable action receipts and interrupted-call
  recovery. `api.py` owns service startup/shutdown and owner/work authorization.

### Proposed implementation boundary

Add a dedicated account-browser service using the existing Docker/browser and
public-network validation patterns. Keep the public renderer's current behavior.
Authenticated profiles must stay outside project files, ordinary Work artifacts,
model-accessible tools and diagnostic exports.

| Integration | Proposed responsibility |
| --- | --- |
| New account-session service; `api.py:create_app` and lifespan | Connecting, owner handoff, ready, expired and revoked states; serialize each account; recover and clean up owned browser containers. |
| New owner-only session/control API | Bounded browser frames and input events for interactive login. Owner-entered passwords/MFA codes and login screenshots bypass Work actions, model prompts and persistent receipts. |
| Separate authenticated browser worker | Dedicated profile/container with no project files or shell-tool access. Expose observed element IDs and bounded actions; expose no arbitrary JavaScript, CDP, cookie or storage-reading tool to the model. |
| Scoped request broker; `downloads.PublicHTTPS` | Recheck exact HTTPS origin grants, redirects and DNS-pinned public addresses on every request. Explicitly account for authentication-provider/resource origins and preserve browser cookie/CSRF semantics. |
| New protected session vault; `windows_security.py` | Encrypt clean profile snapshots atomically using current-user Windows protection and protected owned directories. Fail closed if protection is unavailable; never silently save plaintext. |
| `security.py`, task creation and account grants | Bind access to account generation, task and authorized device. General Work permission must not grant every connected account. |
| `project_tools.py` schema and `work.py` dispatch/context | Offer account actions only with a current grant. Return bounded, task-local observations and receipts; never include session secrets. |
| New account-action ledger; `work_web.py` recovery pattern | Bind an action to the page snapshot and session generation. Record an uncertain outcome after an interrupted external write; verify before retrying. |
| Desktop `App.tsx`/`transport.ts`; Android `MainActivity.kt`, `WorkView.kt`, `ChatModel.kt` | Connected-account status, owner handoff, reconnect/revoke, task account selection and explicitly delegated phone access. |
| `migrations.py`, `storage.py`, exports/diagnostics | Separate account metadata, grants and action receipts from encrypted profile blobs. Do not export login state or traffic. |

Reuse a dedicated browser profile rather than importing the owner's everyday
Chrome profile. Chrome's [remote-debugging guidance](https://developer.chrome.com/blog/remote-debugging-port)
separates debugging from default profiles. For Windows,
[CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
documents user-bound encryption and integrity protection; avoid machine-wide
protection and interactive DPAPI prompts. Linux fixture tests cannot substitute
for native Windows protection tests.

### Constraints that affect the design

- GET-only is not a reliable definition of read-only. Some applications read through
  POST/GraphQL, and some links cause changes. Supported operations need explicit
  rules or an owner-reviewed action boundary. Existing task authorization can cover
  its requested operation without approval for every mechanical click.
- Account access does not implicitly authorize publishing private content through
  public search, automatic memories or unrelated tasks. Keep account observations
  task-local; preserve existing object permissions and bounded context retrieval.
- Existing device revocation blocks new API requests but accepted Work can continue.
  Account grants therefore need a generation checked before every browser/network
  action. Revocation must stop active sessions and invalidate pending actions and
  stale receipts.
- Cookies alone do not preserve every sign-in. Test local storage, IndexedDB and
  actual Chromium profile restoration. Snapshot only after a clean browser stop.
- Local disconnection deletes local session material; universal provider-side
  logout cannot be promised. Previously copied task content needs separate deletion.
- CAPTCHA, MFA, passkeys, consent screens, expiry and login restrictions require
  owner handoff. WebSockets, service workers, complex federation and anti-automation
  checks require explicit compatibility tests. Do not promise every website works.

### Acceptance cases

Use a controlled HTTPS application with real Chromium and an independently checked
server state: owner login; private read; cookie/local-storage/IndexedDB restoration
after backend restart; expiry and reconnect; CSRF and redirect handling; authorized
update; interrupted-write recovery without duplicate effects; revocation during an
active request; cross-task/device denial; and rejection of stale page/session grants.

Plant credential/token sentinels and prove their absence from model inputs,
SQLite/WAL, logs, source/artifact exports and diagnostic bundles. On Windows, test
real protected storage across process restart, tampering and protection failure.
Fixture success establishes that workflow, not universal account compatibility.

## Item 4: deterministic project grouping

### Existing behavior to preserve

- `history_archive.py` imports supported visible text from the active branch, records
  omissions and hashes normalized conversation identity. The original archive stays
  untouched at its selected path; no internal raw-archive copy is retained.
- `history.py` provides atomic imports, retry receipts, source versions, duplicate
  detection, removal tombstones and explicit memory copies.
- `history_import.py` and native `history_ui.rs` provide local selection and
  hash-bound preview/apply. `HistoryImport.tsx` shows the preview and omissions.
- `work_uploads.py` and `work_inputs.py` preserve Work original bytes and hashes.
  Unclaimed upload IDs expire and are removed after task creation.
- `memory.py` scopes memory to personal use or one Work task. Current “projects” are
  Work tasks; there is no independent project-group entity. The `collections` table
  belongs to diagnostics and must not be repurposed.

### Proposed grouping rules and storage

Create editable suggestions over references to existing objects. Rank evidence as:

1. Explicit, supported project metadata or a reviewed import mapping.
2. Exact distinctive repository URL, non-placeholder application ID or validated
   package/project name within the selected content.
3. Distinctive title/artifact-name matches, shown as weaker suggestions.
4. Conflicting or generic names remain ungrouped with alternatives for review.

Do not assume arbitrary export fields identify projects. Generic names such as
“Continue”, “Update”, `main.py` and `app.apk` do not connect unrelated content.
Show the actual matching evidence and descriptive categories, not invented
probability percentages. Normalize comparison keys only; retain original text.

Three small tables are sufficient for a durable first version:

- `project_groups`: stable ID, display name, revision, timestamps and deletion state.
- `project_group_links`: object identity, source hash/version, group, accepted/rejected
  decision, grouping-rule version and evidence references.
- `project_group_requests`: stable request ID, full input/decision hash and applied
  result IDs for atomic, repeatable operations without resurrecting deleted objects.

Compute proposals on demand. Bind preview/apply to source versions, rule version,
group revisions and user corrections. Retain explicit rejection/ungrouped choices.
Keep grouping metadata outside normalized conversation hashes: adding a hint must
not turn an unchanged old import into a different source version.

| Integration | Proposed behavior |
| --- | --- |
| `history_archive.py` and new grouping planner | Extract inert, bounded hints separately from imported text identity. Never execute archive content or use it as model instructions. |
| `history.py` and import CLI/native bridge | Apply reviewed links with the import transaction and retry identity; retain existing duplicate/tombstone rules. |
| `HistoryImport.tsx` | Suggested/existing/new group, explanation, corrections and “Leave ungrouped.” |
| `work_uploads.py`, `work_inputs.py`, task creation | Hash-bound proposals map to permanent Work inputs after creation, not expiring uploads. |
| History search and desktop/Android recall views | Group browsing and bounded group-filtered retrieval with original provenance and object permissions. |
| `Memory` and `History.promote` | Keep copying into memory explicit; grouping does not silently promote messages or broaden memory scope. |

### Versions, ambiguity and preservation

Same source ID/hash remains a duplicate; changed content under the same source ID
remains a preserved version. Identical text under different IDs is only a possible
duplicate. Same filenames with different hashes remain distinct and are never
overwritten by grouping.

A multi-project conversation remains intact. Permit explicit multiple links or
selected-message links rather than rewriting/splitting the original automatically.
Renaming/moving groups changes references only. Source removal must invalidate links
and clear retained source-derived excerpts; cached apply results must not restore
removed content. Validate permissions for each referenced chat/task/file.

If managed preservation of the full history archive is required, retain a verified
immutable owned copy and reference it from `history_batches`; update the import UI
to describe that new behavior. Do not present normalized imported text as a complete
archive backup. Grouping does not itself increase existing archive/import limits.

### Acceptance cases

Use synthetic archives/files covering explicit mappings, exact identifiers, weak
names, conflicting projects, mixed-topic chats, manual correction and rejection,
repeat imports, changed versions, identical text with different IDs, duplicate
filenames, Unicode and input-order independence. Verify stale-preview conflicts are
atomic; decisions survive restart; source removal/retries cannot resurrect links;
and original bytes, normalized hashes, messages and existing memories are unchanged.

Include malicious instruction-like text, unsupported metadata and unsafe ZIP members.
Exercise desktop review/correction and phone group browsing with permission checks.
No user data was grouped or inspected for this source review.
