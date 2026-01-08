#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VERSION="${1:-latest}"
IMAGE_NAME="${IMAGE_NAME:-ghcr.io/microsoft/amplifier-shadow}"

echo "Building shadow container image..."
echo "  Version: $VERSION"
echo "  Image: $IMAGE_NAME"

# Build for current architecture
docker build \
    -t "${IMAGE_NAME}:${VERSION}" \
    -t "${IMAGE_NAME}:latest" \
    .

echo ""
echo "Build complete!"
echo "  Image: ${IMAGE_NAME}:${VERSION}"
echo ""
echo "To test:"
echo "  docker run -it --rm ${IMAGE_NAME}:latest"
