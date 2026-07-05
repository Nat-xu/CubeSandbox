#!/usr/bin/env python3
# Copyright (c) 2026 Tencent Inc.
# SPDX-License-Identifier: Apache-2.0

"""Run a one-shot OpenCode coding-agent task inside CubeSandbox.

Creates a sandbox, seeds a demo project into /workspace, executes OpenCode in
non-interactive mode, prints the results, and pauses the sandbox so it can be
resumed later with resume_opencode.py.

Usage:
    python run_opencode.py
    python run_opencode.py --prompt "Create hello.py and run it"
    python run_opencode.py --no-seed --prompt "Fix the bugs in /workspace"
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys

from dotenv import load_dotenv
from e2b import Sandbox

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def _shell_join(*commands: str) -> str:
    return " && ".join(commands)


def _run(sandbox: Sandbox, cmd: str, **kwargs):
    """Run a command in the sandbox and return the result object."""
    return sandbox.commands.run(cmd, user="root", **kwargs)


def _ensure_success(result, label: str) -> None:
    exit_code = getattr(result, "exit_code", None)
    if exit_code is not None and exit_code != 0:
        stderr = getattr(result, "stderr", "")
        print(f"Error in {label} (exit {exit_code}): {stderr}", file=sys.stderr)
        sys.exit(1)


def _sandbox_id(sandbox: Sandbox) -> str:
    sid = getattr(sandbox, "sandbox_id", None)
    return str(sid) if sid else "unknown"


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------

DEFAULT_PROMPT = (
    "Inspect the project in /workspace, run python3 app.py, and write a "
    "concise summary of the result to /workspace/result.md."
)

WORKSPACE = "/workspace"


def _seed_project(sandbox: Sandbox) -> None:
    """Write a minimal Python project into the sandbox workspace."""
    cmd = rf"""mkdir -p {WORKSPACE}
cat > {WORKSPACE}/README.md <<'EOF'
# CubeSandbox OpenCode Smoke Project

This tiny project exists so the OpenCode agent has a deterministic task to run.
EOF
cat > {WORKSPACE}/app.py <<'EOF'
def main() -> None:
    print("hello from CubeSandbox + OpenCode")


if __name__ == "__main__":
    main()
EOF
"""
    result = _run(sandbox, cmd, timeout=60)
    _ensure_success(result, "seed workspace")


def _show_workspace(sandbox: Sandbox) -> None:
    """Print the workspace listing and result.md (if it exists)."""
    cmd = _shell_join(
        f"ls -la {WORKSPACE}",
        f"test ! -f {WORKSPACE}/result.md || "
        f"(printf '\\n--- result.md ---\\n' && cat {WORKSPACE}/result.md)",
    )
    result = _run(sandbox, cmd, timeout=60)
    _ensure_success(result, "inspect workspace")
    stdout = getattr(result, "stdout", "")
    if stdout:
        print(stdout)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a one-shot OpenCode task inside CubeSandbox."
    )
    parser.add_argument(
        "--template",
        default=os.environ.get("CUBE_TEMPLATE_ID"),
        help="CubeSandbox template ID. Defaults to CUBE_TEMPLATE_ID env var.",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="Prompt passed to OpenCode. Defaults to a small workspace smoke task.",
    )
    parser.add_argument(
        "--sandbox-timeout",
        type=int,
        default=int(os.environ.get("OPENCODE_SANDBOX_TIMEOUT", "1800")),
        help="Sandbox lifetime in seconds. Default: 1800.",
    )
    parser.add_argument(
        "--exec-timeout",
        type=int,
        default=int(os.environ.get("OPENCODE_EXEC_TIMEOUT", "900")),
        help="OpenCode command timeout in seconds. Default: 900.",
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("OPENCODE_PROVIDER", "openai"),
        help="LLM provider for OpenCode. Default: openai.",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Skip writing demo project files into the workspace.",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    template_id = args.template or _required("CUBE_TEMPLATE_ID")
    _required("E2B_API_URL")
    _required("E2B_API_KEY")

    # Resolve the provider key — prefer an env var matching the provider, but
    # also fall back to OPENAI_API_KEY for the most common path.
    provider = args.provider
    provider_key_env = f"{provider.upper()}_API_KEY"
    llm_api_key = os.environ.get(provider_key_env) or os.environ.get("OPENAI_API_KEY")
    if not llm_api_key:
        print(
            f"Missing LLM API key: set {provider_key_env} or OPENAI_API_KEY",
            file=sys.stderr,
        )
        sys.exit(1)

    prompt = args.prompt or DEFAULT_PROMPT
    opencode_cmd = (
        f"cd {WORKSPACE} && "
        f"opencode --non-interactive --provider {shlex.quote(provider)} "
        f"--prompt {shlex.quote(prompt)}"
    )

    print(f"Creating sandbox from template: {template_id}")
    result = None
    # SECURITY: this direct-key demo keeps egress open (allow_internet_access
    # defaults to True) for simplicity, and injects the provider key per command
    # via envs=. A compromised agent with open egress could exfiltrate that key.
    # For shared/production use, pair default-deny egress with the CubeEgress
    # credential vault (see docs/guide/security-proxy.md and the pi-agent
    # network_policy.py example).
    with Sandbox.create(template=template_id, timeout=args.sandbox_timeout) as sandbox:
        sid = _sandbox_id(sandbox)
        print(f"Sandbox ready: {sid}")

        # Preflight: verify OpenCode is installed
        version_result = _run(sandbox, "opencode --version", timeout=60)
        _ensure_success(version_result, "check OpenCode version")
        print(f"OpenCode version: {getattr(version_result, 'stdout', '').strip()}")

        if not args.no_seed:
            _seed_project(sandbox)
            print(f"Seeded demo project in {WORKSPACE}")

        print("\nRunning OpenCode task...\n")
        result = _run(
            sandbox,
            opencode_cmd,
            envs={f"{provider.upper()}_API_KEY": llm_api_key},
            timeout=args.exec_timeout,
        )

        # Print results
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
        exit_code = getattr(result, "exit_code", None)

        if stdout:
            print(stdout)
        if stderr:
            print(stderr, file=sys.stderr)

        print(f"\nOpenCode exit code: {exit_code}")

        print("\n--- /workspace final state ---")
        _show_workspace(sandbox)

        # Pause the sandbox (snapshot VM + rootfs) so it can be resumed later
        print(f"\nPausing sandbox {sid} (snapshotting VM + rootfs)...")
        paused_id = sandbox.pause()
        if isinstance(paused_id, str) and paused_id:
            sid = paused_id
        print(f"Sandbox paused. Resume with: python resume_opencode.py --sandbox-id {sid}")

    return 0 if exit_code is None else int(exit_code)


if __name__ == "__main__":
    sys.exit(main())
