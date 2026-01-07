"""Factory for creating sandbox backends."""

from __future__ import annotations

import asyncio
import platform
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import SandboxBackend


def _check_bubblewrap_works() -> bool:
    """Check if bubblewrap actually works (not just installed)."""
    if not shutil.which("bwrap"):
        return False
    
    # Try a minimal bwrap command to see if user namespaces work
    import subprocess
    try:
        result = subprocess.run(
            ["bwrap", "--dev-bind", "/", "/", "true"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def get_available_backends() -> list[str]:
    """Get list of available sandbox backends on this system."""
    available = []
    system = platform.system()
    
    if system == "Linux":
        if _check_bubblewrap_works():
            available.append("bubblewrap")
    
    elif system == "Darwin":
        from .macos import SeatbeltBackend
        # sandbox-exec is built into macOS
        backend = SeatbeltBackend.__new__(SeatbeltBackend)
        if backend.is_available:
            available.append("seatbelt")
    
    # Direct mode is always available as fallback
    available.append("direct")
    
    return available


def get_sandbox_backend(
    shadow_dir: Path,
    repos_dir: Path,
    mode: str = "auto",
    network_enabled: bool = True,
) -> "SandboxBackend":
    """
    Get the appropriate sandbox backend for the current platform.
    
    Args:
        shadow_dir: Directory for this shadow environment
        repos_dir: Directory containing bare git repos
        mode: Backend mode - "auto", "bubblewrap", "seatbelt", "direct", or "container"
        network_enabled: Whether to allow network access
        
    Returns:
        A SandboxBackend instance
        
    Raises:
        RuntimeError: If no suitable backend is available
    """
    system = platform.system()
    
    if mode == "container":
        raise NotImplementedError("Container mode not yet implemented")
    
    if mode == "auto":
        # Auto-detect based on platform and availability
        if system == "Linux":
            if _check_bubblewrap_works():
                mode = "bubblewrap"
            else:
                # Fall back to direct mode
                mode = "direct"
        elif system == "Darwin":
            mode = "seatbelt"
        else:
            # Fall back to direct mode on unknown platforms
            mode = "direct"
    
    if mode == "bubblewrap":
        from .linux import BubblewrapBackend
        backend = BubblewrapBackend(
            shadow_dir=shadow_dir,
            repos_dir=repos_dir,
            network_enabled=network_enabled,
        )
        if not backend.is_available:
            raise RuntimeError(
                "Bubblewrap is not installed. "
                "Install with: apt install bubblewrap (Debian/Ubuntu) "
                "or dnf install bubblewrap (Fedora)"
            )
        if not _check_bubblewrap_works():
            raise RuntimeError(
                "Bubblewrap is installed but cannot create user namespaces. "
                "This may happen in containers without CAP_SYS_ADMIN. "
                "Use --mode direct for minimal isolation."
            )
        return backend
    
    elif mode == "seatbelt":
        from .macos import SeatbeltBackend
        backend = SeatbeltBackend(
            shadow_dir=shadow_dir,
            repos_dir=repos_dir,
            network_enabled=network_enabled,
        )
        if not backend.is_available:
            raise RuntimeError(
                "sandbox-exec is not available. "
                "This should be built into macOS."
            )
        return backend
    
    elif mode == "direct":
        from .direct import DirectBackend
        return DirectBackend(
            shadow_dir=shadow_dir,
            repos_dir=repos_dir,
            network_enabled=network_enabled,
        )
    
    else:
        raise ValueError(f"Unknown sandbox mode: {mode}")
