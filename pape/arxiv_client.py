import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlencode

import requests


# New-style IDs: YYMM.NNNNN (4 or 5 digit suffix), optional vN
_NEW_ID = r"\d{4}\.\d{4,5}(?:v\d+)?"
# Old-style IDs: e.g. cs/0501001, math.GT/0309136
_OLD_ID = r"[a-zA-Z][a-zA-Z\-\.]+\/\d{7}(?:v\d+)?"

_RE_URL = re.compile(
    rf"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/({_NEW_ID}|{_OLD_ID})(?:\.pdf)?/?$",
    re.IGNORECASE,
)
_RE_BARE = re.compile(rf"^({_NEW_ID}|{_OLD_ID})$")


VALID_EXAMPLES = (
    "https://arxiv.org/abs/1706.03762",
    "https://arxiv.org/pdf/1706.03762v5.pdf",
    "1706.03762",
    "cs/0501001",
)

_API_URL = "https://export.arxiv.org/api/query"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_UA = {"User-Agent": "pape/0.1 (+https://arxiv.org)"}


@dataclass
class PaperMeta:
    arxiv_id: str           # versioned, e.g. "1706.03762v7"
    abs_url: str
    pdf_url: str
    title: str
    abstract: str
    published: str          # YYYY-MM-DD


def parse_identifier(raw: str) -> str:
    """Return the canonical arxiv id (possibly with vN). Raise ValueError otherwise."""
    if not raw:
        raise ValueError("empty input")
    raw = raw.strip()
    raw = re.sub(r"^arxiv:\s*", "", raw, flags=re.IGNORECASE).strip().rstrip("/")
    m = _RE_URL.match(raw) or _RE_BARE.match(raw)
    if not m:
        examples = "\n  ".join(VALID_EXAMPLES)
        raise ValueError("无法识别的 arxiv 链接或编号。合法示例：\n  " + examples)
    return m.group(1)


def strip_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)


def _entry_to_meta(entry: ET.Element) -> PaperMeta:
    id_url = (entry.findtext("atom:id", default="", namespaces=_NS) or "").strip()
    # id_url looks like "http://arxiv.org/abs/1706.03762v7"
    short_id = id_url.rsplit("/abs/", 1)[-1].strip()
    title = " ".join((entry.findtext("atom:title", default="", namespaces=_NS) or "").split())
    summary = (entry.findtext("atom:summary", default="", namespaces=_NS) or "").strip()
    published = (entry.findtext("atom:published", default="", namespaces=_NS) or "")[:10]
    pdf_url = ""
    for link in entry.findall("atom:link", _NS):
        if link.get("type") == "application/pdf" or link.get("title") == "pdf":
            pdf_url = link.get("href", "")
            break
    if not pdf_url and short_id:
        pdf_url = f"https://arxiv.org/pdf/{short_id}"
    return PaperMeta(
        arxiv_id=short_id,
        abs_url=f"https://arxiv.org/abs/{short_id}" if short_id else id_url,
        pdf_url=pdf_url,
        title=title,
        abstract=summary,
        published=published,
    )


def _arxiv_get(params: dict, timeout: int = 20, retries: int = 2) -> ET.Element:
    """GET arxiv API with a hard per-request timeout. Returns parsed feed root."""
    url = f"{_API_URL}?{urlencode(params)}"
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=_UA, timeout=timeout)
            if resp.status_code == 429:
                raise RuntimeError(
                    "arxiv 接口暂时限流 (HTTP 429)。请稍候 1-2 分钟再重试。"
                )
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            return root
        except RuntimeError:
            raise  # don't retry on 429 — won't help
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(1)
                continue
    raise RuntimeError(f"查询 arxiv 失败: {last_exc}")


def fetch_metadata(arxiv_id: str) -> PaperMeta:
    """Query arxiv.org for metadata by id. Raises RuntimeError on failure."""
    root = _arxiv_get({"id_list": arxiv_id, "max_results": 1})
    entries = root.findall("atom:entry", _NS)
    if not entries:
        raise RuntimeError(f"未在 arxiv 找到 id={arxiv_id}，请确认编号正确")
    return _entry_to_meta(entries[0])


def search_arxiv(query: str, n: int = 5) -> List[PaperMeta]:
    """Full-text search arxiv.org. Returns up to n results sorted by relevance."""
    if not query.strip():
        return []
    root = _arxiv_get({
        "search_query": f"all:{query}",
        "max_results": n,
        "sortBy": "relevance",
        "sortOrder": "descending",
    })
    return [_entry_to_meta(e) for e in root.findall("atom:entry", _NS)]


def download_pdf(pdf_url: str, dest_path: str, timeout: int = 30,
                 retries: int = 2) -> None:
    """Stream-download a PDF. Retries transient SSL/network errors; cleans up partial files."""
    tmp_path = dest_path + ".part"
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            with requests.get(pdf_url, stream=True, timeout=timeout, headers=_UA) as resp:
                resp.raise_for_status()
                total = resp.headers.get("Content-Length")
                if total:
                    try:
                        mb = int(total) / 1024 / 1024
                        print(f"  下载中… {mb:.1f} MB")
                    except (TypeError, ValueError):
                        pass
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)
            with open(tmp_path, "rb") as f:
                head = f.read(5)
            if not head.startswith(b"%PDF"):
                raise RuntimeError("下载到的文件不是 PDF（首字节异常）")
            os.replace(tmp_path, dest_path)
            return
        except Exception as exc:
            last_exc = exc
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            if attempt < retries:
                time.sleep(1)
                continue
            break
    raise RuntimeError(f"下载 PDF 失败（已重试 {retries} 次）: {last_exc}")
