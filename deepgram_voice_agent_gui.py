#!/usr/bin/env python3
"""Local Deepgram Voice Agent GUI and key-safe WebSocket proxy.

The browser captures microphone PCM and renders returned TTS audio, while this
server holds the Deepgram API key and relays frames to the Voice Agent API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import uvicorn
import websockets
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response


APP_NAME = "Deepgram Voice Agent GUI"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18087
DEFAULT_SECRET_FILE = Path("/adapt/secrets/m2.env")
DEFAULT_KEY_ENVS = ("DEEPGRAM_API_KEY", "DEEPGRAM_API_KEY_nc")
DEFAULT_DEEPSEEK_KEY_ENVS = ("DEEPSEEK_API_KEY",)
VOICE_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"
DEFAULT_THINK_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_THINK_MODEL = "deepseek-v4-flash"
DEFAULT_PROXY_AUTH_KEY_ENVS = ("sage_20500_gateway_token",)
ASSET_DIR = Path(__file__).resolve().parent / "assets"

LOGGER = logging.getLogger("deepgram_voice_agent_gui")
ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)\s*$")


def _strip_env_value(raw_value: str) -> str:
    """Return an env-file value without leaking comments, quotes, or whitespace."""

    value = raw_value.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]
        return value[1:]
    return value.split(" #", 1)[0].strip()


def load_secret_from_file(secret_file: Path, names: tuple[str, ...]) -> str:
    """Load the first non-empty named value from an env file.

    Parameters:
        secret_file: Path to the env-style file to scan.
        names: Candidate variable names in priority order.

    Returns:
        The first matching secret value, or an empty string when unavailable.

    Errors:
        File read errors are logged and treated as a missing secret so the UI can
        report configuration status without crashing at import time.
    """

    wanted = set(names)
    try:
        lines = secret_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        LOGGER.warning("Could not read Deepgram secret file %s: %s", secret_file, exc)
        return ""

    values: dict[str, str] = {}
    for line in lines:
        match = ENV_LINE_RE.match(line)
        if not match:
            continue
        name, raw_value = match.groups()
        if name in wanted and name not in values:
            value = _strip_env_value(raw_value)
            if value:
                values[name] = value

    for name in names:
        value = values.get(name, "")
        if value:
            return value
    return ""


def deepgram_key() -> str:
    """Resolve the Deepgram API key without printing or exposing it."""

    key_envs = tuple(
        item.strip()
        for item in os.environ.get("VOICE_AGENT_DEEPGRAM_KEY_ENVS", ",".join(DEFAULT_KEY_ENVS)).split(",")
        if item.strip()
    )
    for name in key_envs:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    secret_file = Path(os.environ.get("VOICE_AGENT_SECRET_FILE", str(DEFAULT_SECRET_FILE)))
    return load_secret_from_file(secret_file, key_envs)


def deepseek_key() -> str:
    """Resolve the DeepSeek API key without printing or exposing it."""

    key_envs = tuple(
        item.strip()
        for item in os.environ.get(
            "VOICE_AGENT_DEEPSEEK_KEY_ENVS", ",".join(DEFAULT_DEEPSEEK_KEY_ENVS)
        ).split(",")
        if item.strip()
    )
    for name in key_envs:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    secret_file = Path(os.environ.get("VOICE_AGENT_SECRET_FILE", str(DEFAULT_SECRET_FILE)))
    return load_secret_from_file(secret_file, key_envs)


def proxy_auth_token() -> str:
    """Resolve the bearer token for the public TeamADAPT LLM proxy."""

    key_envs = tuple(
        item.strip()
        for item in os.environ.get(
            "VOICE_AGENT_PROXY_AUTH_KEY_ENVS", ",".join(DEFAULT_PROXY_AUTH_KEY_ENVS)
        ).split(",")
        if item.strip()
    )
    for name in key_envs:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    secret_file = Path(os.environ.get("VOICE_AGENT_SECRET_FILE", str(DEFAULT_SECRET_FILE)))
    return load_secret_from_file(secret_file, key_envs)


def public_config() -> dict[str, Any]:
    """Return non-secret GUI defaults."""

    return {
        "app": APP_NAME,
        "voiceAgentUrl": VOICE_AGENT_URL,
        "thinkUrl": os.environ.get("VOICE_AGENT_THINK_URL", DEFAULT_THINK_URL),
        "thinkProvider": "deepseek",
        "thinkModel": os.environ.get("VOICE_AGENT_THINK_MODEL", DEFAULT_THINK_MODEL),
        "listenModel": os.environ.get("VOICE_AGENT_LISTEN_MODEL", "nova-2"),
        "speakModel": os.environ.get("VOICE_AGENT_SPEAK_MODEL", "aura-2-asteria-en"),
        "prompt": os.environ.get(
            "VOICE_AGENT_PROMPT",
            (
                "You are the local Adapt voice bridge. Keep replies concise, "
                "natural, and immediately useful. Do not mention transport, "
                "routing, markdown, or implementation details."
            ),
        ),
        "sources": {
            "deepgram": "https://developers.deepgram.com/reference/voice-agent/voice-agent",
            "deepgramThink": "https://developers.deepgram.com/docs/voice-agent-llm-models",
            "deepseek": "https://api-docs.deepseek.com/api/create-chat-completion",
            "personaplex": "https://research.nvidia.com/labs/adlr/personaplex/",
        },
    }


app = FastAPI(title=APP_NAME)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Serve the local GUI."""

    return HTML


@app.get("/api/config")
async def api_config() -> JSONResponse:
    """Return GUI configuration without secrets."""

    return JSONResponse(public_config())


@app.get("/favicon.ico")
async def favicon() -> Response:
    """Serve a tiny local icon to keep the browser console clean."""

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="8" fill="#101214"/>'
        '<circle cx="32" cy="32" r="18" fill="#62d27f"/>'
        '<circle cx="32" cy="32" r="8" fill="#101214"/>'
        "</svg>"
    )
    return Response(svg, media_type="image/svg+xml")


@app.get("/assets/{filename}")
async def asset(filename: str) -> FileResponse:
    """Serve bundled visual assets for the voice indicator."""

    allowed = {"dg-voice-two-loops-colored.png", "talking-colors.png"}
    if filename not in allowed:
        return Response(status_code=404)
    return FileResponse(ASSET_DIR / filename, media_type="image/png")


@app.get("/api/health")
async def api_health() -> JSONResponse:
    """Return service and credential readiness without exposing credentials."""

    return JSONResponse(
        {
            "ok": bool(deepgram_key()) and bool(deepseek_key()),
            "deepgramKeyConfigured": bool(deepgram_key()),
            "deepseekKeyConfigured": bool(deepseek_key()),
            "proxyAuthConfigured": bool(proxy_auth_token()),
            "endpoint": VOICE_AGENT_URL,
            "thinkUrl": public_config()["thinkUrl"],
            "thinkModel": public_config()["thinkModel"],
        }
    )


@app.websocket("/ws/voice")
async def ws_voice_proxy(browser: WebSocket) -> None:
    """Relay browser PCM and JSON settings to Deepgram Voice Agent."""

    await browser.accept()
    key = deepgram_key()
    if not key:
        await browser.send_json(
            {
                "type": "VoiceUpstreamError",
                "message": "DEEPGRAM_API_KEY is not configured server-side.",
            }
        )
        await browser.close(code=1011, reason="missing deepgram key")
        return

    try:
        async with websockets.connect(
            VOICE_AGENT_URL,
            additional_headers={"Authorization": f"Token {key}"},
            ping_interval=20,
            close_timeout=10,
            compression=None,
        ) as upstream:
            tasks = (
                asyncio.create_task(_browser_to_deepgram(browser, upstream)),
                asyncio.create_task(_deepgram_to_browser(upstream, browser)),
            )
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
    except Exception as exc:
        LOGGER.warning("Deepgram voice proxy closed: %s", exc)
        try:
            await browser.send_json({"type": "VoiceUpstreamError", "message": str(exc)})
        except Exception:
            pass
        try:
            await browser.close(code=1011, reason="voice upstream closed")
        except Exception:
            pass


async def _browser_to_deepgram(browser: WebSocket, upstream: Any) -> None:
    """Forward browser text and binary frames to Deepgram."""

    while True:
        frame = await browser.receive()
        if frame["type"] == "websocket.disconnect":
            await upstream.close()
            return
        if frame.get("bytes") is not None:
            await upstream.send(frame["bytes"])
        elif frame.get("text") is not None:
            await upstream.send(rewrite_settings_message(frame["text"]))


def rewrite_settings_message(message: str) -> str:
    """Inject server-held DeepSeek settings into the Voice Agent configuration."""

    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return message
    if payload.get("type") != "Settings":
        return message

    key = deepseek_key()
    proxy_token = proxy_auth_token()
    think_url = os.environ.get("VOICE_AGENT_THINK_URL", DEFAULT_THINK_URL)

    agent = payload.setdefault("agent", {})
    headers = {"content-type": "application/json"}
    if "dg.adaptdev.ai" in think_url:
        if proxy_token:
            headers["authorization"] = f"Bearer {proxy_token}"
        else:
            LOGGER.warning("Proxy auth token missing for public dg.adaptdev.ai think URL")
    elif key:
        headers["authorization"] = f"Bearer {key}"
    else:
        LOGGER.warning("DeepSeek key missing; leaving browser think settings unchanged")
        return message

    agent["think"] = {
        "provider": {
            "type": "open_ai",
            "model": os.environ.get("VOICE_AGENT_THINK_MODEL", DEFAULT_THINK_MODEL),
            "temperature": float(os.environ.get("VOICE_AGENT_THINK_TEMPERATURE", "0.35")),
        },
        "endpoint": {
            "url": think_url,
            "headers": headers,
        },
        "prompt": public_config()["prompt"],
    }
    return json.dumps(payload, separators=(",", ":"))


async def _deepgram_to_browser(upstream: Any, browser: WebSocket) -> None:
    """Forward Deepgram JSON events and binary audio to the browser."""

    async for message in upstream:
        if isinstance(message, bytes):
            await browser.send_bytes(message)
        else:
            await browser.send_text(message)


def main() -> None:
    """Run the local GUI server."""

    logging.basicConfig(level=os.environ.get("VOICE_AGENT_LOG_LEVEL", "INFO"))
    host = os.environ.get("VOICE_AGENT_HOST", DEFAULT_HOST)
    port = int(os.environ.get("VOICE_AGENT_PORT", str(DEFAULT_PORT)))
    uvicorn.run(app, host=host, port=port, log_level="info")


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Deepgram Voice Agent</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;650;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      color-scheme: dark light;
      --bg: #101214;
      --panel: #181b1f;
      --panel-2: #20252a;
      --text: #f3f2ec;
      --muted: #a8adb4;
      --line: #363b42;
      --green: #62d27f;
      --amber: #e3b24c;
      --red: #ff6b6b;
      --blue: #63a8ff;
      --ink: #0f1114;
      --radius: 8px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        linear-gradient(180deg, rgba(99, 168, 255, 0.08), transparent 34%),
        var(--bg);
      color: var(--text);
      font-family: Inter, system-ui, sans-serif;
      letter-spacing: 0;
    }
    button, input, select, textarea { font: inherit; }
    button {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: var(--radius);
      min-height: 42px;
      padding: 0 14px;
      cursor: pointer;
    }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    button.primary { background: var(--green); border-color: var(--green); color: var(--ink); font-weight: 800; }
    button.danger { background: transparent; border-color: rgba(255, 107, 107, 0.55); color: #ffb0b0; }
    button.warn { background: rgba(227, 178, 76, 0.12); border-color: rgba(227, 178, 76, 0.55); color: #ffd47d; }
    a { color: #9ec7ff; }
    .shell {
      width: min(1180px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 20px 0 28px;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 0 18px;
    }
    .brand h1 {
      margin: 0;
      font-size: clamp(1.4rem, 4vw, 2.5rem);
      letter-spacing: 0;
      line-height: 1;
    }
    .brand p { margin: 8px 0 0; color: var(--muted); max-width: 720px; }
    .status {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 9px 12px;
      display: flex;
      align-items: center;
      gap: 9px;
      background: rgba(24, 27, 31, 0.86);
      white-space: nowrap;
      font-family: "JetBrains Mono", monospace;
      font-size: 0.82rem;
    }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--red); display: inline-block; }
    .dot.ready { background: var(--green); }
    .dot.busy { background: var(--amber); }
    .grid {
      display: grid;
      grid-template-columns: minmax(300px, 0.8fr) minmax(320px, 1.2fr);
      gap: 16px;
      align-items: start;
    }
    .panel {
      background: rgba(24, 27, 31, 0.94);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 16px;
    }
    .stage {
      min-height: 360px;
      display: grid;
      place-items: center;
      text-align: center;
    }
    .stage > div {
      width: min(100%, 704px);
      display: grid;
      justify-items: center;
    }
    .orb {
      width: min(58vw, 260px);
      aspect-ratio: 1;
      position: relative;
      display: grid;
      place-items: center;
      border-radius: 50%;
      transition: transform 160ms ease;
      isolation: isolate;
    }
    .orb::before {
      content: "";
      position: absolute;
      inset: 31%;
      border-radius: 999px;
      background:
        radial-gradient(circle, rgba(0, 243, 255, 0.23), transparent 62%),
        radial-gradient(circle, rgba(255, 31, 222, 0.16), transparent 68%);
      filter: blur(22px);
      opacity: 0.86;
      z-index: -1;
    }
    .voice-art {
      position: absolute;
      inset: -2%;
      width: 104%;
      height: 104%;
      object-fit: contain;
      filter: drop-shadow(0 0 12px rgba(0, 243, 255, 0.32));
      opacity: 0;
      transform-origin: center;
      transition: opacity 160ms ease, transform 160ms ease, filter 160ms ease;
    }
    .voice-art.idle {
      opacity: 1;
      transform: scale(1.02);
    }
    .voice-art.active {
      transform: scale(1.04);
    }
    .orb[data-state="ready"] .voice-art.idle {
      filter: drop-shadow(0 0 14px rgba(0, 255, 149, 0.28));
    }
    .orb[data-state="listening"] .voice-art.idle,
    .orb[data-state="speaking"] .voice-art.idle {
      opacity: 0;
    }
    .orb[data-state="listening"] .voice-art.active,
    .orb[data-state="speaking"] .voice-art.active {
      opacity: 1;
    }
    .orb[data-state="listening"] .voice-art.active {
      animation: markListen 1.18s ease-in-out infinite;
      filter: drop-shadow(0 0 16px rgba(0, 255, 149, 0.38));
    }
    .orb[data-state="speaking"] .voice-art.active {
      animation: markSpeak 1.55s linear infinite;
      filter: drop-shadow(0 0 18px rgba(255, 31, 222, 0.38));
    }
    .orb[data-state="error"] .voice-art.idle {
      opacity: 1;
      filter: grayscale(0.4) hue-rotate(120deg) drop-shadow(0 0 15px rgba(255, 107, 107, 0.34));
    }
    .orb[data-state="error"] .voice-art.active {
      opacity: 0;
      filter: drop-shadow(0 0 15px rgba(255, 107, 107, 0.34));
    }
    .orb-label {
      position: relative;
      font-family: "JetBrains Mono", monospace;
      text-transform: uppercase;
      font-weight: 700;
      color: var(--text);
      text-shadow: 0 1px 10px rgba(0,0,0,0.72);
      padding: 7px 10px;
      border: 1px solid rgba(0, 243, 255, 0.16);
      border-radius: 999px;
      background: rgba(8, 10, 13, 0.74);
      min-width: 104px;
    }
    @keyframes markListen {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.035); }
    }
    @keyframes markSpeak {
      from { transform: rotate(0deg) scale(1.04); }
      to { transform: rotate(360deg) scale(1.04); }
    }
    .controls { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }
    .controls .wide { grid-column: span 2; }
    .field { display: grid; gap: 7px; margin-bottom: 12px; }
    .field label {
      color: var(--muted);
      font-size: 0.78rem;
      text-transform: uppercase;
      font-weight: 800;
    }
    input, select, textarea {
      width: 100%;
      color: var(--text);
      background: #111418;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 10px 11px;
    }
    textarea { min-height: 84px; resize: vertical; }
    .textbar { display: grid; grid-template-columns: 1fr auto; gap: 10px; }
    .events {
      height: 390px;
      overflow: auto;
      background: #0d0f12;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 10px;
      font-family: "JetBrains Mono", monospace;
      font-size: 0.78rem;
      line-height: 1.45;
    }
    .event { padding: 7px 0; border-bottom: 1px solid rgba(255,255,255,0.06); }
    .event strong { color: #f6d18b; }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
      color: var(--muted);
      font-size: 0.82rem;
    }
    .pill { border: 1px solid var(--line); border-radius: 999px; padding: 5px 8px; background: rgba(255,255,255,0.03); }
    @media (max-width: 820px) {
      .topbar { align-items: flex-start; flex-direction: column; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <h1>Deepgram Voice Agent</h1>
        <p>Local key-safe voice GUI for live Deepgram STT, DeepSeek thinking, and neural TTS.</p>
      </div>
      <div class="status"><span id="statusDot" class="dot"></span><span id="statusText">offline</span></div>
    </header>

    <main class="grid">
      <section>
        <div class="panel stage">
          <div>
            <div id="orb" class="orb" data-state="offline">
              <img class="voice-art idle" src="/assets/dg-voice-two-loops-colored.png" alt="" aria-hidden="true" />
              <img class="voice-art active" src="/assets/talking-colors.png" alt="" aria-hidden="true" />
              <div id="orbText" class="orb-label">offline</div>
            </div>
            <div class="controls">
              <button id="connectBtn" class="primary" type="button">Start</button>
              <button id="muteBtn" class="warn" type="button" disabled>Mute</button>
              <button id="stopBtn" class="danger wide" type="button" disabled>Stop</button>
            </div>
            <div class="meta">
              <span class="pill" id="keyState">keys: checking</span>
              <span class="pill">Deepgram Voice Agent API</span>
              <span class="pill" id="thinkState">Think: DeepSeek</span>
              <span class="pill">NVIDIA PersonaPlex tracked</span>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="field">
          <label for="thinkUrl">Think endpoint</label>
          <input id="thinkUrl" autocomplete="off" disabled />
        </div>
        <div class="field">
          <label for="thinkModel">Think model</label>
          <input id="thinkModel" autocomplete="off" disabled />
        </div>
        <div class="field">
          <label for="prompt">Voice prompt</label>
          <textarea id="prompt"></textarea>
        </div>
        <div class="field">
          <label for="listenModel">Listen model</label>
          <select id="listenModel">
            <option value="nova-2">nova-2</option>
            <option value="nova-3">nova-3</option>
            <option value="flux-general-en">flux-general-en</option>
          </select>
        </div>
        <div class="field">
          <label for="speakModel">Speak voice</label>
          <select id="speakModel">
            <option value="aura-2-asteria-en">aura-2-asteria-en</option>
            <option value="aura-2-thalia-en">aura-2-thalia-en</option>
            <option value="aura-2-arcas-en">aura-2-arcas-en</option>
            <option value="aura-2-orpheus-en">aura-2-orpheus-en</option>
            <option value="aura-2-helena-en">aura-2-helena-en</option>
          </select>
        </div>
        <div class="field">
          <label for="textTurn">Text turn</label>
          <div class="textbar">
            <input id="textTurn" placeholder="Send a typed turn to the same agent" autocomplete="off" />
            <button id="sendTextBtn" type="button" disabled>Send</button>
          </div>
        </div>
        <div id="events" class="events" aria-live="polite"></div>
        <div class="meta">
          <span><a id="deepgramLink" href="#" target="_blank" rel="noreferrer">Deepgram docs</a></span>
          <span><a id="personaplexLink" href="#" target="_blank" rel="noreferrer">NVIDIA PersonaPlex</a></span>
        </div>
      </section>
    </main>
  </div>

  <script>
    const state = {
      ws: null,
      playCtx: null,
      captureCtx: null,
      micStream: null,
      scriptNode: null,
      nextPlayTime: 0,
      muted: false,
      config: null,
    };

    const $ = (id) => document.getElementById(id);
    const statusDot = $("statusDot");
    const statusText = $("statusText");
    const orb = $("orb");
    const orbText = $("orbText");
    const connectBtn = $("connectBtn");
    const stopBtn = $("stopBtn");
    const muteBtn = $("muteBtn");
    const sendTextBtn = $("sendTextBtn");
    const events = $("events");

    function setStatus(kind, text) {
      statusText.textContent = text;
      statusDot.className = "dot" + (kind === "ready" ? " ready" : kind === "busy" ? " busy" : "");
      orb.dataset.state = kind === "ready" ? "ready" : kind === "busy" ? "speaking" : kind;
      orbText.textContent = text;
    }

    function logEvent(type, payload) {
      const row = document.createElement("div");
      row.className = "event";
      const safeType = escapeHtml(type || "event");
      const text = typeof payload === "string" ? payload : JSON.stringify(payload);
      row.innerHTML = `<strong>${safeType}</strong> ${escapeHtml(text || "")}`;
      events.prepend(row);
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
      }[ch]));
    }

    function buildSettings() {
      return {
        type: "Settings",
        audio: {
          input: { encoding: "linear16", sample_rate: 16000 },
          output: { encoding: "linear16", sample_rate: 24000, container: "none" },
        },
        agent: {
          language: "en",
          listen: {
            provider: { type: "deepgram", model: $("listenModel").value, endpointing: 800 },
          },
          think: {
            provider: { type: "open_ai", model: $("thinkModel").value },
            endpoint: { url: $("thinkUrl").value, headers: {} },
            prompt: $("prompt").value,
          },
          speak: {
            provider: { type: "deepgram", model: $("speakModel").value },
          },
        },
      };
    }

    function downsample(float32, fromRate, toRate) {
      if (fromRate === toRate) return float32;
      const ratio = fromRate / toRate;
      const out = new Float32Array(Math.floor(float32.length / ratio));
      for (let i = 0; i < out.length; i++) out[i] = float32[Math.floor(i * ratio)];
      return out;
    }

    function float32ToInt16(float32) {
      const int16 = new Int16Array(float32.length);
      for (let i = 0; i < float32.length; i++) {
        const sample = Math.max(-1, Math.min(1, float32[i]));
        int16[i] = sample < 0 ? sample * 32768 : sample * 32767;
      }
      return int16;
    }

    async function startMic() {
      state.micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      state.captureCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      await state.captureCtx.resume();
      const source = state.captureCtx.createMediaStreamSource(state.micStream);
      const gain = state.captureCtx.createGain();
      gain.gain.value = 0;
      state.scriptNode = state.captureCtx.createScriptProcessor(4096, 1, 1);
      const actualRate = state.captureCtx.sampleRate;
      state.scriptNode.onaudioprocess = (event) => {
        if (state.muted || !state.ws || state.ws.readyState !== WebSocket.OPEN) return;
        const samples = downsample(event.inputBuffer.getChannelData(0), actualRate, 16000);
        state.ws.send(float32ToInt16(samples).buffer);
      };
      source.connect(state.scriptNode);
      state.scriptNode.connect(gain);
      gain.connect(state.captureCtx.destination);
    }

    function scheduleAudio(arrayBuffer) {
      if (!state.playCtx) return;
      const pcm = new Int16Array(arrayBuffer);
      const buffer = state.playCtx.createBuffer(1, pcm.length, 24000);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768;
      const source = state.playCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(state.playCtx.destination);
      const startAt = Math.max(state.playCtx.currentTime, state.nextPlayTime);
      source.start(startAt);
      state.nextPlayTime = startAt + buffer.duration;
    }

    function handleAgentEvent(message) {
      const type = message.type || "event";
      if (type.includes("UserStartedSpeaking")) setStatus("listening", "listening");
      else if (type.includes("UserStoppedSpeaking")) setStatus("busy", "thinking");
      else if (type.includes("AgentStartedSpeaking")) setStatus("busy", "speaking");
      else if (type.includes("AgentAudioDone")) setStatus("ready", "connected");
      else if (type.includes("Error") || type === "VoiceUpstreamError") setStatus("error", "error");

      if (type === "ConversationText" || type.includes("ConversationText")) {
        logEvent(message.role || "text", message.content || message.text || message);
      } else if (!type.includes("Audio")) {
        logEvent(type, message);
      }
    }

    async function connect() {
      connectBtn.disabled = true;
      state.muted = false;
      muteBtn.textContent = "Mute";
      setStatus("busy", "connecting");
      state.playCtx = new (window.AudioContext || window.webkitAudioContext)();
      await state.playCtx.resume();

      const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
      state.ws = new WebSocket(`${wsProtocol}//${location.host}/ws/voice`);
      state.ws.binaryType = "arraybuffer";

      state.ws.onopen = async () => {
        state.ws.send(JSON.stringify(buildSettings()));
        await startMic();
        stopBtn.disabled = false;
        muteBtn.disabled = false;
        sendTextBtn.disabled = false;
        setStatus("ready", "connected");
        logEvent("local", "microphone streaming");
      };
      state.ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          scheduleAudio(event.data);
          return;
        }
        try { handleAgentEvent(JSON.parse(event.data)); }
        catch { logEvent("raw", event.data); }
      };
      state.ws.onerror = () => setStatus("error", "ws error");
      state.ws.onclose = () => teardown("offline");
    }

    function teardown(label = "offline") {
      if (state.scriptNode) state.scriptNode.disconnect();
      if (state.captureCtx) state.captureCtx.close().catch(() => {});
      if (state.playCtx) state.playCtx.close().catch(() => {});
      if (state.micStream) state.micStream.getTracks().forEach((track) => track.stop());
      if (state.ws) {
        state.ws.onclose = null;
        try { state.ws.close(); } catch {}
      }
      state.ws = null;
      state.playCtx = null;
      state.captureCtx = null;
      state.micStream = null;
      state.scriptNode = null;
      state.nextPlayTime = 0;
      state.muted = false;
      connectBtn.disabled = false;
      stopBtn.disabled = true;
      muteBtn.disabled = true;
      muteBtn.textContent = "Mute";
      sendTextBtn.disabled = true;
      setStatus(label === "error" ? "error" : "offline", label);
    }

    function sendTextTurn() {
      const input = $("textTurn");
      const message = input.value.trim();
      if (!message || !state.ws || state.ws.readyState !== WebSocket.OPEN) return;
      state.ws.send(JSON.stringify({ type: "AgentV1InjectUserMessage", payload: { message } }));
      logEvent("typed", message);
      input.value = "";
    }

    connectBtn.addEventListener("click", () => connect().catch((err) => {
      logEvent("local error", err.message || String(err));
      teardown("error");
    }));
    stopBtn.addEventListener("click", () => teardown("offline"));
    muteBtn.addEventListener("click", () => {
      state.muted = !state.muted;
      muteBtn.textContent = state.muted ? "Unmute" : "Mute";
      setStatus(state.muted ? "busy" : "ready", state.muted ? "muted" : "connected");
    });
    sendTextBtn.addEventListener("click", sendTextTurn);
    $("textTurn").addEventListener("keydown", (event) => {
      if (event.key === "Enter") sendTextTurn();
    });

    fetch("/api/config")
      .then((response) => response.json())
      .then((config) => {
        state.config = config;
        $("thinkUrl").value = config.thinkUrl;
        $("thinkModel").value = config.thinkModel;
        $("thinkState").textContent = `Think: ${config.thinkModel}`;
        $("listenModel").value = config.listenModel;
        $("speakModel").value = config.speakModel;
        $("prompt").value = config.prompt;
        $("deepgramLink").href = config.sources.deepgram;
        $("personaplexLink").href = config.sources.personaplex;
      });

    fetch("/api/health")
      .then((response) => response.json())
      .then((health) => {
        const ready = health.deepgramKeyConfigured && health.deepseekKeyConfigured;
        $("keyState").textContent = ready ? "keys: configured" : "keys: missing";
        if (!ready) setStatus("error", "missing key");
      })
      .catch(() => setStatus("error", "health error"));
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
