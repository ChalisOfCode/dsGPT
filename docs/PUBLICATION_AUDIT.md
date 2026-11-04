# Public snapshot review — 2026-11-03

## Source and history boundary

Source archive: `ChalisOfCode/dsGPT-development`, branch `stage5/audit`, commit
`c7c554aaf1b82a8fc5769df5d8925f21dc9b9d4a`. All 16 branch heads were compared.
This branch contains the latest product fixes. The only divergent commit on `main`
retires older cloud workflows; it adds no newer product implementation. The newer
local-worker work remains preserved in the private archive, with its execution
policy superseded by the explicit public/free-build authorization.

427 selected source/document blobs were recovered and matched their Git blob
hashes. The complete original tree inventory was retained privately. Publication
uses a clean snapshot and fresh Git history, not a fork or history-preserving push.
The private archive's visibility/history are not changed by this preparation.

The adjacent `PUBLICATION_FILES.sha256` identifies each reviewed publication file
by relative path and SHA-256, excluding only that checksum file itself. The final
commit ID and whole-tree identity are recorded in the migration handoff. Source
changes after this inventory require a new review; tests are not security proof.

## Scope and exclusions

Review covered the selected backend, desktop/Android clients, APIs, configuration,
dependency locks, build/test/installation scripts, synthetic fixtures, documentation,
assets and the newly consolidated workflows. Required vendor licenses and notices
remain included. The three necessary binary assets were individually reviewed:
the Gradle wrapper, small srt wheel and application icon. Embedded document/image
fixtures were decoded, their document metadata/content inspected, and their raster
content rendered/viewed. They contain synthetic sentinel text, not personal files.

Excluded from publication: private Git history; historical `reports/` and `research/`;
task-state records; recovery journals; the original personal specification/chat
brief; superseded handoff/benchmark/diagnostic reports; old workflow copies and the
retired private-PC worker; obsolete checkpoint/history-export tools; prior release
ZIPs/EXEs/APKs; runtime/model downloads; data stores, account sessions, personal
device information and all private signing material. The source remains available
in the private archive. Public requirements/status documents replace private
conversation-derived handoff prose without dropping the remaining product scope.

## Methods and findings

Two independent open-source secret scanners were used: **Gitleaks 8.30.1** (official
release archive digest verified) and **detect-secrets 1.5.0**, with remote secret
verification disabled. Scans operate on the full publication candidate, not only
changed lines. Scanner findings were reviewed in context; raw reports remain private.

- Gitleaks found no secret matches in the sanitized candidate. Its earlier 11
  findings in excluded historical state records were hashes keyed by API filenames,
  not active API credentials.
- detect-secrets flags in the candidate were reviewed as public dependency/source
  digests and certificate fingerprints; deliberately invalid authentication URLs
  and redaction sentinels; eight encoded synthetic document/image fixtures; and an
  incomplete private-key header containing the literal test marker `HIDDEN`.
  No usable private key is present in that fixture. Counts and individual
  dispositions are recorded in the private review evidence; findings were not
  dismissed merely because they occurred in tests.
- Manual review checked addresses, URLs, emails, user/workspace paths, configuration
  defaults, fixture text/metadata, release provenance and the workflow trust boundary.
  Private project names were removed from capability documentation. Historical
  Windows build IDs/hashes were replaced with current-source artifact manifests.
  Remaining loopback/private-address examples are synthetic security/network tests,
  not observed device addresses. Public package URLs/integrity hashes remain.
- The original Android signing backup was verified against the previously delivered
  APK's public certificate fingerprint. Private key/password bytes stay outside the
  publication tree and outside CI artifacts. Production packaging now rejects a
  missing, stale or different-key APK receipt; test APKs have a separate package ID.
- The Gradle wrapper matches the official 8.13 checksum. The srt wheel's Python
  modules and license match its pinned upstream source. Existing license notices
  were preserved. The icon and fixture images contain no private photos/metadata.

## Limits

This is a publication/privacy and credential review, not a complete vulnerability
assessment, penetration test, legal audit or guarantee that the entire application
is secure. It does not certify the excluded private history. Dependency hashes
establish byte identity, not absence of vulnerabilities. Encoded/binary review is
limited to the necessary assets described above. Physical device behavior and new
GitHub executions require separate actual evidence. Preparing guarded workflows
does not establish that account billing, private Actions disablement or public
repository creation has already been verified.
