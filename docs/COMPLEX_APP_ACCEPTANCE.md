# Long-request application acceptance

This acceptance fixture is **Task Ledger**, an offline Android/Windows task app.
The initial request is over 9 KB and covers editable records, notes and priority,
search plus completion filters, validation, Unicode, counts, versioned transactional
persistence and accessible native controls. A follow-up adds Clear completed while
preserving the original data format, IDs and Android signing identity. The fixture
is a bounded reliability test; passing it does not prove arbitrary-app completion.

Three independent stages must remain separate in reports:

| Stage | Inputs and execution | What a pass establishes |
| --- | --- | --- |
| Reviewed tool validation | `complex_app_fixture.py` supplies reviewed source; actual compilers and fixed behavior tests run | The toolchain can compile, test, repair and preserve signing for this fixture. This is not model evidence. |
| Fresh model workflow | `live_complex_app_model.py` supplies only the saved request, then forwards actual local-model actions through Work and Docker | A fresh task on one backend source version generated both applications, survived backend restart, passed independent behavior tests and completed a follow-up repair. Native UI checks remain pending. |
| Native UI acceptance | `check_complex_app_runtime.py` operates the produced EXE or APK using real Windows controls or an explicitly selected Android emulator | The exact binaries expose working controls and retain data through process restart and an in-place update. |

The fixed external domain oracle checks 16 initial cases and 18 follow-up cases in
both Kotlin and C++. It includes golden serialization bytes, malformed-import
preservation, Unicode, validation without mutation, ID allocation, editing, toggling,
search and counts. The model's own test names or success statements cannot replace
these tests. The actual-model harness overlays the reviewed tests on a separate
copy inside Docker, requires their exact JUnit report and C++ completion marker,
and leaves the model's saved project unchanged.

The actual-model harness starts with a new state directory and refuses an existing
one. It uses the ordinary task API for the initial request, pause/resume and
follow-up. A deliberate backend close/reopen preserves the saved requirement,
source, artifact and signing-key hashes. All initial model decisions and tool
results are real. After the initial delivery, the harness appends one declared
user-side `#error DSGPT_ACCEPTANCE_REPAIR` line to Windows source, then sends the
follow-up request through the normal revision API. A repair pass requires the actual
compiler diagnostic followed by a successful build; the injected edit is recorded
separately and is never attributed to the model.

## Prepared-host commands

Use an already prepared immutable Docker image ID, a loopback local inference
server, and new state/output directories. This does not install a model or replace
the owner's project. Ollama residency is released before compilation by default
to reduce simultaneous memory pressure; generated actions and returned events are
not modified. The report records that runtime policy.

```bash
python -I scripts/live_complex_app_model.py \
  --image "$DSGPT_IMAGE_ID" \
  --source-commit "$DSGPT_SOURCE_COMMIT" \
  --model huihui_ai/qwen3.5-abliterated:9b --abliterated \
  --model-digest 4290bae9417b9d17bf08ec2cc821c4f6b7de2cea710bec968db87e95c88a0997 \
  --endpoint http://127.0.0.1:11434 --context 16384 --output-tokens 4096 \
  --cpu-threads 2 --batch-size 64 \
  --state /tmp/dsgpt-complex-model-state \
  --output evidence/complex-model.json --artifacts evidence/model-apps
```

The timeout and step budget are explicit. Reaching them pauses the task and records
a failure; it never fabricates completion. Model load failures, compiler failures,
invalid actions and missing native stages are retained as failures or pending work.
No model-generated host commands run as a substitute for Docker.

The optional full `--source-commit` label identifies the tested remote source when
the local checkout was reconstructed; the report separately preserves the local
Git commit and hashes every backend Python module, the harness and both requests.
Changes to those hashes invalidate the run. Explicit CPU controls change only
Ollama's thread count, batch size and memory mapping; the report records the actual
request options, thinking control and output budget. Prompts and model actions
are not replaced by the acceptance scripts.

## Dedicated CI workflow

`complex-app-acceptance.yml` runs only on manual dispatch after zero-cost controls are verified. Its first job prepares CPU-only files from the verified Ollama 0.40.13 archive,
pulls the selected 9B tag, then
rejects it unless the manifest digest matches the pin above. It verifies process ownership and effective cgroup memory, performs an actual
cold-load probe, unloads the model, then builds the exact Docker toolchain.
It records actual runner resources and runtime inputs. The model gets a five-hour deadline within
a six-hour job; an exhausted budget is a failed acceptance attempt.

The CPU run uses four inference threads, a batch size of 64, a 16,384-token context,
a 4,096-token output allowance and one loaded model. Residency is released before
compilation. Every generated compilation and independent test runs through the
production Docker boundary. Subsequent disposable Windows and Android emulator
jobs operate the exact initial and updated binaries. The final job joins all
three reports and checks their artifact hashes. A model pass alone does not produce
the combined acceptance result. The workflow does not create a release ZIP.

This workflow is an acceptance mechanism, not a statement that the new model/native
run has passed. Passing the fixed reviewed fixture cannot substitute for this run.

The reviewed fixture can run through the production Docker boundary:

```bash
python -I scripts/live_complex_app_tools.py \
  --image "$DSGPT_IMAGE_ID" --output evidence/reviewed-complex-tools
```

A host with the previously prepared SDK, Gradle/cache, JDK and MinGW tree can instead
run **only the reviewed fixture** with `--local-toolchain /path/to/local-toolchain`.
That report explicitly says `model_driven: false` and `isolation: false`; a Store
reopen is not represented as a process or operating-system restart. This mode does
not accept generated source. It reuses the prepared dependency cache rather than
copying several gigabytes into each output directory.

## Native execution and proof joining

Use disposable CI workers. Existing Stage 3 CI already prepares the offline Docker
app toolchain. Existing native client CI does not automatically test generated apps;
run the following commands on the actual produced binaries as a separate stage.
The Android serial must be an emulator, and the package is the generated
`com.dsgpt.generated.p` application ID followed by its task UUID without hyphens.

```bash
python scripts/check_complex_app_runtime.py --platform android \
  --serial emulator-5554 --package "$DSGPT_GENERATED_PACKAGE" \
  --initial evidence/model-apps/initial/artifacts/dist/app.apk \
  --updated evidence/model-apps/followup/artifacts/dist/app.apk \
  --artifact-origin model-generated --output evidence/android-native.json
```

On a Windows CI worker:

```powershell
python scripts/check_complex_app_runtime.py --platform windows `
  --initial evidence/model-apps/initial/artifacts/dist/app.exe `
  --updated evidence/model-apps/followup/artifacts/dist/app.exe `
  --artifact-origin model-generated --output evidence/windows-native.json
```

The UI scenarios check actual controls, blank rejection, search, edit identity,
completion filters, deletion, monotonically allocated IDs, process restart and
update without losing data. They also select saved rows after restart and update
and verify that Title, Notes and Priority return to the editor. They retain
observed state and screenshots. Android
typing is deliberately ASCII; Unicode is exercised in the independent domain
suite. The Windows harness uses an empty application-data directory. Neither
scenario is a physical owner-device acceptance test or a visual-design review.
Windows control messages have bounded timeouts. Screenshots copy the visible
window pixels directly, so window occlusion can affect images; behavior assertions
use the actual controls and persisted state.

Join reports only after both native stages pass:

```bash
python scripts/check_complex_app_acceptance.py \
  --model evidence/complex-model.json --android evidence/android-native.json \
  --windows evidence/windows-native.json --output evidence/complex-acceptance.json
```

The join rejects missing stages and native reports belonging to different binary
hashes. `bounded_fixture_passed` is distinct from arbitrary-task reliability. Keep
long-media tests, authenticated account workflows, document layout/formula checks,
project grouping and owner-device acceptance on their own checklists. These scripts
do not produce a release ZIP.
