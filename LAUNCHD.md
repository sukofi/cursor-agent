# Discord Bot を launchd で動かす

**実際に動いているのは `~/cursor-agent-bot` です。**  
（macOS の制限で launchd からは Desktop 内のファイルにアクセスできないため、ホーム直下にコピーしてあります。）

## 1. 初回セットアップ（すでに実施済み）

- plist: `~/Library/LaunchAgents/com.sukofi.discord-agent-bot.plist`
- 実行コピー: `~/cursor-agent-bot`（Anaconda の Python で実行）
- ログ: `~/cursor-agent-bot/logs/discord-bot.out.log` と `.err.log`

**LLM:** Ollama 単体。Bot が使う Python 環境で `pip install ollama` を実行してください。  
`pip install -r ~/cursor-agent-bot/requirements.txt` で依存関係を入れ、`ollama list` / `ollama run qwen3-swallow:8b` でモデルを用意すると、起動時のログに「Ollama（単体） — 利用可能」と出ます。

---

## 2. コードを更新したとき

**Step 1: 実行用コピーを更新（Desktop で編集している場合）**

```bash
rsync -av --exclude 'logs' --exclude '.git' /Users/sukofi/Desktop/cursor-agent-main/ /Users/sukofi/cursor-agent-bot/
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

## 4. Ollama も launchd で常時起動

- **ラベル:** `com.ollama.serve`
- **plist:** `~/Library/LaunchAgents/com.ollama.serve.plist`（プロジェクトの `com.ollama.serve.plist` をコピーして使用）
- **コマンド:** `ollama serve`
- **ログ:** `~/cursor-agent-bot/logs/ollama.out.log` と `ollama.err.log`

**初回:** plist の `ProgramArguments` で `ollama` のパスを確認してください。Homebrew の場合は `/opt/homebrew/bin/ollama` に変更してください。

**起動（ログイン時に自動。手動で今すぐ起動する場合）:**
```bash
launchctl load -w ~/Library/LaunchAgents/com.ollama.serve.plist
launchctl kickstart -k gui/$(id -u)/com.ollama.serve
```

**再起動:** `launchctl kickstart -k gui/$(id -u)/com.ollama.serve`  
**停止:** `launchctl bootout gui/$(id -u)/com.ollama.serve`

---

## 5. ログの確認

```bash
# Discord Bot
tail -f ~/cursor-agent-bot/logs/discord-bot.err.log

# Ollama
tail -f ~/cursor-agent-bot/logs/ollama.err.log
```

---

## 6. プログラム作成はフルディスクアクセス不要

**プログラムの作成・実行・スキル保存は、すべてプロジェクトフォルダ（`~/cursor-agent-bot/project`）内だけで行います。**  
この範囲であれば **macOS のフルディスクアクセスを付与しなくても** そのまま利用できます。

- `write_file` で作るファイル → すべて `project/` 以下
- `run_script` で実行するスクリプト → すべて `project/` 以下
- `save_skill` で登録するナレッジ → `project/knowledge/` 以下
- カスタムツール用 .py → `project/tools/` 以下

---

## 7. Operation not permitted の解消

Bot が **プロジェクト外**（Desktop へのフォルダ作成や rsync 先など）で **Operation not permitted** が出る場合のみ、macOS の「フルディスクアクセス」を付与してください。

1. **システム設定** → **プライバシーとセキュリティ** → **フルディスクアクセス**
2. **+** で **ターミナル**、**Cursor**、**Python（Anaconda）** を追加し、チェックをオンにする。
3. 該当アプリを再起動し、Bot を再起動: `launchctl kickstart -k gui/$(id -u)/com.sukofi.discord-agent-bot`
