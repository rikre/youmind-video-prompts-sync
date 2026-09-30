#!/bin/bash
# One-shot installer: drop the skill into ~/.agents/skills, seed the data dir,
# optionally register a daily launchd job.
#
#   ./install.sh                                  install skill + seed data only
#   ./install.sh --schedule 09:30                 also run daily at 09:30
#   ./install.sh --new-base "My prompt library"   create a fresh Feishu Bitable first
#   ./install.sh --base <token> --table <tblxxx>  point at an existing Bitable
#   ./install.sh --uninstall                      remove skill + schedule (keeps data)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="${HERE}/skill/youmind-video-prompts-sync"
SKILL_DST="${HOME}/.agents/skills/youmind-video-prompts-sync"
DATA_DST="${YOUMIND_DATA_DIR:-${HOME}/.youmind-sync}"
BASE_TOKEN="${YOUMIND_BASE_TOKEN:-}"
TABLE_ID="${YOUMIND_TABLE_ID:-}"
SCHEDULE_AT=""
NEW_BASE=""
UNINSTALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --schedule)  SCHEDULE_AT="${2:?HH:MM required}"; shift 2 ;;
    --base)      BASE_TOKEN="${2:?}"; shift 2 ;;
    --table)     TABLE_ID="${2:?}"; shift 2 ;;
    --new-base)  NEW_BASE="${2:?}"; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help)   sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

if [ "${UNINSTALL}" = "1" ]; then
  [ -x "${SKILL_DST}/scripts/schedule.sh" ] && \
    YOUMIND_DATA_DIR="${DATA_DST}" "${SKILL_DST}/scripts/schedule.sh" uninstall || true
  rm -rf "${SKILL_DST}"
  echo "Removed the skill and its schedule. Data kept at ${DATA_DST}"
  exit 0
fi

command -v lark-cli >/dev/null 2>&1 || {
  echo "lark-cli not found. Install it and run: lark-cli auth login --domain base,drive" >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 1; }
python3 -c 'import requests' 2>/dev/null || {
  echo "Installing the python3 dependency (requests)..."
  python3 -m pip install --user --quiet requests || {
    echo "Please run: python3 -m pip install --user requests" >&2; exit 1; }
}

echo "==> skill  -> ${SKILL_DST}"
mkdir -p "$(dirname "${SKILL_DST}")"
rm -rf "${SKILL_DST}"
cp -R "${SKILL_SRC}" "${SKILL_DST}"
chmod +x "${SKILL_DST}/scripts/"*.sh

echo "==> data   -> ${DATA_DST}"
mkdir -p "${DATA_DST}"

if [ -n "${NEW_BASE}" ]; then
  echo "==> creating a new Bitable: ${NEW_BASE}"
  YOUMIND_DATA_DIR="${DATA_DST}" "${SKILL_DST}/scripts/setup_base.sh" "${NEW_BASE}"
  BASE_TOKEN="$(python3 -c "import json;print(json.load(open('${DATA_DST}/config.json'))['base_token'])")"
  TABLE_ID="$(python3 -c "import json;print(json.load(open('${DATA_DST}/config.json'))['table_id'])")"
elif [ -n "${BASE_TOKEN}" ] || [ -n "${TABLE_ID}" ]; then
  python3 - "${DATA_DST}" "${BASE_TOKEN}" "${TABLE_ID}" <<'PY'
import json, os, sys
data_dir, base, table = sys.argv[1:4]
p = os.path.join(data_dir, "config.json")
cfg = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
cfg.setdefault("identity", "bot")
if base:
    cfg["base_token"] = base
if table:
    cfg["table_id"] = table
json.dump(cfg, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("   wrote", p)
PY
fi

if [ -n "${SCHEDULE_AT}" ]; then
  echo "==> daily schedule at ${SCHEDULE_AT}"
  YOUMIND_DATA_DIR="${DATA_DST}" "${SKILL_DST}/scripts/schedule.sh" install "${SCHEDULE_AT}"
fi

if [ -z "${NEW_BASE}" ] && [ -z "${BASE_TOKEN}" ] && [ ! -f "${DATA_DST}/config.json" ]; then
  cat >&2 <<'WARN'
!! No Bitable configured yet. Create one before syncing:

     cd "$(dirname "${SKILL_DST}")/youmind-video-prompts-sync/scripts" 2>/dev/null || true
     ./setup_base.sh "YouMind video prompts"

   or re-run:  ./install.sh --new-base "YouMind video prompts"
WARN
fi

cat <<EOF

Done.

  skill : ${SKILL_DST}
  data  : ${DATA_DST}

Next:
  cd "${SKILL_DST}/scripts"
  ./setup_base.sh              # create the Bitable (skip if you passed --base/--table)
  python3 sync.py --full       # first full sync
  ./schedule.sh install 09:30  # daily incremental sync
EOF
