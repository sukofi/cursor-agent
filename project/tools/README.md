# カスタムツール（project/tools）

Bot 起動時に `project/tools` 直下の `*.py` が自動でツールとして読み込まれます。  
ここに置いたツールは、組み込みツールと同様に LLM が呼び出せます。

## 仕様

各 `.py` ファイルで次の 4 つを定義してください。

| 名前 | 説明 |
|------|------|
| `TOOL_NAME` | ツールの識別子（英数字・アンダースコア）。LLM が呼び出す名前。 |
| `TOOL_DESCRIPTION` | ツールの説明文。LLM がいつ使うか判断するために使われます。 |
| `TOOL_PARAMS` | JSON Schema 形式の引数定義。Ollama の function の `parameters` にそのまま渡されます。 |
| `run(args)` | 実行関数。`args` は `dict`（ツールの引数）。戻り値は `str`（結果テキスト）。 |

- ファイル名は `_` で始まらないこと（`_*.py` は読み込まれません）。
- 1 ファイルにつき **1 ツール** です。複数ツールを出したい場合はファイルを分けてください。
- 追加・変更後は **Bot の再起動** で反映されます。

## 新規ツールの追加手順

1. `project/tools/` に新しい `〇〇.py` を置く。
2. 上記の `TOOL_NAME`, `TOOL_DESCRIPTION`, `TOOL_PARAMS`, `run(args)` を定義する。
3. Bot を再起動する。
4. Discord で「〇〇して」などと依頼すると、LLM がそのツールを選んで実行する。

## サンプル

- **memo_tool.py** … プロジェクト内のメモを読み書きするツール（`memo`）。
- **current_time_tool.py** … 現在日時を返すツール（`get_current_time`）。

## TOOL_PARAMS の例

```python
# 必須引数のみ
TOOL_PARAMS = {
    "type": "object",
    "properties": {"message": {"type": "string"}},
    "required": ["message"],
}

# 任意引数あり
TOOL_PARAMS = {
    "type": "object",
    "properties": {
        "timezone": {"type": "string", "description": "IANAタイムゾーン（例: Asia/Tokyo）"},
    },
    "required": [],
}
```

## 注意

- `run(args)` 内で例外が出ると、「カスタムツール実行エラー: ...」としてユーザーに返ります。
- ファイルの読み書きはプロジェクトフォルダ（`project`）内に留め、パスに `..` を含めないようにしてください。
