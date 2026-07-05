# Copyright (c) 2026 Tencent Inc.
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for the OpenCode integration example scripts."""

from __future__ import annotations

import os
import sys
import traceback

from e2b import Sandbox

# OpenCode config directory inside the sandbox.
OPENCODE_CONFIG_DIR = "/home/agent/.config/opencode"

WORKSPACE = "/workspace"


# ---------------------------------------------------------------------------
# custom exceptions (raised by library functions so callers can test & handle)
# ---------------------------------------------------------------------------


class MissingConfigError(Exception):
    """A required environment variable or configuration value is missing."""


class CommandFailedError(Exception):
    """A sandbox command returned a non-zero exit code or no exit code at all."""


# ---------------------------------------------------------------------------
# configuration & validation
# ---------------------------------------------------------------------------


def required(name: str) -> str:
    """Return the value of *name* from the environment.

    Raises:
        MissingConfigError: if the variable is unset or empty.
    """
    value = os.environ.get(name, "")
    if not value:
        raise MissingConfigError(f"Missing required environment variable: {name}")
    return value


def resolve_provider_key(provider: str) -> str:
    """Return the API key for *provider*.

    Looks up ``<PROVIDER>_API_KEY`` (e.g. ``OPENAI_API_KEY``).  Does **not**
    fall back to ``OPENAI_API_KEY`` for other providers — that would silently
    send an OpenAI key to a different provider's endpoint.

    Raises:
        MissingConfigError: if the matching environment variable is unset or empty.
    """
    env_var = f"{provider.upper()}_API_KEY"
    key = os.environ.get(env_var, "")
    if not key:
        raise MissingConfigError(f"Missing LLM API key: set {env_var}")
    return key


# ---------------------------------------------------------------------------
# sandbox helpers
# ---------------------------------------------------------------------------


def shell_join(*commands: str) -> str:
    """Join shell commands with ``&&``."""
    return " && ".join(commands)


def run(sandbox: Sandbox, cmd: str, **kwargs):
    """Run *cmd* in the sandbox and return the result object."""
    return sandbox.commands.run(cmd, user="agent", **kwargs)


def sandbox_id(sandbox: Sandbox) -> str:
    """Return a stable identifier string for *sandbox*."""
    sid = getattr(sandbox, "sandbox_id", None)
    return str(sid) if sid else "unknown"


def safe_kill(sandbox: Sandbox | None) -> None:
    """Kill *sandbox*, logging any failure to stderr instead of raising.

    Safe to call with ``None`` (no-op).  Intended for use in ``finally`` blocks.
    """
    if sandbox is None:
        return
    try:
        sandbox.kill()
    except Exception:
        print(
            f"Warning: failed to kill sandbox {sandbox_id(sandbox)}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)


# ---------------------------------------------------------------------------
# command validation
# ---------------------------------------------------------------------------


def ensure_success(result, label: str) -> None:
    """Raise if *result* indicates a failed or unverifiable command.

    When *exit_code* is ``None`` (e.g. timeout or SDK error), treat it as a
    failure so the caller does not silently proceed with a broken flow.

    Raises:
        CommandFailedError: if exit_code is ``None`` or non-zero.
    """
    exit_code = getattr(result, "exit_code", None)
    if exit_code is None:
        raise CommandFailedError(
            f"Error in {label}: no exit code (command may have timed out or failed)"
        )
    if exit_code != 0:
        stderr = getattr(result, "stderr", "")
        raise CommandFailedError(f"Error in {label} (exit {exit_code}): {stderr}")


# ---------------------------------------------------------------------------
# OpenCode command builders
# ---------------------------------------------------------------------------


def build_opencode_cmd(provider: str, prompt: str, workspace: str = WORKSPACE) -> str:
    """Return a shell command string that invokes OpenCode non-interactively."""
    import shlex

    return (
        f"cd {shlex.quote(workspace)} && "
        f"opencode --non-interactive --provider {shlex.quote(provider)} "
        f"--prompt {shlex.quote(prompt)}"
    )


def print_result(result) -> int:
    """Print stdout, stderr and exit code from *result*.  Returns the exit code.

    When ``exit_code`` is ``None`` (the SDK field is missing), a diagnostic
    message is printed and the return value is -1 so callers can detect the
    anomaly.
    """
    stdout = getattr(result, "stdout", "")
    stderr = getattr(result, "stderr", "")
    exit_code = getattr(result, "exit_code", None)

    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)

    if exit_code is None:
        print("\nOpenCode exit code: unavailable (SDK may have dropped the field)", file=sys.stderr)
        return -1

    print(f"\nOpenCode exit code: {exit_code}")
    return int(exit_code)


# ---------------------------------------------------------------------------
# credential cache cleanup
# ---------------------------------------------------------------------------


def cleanup_credentials(sandbox: Sandbox) -> None:
    """Remove cached credentials from the OpenCode config directory.

    OpenCode may cache provider API keys under its config directory during
    execution.  When ``sandbox.pause()`` snapshots the VM these cached keys
    persist in the snapshot and would be recoverable by anyone who resumes the
    sandbox.  This helper wipes known cache paths so the snapshot is clean.

    Failures are logged to stderr (including a full traceback) so operators
    are aware that credentials may be present in the snapshot.
    """
    paths = [
        f"{OPENCODE_CONFIG_DIR}/credentials*",
        f"{OPENCODE_CONFIG_DIR}/sessions/*/credentials*",
    ]
    rm_cmd = shell_join(*(f"rm -rf {p}" for p in paths))
    verify_cmd = shell_join(*(f"test ! -e {p} || (echo 'STALE: {p}' && exit 1)" for p in paths))

    try:
        result = sandbox.commands.run(rm_cmd, user="agent", timeout=30)
        exit_code = getattr(result, "exit_code", None)
        if exit_code is not None and exit_code != 0:
            stderr = getattr(result, "stderr", "")
            print(f"Credential cleanup failed (exit {exit_code}): {stderr}", file=sys.stderr)
    except Exception:
        print("Credential cleanup raised an exception:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

    # Verify the files are actually gone.
    try:
        result = sandbox.commands.run(verify_cmd, user="agent", timeout=30)
        exit_code = getattr(result, "exit_code", None)
        if exit_code is not None and exit_code != 0:
            stdout = getattr(result, "stdout", "")
            print(f"Credential cleanup verification failed — stale files remain:\n{stdout}", file=sys.stderr)
    except Exception:
        print("Credential cleanup verification raised an exception:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
