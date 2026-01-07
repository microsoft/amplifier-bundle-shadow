"""
Amplifier Shadow - OS-level sandboxed environments for testing Amplifier changes.

This package provides tools for creating isolated shadow environments that intercept
git operations to use local mock repositories, enabling safe testing of changes
before deployment.
"""

__version__ = "0.1.0"

from .models import RepoSpec, ExecResult, ShadowStatus
from .environment import ShadowEnvironment
from .manager import ShadowManager

__all__ = [
    "RepoSpec",
    "ExecResult", 
    "ShadowStatus",
    "ShadowEnvironment",
    "ShadowManager",
]
