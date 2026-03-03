#!/usr/bin/env python3
"""
画面のスクリーンショットを撮り、指定した Discord ウェブフックでチャンネルに送信する。

使い方:
  1. Discord でチャンネルのウェブフックを作成し、URL を取得する。
  2. このスクリプトと同じフォルダに webhook_url.txt を作り、1行目にウェブフックURLを書く。
     または環境変数 DISCORD_WEBHOOK_URL に URL を設定する。
  3. 実行: python screenshot_to_channel.py

macOS では screencapture を使用します。
"""
import json
import os
import sys
import subprocess
import tempfile
import urllib.request

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# スクリプトのディレクトリ（project/）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WEBHOOK_URL_FILE = os.path.join(SCRIPT_DIR, "webhook_url.txt")


def get_webhook_url():
    """ウェブフックURLを webhook_url.txt または環境変数から取得する。"""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if url and url.startswith("https://discord.com/api/webhooks/"):
        return url
    if os.path.isfile(WEBHOOK_URL_FILE):
        try:
            with open(WEBHOOK_URL_FILE, "r", encoding="utf-8") as f:
                url = f.readline().strip()
            if url.startswith("https://discord.com/api/webhooks/"):
                return url
        except Exception:
            pass
    return None


def take_screenshot():
    """画面のスクリーンショットを撮り、保存したファイルパスを返す。失敗時は None。"""
    if sys.platform != "darwin":
        print("このスクリプトは macOS 用です。", file=sys.stderr)
        return None
    try:
        fd, path = tempfile.mkstemp(suffix=".png", prefix="screenshot_")
        os.close(fd)
        r = subprocess.run(
            ["screencapture", "-x", "-t", "png", path],
            capture_output=True,
            timeout=10,
            cwd=SCRIPT_DIR,
        )
        if r.returncode != 0:
            os.remove(path)
            return None
        return path
    except Exception as e:
        print(f"スクリーンショット取得エラー: {e}", file=sys.stderr)
        return None


def send_image_to_webhook(webhook_url, image_path, content=""):
    """画像ファイルを Discord ウェブフックに送信する。requests があればそれを使用（403 が出にくい）。"""
    if not os.path.isfile(image_path):
        return False, "ファイルがありません"

    payload = {"content": (content or "画面のスクリーンショット")}
    filename = os.path.basename(image_path)

    if HAS_REQUESTS:
        try:
            with open(image_path, "rb") as f:
                r = requests.post(
                    webhook_url,
                    data={"payload_json": json.dumps(payload, ensure_ascii=False)},
                    files={"file": (filename, f, "image/png")},
                    timeout=15,
                )
            if r.status_code in (200, 204):
                return True, "送信しました"
            return False, f"HTTP {r.status_code} {r.reason}"
        except Exception as e:
            return False, str(e)

    # フォールバック: urllib（User-Agent を付与）
    try:
        with open(image_path, "rb") as f:
            file_data = f.read()
    except Exception as e:
        return False, str(e)

    boundary = "----WebKitFormBoundary" + os.urandom(16).hex()
    payload_json = json.dumps(payload, ensure_ascii=False)
    body = []
    body.append(f"--{boundary}\r\n".encode("utf-8"))
    body.append(b'Content-Disposition: form-data; name="payload_json"\r\n')
    body.append(b"Content-Type: application/json; charset=UTF-8\r\n\r\n")
    body.append(payload_json.encode("utf-8"))
    body.append(f"\r\n--{boundary}\r\n".encode("utf-8"))
    body.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"))
    body.append(b"Content-Type: image/png\r\n\r\n")
    body.append(file_data)
    body.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    raw = b"".join(body)

    req = urllib.request.Request(
        webhook_url,
        data=raw,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(raw)),
            "User-Agent": "DiscordBot (https://github.com/discord, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            if res.status in (200, 204):
                return True, "送信しました"
            return False, f"HTTP {res.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} {e.reason}"
    except Exception as e:
        return False, str(e)


def main():
    webhook_url = get_webhook_url()
    if not webhook_url:
        print(
            "ウェブフックURLが設定されていません。\n"
            f"  - {WEBHOOK_URL_FILE} の1行目に Discord ウェブフックURLを書く\n"
            "  - または環境変数 DISCORD_WEBHOOK_URL を設定する",
            file=sys.stderr,
        )
        sys.exit(1)

    path = take_screenshot()
    if not path:
        print("スクリーンショットの取得に失敗しました。", file=sys.stderr)
        sys.exit(1)

    try:
        ok, msg = send_image_to_webhook(webhook_url, path, "画面のスクリーンショット")
        if ok:
            print(msg)
        else:
            print(f"送信失敗: {msg}", file=sys.stderr)
            sys.exit(1)
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


if __name__ == "__main__":
    main()
