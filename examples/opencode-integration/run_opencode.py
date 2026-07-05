#!/usr/bin/env python3
# Copyright (c) 2026 Tencent Inc.
# SPDX-License-Identifier: Apache-2.0

"""Run a one-shot OpenCode coding-agent task inside CubeSandbox.

Creates a sandbox, seeds a demo project into /workspace, executes OpenCode in
non-interactive mode, prints the results, and pauses the sandbox so it can be
resumed later with resume_opencode.py.

Lifecycle note: this script deliberately avoids ``with Sandbox.create(...)``.
A context manager kills the sandbox on ``__exit__``, which would destroy the
sandbox that was just paused.  The lifecycle is managed manually with
try/finally — we only kill when something fails *before* the pause succeeds.

Usage:
    python run_opencode.py
    python run_opencode.py --prompt "Create hello.py and run it"
    python run_opencode.py --no-seed --prompt "Fix the bugs in /workspace"
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv
from e2b import Sandbox

from _common import (
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
# defaults
# ---------------------------------------------------------------------------

DEFAULT_PROMPT = (
    "Inspect the project in /workspace, run python3 app.py, and write a "
    "concise summary of the result to /workspace/result.md."
)


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
    result = run(sandbox, cmd, timeout=60)
    ensure_success(result, "seed workspace")


def _show_workspace(sandbox: Sandbox) -> None:
    """Print the workspace listing and result.md (if it exists)."""
    cmd = shell_join(
        f"ls -la {WORKSPACE}",
        f"test ! -f {WORKSPACE}/result.md || "
        f"(printf '\\n--- result.md ---\\n' && cat {WORKSPACE}/result.md)",
    )
    result = run(sandbox, cmd, timeout=60)
    ensure_success(result, "inspect workspace")
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

    try:
        args = parse_args()
        template_id = args.template or required("CUBE_TEMPLATE_ID")
        required("E2B_API_URL")
        required("E2B_API_KEY")
        llm_api_key = resolve_provider_key(args.provider)
    except MissingConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    prompt = args.prompt or DEFAULT_PROMPT
    opencode_cmd = build_opencode_cmd(args.provider, prompt)

    print(f"Creating sandbox from template: {template_id}")
    # SECURITY: this direct-key demo keeps egress open (allow_internet_access
    # defaults to True) for simplicity, and injects the provider key per command
    # via envs=. A compromised agent with open egress could exfiltrate that key.
    # For shared/production use, pair default-deny egress with the CubeEgress
    # credential vault (see docs/guide/security-proxy.md and the pi-agent
    # network_policy.py example).
    # Pre-initialize so the finally block is safe even when Sandbox.create()
    # raises — without this, an uncaught exception would cause UnboundLocalError
    # in finally, shadowing the original error.
    sandbox = None
    paused = False
    sandbox = Sandbox.create(template=template_id, timeout=args.sandbox_timeout)
    sid = sandbox_id(sandbox)

    try:
        print(f"Sandbox ready: {sid}")

        # Preflight: verify OpenCode is installed
        version_result = run(sandbox, "opencode --version", timeout=60)
        ensure_success(version_result, "check OpenCode version")
        print(f"OpenCode version: {getattr(version_result, 'stdout', '').strip()}")

        if not args.no_seed:
            _seed_project(sandbox)
            print(f"Seeded demo project in {WORKSPACE}")

        print("\nRunning OpenCode task...\n")
        result = run(
            sandbox,
            opencode_cmd,
            envs={f"{args.provider.upper()}_API_KEY": llm_api_key},
            timeout=args.exec_timeout,
        )

        # Wipe any credentials OpenCode may have cached before snapshotting.
        cleanup_credentials(sandbox)

        exit_code = print_result(result)

        print("\n--- /workspace final state ---")
        _show_workspace(sandbox)

        # Pause the sandbox (snapshot VM + rootfs) so it can be resumed later
        print(f"\nPausing sandbox {sid} (snapshotting VM + rootfs)...")
        paused_id = sandbox.pause()

        if not isinstance(paused_id, str) or not paused_id:
            print(
                f"Error: sandbox.pause() returned {paused_id!r} (expected a non-empty str). "
                "The sandbox may not be resumable.",
                file=sys.stderr,
            )
            return 1

        sid = paused_id
        paused = True
        print(f"Sandbox paused. Resume with: python resume_opencode.py --sandbox-id {sid}")

        return exit_code

    except CommandFailedError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if not paused and sandbox is not None:
            safe_kill(sandbox)


if __name__ == "__main__":
    sys.exit(main())
