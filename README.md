# pape — 本地 arxiv 论文管理 CLI（macOS）

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

一个轻量命令行工具，把 arxiv 论文的 PDF 和元数据（id、url、title、abstract、submit_date、本地路径、入库时间）统一存到你机器上，方便后续按 id/标题/关键词查找、打开、删除。

## 安装

```bash
git clone https://github.com/Rodriguez009/pape.git
cd pape
bash install.sh
```

`install.sh` 会：

1. 在项目内创建 `.venv`（不污染系统 Python）
2. 安装依赖：`arxiv`、`requests`、`openpyxl`、`scikit-learn`
3. 创建 `~/pape/pdf/` 数据目录
4. 在 `~/.local/bin/pape` 写入启动器
5. 检查 `~/.local/bin` 是否在你的 `PATH` 中，未配置则给出提示

> 如果脚本提醒 PATH 未配置，把下面这行加到 `~/.zshrc` 然后重开终端：
> ```bash
> export PATH="$HOME/.local/bin:$PATH"
> ```

## 用法

```text
pape add URL_OR_ID         下载并入库（支持 abs/pdf 链接、裸 id）
pape delete TITLE_OR_ID    按 id 或 title 删除本地 PDF 与对应记录
pape list [N]              列出最近 N 篇（默认 10）
pape find KEYWORDS         本地检索：在已入库的论文里查 title/abstract/id（top10）
pape search QUERY [-n N]   在线检索：调 arxiv 搜索 N 篇（默认 5），可交互入库
pape open TITLE_OR_ID      用默认应用（Preview）打开 PDF
pape --help                详细帮助
pape <cmd> --help          某个子命令的帮助
pape --version             版本号
```

### 示例

```bash
# 加入 Attention Is All You Need
pape add https://arxiv.org/abs/1706.03762

# 也可以是 pdf 链接 / 裸 id
pape add https://arxiv.org/pdf/2310.06825v1.pdf
pape add 2401.00001

# 最近 5 篇
pape list 5

# 本地检索（已入库的论文，TF-IDF + 余弦相似度）
pape find "transformer attention scaling"

# 在 arxiv 上在线搜索（按相关性返回 N 篇候选，提示输入编号入库；多选用逗号；a=全部，q=取消）
pape search "qwen3 tts" -n 5
pape search "longcat audiodit"

# 用 Preview 打开
pape open "Attention Is All You Need"
pape open 1706.03762

# 删除（按 id 或 title 都行；多匹配会让你二次确认）
pape delete 1706.03762
```

## 数据存放位置

- PDF 文件：`~/pape/pdf/<论文标题>.pdf`（文件名做了清洗 + 长度限制；冲突时会在末尾追加 arxiv id）
- 元数据：`~/pape/info.xlsx`（首行表头：`id, url, title, abstract, submit_date, path, added_date`）

可以直接用 Excel/Numbers 打开 `info.xlsx` 查看或手工编辑。**注意**：编辑期间请不要同时运行 `pape --add`，写入会被拒绝（pape 会提示你先关闭表格）。

## 卸载

```bash
bash uninstall.sh           # 删除启动器与 .venv，保留 ~/pape/ 数据
bash uninstall.sh --purge   # 同时删除 ~/pape/（需要二次确认）
```

## 设计说明

- **依赖隔离**：所有 Python 依赖装在项目内 `.venv/`，启动器走 `exec "$VENV/bin/python" -m pape ...`，不会动到系统/全局 Python。
- **并发安全**：写 `info.xlsx` 时用 `fcntl.flock` 加排他锁，且先写临时文件再 `os.replace` 原子替换。
- **网络容错**：PDF 下载有超时、流式写、首字节 `%PDF` 校验；失败会清理半成品。
- **检索**：`scikit-learn` 的 `TfidfVectorizer`（1–2 gram、英文停用词）+ 余弦相似度，对中小规模（数千篇）的库足够快。
