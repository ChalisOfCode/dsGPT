$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$env:PYTHONUTF8 = '1'
$private = "$env:RUNNER_TEMP/windows-private"
New-Item -ItemType Directory -Force reports/windows-upgrade, artifacts/windows-upgrade | Out-Null
python scripts/build_upgrade_runtime.py --output dist/upgrade-runtime --cache "$env:RUNNER_TEMP/upgrade-inputs" --client dist/windows-client
# Receipt is bound to the exact already SDK-verified and upgrade-tested APK.
python scripts/build_application.py --kit dist/upgrade-runtime --android "$private/candidate.apk" --android-signature config/android-upgrade-signature.json --setup-source-commit $env:GITHUB_SHA --android-source-commit 82f9c683ee5a670aaae02e3e0fa92a12551c3e0d --output dist/dsGPT-Application
$nsis = "${env:ProgramFiles(x86)}/NSIS/makensis.exe"
if (!(Test-Path $nsis)) { choco install nsis --version=3.11 -y --no-progress }
& $nsis scripts/application.nsi
$candidateHash = (Get-FileHash dist/dsGPT-Setup.exe -Algorithm SHA256).Hash.ToLowerInvariant()
Copy-Item dist/dsGPT-Setup.exe artifacts/windows-upgrade/
Copy-Item dist/dsGPT-Application/application-manifest.json artifacts/windows-upgrade/
python scripts/ci_provenance.py write artifacts/windows-upgrade $env:GITHUB_SHA
python scripts/check_application_upgrade.py --baseline "$private/baseline-setup.exe" --candidate dist/dsGPT-Setup.exe --candidate-sha256 $candidateHash --source $env:GITHUB_SHA --install-dir "$env:RUNNER_TEMP/dsGPT Upgraded App" --private "$env:RUNNER_TEMP/windows-upgrade-observations" --report reports/windows-upgrade/upgrade.json
