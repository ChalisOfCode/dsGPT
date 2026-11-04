#!/usr/bin/env bash
set -euo pipefail
export ANDROID_USER_HOME="$RUNNER_TEMP/dsgpt-android"
export ANDROID_AVD_HOME="$ANDROID_USER_HOME/avd"
export PATH="$ANDROID_HOME/platform-tools:$PATH"
echo "ANDROID_USER_HOME=$ANDROID_USER_HOME" >> "$GITHUB_ENV"
echo "ANDROID_AVD_HOME=$ANDROID_AVD_HOME" >> "$GITHUB_ENV"
echo "$ANDROID_HOME/platform-tools" >> "$GITHUB_PATH"
mkdir -p reports "$ANDROID_AVD_HOME"
test -c /dev/kvm
sudo chmod 666 /dev/kvm
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" "platform-tools" "emulator" "system-images;android-35;google_apis;x86_64"
echo no | "$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager" create avd --force --name dsgpt-ci --device pixel_6 --path "$ANDROID_AVD_HOME/dsgpt-ci.avd" --package "system-images;android-35;google_apis;x86_64"
"$ANDROID_HOME/emulator/emulator" -avd dsgpt-ci -port 5554 -no-window -no-audio -no-snapshot -no-boot-anim -gpu swiftshader_indirect -accel on -camera-back none -camera-front none > reports/emulator.log 2>&1 &
emulator_pid=$!
ready=0
for attempt in $(seq 1 150); do
  if ! kill -0 "$emulator_pid" 2>/dev/null; then cat reports/emulator.log; exit 1; fi
  if [ "$(adb -s emulator-5554 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; then ready=1; break; fi
  sleep 2
done
test "$ready" = 1
adb -s emulator-5554 shell input keyevent 82
for option in window_animation_scale transition_animation_scale animator_duration_scale; do
  adb -s emulator-5554 shell settings put global "$option" 0
done
