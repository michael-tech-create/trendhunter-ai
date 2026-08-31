"""Alpaca CLI subprocess wrapper with retries and JSON parsing."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from typing import Any, Optional

from config import get_settings

logger = logging.getLogger(__name__)


class AlpacaCLIError(RuntimeError):
    """Raised when the Alpaca CLI fails after retries or is unavailable."""


def alpaca_cli_available() -> bool:
    settings = get_settings()
    return shutil.which(settings.alpaca_cli_path) is not None


def call_alpaca_cli(
    args: list[str],
    *,
    retries: Optional[int] = None,
    timeout: Optional[int] = None,
    raw: bool = False,
) -> Any:
    """
    Run `alpaca <args>` and parse JSON stdout.

    Alpaca CLI is alpha — timeouts and flaky JSON are expected. We retry with
    exponential backoff and surface the last stderr clearly. Callers must not
    assume success; demo paths should fall back to cache on AlpacaCLIError.
    """
    settings = get_settings()
    retries = settings.cli_retries if retries is None else retries
    timeout = settings.cli_timeout_seconds if timeout is None else timeout
    binary = settings.alpaca_cli_path

    if not shutil.which(binary):
        raise AlpacaCLIError(
            f"Alpaca CLI not found on PATH ('{binary}'). "
            "Install from https://github.com/alpacahq/cli or set ALPACA_CLI_PATH."
        )

    cmd = [binary, *args]
    last_error: Optional[Exception] = None

    for attempt in range(retries):
        try:
            logger.debug("CLI attempt %s/%s: %s", attempt + 1, retries, " ".join(cmd))
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            if result.returncode != 0:
                raise AlpacaCLIError(
                    f"CLI exit {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
                )

            stdout = (result.stdout or "").strip()
            if raw:
                return stdout
            if not stdout:
                raise AlpacaCLIError("CLI returned empty stdout")

            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                # Some CLI commands emit logs before JSON — try last JSON object/array
                parsed = _extract_json(stdout)
                if parsed is not None:
                    return parsed
                raise AlpacaCLIError(f"CLI stdout is not valid JSON: {stdout[:500]}")

        except (AlpacaCLIError, subprocess.TimeoutExpired, OSError) as e:
            last_error = e
            logger.warning("Alpaca CLI attempt %s failed: %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(2**attempt)

    assert last_error is not None
    logger.error("Alpaca CLI failed after %s attempts: %s", retries, last_error)
    raise AlpacaCLIError(str(last_error)) from last_error


def _extract_json(text: str) -> Any | None:
    """Best-effort extract of a leading JSON value from noisy CLI output."""
    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            chunk = text[start : end + 1]
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                continue
    return None
