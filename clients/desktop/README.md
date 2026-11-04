# dsGPT desktop client

React/TypeScript UI with a Tauri 2 Windows wrapper. The backend must already be running independently; closing the window does not stop accepted requests. Native setup/supervision remains an integration task.

`npm ci`, `npm run types`, `npm test`, `npm run build`.

On a Windows build machine with Rust/MSVC and WebView2 prerequisites, run `npx @tauri-apps/cli@2 build` to produce an NSIS installer. The checkpoint also has a successful portable gnullvm cross-build and a client-only NSIS installer from `scripts/desktop-preview.nsi`. Build with the production `custom-protocol` feature so assets are embedded. A successful build is not proof of Windows execution. See the project test report for actual validation status.

Production requests go through the Rust bridge, with redirect and proxy use disabled; the credential is held in Windows Credential Manager, never localStorage. The WebView CSP disallows direct network access. Native incremental replies use atomic 250ms snapshots while active; browser development uses authenticated SSE and reconnect snapshots. Both retain server-owned generation across disconnections. Reading positions contain offsets and chat IDs, not message text.

Development browser mode intentionally keeps credentials only in memory. Configure the backend's exact development origin explicitly. No permissive CORS default is enabled. Start with `npm run dev`.
