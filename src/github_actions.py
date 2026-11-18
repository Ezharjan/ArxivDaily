"""Helpers for running inside GitHub Actions (all no-ops when run locally).

Public repositories have public workflow logs and summaries, so nothing written
here may contain email addresses or secrets.
"""

from __future__ import annotations

import os
import re
from typing import Optional


def in_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def repository() -> str:
    return os.environ.get("GITHUB_REPOSITORY", "")


def repo_url() -> str:
    repo = repository()
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    return f"{server}/{repo}" if repo else ""


def branch() -> str:
    return os.environ.get("GITHUB_REF_NAME", "") or "master"


def run_url() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    return f"{repo_url()}/actions/runs/{run_id}" if repo_url() and run_id else ""


def workflow_url() -> str:
    ref = os.environ.get("GITHUB_WORKFLOW_REF", "")           # owner/repo/.github/workflows/x.yml@refs/heads/main
    m = re.search(r"\.github/workflows/([^@]+)@", ref)
    name = m.group(1) if m else "arxiv_daily.yml"
    return f"{repo_url()}/actions/workflows/{name}" if repo_url() else ""


def settings_url(page: str) -> str:
    return f"{repo_url()}/settings/{page}" if repo_url() else ""


def edit_url(path: str) -> str:
    return f"{repo_url()}/edit/{branch()}/{path}" if repo_url() else ""


def set_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    safe = str(value).replace("\r", " ").replace("\n", " ").strip()
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"{name}={safe}\n")


def write_summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(markdown.rstrip() + "\n")


def _escape_data(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_prop(s: str) -> str:
    return _escape_data(s).replace(":", "%3A").replace(",", "%2C")


def annotate(level: str, message: str, *, title: str = "", file: str = "", line: int = 0,
             col: int = 0) -> None:
    """Show a message on the run page (and inline on the file for config errors)."""
    if not in_actions():
        return
    props = []
    if title:
        props.append(f"title={_escape_prop(title)}")
    if file:
        props.append(f"file={_escape_prop(file)}")
        if line:
            props.append(f"line={line}")
            if col:
                props.append(f"col={col}")
    print(f"::{level} {','.join(props)}::{_escape_data(message)}", flush=True)


def schedule_description(workflow_path: str) -> str:
    """When the workflow checks for papers, e.g. 'daily at 06:23 and 14:23 UTC'.

    Read from the cron lines of the workflow file; the phrase fits after
    "checks for new papers ...".
    """
    try:
        with open(workflow_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return "on the schedule in .github/workflows/arxiv_daily.yml"
    crons = re.findall(r"""^\s*-\s*cron:\s*["']([^"']+)["']""", text, re.M)
    if not crons:
        return "only when you start it from the Actions tab"
    daily, other = [], []
    for c in crons:
        parts = c.split()
        if len(parts) == 5 and parts[2:] == ["*", "*", "*"] and parts[0].isdigit() and parts[1].isdigit():
            daily.append(f"{int(parts[1]):02d}:{int(parts[0]):02d}")
        else:
            other.append(c)
    bits = []
    if daily:
        bits.append("daily at " + " and ".join(sorted(daily)) + " UTC")
    if other:
        bits.append("on the cron schedule " + ", ".join(f"'{c}'" for c in other) + " (UTC)")
    return " and ".join(bits)


def md_escape(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", text or "")


def link(text: str, url: Optional[str]) -> str:
    return f"[{md_escape(text)}]({url})" if url else md_escape(text)
