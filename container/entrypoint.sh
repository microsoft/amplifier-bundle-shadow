#!/bin/bash
set -e

# Force uv to use git (respects our URL rewriting instead of GitHub API fast path)
export UV_NO_GITHUB_FAST_PATH=1

# Note: /etc/shadow-environment.json is created at image build time (see Dockerfile)
# It contains container self-documentation for agents to discover configuration

# Start Gitea in background
echo "Starting Gitea..."
gitea web --config /etc/gitea/app.ini &
GITEA_PID=$!

# Wait for Gitea to be ready
echo "Waiting for Gitea to be ready..."
for i in {1..60}; do
    if curl -s http://localhost:3000/api/v1/version > /dev/null 2>&1; then
        echo "Gitea is ready"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "ERROR: Gitea failed to start"
        exit 1
    fi
    sleep 0.5
done

# Create admin user if not exists (ignore errors if already exists)
gitea admin user create \
    --config /etc/gitea/app.ini \
    --admin \
    --username shadow \
    --password shadow \
    --email shadow@localhost \
    2>/dev/null || true

# Configure git defaults
git config --global user.email "shadow@localhost"
git config --global user.name "Shadow"
git config --global init.defaultBranch main
git config --global advice.detachedHead false

# If no command provided or command is "bash", keep container alive
if [ $# -eq 0 ] || [ "$1" = "bash" ]; then
    echo "Shadow environment ready. Keeping container alive..."
    # Wait for Gitea process to keep container running
    wait $GITEA_PID
else
    # Execute the requested command
    exec "$@"
fi
