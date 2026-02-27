#!/bin/bash
# Discord Bot の実行用コピーを更新し、launchd で再起動する

set -e
SOURCE="/Users/sukofi/Desktop/cursor-agent"
DEST="/Users/sukofi/cursor-agent-bot"
LABEL="com.sukofi.discord-agent-bot"

echo "1. 実行用コピーを更新中..."
rsync -av --exclude 'logs' --exclude '.git' "$SOURCE/" "$DEST/"

echo "2. Discord Bot を再起動中..."
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "完了しました。"
