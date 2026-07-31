from __future__ import annotations

import json
import os
import signal
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from .permissions import restrict_private_permissions
from .sidecars import InstalledSidecars
from .storage import SecureStorage, StorageBoundaryError


class SidecarRuntime(Protocol):
    def ensure_running(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class LoopbackSidecarProbe:
    streamcap_url: str = "http://127.0.0.1:6006"
    douyinlive_websocket_url: str = "ws://127.0.0.1:1088"
    connect_timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        _loopback_endpoint(self.streamcap_url, {"http", "https"})
        _loopback_endpoint(self.douyinlive_websocket_url, {"ws", "wss"})

    def ready(self) -> bool:
        return self._port_ready(self.streamcap_url) and self._port_ready(
            self.douyinlive_websocket_url
        )

    def any_port_ready(self) -> bool:
        return self._port_ready(self.streamcap_url) or self._port_ready(
            self.douyinlive_websocket_url
        )

    def wait(self, timeout_seconds: float, processes: list[subprocess.Popen[Any]] | None = None) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            for process in processes or []:
                return_code = process.poll()
                if return_code is not None:
                    raise RuntimeError(f"sidecar exited during startup with code {return_code}")
            if self.ready():
                return
            time.sleep(0.25)
        raise RuntimeError("sidecars did not open their loopback ports before the startup deadline")

    def _port_ready(self, value: str) -> bool:
        parsed = urlsplit(value)
        port = parsed.port or (443 if parsed.scheme in {"https", "wss"} else 80)
        try:
            with socket.create_connection(
                (parsed.hostname or "", port), timeout=self.connect_timeout_seconds
            ):
                return True
        except OSError:
            return False


@dataclass(slots=True)
class ExternalSidecarRuntime:
    probe: LoopbackSidecarProbe
    startup_timeout_seconds: float = 10

    def ensure_running(self) -> None:
        self.probe.wait(self.startup_timeout_seconds)

    def close(self) -> None:
        return None


@dataclass(slots=True)
class LocalSidecarRuntime:
    installed: InstalledSidecars
    probe: LoopbackSidecarProbe
    storage_root: Path
    recordings_config: Path
    settings_template: Path
    douyinlive_config: Path
    startup_timeout_seconds: float = 90
    _processes: list[subprocess.Popen[Any]] = field(default_factory=list, init=False)
    _logs: list[Any] = field(default_factory=list, init=False)

    def ensure_running(self) -> None:
        self.installed.verify()
        if self.probe.any_port_ready():
            raise RuntimeError(
                "a sidecar port is already occupied; use --sidecars external only for a verified external runtime"
            )
        SecureStorage.require_private_config(self.recordings_config)
        SecureStorage.require_private_config(self.douyinlive_config)
        staging = self.storage_root.expanduser().resolve() / "staging"
        staging.mkdir(parents=True, exist_ok=True, mode=0o700)
        restrict_private_permissions(staging, 0o700)
        settings = json.loads(self.settings_template.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise RuntimeError("StreamCap settings template must be a JSON object")
        settings["live_save_path"] = str(staging)
        user_settings = self.installed.streamcap_checkout / "config/user_settings.json"
        _write_private_json(user_settings, settings)

        log_root = self.storage_root.expanduser().resolve() / "logs/sidecars"
        log_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        restrict_private_permissions(log_root, 0o700)
        self._start(
            [
                str(self.installed.streamcap_python),
                "main.py",
                "--web",
                "--host",
                "127.0.0.1",
                "--port",
                str(_endpoint_port(self.probe.streamcap_url)),
            ],
            cwd=self.installed.streamcap_checkout,
            log_path=log_root / "streamcap.log",
            environment={"PLATFORM": "web", "TZ": "UTC"},
        )
        self._start(
            [
                str(self.installed.douyinlive_binary),
                "--config",
                str(self.douyinlive_config),
                "--port",
                str(_endpoint_port(self.probe.douyinlive_websocket_url)),
            ],
            cwd=self.installed.douyinlive_binary.parent,
            log_path=log_root / "douyinlive.log",
            environment={"TZ": "UTC"},
        )
        try:
            self.probe.wait(self.startup_timeout_seconds, self._processes)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        for process in reversed(self._processes):
            if process.poll() is None:
                try:
                    if os.name == "nt":
                        process.terminate()
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    continue
        deadline = time.monotonic() + 10
        for process in reversed(self._processes):
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        self._processes.clear()
        for log_file in self._logs:
            log_file.close()
        self._logs.clear()

    def _start(
        self,
        command: list[str],
        *,
        cwd: Path,
        log_path: Path,
        environment: dict[str, str],
    ) -> None:
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        restrict_private_permissions(log_path, 0o600)
        log_file = os.fdopen(descriptor, "ab", buffering=0)
        self._logs.append(log_file)
        process_environment = os.environ.copy()
        process_environment.update(environment)
        self._processes.append(
            subprocess.Popen(
                command,
                cwd=cwd,
                env=process_environment,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
                creationflags=(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    if os.name == "nt"
                    else 0
                ),
            )
        )


@dataclass(slots=True)
class ComposeSidecarRuntime:
    compose_file: Path
    probe: LoopbackSidecarProbe
    storage_root: Path
    recordings_config: Path
    douyinlive_config: Path
    startup_timeout_seconds: float = 120
    _started: bool = field(default=False, init=False)

    def ensure_running(self) -> None:
        SecureStorage.require_private_config(self.recordings_config)
        SecureStorage.require_private_config(self.douyinlive_config)
        environment = self._environment()
        _run_compose(
            self.compose_file,
            ["up", "-d", "--build", "--force-recreate", "streamcap", "douyinlive"],
            environment,
            timeout_seconds=1800,
        )
        self._started = True
        try:
            self.probe.wait(self.startup_timeout_seconds)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if not self._started:
            return
        _run_compose(
            self.compose_file,
            ["stop", "streamcap", "douyinlive"],
            self._environment(),
            timeout_seconds=120,
        )
        self._started = False

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "LIVE_RESEARCH_UID": str(getattr(os, "getuid", lambda: 1000)()),
                "LIVE_RESEARCH_GID": str(getattr(os, "getgid", lambda: 1000)()),
                "ASSETGRAPH_LIVE_RESEARCH_ROOT": str(self.storage_root.expanduser().resolve()),
                "STREAMCAP_RECORDINGS_CONFIG": str(self.recordings_config.expanduser().resolve()),
                "DOUYINLIVE_CONFIG_FILE": str(self.douyinlive_config.expanduser().resolve()),
            }
        )
        return environment


def _loopback_endpoint(value: str, schemes: set[str]) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in schemes or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("sidecar endpoints must use the expected scheme on loopback")
    if parsed.port is None:
        raise ValueError("sidecar endpoints must include an explicit port")


def _endpoint_port(value: str) -> int:
    port = urlsplit(value).port
    if port is None:
        raise ValueError("sidecar endpoint has no port")
    return port


def _write_private_json(destination: Path, value: dict[str, Any]) -> None:
    destination = destination.expanduser()
    if destination.is_symlink() or destination.parent.is_symlink():
        raise StorageBoundaryError("runtime configuration cannot use symlinks")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        restrict_private_permissions(temporary, 0o600)
        os.replace(temporary, destination)
        restrict_private_permissions(destination, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _run_compose(
    compose_file: Path,
    arguments: list[str],
    environment: dict[str, str],
    *,
    timeout_seconds: int,
) -> None:
    completed = subprocess.run(
        [*_compose_command(), "-f", str(compose_file), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=timeout_seconds,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()[-2000:]
        raise RuntimeError(f"docker compose failed with code {completed.returncode}: {detail}")


def _compose_command() -> list[str]:
    docker = shutil.which("docker")
    if docker:
        completed = subprocess.run(
            [docker, "compose", "version"],
            check=False,
            capture_output=True,
            timeout=10,
        )
        if completed.returncode == 0:
            return [docker, "compose"]
    legacy = shutil.which("docker-compose")
    if legacy:
        return [legacy]
    raise RuntimeError("neither docker compose nor docker-compose is installed")
