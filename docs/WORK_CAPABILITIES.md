# Work capability requirements

The acceptance target is every practical ChatGPT Work capability the owner has
actually used in accessible prior chats, with local inference and no paid model
API. Do not reduce this to APK scaffolding or a single preliminary search. New
evidence from those chats expands this checklist. This document distinguishes
tool availability from successful autonomous execution by the selected model.

The owner's long conversational requests, screenshots, corrections, logs and
follow-up changes are normal inputs. Preserve exact requirements, unrelated code,
existing settings and signing identities. Finish with usable files, observed
validation and clear remaining checks. Setup and dependency provisioning should
be automatic where the operating system permits it.

| Required workflow | Current implementation | Acceptance evidence still needed |
| --- | --- | --- |
| Research, cross-reference sources, explain uncertainty and deliver cited findings | Public search/page reader, source snapshots, exact URL provenance, ongoing `search_web` / `open_url` actions | Live public search/read checks passed; local-model research used controlled source fixtures. Inaccessible pages remain reported failures |
| Re-search when new errors, questions or conflicting evidence appear | Research tools are available throughout Work with durable receipts | Qwen3.5 9B abliterated performed two distinct searches, source reads and cited drafting with resume (0.8 evidence); search fixtures were controlled, not live internet |
| Build Android companions and Windows programs from long requests | Exact specification ledger, Kotlin/Compose and native C++ recipes, current-source completion gates | Complex feature completeness and actual Windows/Pixel behavior remain separate checks |
| Repair apps using compiler and runtime diagnostic logs | Source inspection, targeted edits, sandbox execution, paginated logs, repeated build/test cycle | Binary paths now use the same inspect/edit/test loop; individual apps still need runtime validation |
| Inspect/decompile existing apps and make narrow changes | Apktool/JADX decoding, exact smali/resource edits, rebuild and persistent task signing; Ghidra native PE decompilation, monodis IL, guarded byte patches and IL rebuild | Original publisher signatures cannot be reproduced; native pseudocode is not automatically a rebuildable original project |
| Read documents, scanned PDFs, screenshots and Office inputs | Resumable Work inputs up to 256 MiB each / 512 MiB total; original retention; isolated paged PDF/Office extraction and OCR; image review | Four inputs per task, 512 MiB expanded archive limit; extraction does not certify visual layout or recalculate formulas |
| Browser inspection and UI/regression checks | Isolated local Chromium with click/type, screenshots and page/control reports | Scoped owner account handoff, encrypted profiles and task/device plain-text read grants also passed focused acceptance; arbitrary account/site automation remains unsupported |
| Create and deliver an animated GIF | Pillow is installed in the isolated tool image; generated scripts can export files | Inputs and previous tool outputs are available in each isolated run; inspect the generated animation before claiming visual quality |
| Analyze uploaded/linked videos to derive UI requirements | Uploaded/direct-public-linked files, video metadata, timestamped storyboards/OCR, local vision, repeated narrower sampling, FFmpeg exports and local English speech transcription with JSON/SRT timestamps | Frame sampling is not every-frame understanding. Speech recognition can mishear names/code/noise; no speaker identification. Links must serve direct public files, not authenticated/DRM players |
| Preserve progress and deliver installable files after failures/restarts | SQLite checkpoints, immutable tool receipts, source exports, artifact downloads, per-project signing | Migration, interrupted operations and native installer verification on each release |
| Cross-device use, diagnostics and update delivery | Persistent Tailscale route reuse, authenticated phone heartbeats, credential refresh on Android resume, preserved app pairing when ADB is offline, wireless APK updates | Actual device availability cannot be inferred from a backend-only test |

The public checklist retains software-building, research, media, document and
browser requirements without publishing the owner's project names or conversation
history. Historical examples remain in the private archive. New acceptance results
must identify their synthetic fixture and exact source version.

Do not declare full capability parity while rows remain unsupported or untested.
No local tool upgrade reproduces proprietary hosted reasoning or grants access
to another product's account connectors. Decompilation does not guarantee
original-source recovery; changing an APK does not provide its publisher's key.

## Ongoing public research contract

Web Auto can choose research throughout tasks without attached files. With files,
automatic external queries stay off unless the owner chooses Web On. Web On
permits queries derived from task context and errors. The interface explains this
before submission. Web Off rejects model-generated searches and page opens on
the server. A separately entered public query retains its existing narrow scope.

The model can search, read, revise a hypothesis, edit, test and search again.
Source snapshots retain URLs, timestamps and content hashes. Search engine
failures and blocked page reads are visible tool results, never successful
evidence. Removed sources are not resurrected through search or receipt replay.
Public retrieval uses HTTPS, public-address validation and no cookies/credentials.
Current task resource bounds are 64 agent searches and 256 retained sources;
reaching a bound is explicit. It is not an unlimited background crawler.

## 0.9 connection and chat behavior

Desktop and Android expose sidebar, New chat, current title and chat actions.
Rename, Pin/Unpin, Files and Delete are available from the header and chat list.
Delete removes the chat and its messages/attachments from the live database;
explicit saved memories and existing backups remain.

A valid paired phone can be offline without requiring pairing again. The desktop
shows connected only with a recent authenticated heartbeat. Wireless debugging
is used for APK installation/update, not ordinary HTTPS chat over Tailscale.
An app update reloads changed credentials when the Android UI resumes. Physical
Windows/Pixel reconnection still requires checking on the owner's devices.

## 0.9.1 media work

Chat research now budgets the full serialized request, including source metadata,
JSON escaping, output space and one reusable validation-repair instruction. It
reduces optional evidence excerpts instead of rejecting a short question after
retrieving six pages. Exact questions and full saved sources are retained. If only
some source excerpts fit, the answer says so and citation IDs are restricted to
the included sources. Prior image costs are counted when selecting optional chat
memory. An actual Qwen3.5 9B abliterated run completed a short question with six
controlled retrieved sources at 8192 context / 1024 output. This was not a GPU
benchmark or a live-internet test.

`download_file` is available only with isolated Work and enabled Web. It streams
public HTTPS bytes through the same IP-pinned transport as research, rejects
private addresses/redirects, HTML players and encoded/oversized responses, and
retains exact bytes, source/final URLs, retrieval time and SHA256. Task revision
and Web permission are rechecked before saving. Cancellation/late results leave
no input; durable receipts prevent repeating a completed network request. Limits
remain four inputs, 256 MiB each, 512 MiB total. Existing names are immutable.

`audio-transcribe` decodes uploaded/downloaded audio or video inside the offline
container and runs Vosk locally on CPU. Setup provisions the pinned speech wheel
and English model automatically. Each 1..900 second window returns timestamped
JSON, SRT subtitles, an explicit next-start pointer and recognition-confidence
metadata. The model can page saved results and combine speech with video frames.
Only the requested window has been transcribed; longer recordings need follow-up
windows. Real local known-speech and narrated-video checks passed; release-specific
Docker/public-network and local-agent evidence is recorded with the installer.
The earlier 0.9.1 model-driven media run produced a transcript but did not
complete SRT delivery. The 0.9.2 completion result below supersedes that failed
short-fixture test; it does not establish reliability for arbitrary media tasks.

Work instructions are compacted and the latest tool result is prioritized on
small model contexts. Exact requirements remain saved and paged. The bundled
asset guide does not count as a private attachment that disables Web Auto.

## 0.9.2 media completion

`transcribe_media` accepts an exact saved input/receipt path and an optional time
window. The backend supplies the isolated command, retains both JSON and SRT,
checks the source hash and time range, and reports the saved paths and next window.
The model no longer needs to invent the worker command or remember to collect both
outputs. The original typed action is retained for restart recovery. No host-shell
or external speech API fallback is added.

`read_asset` pages saved UTF-8 input/receipt text directly, with byte offsets and an
explicit end-of-file pointer. Original requirements also expose an explicit end of
each page sequence. Complete saved pages are supplied whenever they fit. After
both short transcript/subtitle outputs have been requested, their current
hash-checked contents are kept together for comparison if the full pair fits
with the output reserve. This avoids displacing one file every time the other
is read. Larger or incomplete results retain exact page continuation instead.
Requirement coverage can cite current successful artifact receipts as well as project files; its digest binds the current source and exact
receipt identity/hash. Deleted, replaced, failed, stale and foreign-task receipts
cannot certify completion. This allows file-only tasks to finish without creating
a pretend source file. These checks establish delivery evidence, not recognition
accuracy or arbitrary-task model reliability. The current model-facing asset
catalog exposes at most 16 saved receipt paths. Long workflows spanning many
transcription windows remain unverified; each action covers at most 15 minutes.

When all requirements have current reviewed evidence and the requested outputs
are ready, the model is asked to finish or report a remaining blocker. It cannot
keep rereading already reviewed files in that phase. Completion still runs the
existing file and evidence checks; stale, missing or unreviewed evidence restores
the normal tools. The software does not fabricate a model answer or automatically
mark requirements covered.

Empty completed inference responses now stop with `empty_model_response`, or
`output_limit` only when the runtime explicitly reports length exhaustion. Work
checks empty/whitespace replies before parsing action JSON, preserving saved
progress without invalid-action retries. Existing desktop and mobile clients
receive an explanatory blocker while the session retains its machine error code.
This does not establish why any particular owner runtime returned an empty reply.

Scoped authenticated account workflows and bounded independent document rendering/
recalculation have focused acceptance recorded in the completion plan. Remaining
ordered work includes editable related-project grouping and disposable software
upgrade/reconnection and diagnostic acceptance; physical hardware remains optional. Release validation records the separate real-model and
isolated-tool results; no claim of complete hosted Work parity is made.

An actual Qwen3.5 9B abliterated workflow completed the short media task across
a saved-checkpoint resume after the completion-handoff fix: it downloaded
the controlled WAV response, used the typed transcription action, read the saved
outputs, recorded artifact-backed coverage and finished with both JSON and SRT.
Known spoken words and timestamps were checked independently. This used real
local CPU inference and Vosk with a reviewed local command fixture; separate CI
passed live public download and Docker isolation. The 8 GiB test host used reduced
runtime caches. This is not an RTX 3080 Ti speed test, a long-recording test, or
proof that the model can autonomously finish every requested application.


## Bounded document validation

Work can render DOCX/PPTX/PDF, recalculate supported XLSX formulas with actual Calc,
and expose an exact hash-checked rendered page for vision review. Inputs are copied,
never overwritten. Reports preserve source/output hashes, engine/font details,
structural findings and exported formula errors/changes. Execution receipts bind
the production image; retain them with reports. Limits are explicit: 32 MiB input,
128 MiB expanded package, 20 rendered pages, 32 sheets and 20,000 inspected cells.
Active/external dependencies and unsupported formula representations fail closed.
Desktop and Android distinguish calculation from visual review and historical
receipts. Successful rendering or complete review coverage is not proof of correct
layout. The selected runtime must advertise vision for model image inspection.
Representative production-engine evidence and independent page review passed in
`43278654806`; this does not certify arbitrary Office files or pixel-identical
Microsoft Office formatting. See the office checkpoint for exact boundaries.
