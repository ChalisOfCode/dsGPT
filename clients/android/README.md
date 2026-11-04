# Android 0.4.0 Stage 4A preview

Adds scoped history/semantic retrieval, owner-authorized index/source controls,
Work targets, execution receipts, hash-verified artifact saving and initial private
text/code source files. Archive import itself stays local to the Windows PC.
The CI APK is debug-signed with an ephemeral key. It may not upgrade a previously
installed preview signed with another key; production signing is still pending.
Compilation and CI tests do not claim Pixel or Tailscale device acceptance.

# dsGPT Mobile

Native Kotlin/Jetpack Compose application. No inference runs on the phone.

Build with JDK 17 and Android SDK 35: `./gradlew assembleDebug testDebugUnitTest lintDebug`.
The checked-in wrapper pins Gradle 8.13 with a distribution checksum. The build pins AGP 8.10.1 and Kotlin 2.1.20. Output: `app/build/outputs/apk/debug/app-debug.apk`.

Pair from desktop Settings with a one-use code and the PC's exact HTTPS Tailscale Serve hostname. The backend must allow that exact Host header; it remains bound to loopback behind Tailscale Serve. Public servers, HTTP, redirects and credential-bearing URLs are rejected. Do not enable Funnel.

Credentials use AES-GCM with an Android Keystore key. Backups and device transfers exclude application data. Reading offsets are stored locally without message contents. Foreground chat observation is bound to STARTED lifecycle; the PC owns generation. The native client currently displays incremental replies through atomic 300ms snapshots, not a persistent SSE socket. Completed conversations refresh every 1.8 seconds while open. No background inference or background diagnostic collection runs on Android.

Settings → Chats → Hidden Chats is the only hidden-chat list. Pins survive hide/unhide. There is no count cap; history is fetched in server-sized pages. Model labels come from the shared backend, including `-NA` and `-A` suffixes.

Settings → Diagnostics retrieves desktop measurements, previews a fixed export, and saves it through Android's document picker. Sharing a phone snapshot requires a fresh explicit consent checkbox. Desktop requests do not bypass that consent. These native flows are compiled and statically checked but need device acceptance tests.

The checkpoint APK is debug-signed, for development testing only. The separately retained debug signing key is not a production release identity. Production signing, distribution, Pixel-specific behavior, rotation/background/restart tests and Tailscale end-to-end validation remain release gates.
