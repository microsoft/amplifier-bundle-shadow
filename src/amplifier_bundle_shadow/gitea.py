"""Gitea API client for shadow environments."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .container import ContainerRuntime

__all__ = ["GiteaClient", "GiteaError", "GiteaTimeoutError"]


class GiteaError(Exception):
    """Raised when Gitea operations fail."""
    pass


class GiteaTimeoutError(GiteaError):
    """Raised when Gitea doesn't become ready in time."""
    pass


@dataclass
class GiteaClient:
    """
    Gitea API client that operates within a container.
    
    All operations are executed via container exec since Gitea
    runs inside the shadow container on localhost:3000.
    """
    
    runtime: "ContainerRuntime"
    container: str
    base_url: str = "http://localhost:3000"
    username: str = "shadow"
    password: str = "shadow"
    
    async def wait_ready(self, timeout: float = 30.0) -> None:
        """Wait for Gitea to be ready AND admin user to exist."""
        start = asyncio.get_event_loop().time()
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed >= timeout:
                raise GiteaTimeoutError(
                    f"Gitea did not become ready within {timeout}s"
                )
            
            # First check if Gitea API responds
            code, stdout, _ = await self._exec(
                f"curl -s {self.base_url}/api/v1/version"
            )
            
            if code != 0 or "version" not in stdout:
                await asyncio.sleep(0.5)
                continue
            
            # Then verify admin user exists (entrypoint creates it after Gitea starts)
            auth_code, auth_stdout, _ = await self._exec(
                f"curl -s -u {self.username}:{self.password} {self.base_url}/api/v1/user"
            )
            
            if auth_code == 0 and '"login"' in auth_stdout:
                return
            
            await asyncio.sleep(0.5)
    
    async def create_org(self, org_name: str) -> bool:
        """Create an organization (idempotent)."""
        code, stdout, _ = await self._curl_api(
            "POST",
            "/api/v1/orgs",
            {"username": org_name},
        )
        
        # 201 = created, 422 = already exists
        return code == 201
    
    async def create_repo(self, org: str, name: str) -> dict:
        """Create a repository under an organization."""
        code, stdout, stderr = await self._curl_api(
            "POST",
            f"/api/v1/orgs/{org}/repos",
            {"name": name, "private": False},
        )
        
        if code not in (200, 201):
            raise GiteaError(f"Failed to create repo {org}/{name}: {stdout}")
        
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {"name": name, "org": org}
    
    async def push_bundle(
        self,
        org: str,
        name: str,
        bundle_container_path: str,
    ) -> None:
        """Push a git bundle to a Gitea repository."""
        # Clone bundle to temp dir, set remote, push
        commands = f"""
cd /tmp && rm -rf _push_{name} && \
git clone {bundle_container_path} _push_{name} && \
cd _push_{name} && \
git remote set-url origin http://{self.username}:{self.password}@localhost:3000/{org}/{name}.git && \
git push -u origin --all --force 2>&1
"""
        code, stdout, stderr = await self._exec(commands.strip())
        
        if code != 0:
            raise GiteaError(f"Failed to push bundle: {stdout} {stderr}")
    
    async def setup_repo_from_bundle(
        self,
        org: str,
        name: str,
        bundle_container_path: str,
    ) -> None:
        """Complete setup: create org, create repo, push bundle."""
        await self.create_org(org)
        await self.create_repo(org, name)
        await self.push_bundle(org, name, bundle_container_path)
    
    async def _exec(self, command: str) -> tuple[int, str, str]:
        """Execute command in container via runtime."""
        return await self.runtime.exec(self.container, command)
    
    async def _curl_api(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
    ) -> tuple[int, str, str]:
        """Make authenticated API request via curl."""
        cmd = f"curl -s -w '\\n%{{http_code}}' -X {method}"
        cmd += f" -u {self.username}:{self.password}"
        cmd += " -H 'Content-Type: application/json'"
        
        if data:
            json_data = json.dumps(data).replace("'", "'\\''")
            cmd += f" -d '{json_data}'"
        
        cmd += f" {self.base_url}{endpoint}"
        
        code, stdout, stderr = await self._exec(cmd)
        
        # Parse HTTP status code from output
        lines = stdout.strip().split('\n')
        if len(lines) >= 1:
            try:
                http_code = int(lines[-1])
                body = '\n'.join(lines[:-1])
                return http_code, body, stderr
            except ValueError:
                pass
        
        return code, stdout, stderr
