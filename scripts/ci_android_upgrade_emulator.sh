#!/usr/bin/env bash
set -euo pipefail
test "$GITHUB_REPOSITORY" = ChalisOfCode/dsGPT
test "$GITHUB_ACTIONS" = true
export ANDROID_USER_HOME="$RUNNER_TEMP/upgrade-android"
export ANDROID_AVD_HOME="$ANDROID_USER_HOME/avd"
export PATH="$ANDROID_HOME/platform-tools:$PATH"
echo "ANDROID_USER_HOME=$ANDROID_USER_HOME" >> "$GITHUB_ENV"
echo "ANDROID_AVD_HOME=$ANDROID_AVD_HOME" >> "$GITHUB_ENV"
echo "$ANDROID_HOME/platform-tools" >> "$GITHUB_PATH"
mkdir -p "$ANDROID_AVD_HOME"
test -c /dev/kvm
sudo chmod 666 /dev/kvm
timeout 360 "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" "platform-tools" "emulator" "system-images;android-28;google_apis;x86_64"
echo no | "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" create avd --force --name dsgpt-upgrade --device pixel_2 --path "$ANDROID_AVD_HOME/dsgpt-upgrade.avd" --package "system-images;android-28;google_apis;x86_64"
# Disposable writable image permits a test CA; neither APK's trust policy changes.
"$ANDROID_HOME/emulator/emulator" -avd dsgpt-upgrade -port 5554 -no-window -no-audio -no-snapshot -no-boot-anim -writable-system -gpu swiftshader_indirect -accel on -camera-back none -camera-front none > "$RUNNER_TEMP/upgrade-emulator.log" 2>&1 &
emulator_pid=$!
ready=0
for attempt in $(seq 1 150); do
  kill -0 "$emulator_pid" 2>/dev/null || exit 1
  if [ "$(adb -s emulator-5554 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; then ready=1; break; fi
  sleep 2
done
test "$ready" = 1
adb -s emulator-5554 shell input keyevent 82
for option in window_animation_scale transition_animation_scale animator_duration_scale; do
  adb -s emulator-5554 shell settings put global "$option" 0
done
