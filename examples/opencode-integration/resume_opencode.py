#!/usr/bin/env python3
# Copyright (c) 2026 Tencent Inc.
# SPDX-License-Identifier: Apache-2.0

"""Demonstrate OpenCode session persistence across a CubeSandbox pause/resume.

Turn 1 (run by run_opencode.py) writes artifacts to /workspace and pauses the
sandbox.  This script reconnects to the paused sandbox, verifies /workspace and
the OpenCode config directory survived the snapshot, executes a second OpenCode
task that continues the work, and finally kills the sandbox.

Lifecycle note: this script deliberately avoids ``with Sandbox.create(...)``.
A context manager kills the sandbox on ``__exit__``, which would defeat the
pause.  The lifecycle is managed manually with try/finally.

Usage:
    python resume_opencode.py --sandbox-id <id-from-run_opencode.py>
    python resume_opencode.py --sandbox-id <id> --prompt "Finish the project"
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
# constants
# ---------------------------------------------------------------------------

WORKSPACE = "/workspace"
OPENCODE_CONFIG_DIR = "/root/.config/opencode"

TURN_2_PROMPT = (
    "Read /workspace/plan.md and implement step 1 by creating "
    "/workspace/progress.md that records which step you completed and why. "
    "Do not delete plan.md."
)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resume a paused OpenCode session in CubeSandbox."
    )
    parser.add_argument(
        "--sandbox-id",
        required=True,
        help="Sandbox ID returned by run_opencode.py after pause.",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="Prompt for turn 2. Defaults to continuing the plan from turn 1.",
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
    return parser.parse_args()


def _verify_state(sandbox: Sandbox) -> None:
    """Verify /workspace and the OpenCode config directory survived the snapshot."""
    cmd = _shell_join(
        f"test -d {WORKSPACE}",
        f"test -d {OPENCODE_CONFIG_DIR}",
        "printf '\\n--- Workspace files (survived pause/resume) ---\\n'",
        f"ls -la {WORKSPACE}",
    )
    result = _run(sandbox, cmd, timeout=60)
    _ensure_success(result, "verify /workspace and OpenCode state survived pause/resume")
    stdout = getattr(result, "stdout", "")
    if stdout:
        print(stdout)


def _show_final_workspace(sandbox: Sandbox) -> None:
    """Print the workspace listing and progress.md (if it exists)."""
    cmd = _shell_join(
        f"ls -la {WORKSPACE}",
        f"test ! -f {WORKSPACE}/progress.md || "
        f"(printf '\\n--- progress.md ---\\n' && cat {WORKSPACE}/progress.md)",
    )
    result = _run(sandbox, cmd, timeout=60)
    _ensure_success(result, "inspect final workspace")
    stdout = getattr(result, "stdout", "")
    if stdout:
        print(stdout)


def main() -> int:
    load_dotenv()
    args = parse_args()

    _required("E2B_API_URL")
    _required("E2B_API_KEY")

    provider = args.provider
    provider_key_env = f"{provider.upper()}_API_KEY"
    llm_api_key = os.environ.get(provider_key_env) or os.environ.get("OPENAI_API_KEY")
    if not llm_api_key:
        print(
            f"Missing LLM API key: set {provider_key_env} or OPENAI_API_KEY",
            file=sys.stderr,
        )
        sys.exit(1)

    prompt = args.prompt or TURN_2_PROMPT
    opencode_cmd = (
        f"cd {WORKSPACE} && "
        f"opencode --non-interactive --provider {shlex.quote(provider)} "
        f"--prompt {shlex.quote(prompt)}"
    )

    sandbox_id = args.sandbox_id
    print(f"Reconnecting to sandbox: {sandbox_id}")
    # SECURITY: like run_opencode.py this demo keeps egress open and injects the
    # key per command. The pause() snapshot also captures any credentials cached
    # under /root/.config/opencode, widening exposure — for shared clusters
    # prefer the default-deny + vault pattern (see docs/guide/security-proxy.md
    # and the pi-agent network_policy.py example).
    sandbox = Sandbox.connect(sandbox_id=sandbox_id)
    sid = _sandbox_id(sandbox)

    try:
        print(f"Reconnected. Sandbox ID: {sid}")

        print("\n=== Verifying persistence after resume ===\n")
        _verify_state(sandbox)

        print("\n=== Turn 2: continue the work ===\n")
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
        _show_final_workspace(sandbox)

        return 0 if exit_code is None else int(exit_code)
    finally:
        if sandbox is not None:
            try:
                sandbox.kill()
                print(f"\nSandbox {sid} killed.")
            except Exception as exc:  # noqa: BLE001
                print(
                    f"Warning: failed to kill sandbox {sid}: {exc}",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    sys.exit(main())
