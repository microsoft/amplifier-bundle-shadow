FROM python:3.12-slim

ARG GITEA_VERSION=1.21.4
ARG TARGETARCH

# Install dependencies and common CLI tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    sqlite3 \
    gosu \
    jq \
    less \
    vim-tiny \
    tree \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install Gitea
RUN curl -sL "https://dl.gitea.io/gitea/${GITEA_VERSION}/gitea-${GITEA_VERSION}-linux-${TARGETARCH}" -o /usr/local/bin/gitea \
    && chmod +x /usr/local/bin/gitea

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/ \
    && mv /root/.local/bin/uvx /usr/local/bin/

# Create non-root user for Gitea and workspace
RUN useradd -m -d /home/amplifier -s /bin/bash -U amplifier \
    && mkdir -p /var/lib/gitea /etc/gitea /workspace /snapshots \
    && chown -R amplifier:amplifier /var/lib/gitea /etc/gitea /workspace /snapshots /home/amplifier

# Copy Gitea config
COPY app.ini /etc/gitea/app.ini
RUN chown amplifier:amplifier /etc/gitea/app.ini

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Environment
ENV HOME=/home/amplifier
ENV GITEA_WORK_DIR=/var/lib/gitea
ENV USER=amplifier
# Include uv tool bin directory in PATH so installed tools are immediately usable
ENV PATH="/home/amplifier/.local/bin:${PATH}"
# Force uv to use git (respects our URL rewriting instead of GitHub API fast path)
ENV UV_NO_GITHUB_FAST_PATH=1

# SHADOW-011/012: Explicit Python path for Amplifier tools
# After `uv tool install amplifier`, Python with amplifier_core is at:
ENV AMPLIFIER_PYTHON=/home/amplifier/.local/share/uv/tools/amplifier/bin/python
# Note: System Python (/usr/local/bin/python3) does NOT have amplifier_core installed

# SHADOW-013: Create self-documentation file for container introspection
# This allows agents to quickly discover container configuration without guessing
RUN echo '{\
  "environment": "shadow",\
  "description": "Amplifier shadow environment for isolated testing",\
  "paths": {\
    "workspace": "/workspace",\
    "snapshots": "/snapshots",\
    "home": "/home/amplifier",\
    "gitea_data": "/var/lib/gitea",\
    "gitea_config": "/etc/gitea/app.ini"\
  },\
  "python": {\
    "system": "/usr/local/bin/python3",\
    "amplifier": "/home/amplifier/.local/share/uv/tools/amplifier/bin/python",\
    "note": "System Python does NOT have amplifier_core. Use AMPLIFIER_PYTHON or the amplifier path."\
  },\
  "services": {\
    "gitea": {\
      "url": "http://localhost:3000",\
      "api": "http://localhost:3000/api/v1",\
      "user": "shadow",\
      "password": "shadow"\
    }\
  },\
  "env_vars": {\
    "AMPLIFIER_PYTHON": "Path to Python with amplifier_core installed",\
    "UV_NO_GITHUB_FAST_PATH": "Forces uv to use git for URL rewriting"\
  },\
  "notes": [\
    "The shadow CLI tool is HOST-SIDE ONLY - it does not exist inside this container",\
    "Use amplifier CLI inside the container for testing",\
    "Local source repos are available via Gitea at http://localhost:3000"\
  ]\
}' > /etc/shadow-environment.json

# Run as amplifier user
USER amplifier
WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
