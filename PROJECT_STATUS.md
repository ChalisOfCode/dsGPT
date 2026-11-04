# Active upgrade — software release still held

The latest delivered upgrade is 0.9.2. This public snapshot continues the latest
private development source, including the recovered long-prompt/context fixes and
Gradle cache-alias correction. It does not reset the project or claim the five-item
upgrade is finished. Requirements and detailed designs remain under `docs/`.

The development policy now permits audited public source and free standard GitHub
builds. Parallel software jobs and shared component manifests are prepared. The
owner's PC, local worker, Pixel, Tailscale and GPU are not build prerequisites.
Account-level cost controls and actual GitHub execution must be verified separately.

Current work adds release signing-continuity checks, CPU-only inference-runtime
extraction, effective-memory and process-ownership admission, and an actual cold-load
preflight before expensive compiler setup. The optional native model-copy candidate
whose complete files were lost remains recovery material in the private archive;
it is not silently represented as implemented. The default acceptance path keeps
the original pinned Ollama model. No smaller-model or paid fallback is introduced.

The fresh actual-model long-media and complex-app acceptance runs remain the active
item. Signed-in account workflows, document rendering/recalculation and project
grouping remain subsequent unfinished work; their designs are not implementations.
Software upgrade/reconnect and empty-response validation follows those items.
See `docs/UPGRADE_COMPLETION_PLAN.md` for acceptance criteria. No next release ZIP
is authorized as complete until the agreed software scope passes.
