
# gtd_capture.py
import os, re, time, pathlib
from typing import Optional, List, Tuple
from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright

DEFAULT_URL = "https://sites.google.com/view/garden-td-values/unitsgamepasses?authuser=0"

def _slug(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "item"

def _pad(in_path: str, out_path: str, pad: int = 8):
    im = Image.open(in_path)
    ImageOps.expand(im, border=pad, fill="black").save(out_path)

def _auto_scroll(page, max_steps=50, pause=0.35):
    last = 0
    for _ in range(max_steps):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(pause)
        h = page.evaluate("document.body.scrollHeight")
        if h == last: break
        last = h

def _click_load_more(page, tries=20, pause=0.5):
    labels = ["Load more","Show more","More","See more"]
    for _ in range(tries):
        btn = None
        for lab in labels:
            loc = page.get_by_role("button", name=re.compile(lab, re.I))
            if loc.count(): btn = loc.first; break
        if not btn:
            loc = page.locator("text=/\\b(Load more|Show more|More|See more)\\b/i")
            if loc.count(): btn = loc.first
        if not btn: break
        try:
            btn.click(); time.sleep(pause)
        except Exception: break

_JS_MARK = """
() => {
  const marks=[], K=s=>(s||'').toUpperCase();
  const ok=t => t.includes('VALUE') && t.includes('DEMAND')
                 && (t.includes('STATUS')||t.includes('STABILITY'))
                 && (t.includes('LAST UPDATE')||t.includes('UPDATED'));
  for (const el of document.querySelectorAll('div,section,article')) {
    const t=K(el.innerText||''); if (!ok(t)) continue;
    const r=el.getBoundingClientRect();
    if (r.width<180 || r.height<150 || r.height>2000) continue;
    el.setAttribute('data-gtd-card','1'); marks.push(el);
  }
  return marks.length;
}
"""

def _title(handle) -> str:
    try:
        t = handle.get_by_role("heading").first.inner_text().strip()
        if t: return t
    except Exception: pass
    try:
        t = handle.locator("h1,h2,h3,h4").first.inner_text().strip()
        if t: return t
    except Exception: pass
    try:
        for line in handle.inner_text().splitlines():
            line=line.strip()
            if len(line)>=3: return line
    except Exception: pass
    return "unit"

def _read_counter(page) -> Optional[Tuple[int,int]]:
    pat = re.compile(r"PAGE\\s+(\\d+)\\s+OF\\s+(\\d+)", re.I)
    try:
        t = page.inner_text("body", timeout=2000)
        m = pat.search(t);  # main
        if m: return int(m.group(1)), int(m.group(2))
    except Exception: pass
    for f in page.frames:
        try:
            t = f.inner_text("body", timeout=2000)
            m = pat.search(t); 
            if m: return int(m.group(1)), int(m.group(2))
        except Exception: pass
    return None

def _click_next(page) -> bool:
    for ctx in [page] + list(page.frames):
        try:
            btns = ctx.get_by_role("button", name=re.compile(r"^\\s*Next\\s*$", re.I))
            if btns.count():
                b = btns.first
                try:
                    if b.is_disabled(): continue
                except Exception: pass
                b.click(); return True
        except Exception: pass
        try:
            loc = ctx.locator("xpath=//*[self::a or self::button][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'NEXT') and not(@disabled) and not(contains(@aria-disabled,'true'))]")
            if loc.count(): loc.first.click(); return True
        except Exception: pass
    return False

def capture_gtd_cards(
    url: str = DEFAULT_URL,
    pages: Optional[int] = None,
    out_dir: str = "shots",
    only_regex: Optional[str] = None,
    channel: Optional[str] = None,   # "msedge" or "chrome" if you can't install Chromium
    headed: bool = False,
    debug: bool = False
) -> List[str]:
    """
    Returns list of saved PNG paths across all pages.
    """
    base = pathlib.Path(out_dir); base.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []

    with sync_playwright() as p:
        launch_kwargs = {"headless": not headed}
        if channel:
            launch_kwargs["channel"] = channel
            if not headed:
                launch_kwargs["args"] = ["--headless=new"]  # new headless for Edge/Chrome
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(url, wait_until="networkidle", timeout=90_000); time.sleep(0.8)

        seen = set()
        page_num, page_total = (1, pages or 1)
        ctr = _read_counter(page)
        if ctr: page_num, page_total = ctr
        elif pages: page_total = pages

        for _ in range(page_total):
            ctr = _read_counter(page) or (page_num, page_total)
            page_num, page_total = ctr
            key = f"{page_num}/{page_total}"
            if key in seen: break
            seen.add(key)

            sub = base / f"page-{page_num}-of-{page_total}"
            sub.mkdir(parents=True, exist_ok=True)

            _click_load_more(page); _auto_scroll(page)

            handles = []
            for ctx in [page] + list(page.frames):
                try: n = ctx.evaluate(_JS_MARK)
                except Exception: n = 0
                if n:
                    loc = ctx.locator("[data-gtd-card='1']")
                    for i in range(loc.count()):
                        handles.append(loc.nth(i))

            if not handles and debug:
                (sub / "debug.html").write_text(page.content(), encoding="utf-8", errors="ignore")
                page.screenshot(path=str(sub / "debug_fullpage.png"), full_page=True)

            filt = re.compile(only_regex, re.I) if only_regex else None
            for idx, card in enumerate(handles, 1):
                title = _title(card)
                if filt and not filt.search(title): continue
                base_name = f"{idx:03d}_{_slug(title)}"
                raw = sub / f"{base_name}.raw.png"
                final = sub / f"{base_name}.png"
                card.screenshot(path=str(raw), animations="disabled", timeout=30_000)
                _pad(str(raw), str(final), pad=8)
                try: os.remove(raw)
                except OSError: pass
                saved.append(str(final))

            if page_num >= page_total: break
            if not _click_next(page): break
            page.wait_for_timeout(900); _auto_scroll(page)

        browser.close()

    return saved
