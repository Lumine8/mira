// Bridge from the HUD renderer to the main process. Everything the HUD needs
// is explicit here: config, native alerts, and a CORS-free GET for local data.
"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("mira", {
  config: () => ipcRenderer.invoke("mira:config"),
  setToken: (token) => ipcRenderer.invoke("mira:set-token", token),
  notify: (title, body) => ipcRenderer.invoke("mira:notify", { title, body }),
  toggleHud: () => ipcRenderer.invoke("mira:toggle-hud"),
  openMain: () => ipcRenderer.invoke("mira:open-main"),
  quit: () => ipcRenderer.invoke("mira:quit"),
  get: (url) => ipcRenderer.invoke("mira:get", url),
  post: (url, body) => ipcRenderer.invoke("mira:post", url, body),
  speak: (conversationId, text) => ipcRenderer.invoke("mira:speak", conversationId, text),
  tts: (text) => ipcRenderer.invoke("mira:tts", text),
  transcribe: (wavBytes) => ipcRenderer.invoke("mira:transcribe", wavBytes),
});