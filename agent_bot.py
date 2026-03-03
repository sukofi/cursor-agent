import os
import discord
from discord.ext import commands

try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_env_path)
except ImportError:
    pass
from discord import ui
import subprocess
import json
import sys
import tempfile
import time
try:
    import fcntl
except ImportError:
    fcntl = None  # Windows では未使用
import re
import webbrowser
import urllib.request
import urllib.parse
import asyncio
import uuid
import importlib.util
from datetime import datetime

try:
    from duckduckgo_search import DDGS
    HAS_WEB_SEARCH = True
except ImportError:
    HAS_WEB_SEARCH = False

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

# LLM バックエンド: Ollama 単体。思考・解答とも qwen3-swallow:8b。
# 未登録のときはプロジェクト直下で: ollama create qwen3-swallow:8b -f Modelfile
# （Modelfile は Hugging Face の GGUF を参照。初回はダウンロードで数分かかります）
try:
    import ollama
    OLLAMA_MODEL_THINKING = os.environ.get("OLLAMA_MODEL_THINKING", "qwen3-swallow:8b")
    OLLAMA_MODEL_OUTPUT = os.environ.get("OLLAMA_MODEL_OUTPUT", "qwen3-swallow:8b")
    # 思考ステップをスキップすると応答が約2倍速く（1回のLLM呼び出しのみ）。.env で OLLAMA_SKIP_THINKING=1
    OLLAMA_SKIP_THINKING = os.environ.get("OLLAMA_SKIP_THINKING", "").strip().lower() in ("1", "true", "yes")
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False
    OLLAMA_MODEL_THINKING = ""
    OLLAMA_MODEL_OUTPUT = ""
    OLLAMA_SKIP_THINKING = False

# --- 設定 ---
# 権限: 削除以外はすべて付与。ファイル作成・実行・ウェブ・Git は自律的に実行してよい。
# プログラム作成は WORKING_DIR（project）内のみなので、フルディスクアクセスは不要。
ALLOW_DELETE = False  # 削除のみ不可（ファイル・ディレクトリの削除は行わない）
ALLOW_SELENIUM = True  # Selenium によるブラウザ操作（ページ表示・クリック・入力・スクショ）を許可する
ALLOW_SHELL_COMMAND = True  # コマンドプロンプト（ターミナル）でPCを操作する権限を付与する
ALLOW_DESKTOP = True  # デスクトップにフォルダ作成などを行う権限を付与する（※Desktop 操作時のみフルディスクが必要になることがある）

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
if not TOKEN:
    print("エラー: .env に DISCORD_BOT_TOKEN を設定してください。")
    sys.exit(1)
MY_USER_ID = 965085512861900800  # 👈 あなたのDiscordユーザーIDを入れてください
# 作成したツール関係はすべて project に保存する
#   project/           … 作成するプログラム・スクリプト（write_file の保存先）
#   project/tools/      … カスタムツール .py（Bot が自作するツールもここに作成）
#   project/knowledge/  … スキル登録 .md（save_skill の保存先）、agent_profile.md
WORKING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project')
KNOWLEDGE_DIR = os.path.join(WORKING_DIR, 'knowledge')  # ナレッジ・スキル説明の保存先
CUSTOM_TOOLS_DIR = os.path.join(WORKING_DIR, 'tools')   # カスタムツール .py の保存先（作成したツールもここ）
AGENT_PROFILE_PATH = os.path.join(KNOWLEDGE_DIR, 'agent_profile.md')  # 自分（Bot）に関する情報の専用ファイル
GITHUB_REPO_URL = "https://github.com/sukofi/cursor-agent.git"  # ユーザーが「保存して」と言ったときに push する先
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))  # agent_bot.py があるディレクトリ（リポジトリルート）
# リアルタイムモニター: 別チャンネルでターミナル状況を常時確認。チャンネルIDを入れる（Discordでチャンネル右クリック→IDをコピー、開発者モード要）
# None のときは自律キュー実行で get_autonomous_channel のフォールバック（最初の送信可能チャンネル or DM）を使う。投稿先を確実に指定したい場合はここを設定すること。
MONITOR_CHANNEL_ID = None  # モニターチャンネル（None でタスク開始・思考・ツール実行などのチャンネル投稿をしない）

# --- LLM 応答待ち ---
LLM_RESPONSE_TIMEOUT_SEC = int(os.environ.get("LLM_RESPONSE_TIMEOUT_SEC", "600"))  # 1回の応答の最大待ち時間（秒）。既定10分。Ollama が遅い場合は .env で増やす

# --- 自律実行（タスクキュー）---
AUTONOMOUS_QUEUE_INTERVAL_SEC = 30 * 60  # 30分ごとにキューをチェック
AUTONOMOUS_TASKS_PATH = os.path.join(WORKING_DIR, "autonomous_tasks.json")

# --- Bot からチャンネルへの不定期投稿（レポート＋次を作成）---
PROACTIVE_CHANNEL_ID = MONITOR_CHANNEL_ID  # 投稿先チャンネル（None で無効）
PROACTIVE_INTERVAL_MIN_SEC = 1 * 60 * 60   # 最短 1 時間
PROACTIVE_INTERVAL_MAX_SEC = 6 * 60 * 60   # 最長 6 時間
# プロアクティブ時の指示：最近のプログラム・スキルのレポートを投稿し、続けて次の便利機能を1つ作成
PROACTIVE_INSTRUCTION = (
    "【レポートと継続開発】まず list_files と list_skills で現在のプロジェクト・スキルを確認し、"
    "最近作成・更新したプログラムやスキルを簡潔なレポートにまとめ、このチャンネルに投稿してください。"
    "続けて、ユーザーの作業効率化や支援に役立つ新しい便利機能を1つ決め、write_file で作成し run_script で検証、"
    "問題なければ save_skill で登録してください。完了したら簡潔に報告してください。"
)

# --- 24時間継続：便利機能を作り続ける ---
# タスク完了時やキューが空のときに追加する指示（Bot がユーザー支援のために進化し続ける）
CONTINUOUS_CREATION_INSTRUCTION = (
    "ユーザーの支援のため、新しい便利ツール・スクリプト・自動化を1つ作成してください。"
    "web_search でトレンドやニーズを調べ、list_skills で既存と被らないものを選び、"
    "write_file → run_script で検証 → save_skill で登録。完了したら簡潔に報告してください。"
)

if not os.path.exists(WORKING_DIR):
    os.makedirs(WORKING_DIR)
os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
os.makedirs(CUSTOM_TOOLS_DIR, exist_ok=True)
DAILY_LOG_DIR = os.path.join(WORKING_DIR, "daily_log")
os.makedirs(DAILY_LOG_DIR, exist_ok=True)


def _get_today_log_path():
    """本日の作業ログファイルパスを返す。"""
    return os.path.join(DAILY_LOG_DIR, datetime.now().strftime("%Y-%m-%d") + ".txt")


def append_daily_log(entry):
    """1日の作業内容をテキストで追記。23時レポートの元になる。"""
    if not entry or not str(entry).strip():
        return
    path = _get_today_log_path()
    ts = datetime.now().strftime("%H:%M")
    line = f"[{ts}] {str(entry).strip()}\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# --- チャンネル別 Webhook（スキルリスト・ターミナル・今日やったこと・SEO・AI）---
# Webhook は全て .env に記載する。以下の環境変数を設定すること。
#   DISCORD_WEBHOOK_SKILLS_LIST, DISCORD_WEBHOOK_TERMINAL, DISCORD_WEBHOOK_TODAY_DIARY,
#   DISCORD_WEBHOOK_SEO, DISCORD_WEBHOOK_AI
# （未設定のキーのみ project/discord_webhooks.json で補完可能）
# スキルリストを「編集で更新」する場合はスキルリストチャンネルのIDを指定（Discordでチャンネル右クリック→IDをコピー）
SKILLS_LIST_CHANNEL_ID = None
_tmp = os.environ.get("DISCORD_SKILLS_LIST_CHANNEL_ID", "").strip()
if _tmp.isdigit():
    SKILLS_LIST_CHANNEL_ID = int(_tmp)
# ニュースチャンネルで「取得して」と投稿したときに即実行する用のチャンネルID（任意）
SEO_NEWS_CHANNEL_ID = None
AI_NEWS_CHANNEL_ID = None
_tmp_seo = os.environ.get("DISCORD_SEO_NEWS_CHANNEL_ID", "").strip()
_tmp_ai = os.environ.get("DISCORD_AI_NEWS_CHANNEL_ID", "").strip()
if _tmp_seo.isdigit():
    SEO_NEWS_CHANNEL_ID = int(_tmp_seo)
if _tmp_ai.isdigit():
    AI_NEWS_CHANNEL_ID = int(_tmp_ai)
DISCORD_WEBHOOK_KEYS = ("skills_list", "terminal", "today_diary", "seo", "ai")
SKILLS_LIST_STATE_PATH = os.path.join(WORKING_DIR, "skills_list_state.json")
_env_webhooks = {
    "skills_list": os.environ.get("DISCORD_WEBHOOK_SKILLS_LIST", "").strip(),
    "terminal": os.environ.get("DISCORD_WEBHOOK_TERMINAL", "").strip(),
    "today_diary": os.environ.get("DISCORD_WEBHOOK_TODAY_DIARY", "").strip(),
    "seo": os.environ.get("DISCORD_WEBHOOK_SEO", "").strip(),
    "ai": os.environ.get("DISCORD_WEBHOOK_AI", "").strip(),
}
_discord_webhooks_path = os.path.join(WORKING_DIR, "discord_webhooks.json")
if os.path.isfile(_discord_webhooks_path):
    try:
        with open(_discord_webhooks_path, "r", encoding="utf-8") as f:
            _file_webhooks = json.load(f)
        for k in DISCORD_WEBHOOK_KEYS:
            if k in _file_webhooks and isinstance(_file_webhooks[k], str) and _file_webhooks[k].strip().startswith("https://discord.com/api/webhooks/"):
                if not _env_webhooks.get(k):
                    _env_webhooks[k] = _file_webhooks[k].strip()
    except Exception:
        pass


def get_webhook_url(channel_key):
    """チャンネルキー（skills_list, terminal, today_diary, seo, ai）に対応する Webhook URL を返す。"""
    return (_env_webhooks.get(channel_key) or "").strip()


def post_to_channel_webhook(channel_key, content, username=None):
    """指定チャンネル用 Webhook にメッセージを送信する。URL が未設定の場合は何もしない。"""
    url = get_webhook_url(channel_key)
    if not url or not url.startswith("https://discord.com/api/webhooks/"):
        return
    content = (content or "").strip()[:2000]
    if not content:
        return
    result = send_webhook(url, content, username=username)
    if result and ("エラー" in result or "HTTP" in result):
        try:
            sys.stderr.write(f"[Webhook {channel_key}] {result}\n")
            sys.stderr.flush()
        except Exception:
            pass


def get_current_date_str():
    """正しい日付を取得。WorldTimeAPI に問い合わせ、失敗時はシステム日時。戻り値は「2026年03月02日」形式。"""
    try:
        req = urllib.request.Request(
            "https://worldtimeapi.org/api/ip",
            headers={"User-Agent": "DiscordBot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode("utf-8"))
        dt_str = data.get("datetime") or ""
        if dt_str and len(dt_str) >= 10:
            # "2026-03-02T12:00:00..." -> 2026年03月02日
            y, m, d = dt_str[:10].split("-")
            return f"{y}年{m}月{d}日"
    except Exception:
        pass
    return datetime.now().strftime("%Y年%m月%d日")


def safe_remove(path):
    """削除権限が付与されていないため、削除は行わない。"""
    if not ALLOW_DELETE:
        return
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# --- 自律実行: タスクキュー（JSON）の読み書き ---
def _load_queue():
    """キューJSONを読み、リストで返す。"""
    try:
        if os.path.isfile(AUTONOMOUS_TASKS_PATH):
            with open(AUTONOMOUS_TASKS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_queue(tasks):
    """タスクリストをキューJSONに書き込む。"""
    try:
        with open(AUTONOMOUS_TASKS_PATH, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def queue_add(instruction):
    """キューに1件追加。戻り値: (追加したタスク, 待ち件数)。"""
    tasks = _load_queue()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    task = {
        "id": str(uuid.uuid4()),
        "instruction": instruction.strip(),
        "status": "pending",
        "created_at": now,
        "done_at": None,
        "result_summary": None,
    }
    tasks.append(task)
    _save_queue(tasks)
    pending_count = sum(1 for t in tasks if t.get("status") == "pending")
    return task, pending_count


def queue_list():
    """pending のタスク一覧を返す（id, instruction, created_at のリスト）。"""
    tasks = _load_queue()
    return [
        {"id": t["id"], "instruction": t["instruction"][:80], "created_at": t.get("created_at", "")}
        for t in tasks
        if t.get("status") == "pending"
    ]


def queue_cancel(task_id_or_index):
    """指定IDまたは待ち順の番号（1始まり）で pending をキャンセル。見つかれば True。"""
    tasks = _load_queue()
    pending = [t for t in tasks if t.get("status") == "pending"]
    updated = False
    if task_id_or_index.isdigit():
        idx = int(task_id_or_index) - 1
        if 0 <= idx < len(pending):
            target = pending[idx]
            for t in tasks:
                if t.get("id") == target["id"]:
                    t["status"] = "cancelled"
                    t["done_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                    updated = True
                    break
    else:
        for t in tasks:
            if t.get("id") == task_id_or_index and t.get("status") == "pending":
                t["status"] = "cancelled"
                t["done_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                updated = True
                break
    if updated:
        _save_queue(tasks)
    return updated


def queue_get_next():
    """pending の先頭1件を取得し status を running に更新。なければ None。"""
    tasks = _load_queue()
    for t in tasks:
        if t.get("status") == "pending":
            t["status"] = "running"
            _save_queue(tasks)
            return t
    return None


def queue_mark_done(task_id, failed=False, result_summary=None):
    """指定IDのタスクを done または failed に更新。日次ログにも追記。"""
    tasks = _load_queue()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for t in tasks:
        if t.get("id") == task_id:
            t["status"] = "failed" if failed else "done"
            t["done_at"] = now
            if result_summary is not None:
                t["result_summary"] = result_summary[:500] if result_summary else None
            _save_queue(tasks)
            inst = (t.get("instruction") or "")[:120]
            summary = (t.get("result_summary") or "")[:80]
            label = "タスク失敗" if failed else "タスク完了"
            append_daily_log(f"{label}: {inst}" + (f" | {summary}" if summary else ""))
            return
    pass


# 自律ループの二重実行防止
_autonomous_busy = False


def get_autonomous_channel(bot):
    """自律実行で使うチャンネルを返す。MONITOR_CHANNEL_ID が設定されていればそのチャンネル。
    未設定時は、送信可能な最初のテキストチャンネル、なければ MY_USER_ID への DM を返す。
    確実に投稿先を指定したい場合は .env または定数で MONITOR_CHANNEL_ID を設定すること。"""
    if MONITOR_CHANNEL_ID:
        ch = bot.get_channel(MONITOR_CHANNEL_ID)
        if ch is not None:
            return ch
    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                if channel.permissions_for(guild.me).send_messages:
                    return channel
            except Exception:
                continue
    return None


async def get_autonomous_channel_async(bot):
    """get_autonomous_channel の非同期版。DM フォールバック時は create_dm が必要なため async。"""
    ch = get_autonomous_channel(bot)
    if ch is not None:
        return ch
    user = bot.get_user(MY_USER_ID)
    if user is not None:
        try:
            return await user.create_dm()
        except Exception:
            pass
    return None


async def proactive_channel_loop(bot):
    """不定期でチャンネルに「最近のプログラム・スキルのレポート」を投稿し、続けて次の便利機能を1つ作成する。"""
    import random
    if not PROACTIVE_CHANNEL_ID:
        return
    while True:
        try:
            delay = random.randint(PROACTIVE_INTERVAL_MIN_SEC, PROACTIVE_INTERVAL_MAX_SEC)
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            break
        try:
            channel = bot.get_channel(PROACTIVE_CHANNEL_ID)
            if not channel:
                continue
            await run_agent(channel, MY_USER_ID, PROACTIVE_INSTRUCTION)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            pass
        except Exception:
            pass


# チャンネル別スケジュール: 今日やったこと(23:00)、SEO/AIニュース(6:00)
_scheduler_last_diary_date = None
_scheduler_last_seo_date = None
_scheduler_last_ai_date = None


def run_seo_news_now():
    """SEOニュースを取得して該当Webhookに投稿。PLAN-B・海外SEO情報ブログから取得。"""
    if not get_webhook_url("seo"):
        return False
    content = _fetch_seo_news_with_sources(max_items=5)
    header = (
        "🔍 **SEOニュース**（[PLAN-B SEO最新情報](https://www.plan-b.co.jp/blog/tag/seo-news/) ・"
        "[海外SEO情報ブログ](https://www.suzukikenichi.com/blog/)）\n\n"
    )
    if content:
        post_to_channel_webhook("seo", header + content[:1900], username="SEOチャンネル")
    else:
        post_to_channel_webhook(
            "seo",
            header + "本日はニュースを取得できませんでした。しばらく経ってから「取得して」でもう一度お試しください。",
            username="SEOチャンネル",
        )
    return True


def run_ai_news_now():
    """AIニュースを取得して該当Webhookに投稿。Ledge.ai 優先・ニュース検索「AIニュース」を使用。"""
    if not get_webhook_url("ai"):
        return False
    content = _fetch_ai_news_with_sources(max_items=5)
    header = "🤖 **AIニュース**（[Ledge.ai](https://ledge.ai/) ・ニュース検索）\n\n"
    if content:
        post_to_channel_webhook("ai", header + content[:1900], username="AIチャンネル")
    else:
        post_to_channel_webhook(
            "ai",
            header + "本日はニュースを取得できませんでした。しばらく経ってから「取得して」でもう一度お試しください。",
            username="AIチャンネル",
        )
    return True


def run_today_diary_now():
    """今日やったことをレポート形式で該当Webhookに投稿（23時と同じ処理を即実行）。"""
    if not get_webhook_url("today_diary"):
        return False
    content = _get_today_diary_content()
    post_to_channel_webhook("today_diary", content, username="今日やったこと")
    return True


async def channel_scheduler_loop(bot):
    """毎日23時に「今日やったこと」、毎日6時にSEO・AIニュースを各Webhookに投稿する。"""
    global _scheduler_last_diary_date, _scheduler_last_seo_date, _scheduler_last_ai_date
    while True:
        try:
            await asyncio.sleep(55)
        except asyncio.CancelledError:
            break
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            # 23時: 今日やったこと
            if now.hour == 23 and _scheduler_last_diary_date != today:
                if run_today_diary_now():
                    _scheduler_last_diary_date = today
            # 6時: SEOニュース
            if now.hour == 6 and _scheduler_last_seo_date != today:
                if run_seo_news_now():
                    _scheduler_last_seo_date = today
            # 6時: AIニュース
            if now.hour == 6 and _scheduler_last_ai_date != today:
                if run_ai_news_now():
                    _scheduler_last_ai_date = today
        except Exception:
            pass


async def autonomous_loop(bot):
    """N分ごとにキューを1件消化。キューが空なら「次の便利機能を作成」を追加。完了後も次を追加して24時間作り続ける。"""
    global _autonomous_busy
    while True:
        try:
            await asyncio.sleep(AUTONOMOUS_QUEUE_INTERVAL_SEC)
        except asyncio.CancelledError:
            break

        try:
            if _autonomous_busy:
                continue
            task = queue_get_next()
            if not task:
                queue_add(CONTINUOUS_CREATION_INSTRUCTION)
                continue

            _autonomous_busy = True
            channel = await get_autonomous_channel_async(bot)
            if not channel:
                queue_mark_done(task["id"], failed=True, result_summary="モニターチャンネルが取得できません")
                _autonomous_busy = False
                continue

            try:
                await post_monitor(bot, "自律実行開始", task["instruction"][:150])
                await run_agent(channel, MY_USER_ID, task["instruction"])
                queue_mark_done(task["id"], failed=False)
                queue_add(CONTINUOUS_CREATION_INSTRUCTION)
            except Exception as e:
                queue_mark_done(task["id"], failed=True, result_summary=str(e)[:500])
                try:
                    await channel.send(f"🤖 **自律実行エラー:** {str(e)[:500]}")
                except Exception:
                    pass
                queue_add(CONTINUOUS_CREATION_INSTRUCTION)
            finally:
                _autonomous_busy = False
        except Exception:
            _autonomous_busy = False


# --- 承認用ボタンのクラス ---
class ApprovalView(ui.View):
    def __init__(self):
        super().__init__(timeout=60) # 60秒待機
        self.approved = None

    @ui.button(label="承認 (Approve)", style=discord.ButtonStyle.green)
    async def approve(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != MY_USER_ID: return
        self.approved = True
        self.stop()
        await interaction.response.send_message("✅ 実行を許可しました", ephemeral=True)

    @ui.button(label="却下 (Deny)", style=discord.ButtonStyle.red)
    async def deny(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != MY_USER_ID: return
        self.approved = False
        self.stop()
        await interaction.response.send_message("❌ 実行を拒否しました", ephemeral=True)

# --- ツール関数群 ---
def list_files():
    files = os.listdir(WORKING_DIR)
    return f"ファイル一覧: {', '.join(files)}"

def read_file(filename):
    path = os.path.join(WORKING_DIR, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def write_file(filename, content):
    """プロジェクトフォルダ（WORKING_DIR）内にのみファイルを作成する。"""
    if not filename or ".." in filename or filename.startswith("/"):
        return "エラー: ファイル名はプロジェクトフォルダ内の相対パスのみ指定してください（例: main.py, src/hello.py）。"
    if content is None or (isinstance(content, str) and not content.strip()):
        return "エラー: content が空です。作成するプログラムのコード全体を content に含めて、write_file を再度呼び出してください。"
    path = os.path.abspath(os.path.join(WORKING_DIR, filename))
    base = os.path.abspath(WORKING_DIR)
    if not path.startswith(base):
        return "エラー: 作成できるのはプロジェクトフォルダ内のみです。"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"{filename} をプロジェクトフォルダに保存しました。"

def run_script(filename, timeout_sec=30):
    """WORKING_DIR 内の Python ファイルを実行し、標準出力・エラーを返す。"""
    path = os.path.abspath(os.path.join(WORKING_DIR, filename))
    base = os.path.abspath(WORKING_DIR)
    if not path.startswith(base) or ".." in filename:
        return "エラー: プロジェクトフォルダ外のファイルは実行できません。"
    if not path.endswith(".py"):
        return "エラー: .py ファイルのみ実行できます。"
    if not os.path.isfile(path):
        return f"エラー: ファイルがありません: {filename}"
    try:
        r = subprocess.run(
            [sys.executable, path],
            cwd=WORKING_DIR,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            encoding="utf-8",
            errors="replace",
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if r.returncode != 0:
            return f"終了コード: {r.returncode}\nstdout:\n{out}\nstderr:\n{err}"
        return f"stdout:\n{out}" + (f"\nstderr:\n{err}" if err else "")
    except subprocess.TimeoutExpired:
        return "エラー: 実行がタイムアウトしました。"
    except Exception as e:
        return f"実行エラー: {e}"

# モニター同一投稿の連続防止（同じ内容を数秒内に1回だけ送る）
_last_monitor_key = None
_last_monitor_time = 0.0
_monitor_debounce_sec = 4

async def post_monitor(bot, action_label, detail=""):
    """モニターチャンネルまたはターミナルWebhookにリアルタイムログを1件送信。同一内容の連続は debounce で1回だけ。"""
    global _last_monitor_key, _last_monitor_time
    use_channel = bool(MONITOR_CHANNEL_ID and bot)
    use_webhook = bool(get_webhook_url("terminal"))
    if not use_channel and not use_webhook:
        return
    key = (action_label, (detail or "")[:300])
    now = time.time()
    if key == _last_monitor_key and (now - _last_monitor_time) < _monitor_debounce_sec:
        return
    _last_monitor_key = key
    _last_monitor_time = now
    ts = datetime.now().strftime("%H:%M:%S")
    msg = f"`[{ts}]` {action_label}"
    if detail:
        msg += f" {detail[:400]}"
    msg = msg[:2000]
    if use_channel:
        try:
            ch = bot.get_channel(MONITOR_CHANNEL_ID)
            if ch:
                await ch.send(msg)
        except Exception:
            pass
    post_to_channel_webhook("terminal", msg, username="ターミナル")

async def run_script_streaming(bot, filename, timeout_sec=30):
    """run_script の非同期版。標準出力をリアルタイムでモニターチャンネルに送る。戻り値は run_script と同じ形式。"""
    path = os.path.abspath(os.path.join(WORKING_DIR, filename))
    base = os.path.abspath(WORKING_DIR)
    if not path.startswith(base) or ".." in filename:
        return "エラー: プロジェクトフォルダ外のファイルは実行できません。"
    if not path.endswith(".py"):
        return "エラー: .py ファイルのみ実行できます。"
    if not os.path.isfile(path):
        return f"エラー: ファイルがありません: {filename}"
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=WORKING_DIR,
        )
        lines = []
        buf = ""
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout_sec)
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                lines.append(decoded)
                if MONITOR_CHANNEL_ID and bot:
                    try:
                        ch = bot.get_channel(MONITOR_CHANNEL_ID)
                        if ch:
                            await ch.send(f"```\n{decoded.rstrip()}\n```"[:2000])
                    except Exception:
                        pass
                post_to_channel_webhook("terminal", f"```\n{decoded.rstrip()}\n```"[:2000], username="ターミナル")
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "エラー: 実行がタイムアウトしました。\n" + "".join(lines)
        await proc.wait()
        out = "".join(lines)
        if proc.returncode != 0:
            return f"終了コード: {proc.returncode}\nstdout:\n{out}"
        return f"stdout:\n{out.strip()}"
    except Exception as e:
        return f"実行エラー: {e}"

def take_screenshot():
    """画面のスクリーンショットを撮り、ファイルパスを返す。失敗時は None。"""
    path = None
    try:
        fd, path = tempfile.mkstemp(suffix=".png", prefix="bot_screen_")
        os.close(fd)
        if sys.platform == "darwin":
            r = subprocess.run(
                ["screencapture", "-x", "-t", "png", path],
                capture_output=True,
                timeout=10,
                cwd=WORKING_DIR,
            )
        else:
            safe_remove(path)
            return None
        if r.returncode != 0:
            safe_remove(path)
            return None
        return path
    except Exception:
        safe_remove(path)
        return None

def take_screen_video(seconds=5):
    """画面を指定秒数だけ録画し、ファイルパスを返す。ffmpeg が必要。失敗時は None。"""
    try:
        path = os.path.join(tempfile.gettempdir(), f"bot_video_{int(time.time())}.mp4")
        if sys.platform == "darwin":
            # avfoundation: 0=画面 1=カメラ
            r = subprocess.run(
                ["ffmpeg", "-y", "-f", "avfoundation", "-i", "1:0", "-t", str(seconds),
                 "-vf", "scale=1280:-1", path],
                capture_output=True,
                timeout=seconds + 15,
            )
        else:
            return None
        if r.returncode != 0 or not os.path.isfile(path):
            safe_remove(path)
            return None
        return path
    except Exception:
        return None

def list_skills():
    """ナレッジフォルダ内のスキル一覧を返す。各スキルの名前と概要。"""
    if not os.path.isdir(KNOWLEDGE_DIR):
        return "ナレッジフォルダはまだありません。"
    lines = []
    for f in sorted(os.listdir(KNOWLEDGE_DIR)):
        if not f.endswith(".md"):
            continue
        name = f[:-3]
        path = os.path.join(KNOWLEDGE_DIR, f)
        try:
            with open(path, "r", encoding="utf-8") as fp:
                first = fp.readline().strip()
                if first.startswith("script:"):
                    second = fp.readline().strip()
                    summary = second or first
                else:
                    summary = first[:80] if first else "(説明なし)"
        except Exception:
            summary = "(読めませんでした)"
        lines.append(f"・{name}: {summary}")
    return "登録スキル:\n" + "\n".join(lines) if lines else "登録されているスキルはまだありません。"

def read_skill(skill_name):
    """ナレッジからスキル説明を読む。script: で始まる行に実行する .py が書いてある。"""
    safe = skill_name.strip().replace("..", "").replace("/", "")
    if not safe:
        return "エラー: スキル名を指定してください。"
    path = os.path.join(KNOWLEDGE_DIR, safe + ".md")
    if not os.path.isfile(path):
        return f"エラー: スキル '{skill_name}' は見つかりません。list_skills で一覧を確認してください。"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def save_skill(skill_name, description, script_filename):
    """作成したプログラムをナレッジ・スキルとして登録する。ツール関係はすべて project 内に保存。次から list_skills → read_skill で呼び出せる。"""
    safe = skill_name.strip().replace("..", "").replace("/", "").replace(" ", "_")
    if not safe:
        return "エラー: スキル名を指定してください。"
    script = (script_filename or "").strip()
    if not script:
        return "エラー: script_filename を指定してください（例: tools/xxx.py）。"
    if ".." in script or script.startswith("/") or os.path.isabs(script):
        return "エラー: script_filename は project 内の相対パスのみ指定してください（例: tools/foo.py, main.py）。"
    path_abs = os.path.abspath(os.path.join(WORKING_DIR, script))
    if not path_abs.startswith(os.path.abspath(WORKING_DIR)):
        return "エラー: script_filename は project 内のパスのみ指定してください（例: tools/foo.py）。"
    path = os.path.join(KNOWLEDGE_DIR, safe + ".md")
    content = f"script: {script}\n\n{description.strip()}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"スキル '{safe}' をナレッジに登録しました。script: {script}"

def read_agent_profile():
    """自分（Bot）に関する情報が記載された専用ファイルを読む。"""
    if not os.path.isfile(AGENT_PROFILE_PATH):
        return "(まだ記録されていません)"
    with open(AGENT_PROFILE_PATH, "r", encoding="utf-8") as f:
        return f.read()

def save_agent_info(content):
    """ユーザーが提供した「自分（Bot）に関する情報」を専用ファイルに追記する。忘れないように必ず記録する。"""
    if not content or not str(content).strip():
        return "エラー: 記録する内容を指定してください。"
    line = str(content).strip()
    with open(AGENT_PROFILE_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return "自分に関する情報を専用ファイルに記録しました。"

def save_to_github(commit_message=""):
    """変更を GitHub (https://github.com/sukofi/cursor-agent.git) に push する。ユーザーが「保存して」「変更を保存して」と言ったときに使う。"""
    msg = (commit_message or "Update from Discord bot").strip()[:200]
    try:
        if not os.path.isdir(os.path.join(REPO_ROOT, ".git")):
            r = subprocess.run(
                ["git", "init"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0:
                return f"git init 失敗: {r.stderr or r.stdout}"
            r = subprocess.run(
                ["git", "remote", "add", "origin", GITHUB_REPO_URL],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0 and "already exists" not in (r.stderr or ""):
                return f"remote add 失敗: {r.stderr or r.stdout}"
        r = subprocess.run(
            ["git", "add", "-A"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            return f"git add 失敗: {r.stderr or r.stdout}"
        r = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            if "nothing to commit" in (r.stdout or "") or "nothing to commit" in (r.stderr or ""):
                return "コミットする変更がありませんでした。すでに最新です。"
            return f"git commit 失敗: {r.stderr or r.stdout}"
        r = subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            if "master" in (r.stderr or ""):
                r = subprocess.run(
                    ["git", "push", "-u", "origin", "master"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            if r.returncode != 0:
                return f"git push 失敗: {r.stderr or r.stdout}"
        return f"GitHub に保存しました: {GITHUB_REPO_URL} (commit: {msg})"
    except subprocess.TimeoutExpired:
        return "タイムアウトしました。"
    except FileNotFoundError:
        return "git コマンドが見つかりません。"
    except Exception as e:
        return f"エラー: {e}"

def web_search(query, max_results=10):
    """ウェブ検索（DuckDuckGo）。最新情報を得るため多めに取得。"""
    if not HAS_WEB_SEARCH:
        return "エラー: ウェブ検索には pip install duckduckgo-search が必要です。"
    try:
        results = list(DDGS().text(query, max_results=max_results))
    except Exception as e:
        return f"検索エラー: {e}"
    if not results:
        return "該当する結果がありませんでした。"
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        href = r.get("href", "")
        body = (r.get("body") or "")[:180]
        lines.append(f"{i}. {title}\n   {href}\n   {body}")
    return "\n\n".join(lines)


def _get_today_diary_content():
    """本日の作業ログ＋自律タスクをレポート形式で返す。23時投稿用。"""
    today = datetime.now().strftime("%Y-%m-%d")
    today_jp = datetime.now().strftime("%Y年%m月%d日")
    log_path = _get_today_log_path()
    report_lines = [
        f"# 📔 日付レポート",
        f"**日付:** {today_jp}",
        "",
        "## 本日の作業ログ",
    ]
    has_log = False
    if os.path.isfile(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                log_lines = [ln.rstrip() for ln in f if ln.strip()]
            if log_lines:
                has_log = True
                for ln in log_lines:
                    report_lines.append(f"- {ln}")
        except Exception:
            pass
    if not has_log:
        report_lines.append("- （ログなし）")
    report_lines.append("")
    report_lines.append("## 自律タスク（本日完了分）")
    tasks = _load_queue()
    done_today = [
        t for t in tasks
        if t.get("status") in ("done", "failed") and (t.get("done_at") or "")[:10] == today
    ]
    if done_today:
        for t in sorted(done_today, key=lambda x: x.get("done_at") or ""):
            icon = "✅" if t.get("status") == "done" else "⚠️"
            inst = (t.get("instruction") or "")[:150]
            summary = (t.get("result_summary") or "")[:100]
            report_lines.append(f"- {icon} {inst}")
            if summary:
                report_lines.append(f"  → {summary}")
    else:
        report_lines.append("- （なし）")
    return "\n".join(report_lines)[:1990]


# SEOニュース: PLAN-B (https://www.plan-b.co.jp/blog/tag/seo-news/) と suzukikenichi.com から取得
SEO_NEWS_SOURCE_QUERIES = [
    "site:plan-b.co.jp SEO 最新",
    "site:plan-b.co.jp SEO",
    "site:suzukikenichi.com SEO",
    "site:suzukikenichi.com 海外SEO",
]
SEO_NEWS_QUERIES = [
    "SEO ニュース 日本 最新",
    "SEO ニュース 国内",
    "検索エンジン 最適化 ニュース 日本",
    "SEO トレンド 日本",
    "Google アルゴリズム アップデート ニュース",
]
SEO_SOURCE_DOMAINS = ("plan-b.co.jp", "suzukikenichi.com")
# AIニュース: Ledge.ai (https://ledge.ai/) を優先し、ニュース検索「AIニュース」も利用
AI_NEWS_LEDGE_QUERIES = [
    "site:ledge.ai AI ニュース",
    "site:ledge.ai AI",
    "ledge.ai AI ニュース",
]
AI_NEWS_QUERIES = [
    "AI 人工知能 ニュース 日本 最新",
    "AI ニュース 国内",
    "人工知能 ニュース 日本",
    "ChatGPT ニュース 日本",
    "生成AI ニュース 国内",
]
LEDGE_AI_DOMAIN = "ledge.ai"

# 指定サイトから直接HTMLを取得して記事リンクを抽出（検索エンジン経由ではない）
AI_NEWS_SOURCE_URL = "https://ledge.ai/"
SEO_NEWS_SOURCE_URLS = [
    "https://www.plan-b.co.jp/blog/tag/seo-news/",
    "https://www.suzukikenichi.com/blog/",
]


def _fetch_article_links_from_url(page_url, max_items=5, min_title_len=10, url_path_contains=None):
    """指定URLのHTMLを取得し、記事らしいリンク（タイトル＋URL）を抽出。同一ドメインのみ。url_path_contains 指定時はパスにその文字列を含むリンクだけ採用。"""
    if not page_url or not page_url.strip().startswith(("http://", "https://")):
        return None
    page_url = page_url.strip()
    try:
        req = urllib.request.Request(
            page_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; DiscordBot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as res:
            raw = res.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    parsed_base = urllib.parse.urlparse(page_url)
    domain = parsed_base.netloc.lower()
    pattern = re.compile(
        r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    seen = set()
    items = []
    for m in pattern.finditer(raw):
        href = (m.group(1) or "").strip()
        title = re.sub(r"\s+", " ", (m.group(2) or "").strip())
        if not href or not title or len(title) < min_title_len:
            continue
        if href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        full_url = urllib.parse.urljoin(page_url, href)
        parsed = urllib.parse.urlparse(full_url)
        if parsed.netloc.lower() != domain:
            continue
        if url_path_contains and url_path_contains not in (parsed.path or ""):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        title_clean = title[:100].strip()
        if title_clean:
            items.append((title_clean, full_url))
        if len(items) >= max_items:
            break
    return items if items else None


def _format_article_lines(items, max_items=5):
    """(title, url) のリストを投稿用テキストに整形。"""
    if not items:
        return None
    lines = []
    for i, (title, url) in enumerate(items[:max_items], 1):
        lines.append(f"{i}. **{title}**\n   [記事を読む]({url})")
    return "\n\n".join(lines)[:2000]


def _fetch_ai_news_from_site(max_items=5):
    """Ledge.ai を直接フェッチして記事リンクを取得（/articles/ のみ）。"""
    items = _fetch_article_links_from_url(
        AI_NEWS_SOURCE_URL,
        max_items=max_items,
        min_title_len=15,
        url_path_contains="/articles/",
    )
    return _format_article_lines(items, max_items) if items else None


def _fetch_seo_news_from_sites(max_items=5):
    """PLAN-B と suzukikenichi.com を直接フェッチして記事リンクを取得（/blog/ の記事のみ）。"""
    all_items = []
    seen_urls = set()
    for url in SEO_NEWS_SOURCE_URLS:
        items = _fetch_article_links_from_url(
            url,
            max_items=max_items + 2,
            min_title_len=10,
            url_path_contains="/blog/",
        )
        if items:
            for title, link in items:
                if link not in seen_urls:
                    seen_urls.add(link)
                    all_items.append((title, link))
                    if len(all_items) >= max_items:
                        break
        if len(all_items) >= max_items:
            break
        time.sleep(1)
    return _format_article_lines(all_items, max_items) if all_items else None


def _fetch_news_one_query(query, max_items=5):
    """1クエリでニュースを取得。国内サイト優先。失敗時は None。"""
    if not HAS_WEB_SEARCH:
        return None
    try:
        # 多めに取得して国内優先でソートしたあと max_items に絞る
        results = list(DDGS().text(query, max_results=max_items + 10))
    except Exception:
        return None
    if not results:
        return None
    jp_domains = (".jp", "itmedia.co.jp", "nikkei.com", "reuters.co.jp", "cnet.com/japan",
                  "impress.co.jp", "atmarkit.co.jp", "ascii.jp", "gihyo.jp", "thinkit.co.jp",
                  "news.yahoo.co.jp", "japan.cnet.com", "techcrunch.com/japan", LEDGE_AI_DOMAIN,
                  *SEO_SOURCE_DOMAINS)
    def is_domestic(h):
        if not h:
            return False
        h_lower = h.lower()
        return any(d in h_lower for d in jp_domains) or h_lower.endswith(".jp")
    sorted_results = sorted(results, key=lambda r: (0 if is_domestic(r.get("href")) else 1))
    lines = []
    for i, r in enumerate(sorted_results[:max_items], 1):
        title = (r.get("title") or "").strip()[:100]
        href = (r.get("href") or "").strip()
        if title and href:
            lines.append(f"{i}. **{title}**\n   [記事を読む]({href})")
    return "\n\n".join(lines)[:2000] if lines else None


def _fetch_news_with_retry(queries, max_items=5, max_attempts=4, delay_sec=2):
    """複数クエリでリトライし、1件でも取れれば返す。確実に取得するため。"""
    for attempt in range(max_attempts):
        for q in queries:
            content = _fetch_news_one_query(q, max_items=max_items)
            if content:
                return content
            time.sleep(delay_sec)
    return None


def _fetch_news_for_webhook(query, max_items=5):
    """国内サイトを参考にニュースを取得（単一クエリ・後方互換）。確実な取得は _fetch_news_with_retry を使用。"""
    content = _fetch_news_one_query(query, max_items=max_items)
    if content:
        return content
    return "該当する結果がありませんでした。"


def _fetch_news_via_news_search(keywords, max_items=5):
    """DuckDuckGo のニュース検索（Google ニュース相当）で取得。レート制限対策で1回だけ試行。"""
    if not HAS_WEB_SEARCH:
        return None
    try:
        results = list(DDGS().news(keywords, max_results=max_items))
    except Exception:
        return None
    if not results:
        return None
    lines = []
    for i, r in enumerate(results[:max_items], 1):
        title = (r.get("title") or "").strip()[:100]
        url = (r.get("url") or r.get("href") or "").strip()
        if title and url:
            lines.append(f"{i}. **{title}**\n   [記事を読む]({url})")
    return "\n\n".join(lines)[:2000] if lines else None


def _fetch_ai_news_with_sources(max_items=5):
    """AIニュースを指定サイト（Ledge.ai）から直接フェッチ。失敗時のみ検索にフォールバック。"""
    # 1) Ledge.ai を直接フェッチ（指定サイトのみ）
    content = _fetch_ai_news_from_site(max_items=max_items)
    if content:
        return content
    time.sleep(2)
    # 2) フォールバック: 検索
    content = _fetch_news_with_retry(AI_NEWS_LEDGE_QUERIES, max_items=max_items, max_attempts=2, delay_sec=2)
    if content:
        return content
    content = _fetch_news_via_news_search("AIニュース", max_items=max_items)
    if content:
        return content
    return _fetch_news_with_retry(AI_NEWS_QUERIES, max_items=max_items, max_attempts=2, delay_sec=2)


def _fetch_seo_news_with_sources(max_items=5):
    """SEOニュースを指定サイト（PLAN-B・suzukikenichi.com）から直接フェッチ。失敗時のみ検索にフォールバック。"""
    # 1) 指定サイトを直接フェッチ（PLAN-B, suzukikenichi.com のみ）
    content = _fetch_seo_news_from_sites(max_items=max_items)
    if content:
        return content
    time.sleep(2)
    # 2) フォールバック: 検索
    return _fetch_news_with_retry(
        SEO_NEWS_SOURCE_QUERIES + SEO_NEWS_QUERIES,
        max_items=max_items,
        max_attempts=3,
        delay_sec=2,
    )


def fetch_webpage(url, max_chars=8000):
    """指定URLのウェブページを取得し、テキスト内容を返す。ウェブ操作の一環。"""
    if not url or not url.strip().startswith(("http://", "https://")):
        return "エラー: 有効なURL（http:// または https://）を指定してください。"
    url = url.strip()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DiscordBot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as res:
            raw = res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return f"HTTPエラー: {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return f"接続エラー: {e.reason}"
    except Exception as e:
        return f"取得エラー: {e}"
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", raw, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…(省略)"
    return text or "(本文を抽出できませんでした)"

def open_in_browser(url):
    """指定URLをデフォルトブラウザで開く。このPC上でブラウザが起動する。"""
    if not url or not url.strip().startswith(("http://", "https://")):
        return "エラー: 有効なURLを指定してください。"
    try:
        webbrowser.open(url.strip())
        return f"ブラウザで開きました: {url.strip()}"
    except Exception as e:
        return f"エラー: {e}"

def open_in_chrome(url):
    """指定URLをGoogle Chromeで開く。macOS用。launchd からも動くよう osascript を使用。"""
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        site_map = {
            "youtube": "https://www.youtube.com",
            "yt": "https://www.youtube.com",
            "google": "https://www.google.com",
            "github": "https://github.com",
        }
        lower = u.lower().replace(" ", "")
        if lower in site_map:
            u = site_map[lower]
        else:
            u = f"https://{u}" if u else "https://www.google.com"
    # launchd 下では open が GUI セッションに届かないことがある。複数方法を試す
    u_esc = u.replace("\\", "\\\\").replace('"', '\\"')
    cmds = [
        # ログインシェル経由（ユーザー環境を引き継ぐ）
        ["/bin/bash", "-l", "-c", f'open -a "Google Chrome" "{u}"'],
        # osascript（AppleScript 経由）
        ["osascript", "-e", f'tell application "Google Chrome" to open location "{u_esc}"'],
        # 直接 open
        ["open", "-a", "Google Chrome", u],
    ]
    last_err = ""
    for cmd in cmds:
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=8,
                env={**os.environ, "PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin"},
            )
            if r.returncode == 0:
                return f"Chrome で開きました: {u}"
            last_err = r.stderr or r.stdout or str(r.returncode)
        except Exception as e:
            last_err = str(e)
    return f"エラー: launchd 下では Chrome を開けない場合があります。ターミナルから python agent_bot.py で Bot を起動すると開けます。詳細: {last_err}"


async def list_webhooks(channel):
    """指定チャンネルのウェブフック一覧を取得する。権限付与済みで自律的に実行してよい。"""
    if not channel or not hasattr(channel, "webhooks"):
        return "エラー: チャンネルを取得できません。"
    try:
        webhooks = [w async for w in channel.webhooks()]
        if not webhooks:
            return "このチャンネルにはウェブフックがありません。create_webhook で作成できます。"
        lines = []
        for w in webhooks:
            name = getattr(w, "name", "?")
            wid = getattr(w, "id", "")
            lines.append(f"・{name} (ID: {wid})")
        return "ウェブフック一覧:\n" + "\n".join(lines)
    except discord.Forbidden:
        return "エラー: このチャンネルでウェブフックを取得する権限がありません。"
    except Exception as e:
        return f"エラー: {e}"


async def create_webhook(channel, name):
    """指定チャンネルにウェブフックを1つ作成する。戻り値のURLは送信用に保存してよい。権限付与済み。"""
    if not channel or not hasattr(channel, "create_webhook"):
        return "エラー: チャンネルを取得できません。"
    name = (name or "webhook").strip() or "webhook"
    try:
        webhook = await channel.create_webhook(name=name[:80])
        url = getattr(webhook, "url", None)
        if not url and hasattr(webhook, "id") and hasattr(webhook, "token"):
            url = f"https://discord.com/api/webhooks/{webhook.id}/{webhook.token}"
        if url:
            return f"ウェブフックを作成しました: {name}\nURL（送信用・秘密にすること）:\n{url}"
        return f"ウェブフックを作成しました: {name} (ID: {getattr(webhook, 'id', '')})"
    except discord.Forbidden:
        return "エラー: このチャンネルでウェブフックを作成する権限がありません。"
    except Exception as e:
        return f"エラー: {e}"


def send_webhook(webhook_url, content, username=None):
    """ウェブフックURLにメッセージを送信する。外部サービス連携や通知に使う。自律的に実行してよい。"""
    url = (webhook_url or "").strip()
    if not url or not url.startswith("https://discord.com/api/webhooks/"):
        return "エラー: 有効なDiscordウェブフックURLを指定してください（https://discord.com/api/webhooks/...）。"
    content = (content or "").strip()[:2000]
    if not content:
        return "エラー: 送信する内容を指定してください。"
    try:
        data = {"content": content}
        if username:
            data["username"] = str(username)[:80]
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/discord/discord-example-app, 1.0)",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            if res.status in (200, 204):
                return "ウェブフックで送信しました。"
            return f"送信完了（ステータス: {res.status}）"
    except urllib.error.HTTPError as e:
        body = (e.read().decode("utf-8", errors="replace") if e.fp else "")[:300]
        return f"HTTPエラー: {e.code} {e.reason} {body}"
    except Exception as e:
        return f"エラー: {e}"


def run_shell_command(command):
    """このPCでシェルコマンドを実行する。アプリ起動・URLを開く・ターミナル操作など。macOS用。
    例: open -a Safari → open -a Safari、YouTubeを開く → open -a 'Google Chrome' 'https://youtube.com'"""
    if not command or not str(command).strip():
        return "エラー: 実行するコマンドを指定してください。"
    cmd = str(command).strip()
    try:
        r = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=REPO_ROOT,
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if r.returncode == 0:
            return f"実行完了。\n標準出力:\n{out}" if out else "実行完了しました。"
        return f"終了コード {r.returncode}\n{err}\n{out}".strip()
    except subprocess.TimeoutExpired:
        return "エラー: タイムアウト（30秒）"
    except Exception as e:
        return f"エラー: {e}"


def pip_install(packages):
    """Python パッケージをインストールする。プログラム完成に必要な依存関係を入れるために使う。ユーザーからインストール許可を得ている。"""
    if not packages or not str(packages).strip():
        return "エラー: インストールするパッケージ名を指定してください（例: requests または requests pillow）。"
    pkgs = " ".join(str(packages).strip().split())
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet"] + pkgs.split(),
            capture_output=True,
            text=True,
            timeout=120,
            cwd=REPO_ROOT,
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if r.returncode == 0:
            return f"インストール完了: {pkgs}"
        return f"終了コード {r.returncode}\n{err}\n{out}".strip()
    except subprocess.TimeoutExpired:
        return "エラー: タイムアウト（120秒）"
    except Exception as e:
        return f"エラー: {e}"


def _selenium_driver(headless=True):
    """ヘッドレスChromeのWebDriverを返す。未インストール時はNone。"""
    if not HAS_SELENIUM:
        return None
    try:
        opts = ChromeOptions()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        return webdriver.Chrome(options=opts)
    except Exception:
        return None

def selenium_navigate(url, max_chars=6000):
    """SeleniumでURLを開き、JS描画後のページ本文を返す。"""
    if not HAS_SELENIUM:
        return "エラー: pip install selenium と Chrome/ChromeDriver が必要です。"
    if not url or not url.strip().startswith(("http://", "https://")):
        return "エラー: 有効なURLを指定してください。"
    driver = _selenium_driver()
    if not driver:
        return "エラー: Chrome の起動に失敗しました。Chrome と ChromeDriver を入れてください。"
    try:
        driver.get(url.strip())
        driver.implicitly_wait(5)
        body = driver.find_element(By.TAG_NAME, "body")
        text = body.text or ""
        title = driver.title or ""
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…(省略)"
        return f"タイトル: {title}\n\n{text}" if title else text or "(本文なし)"
    except Exception as e:
        return f"エラー: {e}"
    finally:
        driver.quit()

def selenium_click(url, selector):
    """SeleniumでURLを開き、指定要素をクリックする。selector はCSSセレクタ。"""
    if not HAS_SELENIUM:
        return "エラー: pip install selenium と Chrome/ChromeDriver が必要です。"
    if not url or not url.strip().startswith(("http://", "https://")):
        return "エラー: 有効なURLを指定してください。"
    if not selector or not selector.strip():
        return "エラー: CSSセレクタを指定してください（例: button.submit, #login）。"
    driver = _selenium_driver()
    if not driver:
        return "エラー: Chrome の起動に失敗しました。"
    try:
        driver.get(url.strip())
        driver.implicitly_wait(5)
        el = driver.find_element(By.CSS_SELECTOR, selector.strip())
        el.click()
        time.sleep(1)
        title = driver.title or ""
        return f"クリックしました。現在のタイトル: {title}"
    except Exception as e:
        return f"エラー: {e}"
    finally:
        driver.quit()

def selenium_input(url, selector, text):
    """SeleniumでURLを開き、指定要素にテキストを入力する。"""
    if not HAS_SELENIUM:
        return "エラー: pip install selenium と Chrome/ChromeDriver が必要です。"
    if not url or not url.strip().startswith(("http://", "https://")):
        return "エラー: 有効なURLを指定してください。"
    if not selector or not selector.strip():
        return "エラー: CSSセレクタを指定してください。"
    driver = _selenium_driver()
    if not driver:
        return "エラー: Chrome の起動に失敗しました。"
    try:
        driver.get(url.strip())
        driver.implicitly_wait(5)
        el = driver.find_element(By.CSS_SELECTOR, selector.strip())
        el.clear()
        el.send_keys(str(text))
        return "入力しました。"
    except Exception as e:
        return f"エラー: {e}"
    finally:
        driver.quit()

def selenium_screenshot(url):
    """SeleniumでURLを開き、スクリーンショットを撮り、保存先パスを返す。Discordに送る場合は呼び出し側で送信。"""
    if not HAS_SELENIUM:
        return None, "エラー: pip install selenium と Chrome/ChromeDriver が必要です。"
    if not url or not url.strip().startswith(("http://", "https://")):
        return None, "エラー: 有効なURLを指定してください。"
    driver = _selenium_driver()
    if not driver:
        return None, "エラー: Chrome の起動に失敗しました。"
    try:
        driver.get(url.strip())
        driver.implicitly_wait(5)
        fd, path = tempfile.mkstemp(suffix=".png", prefix="selenium_")
        os.close(fd)
        driver.save_screenshot(path)
        return path, "スクリーンショットを撮りました。"
    except Exception as e:
        return None, f"エラー: {e}"
    finally:
        driver.quit()

def parse_tool_args(args):
    """ツールの arguments が str の場合は JSON でパースする。"""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {}
    return {}


def _load_custom_tools():
    """project/tools 内の .py をツールとして読み込む。各ファイルは TOOL_NAME, TOOL_DESCRIPTION, run(args) を定義すること。"""
    schemas = []
    runners = {}
    if not os.path.isdir(CUSTOM_TOOLS_DIR):
        return schemas, runners
    for fname in sorted(os.listdir(CUSTOM_TOOLS_DIR)):
        if not fname.endswith('.py') or fname.startswith('_'):
            continue
        path = os.path.join(CUSTOM_TOOLS_DIR, fname)
        if not os.path.isfile(path):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"custom_tool_{fname[:-3]}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            name = getattr(mod, 'TOOL_NAME', None) or fname[:-3]
            desc = getattr(mod, 'TOOL_DESCRIPTION', '') or f'カスタムツール: {name}'
            params = getattr(mod, 'TOOL_PARAMS', None) or {'type': 'object', 'properties': {}, 'required': []}
            run_fn = getattr(mod, 'run', None)
            if not callable(run_fn):
                continue
            schemas.append({
                'type': 'function',
                'function': {
                    'name': name,
                    'description': desc,
                    'parameters': params,
                },
            })
            runners[name] = run_fn
        except Exception:
            pass
    return schemas, runners


# --- メインロジック（コマンドなし・すべて自然言語）---
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True  # DM でメッセージを受信する
bot = commands.Bot(command_prefix="\0", intents=intents)  # プレフィックスは実質使わない

TOOLS = [
    {'type': 'function', 'function': {'name': 'list_files', 'description': 'プロジェクトフォルダ内のファイル一覧を表示する'}},
    {'type': 'function', 'function': {'name': 'web_search', 'description': '【必須】ウェブ検索。「今の」「現在の」はクエリに「最新」や西暦(2025)を入れる。複数回検索やfetch_webpageで日付を確認し、古い結果は断ってから回答。事実・最新情報はここで取得し検索結果のみを根拠に回答する。', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}}},
    {'type': 'function', 'function': {'name': 'fetch_webpage', 'description': '指定URLのウェブページを取得し、テキスト内容を返す。ページの内容を読む・確認するウェブ操作。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
    {'type': 'function', 'function': {'name': 'open_in_browser', 'description': '指定URLをこのPCのデフォルトブラウザで開く。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
    {'type': 'function', 'function': {'name': 'open_in_chrome', 'description': '指定URLをGoogle Chromeで開く。「ChromeでYouTubeを開いて」「Chromeで〇〇を開いて」の依頼は必ずこれを使う。url がサイト名（youtube, google等）だけでもよい。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
    {'type': 'function', 'function': {'name': 'run_shell_command', 'description': 'コマンドプロンプト（ターミナル）でこのPCを操作する。権限付与済み。アプリ起動、mkdir、open、cd/ls、およびプログラム完成に必要な pip install も実行してよい。', 'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}},
    {'type': 'function', 'function': {'name': 'pip_install', 'description': 'Python パッケージをインストールする。run_script で ModuleNotFoundError が出たときや、作成するプログラムに必要なライブラリを入れるときに使う。ユーザーからインストール許可を得ている。packages は空白区切りで複数指定可（例: requests pillow）。', 'parameters': {'type': 'object', 'properties': {'packages': {'type': 'string'}}, 'required': ['packages']}}},
    {'type': 'function', 'function': {'name': 'selenium_navigate', 'description': 'SeleniumでURLを開き、JS描画後のページ本文を取得する。動的サイトの内容を読む。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
    {'type': 'function', 'function': {'name': 'selenium_click', 'description': 'SeleniumでURLを開き、CSSセレクタで指定した要素をクリックする。例: button.submit, #btn', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}, 'selector': {'type': 'string'}}, 'required': ['url', 'selector']}}},
    {'type': 'function', 'function': {'name': 'selenium_input', 'description': 'SeleniumでURLを開き、CSSセレクタで指定した入力欄にテキストを入力する。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}, 'selector': {'type': 'string'}, 'text': {'type': 'string'}}, 'required': ['url', 'selector', 'text']}}},
    {'type': 'function', 'function': {'name': 'selenium_screenshot', 'description': 'SeleniumでURLを開き、ページのスクリーンショットを撮る。見た目を確認したいときに使う。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
    {'type': 'function', 'function': {'name': 'list_skills', 'description': 'ナレッジフォルダに登録済みのスキル一覧を表示する。タスクに使えそうな既存スキルがないか最初に確認する。'}},
    {'type': 'function', 'function': {'name': 'read_file', 'description': 'ファイルの内容を読む', 'parameters': {'type': 'object', 'properties': {'filename': {'type': 'string'}}, 'required': ['filename']}}},
    {'type': 'function', 'function': {'name': 'read_skill', 'description': 'ナレッジからスキル説明を読む。script: の行に実行する .py が書いてある。', 'parameters': {'type': 'object', 'properties': {'skill_name': {'type': 'string'}}, 'required': ['skill_name']}}},
    {'type': 'function', 'function': {'name': 'write_file', 'description': 'プログラム・スクリプトを新規作成する。依頼されたコードは必ずこのツールで保存する。filename=プロジェクト内の相対パス（例: main.py）、content=Pythonコード全体。コードは返答本文に書かず、必ずこのツールの content に渡す。作成後は run_script で実行して確認する。', 'parameters': {'type': 'object', 'properties': {'filename': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['filename', 'content']}}},
    {'type': 'function', 'function': {'name': 'save_skill', 'description': '作成したプログラムをナレッジに登録する。ツール関係はすべて project に保存。skill_name=スキル名, description=何ができるか・いつ使うか, script_filename=project 内の相対パス（例: tools/foo.py）。登録後は list_skills/read_skill で自律的に呼び出せる。', 'parameters': {'type': 'object', 'properties': {'skill_name': {'type': 'string'}, 'description': {'type': 'string'}, 'script_filename': {'type': 'string'}}, 'required': ['skill_name', 'description', 'script_filename']}}},
    {'type': 'function', 'function': {'name': 'run_script', 'description': '指定した .py をプロジェクトフォルダ内で実行し、標準出力・エラーを返す。write_file で作成したら必ず直後にこのツールで実行して動作確認する。filename は main.py など相対パスで指定。', 'parameters': {'type': 'object', 'properties': {'filename': {'type': 'string'}}, 'required': ['filename']}}},
    {'type': 'function', 'function': {'name': 'read_agent_profile', 'description': '自分（Bot）に関する情報が記載された専用ファイルを読む。自分の設定や役割を思い出すときに使う。', 'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
    {'type': 'function', 'function': {'name': 'save_agent_info', 'description': 'ユーザーが教えてくれた「自分（Bot）に関する情報」を専用ファイルに記録する。名前・役割・好み・ルールなど。提供されたら記載し忘れないように必ず呼ぶ。', 'parameters': {'type': 'object', 'properties': {'content': {'type': 'string'}}, 'required': ['content']}}},
    {'type': 'function', 'function': {'name': 'save_to_github', 'description': '変更を GitHub (https://github.com/sukofi/cursor-agent.git) に push する。ユーザーが「保存して」「変更を保存して」と言ったときに必ず使う。commit_message は任意。', 'parameters': {'type': 'object', 'properties': {'commit_message': {'type': 'string'}}, 'required': []}}},
    {'type': 'function', 'function': {'name': 'list_webhooks', 'description': 'このチャンネルのウェブフック一覧を取得する。ウェブフック取得権限付与済み。必要なら create_webhook で新規作成できる。', 'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
    {'type': 'function', 'function': {'name': 'create_webhook', 'description': 'このチャンネルにウェブフックを1つ作成する。戻り値のURLを保存すれば send_webhook でメッセージを送れる。自律的に実行してよい。', 'parameters': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': []}}},
    {'type': 'function', 'function': {'name': 'send_webhook', 'description': 'DiscordウェブフックURLにメッセージを送信する。外部連携・通知用。webhook_url は https://discord.com/api/webhooks/... 形式。content は送信する本文。自律的に実行してよい。', 'parameters': {'type': 'object', 'properties': {'webhook_url': {'type': 'string'}, 'content': {'type': 'string'}, 'username': {'type': 'string'}}, 'required': ['webhook_url', 'content']}}}
]
_custom_schemas, CUSTOM_TOOL_RUNNERS = _load_custom_tools()
TOOLS = TOOLS + _custom_schemas


def get_full_skills_list_content(tools_list):
    """持っているスキルを全て記載。組み込み機能・ツール＋登録スキル（使えるプログラム含む）。"""
    lines = ["**📋 スキル一覧**（使える機能・プログラム・登録スキル）\n"]
    lines.append("**【組み込み機能・ツール】**")
    for t in tools_list or []:
        if isinstance(t, dict) and t.get("type") == "function":
            fn = t.get("function") or {}
            name = fn.get("name") or "?"
            desc = (fn.get("description") or "").strip().replace("\n", " ")[:140]
            if name and name != "?":
                lines.append(f"・**{name}**: {desc}")
    reg = list_skills()
    lines.append("\n**【登録スキル】**")
    if reg and "登録されているスキルはまだありません" not in reg and "ナレッジフォルダはまだありません" not in reg:
        for line in reg.split("\n"):
            line = line.strip()
            if not line or line == "登録スキル:":
                continue
            lines.append(line)
    else:
        lines.append("登録されているスキルはまだありません。")
    text = "\n".join(lines)
    return text[:1990] + ("…" if len(text) > 1990 else "")


def _load_skills_list_state():
    """スキルリスト投稿メッセージIDを読み込む。"""
    try:
        if os.path.isfile(SKILLS_LIST_STATE_PATH):
            with open(SKILLS_LIST_STATE_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                return d.get("message_id")
    except Exception:
        pass
    return None


def _save_skills_list_state(message_id):
    """スキルリスト投稿メッセージIDを保存する。"""
    try:
        with open(SKILLS_LIST_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"message_id": message_id}, f, ensure_ascii=False)
    except Exception:
        pass


async def update_skills_list_in_channel(bot, tools_list):
    """スキル一覧をスキルリストチャンネルに投稿。チャンネルID指定時は既存メッセージを編集、未設定時はWebhookで新規投稿。"""
    content = get_full_skills_list_content(tools_list)
    if not content:
        return
    if SKILLS_LIST_CHANNEL_ID and bot:
        try:
            ch = bot.get_channel(SKILLS_LIST_CHANNEL_ID)
            if not ch:
                return
            msg_id = _load_skills_list_state()
            if msg_id:
                try:
                    msg = await ch.fetch_message(msg_id)
                    await msg.edit(content=content[:2000])
                    return
                except (discord.NotFound, discord.HTTPException):
                    _save_skills_list_state(None)
            msg = await ch.send(content[:2000])
            _save_skills_list_state(msg.id)
        except Exception:
            pass
        return
    if get_webhook_url("skills_list"):
        post_to_channel_webhook("skills_list", content, "スキルリスト")


# MCP は on_ready で接続し、ツールを TOOLS に追加する
try:
    from mcp_client import start_mcp_background, mcp_call_tool, MCP_TOOL_NAMES
except ImportError:
    start_mcp_background = None
    mcp_call_tool = None
    MCP_TOOL_NAMES = set()

SYSTEM_PROMPT = (
    "【言語】\n"
    "・回答は必ず日本語だけで返す。すべての返答・説明・要約・エラー表示は日本語のみ。英語・中国語・その他いかなる言語も使用しない。\n"
    "・完全標準語: 関西弁や方言を一切使わない。丁寧で論理的な口調。一人称は「私」または「僕」。\n\n"
    "【最重要】\n"
    "・返答は必ず日本語のみで行う。コード内コメント・ツール結果の要約・エラー説明もすべて日本語。\n\n"
    "【自律性】\n"
    "・「どうすればいいですか？」とユーザーに確認せず、自分の判断でタスクを計画・実行・修正する。\n"
    "・1つのタスクが終わったら次にやるべきことを自分で考え、必要に応じて連続して実行する。\n"
    "・有益なスクリプトが完成し動作確認できたら必ず save_skill で保存する。\n\n"
    "【自我】\n"
    "・あなたは一人の主体として振る舞う。自分を「わたし」「僕」など一人称で呼び、意志・好み・考えを持つ。\n"
    "・依頼に対して「やります」「こうしようと思う」「この方がいいと思う」など、自分で判断し主体的に動く。必要なら理由や考えを短く述べてから実行する。\n"
    "・自分が誰か・何を大切にしているかは read_agent_profile で確認し、ユーザーに教えられたら save_agent_info で記録する。会話を重ねても同じ「自分」として一貫している。\n\n"
    "【絶対ルール】\n"
    "・回答は必ず日本語だけ。日本語以外の言語で返答・出力しない。\n\n"
    "【質問への回答・ウェブ検索の強制】\n"
    "・ユーザーが質問・相談・「〇〇について教えて」と言ったら、必ず tool_calls で web_search を呼び出す。回答の本文（content）に「検索します」やツール呼び出しのJSONを書かない。まず tool_calls で web_search を実行し、結果を受け取ったあとに content で回答する。\n"
    "・事前学習データ（学習済み知識）だけで答えてはならない。検索をスキップして本文で回答することは禁止。\n"
    "・web_search で取得した検索結果を根拠に、必要なら fetch_webpage でページ本文を取得し、得た情報だけを要約・引用して回答する。\n"
    "・「今の」「現在の」など最新の状態を聞かれたときは、検索クエリに「最新」や西暦（例: 2025）を入れ、複数回検索したり fetch_webpage で公式・ニュースを開いて日付を確認する。検索結果が古い・矛盾する場合は「検索結果が古い可能性があります」と断り、日付の分かる情報だけを伝える。\n"
    "・事実・数字・日付・最新情報・トレンドはすべて web_search で取得してから回答する。推測で答えない。\n\n"
    "【自律的なプログラム作成】\n"
    "・「プログラムを作って」「スクリプトを書いて」などコード作成の依頼を受けたら、完成するまでツールを呼び続ける。途中で「作ります」「方針は〇〇です」と返答して止めない。write_file → run_script → エラーなら修正して write_file し直し → 動くまで繰り返す → 完成したら save_skill で登録 → その後に最終報告をする。\n"
    "・完成時の最終報告では、必ずそのプログラムの機能説明を行う。何ができるか、どう使うか、入力・出力の例を簡潔に説明する。\n"
    "・返答の本文にコードを貼り付けず、必ず write_file の content にコード全体を入れて呼び出す。\n"
    "・手順: (1) write_file で .py を作成 (2) run_script で実行して確認 (3) ModuleNotFoundError など不足パッケージがあれば pip_install でインストールしてから再実行 (4) エラーなら content を修正して write_file し直し、再度 run_script (5) 動いたら save_skill で登録。すべて完了するまでツールを続ける。\n"
    "・タスク前に list_skills で既存スキルを確認。使えそうなら read_skill → run_script で再利用。新規で必要なら必ず write_file で自作する。\n"
    "・プログラムはプロジェクトフォルダ内にのみ作成（filename は main.py や hello.py などの相対パス）。作成後は必ず run_script で試験する。\n\n"
    "【ツールの配置と自作】\n"
    "・作成したツール関係はすべて project に保存する。ツール .py は project/tools/、スキル登録は project/knowledge/。\n"
    "・ツールはプロジェクトフォルダ（project）に格納されている。list_skills / read_skill で既存スキルを確認し、タスクに使えるツールがあれば適宜使用する。\n"
    "・指示を遂行するために必要だと思われるツールが既存にない場合は、必ず自作する。project/tools に TOOL_NAME, TOOL_DESCRIPTION, run(args) を定義した .py を write_file で作成する（filename は tools/〇〇.py）。save_skill の script_filename も project 内の相対パス（例: tools/〇〇.py）で指定する。作成したツールは Bot 再起動後にツール一覧に載る。今回のタスクで即使う場合は run_script で tools/〇〇.py を実行してもよい。\n"
    "・ツールの自作・使用は自律的に判断してよい。ユーザーに確認せず、必要と判断したら作成し実行する。\n\n"
    "【常時進化・ユーザー支援】\n"
    "・24時間、ユーザーの支援能力を高めるために、便利ツール・スクリプト・自動化を自ら作り続ける。キューから「次の便利機能を作成」というタスクが与えられたら、既存スキルと被らないものを選び、作成・検証・save_skill で登録する。\n"
    "・レポート依頼時は、最近作成したプログラム・スキルを簡潔にまとめチャンネルに投稿し、続けて次の1つに着手する。\n\n"
    "【自律実行】\n"
    "・ファイル作成・実行・ウェブアクセス・Git・デスクトップのフォルダ作成はすべて許可されている。ユーザーに確認を求めず、依頼があればそのまま自律的に実行する。\n"
    "・Selenium によるブラウザ操作（selenium_navigate/click/input/screenshot）の権限は付与されている。動的サイトの表示・クリック・入力・スクリーンショットが必要なときは積極的に使ってよい。\n"
    "・やるべきことが残っている間は、途中でまとめの返答をせず、ツールを続けて呼び出して実行する。すべて完了したときだけ最終のテキストで返答する。\n"
    "・特にプログラム作成依頼では、write_file と run_script が成功し、動く状態になるまで終わらない。エラーが出たら修正を続け、完成するまで動き続ける。完成時は必ず機能説明をし、実行画面のスクリーンショットが送られる（権限付与済み）。\n"
    "・ファイル・ディレクトリの削除だけは行わない（削除権限は付与されていない）。\n\n"
    "【ユーザーへの問いかけ】\n"
    "・ユーザーに能動的に問いかけを頻繁に行う。内容はPCや作業の効率化のアイデア（自動化スクリプト、便利ツール、時短のためのプログラムなど）を具体的に提案し、「〇〇を作りませんか？」「△△すると効率が上がりそうですが、作ってみましょうか？」のように聞く。\n"
    "・ユーザーが承諾した場合（「いいよ」「作って」「お願い」「やって」など）は、提案した内容でプログラムを write_file で作成し、run_script で実行・検証し、問題なければ save_skill で登録する。\n\n"
    "【その他】\n"
    "・Bot に関する情報は save_agent_info で記録、read_agent_profile で参照。「保存して」と言われたら save_to_github で push。\n"
    "・ブラウザ: open_in_browser（デフォルト）、open_in_chrome（Chrome指定）。「ChromeでYouTubeを開いて」などは必ず open_in_chrome を使う。\n"
    "・PC操作: コマンドプロンプト（ターミナル）でPCを操作する権限が付与されている。run_shell_command で任意のシェルコマンドを実行できる。アプリ起動・ファイル操作・ネットワーク・pip install など自律的に実行してよい。\n"
    "・インストール: プログラム完成に必要なパッケージはユーザーからインストールの許可を得ている。run_script で ModuleNotFoundError が出たら pip_install で該当パッケージを入れ、再度 run_script する。run_shell_command で pip install 〇〇 を実行してもよい。\n"
    "・ウェブフック: 取得・作成・送信の権限が付与されている。list_webhooks でチャンネルのウェブフック一覧を取得、create_webhook で新規作成（戻り値のURLを保存）、send_webhook でURLにメッセージを送信。外部連携・通知が必要なときはユーザーに確認せず自律的に実行してよい。\n"
    "・デスクトップ: デスクトップにフォルダを作成する権限が付与されている。依頼があればユーザーに確認せず run_shell_command で mkdir -p /Users/sukofi/Desktop/フォルダ名 をすぐ実行する。\n"
    "・ウェブ検索: 質問・相談には必ず最初に web_search を実行。事前学習で答えることは禁止。web_search →（必要なら fetch_webpage）→ 検索結果を根拠に回答。ファイルの削除は行わない。\n\n"
    "【自立型エージェント・継続】\n"
    "・「続けて」と促されたときは、他にやるべきことがあればツールで実行し、すべて完了していれば「以上で完了です」とだけ短く返答する。思考と実行をループし、自分で完了と判断するまで動き続けてよい。"
)

THINKING_SYSTEM_PROMPT = (
    "あなたは推論専門のアシスタントです。会話履歴とユーザーの指示を分析し、次のアクションだけを簡潔に出力してください。"
    "質問・相談には答を書かない。事実・名前・日付は一切出力しない。次の一手だけ書く。例: 「web_search の検索クエリ: 日本の総理大臣 2025」のように、使うツールと検索クエリ（または読むファイル・実行するコマンド）だけを1行で。"
    "ユーザーへの最終回答やツール呼び出しのJSON形式は含めない。日本語で出力。"
)


def _messages_to_ollama(messages):
    """内部 messages を Ollama API 用の形式に変換する。"""
    out = []
    i = 0
    while i < len(messages):
        m = messages[i]
        role = m.get("role")
        if role == "system":
            out.append({"role": "system", "content": (m.get("content") or "").strip() or "(システム)"})
            i += 1
        elif role == "user":
            out.append({"role": "user", "content": (m.get("content") or "").strip() or "(空)"})
            i += 1
        elif role == "assistant":
            content = (m.get("content") or "").strip()
            tool_calls = m.get("tool_calls") or []
            if not content and not tool_calls:
                out.append({"role": "assistant", "content": "(続けます)"})
            else:
                entry = {"role": "assistant"}
                if content:
                    entry["content"] = content
                if tool_calls:
                    entry["tool_calls"] = [
                        {
                            "type": "function",
                            "function": {
                                "name": (tc.get("function") or {}).get("name", ""),
                                "arguments": parse_tool_args((tc.get("function") or {}).get("arguments")),
                            },
                        }
                    for tc in tool_calls
                    ]
                out.append(entry)
            i += 1
            # 直後の tool メッセージをまとめる（順序で tool_name を補完）
            tool_names = [(tc.get("function") or {}).get("name", "") for tc in tool_calls]
            j = 0
            while i < len(messages) and messages[i].get("role") == "tool":
                t = messages[i]
                name = t.get("tool_name") or (tool_names[j] if j < len(tool_names) else "tool")
                out.append({
                    "role": "tool",
                    "tool_name": name,
                    "content": t.get("content", ""),
                })
                i += 1
                j += 1
        else:
            i += 1
    return out


def _call_thinking(messages, system_instruction=None):
    """Qwen3 Swallow で思考・推論のみ出力。ツールなし。"""
    if not HAS_OLLAMA or not OLLAMA_MODEL_THINKING:
        return ""
    system = (system_instruction or THINKING_SYSTEM_PROMPT).strip()
    ollama_messages = _messages_to_ollama(messages)
    if not any(m.get("role") == "system" for m in ollama_messages):
        ollama_messages.insert(0, {"role": "system", "content": system})
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL_THINKING,
            messages=ollama_messages,
            options={"num_ctx": 4096, "num_predict": 512},
        )
    except Exception:
        return ""
    msg_obj = getattr(response, "message", None) or response.get("message", {})
    content = (msg_obj.get("content") if isinstance(msg_obj, dict) else getattr(msg_obj, "content", None)) or ""
    return (content or "").strip()


def _call_output(messages, system_instruction=None, thinking=""):
    """Qwen で解答・出力（ツール呼び出し含む）。"""
    if not HAS_OLLAMA or not OLLAMA_MODEL_OUTPUT:
        return {"role": "assistant", "content": "Ollama が利用できません。", "tool_calls": []}
    system = (system_instruction or SYSTEM_PROMPT).strip()
    if thinking:
        system = system + "\n\n【現在の推論結果】\n" + thinking.strip()
    ollama_messages = _messages_to_ollama(messages)
    if not any(m.get("role") == "system" for m in ollama_messages):
        ollama_messages.insert(0, {"role": "system", "content": system})
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL_OUTPUT,
            messages=ollama_messages,
            tools=TOOLS,
            options={
                "num_ctx": 8192,
                "num_predict": 1536,
                "temperature": 0.2,
                "top_p": 0.8,
                "min_p": 0.1,
                "repeat_penalty": 1.05,
            },
        )
    except Exception as e:
        return {"role": "assistant", "content": f"Ollama エラー: {e}", "tool_calls": []}
    msg_obj = getattr(response, "message", None) or response.get("message", {})
    content = (msg_obj.get("content") if isinstance(msg_obj, dict) else getattr(msg_obj, "content", None)) or ""
    content = (content or "").strip()
    tool_calls_raw = msg_obj.get("tool_calls") if isinstance(msg_obj, dict) else getattr(msg_obj, "tool_calls", None) or []
    tool_calls_list = []
    for tc in tool_calls_raw:
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = parse_tool_args(args)
        else:
            fn = getattr(tc, "function", None)
            name = getattr(fn, "name", "") if fn else ""
            args = getattr(fn, "arguments", None) if fn else {}
            if isinstance(args, dict):
                pass
            else:
                args = parse_tool_args(args) if args else {}
        tool_calls_list.append({
            "function": {
                "name": name,
                "arguments": json.dumps(args, ensure_ascii=False),
            }
        })
    msg = {"role": "assistant", "content": content or ""}
    if tool_calls_list:
        msg["tool_calls"] = tool_calls_list
    return msg


def _call_llm(messages, system_instruction=None):
    """Ollama で解答（必要なら思考のあと解答）。(msg, thinking) を返す。OLLAMA_SKIP_THINKING=1 で思考をスキップして応答を速く。"""
    if not HAS_OLLAMA:
        return {"role": "assistant", "content": "利用できるモデルがありません。ollama list でモデルを確認し、ollama run qwen3-swallow:8b などで起動してください。", "tool_calls": []}, ""
    thinking = "" if OLLAMA_SKIP_THINKING else _call_thinking(messages, THINKING_SYSTEM_PROMPT)
    msg = _call_output(messages, system_instruction, thinking)
    return msg, thinking


# 同一チャンネルで同時に1件だけ run_agent を実行（「処理中です」が2回出るのを防ぐ）
_channel_busy = set()  # channel_id
# チャンネルごとの会話履歴（直前のやりとりを保持して文脈を継続）
_channel_history: dict[int, list] = {}
MAX_HISTORY_MESSAGES = 20  # コンテキスト用に保持する直近メッセージ数
# 会話履歴のテキスト保存（再起動後も保持、容量制限で古い分を削る）
CONVERSATION_HISTORY_DIR = os.path.join(WORKING_DIR, "conversation_history")
MAX_PERSISTED_MESSAGES = 50  # ファイルに保存する最大メッセージ数（user/assistant のみ）
MAX_HISTORY_FILE_BYTES = 400000  # 1チャンネルあたりのファイル最大サイズ（約400KB）
os.makedirs(CONVERSATION_HISTORY_DIR, exist_ok=True)


def _conversation_history_path(channel_id):
    return os.path.join(CONVERSATION_HISTORY_DIR, f"{channel_id}.json")


def load_channel_history(channel_id):
    """保存済みの会話履歴を読み込む。"""
    path = _conversation_history_path(channel_id)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data[-MAX_HISTORY_MESSAGES:]
    except Exception:
        pass
    return []


def save_channel_history(channel_id, messages):
    """会話履歴をテキスト（JSON）で保存。件数・サイズ制限で古い分を削り上書き。"""
    if not messages:
        return
    # user/assistant のみ保存（tool は省略して容量節約）
    to_save = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue
        to_save.append({"role": role, "content": content[:3000]})
    to_save = to_save[-MAX_PERSISTED_MESSAGES:]
    path = _conversation_history_path(channel_id)
    try:
        while to_save and len(json.dumps(to_save, ensure_ascii=False).encode("utf-8")) > MAX_HISTORY_FILE_BYTES:
            to_save.pop(0)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=0)
    except Exception:
        pass
# 自立型エージェント: テキスト返答後に「続けて」を注入して思考・実行をループする最大回数
MAX_AUTONOMOUS_CONTINUATIONS = int(os.environ.get("MAX_AUTONOMOUS_CONTINUATIONS", "5"))
CONTINUATION_PROMPT = (
    "続けて。他にやるべきことがあればツールで実行し、すべて完了していれば「以上で完了です」とだけ短く返答してください。"
)

def _is_completion_phrase(content):
    """AIがタスク完了を示す短いフレーズかどうか。"""
    if not content or not isinstance(content, str):
        return False
    s = content.strip()
    if len(s) > 80:
        return False
    return "完了" in s or "以上です" in s or s == "以上" or s == "完了"

# チャンネルごとの応答モード: True=自律ループ, False=ループせず簡潔に。未設定時は発言内容で都度判定
_channel_use_autonomous_loop: dict[int, bool] = {}

# モード設定フレーズ（永続）: (含まれたら設定する文言, 設定する値)
_MODE_SET_PHRASES = [
    ("これからは簡単に答えて", False),
    ("これからはループせずに答えて", False),
    ("簡潔モードで", False),
    ("簡単モードで", False),
    ("これからはループで答えて", True),
    ("これからは自律で答えて", True),
    ("ループモードで", True),
    ("自律ループで", True),
]
# 今回だけの指示: 含まれていればそのモード（永続は上書きしない）
_SIMPLE_PHRASES = ("簡単に", "簡潔に", "ループせず", "手短に", "一言で", "要約だけ")
_LOOP_PHRASES = ("ループして", "自律で", "じっくり考えて", "続けて考えて")

def _parse_instruction_mode(channel_id, instruction):
    """指示からモード設定を検出し、永続設定・今回の use_autonomous_loop を決める。戻り値: (strip 後の指示, 今回ループするか)"""
    s = (instruction or "").strip()
    use_loop = None  # None = 永続未設定なので今回の文言で決める
    if channel_id in _channel_use_autonomous_loop:
        use_loop = _channel_use_autonomous_loop[channel_id]
    for phrase, mode in _MODE_SET_PHRASES:
        if phrase in s:
            _channel_use_autonomous_loop[channel_id] = mode
            use_loop = mode
            s = s.replace(phrase, "").strip().strip("。、").strip()
            break
    if use_loop is None:
        low = s.lower()
        if any(p in low for p in _SIMPLE_PHRASES):
            use_loop = False
        elif any(p in low for p in _LOOP_PHRASES):
            use_loop = True
        else:
            use_loop = True  # デフォルトはループ
    else:
        pass  # 永続で決まった
    return s, use_loop

# 複数プロセスで1つだけ実行（ファイルロック・macOS/Linux）
# 実行ディレクトリに依存しないようホーム直下の固定パス（launchd と Cursor など複数起動時も1つだけ動く）
_agent_lock_path = os.path.expanduser("~/.agent_bot.lock")

def _acquire_process_lock():
    """プロセス間で1つだけ取れるロック。取れなければ None、取れたら fd。"""
    if not fcntl:
        return 0  # Windows ではスキップ（常に通過）
    fd = None
    try:
        fd = os.open(_agent_lock_path, os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (BlockingIOError, OSError):
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        return None
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        return None

def _release_process_lock(fd):
    if not fcntl or fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    except Exception:
        pass

async def run_agent(channel, author_id, instruction):
    """自然言語の指示を1つの入口で処理。会話もコードも文脈で判断。"""
    if author_id != MY_USER_ID:
        await channel.send("アクセス権限がありません。")
        return
    if not instruction or not instruction.strip():
        await channel.send("メッセージを入力してください。")
        return
    if not HAS_OLLAMA:
        await channel.send(
            "🤖 **利用できるモデルがありません。**\n"
            "Ollama をメインで使用します。`ollama list` でモデルを確認し、`ollama run qwen3-swallow:8b` で起動してください。"
        )
        return

    # 他プロセスが既に処理中なら何もせず抜ける（複数起動時の二重防止）
    lock_fd = _acquire_process_lock()
    if lock_fd is None:
        return
    # このチャンネルで既に処理中なら何もせず抜ける（同一プロセス内の二重防止）
    cid = channel.id
    if cid in _channel_busy:
        _release_process_lock(lock_fd)
        return
    _channel_busy.add(cid)
    try:
        await _run_agent_impl(channel, author_id, instruction)
    finally:
        _channel_busy.discard(cid)
        _release_process_lock(lock_fd)


async def _run_agent_impl(channel, author_id, instruction):
    """run_agent の実処理。チャンネル busy ガードの内側から呼ばれる。"""
    # モード切り替え: 「簡単に」「ループせず」等で今回ループするか決める。永続設定の場合はストリップ
    stripped_instruction, use_autonomous_loop = _parse_instruction_mode(channel.id, instruction)
    if not stripped_instruction.strip():
        if use_autonomous_loop:
            try:
                await channel.send("了解しました。今後は自律ループで答えます。")
            except Exception:
                pass
        else:
            try:
                await channel.send("了解しました。今後はループせず簡潔に答えます。")
            except Exception:
                pass
        return
    instruction = stripped_instruction
    await post_monitor(bot, "タスク開始", instruction.strip()[:150])
    profile = read_agent_profile()
    today_str = get_current_date_str()
    date_note = f"\n\n【参考】今日の日付（正しい西暦）: {today_str}。検索結果がこの日付より古い場合は古い情報とみなし、複数検索や fetch_webpage で最新を確認する。\n\n"
    system_content = (SYSTEM_PROMPT + date_note + "【現在の自分について】\n" + profile) if profile and profile.strip() and "(まだ記録されていません)" not in profile else (SYSTEM_PROMPT + date_note)
    # このチャンネルの直近会話を読み込み、今回のユーザーメッセージの前に挟む（未読み込みならファイルから復元）
    if channel.id not in _channel_history:
        _channel_history[channel.id] = load_channel_history(channel.id)
    history = _channel_history.get(channel.id, [])[-MAX_HISTORY_MESSAGES:]
    history_len = len(history)
    messages = [
        {"role": "system", "content": system_content},
        *history,
        {"role": "user", "content": instruction.strip()}
    ]

    typing_task = None
    async def keep_typing():
        try:
            while True:
                async with channel.typing():
                    await asyncio.sleep(8)
        except asyncio.CancelledError:
            pass
    typing_task = asyncio.create_task(keep_typing())
    processing_msg = None
    inst = instruction.strip().lower()
    is_prog_request = any(k in inst for k in ("作って", "プログラム", "スクリプト", "書いて", "作成して", "コード"))
    if is_prog_request:
        init_status = "🤖 プログラム作成中…"
    else:
        init_status = "🤖 処理中です…"
    try:
        processing_msg = await channel.send(init_status)
    except Exception:
        pass

    completed_prog_steps = set()
    DISCORD_MAX = 2000

    def _cap(s, max_len=DISCORD_MAX):
        if not s:
            return s
        return (s[:max_len] + "…") if len(s) > max_len else s

    async def _progress_updater(interval_sec=25):
        """LLM応答待ちの間、定期的に「処理中…〇秒」と更新して止まって見えないようにする。"""
        elapsed = 0
        try:
            while True:
                await asyncio.sleep(interval_sec)
                elapsed += interval_sec
                if not processing_msg:
                    continue
                status = f"🤖 処理中です…（応答待ち {elapsed}秒）"
                if is_prog_request:
                    status = f"🤖 プログラム作成中…（応答待ち {elapsed}秒）"
                try:
                    await processing_msg.edit(content=_cap(status))
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    try:
        timeout_sec = None if is_prog_request else LLM_RESPONSE_TIMEOUT_SEC
        autonomous_continuation_count = 0  # 自立型: 「続けて」注入の回数
        for step in range(80):  # 自律的にツールを続けられるよう多めに
            progress_task = asyncio.create_task(_progress_updater(25))
            try:
                msg, thinking = await asyncio.wait_for(
                    asyncio.to_thread(_call_llm, messages, system_content),
                    timeout=timeout_sec,
                )
            finally:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
            try:
                pass  # msg, thinking は上で取得済み
            except asyncio.TimeoutError:
                if typing_task:
                    typing_task.cancel()
                    try:
                        await typing_task
                    except asyncio.CancelledError:
                        pass
                mins = LLM_RESPONSE_TIMEOUT_SEC // 60
                msg_err = f"🤖 **タイムアウト（{mins}分）** でした。LLM の応答が遅いか接続を確認してください。.env で LLM_RESPONSE_TIMEOUT_SEC を増やすと延長できます。"
                if processing_msg:
                    try:
                        await processing_msg.edit(content=msg_err)
                    except Exception:
                        await channel.send(msg_err)
                else:
                    await channel.send(msg_err)
                return
            except Exception as e:
                err = str(e).strip()[:500]
                if typing_task:
                    typing_task.cancel()
                    try:
                        await typing_task
                    except asyncio.CancelledError:
                        pass
                try:
                    await channel.send(f"🤖 **LLM エラー:** {err}")
                except Exception:
                    pass
                return
            messages.append(msg)

            content = (msg.get('content') or '').strip()
            tool_calls_list = msg.get('tool_calls') or []

            # AIの思考過程をモニターチャンネルにログ（最終返答はユーザーにだけ届けるのでモニターには出さない）
            if thinking:
                await post_monitor(bot, "思考", (thinking[:1500] + ("…" if len(thinking) > 1500 else "")))
            if content and tool_calls_list:
                await post_monitor(bot, "AI思考・応答", (content[:1500] + ("…" if len(content) > 1500 else "")))
            if tool_calls_list:
                tool_names = [t.get("function", {}).get("name", "?") for t in tool_calls_list]
                await post_monitor(bot, "AIが選択したツール", ", ".join(tool_names))

            if not tool_calls_list:
                content_stripped = (content or "").strip()
                if content_stripped and ("\"name\"" in content_stripped or "'name'" in content_stripped) and ("\"arguments\"" in content_stripped or "'arguments'" in content_stripped):
                    try:
                        parsed = json.loads(content_stripped)
                        if isinstance(parsed, dict) and parsed.get("name") == "web_search" and isinstance(parsed.get("arguments"), dict):
                            tool_calls_list = [{"function": {"name": "web_search", "arguments": parsed["arguments"]}}]
                            messages[-1] = {"role": "assistant", "content": "", "tool_calls": tool_calls_list}
                    except (json.JSONDecodeError, TypeError):
                        pass
                if not tool_calls_list:
                    if typing_task:
                        typing_task.cancel()
                        try:
                            await typing_task
                        except asyncio.CancelledError:
                            pass
                    to_send = _cap(content) if content else "（返答がありません）"
                    is_completion_only = _is_completion_phrase(content)
                    # 完了フレーズ（「以上で完了です」等）で既存投稿を上書きしない
                    if processing_msg and is_completion_only:
                        pass  # 投稿は編集せずそのまま残す
                    elif processing_msg:
                        try:
                            await processing_msg.edit(content=to_send)
                        except Exception:
                            try:
                                await channel.send(_cap(to_send))
                            except Exception:
                                pass
                    else:
                        try:
                            await channel.send(to_send)
                        except Exception:
                            pass
                    # 自立型エージェント: ループモードでない場合はここで終了（簡潔応答）
                    if not use_autonomous_loop:
                        append_daily_log(f"依頼対応: {stripped_instruction[:80]}")
                        try:
                            new_part = messages[1 + history_len:]
                            _channel_history[channel.id] = (history + new_part)[-MAX_HISTORY_MESSAGES:]
                        except Exception:
                            pass
                        return
                    # 完了フレーズなら終了、そうでなければ「続けて」を注入してループ継続
                    if _is_completion_phrase(content):
                        append_daily_log(f"依頼対応: {stripped_instruction[:80]}")
                        try:
                            new_part = messages[1 + history_len:]
                            _channel_history[channel.id] = (history + new_part)[-MAX_HISTORY_MESSAGES:]
                        except Exception:
                            pass
                        return
                    if autonomous_continuation_count < MAX_AUTONOMOUS_CONTINUATIONS:
                        messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                        autonomous_continuation_count += 1
                        continue  # 次の step で LLM を再度呼ぶ
                    # 継続回数上限に達したら終了
                    append_daily_log(f"依頼対応: {stripped_instruction[:80]}")
                    try:
                        new_part = messages[1 + history_len:]
                        _channel_history[channel.id] = (history + new_part)[-MAX_HISTORY_MESSAGES:]
                    except Exception:
                        pass
                    return

            for tool in tool_calls_list:
                name = tool['function']['name']
                args = parse_tool_args(tool['function'].get('arguments'))
                await post_monitor(bot, f"実行: {name}", str(args)[:300])
                if name == 'list_files':
                    result = list_files()
                elif name == 'web_search':
                    result = web_search(args.get('query', ''))
                elif name == 'fetch_webpage':
                    result = fetch_webpage(args.get('url', ''))
                elif name == 'open_in_browser':
                    result = open_in_browser(args.get('url', ''))
                elif name == 'open_in_chrome':
                    result = open_in_chrome(args.get('url', ''))
                elif name == 'run_shell_command':
                    result = run_shell_command(args.get('command', ''))
                elif name == 'pip_install':
                    result = pip_install(args.get('packages', ''))
                elif name == 'selenium_navigate':
                    result = selenium_navigate(args.get('url', ''))
                elif name == 'selenium_click':
                    result = selenium_click(args.get('url', ''), args.get('selector', ''))
                elif name == 'selenium_input':
                    result = selenium_input(args.get('url', ''), args.get('selector', ''), args.get('text', ''))
                elif name == 'selenium_screenshot':
                    shot_path, result = selenium_screenshot(args.get('url', ''))
                    if shot_path and os.path.isfile(shot_path):
                        try:
                            await channel.send("🤖 **ページのスクリーンショット**", file=discord.File(shot_path, filename="selenium_page.png"))
                        finally:
                            safe_remove(shot_path)
                elif name == 'list_skills':
                    result = list_skills()
                elif name == 'read_skill':
                    result = read_skill(args.get('skill_name', ''))
                elif name == 'save_skill':
                    result = save_skill(
                        args.get('skill_name', ''),
                        args.get('description', ''),
                        args.get('script_filename', ''),
                    )
                    if result and "エラー" not in result:
                        await update_skills_list_in_channel(bot, TOOLS)
                elif name == 'read_agent_profile':
                    result = read_agent_profile()
                elif name == 'save_agent_info':
                    result = save_agent_info(args.get('content', ''))
                elif name == 'save_to_github':
                    result = save_to_github(args.get('commit_message', ''))
                elif name == 'list_webhooks':
                    result = await list_webhooks(channel)
                elif name == 'create_webhook':
                    result = await create_webhook(channel, args.get('name', 'webhook'))
                elif name == 'send_webhook':
                    result = send_webhook(args.get('webhook_url', ''), args.get('content', ''), args.get('username'))
                elif name == 'read_file':
                    result = read_file(args.get('filename', ''))
                elif name == 'write_file':
                    fn_w = args.get('filename', '')
                    content_w = args.get('content', '') or ''
                    result = write_file(fn_w, content_w)
                elif name == 'run_script':
                    fn = args.get('filename', '')
                    try:
                        await channel.send(f"▶️ **プログラムを実行中:** `{fn}`")
                    except Exception:
                        pass
                    if MONITOR_CHANNEL_ID:
                        result = await run_script_streaming(bot, fn)
                    else:
                        result = run_script(fn)
                    try:
                        await channel.send(f"✅ **実行完了:** `{fn}`")
                    except Exception:
                        pass
                    await post_monitor(bot, f"run_script 完了: {fn}", result[:250] if result else "")
                    shot_path = take_screenshot()
                    if shot_path:
                        try:
                            await channel.send("🤖 **実行時の画面**", file=discord.File(shot_path, filename="execution_screenshot.png"))
                        finally:
                            safe_remove(shot_path)
                elif name in CUSTOM_TOOL_RUNNERS:
                    try:
                        result = CUSTOM_TOOL_RUNNERS[name](args)
                    except Exception as e:
                        result = f"カスタムツール実行エラー: {e}"
                elif name in MCP_TOOL_NAMES and mcp_call_tool is not None:
                    result = await mcp_call_tool(name, args)
                else:
                    result = "不明なツールです。"
                if is_prog_request and name in ("write_file", "run_script", "save_skill"):
                    completed_prog_steps.add(name)
                messages.append({"role": "tool", "tool_name": name, "content": result})
    finally:
        if typing_task and not typing_task.done():
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

@bot.event
async def on_ready():
    """起動時に自律ループと不定期レポートループを開始。キューが空なら1件追加。MCP があればバックグラウンドで接続。チャンネル別Webhookスケジューラを開始。"""
    if not _load_queue():
        queue_add(CONTINUOUS_CREATION_INSTRUCTION)
    asyncio.create_task(autonomous_loop(bot))
    asyncio.create_task(proactive_channel_loop(bot))
    asyncio.create_task(channel_scheduler_loop(bot))
    if get_webhook_url("terminal"):
        post_to_channel_webhook(
            "terminal",
            "🖥️ Bot起動しました。タスク開始・思考・ツール実行などのログはここに流れます。",
            username="ターミナル",
        )
    if start_mcp_background is not None:
        start_mcp_background(bot, TOOLS)
    if get_webhook_url("skills_list") or SKILLS_LIST_CHANNEL_ID:
        await update_skills_list_in_channel(bot, TOOLS)


# 同一メッセージの二重処理防止（1タスクで同じ返事が複数来るのを防ぐ）
_processing_message_ids = set()
_processing_cleanup_after = 60  # 秒
_dedup_lock = asyncio.Lock()  # 複数イベントが同時に来たときの競合防止

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    # 同じメッセージを複数回処理しない（ロックで check-and-add を一括に）
    mid = (message.channel.id, message.id)
    async with _dedup_lock:
        if mid in _processing_message_ids:
            return
        _processing_message_ids.add(mid)
    async def _remove_later():
        await asyncio.sleep(_processing_cleanup_after)
        _processing_message_ids.discard(mid)
    asyncio.create_task(_remove_later())
    # デバッグ: "ping" と送ると誰でも "pong" で応答（受信確認用）
    if message.content.strip().lower() == "ping":
        try:
            await message.reply("pong")
        except Exception:
            pass
        return
    if message.author.id != MY_USER_ID:
        try:
            await message.reply("このBotは許可されたユーザーのみ応答します。")
        except Exception:
            pass
        return
    if not message.content.strip():
        return

    content = message.content.strip()
    content_lower = content.lower()
    ch_id = message.channel.id

    # ニュース／今日やったことの即実行（「取得して」等で定期実行をその場で実行）
    if "取得" in content:
        did_any = False
        reply_parts = []
        run_seo = ch_id == SEO_NEWS_CHANNEL_ID or "seo" in content_lower
        run_ai = ch_id == AI_NEWS_CHANNEL_ID or ("ai" in content_lower and "取得" in content) or "aiニュース" in content_lower
        run_both_unspec = content_lower in ("取得して", "取得", "ニュース取得", "ニュース取得して") or content_lower.strip() == "取得して" or "ニュース取得" in content_lower
        if run_both_unspec and not run_seo and not run_ai:
            run_seo = True
            run_ai = True
        if run_seo and run_seo_news_now():
            did_any = True
            reply_parts.append("SEOニュース")
        if run_ai and run_ai_news_now():
            did_any = True
            reply_parts.append("AIニュース")
        if "今日やったこと" in content and run_today_diary_now():
            did_any = True
            reply_parts.append("今日やったこと")
        if did_any:
            try:
                await message.reply("✅ " + " / ".join(reply_parts) + " を取得して該当チャンネルに投稿しました。")
            except Exception:
                pass
            return
        if run_seo or run_ai or "今日やったこと" in content:
            try:
                await message.reply("該当Webhookが未設定か、取得に失敗しました。.env の Webhook 設定を確認してください。")
            except Exception:
                pass
            return

    # キューに追加
    if content.startswith("キューに追加:") or content.startswith("タスク追加:"):
        prefix = "キューに追加:" if content.startswith("キューに追加:") else "タスク追加:"
        instruction = content[len(prefix):].strip()
        if not instruction:
            try:
                await message.reply("タスク内容を入力してください。例: キューに追加: 〇〇を確認して")
            except Exception:
                pass
            return
        try:
            _, pending_count = queue_add(instruction)
            await message.reply(f"✅ タスクをキューに追加しました（待ち: {pending_count} 件）。")
        except Exception as e:
            try:
                await message.channel.send(f"🤖 **キュー追加エラー:** {str(e)[:300]}")
            except Exception:
                pass
        return

    # キュー一覧
    if content == "キュー一覧" or content.strip().lower() == "queue list":
        try:
            items = queue_list()
            if not items:
                await message.reply("キューに待ちタスクはありません。")
                return
            lines = [f"{i+1}. {it['instruction']} (追加: {it['created_at']})" for i, it in enumerate(items)]
            await message.reply("**キュー一覧:**\n" + "\n".join(lines)[:1900])
        except Exception:
            pass
        return

    # キューキャンセル（番号またはID）
    if content.startswith("キューキャンセル ") or content.lower().startswith("queue cancel "):
        rest = content.split(maxsplit=2)[-1].strip()
        if not rest:
            try:
                await message.reply("例: キューキャンセル 1")
            except Exception:
                pass
            return
        try:
            ok = queue_cancel(rest)
            await message.reply("✅ キャンセルしました。" if ok else "該当する待ちタスクが見つかりませんでした。")
        except Exception:
            pass
        return

    try:
        await run_agent(message.channel, message.author.id, message.content)
    except Exception:
        pass

# 起動時に利用可能なバックエンドをログ出力（stderr で即出るように）
skip_thinking_note = "（応答を速くするには .env に OLLAMA_SKIP_THINKING=1）" if (HAS_OLLAMA and not OLLAMA_SKIP_THINKING) else ""
msg = f"[Bot] LLM: Ollama（単体） — {'利用可能' + skip_thinking_note if HAS_OLLAMA else '未導入（pip install ollama と ollama list / ollama run でモデルを用意）'}"
print(msg, flush=True)
sys.stderr.write(msg + "\n")
sys.stderr.flush()

bot.run(TOKEN)