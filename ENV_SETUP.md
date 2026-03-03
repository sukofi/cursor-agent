# Bot の環境変数（.env）

## 必要な設定

プロジェクト直下の `.env` に以下を記入してください。

```
DISCORD_BOT_TOKEN=DiscordのBotトークン
```

## オプション（Ollama のモデルを変える場合）

```
OLLAMA_MODEL_OUTPUT=qwen3-swallow:8b
OLLAMA_MODEL_THINKING=qwen3-swallow:8b
```

未設定の場合は上記がデフォルトで使われます。

## Discord トークンの取得

1. https://discord.com/developers/applications にアクセス
2. 対象のアプリ → Bot → Reset Token / Copy でトークンをコピー

## 反映

launchd で動かしている場合は、`update_and_restart.sh` 実行時に `.env` も `~/cursor-agent-bot/` へコピーされます。
