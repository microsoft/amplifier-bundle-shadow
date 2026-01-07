"""
Amplifier tool module for shadow environment management.

This module provides the 'shadow' tool for use within Amplifier sessions,
enabling agents to create and interact with isolated shadow environments
for safe testing of changes.
"""

from __future__ import annotations

import asyncio
from typing import Any

from amplifier_bundle_shadow import ShadowManager, ShadowEnvironment
from amplifier_bundle_shadow.models import RepoSpec


class ShadowTool:
    """
    Shadow environment tool for Amplifier.
    
    Provides operations for creating, managing, and interacting with
    shadow environments from within Amplifier sessions.
    """
    
    name = "shadow"
    description = "Manage shadow environments for safe testing of Amplifier changes"
    
    def __init__(self):
        self._manager: ShadowManager | None = None
    
    @property
    def manager(self) -> ShadowManager:
        """Lazy-initialize the shadow manager."""
        if self._manager is None:
            self._manager = ShadowManager()
        return self._manager
    
    async def execute(self, operation: str, **params: Any) -> dict[str, Any]:
        """
        Execute a shadow tool operation.
        
        Args:
            operation: The operation to perform
            **params: Operation-specific parameters
            
        Returns:
            Operation result as a dictionary
        """
        operations = {
            "create": self._create,
            "exec": self._exec,
            "diff": self._diff,
            "extract": self._extract,
            "inject": self._inject,
            "list": self._list,
            "status": self._status,
            "destroy": self._destroy,
        }
        
        if operation not in operations:
            return {
                "success": False,
                "error": f"Unknown operation: {operation}. Available: {', '.join(operations.keys())}",
            }
        
        try:
            return await operations[operation](**params)
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    async def _create(
        self,
        repos: list[str],
        name: str | None = None,
        mode: str = "auto",
        network_enabled: bool = True,
    ) -> dict[str, Any]:
        """Create a new shadow environment."""
        env = await self.manager.create(
            repos=repos,
            name=name,
            mode=mode,
            network_enabled=network_enabled,
        )
        
        return {
            "success": True,
            "shadow_id": env.shadow_id,
            "mode": env.backend.name,
            "repos": [r.display_name for r in env.repos],
            "status": env.status.value,
        }
    
    async def _exec(
        self,
        shadow_id: str,
        command: str,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Execute a command inside a shadow environment."""
        env = self.manager.get(shadow_id)
        if not env:
            return {
                "success": False,
                "error": f"Shadow environment not found: {shadow_id}",
            }
        
        result = await env.exec(command, timeout=timeout)
        
        return {
            "success": result.success,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    
    async def _diff(
        self,
        shadow_id: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Show changed files in a shadow environment."""
        env = self.manager.get(shadow_id)
        if not env:
            return {
                "success": False,
                "error": f"Shadow environment not found: {shadow_id}",
            }
        
        changed = env.diff(path)
        
        return {
            "success": True,
            "changed_files": [
                {
                    "path": f.path,
                    "change_type": f.change_type,
                    "size": f.size,
                }
                for f in changed
            ],
        }
    
    async def _extract(
        self,
        shadow_id: str,
        sandbox_path: str,
        host_path: str,
    ) -> dict[str, Any]:
        """Extract a file from a shadow environment."""
        env = self.manager.get(shadow_id)
        if not env:
            return {
                "success": False,
                "error": f"Shadow environment not found: {shadow_id}",
            }
        
        bytes_copied = env.extract(sandbox_path, host_path)
        
        return {
            "success": True,
            "bytes_copied": bytes_copied,
            "host_path": host_path,
        }
    
    async def _inject(
        self,
        shadow_id: str,
        host_path: str,
        sandbox_path: str,
    ) -> dict[str, Any]:
        """Inject a file into a shadow environment."""
        env = self.manager.get(shadow_id)
        if not env:
            return {
                "success": False,
                "error": f"Shadow environment not found: {shadow_id}",
            }
        
        env.inject(host_path, sandbox_path)
        
        return {
            "success": True,
            "sandbox_path": sandbox_path,
        }
    
    async def _list(self) -> dict[str, Any]:
        """List all shadow environments."""
        environments = self.manager.list_environments()
        
        return {
            "success": True,
            "environments": [env.to_info().to_dict() for env in environments],
        }
    
    async def _status(self, shadow_id: str) -> dict[str, Any]:
        """Get status of a shadow environment."""
        env = self.manager.get(shadow_id)
        if not env:
            return {
                "success": False,
                "error": f"Shadow environment not found: {shadow_id}",
            }
        
        return {
            "success": True,
            **env.to_info().to_dict(),
        }
    
    async def _destroy(
        self,
        shadow_id: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """Destroy a shadow environment."""
        try:
            self.manager.destroy(shadow_id, force=force)
            return {
                "success": True,
                "shadow_id": shadow_id,
            }
        except ValueError as e:
            return {
                "success": False,
                "error": str(e),
            }


# Tool schema for Amplifier
TOOL_SCHEMA = {
    "name": "shadow",
    "description": "Manage shadow environments for safe testing of Amplifier changes",
    "operations": {
        "create": {
            "description": "Create a new shadow environment with mock repositories",
            "parameters": {
                "repos": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Repository specs (e.g., 'microsoft/amplifier', 'org/repo@branch')",
                    "required": True,
                },
                "name": {
                    "type": "string",
                    "description": "Optional name for the environment",
                    "required": False,
                },
                "mode": {
                    "type": "string",
                    "enum": ["auto", "bubblewrap", "seatbelt"],
                    "description": "Sandbox mode (default: auto)",
                    "required": False,
                },
                "network_enabled": {
                    "type": "boolean",
                    "description": "Whether to allow network access (default: true)",
                    "required": False,
                },
            },
        },
        "exec": {
            "description": "Execute a command inside a shadow environment",
            "parameters": {
                "shadow_id": {
                    "type": "string",
                    "description": "Shadow environment ID",
                    "required": True,
                },
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                    "required": True,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 300)",
                    "required": False,
                },
            },
        },
        "diff": {
            "description": "Show changed files in a shadow environment",
            "parameters": {
                "shadow_id": {
                    "type": "string",
                    "description": "Shadow environment ID",
                    "required": True,
                },
                "path": {
                    "type": "string",
                    "description": "Limit diff to specific path",
                    "required": False,
                },
            },
        },
        "extract": {
            "description": "Extract a file from shadow environment to host",
            "parameters": {
                "shadow_id": {
                    "type": "string",
                    "description": "Shadow environment ID",
                    "required": True,
                },
                "sandbox_path": {
                    "type": "string",
                    "description": "Path inside sandbox (e.g., /workspace/file.py)",
                    "required": True,
                },
                "host_path": {
                    "type": "string",
                    "description": "Destination path on host",
                    "required": True,
                },
            },
        },
        "inject": {
            "description": "Copy a file from host into shadow environment",
            "parameters": {
                "shadow_id": {
                    "type": "string",
                    "description": "Shadow environment ID",
                    "required": True,
                },
                "host_path": {
                    "type": "string",
                    "description": "Source path on host",
                    "required": True,
                },
                "sandbox_path": {
                    "type": "string",
                    "description": "Destination path inside sandbox",
                    "required": True,
                },
            },
        },
        "list": {
            "description": "List all shadow environments",
            "parameters": {},
        },
        "status": {
            "description": "Get status of a shadow environment",
            "parameters": {
                "shadow_id": {
                    "type": "string",
                    "description": "Shadow environment ID",
                    "required": True,
                },
            },
        },
        "destroy": {
            "description": "Destroy a shadow environment",
            "parameters": {
                "shadow_id": {
                    "type": "string",
                    "description": "Shadow environment ID",
                    "required": True,
                },
                "force": {
                    "type": "boolean",
                    "description": "Force destruction (default: false)",
                    "required": False,
                },
            },
        },
    },
}


# Export the tool instance and schema
tool = ShadowTool()
schema = TOOL_SCHEMA
