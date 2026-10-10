#!/usr/bin/env bash
# Расписание сбора на macOS через launchd: воркер постоянно, планы 01:00 и 14:00,
# пересчёт 06:30 и 15:30 (время Mac). Удаление: --remove
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/../.." && pwd)"
UV="$(command -v uv)"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/smart-parser"
PREFIX="com.smart-parser"
JOBS=(worker plan-night plan-day recompute)

if [[ "${1:-}" == "--remove" ]]; then
  for j in "${JOBS[@]}"; do
    launchctl bootout "gui/$(id -u)/$PREFIX.$j" 2>/dev/null || true
    rm -f "$AGENTS/$PREFIX.$j.plist"
  done
  echo "Расписание удалено."
  exit 0
fi

mkdir -p "$AGENTS" "$LOGS"

plist() {  # name, args (через пробел), календарь (XML) или пусто, keepalive true|false
  local name="$1" args="$2" calendar="$3" keepalive="$4"
  local items=""
  for a in $args; do items+="<string>$a</string>"; done
  cat > "$AGENTS/$PREFIX.$name.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$PREFIX.$name</string>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <key>ProgramArguments</key><array><string>$UV</string><string>run</string><string>smart-parser</string>$items</array>
  <key>StandardOutPath</key><string>$LOGS/$name.log</string>
  <key>StandardErrorPath</key><string>$LOGS/$name.log</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  $calendar
  <key>KeepAlive</key><$keepalive/>
  <key>ThrottleInterval</key><integer>60</integer>
</dict></plist>
PLIST
  launchctl bootout "gui/$(id -u)/$PREFIX.$name" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$PREFIX.$name.plist"
}

at() { echo "<key>StartCalendarInterval</key><array>$(for t in "$@"; do echo "<dict><key>Hour</key><integer>${t%:*}</integer><key>Minute</key><integer>${t#*:}</integer></dict>"; done)</array>"; }

plist worker "work" "" true
plist plan-night "plan night" "$(at 1:00)" false
plist plan-day "plan day" "$(at 14:00)" false
plist recompute "recompute" "$(at 6:30 15:30)" false

echo "Готово. Задания: ${JOBS[*]/#/$PREFIX.}"
echo "Логи: $LOGS"
