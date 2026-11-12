# Upgrade and runtime diagnosis checkpoint

Item 5 is in progress. This is not final installer or upgrade acceptance.

The first slice adds bounded inference-attempt receipts for Work actions,
specification reviews, input/asset image reviews and Work research planning.
Schema 32 is additive; migration preserves prior group/source records and creates
the existing checked pre-upgrade backup. Receipts are independent of action steps,
so recording an empty reply cannot claim an action ran or alter prior evidence.

Each attempt freezes the selected runtime, hashed model references, configured
digest pin, context/output limits, reasoning setting, task revision and next step.
No endpoint, filename, prompt, generated content or reasoning text is retained.
Context accounting distinguishes runtime tokenization from an upper estimate.
Allowlisted runtime counters keep their original units; visible UTF-8 byte counts,
first-visible-text latency and wall duration are independent measurements.
The configured digest is not an observed runtime measurement. Unknown metrics
remain absent. A completed stream does not establish valid JSON or tool success.

Empty/output-limited responses, runtime/consumer errors and cancellation retain
observed counts. The start, context, metrics and terminal states are durable;
partial byte counters checkpoint at most once per second. Abrupt exit therefore
retains a lower bound, not an invented final duration or token count. Backend
startup marks unfinished receipts interrupted before existing Work recovery.
At most 200 receipts are retained globally, and diagnostics exposes the latest 50
under its existing permission and reviewed-export controls. Existing inference
requests, grammar, model decisions, output limits and retry behavior are unchanged.

Focused protocol, cancellation, separate-process abrupt-exit recovery, privacy,
retention and v31 upgrade checks are distinct from actual-model acceptance.
Item 1 remains accepted and is not rerun. Native Windows verification of this
slice is required before integration. Real old-to-candidate EXE/APK upgrades,
Android signing/data continuity and reconnect acceptance remain outstanding.

The prior delivered baseline binaries have been recovered privately and matched
against their original delivery manifest. The recovered original Android key's
certificate matches the public signing policy and the prior APK certificate.
This is preparation only; no installation or signing-continuity acceptance has
been claimed. Private backups/keys are excluded from source and public artifacts.
