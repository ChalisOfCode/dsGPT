# Office validation checkpoint

Item 3 focused acceptance passed on `b83c47f`; integration into main is pending.
The result is bounded tool acceptance, not universal Office compatibility.

Production recipe `7761958a25ecc10f425344037e52d8a5c0f07431acc1e1bc36ca8a2c9b004e2c`
built in run `43276515827` on `9feadb9`, image
`8ca7a8f326a60cd8b61832fe2585bcdba23827fcabbff2f324bb907823a0fdb3`.
Two actual engine checks failed in 7.00 seconds. Calc recalculated the supported
cells to the independent expected values, and the comparison reported a rewrite
of the deliberately unsupported B6 formula. The test incorrectly expected no
changes for that error specimen. Document rendering reached host validation,
which incorrectly imported Pillow despite it not being a host dependency.

The unchanged artifact guard blocked upload because the workflow had not passed
its existing administrative $0 verification variable. No original report ZIP is
available. A private bounded job-log excerpt bundle was preserved (85,272 bytes,
SHA256 `924449c44c4e54e6373e240af71e827c653a3bad8bb7ce940e3c94ab044909f3`).
This does not substitute for rendered-page evidence or a successful engine run.

The correction checks bounded PNG dimensions, framing and chunk CRC with the host
standard library; pixel decoding remains in the isolated renderer. Extraction is
also independently bound to the exact parent bundle/page bytes. The error specimen
must explicitly report the observed B6 change while ordinary specimens must still
preserve formulas/content. The guard receives the same repository variable that
gates runner allocation; neither guard limits nor billing settings change.

Receipt presentation distinguishes calculation, limited structural findings and
exact page-review coverage. Only current saved page paths/hashes with successful
recorded image inspections count. Replaced inputs invalidate descendants; stale
receipts are historical. Coverage does not claim that layout problems were fixed.
Desktop and Android show the summary separately from raw execution details.

49 focused parser, orchestration and receipt checks passed; three opt-in Docker
checks were skipped locally. Local desktop compilation was unavailable because
its dependencies are absent; no dependencies were downloaded locally. Focused
public-runner desktop and Android checks and the corrected engine checks subsequently
passed in `43278654806`. The next engine run also covers malformed PDF, encrypted PDF and active
workbook rejection. Original inputs must stay byte-identical and failed operations
must collect no artifacts. No full suite or model rerun is part of this check.

## Successful focused acceptance

Run `43278654806`, exact `b83c47fc1bc79af0c47c4d8e20110a7a193304bc`,
passed all three jobs. Actual production-image checks passed 3/3 in 12.66 seconds;
desktop TypeScript/Vite and a focused Chrome presentation check passed; Android
app/test Kotlin compiled and its Compose presentation check passed with no skips.
The image was `e2290d365f8caf3deed4ede8fba246b072c5ed39fb8bd1aaa16a238fc00a512c`,
with the same recipe recorded above. LibreOffice reported 7.4.7.2 40(Build:2).

All six hash-checked page images were individually inspected after retrieval.
The two-page DOCX and its independently rendered PDF preserve readable headers,
footers, table label/value, image and page break. The first slide is readable;
the second deliberately clips beyond the right canvas, and its structural report
correctly identifies that unresolved defect. Rendering success does not label that
slide good. These development-review observations do not fabricate a local-model
vision result or alter immutable reports that say visual review was not performed.

Calc replaced deliberately wrong caches with independently expected dependent and
cross-sheet values 21 and 23, Unicode text and date serial 45293. The normal specimen
preserved formulas/content. The error specimen reported division by zero, an
unsupported function and its B6 formula rewrite, retaining `errors_or_changes`.
Malformed/encrypted PDF and active workbook rejection, original byte preservation
and owned-container cleanup passed. Formatting fidelity remains unverified.

The original artifact is 122,832 bytes, SHA256
`58a9bd0c5ec336d7ea3c3bbd6fd48c6244e18708e069593d98a6c7918f3566a9`.
It and bounded client/engine logs plus visual observations were privately preserved
in a 231,556-byte bundle, SHA256
`745266a9ccbdacef560e3583eb17efae568500aa199a26c1123485d1635f484e`.
Two additional host orchestration checks interrupt each new office action, hold
cleanup in failure, then recover: no artifacts/validation, no replay and original
bytes retained. The focused office module passes 10 checks in 0.25 seconds. This
uses an explicit sandbox fixture; it is not an additional real-engine run.
