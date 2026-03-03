#!/usr/bin/env python3
"""各チャンネルを実際の機能に合わせて投稿する（スキル一覧・今日やったこと・SEO/AIニュース等）。"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKING_DIR = os.path.join(SCRIPT_DIR, "project")
KNOWLEDGE_DIR = os.path.join(WORKING_DIR, "knowledge")
AUTONOMOUS_TASKS_PATH = os.path.join(WORKING_DIR, "autonomous_tasks.json")
DAILY_LOG_DIR = os.path.join(WORKING_DIR, "daily_log")
KEYS = ("skills_list", "terminal", "today_diary", "seo", "ai")
LABELS = {
    "skills_list": "スキルリスト",
    "terminal": "ターミナル",
    "today_diary": "今日やったこと",
    "seo": "SEOチャンネル",
    "ai": "AIチャンネル",
}

try:
    from duckduckgo_search import DDGS
    HAS_WEB_SEARCH = True
except ImportError:
    HAS_WEB_SEARCH = False

env_webhooks = {
    "skills_list": os.environ.get("DISCORD_WEBHOOK_SKILLS_LIST", "").strip(),
    "terminal": os.environ.get("DISCORD_WEBHOOK_TERMINAL", "").strip(),
    "today_diary": os.environ.get("DISCORD_WEBHOOK_TODAY_DIARY", "").strip(),
    "seo": os.environ.get("DISCORD_WEBHOOK_SEO", "").strip(),
    "ai": os.environ.get("DISCORD_WEBHOOK_AI", "").strip(),
}

path = os.path.join(WORKING_DIR, "discord_webhooks.json")
if os.path.isfile(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            file_wh = json.load(f)
        for k in KEYS:
            if k in file_wh and isinstance(file_wh[k], str) and file_wh[k].strip().startswith("https://discord.com/api/webhooks/"):
                if not env_webhooks.get(k):
                    env_webhooks[k] = file_wh[k].strip()
    except Exception:
        pass


def send_webhook(url, content, username=None):
    data = {"content": (content or "").strip()[:2000]}
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
    with urllib.request.urlopen(req, timeout=15) as res:
        return res.status in (200, 204)


def get_list_skills():
    """ナレッジフォルダ内のスキル一覧を返す。"""
    if not os.path.isdir(KNOWLEDGE_DIR):
        return "登録されているスキルはまだありません。"
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
    return "**登録スキル一覧**（随時更新）\n\n" + ("\n".join(lines) if lines else "登録されているスキルはまだありません。")


def get_today_diary_content():
    """本日の作業ログ＋自律タスクをレポート形式で返す。"""
    today = datetime.now().strftime("%Y-%m-%d")
    today_jp = datetime.now().strftime("%Y年%m月%d日")
    log_path = os.path.join(DAILY_LOG_DIR, today + ".txt")
    report_lines = [
        "# 📔 日付レポート",
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
    try:
        tasks = json.load(open(AUTONOMOUS_TASKS_PATH, "r", encoding="utf-8")) if os.path.isfile(AUTONOMOUS_TASKS_PATH) else []
    except Exception:
        tasks = []
    done_today = [t for t in tasks if t.get("status") in ("done", "failed") and (t.get("done_at") or "")[:10] == today]
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


def _is_domestic_url(href):
    """国内サイトのURLかどうか。"""
    if not href:
        return False
    h = href.lower()
    doms = (".jp", "itmedia.co.jp", "nikkei.com", "reuters.co.jp", "impress.co.jp",
            "atmarkit.co.jp", "ascii.jp", "gihyo.jp", "thinkit.co.jp", "news.yahoo.co.jp",
            "cnet.com/japan", "techcrunch.com/japan")
    return any(d in h for d in doms) or h.endswith(".jp")


def fetch_news_once(query, max_items=5):
    """検索1回実行。国内を優先し、ヘッドライン＋記事リンク形式で返す。"""
    if not HAS_WEB_SEARCH:
        return None
    try:
        results = list(DDGS().text(query, max_results=max_items + 5))
    except Exception:
        return None
    if not results:
        return None
    # 国内を優先してソート
    sorted_results = sorted(results, key=lambda r: (0 if _is_domestic_url(r.get("href")) else 1))
    lines = []
    for i, r in enumerate(sorted_results[:max_items], 1):
        title = (r.get("title") or "").strip()[:100]
        href = (r.get("href") or "").strip()
        if title and href:
            lines.append(f"{i}. **{title}**\n   [記事を読む]({href})")
    return "\n\n".join(lines)[:2000] if lines else None


def fetch_news_with_retry(queries, max_items=5, max_attempts=5, delay_sec=2):
    """複数クエリでリトライし、結果が取れるまで試す。"""
    import time
    for attempt in range(max_attempts):
        for q in queries:
            content = fetch_news_once(q, max_items=max_items)
            if content:
                return content
            time.sleep(delay_sec)
    return None


def main():
    print("各チャンネルに実際の機能に合わせた内容を投稿します...\n")
    # スキルリスト
    url = env_webhooks.get("skills_list", "")
    if url and url.startswith("https://discord.com/api/webhooks/"):
        try:
            body = get_list_skills()
            send_webhook(url, body, username=LABELS["skills_list"])
            print("  [スキルリスト] 投稿しました（登録スキル一覧）")
        except Exception as e:
            print(f"  [スキルリスト] エラー: {e}")
    else:
        print("  [スキルリスト] URL未設定のためスキップ")
    # ターミナル（説明のみ）
    url = env_webhooks.get("terminal", "")
    if url and url.startswith("https://discord.com/api/webhooks/"):
        try:
            body = (
                "🖥️ **ターミナルチャンネル**\n\n"
                "Botの処理（タスク開始・思考・ツール実行・run_scriptの出力）がリアルタイムでここに流れます。"
            )
            send_webhook(url, body, username=LABELS["terminal"])
            print("  [ターミナル] 投稿しました（チャンネル説明）")
        except Exception as e:
            print(f"  [ターミナル] エラー: {e}")
    else:
        print("  [ターミナル] URL未設定のためスキップ")
    # 今日やったこと
    url = env_webhooks.get("today_diary", "")
    if url and url.startswith("https://discord.com/api/webhooks/"):
        try:
            body = get_today_diary_content()
            send_webhook(url, body, username=LABELS["today_diary"])
            print("  [今日やったこと] 投稿しました")
        except Exception as e:
            print(f"  [今日やったこと] エラー: {e}")
    else:
        print("  [今日やったこと] URL未設定のためスキップ")
    # SEOニュース（国内サイトを参考に、ヘッドライン＋記事リンク形式）
    SEO_QUERIES = [
        "SEO ニュース 日本 最新",
        "SEO ニュース 国内",
        "検索エンジン 最適化 ニュース 日本",
        "SEO トレンド 日本",
        "Google アルゴリズム アップデート ニュース",
    ]
    url = env_webhooks.get("seo", "")
    if url and url.startswith("https://discord.com/api/webhooks/"):
        try:
            content = fetch_news_with_retry(SEO_QUERIES, max_items=5, max_attempts=4, delay_sec=2)
            if content:
                body = "🔍 **SEOニュース**（国内サイトより）\n\n" + content[:1900]
                print("  [SEOチャンネル] ニュース取得して投稿しました")
            else:
                body = "🔍 **SEOニュース**\n\n本チャンネルでは毎日6時に最新のSEOニュースを自動投稿します。"
                print("  [SEOチャンネル] 取得できなかったため案内文を投稿しました")
            send_webhook(url, body, username=LABELS["seo"])
        except Exception as e:
            print(f"  [SEOチャンネル] エラー: {e}")
    else:
        print("  [SEOチャンネル] URL未設定のためスキップ")
    # AIニュース（国内サイトを参考に、ヘッドライン＋記事リンク形式）
    AI_QUERIES = [
        "AI 人工知能 ニュース 日本 最新",
        "AI ニュース 国内",
        "人工知能 ニュース 日本",
        "ChatGPT ニュース 日本",
        "生成AI ニュース 国内",
    ]
    url = env_webhooks.get("ai", "")
    if url and url.startswith("https://discord.com/api/webhooks/"):
        try:
            content = fetch_news_with_retry(AI_QUERIES, max_items=5, max_attempts=4, delay_sec=2)
            if content:
                body = "🤖 **AIニュース**（国内サイトより）\n\n" + content[:1900]
                print("  [AIチャンネル] ニュース取得して投稿しました")
            else:
                body = "🤖 **AIニュース**\n\n本チャンネルでは毎日6時に最新のAIニュースを自動投稿します。"
                print("  [AIチャンネル] 取得できなかったため案内文を投稿しました")
            send_webhook(url, body, username=LABELS["ai"])
        except Exception as e:
            print(f"  [AIチャンネル] エラー: {e}")
    else:
        print("  [AIチャンネル] URL未設定のためスキップ")
    print("\n完了。Discordの各チャンネルを確認してください。")


if __name__ == "__main__":
    main()
