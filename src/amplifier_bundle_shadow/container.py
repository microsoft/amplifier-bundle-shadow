"""Container runtime abstraction (Docker/Podman)."""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ContainerRuntime",
    "Mount",
    "ContainerNotFoundError",
    "ContainerRuntimeError",
]


class ContainerRuntimeError(Exception):
    """Raised when container operations fail."""

    pass


class ContainerNotFoundError(Exception):
    """Raised when no container runtime is available."""

    pass


@dataclass
class Mount:
    """Container mount specification."""

    host_path: Path
    container_path: str
    readonly: bool = False

    def to_arg(self) -> str:
        """Convert to -v argument format."""
        mode = "ro" if self.readonly else "rw"
        return f"{self.host_path}:{self.container_path}:{mode}"


class ContainerRuntime:
    """
    Abstraction over Docker/Podman container runtimes.

    Prefers podman (rootless by default), falls back to docker.
    All operations are async for non-blocking I/O.
    """

    def __init__(self) -> None:
        """Initialize and detect available runtime."""
        self.runtime = self._detect_runtime()

    def _detect_runtime(self) -> str:
        """Detect available container runtime."""
        if shutil.which("podman"):
            return "podman"
        if shutil.which("docker"):
            return "docker"
        raise ContainerNotFoundError(
            "No container runtime found. Please install docker or podman."
        )

    async def run(
        self,
        image: str,
        name: str,
        mounts: list[Mount] | None = None,
        env: dict[str, str] | None = None,
        command: list[str] | None = None,
        detach: bool = True,
        remove_on_exit: bool = False,
        memory_limit: str = "4g",
        pids_limit: int = 256,
    ) -> str:
        """Start a new container with security hardening.

        Security measures applied:
        - Drop all capabilities (--cap-drop=ALL)
        - No new privileges (--security-opt=no-new-privileges)
        - Memory limit (default 4GB)
        - PID limit (default 256 processes)
        """
        args = [self.runtime, "run"]

        if detach:
            args.append("-d")

        if remove_on_exit:
            args.append("--rm")

        # Security hardening
        args.extend(
            [
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                f"--memory={memory_limit}",
                f"--pids-limit={pids_limit}",
            ]
        )

        args.extend(["--name", name])

        if mounts:
            for mount in mounts:
                args.extend(["-v", mount.to_arg()])

        if env:
            for key, value in env.items():
                args.extend(["-e", f"{key}={value}"])

        args.append(image)

        if command:
            args.extend(command)

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise ContainerRuntimeError(
                f"Failed to start container: {stderr.decode().strip()}"
            )

        return stdout.decode().strip()

    async def exec(
        self,
        container: str,
        command: str,
        timeout: int = 300,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        """Execute command in running container."""
        args = [self.runtime, "exec"]

        if workdir:
            args.extend(["-w", workdir])

        if env:
            for key, value in env.items():
                args.extend(["-e", f"{key}={value}"])

        args.extend([container, "sh", "-c", command])

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=timeout,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            return proc.returncode, stdout.decode(), stderr.decode()
        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(f"Command timed out after {timeout}s: {command}")

    async def exec_interactive(
        self,
        container: str,
        shell: str = "bash",
        workdir: str | None = None,
    ) -> None:
        """Open interactive shell in container (replaces current process)."""
        args = [self.runtime, "exec", "-it"]

        if workdir:
            args.extend(["-w", workdir])

        args.extend([container, shell])

        # Replace current process with interactive shell
        os.execvp(args[0], args)

    async def stop(self, container: str, timeout: int = 10) -> None:
        """Stop a running container."""
        proc = await asyncio.create_subprocess_exec(
            self.runtime,
            "stop",
            "-t",
            str(timeout),
            container,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

    async def remove(self, container: str, force: bool = False) -> None:
        """Remove a container."""
        args = [self.runtime, "rm"]
        if force:
            args.append("-f")
        args.append(container)

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()

    async def exists(self, container: str) -> bool:
        """Check if container exists (running or stopped)."""
        proc = await asyncio.create_subprocess_exec(
            self.runtime,
            "container",
            "inspect",
            container,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        return proc.returncode == 0

    async def is_running(self, container: str) -> bool:
        """Check if container is currently running."""
        proc = await asyncio.create_subprocess_exec(
            self.runtime,
            "container",
            "inspect",
            "-f",
            "{{.State.Running}}",
            container,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip().lower() == "true"

    async def logs(self, container: str, tail: int = 100) -> str:
        """Get container logs."""
        proc = await asyncio.create_subprocess_exec(
            self.runtime,
            "logs",
            "--tail",
            str(tail),
            container,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode()
