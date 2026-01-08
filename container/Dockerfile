FROM python:3.12-slim

ARG GITEA_VERSION=1.21.4
ARG TARGETARCH

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install Gitea
RUN curl -sL "https://dl.gitea.io/gitea/${GITEA_VERSION}/gitea-${GITEA_VERSION}-linux-${TARGETARCH}" -o /usr/local/bin/gitea \
    && chmod +x /usr/local/bin/gitea

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/ \
    && mv /root/.local/bin/uvx /usr/local/bin/

# Create directories
RUN mkdir -p /var/lib/gitea /etc/gitea /workspace /snapshots /home/shadow

# Copy Gitea config
COPY app.ini /etc/gitea/app.ini

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Environment
ENV HOME=/home/shadow
ENV GITEA_WORK_DIR=/var/lib/gitea
ENV USER=root

WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
