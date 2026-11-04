param([switch]$BuildOnly)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$env:PYTHONUTF8 = '1'

if ($BuildOnly) {
    python scripts/ci_provenance.py verify shared/frontend $env:GITHUB_SHA
    New-Item -ItemType Directory -Force clients/desktop/dist | Out-Null
    Copy-Item shared/frontend/* clients/desktop/dist -Recurse
    Push-Location clients/desktop
    try {
        npm ci --ignore-scripts --no-audit --no-fund
        cargo test --manifest-path src-tauri/Cargo.toml --locked --release --features custom-protocol
        cargo build --manifest-path src-tauri/Cargo.toml --locked --release --features custom-protocol
        cargo metadata --manifest-path src-tauri/Cargo.toml --locked --format-version 1 --filter-platform x86_64-pc-windows-msvc | Out-File -Encoding utf8 cargo-metadata.json
        python ../../scripts/collect-client-licenses.py cargo-metadata.json
    } finally { Pop-Location }
    Copy-Item clients/desktop/src-tauri/target/release/dsgpt-desktop.exe dist/windows-client/dsGPT.exe
    python scripts/ci_provenance.py write dist/windows-client $env:GITHUB_SHA
    exit 0
}

foreach ($component in @('backend', 'android', 'windows-client')) {
    python scripts/ci_provenance.py verify "shared/$component" $env:GITHUB_SHA
}
python -m pip install packaging==26.3 pytest==9.1.1 pytest-asyncio==1.4.0
New-Item -ItemType Directory -Force dist, artifacts/windows, reports/windows | Out-Null
Copy-Item shared/backend/*.whl dist/
python scripts/build_acceptance_kit.py --output dist/dsGPT-Acceptance --cache "$env:RUNNER_TEMP/acceptance-inputs" --client shared/windows-client --android shared/android/acceptance.apk --android-test shared/android/acceptance-test.apk
$portable = "$PWD/dist/dsGPT-Acceptance/python/python.exe"
try {
    & $portable -B -I -m dsgpt_acceptance --kit dist/dsGPT-Acceptance --ci --no-phone --output "$env:RUNNER_TEMP/acceptance-results"
} finally {
    # Retain only fixed stage/check labels and results, never private logs or profiles.
    $reportPath = "$env:RUNNER_TEMP/acceptance-results/report/report.json"
    if (Test-Path $reportPath) {
        $observed = Get-Content $reportPath | ConvertFrom-Json
        @{
            native_client_stage = $observed.native_client_stage
            checks = @($observed.checks | Select-Object name,status,seconds)
        } | ConvertTo-Json -Depth 4 | Set-Content reports/windows/acceptance-stages.json
    }
}
$report = Get-Content "$env:RUNNER_TEMP/acceptance-results/report/report.json" | ConvertFrom-Json
foreach ($name in @('Kit file integrity','Start isolated backend','Chat, restart, cancellation, pairing and diagnostics','Windows client and Credential Manager')) {
    if (($report.checks | Where-Object name -eq $name).status -ne 'PASS') { throw "Required check did not pass: $name" }
}
$env:PYTHONPATH = "$PWD/dist/dsGPT-Acceptance/python/Lib/site-packages"
python -m pytest -q tests/test_acceptance_harness.py tests/test_acceptance_setup.py tests/test_acceptance_ollama_runtime.py tests/test_sandbox_transport.py tests/test_inference.py tests/test_conversations_runs.py tests/test_application_setup.py tests/test_managed.py --junitxml=reports/windows/regressions.xml
Remove-Item Env:PYTHONPATH

# Both tests run on this disposable GitHub account; no owner machine/phone is used.
& $portable -B -I scripts/check_windows_setup.py --kit dist/dsGPT-Acceptance --output "$env:RUNNER_TEMP/acceptance-setup"
python scripts/build_application.py --kit dist/dsGPT-Acceptance --android shared/android/acceptance.apk --ci-acceptance --setup-source-commit $env:GITHUB_SHA --android-source-commit $env:GITHUB_SHA --output dist/dsGPT-Application
$nsis = "${env:ProgramFiles(x86)}/NSIS/makensis.exe"
if (!(Test-Path $nsis)) { choco install nsis --version=3.11 -y --no-progress }
& $nsis scripts/application.nsi
python scripts/check_application_install.py --installer dist/dsGPT-Setup.exe --install-dir "$env:RUNNER_TEMP/dsGPT Installed App" --output "$env:RUNNER_TEMP/application-results"

# Upload only reviewed synthetic summary files, never credentials/profile/db/log trees.
foreach ($name in @('application-installation.json','first.json','restart.json')) {
    Copy-Item "$env:RUNNER_TEMP/application-results/$name" "reports/windows/$name"
}
# Always package and fingerprint the tested kit. No downstream job consumes this
# final ZIP. On push/PR retain its receipt instead of charging the shared storage
# allowance for another copy; a manual CI dispatch retains the full kit.
$packed = "dist/ci-packed"
New-Item -ItemType Directory -Force $packed | Out-Null
python scripts/package_acceptance_kit.py --kit dist/dsGPT-Acceptance --output "$packed/acceptance-components.zip"
python scripts/ci_provenance.py write $packed $env:GITHUB_SHA
Copy-Item "$packed/SOURCE.json" artifacts/windows/tested-kit-receipt.json
if ($env:GITHUB_EVENT_NAME -eq 'workflow_dispatch') {
    Copy-Item "$packed/acceptance-components.zip" artifacts/windows/
}
python scripts/ci_provenance.py write artifacts/windows $env:GITHUB_SHA
# The CI installer embeds the distinct test APK and is intentionally not published.
