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

# Run as amplifier user
USER amplifier
WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
