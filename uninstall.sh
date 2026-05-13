#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$HOME/pape"
BIN_DIR="$HOME/.local/bin"
VENV_DIR="$PROJECT_DIR/.venv"

PURGE=0
for a in "$@"; do
  case "$a" in
    --purge) PURGE=1 ;;
    *) echo "未知参数: $a" >&2; exit 1 ;;
  esac
done

if [ -e "$BIN_DIR/pape" ]; then
  rm -f "$BIN_DIR/pape"
  echo "已删除启动器: $BIN_DIR/pape"
fi

if [ -d "$VENV_DIR" ]; then
  rm -rf "$VENV_DIR"
  echo "已删除 venv: $VENV_DIR"
fi

if [ "$PURGE" = "1" ]; then
  echo
  echo "⚠ 即将删除数据目录 $DATA_DIR （含所有 PDF 与 info.xlsx）。"
  read -r -p "确认删除？输入 yes 以继续: " ans
  if [ "$ans" = "yes" ]; then
    rm -rf "$DATA_DIR"
    echo "已删除数据目录: $DATA_DIR"
  else
    echo "已取消，保留数据目录。"
  fi
else
  echo "保留数据目录 $DATA_DIR（如需一起删除请用 --purge）"
fi
