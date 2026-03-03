# カスタムツール（project/tools）

このフォルダに置いた `.py` が Bot の**ツール**として自動登録され、モデルが呼び出せます。

## 書き方

各 `.py` に以下を定義してください。

- **TOOL_NAME** (str): ツール名（モデルが呼び出す名前。英数字・アンダースコア推奨）
- **TOOL_DESCRIPTION** (str): 説明（モデルがいつこのツールを使うか判断するため）
- **TOOL_PARAMS** (dict, 任意): Ollama 用パラメータスキーマ。省略時は引数なし
- **run(args)** (function): 実行関数。`args` は `dict`、戻り値は `str`

## 例（example_tool.py）

```python
TOOL_NAME = "echo_message"
TOOL_DESCRIPTION = "受け取ったメッセージをそのまま返す。テスト用。"
TOOL_PARAMS = {
    "type": "object",
    "properties": {"message": {"type": "string"}},
    "required": ["message"],
}

def run(args):
    return args.get("message", "")
```

## 注意

- `_` で始まるファイルや `.py` 以外は読み込みません。
- 読み込みは Bot 起動時のみ。追加・変更したら Bot を再起動してください。
