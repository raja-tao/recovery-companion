// Applies project settings to the generated android/ project (run after `cap add android`).
//   ANDROID_ALLOW_HTTP=true   lets a development build call an http:// API (emulator → http://10.0.2.2:8081/api).
//   APP_VERSION_NAME / APP_VERSION_CODE set the version shown in the Play Console / device settings.
import { readFileSync, writeFileSync } from "node:fs";

const allowHttp = process.env.ANDROID_ALLOW_HTTP === "true";
const versionName = process.env.APP_VERSION_NAME || "0.1.0";
const versionCode = process.env.APP_VERSION_CODE || "1";

const edit = (path, fn) => writeFileSync(path, fn(readFileSync(path, "utf8")));

// Capacitor config is copied into the APK; mixed content is needed for http APIs from the https WebView origin.
const cfgPath = "capacitor.config.json";
const cfg = JSON.parse(readFileSync(cfgPath, "utf8"));
cfg.android = { ...cfg.android, allowMixedContent: allowHttp };
cfg.server = { ...cfg.server, cleartext: allowHttp };
writeFileSync(cfgPath, JSON.stringify(cfg, null, 2) + "\n");

edit("android/app/src/main/AndroidManifest.xml", (xml) => {
  xml = xml.replace(/\s*android:usesCleartextTraffic="[^"]*"/, "");
  return xml.replace("<application", `<application\n        android:usesCleartextTraffic="${allowHttp}"`);
});

edit("android/app/build.gradle", (g) =>
  g.replace(/versionCode \d+/, `versionCode ${versionCode}`).replace(/versionName "[^"]*"/, `versionName "${versionName}"`));

// Smaller Gradle distribution and a longer download timeout (the 10 s default fails on slow links).
edit("android/gradle/wrapper/gradle-wrapper.properties", (props) => {
  props = props.replace("-all.zip", "-bin.zip").replace(/\nnetworkTimeout=\d+/, "");
  return props.trimEnd() + "\nnetworkTimeout=300000\n";
});

console.log(`android configured: allowHttp=${allowHttp} version=${versionName} (${versionCode})`);
