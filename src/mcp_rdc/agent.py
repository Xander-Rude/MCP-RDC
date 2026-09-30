from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psutil
import websockets

from .config import AgentSettings


def _package_version() -> str:
    try:
        return version("mcp-rdc")
    except PackageNotFoundError:
        return "dev"


def _append_query(url: str, **values: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(values)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class AgentRuntime:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.allowed_roots = tuple(root.resolve(strict=False) for root in settings.allowed_roots)
        self._secrets = tuple(
            secret for secret in (settings.agent_token,) if secret and len(secret) >= 8
        )

    def resolve_path(self, value: str | None) -> Path:
        if not value:
            candidate = self.allowed_roots[0]
        else:
            raw = Path(value).expanduser()
            candidate = raw if raw.is_absolute() else self.allowed_roots[0] / raw
            candidate = candidate.resolve(strict=False)

        candidate_norm = os.path.normcase(os.path.abspath(str(candidate)))
        for root in self.allowed_roots:
            root_norm = os.path.normcase(os.path.abspath(str(root)))
            try:
                if os.path.commonpath([candidate_norm, root_norm]) == root_norm:
                    return Path(candidate)
            except ValueError:
                continue
        raise PermissionError(f"path is outside allowed roots: {candidate}")

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "***REDACTED***")
        return text

    def _truncate(self, text: str) -> tuple[str, bool]:
        data = text.encode("utf-8", errors="replace")
        if len(data) <= self.settings.max_output_bytes:
            return self._redact(text), False
        clipped = data[: self.settings.max_output_bytes].decode("utf-8", errors="replace")
        return self._redact(clipped) + "\n...[output truncated]", True

    async def _kill_tree(self, pid: int) -> None:
        try:
            parent = psutil.Process(pid)
        except psutil.Error:
            return
        for process in parent.children(recursive=True):
            with contextlib.suppress(psutil.Error):
                process.kill()
        with contextlib.suppress(psutil.Error):
            parent.kill()

    async def _run(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        workdir = self.resolve_path(cwd) if cwd else self.allowed_roots[0]
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
        effective_timeout = timeout or self.settings.command_timeout
        started = time.monotonic()
        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(
                process.communicate(), timeout=effective_timeout
            )
        except TimeoutError as exc:
            await self._kill_tree(process.pid)
            await process.wait()
            raise TimeoutError(f"command exceeded {effective_timeout:.1f}s") from exc

        stdout, stdout_truncated = self._truncate(stdout_raw.decode("utf-8", errors="replace"))
        stderr, stderr_truncated = self._truncate(stderr_raw.decode("utf-8", errors="replace"))
        return {
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "duration_seconds": round(time.monotonic() - started, 3),
            "truncated": stdout_truncated or stderr_truncated,
        }

    async def system_info(self, _: dict[str, Any]) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        return {
            "agent_version": _package_version(),
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "boot_time": psutil.boot_time(),
            "cpu_count": psutil.cpu_count(),
            "memory_total_bytes": vm.total,
            "memory_available_bytes": vm.available,
            "allowed_roots": [str(root) for root in self.allowed_roots],
        }

    async def read_text(self, params: dict[str, Any]) -> dict[str, Any]:
        path = self.resolve_path(str(params["path"]))
        max_bytes = min(int(params.get("max_bytes", 262144)), self.settings.max_output_bytes)
        data = path.read_bytes()
        truncated = len(data) > max_bytes
        if truncated:
            data = data[:max_bytes]
        text = self._redact(data.decode(str(params.get("encoding", "utf-8")), errors="replace"))
        return {
            "path": str(path),
            "text": text,
            "size_bytes": path.stat().st_size,
            "truncated": truncated,
        }

    async def write_text(self, params: dict[str, Any]) -> dict[str, Any]:
        path = self.resolve_path(str(params["path"]))
        if bool(params.get("create_parents", True)):
            path.parent.mkdir(parents=True, exist_ok=True)
        content = str(params.get("content", ""))
        encoding = str(params.get("encoding", "utf-8"))
        tmp = path.with_name(path.name + ".mcp-rdc.tmp")
        tmp.write_text(content, encoding=encoding)
        os.replace(tmp, path)
        return {"path": str(path), "bytes_written": len(content.encode(encoding))}

    async def list_directory(self, params: dict[str, Any]) -> dict[str, Any]:
        path = self.resolve_path(str(params.get("path") or ""))
        limit = max(1, min(int(params.get("limit", 500)), 2000))
        entries: list[dict[str, Any]] = []
        for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:limit]:
            try:
                stat = item.stat()
            except OSError:
                continue
            entries.append(
                {
                    "name": item.name,
                    "path": str(item),
                    "is_dir": item.is_dir(),
                    "size_bytes": stat.st_size,
                    "modified_time": stat.st_mtime,
                }
            )
        return {"path": str(path), "entries": entries, "limit": limit}

    async def tail_file(self, params: dict[str, Any]) -> dict[str, Any]:
        path = self.resolve_path(str(params["path"]))
        lines = max(1, min(int(params.get("lines", 200)), 5000))
        max_bytes = min(int(params.get("max_bytes", 524288)), self.settings.max_output_bytes)
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                handle.readline()
            data = handle.read()
        text = data.decode(str(params.get("encoding", "utf-8")), errors="replace")
        selected = "\n".join(text.splitlines()[-lines:])
        selected, truncated = self._truncate(selected)
        return {"path": str(path), "text": selected, "size_bytes": size, "truncated": truncated}

    async def run_powershell(self, params: dict[str, Any]) -> dict[str, Any]:
        executable = shutil.which("pwsh") or shutil.which("powershell.exe")
        if executable is None:
            raise RuntimeError("PowerShell executable not found")
        command = str(params["command"])
        prefix = (
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();"
            "$OutputEncoding=[Console]::OutputEncoding;"
        )
        return await self._run(
            [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", prefix + command],
            cwd=params.get("cwd"),
            timeout=float(params["timeout_seconds"]) if params.get("timeout_seconds") else None,
        )

    async def list_processes(self, params: dict[str, Any]) -> dict[str, Any]:
        needle = str(params.get("name_contains", "")).lower()
        limit = max(1, min(int(params.get("limit", 200)), 1000))
        rows: list[dict[str, Any]] = []
        for process in psutil.process_iter(["pid", "name", "username", "cmdline", "create_time"]):
            try:
                info = process.info
                name = str(info.get("name") or "")
                if needle and needle not in name.lower():
                    continue
                cmdline = " ".join(info.get("cmdline") or [])
                cmdline, _ = self._truncate(cmdline)
                rows.append(
                    {
                        "pid": info.get("pid"),
                        "name": name,
                        "username": info.get("username"),
                        "cmdline": cmdline,
                        "create_time": info.get("create_time"),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if len(rows) >= limit:
                break
        return {"processes": rows, "limit": limit}

    async def scheduled_task_status(self, params: dict[str, Any]) -> dict[str, Any]:
        if os.name != "nt":
            raise RuntimeError("scheduled tasks are only supported on Windows")
        name = str(params["name"])
        quoted = _powershell_quote(name)
        command = (
            f"$t=Get-ScheduledTask -TaskName {quoted} -ErrorAction Stop;"
            f"$i=Get-ScheduledTaskInfo -TaskName {quoted} -ErrorAction Stop;"
            "[pscustomobject]@{"
            "TaskName=$t.TaskName;State=[string]$t.State;"
            "LastRunTime=$i.LastRunTime.ToString('o');"
            "LastTaskResult=$i.LastTaskResult;"
            "NextRunTime=if($i.NextRunTime){$i.NextRunTime.ToString('o')}else{$null}"
            "}|ConvertTo-Json -Compress"
        )
        result = await self.run_powershell({"command": command})
        if result["exit_code"] != 0:
            raise RuntimeError(result["stderr"] or result["stdout"])
        return json.loads(result["stdout"])

    async def scheduled_task_start(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params["name"])
        result = await self.run_powershell(
            {"command": f"Start-ScheduledTask -TaskName {_powershell_quote(name)}"}
        )
        if result["exit_code"] != 0:
            raise RuntimeError(result["stderr"] or result["stdout"])
        return {"task": name, "started": True}

    async def scheduled_task_stop(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params["name"])
        result = await self.run_powershell(
            {"command": f"Stop-ScheduledTask -TaskName {_powershell_quote(name)}"}
        )
        if result["exit_code"] != 0:
            raise RuntimeError(result["stderr"] or result["stdout"])
        return {"task": name, "stopped": True}

    async def git_status(self, params: dict[str, Any]) -> dict[str, Any]:
        repo = self.resolve_path(str(params.get("repo_path") or ""))
        result = await self._run(["git", "-C", str(repo), "status", "--short", "--branch"])
        return {"repo_path": str(repo), **result}

    async def git_head(self, params: dict[str, Any]) -> dict[str, Any]:
        repo = self.resolve_path(str(params.get("repo_path") or ""))
        head = await self._run(["git", "-C", str(repo), "rev-parse", "HEAD"])
        branch = await self._run(["git", "-C", str(repo), "branch", "--show-current"])
        if head["exit_code"] != 0:
            raise RuntimeError(head["stderr"] or head["stdout"])
        return {
            "repo_path": str(repo),
            "head": head["stdout"].strip(),
            "branch": branch["stdout"].strip(),
        }

    async def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        handlers = {
            "system.info": self.system_info,
            "fs.read_text": self.read_text,
            "fs.write_text": self.write_text,
            "fs.list": self.list_directory,
            "fs.tail": self.tail_file,
            "shell.powershell": self.run_powershell,
            "process.list": self.list_processes,
            "task.status": self.scheduled_task_status,
            "task.start": self.scheduled_task_start,
            "task.stop": self.scheduled_task_stop,
            "git.status": self.git_status,
            "git.head": self.git_head,
        }
        handler = handlers.get(method)
        if handler is None:
            raise ValueError(f"unsupported method: {method}")
        return await handler(params)


async def _handle_request(
    websocket: Any,
    send_lock: asyncio.Lock,
    runtime: AgentRuntime,
    payload: dict[str, Any],
) -> None:
    request_id = str(payload.get("id", ""))
    method = str(payload.get("method", ""))
    params = payload.get("params")
    if not isinstance(params, dict):
        params = {}
    try:
        result = await runtime.dispatch(method, params)
        response = {"type": "response", "id": request_id, "ok": True, "result": result}
    except Exception as exc:
        response = {
            "type": "response",
            "id": request_id,
            "ok": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    async with send_lock:
        await websocket.send(json.dumps(response, ensure_ascii=False))


async def _heartbeat(websocket: Any, send_lock: asyncio.Lock, interval: float = 15.0) -> None:
    while True:
        await asyncio.sleep(interval)
        async with send_lock:
            await websocket.send(json.dumps({"type": "heartbeat"}))


def _consume_task_result(task: asyncio.Task[None], tasks: set[asyncio.Task[None]]) -> None:
    tasks.discard(task)
    with contextlib.suppress(asyncio.CancelledError, Exception):
        task.result()


async def run_agent(settings: AgentSettings) -> None:
    runtime = AgentRuntime(settings)
    url = _append_query(settings.gateway_ws, agent_id=settings.agent_id)
    delay = 1.0

    while True:
        try:
            async with websockets.connect(
                url,
                additional_headers={"Authorization": f"Bearer {settings.agent_token}"},
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=2 * 1024 * 1024,
            ) as websocket:
                delay = 1.0
                send_lock = asyncio.Lock()
                hello = {"type": "hello", "metadata": await runtime.system_info({})}
                await websocket.send(json.dumps(hello, ensure_ascii=False))
                tasks: set[asyncio.Task[None]] = set()
                heartbeat = asyncio.create_task(_heartbeat(websocket, send_lock))
                tasks.add(heartbeat)
                on_task_done = functools.partial(_consume_task_result, tasks=tasks)
                heartbeat.add_done_callback(on_task_done)
                try:
                    async for raw in websocket:
                        payload = json.loads(raw)
                        if not isinstance(payload, dict) or payload.get("type") != "request":
                            continue
                        task = asyncio.create_task(
                            _handle_request(websocket, send_lock, runtime, payload)
                        )
                        tasks.add(task)
                        task.add_done_callback(on_task_done)
                finally:
                    for task in tasks:
                        task.cancel()
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[mcp-rdc-agent] connection failed: {exc}", file=sys.stderr)

        await asyncio.sleep(delay)
        delay = min(delay * 2, settings.reconnect_max_seconds)


def main() -> None:
    settings = AgentSettings.from_env(strict=True)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_agent(settings))


if __name__ == "__main__":
    main()
