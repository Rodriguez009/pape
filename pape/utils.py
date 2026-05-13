import os
import re
import sys
import unicodedata
from datetime import datetime


_BAD_CHARS = re.compile(r'[\\/:*?"<>|\n\r\t]')
_MULTI_SPACE = re.compile(r"\s+")


def sanitize_filename(title: str, max_len: int = 150) -> str:
    """Turn an arbitrary paper title into a filesystem-safe filename stem."""
    title = unicodedata.normalize("NFKC", title or "").strip()
    title = _BAD_CHARS.sub(" ", title)
    title = _MULTI_SPACE.sub(" ", title).strip()
    title = title.replace(" ", "_")
    if not title:
        title = "untitled"
    if len(title) > max_len:
        title = title[:max_len].rstrip("_")
    return title


def now_local_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fmt_date(value) -> str:
    """Format an arxiv date (datetime or str) as YYYY-MM-DD."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    s = str(value)
    return s[:10]


def trunc(s: str, n: int) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\n", " ").replace("\r", " ")
    if len(s) <= n:
        return s
    return s[: max(0, n - 1)] + "…"


def print_table(headers, rows, max_widths=None, file=None):
    """ASCII table writer with per-column max widths and auto-shrinking."""
    file = file or sys.stdout
    cols = len(headers)
    max_widths = list(max_widths) if max_widths else [None] * cols
    cells = [[trunc(c, max_widths[i]) if max_widths[i] else ("" if c is None else str(c))
              for i, c in enumerate(row)] for row in rows]
    widths = [len(h) for h in headers]
    for r in cells:
        for i, c in enumerate(r):
            if len(c) > widths[i]:
                widths[i] = len(c)
    sep = "  "
    line = sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line, file=file)
    print(sep.join("-" * widths[i] for i in range(cols)), file=file)
    for r in cells:
        print(sep.join(r[i].ljust(widths[i]) for i in range(cols)), file=file)


def err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def info(msg: str) -> None:
    print(msg)


def prompt_yes_no(question: str, default_no: bool = True) -> bool:
    suffix = " [y/N] " if default_no else " [Y/n] "
    try:
        ans = input(question + suffix).strip().lower()
    except EOFError:
        return not default_no
    if not ans:
        return not default_no
    return ans in ("y", "yes")


def prompt_choice(prompt: str, n: int):
    """Prompt user to pick 1..n, 'a' for all, 'q' to cancel. Returns list of indices or None."""
    try:
        ans = input(prompt).strip().lower()
    except EOFError:
        return None
    if not ans or ans == "q":
        return None
    if ans == "a":
        return list(range(n))
    try:
        idx = int(ans) - 1
    except ValueError:
        return None
    if 0 <= idx < n:
        return [idx]
    return None
