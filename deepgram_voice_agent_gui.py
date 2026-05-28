#!/usr/bin/env python3
"""Local Deepgram Voice Agent GUI and key-safe WebSocket proxy.

The browser captures microphone PCM and renders returned TTS audio, while this
server holds the Deepgram API key and relays frames to the Voice Agent API.
"""

from __future__ import annotations

import asyncio
import audioop
import io
import json
import logging
import os
import re
import subprocess
import threading
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nats
import requests
import uvicorn
import websockets
from fastapi import Request, FastAPI, WebSocket
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
DEFAULT_DB_SECRET_FILE = Path("/adapt/secrets/db.env")
DEFAULT_VOICE_HOME = Path("/adapt/novas/active/voice")
ROSTER_PATH = Path("/adapt/platform/novaops/controlplane/pipecat-voice/roster.json")
NOVA_SUBJECT_NS = "nova"
NATS_SENDER = "voice-agent-gui"
DICTATION_SAMPLE_RATE = 16_000
DICTATION_CHANNELS = 1
DICTATION_SAMPLE_WIDTH_BYTES = 2
DICTATION_THRESHOLD = 280
DICTATION_SILENCE_MS = 650
DICTATION_MIN_SPEECH_MS = 300
DICTATION_MAX_SEGMENT_MS = 4_000
TYPE_LOCK = threading.Lock()

LOGGER = logging.getLogger("deepgram_voice_agent_gui")
ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)\s*$")
SECRET_LINE_RE = re.compile(
    r"(?im)^([^=\n]*(?:api[_-]?key|token|secret|password|passwd|auth)[^=\n]*)=([^\n]*)$"
)
AUTH_VALUE_RE = re.compile(
    r"(?i)\b(bearer|token|basic)\s+[A-Za-z0-9._~+/=-]{12,}"
)
MAX_TOOL_OUTPUT_CHARS = 12000
MAX_TOOL_FILE_BYTES = 262144
MAX_TOOL_WRITE_BYTES = 1048576
VOICE_MEMORY_FILE = "voice_memory.jsonl"
VOICE_MEMORY_LOCK = asyncio.Lock()
VOICE_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "adapt_tool_policy",
        "description": (
            "Inspect the active Adapt voice tool policy, runtime home, sandbox state, "
            "sudo allowance, and available tool names."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "adapt_shell",
        "description": (
            "Run a shell command on the Adapt host. Use for system inspection, service "
            "control, git, NATS CLI work, build/test commands, and local automation. "
            "Default working directory is the voice agent home."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run."},
                "cwd": {
                    "type": "string",
                    "description": (
                        "Optional working directory. Relative paths resolve from voice home."
                    ),
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds. Defaults to 60, capped at 300.",
                },
                "sudo": {
                    "type": "boolean",
                    "description": "Run through sudo -n when true and sudo is enabled.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "adapt_read_file",
        "description": (
            "Read a local text file. Relative paths resolve from the voice agent home. "
            "Sensitive-looking values are redacted from the returned content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read."},
                "max_bytes": {
                    "type": "number",
                    "description": "Maximum bytes to read. Defaults to 65536, capped at 262144.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "adapt_write_file",
        "description": (
            "Write or append a local text file. Relative paths resolve from the voice "
            "agent home. Do not use for secrets; shared secrets belong in /adapt/secrets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write."},
                "content": {"type": "string", "description": "Text content to write."},
                "append": {"type": "boolean", "description": "Append when true."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "adapt_nats_ping",
        "description": "Ping one or more Adapt nova agents over NATS and return online status.",
        "parameters": {
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Nova agent names to ping, such as vox, iris, or vaeris.",
                },
                "timeout": {"type": "number", "description": "Timeout seconds per ping."},
            },
            "required": ["agents"],
        },
    },
    {
        "name": "adapt_nats_direct",
        "description": "Send a direct NATS message to one Adapt nova and return the reply.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Nova agent name."},
                "message": {"type": "string", "description": "Message to send."},
                "timeout": {"type": "number", "description": "Reply timeout seconds."},
            },
            "required": ["agent", "message"],
        },
    },
    {
        "name": "adapt_nats_group",
        "description": "Send the same NATS room message to multiple Adapt novas.",
        "parameters": {
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Nova agent names to message.",
                },
                "message": {"type": "string", "description": "Message to send."},
                "timeout": {"type": "number", "description": "Reply timeout seconds."},
            },
            "required": ["agents", "message"],
        },
    },
    {
        "name": "voice_remember",
        "description": (
            "Store a durable local voice memory in the voice agent runtime home. "
            "Use for operator preferences, current project context, recurring facts, "
            "and short-term session continuity."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Memory text to store."},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for recall.",
                },
                "source": {"type": "string", "description": "Optional source label."},
                "importance": {
                    "type": "number",
                    "description": "Optional importance from 0 to 1. Defaults to 0.5.",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "voice_recall",
        "description": "Search local voice memories by query and/or tags.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional search query."},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags to filter by.",
                },
                "limit": {"type": "number", "description": "Maximum memories to return."},
            },
        },
    },
    {
        "name": "voice_forget",
        "description": "Remove local voice memories by id.",
        "parameters": {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Memory ids to remove.",
                }
            },
            "required": ["ids"],
        },
    },
    {
        "name": "hermes_remember",
        "description": (
            "Send a durable memory note to the Hermes/Mnemos nova over NATS and "
            "also keep a local voice copy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Memory text to persist."},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for recall.",
                },
                "agent": {
                    "type": "string",
                    "description": "Hermes memory nova target. Defaults to mnemos.",
                },
                "timeout": {"type": "number", "description": "NATS reply timeout seconds."},
            },
            "required": ["content"],
        },
    },
    {
        "name": "hermes_recall",
        "description": "Ask the Hermes/Mnemos nova to recall durable fleet memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Recall query."},
                "agent": {
                    "type": "string",
                    "description": "Hermes memory nova target. Defaults to mnemos.",
                },
                "timeout": {"type": "number", "description": "NATS reply timeout seconds."},
            },
            "required": ["query"],
        },
    },
]


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


def nats_url() -> str:
    """Resolve the NATS URL without exposing it to the browser."""

    value = os.environ.get("NATS_URL", "").strip()
    if value:
        return value
    return load_secret_from_file(DEFAULT_DB_SECRET_FILE, ("NATS_URL",))


def _enabled_env(name: str, default: str = "0") -> bool:
    """Return true for explicit operator-enabled env flags."""

    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on", "yolo"}


def voice_home() -> Path:
    """Return the operator-approved voice agent workspace."""

    return Path(os.environ.get("VOICE_AGENT_HOME", str(DEFAULT_VOICE_HOME))).expanduser()


def tool_policy() -> dict[str, Any]:
    """Return the active server-side tool execution policy without secrets."""

    return {
        "home": str(voice_home()),
        "sandbox": os.environ.get("VOICE_AGENT_SANDBOX", "none"),
        "yolo": _enabled_env("VOICE_AGENT_YOLO", "1"),
        "allowSudo": _enabled_env("VOICE_AGENT_ALLOW_SUDO", "1"),
        "approvalPolicy": os.environ.get("VOICE_AGENT_APPROVAL_POLICY", "never"),
        "toolScope": os.environ.get("VOICE_AGENT_TOOL_SCOPE", "all"),
    }


def tool_prompt() -> str:
    """Return operator instructions that make Deepgram function use reliable."""

    names = ", ".join(definition["name"] for definition in VOICE_TOOL_DEFINITIONS)
    return (
        "\n\nAdapt tool mode is enabled. Use these functions directly when the "
        f"operator asks for system, file, NATS, service, git, or agent work: {names}. "
        "Do not invent command output. After a tool call, summarize the result briefly."
    )


def redact_sensitive(value: str) -> str:
    """Redact common secret shapes from tool output before returning it to the agent."""

    redacted = SECRET_LINE_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return AUTH_VALUE_RE.sub(lambda match: f"{match.group(1)} [REDACTED]", redacted)


def trim_tool_output(value: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    """Bound tool output so function responses stay small enough for the voice agent."""

    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    return f"{value[:limit]}\n...[truncated {omitted} chars]"


def resolve_tool_path(path: str) -> Path:
    """Resolve a tool path, using voice home for relative paths."""

    raw_path = Path(path).expanduser()
    if raw_path.is_absolute():
        return raw_path
    return voice_home() / raw_path


def tool_timeout(value: Any, default: float, maximum: float) -> float:
    """Clamp a caller-provided timeout to a bounded operational range."""

    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = default
    return min(max(timeout, 0.5), maximum)


def parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    """Parse Deepgram function arguments into a dictionary."""

    if isinstance(raw_arguments, dict):
        return raw_arguments
    if raw_arguments in (None, ""):
        return {}
    if isinstance(raw_arguments, str):
        parsed = json.loads(raw_arguments)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("tool arguments must be a JSON object")


def voice_memory_path() -> Path:
    """Return the local JSONL memory path."""

    return voice_home() / "state" / VOICE_MEMORY_FILE


def normalize_tags(raw_tags: Any) -> list[str]:
    """Normalize memory tags to short lowercase labels."""

    if raw_tags is None:
        return []
    if isinstance(raw_tags, str):
        candidates = re.split(r"[, ]+", raw_tags)
    elif isinstance(raw_tags, list):
        candidates = [str(tag) for tag in raw_tags]
    else:
        raise ValueError("tags must be a list or comma-separated string")
    tags: list[str] = []
    for candidate in candidates:
        tag = re.sub(r"[^a-z0-9_.:-]+", "-", candidate.strip().lower()).strip("-")
        if tag and tag not in tags:
            tags.append(tag[:64])
    return tags[:16]


def bounded_importance(value: Any) -> float:
    """Clamp a memory importance score to the 0..1 range."""

    try:
        importance = float(value)
    except (TypeError, ValueError):
        importance = 0.5
    return min(max(importance, 0.0), 1.0)


def assert_memory_content_safe(content: str) -> None:
    """Prevent accidental storage of obvious secret material."""

    if SECRET_LINE_RE.search(content) or AUTH_VALUE_RE.search(content):
        raise ValueError("memory content appears to contain a secret, token, or password")


def load_voice_memories() -> list[dict[str, Any]]:
    """Load local voice memory entries from JSONL."""

    path = voice_memory_path()
    if not path.exists():
        return []
    memories: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            memory = json.loads(line)
        except json.JSONDecodeError:
            LOGGER.warning("Skipping corrupt voice memory line in %s", path)
            continue
        if isinstance(memory, dict) and memory.get("id") and memory.get("content"):
            memories.append(memory)
    return memories


def memory_score(memory: dict[str, Any], query: str, tags: list[str]) -> float:
    """Score a memory entry for simple local recall."""

    content = str(memory.get("content") or "").lower()
    memory_tags = {str(tag).lower() for tag in memory.get("tags") or []}
    score = float(memory.get("importance") or 0.0)
    if tags:
        matched_tags = sum(1 for tag in tags if tag in memory_tags)
        if matched_tags != len(tags):
            return -1.0
        score += matched_tags * 3.0
    if query:
        terms = [term for term in re.split(r"\W+", query.lower()) if len(term) > 1]
        if terms:
            matched_terms = sum(1 for term in terms if term in content)
            if matched_terms == 0:
                return -1.0
            score += matched_terms * 2.0
            if query.lower() in content:
                score += 5.0
    return score


async def store_voice_memory(
    content: str,
    tags: list[str],
    source: str,
    importance: float,
    scope: str = "voice",
) -> dict[str, Any]:
    """Persist one local voice memory entry."""

    content = content.strip()
    if not content:
        raise ValueError("content is required")
    assert_memory_content_safe(content)

    now = datetime.now(timezone.utc).isoformat()
    memory = {
        "id": f"vmem_{uuid.uuid4().hex[:16]}",
        "createdAt": now,
        "scope": scope,
        "source": source[:80] if source else "voice-agent",
        "importance": importance,
        "tags": tags,
        "content": content,
    }
    path = voice_memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with VOICE_MEMORY_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(memory, separators=(",", ":")) + "\n")
    return memory


async def tool_voice_remember(arguments: dict[str, Any]) -> dict[str, Any]:
    """Store local voice memory."""

    memory = await store_voice_memory(
        content=str(arguments.get("content") or ""),
        tags=normalize_tags(arguments.get("tags")),
        source=str(arguments.get("source") or "voice-agent"),
        importance=bounded_importance(arguments.get("importance")),
    )
    return {"ok": True, "tool": "voice_remember", "memory": memory}


async def tool_voice_recall(arguments: dict[str, Any]) -> dict[str, Any]:
    """Recall local voice memories."""

    query = str(arguments.get("query") or "").strip()
    tags = normalize_tags(arguments.get("tags"))
    limit = int(tool_timeout(arguments.get("limit"), default=8, maximum=32))
    async with VOICE_MEMORY_LOCK:
        memories = load_voice_memories()

    scored = [
        (memory_score(memory, query, tags), memory)
        for memory in memories
    ]
    matches = [
        memory
        for score, memory in sorted(scored, key=lambda item: item[0], reverse=True)
        if score >= 0
    ][:limit]
    return {
        "ok": True,
        "tool": "voice_recall",
        "query": query,
        "tags": tags,
        "count": len(matches),
        "memories": matches,
    }


async def tool_voice_forget(arguments: dict[str, Any]) -> dict[str, Any]:
    """Remove local voice memories by id."""

    raw_ids = arguments.get("ids") or []
    if isinstance(raw_ids, str):
        ids = {raw_ids.strip()}
    elif isinstance(raw_ids, list):
        ids = {str(item).strip() for item in raw_ids}
    else:
        raise ValueError("ids must be a list or string")
    ids.discard("")
    if not ids:
        raise ValueError("at least one id is required")

    path = voice_memory_path()
    async with VOICE_MEMORY_LOCK:
        memories = load_voice_memories()
        kept = [memory for memory in memories if str(memory.get("id")) not in ids]
        removed = len(memories) - len(kept)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".jsonl.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            for memory in kept:
                handle.write(json.dumps(memory, separators=(",", ":")) + "\n")
        temp_path.replace(path)
    return {"ok": True, "tool": "voice_forget", "removed": removed, "ids": sorted(ids)}


async def tool_hermes_remember(arguments: dict[str, Any]) -> dict[str, Any]:
    """Store local voice memory and forward it to Mnemos/Hermes over NATS."""

    content = str(arguments.get("content") or "").strip()
    tags = normalize_tags(arguments.get("tags"))
    memory = await store_voice_memory(
        content=content,
        tags=tags,
        source="hermes-remember",
        importance=bounded_importance(arguments.get("importance")),
        scope="hermes",
    )
    agent = _valid_agent_name(str(arguments.get("agent") or "mnemos"))
    message = (
        "MEMORY WRITE REQUEST from Deepgram voice agent.\n"
        f"Local memory id: {memory['id']}\n"
        f"Tags: {', '.join(tags) if tags else '(none)'}\n"
        "Persist this in durable Hermes/Mnemos fleet memory. No synchronous reply is required.\n\n"
        f"{content}"
    )
    result = await _nats_publish(agent, "direct", message)
    return {"ok": True, "tool": "hermes_remember", "memory": memory, "nats": result}


async def tool_hermes_recall(arguments: dict[str, Any]) -> dict[str, Any]:
    """Ask Mnemos/Hermes to recall durable fleet memory."""

    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    agent = _valid_agent_name(str(arguments.get("agent") or "mnemos"))
    timeout = tool_timeout(arguments.get("timeout"), default=45, maximum=120)
    message = (
        "MEMORY RECALL REQUEST from Deepgram voice agent.\n"
        "Search durable Hermes/Mnemos fleet memory and reply concisely with matches, "
        "sources, and uncertainty.\n\n"
        f"Query: {query}"
    )
    result = await _nats_roundtrip(agent, "direct", message, timeout)
    return {"ok": True, "tool": "hermes_recall", "query": query, "nats": result}


async def tool_adapt_shell(arguments: dict[str, Any]) -> dict[str, Any]:
    """Run a shell command under the active voice-agent execution policy."""

    command = str(arguments.get("command") or "").strip()
    if not command:
        raise ValueError("command is required")

    cwd = resolve_tool_path(str(arguments.get("cwd") or "."))
    if not cwd.exists() or not cwd.is_dir():
        raise ValueError(f"cwd does not exist or is not a directory: {cwd}")

    timeout = tool_timeout(arguments.get("timeout"), default=60, maximum=300)
    sudo_requested = bool(arguments.get("sudo"))
    allow_sudo = bool(tool_policy()["allowSudo"])
    if sudo_requested and not allow_sudo:
        raise PermissionError("sudo is disabled by VOICE_AGENT_ALLOW_SUDO")

    argv = (
        ["sudo", "-n", "/bin/bash", "-lc", command]
        if sudo_requested
        else ["/bin/bash", "-lc", command]
    )
    started_at = datetime.now(timezone.utc).isoformat()
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
        timed_out = False
    except asyncio.TimeoutError:
        process.kill()
        stdout_bytes, stderr_bytes = await process.communicate()
        timed_out = True

    stdout = redact_sensitive(stdout_bytes.decode("utf-8", errors="replace"))
    stderr = redact_sensitive(stderr_bytes.decode("utf-8", errors="replace"))
    return {
        "ok": process.returncode == 0 and not timed_out,
        "tool": "adapt_shell",
        "command": command,
        "cwd": str(cwd),
        "sudo": sudo_requested,
        "timedOut": timed_out,
        "returncode": process.returncode,
        "startedAt": started_at,
        "stdout": trim_tool_output(stdout),
        "stderr": trim_tool_output(stderr),
    }


async def tool_adapt_read_file(arguments: dict[str, Any]) -> dict[str, Any]:
    """Read a local file for the voice agent."""

    path = resolve_tool_path(str(arguments.get("path") or ""))
    if not str(arguments.get("path") or "").strip():
        raise ValueError("path is required")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))

    max_bytes = int(
        tool_timeout(arguments.get("max_bytes"), default=65536, maximum=MAX_TOOL_FILE_BYTES)
    )
    data = path.read_bytes()[:max_bytes]
    content = redact_sensitive(data.decode("utf-8", errors="replace"))
    truncated = path.stat().st_size > len(data)
    return {
        "ok": True,
        "tool": "adapt_read_file",
        "path": str(path),
        "bytesRead": len(data),
        "truncated": truncated,
        "content": trim_tool_output(content),
    }


async def tool_adapt_write_file(arguments: dict[str, Any]) -> dict[str, Any]:
    """Write or append a local text file for the voice agent."""

    raw_path = str(arguments.get("path") or "").strip()
    if not raw_path:
        raise ValueError("path is required")
    content = str(arguments.get("content") or "")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_TOOL_WRITE_BYTES:
        raise ValueError(f"content exceeds {MAX_TOOL_WRITE_BYTES} bytes")

    path = resolve_tool_path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if bool(arguments.get("append")) else "w"
    with path.open(mode, encoding="utf-8") as handle:
        handle.write(content)
    return {
        "ok": True,
        "tool": "adapt_write_file",
        "path": str(path),
        "bytesWritten": len(encoded),
        "append": bool(arguments.get("append")),
    }


async def tool_adapt_nats_ping(arguments: dict[str, Any]) -> dict[str, Any]:
    """Ping selected NATS agents for a voice function call."""

    raw_agents = arguments.get("agents") or []
    if not isinstance(raw_agents, list):
        raise ValueError("agents must be a list")
    agents = [_valid_agent_name(str(agent)) for agent in raw_agents[:16]]
    if not agents:
        raise ValueError("at least one agent is required")
    timeout = tool_timeout(arguments.get("timeout"), default=1.2, maximum=8)
    return {"ok": True, "tool": "adapt_nats_ping", "results": await _nats_ping(agents, timeout)}


async def tool_adapt_nats_direct(arguments: dict[str, Any]) -> dict[str, Any]:
    """Send a direct NATS message for a voice function call."""

    agent = _valid_agent_name(str(arguments.get("agent") or "iris"))
    message = str(arguments.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")
    timeout = tool_timeout(arguments.get("timeout"), default=45, maximum=120)
    return {
        "ok": True,
        "tool": "adapt_nats_direct",
        "result": await _nats_roundtrip(agent, "direct", message, timeout),
    }


async def tool_adapt_nats_group(arguments: dict[str, Any]) -> dict[str, Any]:
    """Send a NATS group message for a voice function call."""

    raw_agents = arguments.get("agents") or []
    if not isinstance(raw_agents, list):
        raise ValueError("agents must be a list")
    agents = [_valid_agent_name(str(agent)) for agent in raw_agents[:8]]
    message = str(arguments.get("message") or "").strip()
    if not agents:
        raise ValueError("at least one agent is required")
    if not message:
        raise ValueError("message is required")

    timeout = tool_timeout(arguments.get("timeout"), default=60, maximum=120)
    results = await asyncio.gather(
        *(_nats_roundtrip(agent, "meet", message, timeout) for agent in agents),
        return_exceptions=True,
    )
    payload: list[dict[str, Any]] = []
    for agent, result in zip(agents, results, strict=False):
        if isinstance(result, Exception):
            payload.append({"agent": agent, "error": str(result), "timedOut": True})
        else:
            payload.append(result)
    return {"ok": True, "tool": "adapt_nats_group", "results": payload}


async def execute_voice_tool(name: str, raw_arguments: Any) -> dict[str, Any]:
    """Execute a named voice tool and return a JSON-serializable result."""

    arguments = parse_tool_arguments(raw_arguments)
    tool_map = {
        "adapt_tool_policy": lambda _: {
            "ok": True,
            "tool": "adapt_tool_policy",
            "policy": tool_policy(),
            "tools": [definition["name"] for definition in VOICE_TOOL_DEFINITIONS],
        },
        "adapt_shell": tool_adapt_shell,
        "adapt_read_file": tool_adapt_read_file,
        "adapt_write_file": tool_adapt_write_file,
        "adapt_nats_ping": tool_adapt_nats_ping,
        "adapt_nats_direct": tool_adapt_nats_direct,
        "adapt_nats_group": tool_adapt_nats_group,
        "voice_remember": tool_voice_remember,
        "voice_recall": tool_voice_recall,
        "voice_forget": tool_voice_forget,
        "hermes_remember": tool_hermes_remember,
        "hermes_recall": tool_hermes_recall,
    }
    handler = tool_map.get(name)
    if handler is None:
        raise ValueError(f"unknown tool: {name}")

    result = handler(arguments)
    if asyncio.iscoroutine(result):
        return await result
    return result


def roster_agents() -> list[dict[str, Any]]:
    """Return the public fleet roster used by the voice control panel."""

    try:
        data = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Could not read nova roster %s: %s", ROSTER_PATH, exc)
        return []

    agents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_agent in data.get("agents", []):
        if not isinstance(raw_agent, dict):
            continue
        name = str(raw_agent.get("profile") or raw_agent.get("name") or "").strip().lower()
        if not name or name in seen or raw_agent.get("active") is False:
            continue
        seen.add(name)
        agents.append(
            {
                "name": name,
                "label": raw_agent.get("label") or raw_agent.get("name") or name.capitalize(),
                "tier": raw_agent.get("tier") or "",
                "domain": raw_agent.get("domain") or "",
                "voice": raw_agent.get("voice") or "",
                "description": raw_agent.get("description") or "",
            }
        )
    return agents


def _valid_agent_name(name: str) -> str:
    """Validate a NATS agent segment."""

    normalized = name.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,48}", normalized):
        raise ValueError(f"invalid agent name: {name}")
    return normalized


def _nats_message(message: str, reply_to: str | None = None) -> dict[str, Any]:
    """Build a nova-compatible NATS envelope."""

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "from": NATS_SENDER,
        "id": f"{NATS_SENDER}:{now}:{uuid.uuid4().hex[:10]}",
        "message": message,
        "timestamp": now,
    }
    if reply_to:
        payload["reply_to"] = reply_to
    return payload


async def _nats_publish(agent: str, channel: str, message: str) -> dict[str, Any]:
    """Publish a NATS message without waiting for a reply."""

    agent = _valid_agent_name(agent)
    if channel not in {"direct", "meet"}:
        raise ValueError("channel must be direct or meet")
    url = nats_url()
    if not url:
        raise RuntimeError("NATS_URL is not configured")

    nc = await nats.connect(url, name="deepgram-voice-agent-gui-publish")
    subject = f"{NOVA_SUBJECT_NS}.{agent}.{channel}"
    event = _nats_message(message)
    await nc.publish(subject, json.dumps(event).encode())
    await nc.flush()
    await nc.drain()
    return {
        "agent": agent,
        "channel": channel,
        "subject": subject,
        "published": True,
        "eventId": event["id"],
    }


async def _nats_roundtrip(agent: str, channel: str, message: str, timeout: float) -> dict[str, Any]:
    """Publish a NATS message to one agent and collect streamed reply chunks."""

    agent = _valid_agent_name(agent)
    if channel not in {"direct", "meet"}:
        raise ValueError("channel must be direct or meet")
    url = nats_url()
    if not url:
        raise RuntimeError("NATS_URL is not configured")

    nc = await nats.connect(url, name="deepgram-voice-agent-gui")
    reply_to = nc.new_inbox()
    done = asyncio.Event()
    chunks: list[str] = []
    raw_events: list[dict[str, Any]] = []

    async def on_reply(msg) -> None:
        try:
            payload = json.loads(msg.data.decode())
        except Exception:
            payload = {"chunk": msg.data.decode(errors="replace"), "final": True}
        raw_events.append(payload)
        if chunk := payload.get("chunk"):
            chunks.append(str(chunk))
        if payload.get("final") or payload.get("message"):
            if payload.get("message") and not chunks:
                chunks.append(str(payload["message"]))
            done.set()

    subscription = await nc.subscribe(reply_to, cb=on_reply)
    subject = f"{NOVA_SUBJECT_NS}.{agent}.{channel}"
    await nc.publish(subject, json.dumps(_nats_message(message, reply_to)).encode())
    await nc.flush()

    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        await subscription.unsubscribe()
        await nc.drain()

    text = "".join(chunks).strip()
    return {
        "agent": agent,
        "channel": channel,
        "subject": subject,
        "reply": text,
        "timedOut": not bool(text),
        "events": raw_events[-12:],
    }


async def _nats_ping(agents: list[str], timeout: float) -> list[dict[str, Any]]:
    """Ping selected novas over NATS."""

    url = nats_url()
    if not url:
        raise RuntimeError("NATS_URL is not configured")
    nc = await nats.connect(url, name="deepgram-voice-agent-gui-ping")

    async def ping_one(agent: str) -> dict[str, Any]:
        agent = _valid_agent_name(agent)
        subject = f"{NOVA_SUBJECT_NS}.{agent}.ping"
        try:
            msg = await nc.request(subject, b"ping", timeout=timeout)
            return {
                "agent": agent,
                "subject": subject,
                "online": True,
                "response": msg.data.decode(errors="replace"),
            }
        except Exception as exc:
            return {
                "agent": agent,
                "subject": subject,
                "online": False,
                "error": str(exc),
            }

    try:
        return await asyncio.gather(*(ping_one(agent) for agent in agents))
    finally:
        await nc.drain()


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
        "toolPolicy": tool_policy(),
        "tools": [definition["name"] for definition in VOICE_TOOL_DEFINITIONS],
    }


app = FastAPI(title=APP_NAME)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Serve the local GUI."""

    return HTML


@app.get("/dictation", response_class=HTMLResponse)
async def dictation_index() -> str:
    """Serve browser-microphone dictation into the active X11 window."""

    return DICTATION_HTML


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
            "toolPolicy": tool_policy(),
            "endpoint": VOICE_AGENT_URL,
            "thinkUrl": public_config()["thinkUrl"],
            "thinkModel": public_config()["thinkModel"],
        }
    )


@app.get("/api/nats/agents")
async def api_nats_agents() -> JSONResponse:
    """Return public NATS fleet routing data for the GUI."""

    return JSONResponse(
        {
            "ok": bool(nats_url()),
            "subjectNamespace": NOVA_SUBJECT_NS,
            "agents": roster_agents(),
        }
    )


@app.post("/api/nats/direct")
async def api_nats_direct(request: Request) -> JSONResponse:
    """Send a direct NATS message to one nova and collect its reply."""

    body = await request.json()
    agent = _valid_agent_name(str(body.get("agent") or "iris"))
    message = str(body.get("message") or "").strip()
    if not message:
        return JSONResponse({"ok": False, "error": "message is required"}, status_code=400)
    timeout = min(max(float(body.get("timeout") or 45), 5), 120)
    try:
        result = await _nats_roundtrip(agent, "direct", message, timeout)
    except Exception as exc:
        LOGGER.warning("NATS direct dispatch failed: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, "result": result})


@app.post("/api/nats/ping")
async def api_nats_ping(request: Request) -> JSONResponse:
    """Ping selected novas over NATS."""

    body = await request.json()
    requested_agents = body.get("agents") or []
    if not isinstance(requested_agents, list):
        return JSONResponse({"ok": False, "error": "agents must be a list"}, status_code=400)
    agents = [_valid_agent_name(str(agent)) for agent in requested_agents[:16]]
    if not agents:
        return JSONResponse({"ok": False, "error": "at least one agent is required"}, status_code=400)
    timeout = min(max(float(body.get("timeout") or 1.2), 0.3), 8)
    try:
        results = await _nats_ping(agents, timeout)
    except Exception as exc:
        LOGGER.warning("NATS ping failed: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, "results": results})


@app.post("/api/nats/group")
async def api_nats_group(request: Request) -> JSONResponse:
    """Send a room-style NATS message to multiple novas and collect replies."""

    body = await request.json()
    requested_agents = body.get("agents") or []
    if not isinstance(requested_agents, list):
        return JSONResponse({"ok": False, "error": "agents must be a list"}, status_code=400)
    agents = [_valid_agent_name(str(agent)) for agent in requested_agents[:8]]
    message = str(body.get("message") or "").strip()
    if not agents:
        return JSONResponse({"ok": False, "error": "at least one agent is required"}, status_code=400)
    if not message:
        return JSONResponse({"ok": False, "error": "message is required"}, status_code=400)
    timeout = min(max(float(body.get("timeout") or 60), 5), 120)
    try:
        results = await asyncio.gather(
            *(_nats_roundtrip(agent, "meet", message, timeout) for agent in agents),
            return_exceptions=True,
        )
    except Exception as exc:
        LOGGER.warning("NATS group dispatch failed: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    payload: list[dict[str, Any]] = []
    for agent, result in zip(agents, results, strict=False):
        if isinstance(result, Exception):
            payload.append({"agent": agent, "error": str(result), "timedOut": True})
        else:
            payload.append(result)
    return JSONResponse({"ok": True, "results": payload})


@app.post("/api/tools/execute")
async def api_tools_execute(request: Request) -> JSONResponse:
    """Execute a voice tool through the same server-side dispatcher used by Deepgram."""

    body = await request.json()
    name = str(body.get("name") or "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "name is required"}, status_code=400)
    try:
        result = await execute_voice_tool(name, body.get("arguments") or {})
    except Exception as exc:
        LOGGER.warning("Voice tool execution failed: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc), "tool": name}, status_code=400)
    return JSONResponse({"ok": True, "result": result})


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


@app.websocket("/ws/dictate")
async def ws_dictation(browser: WebSocket) -> None:
    """Transcribe browser PCM and type recognized text into the active X11 window."""

    await browser.accept()
    if not deepgram_key():
        await browser.send_json({"type": "error", "message": "Deepgram key is not configured"})
        await browser.close(code=1011, reason="missing deepgram key")
        return

    typing_enabled = True
    speech = bytearray()
    pre_roll: list[bytes] = []
    pre_roll_ms = 0.0
    silence_ms = 0.0
    speech_ms = 0.0
    total_ms = 0.0
    peak_rms = 0

    async def flush_segment() -> None:
        nonlocal speech, pre_roll, pre_roll_ms, silence_ms, speech_ms, total_ms, peak_rms
        pcm = bytes(speech)
        audio_ms = len(pcm) / (
            DICTATION_SAMPLE_RATE * DICTATION_CHANNELS * DICTATION_SAMPLE_WIDTH_BYTES
        ) * 1000
        segment_peak_rms = peak_rms
        speech = bytearray()
        pre_roll = []
        pre_roll_ms = 0.0
        silence_ms = 0.0
        speech_ms = 0.0
        total_ms = 0.0
        peak_rms = 0
        if not pcm:
            return
        transcript = await asyncio.to_thread(transcribe_dictation_pcm, pcm)
        await browser.send_json(
            {
                "type": "segment",
                "audioMs": round(audio_ms),
                "peakRms": segment_peak_rms,
                "text": transcript,
            }
        )
        if transcript and typing_enabled:
            await asyncio.to_thread(type_dictation_text, transcript)

    try:
        while True:
            frame = await browser.receive()
            if frame["type"] == "websocket.disconnect":
                return
            if frame.get("text") is not None:
                try:
                    payload = json.loads(frame["text"])
                except json.JSONDecodeError:
                    continue
                if payload.get("type") == "typing":
                    typing_enabled = bool(payload.get("enabled", True))
                    await browser.send_json({"type": "typing", "enabled": typing_enabled})
                continue

            chunk = frame.get("bytes")
            if not chunk:
                continue
            chunk_ms = len(chunk) / (
                DICTATION_SAMPLE_RATE * DICTATION_CHANNELS * DICTATION_SAMPLE_WIDTH_BYTES
            ) * 1000
            rms = audioop.rms(chunk, DICTATION_SAMPLE_WIDTH_BYTES)
            peak_rms = max(peak_rms, rms)
            has_voice = rms >= DICTATION_THRESHOLD

            if not speech:
                pre_roll.append(chunk)
                pre_roll_ms += chunk_ms
                while pre_roll_ms > 350 and pre_roll:
                    dropped = pre_roll.pop(0)
                    pre_roll_ms -= len(dropped) / (
                        DICTATION_SAMPLE_RATE
                        * DICTATION_CHANNELS
                        * DICTATION_SAMPLE_WIDTH_BYTES
                    ) * 1000
                if not has_voice:
                    continue
                speech.extend(b"".join(pre_roll))
                total_ms += pre_roll_ms
                pre_roll = []
                pre_roll_ms = 0.0

            speech.extend(chunk)
            total_ms += chunk_ms
            if has_voice:
                silence_ms = 0.0
                speech_ms += chunk_ms
            else:
                silence_ms += chunk_ms

            should_flush = (
                silence_ms >= DICTATION_SILENCE_MS and speech_ms >= DICTATION_MIN_SPEECH_MS
            ) or total_ms >= DICTATION_MAX_SEGMENT_MS
            if should_flush:
                await flush_segment()
    except Exception as exc:
        LOGGER.info("Dictation websocket closed: %s", exc)


def transcribe_dictation_pcm(pcm: bytes) -> str:
    """Transcribe signed 16-bit mono PCM with Deepgram prerecorded STT."""

    key = deepgram_key()
    if not key or not pcm:
        return ""
    response = requests.post(
        "https://api.deepgram.com/v1/listen",
        params={
            "model": "nova-3",
            "language": "en-US",
            "smart_format": "true",
            "punctuate": "true",
            "dictation": "true",
        },
        headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"},
        data=pcm_to_wav_bytes(pcm),
        timeout=(3.05, 8),
    )
    response.raise_for_status()
    payload = response.json()
    alternatives = payload["results"]["channels"][0]["alternatives"]
    return str(alternatives[0].get("transcript", "")).strip()


def pcm_to_wav_bytes(pcm: bytes) -> bytes:
    """Wrap raw signed 16-bit mono PCM in a WAV container."""

    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(DICTATION_CHANNELS)
        wav_file.setsampwidth(DICTATION_SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(DICTATION_SAMPLE_RATE)
        wav_file.writeframes(pcm)
    return output.getvalue()


def type_dictation_text(text: str) -> None:
    """Type recognized text into the active X11 window."""

    env = {
        **os.environ,
        "DISPLAY": os.environ.get("DISPLAY", ":0"),
        "XAUTHORITY": os.environ.get("XAUTHORITY", "/home/x/.Xauthority"),
    }
    with TYPE_LOCK:
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", "2", f"{text} "],
            check=False,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


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
    previous_think = agent.get("think") if isinstance(agent.get("think"), dict) else {}
    previous_prompt = str(previous_think.get("prompt") or public_config()["prompt"])
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
        "prompt": f"{previous_prompt}{tool_prompt()}",
        "functions": VOICE_TOOL_DEFINITIONS,
    }
    return json.dumps(payload, separators=(",", ":"))


async def handle_function_call_request(
    payload: dict[str, Any], upstream: Any, browser: WebSocket
) -> None:
    """Execute Deepgram client-side function requests and return responses upstream."""

    functions = payload.get("functions") or []
    if not isinstance(functions, list):
        return
    for function_call in functions:
        if not isinstance(function_call, dict):
            continue
        if function_call.get("client_side") is False:
            continue

        call_id = str(function_call.get("id") or "")
        name = str(function_call.get("name") or "")
        try:
            result = await execute_voice_tool(name, function_call.get("arguments"))
        except Exception as exc:
            LOGGER.warning("Voice function call failed: %s", exc)
            result = {"ok": False, "tool": name, "error": str(exc)}

        response = {
            "type": "FunctionCallResponse",
            "id": call_id,
            "name": name,
            "content": json.dumps(result, separators=(",", ":")),
        }
        if function_call.get("thought_signature"):
            response["thought_signature"] = function_call["thought_signature"]

        await upstream.send(json.dumps(response, separators=(",", ":")))
        try:
            await browser.send_json(
                {"type": "VoiceToolResult", "id": call_id, "name": name, "result": result}
            )
        except Exception:
            LOGGER.debug("Browser closed before VoiceToolResult could be sent")


async def _deepgram_to_browser(upstream: Any, browser: WebSocket) -> None:
    """Forward Deepgram JSON events and binary audio to the browser."""

    async for message in upstream:
        if isinstance(message, bytes):
            await browser.send_bytes(message)
        else:
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                payload = None
            await browser.send_text(message)
            if isinstance(payload, dict) and payload.get("type") == "FunctionCallRequest":
                await handle_function_call_request(payload, upstream, browser)


def main() -> None:
    """Run the local GUI server."""

    logging.basicConfig(level=os.environ.get("VOICE_AGENT_LOG_LEVEL", "INFO"))
    host = os.environ.get("VOICE_AGENT_HOST", DEFAULT_HOST)
    port = int(os.environ.get("VOICE_AGENT_PORT", str(DEFAULT_PORT)))
    uvicorn.run(app, host=host, port=port, log_level="info")


DICTATION_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Adapt Dictation</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, system-ui, sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #0d1117; color: #f0f6fc; }
    main { width: min(720px, calc(100vw - 32px)); display: grid; gap: 16px; }
    h1 { margin: 0; font-size: 28px; font-weight: 700; }
    p { margin: 0; color: #8b949e; line-height: 1.45; }
    .controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
    button { border: 1px solid #30363d; background: #161b22; color: #f0f6fc; border-radius: 8px; padding: 10px 14px; font: inherit; cursor: pointer; }
    button.primary { background: #238636; border-color: #2ea043; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .status { border: 1px solid #30363d; border-radius: 8px; padding: 12px; background: #010409; min-height: 24px; }
    .log { height: 280px; overflow: auto; border: 1px solid #30363d; border-radius: 8px; background: #010409; padding: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
    .row { padding: 6px 0; border-bottom: 1px solid #161b22; }
    .empty { color: #6e7681; }
  </style>
</head>
<body>
  <main>
    <div>
      <h1>Adapt Dictation</h1>
      <p>Browser microphone to Deepgram, then typed into the active desktop text field.</p>
    </div>
    <div class="controls">
      <button id="start" class="primary">Start</button>
      <button id="stop" disabled>Stop</button>
      <button id="typing" disabled>Typing On</button>
    </div>
    <div id="status" class="status">offline</div>
    <div id="log" class="log"></div>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const state = { ws: null, stream: null, ctx: null, node: null, typing: true };

    function log(text, cls = "") {
      const row = document.createElement("div");
      row.className = `row ${cls}`;
      row.textContent = text;
      $("log").prepend(row);
    }

    function setStatus(text) { $("status").textContent = text; }

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

    async function start() {
      $("start").disabled = true;
      setStatus("requesting microphone");
      state.stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      state.ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      await state.ctx.resume();
      const source = state.ctx.createMediaStreamSource(state.stream);
      const gain = state.ctx.createGain();
      gain.gain.value = 0;
      state.node = state.ctx.createScriptProcessor(4096, 1, 1);
      const actualRate = state.ctx.sampleRate;
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      state.ws = new WebSocket(`${proto}//${location.host}/ws/dictate`);
      state.ws.binaryType = "arraybuffer";
      state.ws.onopen = () => {
        setStatus("listening");
        $("stop").disabled = false;
        $("typing").disabled = false;
        state.ws.send(JSON.stringify({ type: "typing", enabled: state.typing }));
      };
      state.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "segment") {
          const text = msg.text || "";
          log(text || `blank segment peak=${msg.peakRms} audio=${msg.audioMs}ms`, text ? "" : "empty");
        } else if (msg.type === "error") {
          log(msg.message || "error");
        }
      };
      state.ws.onclose = () => stop("offline");
      state.node.onaudioprocess = (event) => {
        if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
        const samples = downsample(event.inputBuffer.getChannelData(0), actualRate, 16000);
        state.ws.send(float32ToInt16(samples).buffer);
      };
      source.connect(state.node);
      state.node.connect(gain);
      gain.connect(state.ctx.destination);
    }

    function stop(label = "stopped") {
      if (state.node) state.node.disconnect();
      if (state.ctx) state.ctx.close().catch(() => {});
      if (state.stream) state.stream.getTracks().forEach((track) => track.stop());
      if (state.ws) {
        state.ws.onclose = null;
        try { state.ws.close(); } catch {}
      }
      state.ws = null;
      state.stream = null;
      state.ctx = null;
      state.node = null;
      $("start").disabled = false;
      $("stop").disabled = true;
      $("typing").disabled = true;
      setStatus(label);
    }

    $("start").addEventListener("click", () => start().catch((err) => {
      log(err.message || String(err));
      stop("error");
    }));
    $("stop").addEventListener("click", () => stop());
    $("typing").addEventListener("click", () => {
      state.typing = !state.typing;
      $("typing").textContent = state.typing ? "Typing On" : "Typing Muted";
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ type: "typing", enabled: state.typing }));
      }
    });
  </script>
</body>
</html>
"""


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
    .fleetbar { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .agent-list {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 8px;
      max-height: 140px;
      overflow: auto;
      padding: 8px;
      background: #0d0f12;
      border: 1px solid var(--line);
      border-radius: var(--radius);
    }
    .agent-option {
      display: flex;
      align-items: center;
      gap: 7px;
      color: var(--muted);
      font-size: 0.82rem;
    }
    .agent-option input { width: auto; }
    .nats-output {
      min-height: 92px;
      max-height: 180px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      background: #0d0f12;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 10px;
      font-family: "JetBrains Mono", monospace;
      font-size: 0.76rem;
      line-height: 1.42;
    }
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
              <span class="pill" id="toolState">Tools: checking</span>
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
        <div class="field">
          <label for="natsMessage">Nova fleet</label>
          <div id="agentList" class="agent-list"></div>
        </div>
        <div class="field">
          <textarea id="natsMessage" placeholder="Ask selected novas or send a direct note to one agent"></textarea>
          <div class="fleetbar">
            <button id="sendDirectBtn" type="button">Direct</button>
            <button id="sendGroupBtn" type="button">Group</button>
          </div>
          <button id="pingAgentsBtn" type="button">Ping selected</button>
        </div>
        <pre id="natsOutput" class="nats-output"></pre>
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
      agents: [],
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
    const sendDirectBtn = $("sendDirectBtn");
    const sendGroupBtn = $("sendGroupBtn");
    const pingAgentsBtn = $("pingAgentsBtn");
    const agentList = $("agentList");
    const natsOutput = $("natsOutput");
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

    function selectedAgents() {
      return [...agentList.querySelectorAll("input:checked")].map((input) => input.value);
    }

    function setNatsOutput(value) {
      natsOutput.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    }

    async function postJson(path, body) {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) throw payload;
      return payload;
    }

    function renderAgents(agents) {
      agentList.innerHTML = "";
      const defaults = new Set(["iris", "vox", "vaeris"]);
      for (const agent of agents) {
        const label = document.createElement("label");
        label.className = "agent-option";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = agent.name;
        input.checked = defaults.has(agent.name);
        label.append(input, document.createTextNode(agent.label || agent.name));
        agentList.append(label);
      }
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

    async function sendDirectNats() {
      const agents = selectedAgents();
      const message = $("natsMessage").value.trim();
      if (!message) return setNatsOutput("Enter a fleet message first.");
      if (!agents.length) return setNatsOutput("Select one nova first.");
      sendDirectBtn.disabled = true;
      sendGroupBtn.disabled = true;
      pingAgentsBtn.disabled = true;
      setNatsOutput(`Sending direct to ${agents[0]}...`);
      try {
        const payload = await postJson("/api/nats/direct", { agent: agents[0], message });
        setNatsOutput(payload.result);
        logEvent("nats direct", `${agents[0]}: ${payload.result.reply || "(no reply)"}`);
      } catch (error) {
        setNatsOutput(error);
      } finally {
        sendDirectBtn.disabled = false;
        sendGroupBtn.disabled = false;
        pingAgentsBtn.disabled = false;
      }
    }

    async function pingSelectedAgents() {
      const agents = selectedAgents();
      if (!agents.length) return setNatsOutput("Select at least one nova.");
      sendDirectBtn.disabled = true;
      sendGroupBtn.disabled = true;
      pingAgentsBtn.disabled = true;
      setNatsOutput(`Pinging ${agents.join(", ")}...`);
      try {
        const payload = await postJson("/api/nats/ping", { agents });
        setNatsOutput(payload.results);
      } catch (error) {
        setNatsOutput(error);
      } finally {
        sendDirectBtn.disabled = false;
        sendGroupBtn.disabled = false;
        pingAgentsBtn.disabled = false;
      }
    }

    async function sendGroupNats() {
      const agents = selectedAgents();
      const message = $("natsMessage").value.trim();
      if (!message) return setNatsOutput("Enter a fleet message first.");
      if (!agents.length) return setNatsOutput("Select at least one nova.");
      sendDirectBtn.disabled = true;
      sendGroupBtn.disabled = true;
      pingAgentsBtn.disabled = true;
      setNatsOutput(`Sending group message to ${agents.join(", ")}...`);
      try {
        const payload = await postJson("/api/nats/group", { agents, message });
        setNatsOutput(payload.results);
        for (const result of payload.results || []) {
          logEvent("nats group", `${result.agent}: ${result.reply || result.error || "(no reply)"}`);
        }
      } catch (error) {
        setNatsOutput(error);
      } finally {
        sendDirectBtn.disabled = false;
        sendGroupBtn.disabled = false;
        pingAgentsBtn.disabled = false;
      }
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
    sendDirectBtn.addEventListener("click", sendDirectNats);
    sendGroupBtn.addEventListener("click", sendGroupNats);
    pingAgentsBtn.addEventListener("click", pingSelectedAgents);
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
        if (config.toolPolicy) {
          const policy = config.toolPolicy;
          $("toolState").textContent = policy.yolo
            ? `Tools: YOLO / ${policy.sandbox}`
            : `Tools: ${policy.sandbox}`;
          $("toolState").title = `home=${policy.home}; sudo=${policy.allowSudo}; approval=${policy.approvalPolicy}; scope=${policy.toolScope}`;
        }
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

    fetch("/api/nats/agents")
      .then((response) => response.json())
      .then((payload) => {
        state.agents = payload.agents || [];
        renderAgents(state.agents);
        setNatsOutput(payload.ok ? "NATS fleet ready." : "NATS_URL not configured.");
      })
      .catch((error) => setNatsOutput(error.message || String(error)));
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
