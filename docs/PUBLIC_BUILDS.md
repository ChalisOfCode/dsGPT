# Public builds with no additional spending

The source-publication authorization changes development infrastructure. It does
not turn dsGPT into a hosted-inference product and does not authorize paid services.
The private development archive and its complete history remain private.

## Activation controls

Every job checks that its repository is public and `DSGPT_ZERO_COST_READY` is
`true` before allocating a runner. Leave that variable unset until all these facts
are checked in the owner's account, recording any unavailable historical inventory:

1. The archive's Settings → Actions → General says **Disable actions**, and all
   running/queued runs have been stopped. This must apply to the entire repository.
2. Billing and licensing → Budgets and alerts has applicable **$0 budgets with
   Stop usage when budget limit is reached**, not just notification thresholds.
   Cover metered Actions/storage/Packages/cache products shown by the account.
   Check for other applicable budgets or paid products; do not enable them.
3. Existing artifact and cache storage in both repositories has been inventoried.
   Preserve required deliverables and signing backups before any deletion proposal.
   Actions disablement does not delete storage or cancel past accrued usage.
4. The new repository uses standard hosted runners only and its cache storage
   limit is no greater than the included 10 GB. Retention for new CI artifacts is
   one day. Changing retention does not retroactively shorten older artifacts.

The variable is an activation record, not a substitute for billing enforcement.
If spending enforcement or runner/storage limits cannot be verified, keep jobs
disabled. An inaccessible historical archive cache inventory is recorded as
unverified, not as zero: keep archive Actions disabled, do not delete its data,
and disable dependency cache writes in public jobs while that review is open.
This permits independent public work under verified $0 usage blocking without
claiming the archive storage review is complete.
Never raise a budget or use a paid fallback to bypass a blocked job. The assistant
must manage runs and failures itself when authenticated capabilities allow it.

## Consolidated pipeline

| Job | Execution and reuse |
| --- | --- |
| Backend | Locked Python environment, lint, policy checks, regression suite, one wheel. |
| Frontend | Locked npm environment, tests, one web bundle. |
| Browser | Real Chromium against a disposable fixture backend; runs beside backend/frontend checks without rebuilding the web release bundle. |
| Android | Unit tests, one unsigned production APK and distinct acceptance APK/instrumentation outputs; no production signing secret in PRs. |
| Windows native | Starts when the web bundle is ready; Rust tests and native executable using that exact bundle. |
| Android runtime | Reuses acceptance APKs in an emulator for lifecycle, pairing, reconnect and update fixtures. |
| Windows installer | Reuses backend/native/Android inputs; tests portable runtime, automatic Ollama setup, native UI, installer, restart, reinstall and uninstall on disposable Windows. Its test-only installer is not uploaded as a release. |
| Required | Fails unless all required software jobs pass; skipped/cancelled jobs are not passes. |

Independent roots run concurrently. Windows native compilation overlaps Android
compilation; packaging waits only for the components it actually needs. Shared
outputs carry a file manifest and exact source SHA and are verified by consumers.
All actions use fixed commit SHAs and checkout credentials are not persisted.

The two manually dispatched acceptance workflows keep expensive CPU model tests
out of ordinary UI/doc iterations. They use the exact pinned 9B abliterated model,
real Docker tools and independently checked synthetic media/app fixtures. A real
cold-load probe and memory/ownership admission check precede toolchain compilation.
CPU-only runtime extraction avoids unpacking unused GPU libraries. No smaller
model, fabricated action or alternate paid service replaces a failed acceptance.
Generated APKs and EXEs then run on disposable native/emulator workers.

## Storage and trust

CI artifacts have one-day retention. Upload checks reject selected signing files,
symlinks, payloads above 128 MiB and observed repository artifact totals above
300 MiB. These are conservative repository controls, not proof about account-wide
allowance or simultaneous uploads. Verified account-level usage blocking is still
required. If the guard fails, keep useful failure information in job logs and
preserve needed artifacts before proposing cleanup; never expand the allowance.

Dependency cache actions are currently removed and rejected by the policy check
while historical cache inventory is unresolved. Future reviewed caches may contain
only pip/npm packages, Gradle modules/wrapper and Cargo registry sources. No model weights, build target trees, browser sessions, signing
keys or user files are cached. Keep GitHub's repository cache cap within the free
allowance so eviction, not paid overflow, handles growth. There are no cron jobs,
`pull_request_target` workflows, write tokens, cloud machines or paid security scans.
Fork PRs receive no signing secrets. Public CI fixtures contain no personal chats.

## Production signing and delivery

Production `assembleRelease` produces an unsigned input. The existing private
signing key stays outside public source, caches and diagnostic artifacts. Signing
can happen in the assistant's protected workspace after downloading the exact
tested APK; it need not depend on the owner's PC or a public-repository secret.
`scripts/verify_android_release.py` runs Android's real verifier and checks the
certificate and application ID against `config/android-signing.json`, which contains
only public fingerprints. `build_application.py` requires that receipt for the
exact APK. It refuses missing, stale or wrong-key production inputs.

Reuse the CI-tested portable components when packaging the production EXE with the
verified APK; do not recompile and silently claim the rebuilt files were tested.
Repeat installer acceptance for the final production payload and record hashes.
Do not distribute the next upgrade while the five-item software scope is incomplete.
Owner PC/Pixel/GPU performance remains separately unverified unless actually tested.

Official policy references, consulted 2026-11-03:

- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/billing/how-tos/set-up-budgets
- https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository

### Explicit complex-acceptance request

Complex acceptance also supports an audited change to
`.github/complex-acceptance-request.txt` on `main`. This is an explicit dispatch
alternative when the browser is unavailable, not an automatic run on product
source changes. Record a unique request and prior terminal run; check active runs
and storage before publishing. The workflow tests the exact triggering commit,
retains the existing public/$0 gate and read-only permissions, and never cancels
an active acceptance run. Do not submit another request while acceptance is active.
