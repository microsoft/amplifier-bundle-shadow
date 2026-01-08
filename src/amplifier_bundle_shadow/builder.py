"""Build shadow container image from bundled Dockerfile."""

from __future__ import annotations

import asyncio
import importlib.resources
import shutil
import tempfile
from pathlib import Path

from .container import ContainerRuntime

__all__ = ["ImageBuilder", "DEFAULT_IMAGE_NAME"]

# Local image name (no registry prefix)
DEFAULT_IMAGE_NAME = "amplifier-shadow:local"


class ImageBuilder:
    """
    Builds the shadow container image from bundled resources.
    
    The Dockerfile and related files are bundled with the Python package,
    allowing local builds without needing to clone the repo or pull from
    a registry.
    """
    
    def __init__(self, runtime: ContainerRuntime | None = None) -> None:
        self.runtime = runtime or ContainerRuntime()
    
    async def build(
        self,
        tag: str = DEFAULT_IMAGE_NAME,
        progress_callback: callable | None = None,
    ) -> str:
        """
        Build the shadow container image.
        
        Args:
            tag: Image tag (default: amplifier-shadow:local)
            progress_callback: Optional callback for build progress
            
        Returns:
            The image tag that was built
        """
        # Get container files from package resources
        container_dir = self._get_container_dir()
        
        if progress_callback:
            progress_callback(f"Building image {tag} from {container_dir}")
        
        # Build the image
        args = [
            self.runtime.runtime,
            "build",
            "-t", tag,
            str(container_dir),
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        
        # Stream output if callback provided
        output_lines = []
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode().rstrip()
            output_lines.append(decoded)
            if progress_callback:
                progress_callback(decoded)
        
        await proc.wait()
        
        if proc.returncode != 0:
            raise RuntimeError(
                f"Failed to build image: {chr(10).join(output_lines[-10:])}"
            )
        
        return tag
    
    async def image_exists(self, tag: str = DEFAULT_IMAGE_NAME) -> bool:
        """Check if the image exists locally."""
        args = [
            self.runtime.runtime,
            "image", "inspect",
            tag,
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        
        return proc.returncode == 0
    
    async def ensure_image(
        self,
        tag: str = DEFAULT_IMAGE_NAME,
        progress_callback: callable | None = None,
    ) -> str:
        """
        Ensure the image exists, building if necessary.
        
        Returns:
            The image tag (either existing or newly built)
        """
        if await self.image_exists(tag):
            return tag
        
        return await self.build(tag, progress_callback)
    
    def _get_container_dir(self) -> Path:
        """Get the path to bundled container files."""
        # Try package resources first (installed package)
        try:
            # Python 3.9+ importlib.resources
            files = importlib.resources.files("amplifier_bundle_shadow")
            container_path = files / "container"
            
            # Check if it's a real directory we can use
            if hasattr(container_path, "_path"):
                path = Path(container_path._path)
                if path.exists() and (path / "Dockerfile").exists():
                    return path
        except (AttributeError, TypeError):
            pass
        
        # Try relative to this file (development mode)
        dev_path = Path(__file__).parent / "container"
        if dev_path.exists() and (dev_path / "Dockerfile").exists():
            return dev_path
        
        # Try the repo container directory (development mode)
        repo_path = Path(__file__).parent.parent.parent.parent / "container"
        if repo_path.exists() and (repo_path / "Dockerfile").exists():
            return repo_path
        
        raise FileNotFoundError(
            "Could not find container build files. "
            "Ensure the package is installed correctly."
        )
