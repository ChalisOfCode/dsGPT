> Workflow update (2026-11-03): public standard GitHub runners and emulators are
> the routine test/build path. Owner hardware is optional for targeted observations;
> it is not required for development or packaging. Earlier physical release-gate
> language below is historical design context, superseded by the completion plan.

# Document and owner-device validation design

Status: read-only design, 2026-11-03. These capabilities are not implemented or
accepted by this document. The owner requested completion in order: item 1, then
items 2 through 5, and no next upgraded ZIP until all five are complete. Item 3
implementation follows item 2; item 5 implementation follows item 4. Preparation
here does not change that order or claim access to the owner's Windows PC/Pixel.

## Item 3: document layout and spreadsheet calculation

### Existing integration points

| Component | Present behavior | Planned integration |
| --- | --- | --- |
| `document_worker.py`, `document_processing.py`, `documents.py` | Attachment text/OCR extraction; cached spreadsheet values; bounded originals | Keep extraction separate from validation and retain its existing notices |
| `work_uploads.py`, `work_assets.py` | Large Work originals, exact hashes, current receipt lookup and snapshots | Validate saved `inputs/` and `receipts/` paths without routing large inputs through the 512 KiB attachment API |
| `tool_image.py`, `execution/Dockerfile`, `tool_setup.recipe_files()` | Reviewed offline image with Poppler, Pillow and Tesseract | Add trusted validation worker, LibreOffice Writer/Impress/Calc, Python UNO and a recorded font set; bind results to the immutable image and recipe |
| `project_tools.py`, `builds.py`, `work.py`, `work_assets.GUIDE` | Typed actions, isolated execution, saved outputs, paged model context | Add bounded document-render and workbook-recalculation actions with independently checked reports |
| `WorkRegistry._inspect_asset_image()` | Saved PNG/JPEG review, maximum 4 MiB, Ollama vision required | Review rendered document pages and retain image/source hashes and exact page coverage |
| `api.py`, client capability/result displays | Extraction readiness and generic Work evidence | Show rendering, structural checks, visual review and calculation as distinct outcomes |

Proposed dependencies must be resolved against the reviewed base image and tested;
none were installed during this design review. Record their actual versions and
fonts in the resulting image instead of implying that an apt install alone proves
reproducibility or document compatibility.

### Rendering and visual checks

1. Load a copy of DOCX/PPTX with LibreOffice in the existing checked, networkless
   container. Use a fresh writable profile under `/work`, disabled macro execution,
   disabled linked-document updates, bounded execution and owned-process cleanup.
   Export a separate PDF. Existing PDFs go directly through Poppler.
2. Render the actual PDF pages with Poppler. Preserve original bytes and record
   input/export/image hashes, page numbers, dimensions, renderer versions and font
   inventory. Validate page bounds and reject malformed, encrypted or excessive
   inputs explicitly; do not silently skip pages.
3. Keep the generic two-artifact limit. A bounded render bundle plus JSON manifest
   can retain the PDF and page images. A separate checked page-extraction action
   can expose a saved PNG for `inspect_image`; verify the bundle/member hash,
   decompressed size and page identity. Full-resolution evidence stays available
   even when a smaller review image is required.
4. Add structural checks such as invalid page geometry, elements outside a slide
   canvas and suspicious blank pages. Report these as limited checks, not proof of
   good layout. Review rendered page images for clipping, overlap, readability and
   missing content. Record every reviewed page and any unresolved finding.

Use separate results: `rendered`, `structural_checks_completed`,
`visually_reviewed_pages` and unresolved issues. The current native text-only model
cannot inspect images: `inference.py` requires an Ollama runtime advertising vision.
Absent vision leaves visual review unperformed; text extraction or OCR cannot
substitute for it. LibreOffice rendering does not establish pixel-identical
Microsoft Office behavior, and font substitution must be disclosed.

### Real workbook recalculation

Use LibreOffice Calc through UNO, call `calculateAll()`, inspect formula-cell
errors with `getError()`, and save a new XLSX rather than overwrite the original.
Reopen the result and independently inspect exported formula/cache values.
Successful conversion, `fullCalcOnLoad`, or reading `data_only` values is not proof
of recalculation. Report formula counts, error cells, changed formulas/non-formula
content, external dependencies, unsupported features and relevant number formats.
External links and active content must not be executed or refreshed implicitly;
unsupported dependencies remain explicit rather than becoming a false pass.

Calculation reports bind the original, output, engine version and recipe hashes.
Current-source evidence rules must reject replaced outputs and stale validation.
An engine accepting a workbook does not guarantee support for every Excel function
or preservation of all Excel-specific formatting/features.

### Required acceptance evidence

- Actual LibreOffice/Poppler rendering of DOCX with tables, headers/footers, images
  and page breaks; PPTX with known slide count and an intentionally overflowing
  shape; and PDF with known page sizes. Inspect the resulting page images.
- XLSX with deliberately incorrect cached values, dependent and cross-sheet
  formulas, Unicode/string/date results, division by zero and unsupported formulas.
  Compare recalculated results against independent expected values, including the
  exported workbook, not just an engine success code.
- Exact original preservation, bounded traversal of every page, stale-receipt
  rejection, malformed/encrypted input handling, interruption and cleanup failure.
  Failed or partial rendering/calculation must never be labeled verified.

### Official documentation consulted

These sources establish engine interfaces, not a completed dsGPT integration:

- [XCalculatable: calculateAll](https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1sheet_1_1XCalculatable.html)
- [XCell: formula, value and error access](https://api.libreoffice.org/docs/idl/ref/interfacecom_1_1sun_1_1star_1_1table_1_1XCell.html)
- [MediaDescriptor: load and save properties](https://api.libreoffice.org/docs/idl/ref/servicecom_1_1sun_1_1star_1_1document_1_1MediaDescriptor.html)
- [MacroExecMode](https://api.libreoffice.org/docs/idl/ref/namespacecom_1_1sun_1_1star_1_1document_1_1MacroExecMode.html)
- [UpdateDocMode](https://api.libreoffice.org/docs/idl/ref/namespacecom_1_1sun_1_1star_1_1document_1_1UpdateDocMode.html)
- [Headless startup and isolated user profiles](https://help.libreoffice.org/latest/en-GB/text/shared/guide/start_parameters.html?DbPAR=BASIC&System=WIN)

## Item 5: disposable software acceptance and optional hardware diagnosis

### Reusable checks and their limits

| Component | Reusable behavior | Evidence still missing |
| --- | --- | --- |
| `scripts/acceptance/__main__.py` | Atomic reports, dependency checks, real WebView, GPU residency, Pixel instrumentation, actual Tailscale HTTPS | Uses a synthetic backend and separate acceptance package; does not prove the owner's production upgrade |
| `scripts/check_application_install.py` | Managed backend, Windows vault wiring, owner/reply persistence | Fresh CI-user assumptions need an owner-safe upgrade mode |
| `scripts/application/__main__.py` | Reused HTTPS route, authorized Pixel discovery, `adb install -r`, verified phone identity | Measured old-to-candidate production upgrade/reconnection |
| Android `Vault`, `automaticConnection`, `restoreUpdatedConnection` | Credential storage/reuse and live reload | Physical device checks after real update and interruption |
| `scripts/check_complex_app_runtime.py` | Exact installed APK bytes and native controls/data persistence | Android deliberately refuses physical devices; retain that default protection |
| `diagnostic_details.py`, `hardware.py`, `LocalInference.stream` | Sanitized Chat metrics, hardware measurements and classified errors | Work loops discard context/runtime metric events, leaving empty Work responses without per-attempt evidence |

The existing phone harness reinstalls the same acceptance APK. Its result is not a
production old-version-to-candidate upgrade result. `CLIENT_ACCEPTANCE.md` also
contains older version-specific instructions; update its claims with the final
implementation and actual acceptance evidence.

### One-run owner acceptance pipeline

1. **Protected baseline.** Verify candidate hashes, installed versions, Android
   package and signing identity. Keep identity comparisons private; export only
   sanitized outcomes. Back up SQLite safely and inventory preserved chat, memory,
   Work and model state without exporting contents. Wait for active work before
   upgrading; never clear production app data or unrelated processes.
2. **Windows upgrade.** Install the candidate over the current installation. Verify
   expected version/schema, original owner credential, retained records/model
   registrations and a fresh benign reply through the real client. Restart only
   owned backend/client processes and verify restoration. Actual reboot/logon is a
   separate measured phase; process restart cannot pass it.
3. **Pixel update and reconnect.** Require the same signing identity, update with
   `-r`, and verify the same backend device ID. Require a new heartbeat after the
   update with the candidate app version, not a stale online indication. Exercise
   automatic pairing while the main activity remains alive, then cold reopen.
   Valid credentials must be reused; network/TLS failures must not create devices.
   Never uninstall or clear the original app to bypass a signature mismatch.
4. **Real route recovery.** Interrupt and restore only an owned test route, verify
   reconnect without re-pairing, and prove a phone request over Tailscale without an
   active ADB transport. Preserve unrelated Serve routes and the owner's VPN.
   Local Tailscale `Running` is not phone reachability. Disconnecting ADB is not a
   measurement of Android wireless-debugging battery cost or the toggle itself.
5. **Native generated/modified applications.** Reuse exact artifact hashes and
   Task Ledger's independent behavior/update checks. Add an explicit physical
   fixture mode with a verified selected device and an owned test package; keep
   emulator-only defaults and do not clear pre-existing owner apps. Include benign
   imported APK/EXE modification fixtures through the real asset tools, followed by
   native launch/behavior checks. Source-follow-up success alone does not prove a
   decompile/modify/rebuild path or arbitrary imported-app compatibility.
6. **Runtime diagnosis.** Run benign short Chat, structured Work and short research
   cases with the actual installed model/configuration. Sample RAM/VRAM and digest-
   matched model residency during the requests. Preserve partial and failed
   evidence; classify dependency, transport, loading, inference and tool failures
   separately. Do not substitute a tiny acceptance model for the owner's model.

Reuse the existing report runner's incremental save/recovery and owned cleanup.
Every stage needs `PASS`, `FAIL`, `BLOCKED` or unperformed status; unavailable target
hardware is not a pass. No report is uploaded automatically and no new release ZIP
is produced by this design.

### Work inference evidence to add

Record each actual specification/action/image inference attempt with an attempt ID,
task/step linkage, model digest or reference, frozen runtime/configuration, context
accounting method, output budget, thinking count, first-visible-text latency,
reported token/duration counters, terminal/error code and visible-output byte count.
Retain metrics on empty response, cancellation and failure. Never store prompts,
reasoning text or raw credentials in the shareable diagnostic receipt. Historical
settings must come from that attempt, not today's model registration. Do not infer
token throughput from character counts or substitute wall time for runtime timing.

Physical acceptance requires execution on the owner's actual Windows PC, Pixel and
RTX hardware. This workspace currently has no connection to those devices. Prepare
the concrete candidate/checks first, then obtain the missing device evidence; Linux
fixtures, emulators and CI cannot establish those physical results.
