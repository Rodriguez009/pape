import argparse
import os
import subprocess
import sys
import time
from typing import List, Optional

from . import __version__
from . import arxiv_client
from . import storage
from . import search
from .storage import Row
from .utils import (
    err,
    fmt_date,
    info,
    now_local_str,
    print_table,
    prompt_choice,
    prompt_yes_no,
    sanitize_filename,
    trunc,
    warn,
)


USAGE_EPILOG = """examples:
  pape add https://arxiv.org/abs/1706.03762
  pape add 1706.03762
  pape search "qwen3 tts" -n 5
  pape list 5
  pape find "transformer attention"
  pape open "Attention Is All You Need"
  pape delete 1706.03762

find = 本地检索（已入库）   search = arxiv 在线搜索（可交互入库）
"""


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pape",
        description="本地 arxiv 论文管理工具：下载 PDF、维护元信息、检索、打开、删除。",
        epilog=USAGE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"pape {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    sp_add = sub.add_parser("add", help="下载一篇 arxiv 论文并入库（abs/pdf 链接或裸 id）")
    sp_add.add_argument("target", metavar="URL_OR_ID")

    sp_del = sub.add_parser("delete", help="按 id 或 title 删除本地 PDF 与对应记录")
    sp_del.add_argument("target", metavar="TITLE_OR_ID")

    sp_list = sub.add_parser("list", help="列出最近 N 篇（默认 10）")
    sp_list.add_argument("n", nargs="?", type=int, default=10, metavar="N")

    sp_find = sub.add_parser("find", help="本地检索 title/abstract/id，返回 top10")
    sp_find.add_argument("keywords", metavar="KEYWORDS")

    sp_search = sub.add_parser("search", help="在 arxiv 上按关键词搜索，可交互入库")
    sp_search.add_argument("query", metavar="QUERY")
    sp_search.add_argument("-n", "--num", type=int, default=5,
                           help="返回多少条候选（默认 5，最多 20）")

    sp_open = sub.add_parser("open", help="按 id 或 title 用默认应用打开 PDF")
    sp_open.add_argument("target", metavar="TITLE_OR_ID")

    return p


def _ingest(meta) -> int:
    """Given fetched arxiv metadata, handle dedup/overwrite/download/write."""
    with storage.write_session() as state:
        rows: List[Row] = state["rows"]
        existing_idx = storage.find_by_id_exact(rows, meta.arxiv_id)
        if existing_idx is not None:
            existing = rows[existing_idx]
            info(f"该论文已在库中：[{existing.id}] {existing.title}")
            info(f"  路径: {existing.path}")
            info(f"  入库时间: {existing.added_date}")
            if not prompt_yes_no("是否覆盖（重新下载并更新记录）？", default_no=True):
                state["save"] = False
                return 0
            # Safe overwrite: rename old PDF to .bak first, restore on failure.
            old_path = existing.path
            backup = None
            if old_path and os.path.exists(old_path):
                backup = old_path + ".bak"
                try:
                    os.rename(old_path, backup)
                except OSError as exc:
                    warn(f"备份旧 PDF 失败（将走非原位下载）: {exc}")
                    backup = None
            safe_stem = sanitize_filename(meta.title) or sanitize_filename(meta.arxiv_id)
            dest = old_path if (backup and old_path) else storage.pick_pdf_path(safe_stem, meta.arxiv_id)
            try:
                arxiv_client.download_pdf(meta.pdf_url, dest)
            except RuntimeError as exc:
                if backup and os.path.exists(backup):
                    try:
                        os.rename(backup, old_path)
                    except OSError:
                        pass
                err(str(exc))
                state["save"] = False
                return 1
            if backup and os.path.exists(backup):
                try:
                    os.remove(backup)
                except OSError:
                    pass
            rows.pop(existing_idx)
        else:
            safe_stem = sanitize_filename(meta.title) or sanitize_filename(meta.arxiv_id)
            dest = storage.pick_pdf_path(safe_stem, meta.arxiv_id)
            try:
                arxiv_client.download_pdf(meta.pdf_url, dest)
            except RuntimeError as exc:
                err(str(exc))
                state["save"] = False
                return 1

        new_row = Row(
            id=meta.arxiv_id,
            url=meta.abs_url,
            title=meta.title,
            abstract=meta.abstract,
            submit_date=meta.published,
            path=dest,
            added_date=now_local_str(),
        )
        rows.append(new_row)
        info(f"已入库: [{new_row.id}] {new_row.title}")
        info(f"  PDF : {new_row.path}")
    return 0


def cmd_add(target: str) -> int:
    try:
        arxiv_id_in = arxiv_client.parse_identifier(target)
    except ValueError as exc:
        err(str(exc))
        return 1
    info(f"查询 arxiv: {arxiv_id_in} …")
    try:
        meta = arxiv_client.fetch_metadata(arxiv_id_in)
    except RuntimeError as exc:
        err(str(exc))
        return 1
    return _ingest(meta)


def _parse_picks(ans: str, total: int) -> Optional[List[int]]:
    """Parse a user pick string like '1,3,5' / 'a' / '' / 'q' into 0-based indices.
    Returns None if user wants to cancel, [] if input invalid (caller decides)."""
    ans = ans.strip().lower()
    if not ans or ans == "q":
        return None
    if ans == "a":
        return list(range(total))
    out: List[int] = []
    for piece in ans.replace(" ", ",").split(","):
        if not piece:
            continue
        try:
            i = int(piece) - 1
        except ValueError:
            return []
        if 0 <= i < total and i not in out:
            out.append(i)
    return out


def cmd_search(query: str, n: int) -> int:
    if n <= 0:
        err("-n 必须为正整数")
        return 1
    n = min(n, 20)
    info(f"在 arxiv 上搜索 {query!r}（top {n}）…")
    try:
        results = arxiv_client.search_arxiv(query, n)
    except RuntimeError as exc:
        err(str(exc))
        return 1
    if not results:
        info(f"arxiv 没有匹配 {query!r} 的论文。")
        return 0

    table = [[i + 1, m.arxiv_id, m.title, m.published] for i, m in enumerate(results)]
    print_table(["#", "id", "title", "submit_date"], table,
                max_widths=[3, 16, 80, 12])

    try:
        ans = input("输入编号入库（逗号分隔），a=全部，回车/q=取消: ")
    except EOFError:
        return 0
    picks = _parse_picks(ans, len(results))
    if picks is None:
        info("已取消。")
        return 0
    if not picks:
        err("未识别的选择")
        return 1

    rc = 0
    for k, idx in enumerate(picks):
        m = results[idx]
        info(f"\n--- 入库 [{idx + 1}/{len(picks)}] {m.arxiv_id} ---")
        rc |= _ingest(m)
        if k < len(picks) - 1:
            # Be gentle to arxiv's PDF endpoint between successive downloads.
            time.sleep(2)
    return rc


def cmd_delete(target: str) -> int:
    with storage.write_session() as state:
        rows: List[Row] = state["rows"]
        hits = storage.find_rows(rows, target)
        if not hits:
            err(f"未找到匹配项: {target!r}")
            state["save"] = False
            return 1
        if len(hits) > 1:
            info(f"匹配到 {len(hits)} 条，请选择要删除的：")
            display = [(i + 1, rows[h].id, trunc(rows[h].title, 70), rows[h].submit_date)
                       for i, h in enumerate(hits)]
            print_table(["#", "id", "title", "submit_date"], display, max_widths=[3, 16, 70, 12])
            pick = prompt_choice("输入编号 / a=全选 / q=取消: ", len(hits))
            if pick is None:
                info("已取消。")
                state["save"] = False
                return 0
            chosen = [hits[i] for i in pick]
        else:
            chosen = hits

        # Delete from largest index down to keep indices valid
        for idx in sorted(chosen, reverse=True):
            row = rows[idx]
            if row.path and os.path.exists(row.path):
                try:
                    os.remove(row.path)
                except OSError as exc:
                    warn(f"删除 PDF 失败（仍会移除记录）: {exc}")
            elif row.path:
                warn(f"PDF 不存在: {row.path}")
            rows.pop(idx)
            info(f"已删除: [{row.id}] {row.title}")
    return 0


def cmd_list(n: int) -> int:
    if n <= 0:
        err("N 必须为正整数")
        return 1
    rows = storage.load_rows()
    if not rows:
        info("库内还没有论文。先用 `pape --add <url-or-id>` 加一篇。")
        return 0
    rows_sorted = sorted(rows, key=lambda r: r.added_date, reverse=True)[:n]
    table = []
    for i, r in enumerate(rows_sorted, 1):
        table.append([i, r.id, r.title, r.submit_date, r.added_date])
    print_table(
        ["#", "id", "title", "submit_date", "added_date"],
        table,
        max_widths=[3, 16, 60, 12, 20],
    )
    info(f"共 {len(rows)} 篇，显示最新 {len(rows_sorted)} 篇。")
    return 0


def cmd_find(query: str) -> int:
    rows = storage.load_rows()
    if not rows:
        info("库内还没有论文。先用 `pape --add <url-or-id>` 加一篇。")
        return 0
    scored = search.rank(rows, query, top_k=10)
    if not scored:
        info(f"未找到与 {query!r} 相关的论文。")
        return 0
    table = []
    for i, (idx, score) in enumerate(scored, 1):
        r = rows[idx]
        table.append([i, f"{score:.3f}", r.id, r.title, r.submit_date])
    print_table(
        ["#", "score", "id", "title", "submit_date"],
        table,
        max_widths=[3, 6, 16, 70, 12],
    )
    return 0


def cmd_open(target: str) -> int:
    rows = storage.load_rows()
    hits = storage.find_rows(rows, target)
    if not hits:
        err(f"未找到匹配项: {target!r}")
        return 1
    if len(hits) > 1:
        info(f"匹配到 {len(hits)} 条，请选择要打开的：")
        display = [(i + 1, rows[h].id, trunc(rows[h].title, 70), rows[h].submit_date)
                   for i, h in enumerate(hits)]
        print_table(["#", "id", "title", "submit_date"], display, max_widths=[3, 16, 70, 12])
        pick = prompt_choice("输入编号 / q=取消: ", len(hits))
        if not pick:
            info("已取消。")
            return 0
        idx = hits[pick[0]]
    else:
        idx = hits[0]

    row = rows[idx]
    if not row.path or not os.path.exists(row.path):
        err(f"PDF 文件丢失: {row.path or '<空路径>'}\n可以重新 `pape --add {row.id}` 或 `pape --delete {row.id}` 清理记录。")
        return 1
    try:
        subprocess.run(["open", row.path], check=True)
    except subprocess.CalledProcessError as exc:
        err(f"调用 `open` 失败: {exc}")
        return 1
    info(f"已打开: [{row.id}] {row.title}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    storage.ensure_dirs()

    try:
        if args.cmd == "add":
            return cmd_add(args.target)
        if args.cmd == "delete":
            return cmd_delete(args.target)
        if args.cmd == "list":
            return cmd_list(args.n)
        if args.cmd == "find":
            return cmd_find(args.keywords)
        if args.cmd == "search":
            return cmd_search(args.query, args.num)
        if args.cmd == "open":
            return cmd_open(args.target)
        parser.print_help()
        return 0
    except KeyboardInterrupt:
        err("已中断。")
        return 130
    except RuntimeError as exc:
        err(str(exc))
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
