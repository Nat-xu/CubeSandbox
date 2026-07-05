# syntax=docker/dockerfile:1.7
#
# OpenCode AI coding agent inside a CubeSandbox template.
#
# The image installs Node.js 24 and the OpenCode CLI on top of the official
# CubeSandbox base image. The inherited cube-entrypoint keeps envd running on
# :49983 so Cube can use the standard readiness probe.
#
# Build:
#   docker build -t opencode-cube:latest examples/opencode-integration
#
# Register as a Cube template:
#   cubemastercli tpl create-from-image \
#     --image <your-registry>/opencode-cube:latest \
#     --writable-layer-size 4G \
#     --expose-port 49983 \
#     --probe       49983 \
#     --probe-path  /health

ARG CUBE_BASE_IMAGE=ghcr.io/tencentcloud/cubesandbox-base:2026.16
FROM ${CUBE_BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
ARG NODE_MAJOR=24
ARG OPENCODE_VERSION=1.17.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
        less \
        procps \
        python3 \
        python3-pip \
        ripgrep \
    && curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for agent commands executed via the SDK.  The container's
# entrypoint (envd) must remain root, so there is no USER directive here.
# Instead, the SDK driver (_common.py:run) passes user="agent" on every
# sandbox.commands.run call, so OpenCode and user-supplied commands run
# without root inside the guest.  KVM isolation protects the host, while
# this user provides defense-in-depth inside the VM.
RUN useradd --create-home --shell /bin/bash agent

# Install OpenCode in its own layer so a version bump only rebuilds this step.
RUN npm install -g --ignore-scripts "opencode-ai@${OPENCODE_VERSION}" \
    && opencode --version \
    && npm cache clean --force \
    && rm -rf /root/.npm

# OpenCode state directory ─ created at build time but carries no credentials.
ENV OPENCODE_CONFIG_DIR=/home/agent/.config/opencode

RUN mkdir -p /workspace "${OPENCODE_CONFIG_DIR}" \
    && printf '%s\n' \
        '{' \
        '  "provider": "openai",' \
        '  "model": "gpt-4.1"' \
        '}' \
        > "${OPENCODE_CONFIG_DIR}/opencode.json" \
    && chown -R agent:agent /workspace "${OPENCODE_CONFIG_DIR}"

WORKDIR /workspace

EXPOSE 49983
