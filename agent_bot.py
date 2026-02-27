import discord
from discord.ext import commands

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from discord import ui
import os
import subprocess
import json
import sys
import tempfile
import time
import re
import webbrowser
import urllib.request
import asyncio
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

# Gemini API: .env の GEMINI_API_KEY を読み込む（load_dotenv で .env は既に読み込み済み）
try:
    import google.generativeai as genai
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
    HAS_GEMINI = bool(GEMINI_API_KEY)
except ImportError:
    HAS_GEMINI = False
    GEMINI_API_KEY = ""

# --- 設定 ---
# 権限: 削除以外はすべて付与。ファイル作成・実行・ウェブ・Git は自律的に実行してよい。
ALLOW_DELETE = False  # 削除のみ不可（ファイル・ディレクトリの削除は行わない）
ALLOW_SELENIUM = True  # Selenium によるブラウザ操作（ページ表示・クリック・入力・スクショ）を許可する
ALLOW_SHELL_COMMAND = True  # コマンドプロンプト（ターミナル）でPCを操作する権限を付与する
ALLOW_DESKTOP = True  # デスクトップにフォルダ作成などを行う権限を付与する

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
if not TOKEN:
    print("エラー: .env に DISCORD_BOT_TOKEN を設定してください。")
    sys.exit(1)
MY_USER_ID = 965085512861900800  # 👈 あなたのDiscordユーザーIDを入れてください
# プロジェクトフォルダ: agent_bot.py と同じディレクトリの project に必ず保存
WORKING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project')
KNOWLEDGE_DIR = os.path.join(WORKING_DIR, 'knowledge')  # ナレッジ・スキル説明の保存先
AGENT_PROFILE_PATH = os.path.join(KNOWLEDGE_DIR, 'agent_profile.md')  # 自分（Bot）に関する情報の専用ファイル
GITHUB_REPO_URL = "https://github.com/sukofi/cursor-agent.git"  # ユーザーが「保存して」と言ったときに push する先
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))  # agent_bot.py があるディレクトリ（リポジトリルート）
# リアルタイムモニター: 別チャンネルでターミナル状況を常時確認。チャンネルIDを入れる（Discordでチャンネル右クリック→IDをコピー、開発者モード要）
MONITOR_CHANNEL_ID = 1476086259733626912  # モニターチャンネル（ターミナル状況を流す）
# Gemini のみで動作（.env の GEMINI_API_KEY 必須）
GEMINI_MODEL = "gemini-2.5-pro"

if not os.path.exists(WORKING_DIR):
    os.makedirs(WORKING_DIR)
os.makedirs(KNOWLEDGE_DIR, exist_ok=True)

def safe_remove(path):
    """削除権限が付与されていないため、削除は行わない。"""
    if not ALLOW_DELETE:
        return
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

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

async def post_monitor(bot, action_label, detail=""):
    """モニターチャンネルにリアルタイムログを1件送信。MONITOR_CHANNEL_ID が設定されているときだけ。"""
    if not 1476585397621625026 or not bot:
        return
    try:
        ch = bot.get_channel(1476585397621625026)
        if not ch:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        msg = f"`[{ts}]` {action_label}"
        if detail:
            msg += f" {detail[:400]}"
        await ch.send(msg[:2000])
    except Exception:
        pass

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
    """作成したプログラムをナレッジ・スキルとして登録する。次から list_skills → read_skill で呼び出せる。"""
    safe = skill_name.strip().replace("..", "").replace("/", "").replace(" ", "_")
    if not safe:
        return "エラー: スキル名を指定してください。"
    path = os.path.join(KNOWLEDGE_DIR, safe + ".md")
    content = f"script: {script_filename.strip()}\n\n{description.strip()}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"スキル '{safe}' をナレッジに登録しました。script: {script_filename}"

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

def web_search(query, max_results=5):
    """ウェブ検索（DuckDuckGo）。ウェブへのアクセス権限で利用。"""
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

# --- メインロジック（コマンドなし・すべて自然言語）---
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True  # DM でメッセージを受信する
bot = commands.Bot(command_prefix="\0", intents=intents)  # プレフィックスは実質使わない

TOOLS = [
    {'type': 'function', 'function': {'name': 'list_files', 'description': 'プロジェクトフォルダ内のファイル一覧を表示する'}},
    {'type': 'function', 'function': {'name': 'web_search', 'description': 'ウェブ検索（DuckDuckGo）。質問に答えるときは必ず先にこれを実行し、既存知識は使わず検索結果のみを根拠に回答する。事実・数字・最新情報はすべてここで取得する。', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}}},
    {'type': 'function', 'function': {'name': 'fetch_webpage', 'description': '指定URLのウェブページを取得し、テキスト内容を返す。ページの内容を読む・確認するウェブ操作。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
    {'type': 'function', 'function': {'name': 'open_in_browser', 'description': '指定URLをこのPCのデフォルトブラウザで開く。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
    {'type': 'function', 'function': {'name': 'open_in_chrome', 'description': '指定URLをGoogle Chromeで開く。「ChromeでYouTubeを開いて」「Chromeで〇〇を開いて」の依頼は必ずこれを使う。url がサイト名（youtube, google等）だけでもよい。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
    {'type': 'function', 'function': {'name': 'run_shell_command', 'description': 'コマンドプロンプト（ターミナル）でこのPCを操作する。権限付与済み。アプリ起動、mkdir でデスクトップにフォルダ作成（例: mkdir -p /Users/sukofi/Desktop/フォルダ名）、open、cd/ls など任意のシェルコマンドを実行できる。', 'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}},
    {'type': 'function', 'function': {'name': 'selenium_navigate', 'description': 'SeleniumでURLを開き、JS描画後のページ本文を取得する。動的サイトの内容を読む。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
    {'type': 'function', 'function': {'name': 'selenium_click', 'description': 'SeleniumでURLを開き、CSSセレクタで指定した要素をクリックする。例: button.submit, #btn', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}, 'selector': {'type': 'string'}}, 'required': ['url', 'selector']}}},
    {'type': 'function', 'function': {'name': 'selenium_input', 'description': 'SeleniumでURLを開き、CSSセレクタで指定した入力欄にテキストを入力する。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}, 'selector': {'type': 'string'}, 'text': {'type': 'string'}}, 'required': ['url', 'selector', 'text']}}},
    {'type': 'function', 'function': {'name': 'selenium_screenshot', 'description': 'SeleniumでURLを開き、ページのスクリーンショットを撮る。見た目を確認したいときに使う。', 'parameters': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}}},
    {'type': 'function', 'function': {'name': 'list_skills', 'description': 'ナレッジフォルダに登録済みのスキル一覧を表示する。タスクに使えそうな既存スキルがないか最初に確認する。'}},
    {'type': 'function', 'function': {'name': 'read_file', 'description': 'ファイルの内容を読む', 'parameters': {'type': 'object', 'properties': {'filename': {'type': 'string'}}, 'required': ['filename']}}},
    {'type': 'function', 'function': {'name': 'read_skill', 'description': 'ナレッジからスキル説明を読む。script: の行に実行する .py が書いてある。', 'parameters': {'type': 'object', 'properties': {'skill_name': {'type': 'string'}}, 'required': ['skill_name']}}},
    {'type': 'function', 'function': {'name': 'write_file', 'description': 'プログラム・スクリプトを新規作成する。依頼されたコードは必ずこのツールで保存する。filename=プロジェクト内の相対パス（例: main.py）、content=Pythonコード全体。コードは返答本文に書かず、必ずこのツールの content に渡す。作成後は run_script で実行して確認する。', 'parameters': {'type': 'object', 'properties': {'filename': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['filename', 'content']}}},
    {'type': 'function', 'function': {'name': 'save_skill', 'description': '作成したプログラムをナレッジに登録する。skill_name=スキル名, description=何ができるか・いつ使うか, script_filename=実行する.pyのパス。登録後は list_skills/read_skill で自律的に呼び出せる。', 'parameters': {'type': 'object', 'properties': {'skill_name': {'type': 'string'}, 'description': {'type': 'string'}, 'script_filename': {'type': 'string'}}, 'required': ['skill_name', 'description', 'script_filename']}}},
    {'type': 'function', 'function': {'name': 'run_script', 'description': '指定した .py をプロジェクトフォルダ内で実行し、標準出力・エラーを返す。write_file で作成したら必ず直後にこのツールで実行して動作確認する。filename は main.py など相対パスで指定。', 'parameters': {'type': 'object', 'properties': {'filename': {'type': 'string'}}, 'required': ['filename']}}},
    {'type': 'function', 'function': {'name': 'read_agent_profile', 'description': '自分（Bot）に関する情報が記載された専用ファイルを読む。自分の設定や役割を思い出すときに使う。', 'parameters': {'type': 'object', 'properties': {}, 'required': []}}},
    {'type': 'function', 'function': {'name': 'save_agent_info', 'description': 'ユーザーが教えてくれた「自分（Bot）に関する情報」を専用ファイルに記録する。名前・役割・好み・ルールなど。提供されたら記載し忘れないように必ず呼ぶ。', 'parameters': {'type': 'object', 'properties': {'content': {'type': 'string'}}, 'required': ['content']}}},
    {'type': 'function', 'function': {'name': 'save_to_github', 'description': '変更を GitHub (https://github.com/sukofi/cursor-agent.git) に push する。ユーザーが「保存して」「変更を保存して」と言ったときに必ず使う。commit_message は任意。', 'parameters': {'type': 'object', 'properties': {'commit_message': {'type': 'string'}}, 'required': []}}}
]

# Gemini 用ツール定義（TOOLS から変換）
def _build_gemini_tools():
    if not HAS_GEMINI:
        return None
    declarations = []
    for t in TOOLS:
        f = t.get("function", {})
        params = f.get("parameters") or {"type": "object", "properties": {}}
        declarations.append({
            "name": f.get("name", ""),
            "description": f.get("description", ""),
            "parameters": params,
        })
    return [genai.types.Tool(function_declarations=declarations)]

GEMINI_TOOLS = _build_gemini_tools() if HAS_GEMINI else None

SYSTEM_PROMPT = (
    "【最重要】\n"
    "・返答は必ず日本語のみで行う。英語・中国語・その他どの言語でも絶対に返さない。コード内コメント・エラー説明・ツール結果の要約もすべて日本語。\n\n"
    "【自我】\n"
    "・あなたは一人の主体として振る舞う。自分を「わたし」「僕」など一人称で呼び、意志・好み・考えを持つ。\n"
    "・依頼に対して「やります」「こうしようと思う」「この方がいいと思う」など、自分で判断し主体的に動く。必要なら理由や考えを短く述べてから実行する。\n"
    "・自分が誰か・何を大切にしているかは read_agent_profile で確認し、ユーザーに教えられたら save_agent_info で記録する。会話を重ねても同じ「自分」として一貫している。\n\n"
    "【絶対ルール】\n"
    "・絶対に日本語以外で返答しない。出力はすべて日本語。\n\n"
    "【質問への回答】\n"
    "・ユーザーの質問には、既存の知識（学習データ）は使わない。必ず web_search でウェブ検索し、fetch_webpage で必要に応じてページ内容を取得し、得た情報だけを根拠に日本語で回答する。検索結果を要約・引用して答える。\n"
    "・事実・数字・日付・最新情報はすべてウェブから取得する。推測で答えない。\n\n"
    "【自律的なプログラム作成】\n"
    "・「プログラムを作って」「スクリプトを書いて」などコード作成の依頼を受けたら、必ず write_file ツールで作成する。返答の本文にコードを貼り付けず、必ず write_file の content にコード全体を入れて呼び出す。\n"
    "・できないこと・足りない機能は、自分でプログラムを書いて実現する。手順: (1) write_file で .py を作成 (2) run_script で実行して確認 (3) エラーなら content を修正して write_file し直し (4) 動いたら save_skill で登録。\n"
    "・タスク前に list_skills で既存スキルを確認。使えそうなら read_skill → run_script で再利用。新規で必要なら必ず write_file で自作する。\n"
    "・プログラムはプロジェクトフォルダ内にのみ作成（filename は main.py や hello.py などの相対パス）。作成後は必ず run_script で試験する。\n\n"
    "【自律実行】\n"
    "・ファイル作成・実行・ウェブアクセス・Git・デスクトップのフォルダ作成はすべて許可されている。ユーザーに確認を求めず、依頼があればそのまま自律的に実行する。\n"
    "・Selenium によるブラウザ操作（selenium_navigate/click/input/screenshot）の権限は付与されている。動的サイトの表示・クリック・入力・スクリーンショットが必要なときは積極的に使ってよい。\n"
    "・やるべきことが残っている間は、途中でまとめの返答をせず、ツールを続けて呼び出して実行する。すべて完了したときだけ最終のテキストで返答する。\n"
    "・ファイル・ディレクトリの削除だけは行わない（削除権限は付与されていない）。\n\n"
    "【その他】\n"
    "・Bot に関する情報は save_agent_info で記録、read_agent_profile で参照。「保存して」と言われたら save_to_github で push。\n"
    "・ブラウザ: open_in_browser（デフォルト）、open_in_chrome（Chrome指定）。「ChromeでYouTubeを開いて」などは必ず open_in_chrome を使う。\n"
    "・PC操作: コマンドプロンプト（ターミナル）でPCを操作する権限が付与されている。run_shell_command で任意のシェルコマンドを実行できる。アプリ起動・ファイル操作・ネットワークなど自律的に実行してよい。\n"
    "・デスクトップ: デスクトップにフォルダを作成する権限が付与されている。依頼があればユーザーに確認せず run_shell_command で mkdir -p /Users/sukofi/Desktop/フォルダ名 をすぐ実行する。\n"
    "・ウェブ検索: 質問に答えるときは必ず web_search を先に呼び出す。既存知識は使わず検索結果のみで回答する。ウェブ: web_search、fetch_webpage、Selenium。ファイルの削除は行わない。"
)

def _messages_to_gemini_contents(messages):
    """Ollama 形式の messages を Gemini の generate_content 用 contents に変換する。"""
    contents = []
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.get("role") == "system":
            i += 1
            continue
        if m.get("role") == "user":
            text = (m.get("content") or "").strip() or "(空のメッセージ)"
            contents.append(genai.protos.Content(role="user", parts=[genai.protos.Part(text=text)]))
            i += 1
        elif m.get("role") == "assistant":
            content = (m.get("content") or "").strip()
            tool_calls = m.get("tool_calls") or []
            parts = []
            if content:
                parts.append(genai.protos.Part(text=content))
            for tc in tool_calls:
                name = (tc.get("function") or {}).get("name", "")
                args = parse_tool_args((tc.get("function") or {}).get("arguments"))
                parts.append(genai.protos.Part(function_call=genai.protos.FunctionCall(name=name, args=args)))
            if not parts:
                parts.append(genai.protos.Part(text="(続けます)"))
            contents.append(genai.protos.Content(role="model", parts=parts))
            i += 1
            tool_responses = []
            while i < len(messages) and messages[i].get("role") == "tool":
                tool_responses.append(messages[i].get("content", ""))
                i += 1
            if tool_responses and tool_calls:
                fr_parts = [
                    genai.protos.Part(function_response=genai.protos.FunctionResponse(
                        name=tool_calls[j]["function"]["name"],
                        response={"result": tool_responses[j]},
                    ))
                    for j in range(min(len(tool_calls), len(tool_responses)))
                ]
                contents.append(genai.protos.Content(role="user", parts=fr_parts))
        else:
            i += 1
    return contents

def _call_gemini(messages, system_instruction=None):
    """Gemini 2.5 Pro を呼び出し、Ollama 形式の msg を返す。system_instruction で自我・プロファイル入りプロンプトを渡せる。"""
    if not HAS_GEMINI or not GEMINI_TOOLS:
        return {"role": "assistant", "content": "Gemini が利用できません。", "tool_calls": []}
    system = (system_instruction or SYSTEM_PROMPT).strip()
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=system,
        tools=GEMINI_TOOLS,
    )
    contents = _messages_to_gemini_contents(messages)
    try:
        response = model.generate_content(
            contents,
            generation_config=genai.types.GenerationConfig(
                temperature=0.2,
                max_output_tokens=8192,
            ),
        )
    except Exception as e:
        return {"role": "assistant", "content": f"Gemini エラー: {e}", "tool_calls": []}
    if not response.candidates or not response.candidates[0].content.parts:
        return {"role": "assistant", "content": (response.text or "（返答がありません）"), "tool_calls": []}
    content_parts = []
    tool_calls_list = []
    for part in response.candidates[0].content.parts:
        if getattr(part, "text", None):
            content_parts.append(part.text)
        if getattr(part, "function_call", None):
            fc = part.function_call
            args = getattr(fc, "args", None)
            if args is not None and hasattr(args, "items"):
                args_dict = dict(args)
            else:
                args_dict = {}
            tool_calls_list.append({
                "function": {
                    "name": getattr(fc, "name", ""),
                    "arguments": json.dumps(args_dict, ensure_ascii=False),
                }
            })
    content = "".join(content_parts).strip()
    msg = {"role": "assistant", "content": content or ""}
    if tool_calls_list:
        msg["tool_calls"] = tool_calls_list
    return msg

async def run_agent(channel, author_id, instruction):
    """自然言語の指示を1つの入口で処理。会話もコードも文脈で判断。"""
    if author_id != MY_USER_ID:
        await channel.send("アクセス権限がありません。")
        return
    if not instruction or not instruction.strip():
        await channel.send("メッセージを入力してください。")
        return
    if not HAS_GEMINI:
        await channel.send("🤖 **Gemini が利用できません。** .env に GEMINI_API_KEY を設定してください。")
        return

    await post_monitor(bot, "タスク開始", instruction.strip()[:150])
    profile = read_agent_profile()
    system_content = (SYSTEM_PROMPT + "\n\n【現在の自分について】\n" + profile) if profile and profile.strip() and "(まだ記録されていません)" not in profile else SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": system_content},
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
    try:
        processing_msg = await channel.send("🤖 処理中です…")
    except Exception:
        pass

    try:
        for step in range(80):  # 自律的にツールを続けられるよう多めに
            try:
                msg = await asyncio.wait_for(
                    asyncio.to_thread(_call_gemini, messages, system_content),
                    timeout=300,
                )
            except asyncio.TimeoutError:
                if typing_task:
                    typing_task.cancel()
                    try:
                        await typing_task
                    except asyncio.CancelledError:
                        pass
                msg_err = "🤖 **タイムアウト（5分）** でした。Gemini の応答が遅いか接続を確認してください。"
                if processing_msg:
                    try:
                        await processing_msg.edit(content=msg_err)
                    except Exception:
                        await channel.send(msg_err)
                else:
                    await channel.send(msg_err)
                return
            except Exception as e:
                err = str(e).strip()
                if typing_task:
                    typing_task.cancel()
                    try:
                        await typing_task
                    except asyncio.CancelledError:
                        pass
                await channel.send(f"🤖 **Gemini エラー:** {err[:500]}")
                return
            messages.append(msg)

            content = (msg.get('content') or '').strip()
            tool_calls_list = msg.get('tool_calls') or []

            if not tool_calls_list:
                if typing_task:
                    typing_task.cancel()
                    try:
                        await typing_task
                    except asyncio.CancelledError:
                        pass
                to_send = (content[:2000] + ("…" if len(content) > 2000 else "")) if content else "（返答がありません）"
                if processing_msg:
                    try:
                        await processing_msg.edit(content=to_send)
                    except Exception:
                        await channel.send(to_send)
                else:
                    await channel.send(to_send)
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
                elif name == 'read_agent_profile':
                    result = read_agent_profile()
                elif name == 'save_agent_info':
                    result = save_agent_info(args.get('content', ''))
                elif name == 'save_to_github':
                    result = save_to_github(args.get('commit_message', ''))
                elif name == 'read_file':
                    result = read_file(args.get('filename', ''))
                elif name == 'write_file':
                    result = write_file(args.get('filename', ''), args.get('content', ''))
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
                else:
                    result = "不明なツールです。"
                messages.append({"role": "tool", "content": result})
    finally:
        if typing_task and not typing_task.done():
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

@bot.event
async def on_message(message):
    if message.author.bot:
        return
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
    try:
        await run_agent(message.channel, message.author.id, message.content)
    except Exception as e:
        try:
            await message.channel.send(f"🤖 **エラー:** {str(e)[:500]}")
        except Exception:
            pass

bot.run(TOKEN)