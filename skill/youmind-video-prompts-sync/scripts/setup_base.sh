#!/bin/bash
# Create the Feishu Bitable (table + 28 fields) and write ~/.youmind-sync/config.json.
#
#   ./setup_base.sh                      # create a new Base named "YouMind 视频提示词库"
#   ./setup_base.sh "我的提示词库"        # custom name
#   BASE_NAME=... ./setup_base.sh
#
# Requires: lark-cli authenticated (`lark-cli auth status`), python3.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${YOUMIND_DATA_DIR:-$HOME/.youmind-sync}"
BASE_NAME="${1:-${BASE_NAME:-YouMind 视频提示词库}}"
TABLE_NAME="${TABLE_NAME:-视频提示词}"
IDENTITY="${YOUMIND_IDENTITY:-bot}"

mkdir -p "${DATA_DIR}"

if ! command -v lark-cli >/dev/null 2>&1; then
  echo "✖ 找不到 lark-cli，请先安装并登录：lark-cli auth login --domain base,drive" >&2
  exit 1
fi

FIELDS="$(cat "${HERE}/fields.json")"
echo "▶ 正在创建多维表格「${BASE_NAME}」…"
OUT="$(lark-cli base +base-create \
        --name "${BASE_NAME}" \
        --table-name "${TABLE_NAME}" \
        --fields "$FIELDS" \
        --as "${IDENTITY}" --format json)"

read -r BASE_TOKEN BASE_URL TABLE_ID <<<"$(printf '%s' "${OUT}" | python3 -c '
import json, sys
d = json.load(sys.stdin).get("data") or {}
b = d.get("base") or {}
t = d.get("table") or {}
tok = b.get("base_token") or b.get("app_token") or d.get("app_token") or ""
url = b.get("url") or ("https://feishu.cn/base/" + tok if tok else "-")
print(tok, url or "-", t.get("id") or "")
')"

if [ -z "${BASE_TOKEN}" ] || [ -z "${TABLE_ID}" ]; then
  echo "✖ 创建失败，原始返回：" >&2
  printf '%s\n' "${OUT}" >&2
  exit 1
fi

python3 - "${DATA_DIR}" "${BASE_TOKEN}" "${TABLE_ID}" "${IDENTITY}" <<'PY'
import json, os, sys
data_dir, base, table, identity = sys.argv[1:5]
p = os.path.join(data_dir, "config.json")
cfg = {}
if os.path.exists(p):
    cfg = json.load(open(p, encoding="utf-8"))
cfg.update({"base_token": base, "table_id": table, "identity": identity})
json.dump(cfg, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("✔ 已写入配置：", p)
PY

URL="${BASE_URL}"
echo
echo "✔ 建表完成"
echo "  多维表格：${URL}"
echo "  base_token: ${BASE_TOKEN}"
echo "  table_id  : ${TABLE_ID}"
echo "  配置目录  : ${DATA_DIR}"
echo
echo "下一步：YOUMIND_DATA_DIR=${DATA_DIR} python3 \"${HERE}/sync.py\" --full"
