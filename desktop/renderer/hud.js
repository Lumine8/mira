// Mira HUD — the ambient companion panel.
// Polls her state, the machine's live read, and pending approvals; lets you
// ask quickly (text or hold-to-talk); and surfaces her self-initiated messages
// as in-panel alerts + native notifications.
"use strict";

const $ = (id) => document.getElementById(id);

let apiUrl = "http://localhost:8000";
let token = "";
let state = {};

// Tracked live WS: one for /ws/live (her self-messages), one per quick-ask.
let liveWs = null;
let convoWs = null;
let conversationId = null;

const whoMap = {
  thinking: "thinking",
  speaking: "speaking",
  reflecting: "reflecting",
  observing: "observing",
  resting: "resting",
};

function fmtTime(ts) {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function startClock() {
  const tick = () => ($("clock").textContent = fmtTime(Date.now()));
  tick();
  setInterval(tick, 1000);
}

function setMiraLine(text, cls) {
  $("mira-text").textContent = text || "";
  const el = $("mira-line");
  el.classList.remove("is-thinking", "is-reflecting", "is-speaking");
  if (cls) el.classList.add(cls);
}

function addAlert(title, body) {
  const el = document.createElement("div");
  el.className = "hud__alert";
  const t = document.createElement("strong");
  t.textContent = title;
  el.appendChild(t);
  if (body) {
    el.appendChild(document.createElement("br"));
    el.appendChild(document.createTextNode(body));
  }
  const list = $("alerts");
  list.prepend(el);
  while (list.childNodes.length > 8) list.removeChild(list.lastChild);
}

async function refresh() {
  try {
    const [s, sys, pending] = await Promise.all([
      window.mira.get(`${apiUrl}/mira/state`),
      window.mira.get(`${apiUrl}/mira/system`),
      window.mira.get(`${apiUrl}/mira/tools/pending`),
    ]);
    state = s?.state || {};
    renderPresence(state);
    renderStats(sys || null);
    renderPending(pending || []);
  } catch (err) {
    setMiraLine("offline — waiting for Mira", "");
  }
}

function renderPresence(s) {
  const mood = s.mood || "quiet";
  const tone = whoMap[s.present_energy_level === "high" ? "speaking" : s.thinking || "resting"];
  const who = mood === "quiet" ? "at the door" : `${mood} right now`;
  $("who").textContent = who;
  setMiraLine(s.pending_message || `she feels ${mood}`, tone === "speaking" ? "is-speaking" : "");
}

function renderStats(sys) {
  $("stat-cpu").textContent = sys?.cpu_percent != null ? `${Math.round(sys.cpu_percent)}%` : "—";
  $("stat-mem").textContent = sys?.memory_percent != null ? `${Math.round(sys.memory_percent)}%` : "—";
  const batt = sys?.battery_percent;
  $("stat-batt").textContent = batt != null ? `${batt}%${sys.battery_charging ? " ⚡" : ""}` : "—";
  const idle = sys?.idle_seconds;
  $("stat-idle").textContent =
    idle == null ? "—" : idle < 60 ? `${idle}s` : `${Math.round(idle / 60)}m`;
}

function renderPending(pending) {
  $("pending-count").textContent = String(pending.length);
}

// ---- quick-ask: start a call, chat over WS, hear the reply -----------------

async function connectConvo() {
  try {
    const res = await window.mira.post(`${apiUrl}/call/start`, { kind: "call" });
    conversationId = res.conversation_id;
    const wsUrl = res.ws_url.replace(/^http/, "ws");
    convoWs = new WebSocket(wsUrl + (token ? `?token=${encodeURIComponent(token)}` : ""));
    convoWs.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "message" && msg.speaker === "mira") {
        setMiraLine("she answered", "is-speaking");
        addAlert("Mira", msg.content);
        speakReply(msg.content);
      } else if (msg.type === "stream_token") {
        setMiraLine("thinking…", "is-speaking");
      } else if (msg.type === "pending_change") {
        addAlert("approval needed", msg.change.summary || msg.change.kind);
      } else if (msg.type === "error") {
        addAlert("error", msg.message);
      }
    };
    convoWs.onerror = () => setMiraLine("couldn't reach her", "");
  } catch (err) {
    addAlert("ask failed", String(err.message || err));
  }
}

async function sendAsk(text) {
  text = (text || "").trim();
  if (!text) return;
  $("ask").value = "";
  if (!convoWs || convoWs.readyState !== WebSocket.OPEN) await connectConvo();
  if (!convoWs || convoWs.readyState !== WebSocket.OPEN) return;
  setMiraLine("she's thinking…", "is-speaking");
  convoWs.send(JSON.stringify({ type: "text", content: text }));
}

async function speakReply(text) {
  if (!conversationId || !text) return;
  try {
    const b64 = await window.mira.speak(conversationId, text);
    if (!b64) return;
    const audio = new Audio(`data:audio/wav;base64,${b64}`);
    audio.play();
  } catch {
    /* TTS unavailable — the text stays on the HUD */
  }
}

// ---- voice: push-to-talk via the browser's speech recognition ---------------

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;

function startVoice() {
  if (!SR) {
    addAlert("voice unavailable", "this build has no speech recognition");
    return;
  }
  rec = new SR();
  rec.lang = "en-US";
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.onresult = (ev) => {
    const heard = ev.results[0][0].transcript.trim();
    $("voice-btn").classList.remove("listening");
    $("voice-btn").textContent = "hold to talk";
    if (heard) sendAsk(heard);
  };
  rec.onerror = () => {
    $("voice-btn").classList.remove("listening");
    $("voice-btn").textContent = "hold to talk";
  };
  rec.onend = () => {
    $("voice-btn").classList.remove("listening");
    $("voice-btn").textContent = "hold to talk";
  };
  rec.start();
  $("voice-btn").classList.add("listening");
  $("voice-btn").textContent = "listening…";
}

// ---- live channel: her self-initiated messages ------------------------------

function connectLive() {
  const scheme = apiUrl.startsWith("https") ? "wss" : "ws";
  liveWs = new WebSocket(`${scheme}://${apiUrl.replace(/^https?:\/\//, "")}/ws/live?token=${encodeURIComponent(token)}`);
  liveWs.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "self_message") {
        setMiraLine("she's speaking", "is-speaking");
        addAlert("Mira reached out", msg.content);
        window.mira.notify("Mira", msg.content);
      } else if (msg.type === "mote") {
        addAlert("mote", msg.word || msg.kind);
      }
    } catch {
      /* ignore */
    }
  };
  liveWs.onclose = () => setTimeout(connectLive, 5000);
}

// ---- wiring ------------------------------------------------------------------

async function init() {
  const cfg = await window.mira.config();
  apiUrl = cfg.apiUrl;
  token = cfg.token;
  startClock();
  refresh();
  setInterval(refresh, 10000);
  connectLive();

  if (!cfg.loggedIn) $("login-row").hidden = false;

  $("ask-btn").addEventListener("click", () => sendAsk($("ask").value));
  $("ask").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") sendAsk($("ask").value);
  });

  const vbtn = $("voice-btn");
  vbtn.addEventListener("mousedown", startVoice);
  vbtn.addEventListener("mouseup", () => rec && rec.stop());

  $("close-btn").addEventListener("click", () => window.mira.toggleHud());

  $("token-btn").addEventListener("click", async () => {
    const val = $("token-input").value.trim();
    if (!val) return;
    await window.mira.setToken(val);
    token = val;
    $("login-row").hidden = true;
    $("token-input").value = "";
    addAlert("signed in", "Mira is home again");
    refresh();
    connectLive();
  });

  $("open-btn").addEventListener("click", () => window.mira.openMain());
  $("quit-btn").addEventListener("click", () => window.mira.quit());

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });
}

init();