# OpenCode + CubeSandbox Example

[中文文档](README_zh.md)

Run [OpenCode](https://www.npmjs.com/package/opencode-ai) — an open-source
terminal AI coding agent — inside a CubeSandbox MicroVM. The agent edits files,
runs commands, and reaches an LLM API entirely within an isolated, reproducible
sandbox.

This example ships:

- A `Dockerfile` that stacks Node.js + the OpenCode CLI on top of the
  CubeSandbox base image (envd already listens on `:49983`).
- `run_opencode.py` — a headless one-shot run inside `/workspace`.
- `resume_opencode.py` — pause/resume across two turns, proving `/workspace` and
  OpenCode's config directory survive the snapshot.
- `.env.example`, `requirements.txt`.

## Directory layout

```
opencode-integration/
├── Dockerfile            # CubeSandbox template image (Node.js + OpenCode CLI)
├── .env.example          # Copy to .env and fill in
├── requirements.txt      # Host driver deps (e2b, python-dotenv)
├── _common.py            # Shared helpers (sandbox ops, key resolution, cleanup)
├── run_opencode.py       # One-shot OpenCode task
├── resume_opencode.py    # Pause / resume session persistence
├── README.md             # English docs (this file)
└── README_zh.md          # Chinese docs
```

## Prerequisites

- A running CubeSandbox deployment; CubeAPI reachable at `http://<node>:8080`.
- `cubemastercli` on `$PATH`, connected to the cluster.
- Docker on the build workstation, plus a registry the Cube nodes can pull from.
- An LLM provider API key (OpenAI by default; any provider OpenCode supports).
- Python 3.9+ for the host driver scripts.

## 1. Build the template image

```bash
docker build --platform linux/amd64 \
  -t <your-registry>/opencode-cube:latest \
  examples/opencode-integration
docker push <your-registry>/opencode-cube:latest
```

The image installs `opencode-ai` (pinned via `OPENCODE_VERSION` build arg,
default `1.17.0`; bump the ARG in the Dockerfile to upgrade), plus `git`,
`python3`, `ripgrep`, `jq`, and cleans apt/npm caches.

## 2. Register as a Cube template

```bash
cubemastercli tpl create-from-image \
  --image <your-registry>/opencode-cube:latest \
  --writable-layer-size 4G \
  --expose-port 49983 \
  --probe       49983 \
  --probe-path  /health

cubemastercli tpl watch --job-id <job_id>
```

Note the `template_id` once the job reaches `READY`.

## 3. Configure the host driver

```bash
cd examples/opencode-integration
cp .env.example .env
# fill in E2B_API_URL, E2B_API_KEY, CUBE_TEMPLATE_ID, and your provider key
pip install -r requirements.txt
```

| Variable | Where it flows | Notes |
|---|---|---|
| `E2B_API_URL` | Local process | CubeAPI address (`http://<node>:8080`) |
| `E2B_API_KEY` | Local process | Any non-empty string in local dev |
| `CUBE_TEMPLATE_ID` | `Sandbox.create(template=...)` | From step 2 |
| `OPENAI_API_KEY` | `envs=...` (per-command injection) | Provider key, scoped to the exec call |
| `OPENCODE_PROVIDER` | OpenCode CLI `--provider` flag | `openai` (default), `anthropic`, etc. |

## 4. One-shot run

```bash
python run_opencode.py --prompt "Create hello.py that prints 'Hello from CubeSandbox' and run it."
```

The key is forwarded per-command via `sandbox.commands.run(..., envs=...)` — it
lives only for the lifetime of that exec call and is never written to a
persistent file inside the VM.

> **Security:** this demo keeps egress open by default, so a compromised agent
> could exfiltrate the injected key. For shared clusters, use the CubeEgress
> credential vault with default-deny egress (see the pi-agent
> `network_policy.py` example for the pattern).

The script prints OpenCode's stdout/stderr, the exit code, and the final
`/workspace` listing. At the end it pauses the sandbox and prints the sandbox
ID for later resume.

## 5. Pause / resume (session persistence)

```bash
python resume_opencode.py --sandbox-id <id-from-run_opencode.py>
```

Turn 1 (run by `run_opencode.py`) writes artifacts to `/workspace` and calls
`sandbox.pause()`. This script reconnects with `Sandbox.connect(sandbox_id)`,
verifies `/workspace` and the OpenCode config directory (`/home/agent/.config/opencode`)
survived the snapshot, then runs turn 2 to continue the work. The sandbox
lifecycle is managed manually with `try/finally` (not a context manager), so the
pause is not undone by an early `kill`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `opencode: command not found` in preflight | Template not rebuilt after CLI change | Rebuild the image, re-register the template |
| Auth error from the provider | Key not forwarded | Ensure the correct `*_API_KEY` env var is set and passed via `envs=` |
| `403 Forbidden - CubeEgress` | Default-deny with no matching allow rule | Add the LLM host to the egress rules, or keep egress open for dev |
| `Connection error` / TLS failure from OpenCode | Node runtime ignores system CA store under egress interception | Set `NODE_EXTRA_CA_CERTS` to the system CA bundle path |
| Template creation stuck in `PULLING` | Registry unreachable from Cube nodes | Push to a registry the cluster can reach; supply auth if needed |
| Readiness probe timeout | Image without envd | Ensure `FROM ghcr.io/tencentcloud/cubesandbox-base:...` |
| `pause()` / `connect()` errors | Platform too old for snapshots | Upgrade the CubeSandbox platform |

## References

- Integration guide: [`docs/guide/integrations/opencode.md`](../../docs/guide/integrations/opencode.md)
- Snapshot / Clone / Rollback: [`docs/guide/snapshot-rollback-clone.md`](../../docs/guide/snapshot-rollback-clone.md)
- Network / egress policy examples: [`examples/network-policy`](../network-policy)
- OpenCode: <https://www.npmjs.com/package/opencode-ai>
- CubeEgress credential vault: [`docs/guide/security-proxy.md`](../../docs/guide/security-proxy.md)
