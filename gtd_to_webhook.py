
# gtd_to_webhook.py
import argparse, os, sys, time, json, glob, subprocess, pathlib
from typing import List, Optional
import requests
from PIL import Image

DEFAULT_URL = "https://sites.google.com/view/garden-td-values/unitsgamepasses?authuser=0"
MAX_PER_MSG = 10
DEFAULT_CAPTION = "Garden TD value cards"

def ensure_under_limit(path: str, max_bytes: int) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return path
    if size <= max_bytes:
        return path
    im = Image.open(path).convert("RGB")
    q = 90
    tmp = pathlib.Path(path).with_suffix(".jpg")
    while q >= 50:
        im.save(tmp, "JPEG", quality=q, optimize=True)
        if os.path.getsize(tmp) <= max_bytes:
            break
        q -= 10
    return str(tmp)

def send_to_webhook(webhook_url: str, files: List[str], caption: str, username: Optional[str], max_upload_mb: int) -> None:
    max_bytes = max_upload_mb * 1024 * 1024
    with requests.Session() as s:
        for i in range(0, len(files), MAX_PER_MSG):
            batch = files[i:i+MAX_PER_MSG]
            form = {}
            opened = []
            try:
                for idx, fp in enumerate(batch):
                    fp2 = ensure_under_limit(fp, max_bytes)
                    f = open(fp2, "rb")
                    opened.append(f)
                    form[f"files[{idx}]"] = (os.path.basename(fp2), f, "application/octet-stream")
                payload = {"content": caption}
                if username:
                    payload["username"] = username
                form["payload_json"] = (None, json.dumps(payload), "application/json")
                r = s.post(webhook_url, files=form, timeout=60)
                if r.status_code == 429:
                    retry = r.json().get("retry_after", 1000) / 1000.0
                    time.sleep(retry + 0.5)
                    r = s.post(webhook_url, files=form, timeout=60)
                if r.status_code >= 300:
                    print("Webhook error:", r.status_code, r.text)
                    r.raise_for_status()
                time.sleep(0.8)
            finally:
                for f in opened:
                    try: f.close()
                    except: pass

def run_scraper(out_dir: str, url: str, pages: Optional[int], channel: Optional[str], only: Optional[str], headed: bool, debug: bool) -> None:
    cmd = [sys.executable, "gtd_card_screenshots_v5.py", "--out", out_dir, "--url", url]
    if pages is not None: cmd += ["--pages", str(pages)]
    if channel: cmd += ["--channel", channel]
    if only: cmd += ["--only", only]
    if headed: cmd += ["--headed"]
    if debug: cmd += ["--debug"]
    print("Running:", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr)
        raise SystemExit(res.returncode)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run the GTD screenshotter and upload PNGs to a Discord webhook.")
    ap.add_argument("--webhook", required=True, help="Discord webhook URL")
    ap.add_argument("--caption", default=DEFAULT_CAPTION)
    ap.add_argument("--username", help="Override webhook username")
    ap.add_argument("--max-mb", type=int, default=8, help="Per-file upload cap (MB)")
    ap.add_argument("--out", default="shots_out", help="Output folder for screenshots")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--pages", type=int, help="Total pages if PAGE X OF Y isn’t detectable (e.g., 7)")
    ap.add_argument("--channel", choices=["msedge","chrome"], help="Use system Edge/Chrome instead of Playwright Chromium")
    ap.add_argument("--only", help="Regex filter for unit names")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    # Optional: if you want this CLI to do the capture itself via gtd_capture instead of shelling out, you could import and run capture_gtd_cards here.
    # For now, we assume you already have gtd_card_screenshots_v5.py in your project; otherwise, replace run_scraper(...) with gtd_capture.capture_gtd_cards(...).
    # run_scraper(args.out, args.url, args.pages, args.channel, args.only, args.headed, args.debug)

    # Use gtd_capture directly (safer, avoids dependency on external script)
    try:
        from gtd_capture import capture_gtd_cards
    except Exception as e:
        print("Failed to import gtd_capture:", e)
        raise

    paths = capture_gtd_cards(url=args.url, pages=args.pages, out_dir=args.out, only_regex=args.only, channel=args.channel, headed=args.headed, debug=args.debug)
    if not paths:
        print("No PNGs found to send.")
        sys.exit(0)
    print(f"Uploading {len(paths)} image(s) to webhook…")
    send_to_webhook(args.webhook, paths, args.caption, args.username, args.max_mb)
    print("Done.")
