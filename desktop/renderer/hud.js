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
let inReply = false; // true while she's mid-reply — presence poll must not clobber it

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
  // Never overwrite an active reply's status: she may be thinking for a while,
  // and the 10s presence poll would otherwise wipe "thinking…" a second in.
  if (inReply) return;
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
  const watchEl = $("stat-watching");
  const fw = sys?.focused_window;
  if (fw) {
    watchEl.textContent = fw.length > 40 ? `${fw.slice(0, 40)}…` : fw;
    watchEl.title = sys.clipboard_text
      ? `copied: ${sys.clipboard_text.slice(0, 120)}`
      : fw;
  } else {
    watchEl.textContent = "—";
    watchEl.title = "";
  }
}

function renderPending(pending) {
  $("pending-count").textContent = String(pending.length);
}

// ---- quick-ask: start a call, chat over WS, hear the reply -----------------

// Streaming speech: Gemini streams tokens as it thinks, so we speak each
// complete sentence the moment it arrives instead of waiting for the whole
// reply. TTS overlaps generation — the delay between text and voice all but
// disappears. The audio queue still serializes playback, and a promise chain
// serializes the /call/speak HTTP calls (kokoro's pipeline is not safe to run
// concurrently).
let streamed = ""; // accumulated tokens of the current reply
let spokenChars = 0; // chars of `streamed` already dispatched to speech
let speechChain = Promise.resolve();

function speakChunk(text) {
  if (!text || !text.trim()) return;
  speechChain = speechChain.then(() => speakReply(text));
}

// Sentence enders: . ! ? … followed by whitespace (so "U.S." doesn't cut).
function flushCompleteSentences() {
  if (!streamed) return;
  const re = /[.!?…](?=\s|$)/g;
  let last = -1;
  let m;
  while ((m = re.exec(streamed)) !== null) last = m.index + 1;
  if (last <= spokenChars) return;
  const next = streamed.slice(spokenChars, last);
  if (next.trim().length < 6) return; // too tiny to speak yet ("Ok." etc.)
  speakChunk(next);
  spokenChars = last;
}

async function connectConvo() {
  try {
    const res = await window.mira.post(`${apiUrl}/call/start`, { kind: "call" });
    conversationId = res.conversation_id;
    const wsUrl = res.ws_url.replace(/^http/, "ws");
    convoWs = new WebSocket(wsUrl + (token ? `?token=${encodeURIComponent(token)}` : ""));
    convoWs.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "message" && msg.speaker === "mira") {
        inReply = false;
        setMiraLine("she answered", "is-speaking");
        addAlert("Mira", msg.content);
        if (!streamed) {
          // Nothing streamed (fallback reply like "I asked …", meeting end) —
          // speak the whole message as before.
          speakChunk(msg.content);
        } else {
          // Speak whatever never hit a sentence boundary mid-stream (the tail).
          const tail = streamed.slice(spokenChars);
          streamed = "";
          spokenChars = 0;
          if (tail.trim()) speakChunk(tail);
        }
      } else if (msg.type === "stream_token") {
        inReply = true;
        setMiraLine("thinking…", "is-speaking");
        streamed += msg.content || "";
        flushCompleteSentences();
      } else if (msg.type === "pending_change") {
        addAlert("approval needed", msg.change.summary || msg.change.kind);
      } else if (msg.type === "error") {
        inReply = false;
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
  inReply = true;
  setMiraLine("she's thinking…", "is-speaking");
  convoWs.send(JSON.stringify({ type: "text", content: text }));
}

// Split long replies into sentence-sized chunks so the first sentence plays
// almost immediately while the rest are still being synthesized.
function splitSpeech(text) {
  const parts = text.match(/[^.!?…]+[.!?…]*/g) || [text];
  const chunks = [];
  let cur = "";
  for (const p of parts) {
    const t = (p || "").trim();
    if (!t) continue;
    if (cur && (cur + " " + t).length > 180) {
      chunks.push(cur);
      cur = t;
    } else {
      cur = cur ? `${cur} ${t}` : t;
    }
  }
  if (cur) chunks.push(cur);
  return chunks.length ? chunks : [text];
}

async function speakReply(text) {
  if (!conversationId || !text) return;
  for (const chunk of splitSpeech(text)) {
    try {
      const b64 = await window.mira.speak(conversationId, chunk);
      if (!b64) continue;
      const audio = new Audio(`data:audio/wav;base64,${b64}`);
      audio.onended = dequeueAudio;
      queueAudio(audio);
    } catch {
      /* TTS unavailable — the text stays on the HUD */
    }
  }
}

// Speak one of Mira's self-initiated messages aloud — her reaching out on her
// own, through the voice-output bridge (no call conversation needed).
async function speakAnnouncement(text) {
  if (!text) return;
  for (const chunk of splitSpeech(text)) {
    try {
      const b64 = await window.mira.tts(chunk);
      if (!b64) continue;
      const audio = new Audio(`data:audio/wav;base64,${b64}`);
      audio.onended = dequeueAudio;
      queueAudio(audio);
    } catch {
      /* TTS unavailable — the alert stays on the HUD */
    }
  }
}

// Speak one reply at a time so overlapping messages don't stomp each other.
let audioQueue = [];
let audioBusy = false;
let speakingNowTimer = null;

function queueAudio(audio) {
  audioQueue.push(audio);
  if (!audioBusy) dequeueAudio();
}

function dequeueAudio() {
  if (audioQueue.length === 0) {
    audioBusy = false;
    speakingNow = false;
    return;
  }
  audioBusy = true;
  speakingNow = true;
  const next = audioQueue.shift();
  // Safety net: if an audio element never fires 'ended' (system hiccup), don't
  // let speakingNow stay true forever — that would silently deafen Mira.
  if (speakingNowTimer) clearTimeout(speakingNowTimer);
  speakingNowTimer = setTimeout(() => {
    if (audioBusy) {
      audioBusy = false;
      speakingNow = false;
    }
  }, 20000);
  next.play().catch(() => {
    dequeueAudio();
  });
}

// ---- voice: continuous local listening (mic -> WAV -> backend whisper) -------
// Hands-free: with listening on, Mira hears whole utterances and answers them.
// The mic stream is split to an analyser for energy-based voice-activity
// detection; speech segments are encoded to WAV and transcribed locally by the
// backend's sherpa-onnx whisper. No audio ever leaves the machine.

let audioCtx = null;
let micStream = null;
let micProc = null;
let listenOn = false;
let speakingNow = false; // set while her TTS audio is playing (avoid hearing herself)

const VAD_PRE_MS = 250; // keep 250ms before speech onset so no first word is lost
const VAD_END_MS = 900; // this much silence ends an utterance (900ms tolerates natural pauses)
const VAD_MAX_MS = 12000; // hard cap on a single utterance
const VAD_MIN_MS = 300; // ignore sub-second noise blips
const VAD_THRESHOLD = 0.02; // RMS floor for speech (lower catches quieter voices)

const vad = { state: "idle", pre: [], buf: [], totalMs: 0, silenceMs: 0, speechMs: 0, floor: 0.015 };

function setListenUI(on) {
  const btn = $("voice-btn");
  btn.classList.toggle("listening", on);
  btn.textContent = on ? "always listening" : "talk to her";
}

async function toggleListen() {
  if (listenOn) return stopListening();
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    addAlert("mic unavailable", String(err.message || err));
    return;
  }
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = audioCtx.createMediaStreamSource(micStream);
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 2048;
  src.connect(analyser);
  micProc = audioCtx.createScriptProcessor(4096, 1, 1);
  const sampleRate = audioCtx.sampleRate;
  const frameMs = (4096 / sampleRate) * 1000;
  micProc.onaudioprocess = (ev) => {
    const samples = ev.inputBuffer.getChannelData(0);
    handleFrame(samples, frameMs, sampleRate);
  };
  analyser.connect(micProc);
  // Route the script processor through a zero-gain node so the graph stays
  // live (onaudioprocess keeps firing) without feeding the mic into the
  // speakers — which would echo back into the VAD and deafen Mira.
  const mute = audioCtx.createGain();
  mute.gain.value = 0;
  micProc.connect(mute);
  mute.connect(audioCtx.destination);
  listenOn = true;
  vad.state = "idle";
  vad.pre = [];
  vad.buf = [];
  vad.totalMs = 0;
  vad.silenceMs = 0;
  vad.speechMs = 0;
  setListenUI(true);
  addAlert("listening", "just talk to her — she'll answer on her own");
}

function stopListening() {
  listenOn = false;
  setListenUI(false);
  if (micProc) {
    micProc.disconnect();
    micProc = null;
  }
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  micStream = null;
  if (audioCtx && audioCtx.state !== "closed") audioCtx.close().catch(() => {});
  audioCtx = null;
  vad.buf = [];
}

function rms(samples) {
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.sqrt(sum / samples.length);
}

function handleFrame(samples, frameMs, sampleRate) {
  const level = rms(samples);
  if (vad.state === "idle") {
    // Track the noise floor so room hum doesn't count as speech.
    vad.floor = Math.min(vad.floor * 0.995 + level * 0.005, 0.03);
    const active = level > Math.max(VAD_THRESHOLD, vad.floor * 2.5);
    vad.pre.push(Float32Array.from(samples));
    const preMs = (vad.pre.reduce((n, a) => n + a.length, 0) / sampleRate) * 1000;
    while (preMs > VAD_PRE_MS && vad.pre.length) {
      vad.pre.shift();
      if (vad.pre.length && vad.pre.reduce((n, a) => n + a.length, 0) / sampleRate * 1000 <= VAD_PRE_MS) break;
    }
    if (active) {
      vad.state = "speech";
      vad.buf = vad.pre.slice();
      vad.pre = [];
      vad.totalMs = VAD_PRE_MS;
      vad.speechMs = 0;
      vad.silenceMs = 0;
    }
    return;
  }
  // speech state
  const active = level > Math.max(VAD_THRESHOLD, vad.floor * 1.5);
  vad.buf.push(Float32Array.from(samples));
  vad.totalMs += frameMs;
  if (active) {
    vad.speechMs += frameMs;
    vad.silenceMs = 0;
  } else {
    vad.silenceMs += frameMs;
  }
  const utterEnd = vad.silenceMs >= VAD_END_MS || vad.totalMs >= VAD_MAX_MS;
  if (utterEnd) {
    const speechMs = vad.speechMs + (vad.silenceMs >= VAD_END_MS ? 0 : VAD_END_MS);
    vad.state = "idle";
    vad.pre = [];
    const collected = vad.buf;
    vad.buf = [];
    vad.speechMs = 0;
    vad.silenceMs = 0;
    vad.totalMs = 0;
    if (speechMs >= VAD_MIN_MS && !speakingNow) sendUtterance(collected, sampleRate);
  }
}

function sendUtterance(chunks, sampleRate) {
  const pcm = new Float32Array(chunks.reduce((n, a) => n + a.length, 0));
  let off = 0;
  for (const c of chunks) {
    pcm.set(c, off);
    off += c.length;
  }
  const wav = encodeWav(pcm, sampleRate);
  const gate = () => {
    // Cheap audio-level gate: does this audio actually contain her name?
    // The backend keyword-spotter answers without running whisper, so chatter
    // she wasn't summoned by never reaches transcription. A false "not heard"
    // must not swallow real speech though — so the gate is a soft hint, and the
    // fuzzy text gate below is the real filter.
    return window.mira.wakeCheck(wav).then(
      (heard) => {
        transcribe(wav);
      },
      () => transcribe(wav), // gate unavailable: fall back to today's behaviour
    );
  };
  const transcribe = (seg) => {
    $("mira-line").classList.add("is-speaking");
    window.mira
      .transcribe(seg)
      .then((text) => {
        $("mira-line").classList.remove("is-speaking");
        const spoken = (text || "").trim();
        if (!spoken) {
          setMiraLine("didn't catch that — try again", "");
          return;
        }
        const gated = applyWakeWord(spoken);
        if (gated === null) return; // ignored — she wasn't summoned
        if (gated) sendAsk(gated);
        else setMiraLine("didn't catch that — try again", "");
      })
      .catch(() => {
        $("mira-line").classList.remove("is-speaking");
        setMiraLine("hearing failed", "");
      });
  };
  gate();
}

// The wake word: she only answers in always-listening mode when she's called
// ("mira, ..."). Whisper base.en is a 39M-param model, so it renders the name
// loosely (myra, meera, mira, "what mire", "merry") and often front-loads a
// filler word ("what", "that", "hey") before it. So instead of requiring an
// exact name at position 0, we look for a name-like word within the first few
// words and strip everything up to and including it. Returns the text with the
// wake word stripped (or null when the utterance clearly didn't summon her).
// No wake word configured = every utterance heard.
const WAKE_GREETINGS =
  /^(hey|hi|hello|okay|ok|so|listen|um|uh|please|good\s*(morning|afternoon|evening))\b[\s,.:!?]*/i;

// Whisper renderings that still mean her name (mira/myra/meera/mire/merry/
// marie/mara/mari...). The loose m-pattern tolerates the base model's sloppy
// vowels. Search window is the first 3 words so a stray filler can't break a
// real summon, but random chatter far from her name still won't match.
const WAKE_NAME = /^m[iyae]{0,2}r[aeiouyrw]{1,2}\b/i;

function applyWakeWord(text) {
  const ww = (state.wake_word || "").trim().toLowerCase();
  if (!ww) return text;
  let lower = text.toLowerCase().trim();
  let rest = lower.replace(WAKE_GREETINGS, "");
  if (rest === lower) rest = lower; // no greeting — keep original start
  const words = rest.split(/[\s,.;:!?]+/).filter(Boolean);
  let hit = -1;
  for (let i = 0; i < Math.min(words.length, 3); i++) {
    if (WAKE_NAME.test(words[i])) {
      hit = i;
      break;
    }
  }
  if (hit === -1) {
    setMiraLine("she's listening — call her by name", "");
    return null;
  }
  const stripped = words.slice(hit + 1).join(" ").trim();
  return stripped || null;
}

function encodeWav(pcm, sampleRate) {
  // 16-bit mono PCM WAV, exactly what the backend's sherpa whisper expects.
  const buf = new ArrayBuffer(44 + pcm.length * 2);
  const v = new DataView(buf);
  const ws = (o, s) => {
    for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i));
  };
  ws(0, "RIFF");
  v.setUint32(4, 36 + pcm.length * 2, true);
  ws(8, "WAVE");
  ws(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  ws(36, "data");
  v.setUint32(40, pcm.length * 2, true);
  let o = 44;
  for (let i = 0; i < pcm.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, pcm[i]));
    v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buf);
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
        speakAnnouncement(msg.content);
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

  // The stack may have had to move to a free port (a foreign backend on 8000).
  // Point every request at the live base and reconnect once.
  if (window.mira.onApiUrl) {
    window.mira.onApiUrl((url) => {
      if (!url || url === apiUrl) return;
      apiUrl = url;
      if (liveWs) {
        liveWs.onclose = null;
        try { liveWs.close(); } catch { /* already closed */ }
        liveWs = null;
      }
      if (convoWs) {
        convoWs.onclose = null;
        try { convoWs.close(); } catch { /* already closed */ }
        convoWs = null;
        conversationId = null;
      }
      refresh();
      connectLive();
    });
  }

  if (!cfg.loggedIn) $("login-row").hidden = false;

  $("ask-btn").addEventListener("click", () => sendAsk($("ask").value));
  $("ask").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") sendAsk($("ask").value);
  });

  const vbtn = $("voice-btn");
  vbtn.addEventListener("click", toggleListen);

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