#!/bin/bash
# Install / manage the daily launchd job that runs sync.py unattended.
#
#   ./schedule.sh install [HH:MM]   # default 09:30, runs every day
#   ./schedule.sh run               # trigger one run right now
#   ./schedule.sh status            # is it loaded? when did it last run?
#   ./schedule.sh logs              # tail today's sync log
#   ./schedule.sh uninstall
#
# Notes
#  * launchd gets a bare PATH, so the job pins the python3 and the folder that
#    holds lark-cli into the plist.
#  * If the Mac is asleep at the scheduled time, launchd runs the job at wake.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${YOUMIND_DATA_DIR:-$HOME/.youmind-sync}"
LABEL="com.youmind.prompts-sync"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${DATA_DIR}/logs"
PYTHON="$(command -v python3)"

install_job() {
  local when="${1:-09:30}"
  local hh="${when%%:*}" mm="${when##*:}"
  mkdir -p "$HOME/Library/LaunchAgents" "${LOG_DIR}" "${DATA_DIR}"

  local lark_dir
  lark_dir="$(dirname "$(command -v lark-cli 2>/dev/null || echo /usr/local/bin/lark-cli)")"
  local py_dir
  py_dir="$(dirname "${PYTHON}")"

  cat > "${PLIST}" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${HERE}/sync.py</string>
  </array>
  <key>WorkingDirectory</key><string>${HERE}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$py_dir:$lark_dir:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>YOUMIND_DATA_DIR</key><string>${DATA_DIR}</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$((10#$hh))</integer><key>Minute</key><integer>$((10#$mm))</integer></dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>${LOG_DIR}/launchd.out.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/launchd.err.log</string>
</dict>
</plist>
PLISTEOF

  launchctl unload "${PLIST}" 2>/dev/null || true
  launchctl load -w "${PLIST}"
  echo "✔ 已安装定时任务：每天 ${when} 运行"
  echo "  plist: ${PLIST}"
  echo "  日志 : ${DATA_DIR}/sync.log"
}

case "${1:-install}" in
  install) shift || true; install_job "${1:-09:30}" ;;
  uninstall)
    launchctl unload "${PLIST}" 2>/dev/null || true
    rm -f "${PLIST}"
    echo "✔ 已移除定时任务" ;;
  run)
    "${PYTHON}" "${HERE}/sync.py" ;;
  status)
    if launchctl list | grep -q "${LABEL}"; then
      echo "✔ 定时任务已加载"
      launchctl list | grep "${LABEL}"
    else
      echo "✖ 定时任务未加载（${PLIST}）"
    fi
    echo "--- state.json"
    cat "${DATA_DIR}/state.json" 2>/dev/null || echo "(还没有运行过)"
    ;;
  logs)
    mkdir -p "${LOG_DIR}"
    tail -n 60 "${DATA_DIR}/sync.log" 2>/dev/null || echo "(暂无日志)"
    ;;
  *)
    echo "用法: $0 {install [HH:MM]|run|status|logs|uninstall}" >&2
    exit 1 ;;
esac
