#!/bin/zsh
# Install music-stack watch as a login-started, auto-restarting LaunchAgent.
# Idempotent: re-running replaces the agent with current paths.
set -euo pipefail

LABEL="com.vanalm.music-stack-watch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$(command -v music-stack)"
if [ -z "$BIN" ]; then
  echo "music-stack not on PATH — run: pip install -e $ROOT" >&2
  exit 1
fi
# Resolve through pyenv shims so launchd (which has no shims) gets a real binary.
case "$BIN" in
  */shims/*) BIN="$(pyenv which music-stack)" ;;
esac
BINDIR="$(dirname "$BIN")"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array><string>$BIN</string><string>watch</string></array>
    <key>WorkingDirectory</key><string>$ROOT</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>$BINDIR:/opt/homebrew/bin:/usr/bin:/bin</string>
        <key>HOME</key><string>$HOME</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$ROOT/watch-launchd.log</string>
    <key>StandardErrorPath</key><string>$ROOT/watch-launchd.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed and started: $LABEL"
echo "drop folder: $ROOT/dropbox"
echo "log:         $ROOT/watch.log"
echo "uninstall:   launchctl bootout gui/$(id -u)/$LABEL && rm $PLIST"
