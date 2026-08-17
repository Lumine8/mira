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
"use strict";

const { app, BrowserWindow, Tray, Menu, Notification, ipcMain, globalShortcut } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");

const WEB_URL = process.env.MIRA_WEB_URL || "http://localhost:8080";
const API_URL = process.env.MIRA_API_URL || "http://localhost:8000";

let tray = null;
let mainWindow = null;
let hudWindow = null;
let hudVisible = true;

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
  mainWindow.on("closed", () => (mainWindow = null));
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

ipcMain.handle("mira:config", () => ({ apiUrl: API_URL, token: getToken(), loggedIn: Boolean(getToken()) }));
ipcMain.handle("mira:set-token", (_e, token) => {
  writeConfig({ ...readConfig(), token: (token || "").trim() });
  if (mainWindow) mainWindow.loadURL(withToken(WEB_URL));
  return { ok: true };
});
ipcMain.handle("mira:notify", (_e, { title, body }) => notify(title || "Mira", body || ""));
ipcMain.handle("mira:toggle-hud", () => toggleHud());
ipcMain.handle("mira:open-main", () => (mainWindow ? mainWindow.show() : createMainWindow()));
ipcMain.handle("mira:quit", () => app.quit());

// JSON GET / POST / speak helpers — CORS-free routes for the file:// renderer.
function guardUrl(url) {
  if (!url.startsWith(API_URL)) throw new Error("refusing non-local URL");
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
  const body = await windowlessPost(`${API_URL}/call/speak`, {
    conversation_id: conversationId,
    text,
  });
  return body.toString("base64");
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
    createTray();
    createMainWindow();
    createHud();
    globalShortcut.register("CommandOrControl+Shift+M", toggleHud);
    app.on("activate", () => (mainWindow ? mainWindow.show() : createMainWindow()));
  });
}

app.on("window-all-closed", () => {
  // Keep running in the tray — that's the point of the companion.
});

app.on("before-quit", () => globalShortcut.unregisterAll());