# dsGPT development rules

## Authorized public development and the private archive

The owner authorized a new public source repository on 2026-11-03. This explicitly
replaces the earlier private-source/local-worker-only development policy. Start
from the audited snapshot; never import the private archive's Git history, reports,
conversations, device details or signing material. The existing
`ChalisOfCode/dsGPT-development` repository stays private and its Actions must be
disabled repository-wide, including historical branches. Do not change its visibility.

## Zero additional spending

Use only standard `ubuntu-24.04` and `windows-2025` GitHub-hosted runners in the
public repository. No larger/GPU runners, paid machines, hosted AI inference,
paid security services, subscriptions or trials. Never raise a budget or select a
paid fallback. Public compute is free; that does not establish free storage.

Before enabling jobs, verify account-wide $0 budgets with **Stop usage**, private
archive Actions disablement and queued/running runs, existing artifact/cache usage,
and a public-repository cache limit no greater than the included 10 GB. Record the
observations. Only then set `DSGPT_ZERO_COST_READY=true`. An unset variable disables
every job before runner allocation. This variable records an administrative check;
it cannot enforce billing settings or prove they remain unchanged.

Artifacts have one-day retention and size checks; caches contain dependencies only.
Preserve irreplaceable deliverables before proposing deletion. Disabling workflows
or shortening retention does not delete existing storage or cancel accrued charges.
Never publish secrets in logs/artifacts or give signing secrets to pull requests.
Keep workflow permissions read-only except a narrowly justified operation.

## Workflow and acceptance

Run independent backend, frontend, browser and Android checks concurrently. Reuse
the backend wheel, web bundle and Android outputs in Windows packaging. Compile
each deliverable once per tested source version. Cancel superseded CI runs, keep
bounded failure diagnostics, and investigate actual failed jobs before retrying.
Use disposable runners/emulators for installation, lifecycle and upgrade tests.

The owner's PC, GPU, Pixel, local worker, heartbeat and Tailscale are **not** routine
build, development or packaging prerequisites. Targeted hardware diagnostics are
optional. Record physical behavior as unverified unless actually observed. Never
run destructive installer acceptance in the owner's everyday Windows profile.

The product still runs inference locally. Public CI changes development, not that
runtime promise. Preserve existing capabilities, data migrations, package IDs and
Android signing continuity. Test APKs use `com.dsgpt.mobile.acceptance`; they are
not production updates. A release with a missing/wrong signing key must fail.

## Continue the existing upgrade

Read `docs/UPGRADE_COMPLETION_PLAN.md` and `REQUIREMENTS.md`. Complete the active
five-item scope in order; a checkpoint is not completion. Do not weaken tests,
substitute generated fixture code for actual model decisions, or replace missing
evidence with claims. Keep precise source, tool and artifact hashes. Separate
unit/fixture checks, real model decisions, compiler results, native UI behavior and
owner-hardware observations. Deliver an upgrade only when the agreed software
scope passes, with explicit hardware limitations and unchanged signing identity.

Do not claim ChatGPT keeps working after the turn. Background work requires an
actually configured and verified workflow or automation, with its real run URL.
TinyFish is optional tooling for the development assistant's signed-in website
tasks; it is not a paid dependency of dsGPT, and installation authorizes no charges.
