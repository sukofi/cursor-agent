# 現在日時を返すツール。Bot 起動時に project/tools から自動読み込みされます。

from datetime import datetime

TOOL_NAME = "get_current_time"
TOOL_DESCRIPTION = "現在の日時を返す。タイムゾーンを指定できる（省略時はローカル時刻）。"
TOOL_PARAMS = {
    "type": "object",
    "properties": {
        "timezone": {
            "type": "string",
            "description": "IANAタイムゾーン（例: Asia/Tokyo, America/New_York）。省略時はシステムのローカル時刻。",
        },
    },
    "required": [],
}


def run(args):
    tz_name = (args.get("timezone") or "").strip()
    if not tz_name:
        now = datetime.now()
        return f"現在の日時（ローカル）: {now.strftime('%Y年%m月%d日 %H:%M:%S')}"
    try:
        import zoneinfo
    except ImportError:
        try:
            from backports import zoneinfo
        except ImportError:
            return "タイムゾーン指定には Python 3.9+ の zoneinfo または backports.zoneinfo が必要です。省略して再度呼んでください。"
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
        now = datetime.now(tz)
        return f"現在の日時（{tz_name}）: {now.strftime('%Y年%m月%d日 %H:%M:%S')}"
    except Exception as e:
        return f"タイムゾーンエラー: {e}（例: Asia/Tokyo で指定してください）"
