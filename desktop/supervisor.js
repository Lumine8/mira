// Mira stack supervisor.
//
// Gives the Electron companion the ability to RUN all of Mira, not just open a
// window onto a backend someone else started. In a packaged / portable install
// it owns everything:
//
//   * Ollama     - the portable binary + bundled models (runtime/ollama)
//   * backend    - uvicorn app.main:app on 127.0.0.1:8000 (runtime/python + runtime/backend)
//   * host agent - eyes/hands that watch the screen and run approved actions (runtime/host)
//
// The same module works from a dev checkout (backend/.venv, system Ollama), so
// behaviour is identical before and after packaging.
//
// The supervisor is lenient by design:
//   * if the backend is already healthy on :8000 when we start, we adopt it
//     instead of spawning a second one;
//   * if an Ollama is already answering on :11434, we reuse it;
//   * missing pieces (host agent, portable ollama) degrade gracefully instead
//     of failing the whole app.
"use strict";

const path = require("path");
const fs = require("fs");
const http = require("http");
const { spawn } = require("child_process");

const PORT = 8000;
const OLLAMA_PORT = 11434;
const BASE_URL = `http://127.0.0.1:${PORT}`;

function exists(p) {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

function healthOk(url, timeoutMs = 3000) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

// True when the backend on `url` also serves the web UI (its root returns HTML).
// The Docker stack serves postgres-mode API only: /health is 200 but / is the
// JSON `{"detail":"Not Found"}` — adopting it would leave the window blank.
function servesWebUi(url, timeoutMs = 3000) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      const html = (res.headers["content-type"] || "").includes("text/html");
      res.resume();
      resolve(res.statusCode === 200 && html);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

function loadEnvFile(envPath) {
  const out = {};
  try {
    for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
      const t = line.trim();
      if (!t || t.startsWith("#")) continue;
      const m = t.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
      if (m) out[m[1]] = m[2].trim().replace(/^"|"$/g, "");
    }
  } catch {
    /* no env file */
  }
  return out;
}

// Resolve where the stack lives: a bundled portable runtime first, then the dev
// checkout. PORTABLE_EXECUTABLE_DIR is set by electron-builder portable targets;
// for an installed app the runtime/ dir sits next to the exe.
function resolveRuntime() {
  const exeDir = process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(process.execPath);
  const portableRuntime = path.join(exeDir, "runtime");
  const portableBackend = path.join(portableRuntime, "backend");

  if (exists(path.join(portableBackend, "app", "main.py"))) {
    return {
      mode: "portable",
      dataDir: path.join(exeDir, "data"),
      backendDir: portableBackend,
      backendPython: path.join(portableRuntime, "python", "python.exe"),
      ollama: path.join(portableRuntime, "ollama", "ollama.exe"),
      ollamaModelsDir: path.join(portableRuntime, "ollama", "models"),
      hostDir: path.join(portableBackend, "host"),
      hostPython: path.join(portableRuntime, "host", "python", "python.exe"),
      envFile: path.join(portableBackend, ".env"),
    };
  }

  const root = path.resolve(__dirname, "..");
  const backendDir = path.join(root, "backend");
  return {
    mode: "dev",
    dataDir: path.join(root, "data"),
    backendDir,
    backendPython: path.join(backendDir, ".venv", "Scripts", "python.exe"),
    ollama: null,
    ollamaModelsDir: null,
    hostDir: path.join(backendDir, "host"),
    hostPython: path.join(backendDir, "host", ".venv", "Scripts", "python.exe"),
    envFile: path.join(root, ".env"),
  };
}

function hasPortableRuntime() {
  const exeDir = process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(process.execPath);
  return exists(path.join(exeDir, "runtime", "backend", "app", "main.py"));
}

function killTree(pid) {
  if (!pid) return;
  try {
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
    } else {
      process.kill(pid, "SIGKILL");
    }
  } catch {
    /* already gone */
  }
}

class MiraStack {
  constructor() {
    this.rt = resolveRuntime();
    this.procs = { backend: null, ollama: null, agent: null };
    this.healthy = false;
    this.stopped = false;
    this.restartTimer = null;
    this.logs = {};
    this.onChange = null;
    // The port the backend actually runs on. Defaults to 8000; if a foreign
    // backend (the Docker stack, another app) is already squatting there, we
    // pick a free port so the installed app always owns its own stack.
    this.port = PORT;
    this.baseUrl = BASE_URL;
  }

  status() {
    return {
      mode: this.rt.mode,
      healthy: this.healthy,
      baseUrl: this.baseUrl,
      port: this.port,
      backend: this.procs.backend ? { pid: this.procs.backend.pid, alive: this.procs.backend.exitCode === null } : null,
      ollama: this.procs.ollama ? { pid: this.procs.ollama.pid, alive: this.procs.ollama.exitCode === null } : null,
      agent: this.procs.agent ? { pid: this.procs.agent.pid, alive: this.procs.agent.exitCode === null } : null,
    };
  }

  _emit() {
    if (this.onChange) this.onChange(this.status());
  }

  _log(name, stream) {
    const dir = path.join(this.rt.dataDir, "logs");
    try {
      fs.mkdirSync(dir, { recursive: true });
    } catch {
      /* best effort */
    }
    if (!this.logs[name]) {
      try {
        this.logs[name] = fs.createWriteStream(path.join(dir, `${name}.log`), { flags: "a" });
      } catch {
        this.logs[name] = null;
      }
    }
    if (this.logs[name]) this.logs[name].write(stream);
  }

  _spawn(name, cmd, args, opts = {}) {
    const child = spawn(cmd, args, {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
      ...opts,
    });
    this.procs[name] = child;
    child.stdout.on("data", (d) => this._log(name, d));
    child.stderr.on("data", (d) => this._log(name, d));
    child.on("exit", (code) => {
      this._log(name, `\n[${name}] exited (${code})\n`);
      if (this.procs[name] === child) this.procs[name] = null;
      this._emit();
      if (name === "backend" && !this.stopped && code !== 0) {
        // Backend died under us (not a clean shutdown, not an adopted server).
        clearTimeout(this.restartTimer);
        this.restartTimer = setTimeout(() => {
          if (!this.stopped && !this.healthy) this._startBackend();
        }, 2000);
      }
    });
    child.on("error", (err) => {
      this._log(name, `\n[${name}] spawn error: ${err.message}\n`);
      if (this.procs[name] === child) this.procs[name] = null;
      this._emit();
    });
    this._emit();
    return child;
  }

  async _ensureOllama() {
    if (await healthOk(`http://127.0.0.1:${OLLAMA_PORT}/api/version`, 800)) {
      return true; // someone already serving ollama (dev / system service)
    }
    if (!this.rt.ollama || !exists(this.rt.ollama)) return false;
    const env = { ...process.env, OLLAMA_HOST: `127.0.0.1:${OLLAMA_PORT}` };
    if (this.rt.ollamaModelsDir) env.OLLAMA_MODELS = this.rt.ollamaModelsDir;
    this._spawn("ollama", this.rt.ollama, ["serve"], { env });
    for (let i = 0; i < 30; i++) {
      if (await healthOk(`http://127.0.0.1:${OLLAMA_PORT}/api/version`, 800)) return true;
      await new Promise((r) => setTimeout(r, 400));
    }
    return false;
  }

  _startBackend() {
    const env = { ...process.env, ...loadEnvFile(this.rt.envFile) };
    env.OLLAMA_HOST = `http://127.0.0.1:${OLLAMA_PORT}`;
    env.DATABASE_URL_OVERRIDE = `sqlite:///${this.rt.dataDir.replace(/\\/g, "/")}/mira.db`;
if (this.rt.mode === "portable") {
      // In a portable install the STT + KWS models must live in the writable
      // data dir, not next to the read-only program files. The resolver looks
      // for files directly in the given dir, so point at the model folders
      // themselves (the whisper one is nested under data/models/sherpa).
      env.STT_MODEL_DIR = path.join(this.rt.dataDir, "models", "sherpa", "sherpa-onnx-whisper-base.en");
      env.KWS_MODEL_DIR = path.join(
        this.rt.dataDir,
        "models",
        "kws",
        "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01",
      );
      fs.mkdirSync(this.rt.dataDir, { recursive: true });
    }
    try {
      fs.mkdirSync(this.rt.dataDir, { recursive: true });
    } catch {
      /* best effort */
    }
    const host = process.env.MIRA_API_HOST || env.API_HOST || "127.0.0.1";
    this._spawn(
      "backend",
      this.rt.backendPython,
      ["-m", "uvicorn", "app.main:app", "--host", host, "--port", String(this.port)],
      { cwd: this.rt.backendDir, env },
    );
  }

  _startAgent() {
    if (!exists(path.join(this.rt.hostDir, "agent.py"))) return;
    const python = exists(this.rt.hostPython) ? this.rt.hostPython : this.rt.backendPython;
    const env = { ...process.env };
    if (!env.MIRA_ACCESS_TOKEN) env.MIRA_ACCESS_TOKEN = loadEnvFile(this.rt.envFile).MIRA_ACCESS_TOKEN || "";
    this._spawn("agent", python, ["agent.py"], { cwd: this.rt.hostDir, env });
  }

  async start() {
    // A backend on our port already. Only adopt it if it is OURS — i.e. it also
    // serves the web UI. A foreign backend (the Docker stack's postgres-mode API)
    // passes /health but returns JSON at /, which would leave the window blank.
    if (await healthOk(`${this.baseUrl}/health`)) {
      if (await servesWebUi(this.baseUrl)) {
        this.healthy = true; // adopt an already-running Mira backend
        this._emit();
        return;
      }
      // Foreign backend squatting on our port: move to a free one.
      for (let port = PORT + 1; port < PORT + 100; port++) {
        if (!(await healthOk(`http://127.0.0.1:${port}/health`, 800))) {
          this.port = port;
          this.baseUrl = `http://127.0.0.1:${port}`;
          break;
        }
      }
      this._emit();
    }
    await this._ensureOllama();
    this._startBackend();
    // Cold starts vary: the bundled python imports sherpa + kokoro (and Windows
    // Defender may scan the freshly extracted runtime first time). Give it a
    // generous window, and if it still isn't up, keep retrying in the
    // background rather than giving up and leaving the app stuck "offline".
    for (let i = 0; i < 120 && !this.stopped; i++) {
      if (await healthOk(`${this.baseUrl}/health`, 5000)) {
        this.healthy = true;
        this._emit();
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    if (!this.healthy && !this.stopped) {
      this._emit();
      this._healthRetry = setInterval(async () => {
        if (this.stopped) return clearInterval(this._healthRetry);
        if (this.healthy) return clearInterval(this._healthRetry);
        if (await healthOk(`${this.baseUrl}/health`, 5000)) {
          this.healthy = true;
          this._emit();
          if (this.healthy) this._startAgent();
          clearInterval(this._healthRetry);
        }
      }, 3000);
    }
    if (this.healthy) this._startAgent();
    this._emit();
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.restartTimer);
    if (this._healthRetry) {
      clearInterval(this._healthRetry);
      this._healthRetry = null;
    }
    for (const name of Object.keys(this.procs)) {
      killTree(this.procs[name] && this.procs[name].pid);
      this.procs[name] = null;
    }
    for (const k of Object.keys(this.logs)) {
      try {
        this.logs[k].end();
      } catch {
        /* ignore */
      }
      delete this.logs[k];
    }
    this.healthy = false;
    this._emit();
  }
}

module.exports = { MiraStack, resolveRuntime, hasPortableRuntime, BASE_URL };