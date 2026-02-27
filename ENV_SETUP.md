# Bot の環境変数（.env）

## 必要な設定

プロジェクトフォルダの `.env` に以下を記入：

```
DISCORD_BOT_TOKEN=DiscordのBotトークン
GEMINI_API_KEY=GeminiのAPIキー
```

## 取得方法

**DISCORD_BOT_TOKEN**
1. https://discord.com/developers/applications にアクセス
2. 対象のアプリ → Bot → Reset Token / Copy でトークンをコピー

**GEMINI_API_KEY**
1. https://aistudio.google.com/apikey にアクセス
2. 「Create API Key」でキーを作成しコピー

## 反映

```bash
/Users/sukofi/Desktop/cursor-agent/update_and_restart.sh
```

`.env` は `update_and_restart.sh` で `~/cursor-agent-bot/` にコピーされます。launchd で動かしている場合も同じ `.env` が使われます。
