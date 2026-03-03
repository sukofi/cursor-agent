# メモの読み取り・追記ツール。Bot 起動時に project/tools から自動読み込みされます。
# メモファイル: project/knowledge/agent_memo.md

import os

# agent_bot の WORKING_DIR は agent_bot.py のディレクトリ基準の 'project'
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKING_DIR = os.path.dirname(_THIS_DIR)  # project
_MEMO_PATH = os.path.join(_WORKING_DIR, "knowledge", "agent_memo.md")

TOOL_NAME = "memo"
TOOL_DESCRIPTION = "プロジェクト内のエージェント用メモを読む、または追記する。覚えておくこと・メモを残すときに使う。"
TOOL_PARAMS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": "read=メモを読む, append=メモに追記する",
        },
        "content": {
            "type": "string",
            "description": "append のときに追記する内容",
        },
    },
    "required": ["action"],
}


def run(args):
    action = (args.get("action") or "").strip().lower()
    if action not in ("read", "append"):
        return "エラー: action は read または append を指定してください。"

    if action == "read":
        if not os.path.isfile(_MEMO_PATH):
            return "メモはまだありません。"
        try:
            with open(_MEMO_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"メモの読み取りエラー: {e}"

    # append
    content = args.get("content") or ""
    if not content.strip():
        return "エラー: append のときは content を指定してください。"
    try:
        os.makedirs(os.path.dirname(_MEMO_PATH), exist_ok=True)
        with open(_MEMO_PATH, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"\n[{datetime.now().isoformat()}] {content.strip()}\n")
        return "メモに追記しました。"
    except Exception as e:
        return f"メモの追記エラー: {e}"
