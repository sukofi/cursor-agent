# cursor-agent

Discord 上で動く自律型エージェント Bot。**Ollama 単体**で Qwen3 Swallow などを利用し、標準語で会話・プログラム作成・ツール実行を行います。

## 必要なもの

- Python 3.x（Anaconda など）
- Discord Bot トークン（[開発者ポータル](https://discord.com/developers/applications)で取得）
- [Ollama](https://ollama.com/)（ローカル LLM。例: `ollama run qwen3-swallow:8b`）

## セットアップ

1. `.env` に `DISCORD_BOT_TOKEN=...` を設定（詳細は [ENV_SETUP.md](ENV_SETUP.md)）
2. `pip install -r requirements.txt`
3. **Qwen3 Swallow を Ollama に登録（初回のみ）**  
   プロジェクト直下で実行。Hugging Face から GGUF がダウンロードされ、数分かかることがあります。
   ```bash
   ollama create qwen3-swallow:8b -f Modelfile
   ```
4. `ollama list` で `qwen3-swallow:8b` が表示されることを確認
5. `python agent_bot.py` で起動

launchd で常時起動する手順は [LAUNCHD.md](LAUNCHD.md) を参照。

## 構成

| ファイル・フォルダ | 説明 |
|--------------------|------|
| `agent_bot.py` | Bot 本体（Ollama 単体で LLM 呼び出し） |
| `project/` | Bot が作成するプログラム・ナレッジの保存先 |
| `project/knowledge/agent_profile.md` | Bot の役割・口調の設定 |
| `project/tools/` | カスタムツール用 .py |
| `Modelfile` | Qwen3 Swallow を Ollama に登録する定義（Hugging Face GGUF 参照） |

## モデル（Ollama）

- **思考・解答:** 既定はどちらも `qwen3-swallow:8b`（`.env` の `OLLAMA_MODEL_THINKING` / `OLLAMA_MODEL_OUTPUT` で上書き可）
- 未登録のときは `ollama create qwen3-swallow:8b -f Modelfile` を実行してから Bot を起動してください。
