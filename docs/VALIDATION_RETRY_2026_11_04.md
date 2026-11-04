# Fresh acceptance retry, 2026-11-04

This is a failure investigation, not release approval. The five-item scope in
UPGRADE_COMPLETION_PLAN.md remains authoritative. No new upgrade ZIP is approved.

## Observed public GitHub runs

- Media run 41885363018, source 103e3cab80e366aad979ce2fb22933d8e1355207:
  exact pinned 9B runtime loaded; fresh short recording completed with checked
  JSON/SRT output. Fresh 908.308-second recording processed only seconds 0–300;
  the independent oracle rejected incomplete coverage and missing later speech.
- Complex app run 41885498717, same source: runtime and production Docker image
  preparation passed. Actual model actions stopped with `no_progress`, after
  invented evidence paths were rejected and the model repeated an EOF requirement
  read. No generated APK/EXE acceptance pass is claimed.
- Routine run 41887925342, source a74de4fa5cd5639b14ca9332f881ad40c135eade:
  backend, frontend, browser, Android build/runtime and Windows native compilation
  passed. Native Windows client/credential checks and unattended Ollama setup plus
  a real local inference request passed. Later installation acceptance failed at
  the expected destination's missing Uninstall.exe. Python's argument-list quoting
  conflicts with NSIS's unquoted final `/D=` path syntax for paths with spaces.
  The same special syntax applies to the uninstaller's `_?=` tail.

## Changes under validation

Explicit positive whole-recording transcription requests now gate coverage and
finish against current source-bound window receipts. Multi-window recordings also
require a current assembled JSON/SRT pair. Scope comes from original requirements,
not the model's generated review. Recognition is deliberately narrow; ambiguous,
negated and excerpt wording retains the existing requirement-review path. This is
not a general natural-language scope verifier or an accuracy certification.

The controller supplies continuation guidance, preserves legitimate excerpt work,
and tells the model to inspect/implement actual source after a requirement's EOF.
The Windows install/uninstall harness uses NSIS's documented raw path-tail syntax,
without a shell. The original long prompts, pinned model, output oracle, native
acceptance requirements, private archive and zero-cost boundary are unchanged.

Modified source, tests and this document were manually reviewed for publication.
Only current source is published: diagnostic ZIPs, model outputs, profiles, logs,
credentials and signing material remain excluded. A tracked-source Gitleaks scan
is an additional check, not proof of overall security.

Native installation and actual model task completion must be rerun on this change.
Owner GPU/Pixel/Tailscale behavior is not established by these disposable runs.
