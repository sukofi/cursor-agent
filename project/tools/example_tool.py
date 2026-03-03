# カスタムツールのサンプル。Bot 起動時に project/tools から自動読み込みされます。

TOOL_NAME = "echo_message"
TOOL_DESCRIPTION = "受け取ったメッセージをそのまま返す。テスト用。"
TOOL_PARAMS = {
    "type": "object",
    "properties": {"message": {"type": "string"}},
    "required": ["message"],
}


def run(args):
    return args.get("message", "")
