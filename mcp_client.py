# MCP (Model Context Protocol) クライアント。
# project/mcp_servers.json で複数サーバーを指定するか、環境変数 MCP_SERVER_CMD で 1 つ指定。
# ツール一覧を取得して Ollama 用の function 形式に変換し、Bot 稼働中はセッションを保持して call_tool で実行する。

import asyncio
import json
import os
import sys

# project フォルダのパス（agent_bot.py と同じ並びで mcp_client.py がある前提）
_PROJECT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "project")
_MCP_SERVERS_JSON = os.path.join(_PROJECT_DIR, "mcp_servers.json")

# mcp が未インストールの場合は MCP 機能はスキップする（Python 3.10+ と pip install mcp が必要）
try:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    ClientSession = None
    stdio_client = None
    StdioServerParameters = None

# ツール名 → セッション（複数 MCP 対応でどのサーバーに聞くか）
_mcp_tool_to_session = {}
# MCP ツール名の集合。実行ディスパッチ用。
MCP_TOOL_NAMES = set()


def _load_mcp_server_config():
    """project/mcp_servers.json を読んで [(command, args), ...] を返す。無ければ []。"""
    if not os.path.isfile(_MCP_SERVERS_JSON):
        return []
    try:
        with open(_MCP_SERVERS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cmd = item.get("command")
        if not cmd:
            continue
        args = item.get("args")
        if args is None:
            args = []
        if not isinstance(args, list):
            args = [str(args)]
        out.append((str(cmd).strip(), [str(a) for a in args]))
    return out


def _parse_mcp_cmd(cmd_str):
    """MCP_SERVER_CMD を command と args に分割する。"""
    s = (cmd_str or "").strip()
    if not s:
        return None, None
    parts = s.split()
    if not parts:
        return None, None
    return parts[0], parts[1:]


def _tool_to_ollama_schema(tool):
    """MCP の Tool を Ollama の function 形式に変換。"""
    if isinstance(tool, dict):
        name = tool.get("name", "unknown")
        description = tool.get("description", "")
        input_schema = tool.get("inputSchema")
    else:
        name = getattr(tool, "name", "unknown")
        description = getattr(tool, "description", "") or ""
        input_schema = getattr(tool, "inputSchema", None)
    if input_schema is None:
        params = {"type": "object", "properties": {}, "required": []}
    elif isinstance(input_schema, dict):
        params = input_schema
    else:
        params = getattr(input_schema, "model_dump", None)
        if callable(params):
            params = params()
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}, "required": []}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description or f"MCP ツール: {name}",
            "parameters": params,
        },
    }


async def _hold_mcp_connection(bot, server_params, tools_list_ref):
    """バックグラウンドで MCP に接続し、ツールを tools_list_ref に追加してセッションを保持する。"""
    global _mcp_tool_to_session, MCP_TOOL_NAMES
    names = set()
    if not HAS_MCP or stdio_client is None or ClientSession is None:
        return
    try:
        async with stdio_client(server_params, errlog=sys.stderr) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                # ListToolsResult.tools またはリストそのまま
                tools = getattr(tools_result, "tools", None) if tools_result is not None else None
                if tools is None and isinstance(tools_result, list):
                    tools = tools_result
                tools = tools or []
                schemas = []
                for t in tools:
                    try:
                        schema = _tool_to_ollama_schema(t)
                        schemas.append(schema)
                        names.add(schema["function"]["name"])
                    except Exception:
                        continue
                if schemas:
                    tools_list_ref.extend(schemas)
                    MCP_TOOL_NAMES.update(names)
                    for n in names:
                        _mcp_tool_to_session[n] = session
                # Bot が終了するまでこのコンテキストを維持
                if bot:
                    await bot.wait_until_closed()
                else:
                    await asyncio.Future()
    except Exception as e:
        sys.stderr.write(f"[MCP] 接続エラー: {e}\n")
        sys.stderr.flush()
    finally:
        for n in names:
            _mcp_tool_to_session.pop(n, None)
        MCP_TOOL_NAMES.difference_update(names)


def start_mcp_background(bot, tools_list_ref):
    """MCP サーバーに接続するバックグラウンドタスクを開始する。on_ready から呼ぶ。
    project/mcp_servers.json があれば複数サーバーを起動。無ければ MCP_SERVER_CMD の 1 件のみ。"""
    if not HAS_MCP:
        return None
    configs = _load_mcp_server_config()
    if not configs:
        cmd = os.environ.get("MCP_SERVER_CMD", "").strip()
        command, args = _parse_mcp_cmd(cmd)
        if command:
            configs = [(command, args or [])]
    if not configs:
        return None
    tasks = []
    for command, args in configs:
        try:
            server_params = StdioServerParameters(command=command, args=args)
            t = asyncio.create_task(_hold_mcp_connection(bot, server_params, tools_list_ref))
            tasks.append(t)
        except Exception as e:
            sys.stderr.write(f"[MCP] パラメータエラー ({command}): {e}\n")
            sys.stderr.flush()
    return tasks


async def mcp_call_tool(name, args):
    """MCP ツールを実行する。戻り値は文字列。"""
    if name not in MCP_TOOL_NAMES:
        return f"MCP ツール実行エラー: 不明なツール '{name}' です。"
    session = _mcp_tool_to_session.get(name)
    if session is None:
        return "MCP ツール実行エラー: そのツールの MCP セッションが接続されていません。"
    try:
        result = await session.call_tool(name, args or {})
        # 戻り値は CallToolResult など。content がリストのことがある
        content = getattr(result, "content", None) or result
        if isinstance(content, list):
            texts = []
            for part in content:
                if hasattr(part, "text"):
                    texts.append(part.text)
                elif isinstance(part, dict) and "text" in part:
                    texts.append(part["text"])
                elif isinstance(part, str):
                    texts.append(part)
            return "\n".join(texts) if texts else str(content)
        if hasattr(content, "text"):
            return content.text
        if isinstance(content, str):
            return content
        return str(content)
    except Exception as e:
        return f"MCPツール実行エラー: {e}"
