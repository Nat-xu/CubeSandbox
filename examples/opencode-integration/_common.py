# Copyright (c) 2026 Tencent Inc.
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for the OpenCode integration example scripts."""

from __future__ import annotations

import os
import sys

from e2b import Sandbox

# OpenCode config directory inside the sandbox.
OPENCODE_CONFIG_DIR = "/home/agent/.config/opencode"


def required(name: str) -> str:
    """Return the value of *name* from the environment, or exit if unset/empty."""
    value = os.environ.get(name, "")
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def shell_join(*commands: str) -> str:
    """Join shell commands with ``&&``."""
    return " && ".join(commands)


def run(sandbox: Sandbox, cmd: str, **kwargs):
    """Run *cmd* in the sandbox and return the result object."""
    return sandbox.commands.run(cmd, user="agent", **kwargs)


def ensure_success(result, label: str) -> None:
    """Exit if *result* has a non-zero exit code.

    When *exit_code* is ``None`` (e.g. timeout or SDK error), treat it as a
    failure so the caller does not silently proceed with a broken flow.
    """
    exit_code = getattr(result, "exit_code", None)
    if exit_code is None:
        print(f"Error in {label}: no exit code (command may have timed out or failed)", file=sys.stderr)
        sys.exit(1)
    if exit_code != 0:
        stderr = getattr(result, "stderr", "")
        print(f"Error in {label} (exit {exit_code}): {stderr}", file=sys.stderr)
        sys.exit(1)


def sandbox_id(sandbox: Sandbox) -> str:
    """Return a stable identifier string for *sandbox*."""
    sid = getattr(sandbox, "sandbox_id", None)
    return str(sid) if sid else "unknown"


def cleanup_credentials(sandbox: Sandbox) -> None:
    """Remove cached credentials from the OpenCode config directory.

    OpenCode may cache provider API keys under its config directory during
    execution.  When ``sandbox.pause()`` snapshots the VM these cached keys
    persist in the snapshot and would be recoverable by anyone who resumes the
    sandbox.  This helper wipes known cache paths so the snapshot is clean.
    """
    cmd = shell_join(
        f"rm -rf {OPENCODE_CONFIG_DIR}/credentials*",
        f"rm -rf {OPENCODE_CONFIG_DIR}/sessions/*/credentials*",
    )
    try:
        sandbox.commands.run(cmd, user="agent", timeout=30)
    except Exception:
        # Best-effort cleanup — never fail the script over cache removal.
        pass


def resolve_provider_key(provider: str) -> str:
    """Return the API key for *provider*, or exit if not set.

    Looks up ``<PROVIDER>_API_KEY`` (e.g. ``OPENAI_API_KEY``).  Does **not**
    fall back to ``OPENAI_API_KEY`` for other providers — that would silently
    send an OpenAI key to a different provider's endpoint.
    """
    env_var = f"{provider.upper()}_API_KEY"
    key = os.environ.get(env_var, "")
    if not key:
        print(f"Missing LLM API key: set {env_var}", file=sys.stderr)
        sys.exit(1)
    return key
