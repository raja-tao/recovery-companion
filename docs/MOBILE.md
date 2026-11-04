# Android app

The patient and care-team experience is one responsive React app. On Android it runs inside a
[Capacitor](https://capacitorjs.com/) shell: the web build is bundled into the APK and talks to the same API.
Everything builds in Docker; you don't need Android Studio, the Android SDK or Node on your machine.

## Build the APK

```bash
make up                 # the API the app talks to (WEB_PORT=8081 if 8080 is taken)
make android            # → dist/android/recovery-companion-debug.apk
                        #   dist/android/android-project/  (open in Android Studio if you want to)
```

The first build downloads the Android SDK and Gradle (about 1.5 GB) and takes a while: on Apple Silicon it runs as
`linux/amd64`, because Google's Android build tools are x86-64 only. Later builds reuse the cached layers.

| Variable | Default | Use |
|---|---|---|
| `API_BASE` | `http://10.0.2.2:8081/api` | API address baked into the app. `10.0.2.2` is the host machine as seen from the Android emulator. |
| `ANDROID_ALLOW_HTTP` | `true` when `API_BASE` is `http://` | Allows cleartext HTTP and mixed content. Leave it off (use `https://`) for anything but local testing. |

```bash
make android API_BASE=http://192.168.1.20:8081/api     # a phone on the same Wi-Fi as this machine
make android API_BASE=https://recovery.example.org/api # a deployed API (HTTPS, no cleartext)
```

The server address can also be changed on the app's sign-in screen (shown only inside the app), so one APK can
point at different environments.

## Install

- **Emulator:** drag the APK onto the emulator window, or `adb install -r dist/android/recovery-companion-debug.apk`.
- **Phone:** enable *Install unknown apps* for your file manager, copy the APK over and open it; or use
  `adb install` with USB debugging on.

Then sign in with a demo account (`patient@example.com` / `Recovery#2026`). For a phone, start the stack with the
API reachable on your LAN address and build with that `API_BASE`.

## What works in the app

Everything in the web app: the mood question after each sign-in, check-ins, medications, the assistant, the recovery
plan, appointments with ride requests, surveys, messages and caregiver access, plus the care-team and admin screens.
The Android back button navigates back through screens (Capacitor App plugin), and the layout uses the bottom
navigation bar on phones.

The backend allows the app's WebView origins (`https://localhost`, `capacitor://localhost`) in `CORS_ORIGINS`.
Sessions use the same short-lived bearer token as the web app and end when the app is closed.

## Before a store release

- **Signing:** the APK is a debug build. Create an upload key and build a signed release bundle
  (`./gradlew bundleRelease` in `android-project/` with a `signingConfigs` block) for Google Play.
- **App id and icons:** change `appId` in `mobile/capacitor.config.json` from `org.example.recoverycompanion` and
  replace the default launcher icons (e.g. with `@capacitor/assets`).
- **HTTPS only:** build with an `https://` `API_BASE` so cleartext stays disabled.
- **Push notifications:** reminders currently arrive in-app and by SMS. Native push needs Firebase Cloud Messaging
  (`@capacitor/push-notifications`) and a backend notification provider for FCM.
- **Health data:** wearable sync (Health Connect) needs a native plugin and the user's consent screen; the API side
  (`POST /api/integrations/devices`) already exists.
- **PHI on the device:** nothing is stored offline beyond the session token; keep it that way or use encrypted
  storage.
