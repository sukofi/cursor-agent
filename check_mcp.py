#!/usr/bin/env python3
# MCP 接続の事前確認用スクリプト。
# 用法: python check_mcp.py
# - mcp が import できるか、project/mcp_servers.json または MCP_SERVER_CMD が設定されているか、
#   設定されていれば実際に接続してツール一覧を取得できるかを表示する。

import asyncio
import json
import os
import sys

_PROJECT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "project")
_MCP_SERVERS_JSON = os.path.join(_PROJECT_DIR, "mcp_servers.json")


def _load_config():
    """[(command, args), ...] を返す。mcp_servers.json 優先、無ければ MCP_SERVER_CMD。"""
    if os.path.isfile(_MCP_SERVERS_JSON):
        try:
            with open(_MCP_SERVERS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict) or not item.get("command"):
                continue
            args = item.get("args")
            if args is None:
                args = []
            if not isinstance(args, list):
                args = [str(args)]
            out.append((str(item["command"]).strip(), [str(a) for a in args]))
        return out
    cmd = os.environ.get("MCP_SERVER_CMD", "").strip()
    if not cmd:
        return []
    parts = cmd.split()
    return [(parts[0], parts[1:])] if parts else []


def main():
    print("=== MCP 接続チェック ===\n")
    print(f"Python: {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print("⚠️  mcp パッケージは Python 3.10+ が必要です。この環境では MCP は無効になります。\n")
    print()

    # 1. mcp の import
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
        print("✅ mcp パッケージ: 利用可能")
    except ImportError as e:
        print("❌ mcp パッケージ: 利用できません")
        print(f"   {e}")
        print("   → pip install mcp を実行してください（Python 3.10+ が必要）")
        return
    print()

    # 2. 設定（mcp_servers.json or MCP_SERVER_CMD）
    configs = _load_config()
    if not configs:
        print("⚠️  MCP の設定がありません。")
        print("   project/mcp_servers.json を作成するか、.env に MCP_SERVER_CMD=... を設定してください。")
        return
    if os.path.isfile(_MCP_SERVERS_JSON):
        print(f"✅ project/mcp_servers.json: {len(configs)} 件のサーバー")
    else:
        print(f"✅ MCP_SERVER_CMD: 1 件のサーバー")
    print()

    # 3. 実際に接続してツール一覧を取得（各サーバー）
    async def try_connect_one(command, args, index, total):
        try:
            params = StdioServerParameters(command=command, args=args)
        except Exception as e:
            print(f"[{index}/{total}] ❌ パラメータエラー: {e}")
            return
        label = f"{command} {' '.join(args[:2])}{'...' if len(args) > 2 else ''}"
        print(f"[{index}/{total}] {label} に接続中...")
        try:
            async with stdio_client(params, errlog=sys.stderr) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    tools = getattr(result, "tools", None) or (result if isinstance(result, list) else [])
                    tools = tools or []
                    print(f"       ✅ 接続成功。ツール数: {len(tools)}")
                    for i, t in enumerate(tools[:5]):
                        name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else "?")
                        print(f"          {i+1}. {name}")
                    if len(tools) > 5:
                        print(f"          ... 他 {len(tools) - 5} 件")
        except FileNotFoundError as e:
            print(f"       ❌ コマンドが見つかりません: {e}")
        except Exception as e:
            print(f"       ❌ 接続エラー: {e}")

    async def run_all():
        for i, (command, args) in enumerate(configs, 1):
            await try_connect_one(command, args, i, len(configs))
            print()

    asyncio.run(run_all())
    print("=== チェック終了 ===")


if __name__ == "__main__":
    main()
