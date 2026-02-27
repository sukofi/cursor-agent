# Discord Bot を launchd で動かす

**実際に動いているのは `~/cursor-agent-bot` です。**  
（macOS の制限で launchd からは Desktop 内のファイルにアクセスできないため、ホーム直下にコピーしてあります。）

## 1. 初回セットアップ（すでに実施済み）

- plist: `~/Library/LaunchAgents/com.sukofi.discord-agent-bot.plist`
- 実行コピー: `~/cursor-agent-bot`（Anaconda の Python で実行）
- ログ: `~/cursor-agent-bot/logs/discord-bot.out.log` と `.err.log`

**Gemini を常時使用する場合:** plist の `EnvironmentVariables` に `GEMINI_API_KEY` を追加してください。

---

## 2. コードを更新したとき

**Step 1: 実行用コピーを更新（Desktop で編集している場合）**

```bash
rsync -av --exclude 'logs' /Users/sukofi/Desktop/cursor-agent/ /Users/sukofi/cursor-agent-bot/
```

**Step 2: Bot を再起動**

```bash
launchctl kickstart -k gui/$(id -u)/com.sukofi.discord-agent-bot
```

`-k` は「既に動いていても一度止めてから起動し直す」という意味です。

---

## 3. その他の操作

| 操作       | コマンド |
|------------|----------|
| 停止       | `launchctl bootout gui/$(id -u)/com.sukofi.discord-agent-bot` |
| 起動       | `launchctl bootstrap gui/$(id -u)/~/Library/LaunchAgents/com.sukofi.discord-agent-bot.plist` |
| 状態確認   | `launchctl print gui/$(id -u)/com.sukofi.discord-agent-bot` |

---

## 4. Ollama も launchd で常時起動（設定済み）

- **ラベル:** `com.ollama.serve`
- **コマンド:** `ollama serve`
- **ログ:** `~/cursor-agent-bot/logs/ollama.out.log` と `ollama.err.log`

**再起動:**
```bash
launchctl kickstart -k gui/$(id -u)/com.ollama.serve
```

**停止:**
```bash
launchctl bootout gui/$(id -u)/com.ollama.serve
```

---

## 5. ログの確認

```bash
# Discord Bot
tail -f ~/cursor-agent-bot/logs/discord-bot.err.log

# Ollama
tail -f ~/cursor-agent-bot/logs/ollama.err.log
```
