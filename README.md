# dsGPT

Local AI chat and persistent software-building tasks with a Windows desktop client
and Android companion. The backend supports local model runtimes, bounded web
research, project files, isolated tools, memory and diagnostics. The desktop uses
React/Tauri; Android uses Kotlin/Compose; the backend uses Python/FastAPI.

This is an active development snapshot, **not a finished upgrade**. See
[requirements](REQUIREMENTS.md), the [remaining upgrade](docs/UPGRADE_COMPLETION_PLAN.md),
and [build controls](docs/PUBLIC_BUILDS.md). Existing user data and Android signing
identity must survive upgrades. A test APK is never a replacement for the normal app.

Development runs on free standard public GitHub Actions runners. dsGPT's model
inference remains local; no paid inference service is required. Owner hardware is
not needed to compile or run routine CI. Hardware-specific claims require actual
hardware observations and are kept separate from runner/emulator results.

## Development checks

Use Python 3.12 and Node 22 or newer compatible with the locked frontend dependencies.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/ruff check src tests scripts
.venv/bin/pytest -q
cd clients/desktop
npm ci --ignore-scripts --no-audit --no-fund
npm test
npm run build
```

Windows uses `.venv/Scripts/python.exe`. Browser tests use Playwright Chromium and
`DSGPT_TEST_PYTHON` pointing to the backend environment. Android requires JDK 17
and Android SDK 35; `-Pacceptance` creates the separate disposable test app.

The source was recovered from a private development archive without copying its
history. [Publication review](docs/PUBLICATION_AUDIT.md) records the exact source,
exclusions and review limits. Dependency notices remain with their source/assets;
see [third-party material](docs/THIRD_PARTY.md). No general open-source license has
been added on behalf of the owner; the included third-party licenses still apply.
