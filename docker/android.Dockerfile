# Builds the Android app (APK) for the Recovery Companion web app, entirely in Docker.
#   make android                       → dist/android/recovery-companion-debug.apk (+ the android/ project)
#   make android API_BASE=https://…/api
# Runs as linux/amd64: Google's Android build tools (aapt2) are x86-64 only.

# --------------------------------------------------------------------------- 1. web bundle
FROM node:20-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
# The bundled app can't use a relative /api, so the server address is baked in (and editable on the login screen).
ARG API_BASE=http://10.0.2.2:8081/api
ENV VITE_API_BASE=${API_BASE}
RUN npm run build

# --------------------------------------------------------------------------- 2. Android SDK + Gradle build
FROM eclipse-temurin:17-jdk-jammy AS android
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/*
ENV ANDROID_HOME=/opt/android-sdk ANDROID_SDK_ROOT=/opt/android-sdk
ENV PATH=${PATH}:/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools
RUN mkdir -p ${ANDROID_HOME}/cmdline-tools \
 && curl -fsSL -o /tmp/tools.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
 && unzip -q /tmp/tools.zip -d ${ANDROID_HOME}/cmdline-tools && mv ${ANDROID_HOME}/cmdline-tools/cmdline-tools ${ANDROID_HOME}/cmdline-tools/latest \
 && rm /tmp/tools.zip \
 && yes | sdkmanager --licenses > /dev/null \
 && sdkmanager --install "platform-tools" "platforms;android-34" "build-tools;34.0.0" > /dev/null

WORKDIR /app
COPY mobile/package.json mobile/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY mobile/capacitor.config.json ./
COPY mobile/scripts ./scripts
COPY --from=web /web/dist ./www
ARG ANDROID_ALLOW_HTTP=true
ARG APP_VERSION_NAME=0.1.0
ARG APP_VERSION_CODE=1
RUN npx cap add android \
 && ANDROID_ALLOW_HTTP=${ANDROID_ALLOW_HTTP} APP_VERSION_NAME=${APP_VERSION_NAME} APP_VERSION_CODE=${APP_VERSION_CODE} \
    node scripts/configure-android.mjs \
 && npx cap sync android
# Download Gradle and the Android Gradle plugin dependencies in their own layer (cached between builds).
RUN cd android && for i in 1 2 3; do ./gradlew --no-daemon -q help && break || sleep 10; done
RUN cd android && ./gradlew --no-daemon -q assembleDebug \
 && cp app/build/outputs/apk/debug/app-debug.apk /app/recovery-companion-debug.apk \
 && rm -rf app/build .gradle build

# --------------------------------------------------------------------------- 3. export
FROM scratch AS apk
COPY --from=android /app/recovery-companion-debug.apk /
COPY --from=android /app/android /android-project/
COPY --from=android /app/capacitor.config.json /android-project/capacitor.config.json
