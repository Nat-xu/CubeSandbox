---
title: OpenCode Integration Guide
author: Nat-xu
date: 2026-07-05
tags:
  - integration
  - opencode
  - coding-agent
  - agent
lang: en-US
---

# OpenCode Integration Guide

[中文文档](../../zh/guide/integrations/opencode.md)

Run [OpenCode](https://www.npmjs.com/package/opencode-ai) — an open-source
terminal AI coding agent — inside CubeSandbox MicroVMs. This guide covers image
build, key injection, and snapshot-based session persistence, and pairs with the
runnable
[`examples/opencode-integration`](https://github.com/TencentCloud/CubeSandbox/tree/master/examples/opencode-integration)
project.

## Integration Target and Version

| Component | Version |
|---|---|
| OpenCode | `opencode-ai` (installed via npm, pin a specific version in the Dockerfile if needed) |
| Node.js | 24 (installed via NodeSource) |
| CubeSandbox base image | `ghcr.io/tencentcloud/cubesandbox-base:2026.16` |
| E2B SDK (host driver) | `e2b` (latest) |
| CubeSandbox platform | `>= 0.3.0` (pause/resume) |

## Prerequisites

- A running CubeSandbox deployment; CubeAPI reachable at `http://<node>:8080`.
- `cubemastercli` on `$PATH`, connected to the cluster.
- Docker on the build workstation, plus a registry the Cube nodes can pull from.
- An LLM provider API key. OpenAI is the default; any provider supported by
  OpenCode (Anthropic, Google, etc.) works by passing `--provider <name>`.
- Python 3.9+ for the host driver scripts.

## Why Run OpenCode Inside a Sandbox

OpenCode is a terminal agent that edits files, runs commands, and installs
packages. Running it directly on a workstation blends the agent's blast radius
with your dev environment. Running it inside CubeSandbox gives you:

| Concern | CubeSandbox provides |
|---|---|
| **Isolation** | KVM MicroVM per session, dedicated guest kernel |
| **Reproducibility** | Every session boots from the same template snapshot |
| **Fast spin-up** | Sub-60 ms cold start, so N-parallel agents are cheap |
| **Long tasks** | `sandbox.pause()` snapshots VM + rootfs; resume later |
| **Key hygiene** | CubeEgress injects the auth header on the wire — the VM never sees the real key |
| **Egress audit** | Every request to the LLM API is recorded in the egress audit log |

## Integration Steps

### 1. Build the template image

The image stacks Node.js 24 and the OpenCode CLI on top of `cubesandbox-base`,
so envd is already listening on `:49983`.

```dockerfile
# examples/opencode-integration/Dockerfile (excerpt)
ARG CUBE_BASE_IMAGE=ghcr.io/tencentcloud/cubesandbox-base:2026.16
FROM ${CUBE_BASE_IMAGE}

ARG NODE_MAJOR=24
ARG OPENCODE_VERSION=1.17.0

# OS packages + Node.js (first layer)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git gnupg jq less procps python3 python3-pip ripgrep \
    && curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for defense-in-depth inside the guest
RUN useradd --create-home --shell /bin/bash agent

# OpenCode CLI ─ pinned version in its own layer (second layer)
RUN npm install -g --ignore-scripts "opencode-ai@${OPENCODE_VERSION}" \
    && opencode --version \
    && npm cache clean --force \
    && rm -rf /root/.npm

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
```

Build and push:

```bash
docker build --platform linux/amd64 \
  -t <your-registry>/opencode-cube:latest \
  examples/opencode-integration
docker push <your-registry>/opencode-cube:latest
```

### 2. Register as a Cube template

```bash
cubemastercli tpl create-from-image \
  --image <your-registry>/opencode-cube:latest \
  --writable-layer-size 4G \
  --expose-port 49983 \
  --probe       49983 \
  --probe-path  /health

cubemastercli tpl watch --job-id <job_id>
```

Once the job reaches `READY`, note the `template_id` — you pass it to every
`Sandbox.create()` call. `4G` writable layer suits medium tasks; bump to `8G+`
if the agent installs large toolchains.

### 3. Wire up the host driver

```bash
cd examples/opencode-integration
cp .env.example .env
# fill in E2B_API_URL, CUBE_TEMPLATE_ID, and your provider key
pip install -r requirements.txt
```

| Variable | Where it flows | Notes |
|---|---|---|
| `E2B_API_URL` | Local process | CubeAPI address (`http://<node>:8080`) |
| `E2B_API_KEY` | Local process | Any non-empty string in local dev |
| `CUBE_TEMPLATE_ID` | `Sandbox.create(template=...)` | From step 2 |
| `OPENAI_API_KEY` | `envs=...` (per-command injection) | Provider key for OpenAI; use `ANTHROPIC_API_KEY` for Anthropic, etc. |
| `OPENCODE_PROVIDER` | OpenCode CLI `--provider` flag | Override the default provider in `opencode.json` |

### 4. Runtime Configuration and API Key Injection

OpenCode is invoked in non-interactive mode with `--non-interactive`, an
explicit `--provider`, and a `--prompt` positional argument:

```python
result = sandbox.commands.run(
    "cd /workspace && opencode --non-interactive --provider openai "
    "--prompt 'Create hello.py that prints Hello from CubeSandbox and run it.'",
    envs={"OPENAI_API_KEY": key},
    user="agent",
    timeout=900,
)
```

`e2b`'s `commands.run(envs=...)` puts the environment into the exec envelope,
not into a persistent file inside the VM, so the key lives only for the
lifetime of that command.

> **Security:** this direct-key flavor keeps egress open by default for
> simplicity. For shared/production clusters, use the CubeEgress credential
> vault with default-deny egress (see the pi-agent `network_policy.py` example
> for the pattern). The vault injects the API key as an HTTP header on the wire
> — the VM never sees the real key, and `printenv` inside the sandbox shows
> only a placeholder.

### 5. Session Persistence (pause / resume)

```bash
python resume_opencode.py --sandbox-id <id-from-run_opencode.py>
```

This mirrors the [snapshot / clone / rollback](../snapshot-rollback-clone.md)
engine at the SDK layer:

- `sandbox.pause()` snapshots the running VM (memory + rootfs) and frees compute.
- `Sandbox.connect(sandbox_id)` resumes with `/workspace`, OpenCode's config
  directory (`/home/agent/.config/opencode`), and every other file intact.

> **Lifecycle caveat:** manage the sandbox lifecycle with `try/finally`, not a
> `with Sandbox.create(...)` context manager. On `__exit__` the context manager
> kills the sandbox, which would undo the pause. The example creates the sandbox
> explicitly and only calls `sandbox.kill()` in `finally`.

```python
sandbox = Sandbox.create(template=template_id, timeout=1800)
try:
    run_turn(sandbox, prompt_1)          # writes /workspace/plan.md
    sandbox_id = sandbox.pause() or sandbox.sandbox_id
    sandbox = Sandbox.connect(sandbox_id)
    verify_state_survived(sandbox)       # /workspace + /home/agent/.config/opencode intact
    run_turn(sandbox, prompt_2)          # continues the work
finally:
    sandbox.kill()
```

## Use Cases and Best Practices

- **Isolated development.** Run the coding agent inside the sandbox so its file
  edits and shell commands cannot touch the host.
- **Execute agent-generated code and collect results.** Have the agent write to
  `/workspace`, then read artifacts back via `sandbox.files` or `commands.run`.
- **Checkpoint / resume long tasks.** Use `pause()` + `connect()` to snapshot a
  long refactor and resume later, or fork multiple task variants off one snapshot.
- **Preinstall heavy dependencies** into the template rather than fetching them
  at runtime, especially under a default-deny egress policy.

## Key Code Snippets

### Non-interactive OpenCode invocation

```python
cmd = (
    "cd /workspace && opencode --non-interactive --provider openai "
    "--prompt 'Inspect the project, run app.py, and summarize the result.'"
)
result = sandbox.commands.run(cmd, envs={"OPENAI_API_KEY": key}, user="agent", timeout=900)
```

### Preflight version check

```python
version = sandbox.commands.run("opencode --version", timeout=60)
```

### Seed a demo project into the sandbox

```python
sandbox.commands.run("""
cat > /workspace/app.py <<'EOF'
def main() -> None:
    print("hello from CubeSandbox + OpenCode")

if __name__ == "__main__":
    main()
EOF
""", user="agent", timeout=60)
```

## Caveats

- **Node.js version.** OpenCode needs a recent Node runtime; the base image
  ships an older apt Node, so always install via NodeSource (the Dockerfile
  does this).
- **Agent config directory.** `/home/agent/.config/opencode` holds OpenCode's
  configuration and session state. Keep it empty of credentials in the image;
  the Dockerfile creates a minimal `opencode.json` with only the default
  provider and model.
- **Direct-flavor key persistence.** With the direct flavor (`envs=`) the key is
  scoped to the exec call, but OpenCode may cache provider credentials under its
  config dir (`/home/agent/.config/opencode/`), which survives `pause()` /
  `resume()`. For strict isolation prefer the CubeEgress vault pattern, where
  the key never enters the VM.
- **Egress side-effects.** Tasks that `npm install` or fetch MCP tools need
  those hosts allowed or preinstalled into the template.
- **Interactive TTY features.** The OpenCode TUI is not available over the E2B
  protocol. Use `--non-interactive` mode and drive multi-turn conversations
  from the host script.
- **Provider compatibility.** OpenCode supports multiple LLM providers
  (OpenAI, Anthropic, Google, etc.). Ensure the matching `*_API_KEY` env var
  is set and passed via `envs=` for each invocation. Override the default
  provider at runtime with `--provider <name>`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `opencode: command not found` in preflight | Template not rebuilt after CLI change | Rebuild the image, re-register the template |
| Provider auth failure | Key not forwarded (direct) or missing inject rule (vault) | Pass `envs={...}` or fix the rule's `sni`/`host` |
| `403 Forbidden - CubeEgress` | Default-deny with no matching allow rule | Add the LLM host (and any extra hosts) to the rules |
| `Connection error` / TLS failure from OpenCode (vault) | OpenCode runs on Node, which ignores the system CA store and won't trust the CubeEgress CA | Set `NODE_EXTRA_CA_CERTS` to the system bundle path containing the CubeEgress CA |
| Template creation stuck in `PULLING` | Registry unreachable from Cube nodes | Push to a registry the cluster can reach; supply auth if needed |
| Readiness probe timeout | Base image without envd | Ensure `FROM ghcr.io/tencentcloud/cubesandbox-base:2026.16` |
| `pause()` / `connect()` errors | Platform too old for snapshots | Upgrade the CubeSandbox platform |
| OpenCode hangs or times out | Prompt too large or agent stuck in a loop | Reduce prompt size or lower `--exec-timeout`; check stderr for hints |

## References

- Runnable example: [`examples/opencode-integration`](https://github.com/TencentCloud/CubeSandbox/tree/master/examples/opencode-integration)
- Bring Your Own Image: [`docs/guide/tutorials/bring-your-own-image.md`](../tutorials/bring-your-own-image.md)
- Template from image: [`docs/guide/tutorials/template-from-image.md`](../tutorials/template-from-image.md)
- Snapshot / Clone / Rollback: [`docs/guide/snapshot-rollback-clone.md`](../snapshot-rollback-clone.md)
- Credential vault + egress control: [`docs/guide/security-proxy.md`](../security-proxy.md)
- Pi Agent `network_policy.py` (vault pattern reference): [`examples/pi-agent-integration/network_policy.py`](https://github.com/TencentCloud/CubeSandbox/tree/master/examples/pi-agent-integration)
- OpenCode: <https://www.npmjs.com/package/opencode-ai>
