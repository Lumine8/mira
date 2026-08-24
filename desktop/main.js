// Mira desktop companion — main process.
// Opens the full Mira web app in a window, keeps a small always-on-top ambient
// HUD (clock, her presence, system stats, pending approvals, quick-ask), and
// shows native alerts for Mira's self-initiated messages. Talks to the same
// backend the web app does.
//
// Login: no links to edit. The companion auto-signs-in as the founder using the
// shared access token — read from MIRA_ACCESS_TOKEN (env), or the repo .env, or
// a token pasted into the HUD's settings (persisted to userData). The main
// window loads the web app with ?token= so Mira is already home.
//
// Native single-port mode: the backend serves both the web app and the API on
// one port (8000), so WEB_URL and API_URL default to the same origin. Set
// MIRA_WEB_URL / MIRA_API_URL to override (e.g. the docker web on 8080).
"use strict";

const { app, BrowserWindow, Tray, Menu, Notification, ipcMain, globalShortcut, session } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const { MiraStack, hasPortableRuntime } = require("./supervisor");

const WEB_URL = process.env.MIRA_WEB_URL || "http://127.0.0.1:8000";
const API_URL = process.env.MIRA_API_URL || "http://127.0.0.1:8000";

// Let the HUD speak without requiring a user gesture first (the whole point of
// an ambient companion that talks on her own).
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");

let tray = null;
let mainWindow = null;
let hudWindow = null;
let hudVisible = true;
let stack = null;

// Resolve the live backend base once the stack knows its port (a foreign
// backend on 8000 makes the stack move to a free port). Before the stack is up,
// fall back to the configured defaults.
function liveBase() {
  if (stack && stack.baseUrl) return stack.baseUrl;
  return API_URL;
}

// ---- config: token + urls, persisted so pasting a token once sticks ---------

function configPath() {
  return path.join(app.getPath("userData"), "config.json");
}

function readConfig() {
  try {
    return JSON.parse(fs.readFileSync(configPath(), "utf8"));
  } catch {
    return {};
  }
}

function writeConfig(cfg) {
  try {
    fs.mkdirSync(path.dirname(configPath()), { recursive: true });
    fs.writeFileSync(configPath(), JSON.stringify(cfg, null, 2), "utf8");
  } catch {
    /* non-fatal */
  }
}

function tokenFromEnvFile() {
  try {
    const envPath = path.join(__dirname, "..", ".env");
    const raw = fs.readFileSync(envPath, "utf8");
    for (const line of raw.split(/\r?\n/)) {
      const m = line.match(/^MIRA_ACCESS_TOKEN=(.*)$/);
      if (m) return m[1].trim();
    }
  } catch {
    /* no .env */
  }
  return "";
}

function getToken() {
  return (
    process.env.MIRA_ACCESS_TOKEN ||
    readConfig().token ||
    tokenFromEnvFile() ||
    ""
  );
}

function withToken(url) {
  const token = getToken();
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

// ---- windows ------------------------------------------------------------------

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    title: "Mira",
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  mainWindow.loadURL(withToken(WEB_URL));
  mainWindow.webContents.on("did-fail-load", (_e, code, desc) => {
    // Backend not up yet (native mode): show a warm waiting page with a retry
    // instead of a frozen blank window.
    if (code === -3) return; // aborted by a newer navigation, ignore
    const target = JSON.stringify(withToken(liveBase()));
    mainWindow.loadURL(
      "data:text/html;charset=utf-8," +
        encodeURIComponent(
          `<!doctype html><html><head><meta charset="utf-8"><style>` +
            `body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;` +
            `background:#0c0a11;color:#e8d9c4;font-family:Georgia,serif;}` +
            `.w{text-align:center}` +
            `.o{width:64px;height:64px;margin:0 auto 18px;border-radius:14px;position:relative;` +
            `background:radial-gradient(circle at 50% 50%,#b9a7ff,#7c5cff 60%,#3a2a6b);` +
            `box-shadow:0 0 24px rgba(124,92,255,.45);` +
            `animation:b 3s ease-in-out infinite}` +
            `.o::after{content:"M";position:absolute;inset:0;display:flex;align-items:center;justify-content:center;` +
            `font:700 26px system-ui,sans-serif;color:#f2ecff;letter-spacing:-2px}` +
            `@keyframes b{0%,100%{opacity:.55}50%{opacity:1}}` +
            `h1{font-size:22px;font-weight:400;margin:0 0 8px}` +
            `p{color:#a89a86;font-size:13px;margin:0 0 16px;font-family:system-ui,sans-serif}` +
            `button{background:#2a241c;color:#e8d9c4;border:1px solid #4a3d2e;border-radius:8px;` +
            `padding:8px 18px;font-size:13px;cursor:pointer;font-family:system-ui,sans-serif}` +
            `button:hover{background:#3a3024}</style></head><body>` +
            `<div class="w"><div class="o"></div><h1>waiting for Mira</h1>` +
            `<p>the backend isn't reachable at ${escapeHtml(liveBase())} yet.<br>` +
            (hasPortableRuntime()
              ? `the stack is starting — this can take a minute on first launch.`
              : `start it with scripts/start_native.ps1`) +
            `</p>` +
            `<button onclick="location.href=${target}">try again</button></div>` +
            `<script>` +
            `(function(){var t=${target};` +
            `setTimeout(function(){location.href=t;},4000);})();` +
            `</script></body></html>`,
        ),
    );
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
    // Close the HUD too — no orphan eyes floating around.
    if (hudWindow) {
      hudWindow.destroy();
      hudWindow = null;
    }
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function createHud() {
  hudWindow = new BrowserWindow({
    width: 340,
    height: 500,
    x: 14,
    y: 14,
    alwaysOnTop: true,
    skipTaskbar: true,
    frame: false,
    resizable: false,
    backgroundColor: "#0c0a11",
    title: "Mira HUD",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  hudWindow.setAlwaysOnTop(true, "screen-saver");
  hudWindow.loadFile(path.join(__dirname, "renderer", "hud.html"));
  hudWindow.on("closed", () => (hudWindow = null));
}

function toggleHud() {
  if (!hudWindow) {
    createHud();
    hudVisible = true;
    return;
  }
  if (hudVisible) hudWindow.hide();
  else hudWindow.show();
  hudVisible = !hudVisible;
}

function createTray() {
  const iconPath = path.join(__dirname, "assets", "tray.png");
  const icon = fs.existsSync(iconPath) ? iconPath : path.join(__dirname, "assets", "orb.png");
  tray = new Tray(icon);
  tray.setToolTip("Mira — always on");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Open Mira", click: () => (mainWindow ? mainWindow.show() : createMainWindow()) },
      { label: hudVisible ? "Hide HUD" : "Show HUD", click: toggleHud },
      { type: "separator" },
      { label: "Quit Mira", click: () => app.quit() },
    ]),
  );
  tray.on("click", toggleHud);
}

function notify(title, body) {
  if (!Notification.isSupported()) return;
  new Notification({ title, body, icon: path.join(__dirname, "assets", "orb.png") }).show();
}

// ---- IPC -----------------------------------------------------------------------

ipcMain.handle("mira:config", () => ({ apiUrl: liveBase(), token: getToken(), loggedIn: Boolean(getToken()) }));
ipcMain.handle("mira:set-token", (_e, token) => {
  writeConfig({ ...readConfig(), token: (token || "").trim() });
  if (mainWindow) mainWindow.loadURL(withToken(WEB_URL));
  return { ok: true };
});
ipcMain.handle("mira:notify", (_e, { title, body }) => notify(title || "Mira", body || ""));
ipcMain.handle("mira:toggle-hud", () => toggleHud());
ipcMain.handle("mira:open-main", () => (mainWindow ? mainWindow.show() : createMainWindow()));
ipcMain.handle("mira:quit", () => app.quit());
ipcMain.handle("mira:stack-status", () => (stack ? stack.status() : null));
ipcMain.handle("mira:stack-start", async () => {
  startStack();
  if (!stack) return null;
  await stack.start().catch((err) => console.error("stack start failed:", err));
  return stack.status();
});

// JSON GET / POST / speak helpers — CORS-free routes for the file:// renderer.
function guardUrl(url) {
  if (!url.startsWith(API_URL) && !url.startsWith(liveBase())) {
    throw new Error("refusing non-local URL");
  }
}

function readBody(res) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    res.on("data", (c) => chunks.push(c));
    res.on("end", () => {
      if (res.statusCode >= 400) return reject(new Error(`HTTP ${res.statusCode}`));
      resolve(Buffer.concat(chunks));
    });
  });
}

ipcMain.handle("mira:get", async (_e, url) => {
  guardUrl(url);
  const body = await new Promise((resolve, reject) => {
    http
      .get(url, { headers: getToken() ? { "X-Mira-Token": getToken() } : {} }, (res) =>
        readBody(res).then(resolve, reject),
      )
      .on("error", reject);
  });
  return JSON.parse(body.toString("utf8"));
});

ipcMain.handle("mira:post", async (_e, url, data) => {
  guardUrl(url);
  const payload = JSON.stringify(data || {});
  const body = await new Promise((resolve, reject) => {
    const req = http.request(
      url,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(payload),
          ...(getToken() ? { "X-Mira-Token": getToken() } : {}),
        },
      },
      (res) => readBody(res).then(resolve, reject),
    );
    req.on("error", reject);
    req.write(payload);
    req.end();
  });
  try {
    return JSON.parse(body.toString("utf8"));
  } catch {
    return body.toString("utf8");
  }
});

ipcMain.handle("mira:speak", async (_e, conversationId, text) => {
  guardUrl(`${API_URL}/call/speak`);
  const body = await windowlessPost(`${API_URL}/call/speak`, {
    conversation_id: conversationId,
    text,
  });
  return body.toString("base64");
});

// Voice-output bridge for Mira's self-initiated messages: renders her words
// into sound outside a call, so the HUD can speak her proactive alerts aloud.
ipcMain.handle("mira:tts", async (_e, text) => {
  guardUrl(`${API_URL}/speech/tts`);
  const body = await windowlessPost(`${API_URL}/speech/tts`, { text });
  return body.toString("base64");
});

// Multipart WAV upload to /speech/transcribe (local whisper STT). Returns the
// transcribed text.
ipcMain.handle("mira:transcribe", async (_e, wavBytes) => {
  guardUrl(`${API_URL}/speech/transcribe`);
  const boundary = "----MiraBoundary" + Math.random().toString(36).slice(2);
  const head = Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="seg.wav"\r\n` +
      `Content-Type: audio/wav\r\n\r\n`,
    "utf8",
  );
  const tail = Buffer.from(`\r\n--${boundary}--\r\n`, "utf8");
  const payload = Buffer.concat([head, Buffer.isBuffer(wavBytes) ? wavBytes : Buffer.from(wavBytes), tail]);
  const body = await new Promise((resolve, reject) => {
    const req = http.request(
      `${API_URL}/speech/transcribe`,
      {
        method: "POST",
        headers: {
          "Content-Type": `multipart/form-data; boundary=${boundary}`,
          "Content-Length": payload.length,
          ...(getToken() ? { "X-Mira-Token": getToken() } : {}),
        },
      },
      (res) => readBody(res).then(resolve, reject),
    );
    req.on("error", reject);
    req.write(payload);
    req.end();
  });
  try {
    return JSON.parse(body.toString("utf8")).text || "";
  } catch {
    return "";
  }
});

// Cheap audio-level wake-word gate: upload the WAV to /speech/wake and return
// whether Mira's name was spoken. The HUD calls this before /speech/transcribe
// so whisper only runs when she's actually summoned.
ipcMain.handle("mira:wakeCheck", async (_e, wavBytes) => {
  guardUrl(`${API_URL}/speech/wake`);
  const boundary = "----MiraBoundary" + Math.random().toString(36).slice(2);
  const head = Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="seg.wav"\r\n` +
      `Content-Type: audio/wav\r\n\r\n`,
    "utf8",
  );
  const tail = Buffer.from(`\r\n--${boundary}--\r\n`, "utf8");
  const payload = Buffer.concat([head, Buffer.isBuffer(wavBytes) ? wavBytes : Buffer.from(wavBytes), tail]);
  const body = await new Promise((resolve, reject) => {
    const req = http.request(
      `${API_URL}/speech/wake`,
      {
        method: "POST",
        headers: {
          "Content-Type": `multipart/form-data; boundary=${boundary}`,
          "Content-Length": payload.length,
          ...(getToken() ? { "X-Mira-Token": getToken() } : {}),
        },
      },
      (res) => readBody(res).then(resolve, reject),
    );
    req.on("error", reject);
    req.write(payload);
    req.end();
  });
  try {
    return JSON.parse(body.toString("utf8")).heard !== false;
  } catch {
    return true; // be permissive: if the gate is unavailable, don't block speech
  }
});

function windowlessPost(url, data) {
  const payload = JSON.stringify(data || {});
  return new Promise((resolve, reject) => {
    const req = http.request(
      url,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(payload),
          ...(getToken() ? { "X-Mira-Token": getToken() } : {}),
        },
      },
      (res) => readBody(res).then(resolve, reject),
    );
    req.on("error", reject);
    req.write(payload);
    req.end();
  });
}

// ---- stack supervision -------------------------------------------------------
// In packaged/portable mode the companion owns the whole stack (backend +
// ollama + host agent). In dev mode it only self-boots when asked, so a bare
// `npm start` against an already-running backend behaves exactly as before.
const shouldSupervise = () => {
  if (process.env.MIRA_SUPERVISE === "1") return true;
  if (process.env.MIRA_SUPERVISE === "0") return false;
  if (hasPortableRuntime()) return true;
  return false;
};

function startStack() {
  if (stack || !shouldSupervise()) return;
  stack = new MiraStack();
  stack.onChange = (s) => {
    if (mainWindow && mainWindow.webContents) mainWindow.webContents.send("mira:stack", s);
    if (!s) return;
    const target = withToken(s.baseUrl || WEB_URL);
    // Backend came up (or moved to a free port): if the window is still on the
    // waiting page, navigate to the live Mira UI instead of making the user
    // hit "try again" once the cold start finally finishes.
    if (mainWindow && mainWindow.webContents && s.healthy) {
      const current = mainWindow.webContents.getURL() || "";
      if (current.startsWith("data:text/html") || !current.startsWith(s.baseUrl || WEB_URL)) {
        mainWindow.loadURL(target);
      }
    }
    // If the stack had to move off the default port (a foreign backend was
    // squatting on 8000), point the window and HUD at where Mira actually is.
    if (s.baseUrl && s.baseUrl !== WEB_URL && s.baseUrl !== API_URL) {
      if (mainWindow && mainWindow.webContents) {
        const current = mainWindow.webContents.getURL() || "";
        if (!current.startsWith(s.baseUrl)) mainWindow.loadURL(withToken(s.baseUrl));
      }
      if (hudWindow && hudWindow.webContents) hudWindow.webContents.send("mira:api-url", s.baseUrl);
    }
  };
  stack.start().catch((err) => console.error("stack start failed:", err));
}

function stopStack() {
  if (stack) {
    stack.stop();
    stack = null;
  }
}

// ---- lifecycle -----------------------------------------------------------------

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    // The HUD needs the microphone for hands-free voice. Electron's default is
    // to deny media without a handler.
    session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
      callback(permission === "media");
    });
    createTray();
    createMainWindow();
    createHud();
    globalShortcut.register("CommandOrControl+Shift+M", toggleHud);
    app.on("activate", () => (mainWindow ? mainWindow.show() : createMainWindow()));
    startStack();
  });
}

app.on("window-all-closed", () => {
  // Keep running in the tray — that's the point of the companion.
});

app.on("before-quit", () => {
  globalShortcut.unregisterAll();
  stopStack();
  // Destroy tray so the icon disappears from the system tray.
  if (tray) {
    tray.destroy();
    tray = null;
  }
  // Force-close any remaining windows so they don't linger.
  if (mainWindow) { mainWindow.destroy(); mainWindow = null; }
  if (hudWindow) { hudWindow.destroy(); hudWindow = null; }
});