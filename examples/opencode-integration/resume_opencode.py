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
import sys

from dotenv import load_dotenv
from e2b import Sandbox

from _common import (
    OPENCODE_CONFIG_DIR,
    WORKSPACE,
    CommandFailedError,
    MissingConfigError,
    build_opencode_cmd,
    cleanup_credentials,
    ensure_success,
    print_result,
    required,
    resolve_provider_key,
    run,
    safe_kill,
    sandbox_id,
    shell_join,
)

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

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
    cmd = shell_join(
        f"test -d {WORKSPACE}",
        f"test -d {OPENCODE_CONFIG_DIR}",
        "printf '\\n--- Workspace files (survived pause/resume) ---\\n'",
        f"ls -la {WORKSPACE}",
    )
    result = run(sandbox, cmd, timeout=60)
    ensure_success(result, "verify /workspace and OpenCode state survived pause/resume")
    stdout = getattr(result, "stdout", "")
    if stdout:
        print(stdout)


def _show_final_workspace(sandbox: Sandbox) -> None:
    """Print the workspace listing and progress.md (if it exists)."""
    cmd = shell_join(
        f"ls -la {WORKSPACE}",
        f"test ! -f {WORKSPACE}/progress.md || "
        f"(printf '\\n--- progress.md ---\\n' && cat {WORKSPACE}/progress.md)",
    )
    result = run(sandbox, cmd, timeout=60)
    ensure_success(result, "inspect final workspace")
    stdout = getattr(result, "stdout", "")
    if stdout:
        print(stdout)


def main() -> int:
    load_dotenv()

    try:
        args = parse_args()
        required("E2B_API_URL")
        required("E2B_API_KEY")
        llm_api_key = resolve_provider_key(args.provider)
    except MissingConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    prompt = args.prompt or TURN_2_PROMPT
    opencode_cmd = build_opencode_cmd(args.provider, prompt)

    sandbox_id_arg = args.sandbox_id
    print(f"Reconnecting to sandbox: {sandbox_id_arg}")
    # SECURITY: like run_opencode.py this demo keeps egress open and injects the
    # key per command. The pause() snapshot also captures any credentials cached
    # under /home/agent/.config/opencode, widening exposure — for shared clusters
    # prefer the default-deny + vault pattern (see docs/guide/security-proxy.md
    # and the pi-agent network_policy.py example).
    # Pre-initialize so the finally block is safe even when Sandbox.connect()
    # raises — without this, an uncaught exception would cause UnboundLocalError
    # in finally, shadowing the original error.
    sandbox = None
    sandbox = Sandbox.connect(sandbox_id=sandbox_id_arg)
    sid = sandbox_id(sandbox)

    try:
        print(f"Reconnected. Sandbox ID: {sid}")

        print("\n=== Verifying persistence after resume ===\n")
        _verify_state(sandbox)

        print("\n=== Turn 2: continue the work ===\n")
        result = run(
            sandbox,
            opencode_cmd,
            envs={f"{args.provider.upper()}_API_KEY": llm_api_key},
            timeout=args.exec_timeout,
        )

        # Wipe any credentials OpenCode may have cached in the resumed session.
        cleanup_credentials(sandbox)

        exit_code = print_result(result)

        print("\n--- /workspace final state ---")
        _show_final_workspace(sandbox)

        return exit_code

    except CommandFailedError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if sandbox is not None:
            safe_kill(sandbox)


if __name__ == "__main__":
    sys.exit(main())
