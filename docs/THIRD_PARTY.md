# Third-party material retained for builds

- `clients/android/gradle/wrapper/gradle-wrapper.jar`: Gradle 8.13 wrapper,
  SHA-256 `81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f`.
  The official published checksum was checked. Apache-2.0 license is embedded at
  `META-INF/LICENSE`. Gradle scripts retain their upstream copyright/license headers.
- `scripts/vendor/srt-3.5.3-py3-none-any.whl`: small reproducible pure-Python build
  from the pinned upstream srt 3.5.3 source. Python modules and the MIT license were
  compared byte for byte with that source. Copyright Christopher Down is retained
  in the wheel. `requirements-windows.lock.json` records source and wheel hashes.
- `docs/speech-licenses/`: Vosk Apache-2.0, GCC licensing/runtime exception and
  MinGW winpthreads notices required by the packaged speech dependencies.
- The custom dsGPT icon is retained as a required installer asset. Embedded document
  fixtures contain generated sentinel text and no personal documents or photos.
- Dependency lockfiles retain registry URLs, integrity hashes and package/license
  metadata. Packaging collects Rust/JavaScript/Python dependency notices instead of
  dropping them when producing binaries. Downloaded models/tools keep their licenses.

This document does not grant a new license over the owner's original source or
claim a complete legal review of every transitive dependency. Public availability
and an open-source license are separate decisions.
