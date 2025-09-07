
# bot.py — ToukaBot (all-in-one)
# Features:
# - Token loader (DISCORD_TOKEN or token.txt)
# - Units scanning from units_assets/ with aliases (aliases.json optional)
# - /unit <name>  → composite image (main + stats)
# - /units [name|per_page] → **button-paged** list or details
# - /wheel [include|exclude] → CS:GO-style GIF that stops on winner + Respin
# - /team [size|allow_duplicates|include|exclude] → roulette + collage + Respin
# - /menu → clean button UI (case, team, values links, units)
# - /values → link buttons to official site; /valueslive → experimental parser
# - /assetsinfo → counts and assets folder path
# - /reload → rescan assets/aliases/units
# - /setoutputdir → change where GIFs/PNGs are saved (persisted to config.json)
# - /configshow → print config
# - Autorole on join: /autorole show|set|clear  (Members intent requested only if configured)
# - Upload-to-update system: /updateset, /updateinfo, /ingest + auto ingest in channel
#
# Requires: discord.py>=2.3, Pillow, requests, beautifulsoup4

import os, json, re, asyncio, random, time
from typing import List, Optional, Dict, Tuple

from PIL import Image, ImageDraw, ImageFont
import discord
from discord import app_commands

# ----------------------------- Config / Paths --------------------------------
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

UNITS_TXT    = os.getenv("UNITS_TXT", "units.txt")
ASSETS_DIR   = os.getenv("UNITS_ASSETS_DIR", "units_assets")
ALIASES_JSON = os.getenv("ALIASES_JSON", "aliases.json")
CONFIG_JSON  = os.getenv("CONFIG_JSON", "config.json")

VALUES_URL   = os.getenv("VALUES_URL", "https://sites.google.com/view/garden-td-values/main-page?authuser=0")
CALC_URL     = os.getenv("CALC_URL",   "https://sites.google.com/view/garden-td-values/value-calculator?authuser=0")

DEFAULT_CONFIG = {
    "UPDATE_CHANNEL_ID": None,
    "OUTPUT_DIR": "media",
    "SHOW_COLLAGE": True,
    "STRIP_TILE_W": 128,
    "STRIP_TILE_H": 96,
    "STRIP_PAD": 6,
    "STRIP_BG": "#c49a6c",
    "STRIP_CARD": "#4a3a2a",
    "SPIN_HOPS_SLOT": 9,
    "CASE_VISIBLE": 7,
    "CASE_FRAMES": 18,
    "CASE_DURATION_MS": 90,
    "CASE_FINAL_HOLD_MS": 1600,
    "GIF_LOOP": 1,
    "AUTO_ROLE_ID": None
}

def _load_json(path: str) -> Optional[dict]:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return None
    return None

def _save_json(path: str, data: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[config] save failed:", e)

CONFIG = DEFAULT_CONFIG.copy()
cfg = _load_json(CONFIG_JSON)
if cfg:
    for k in DEFAULT_CONFIG:
        if k in cfg:
            CONFIG[k] = cfg[k]

OUTPUT_DIR = str(CONFIG.get("OUTPUT_DIR") or "media").strip() or "media"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def _parse_color(s: str):
    s = str(s)
    if s.startswith("#") and len(s) == 7:
        return (int(s[1:3],16), int(s[3:5],16), int(s[5:7],16), 255)
    return (196,154,108,255)

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[_\-]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s

def load_units() -> List[str]:
    units: List[str] = []
    if os.path.isfile(UNITS_TXT):
        with open(UNITS_TXT, "r", encoding="utf-8") as f:
            for line in f:
                name = " ".join(line.strip().split())
                if name: units.append(name)
    else:
        for k in scan_images(ASSETS_DIR).keys():
            units.append(" ".join(w.capitalize() for w in k.split()))
    if not units:
        units = ["Tomato","Cactus","Pumpkin","Rose","Umbra","Onion","Bee"]
    dedup = list(dict.fromkeys(units))
    return sorted(dedup, key=str.lower)

def scan_images(root: Optional[str]) -> Dict[str, List[str]]:
    mp: Dict[str, List[str]] = {}
    if not root or not os.path.isdir(root): return mp
    for dirpath, _, files in os.walk(root):
        for f in files:
            if not f.lower().endswith((".png",".jpg",".jpeg",".webp",".gif")): continue
            base = os.path.splitext(f)[0]
            base = re.sub(r"\s+(\d+)$", "", base)  # drop trailing numbers for key
            key  = _norm(base)
            mp.setdefault(key, []).append(os.path.join(dirpath, f))
    for k in mp: mp[k].sort(key=lambda p: p.lower())
    return mp

def load_aliases() -> Dict[str, str]:
    al = {}
    j = _load_json(ALIASES_JSON)
    if j:
        for k, v in j.items():
            if k and v: al[_norm(k)] = v.strip()
    for k,v in {"rb":"Rosebeam","bb":"Blueberries","gc":"Galactic Shroom"}.items():
        al.setdefault(_norm(k), v)
    return al

IMAGES: Dict[str, List[str]] = scan_images(ASSETS_DIR)
ALIASES: Dict[str, str] = load_aliases()
UNITS: List[str] = load_units()

def resolve_alias(name: str) -> str:
    return ALIASES.get(_norm(name), name)

def find_images_for(name: str) -> List[str]:
    key = _norm(name)
    if key in IMAGES: return IMAGES[key][:]
    for k in IMAGES:
        if key.startswith(k) or k.startswith(key): return IMAGES[k][:]
    for k in IMAGES:
        if key in k or k in key: return IMAGES[k][:]
    return []

def pick_main_and_stats(imgs: List[str]) -> Tuple[Optional[str], Optional[str]]:
    if not imgs: return (None, None)
    def score(p):
        fn = os.path.basename(p).lower(); s=0
        if re.search(r"(^|[ _\-])1(\D|$)", fn): s += 3
        if not re.search(r"(^|[ _\-])[12](\D|$)", fn): s += 2
        if "icon" in fn or "card" in fn: s += 1
        return s
    main = max(imgs, key=score)
    candidates = sorted(imgs, key=lambda p: (
        "stats" not in os.path.basename(p).lower(),
        not re.search(r"(^|[ _\-])2(\D|$)", os.path.basename(p).lower()),
        os.path.basename(p).lower()
    ))
    stats=None
    for p in candidates:
        if p != main: stats=p; break
    if stats == main: stats=None
    return (main, stats)

def filter_pool(src: List[str], include: Optional[str], exclude: Optional[str]) -> List[str]:
    inc = [t.strip().lower() for t in (include or "").replace(",", " ").split() if t.strip()]
    exc = [t.strip().lower() for t in (exclude or "").replace(",", " ").split() if t.strip()]
    out = []
    for n in src:
        low = n.lower()
        keep=True
        if inc and not any(tok in low for tok in inc): keep=False
        if exc and any(tok in low for tok in exc): keep=False
        if keep: out.append(n)
    return out

def _get_fonts():
    try:
        return (
            ImageFont.truetype("arial.ttf", 14),
            ImageFont.truetype("arialbd.ttf", 18),
            ImageFont.truetype("arialbd.ttf", 16)
        )
    except Exception:
        f = ImageFont.load_default()
        return (f, f, f)

def _text_wh(draw, font, text: str):
    try:
        bbox = draw.textbbox((0,0), text, font=font)
        return bbox[2]-bbox[0], bbox[3]-bbox[1]
    except Exception:
        try:
            bbox = font.getbbox(text)
            return bbox[2]-bbox[0], bbox[3]-bbox[1]
        except Exception:
            try: return (font.getlength(text), font.size)
            except Exception: return (len(text)*8, 16)

def _save_path(prefix: str, ext: str) -> str:
    fn = f"{prefix}_{int(time.time()*1000)}.{ext}"
    path = os.path.join(OUTPUT_DIR, fn)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return path

# ---------------------- Ingestion helpers (uploads in Discord) -----------------
def _sanitize_filename(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-\. ]+", "_", name)
    safe = safe.strip().lstrip(".")
    return safe or "file"

async def _save_attachment(att: discord.Attachment, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    data = await att.read()
    fn = _sanitize_filename(att.filename)
    path = os.path.join(dest_dir, fn)
    with open(path, "wb") as f:
        f.write(data)
    return path

def _process_saved_file(path: str) -> str:
    base = os.path.basename(path).lower()
    ext = os.path.splitext(base)[1]
    msg = None
    try:
        if ext in (".png",".jpg",".jpeg",".webp",".gif"):
            msg = f"Image saved: `{os.path.basename(path)}`"
        elif ext == ".txt":
            if "units" in base:
                os.replace(path, UNITS_TXT)
                msg = "units.txt updated"
            else:
                msg = f"TXT saved: `{os.path.basename(path)}`"
        elif ext == ".json":
            if "aliases" in base:
                os.replace(path, ALIASES_JSON)
                msg = "aliases.json updated"
            else:
                msg = f"JSON saved: `{os.path.basename(path)}`"
        elif ext == ".zip":
            import zipfile
            with zipfile.ZipFile(path, 'r') as zf:
                zf.extractall(ASSETS_DIR)
            msg = "ZIP extracted into units_assets/"
        else:
            msg = f"File saved (unknown type): `{os.path.basename(path)}`"
    except Exception as e:
        msg = f"Error processing `{os.path.basename(path)}`: {e}"
    return msg

async def _ingest_attachments(attachments: list[discord.Attachment]) -> list[str]:
    results = []
    for att in attachments or []:
        ext = os.path.splitext(att.filename.lower())[1]
        dst = ASSETS_DIR if ext in (".png",".jpg",".jpeg",".webp",".gif",".zip") else OUTPUT_DIR
        path = await _save_attachment(att, dst)
        results.append(_process_saved_file(path))
    global IMAGES, ALIASES, UNITS
    IMAGES = scan_images(ASSETS_DIR)
    ALIASES = load_aliases()
    UNITS = load_units()
    return results

# --------------------------- Builders (images/GIFs) ---------------------------
def build_strip(names: List[str]) -> Optional[str]:
    font_num, font_cost, font_name = _get_fonts()
    TW=CONFIG["STRIP_TILE_W"]; TH=CONFIG["STRIP_TILE_H"]; PAD=CONFIG["STRIP_PAD"]
    card=_parse_color(CONFIG["STRIP_CARD"]); bg=_parse_color(CONFIG["STRIP_BG"])
    W = PAD + len(names)*(TW+PAD); H = PAD*2 + TH
    canvas = Image.new("RGBA", (W,H), bg); draw = ImageDraw.Draw(canvas)
    def rrect(x0,y0,x1,y1,r=10,fill=(0,0,0,255)):
        try: draw.rounded_rectangle([x0,y0,x1,y1], radius=r, fill=fill)
        except Exception: draw.rectangle([x0,y0,x1,y1], fill=fill)
    for i,nm in enumerate(names):
        x = PAD + i*(TW+PAD); y = PAD
        rrect(x,y,x+TW,y+TH,10,card)
        imgs = find_images_for(nm)
        main,_ = pick_main_and_stats(imgs)
        if main and os.path.isfile(main):
            try:
                im = Image.open(main).convert("RGBA")
                im.thumbnail((TW-10, TH-28))
                ix = x + (TW-im.width)//2; iy = y + 4
                canvas.paste(im, (ix,iy), im)
            except Exception: pass
        cx,cy = x+12, y+12
        draw.ellipse((cx-11,cy-11,cx+11,cy+11), fill=(30,30,30,220))
        txt = str(i+1); w,h = _text_wh(draw, font_num, txt)
        draw.text((cx-w/2,cy-h/2-1), txt, fill=(255,255,255,255), font=font_num)
    out = _save_path("team_strip", "png"); canvas.save(out); return out

def build_unit_composite(name: str) -> Optional[str]:
    imgs = find_images_for(name)
    if not imgs: return None
    main, stats = pick_main_and_stats(imgs)
    try:
        im1 = Image.open(main).convert("RGBA") if main else None
        im2 = Image.open(stats).convert("RGBA") if stats else None
    except Exception:
        return None
    if im1 and im2:
        scale = 450
        def scale_to_h(im):
            r = scale / im.height
            return im.resize((int(im.width*r), scale))
        im1 = scale_to_h(im1); im2 = scale_to_h(im2)
        out = Image.new("RGBA", (im1.width+im2.width, scale), (20,20,20,255))
        out.paste(im1, (0,0), im1); out.paste(im2, (im1.width,0), im2)
    else:
        im = im1 or im2
        if im is None: return None
        scale = 450; r = scale / im.height
        out = im.resize((int(im.width*r), scale))
    draw = ImageDraw.Draw(out)
    try: font = ImageFont.truetype("arial.ttf", 24)
    except Exception: font = ImageFont.load_default()
    title = " ".join(w.capitalize() for w in _norm(name).split())
    tw, th = _text_wh(draw, font, title)
    bar_h = th + 10
    draw.rectangle([0,0,out.width,bar_h], fill=(0,0,0,160))
    draw.text((10,(bar_h-th)//2), title, fill=(255,255,255,255), font=font)
    path = _save_path("unit", "png"); out.save(path); return path

def _frame_strip(seq: List[str], offset_px: int) -> Image.Image:
    T = {
        "tile_w": CONFIG["STRIP_TILE_W"],
        "tile_h": CONFIG["STRIP_TILE_H"],
        "pad": CONFIG["STRIP_PAD"],
        "bg": _parse_color(CONFIG["STRIP_BG"]),
        "card": _parse_color(CONFIG["STRIP_CARD"]),
        "visible": CONFIG["CASE_VISIBLE"],
    }
    V = T["visible"]
    TW, TH, PAD = T["tile_w"], T["tile_h"], T["pad"]
    vw = PAD + V*(TW+PAD)
    vh = PAD*2 + TH + 22
    canvas = Image.new("RGBA", (vw, vh), T["bg"])
    draw = ImageDraw.Draw(canvas)
    try: font = ImageFont.truetype("arial.ttf", 14)
    except Exception: font = ImageFont.load_default()
    def rrect(x0,y0,x1,y1,rad=10,fill=(0,0,0,180)):
        try: draw.rounded_rectangle([x0,y0,x1,y1], radius=rad, fill=fill)
        except Exception: draw.rectangle([x0,y0,x1,y1], fill=fill)
    x = PAD - offset_px
    for nm in seq:
        if x > vw: break
        rrect(x, PAD, x+TW, PAD+TH, 10, T["card"])
        imgs = find_images_for(nm); main,_ = pick_main_and_stats(imgs)
        if main and os.path.isfile(main):
            try:
                im = Image.open(main).convert("RGBA"); im.thumbnail((TW-10, TH-28))
                ix = x + (TW-im.width)//2; iy = PAD + 4
                canvas.paste(im, (ix,iy), im)
            except Exception: pass
        w,h = _text_wh(draw, font, nm)
        draw.text((x+(TW-w)//2, PAD+TH-2), nm[:22], fill=(240,240,240,255), font=font)
        x += TW + PAD
    cx = PAD + (V//2)*(TW+PAD)
    rrect(cx-2, PAD-2, cx+TW+2, PAD+TH+2, 8, (250,220,80,120))
    return canvas

def _ease_out_cubic(t: float) -> float: return 1 - (1 - t)**3

def build_case_gif_stopping(pool: List[str]) -> Tuple[str, str]:
    V = CONFIG["CASE_VISIBLE"]; TW=CONFIG["STRIP_TILE_W"]; PAD=CONFIG["STRIP_PAD"]
    winner = random.choice(pool)
    pre = random.choices(pool, k=V+5)
    seq = pre + [winner] + random.choices(pool, k=2)
    center_x = PAD + (V//2)*(TW+PAD)
    winner_index = len(pre)
    final_offset = PAD + winner_index*(TW+PAD) - center_x
    frames = max(14, int(CONFIG["CASE_FRAMES"]))
    offsets = []
    for i in range(frames-1):
        t = i/(frames-1); offsets.append(int(final_offset * _ease_out_cubic(t)))
        if i and offsets[i] < offsets[i-1]: offsets[i] = offsets[i-1]
    offsets.append(final_offset)
    images=[]; durations=[]
    for i, off in enumerate(offsets):
        frame = _frame_strip(seq, off).convert("P", palette=Image.ADAPTIVE)
        images.append(frame)
        durations.append(CONFIG["CASE_FINAL_HOLD_MS"] if i==len(offsets)-1 else CONFIG["CASE_DURATION_MS"])
    out = _save_path("wheel_case", "gif")
    images[0].save(out, save_all=True, append_images=images[1:], duration=durations, loop=int(CONFIG.get("GIF_LOOP",1)), disposal=2)
    return out, winner

# ----------------------------- Discord setup ---------------------------------
want_members_intent = bool(CONFIG.get("AUTO_ROLE_ID"))
if os.getenv("FORCE_MEMBERS_INTENT") == "1": want_members_intent = True
intents = discord.Intents.default()
intents.members = bool(want_members_intent)
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

@bot.event
async def on_ready():
    print(f"[ready] Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        guild_ids = os.getenv("GUILD_IDS", "").strip()
        if guild_ids:
            ids = [int(x) for x in guild_ids.split(",") if x.strip().isdigit()]
            for gid in ids:
                await tree.sync(guild=discord.Object(id=gid))
                print(f"[sync] commands synced to guild {gid}")
        await tree.sync()
        print("[sync] global commands synced")
    except Exception as e:
        print("[sync] failed:", e)
    total_imgs=sum(len(v) for v in IMAGES.values())
    print(f"[assets] folder={ASSETS_DIR} groups={len(IMAGES)} files={total_imgs}")
    print(f"[output] {OUTPUT_DIR}")

@bot.event
async def on_message(message: discord.Message):
    if not message.guild or message.author.bot:
        return
    ch_id = CONFIG.get("UPDATE_CHANNEL_ID")
    if not ch_id or int(ch_id) != message.channel.id:
        return
    if not (message.author.guild_permissions.manage_guild or (OWNER_ID and message.author.id == OWNER_ID)):
        return
    if not message.attachments:
        return
    try:
        results = await _ingest_attachments(message.attachments)
        summary = "\n".join(f"• {r}" for r in results if r)
        await message.reply(f"**Ingest complete.**\n{summary or 'No files processed.'}")
    except Exception as e:
        await message.reply(f"Ingest failed: `{e}`")

@bot.event
async def on_member_join(member: discord.Member):
    role_id = CONFIG.get("AUTO_ROLE_ID")
    if not role_id: return
    try:
        role = member.guild.get_role(int(role_id))
        if role: await member.add_roles(role, reason="Auto role on join")
    except Exception as e:
        print("[autorole] failed:", e)

# ----------------------------- Values (links + live) --------------------------
def _try_fetch_values(url: str = VALUES_URL):
    try:
        import requests
        from bs4 import BeautifulSoup
    except Exception as e:
        return None, f"Missing deps: {e}. Install requests and beautifulsoup4."
    try:
        headers = {"User-Agent": "Mozilla/5.0 (ToukaBot)"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        soup = BeautifulSoup(r.text, "html.parser")
        rows = []
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                cells = [c.get_text(strip=True) for c in tr.find_all(["td","th"])]
                if len(cells) >= 2 and cells[0] and cells[1]:
                    if cells[0].lower() in ("unit","name") and cells[1].lower().startswith(("value","worth")):
                        continue
                    rows.append({"name": cells[0], "value": cells[1]})
        if not rows:
            for li in soup.find_all(["li","p","div"]):
                txt = li.get_text(" ", strip=True)
                if " - " in txt or " – " in txt:
                    parts = [x.strip() for x in re.split(r"\s+[–-]\s+", txt, maxsplit=1)]
                    if len(parts) == 2 and len(parts[0]) <= 60 and len(parts[1]) <= 60:
                        rows.append({"name": parts[0], "value": parts[1]})
        seen = set(); out = []
        for r0 in rows:
            key = (r0["name"].lower(), r0["value"].lower())
            if key in seen: continue
            seen.add(key); out.append(r0)
        if not out:
            return None, "Could not parse any values from the page."
        return out, None
    except Exception as e:
        return None, f"Error: {e}"

class ValuesPagerView(discord.ui.View):
    def __init__(self, data, page_size=10):
        super().__init__(timeout=120)
        self.data = data or []
        self.page_size = max(5, min(25, int(page_size or 10)))
        self.page = 1
        self.pages = max(1, (len(self.data) + self.page_size - 1)//self.page_size)
        self.add_item(discord.ui.Button(label="Values (Main Page)", url=VALUES_URL))
        self.add_item(discord.ui.Button(label="Calculator", url=CALC_URL))

    def build_embed(self):
        start = (self.page-1)*self.page_size
        chunk = self.data[start:start+self.page_size]
        desc = "\n".join(f"**{i+start+1}. {row['name']}** — `{row['value']}`" for i, row in enumerate(chunk)) or "—"
        e = discord.Embed(
            title=f"Garden TD Values (page {self.page}/{self.pages})",
            description=desc,
            color=discord.Color.green()
        )
        e.set_footer(text="Parsed from the website — buttons link to official pages")
        return e

    async def update(self, interaction: discord.Interaction):
        for b in self.children:
            if isinstance(b, discord.ui.Button) and b.style != discord.ButtonStyle.link:
                if b.custom_id in ("prev","first"):
                    b.disabled = (self.page <= 1) or (self.pages <= 1)
                elif b.custom_id in ("next","last"):
                    b.disabled = (self.page >= self.pages) or (self.pages <= 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="⏮ First", style=discord.ButtonStyle.secondary, custom_id="first")
    async def first(self, interaction: discord.Interaction, _):
        if self.page != 1:
            self.page = 1
        await self.update(interaction)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.primary, custom_id="prev")
    async def prev(self, interaction: discord.Interaction, _):
        if self.page > 1:
            self.page -= 1
        await self.update(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, custom_id="next")
    async def next(self, interaction: discord.Interaction, _):
        if self.page < self.pages:
            self.page += 1
        await self.update(interaction)

    @discord.ui.button(label="Last ⏭", style=discord.ButtonStyle.secondary, custom_id="last")
    async def last(self, interaction: discord.Interaction, _):
        if self.page != self.pages:
            self.page = self.pages
        await self.update(interaction)

# ---------------------------- Units pager (buttons) ----------------------------
class UnitsPagerView(discord.ui.View):
    def __init__(self, names, page_size=20):
        super().__init__(timeout=120)
        self.names = names or []
        self.page_size = max(5, min(50, int(page_size or 20)))
        self.page = 1
        self.pages = max(1, (len(self.names) + self.page_size - 1)//self.page_size)

    def build_embed(self):
        start = (self.page-1)*self.page_size
        chunk = self.names[start:start+self.page_size]
        desc = "\n".join(f"{start+i+1}. {nm}" for i, nm in enumerate(chunk)) or "—"
        e = discord.Embed(
            title=f"Units (page {self.page}/{self.pages})",
            description=desc,
            color=discord.Color.blurple()
        )
        e.set_footer(text=f"{len(self.names)} total units — tip: /unit <name> for details")
        return e

    async def update(self, interaction: discord.Interaction):
        for b in self.children:
            if isinstance(b, discord.ui.Button):
                if b.custom_id in ("prev","first"):
                    b.disabled = (self.page <= 1) or (self.pages <= 1)
                elif b.custom_id in ("next","last"):
                    b.disabled = (self.page >= self.pages) or (self.pages <= 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="⏮ First", style=discord.ButtonStyle.secondary, custom_id="first")
    async def first(self, interaction: discord.Interaction, _):
        if self.page != 1:
            self.page = 1
        await self.update(interaction)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.primary, custom_id="prev")
    async def prev(self, interaction: discord.Interaction, _):
        if self.page > 1:
            self.page -= 1
        await self.update(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary, custom_id="next")
    async def next(self, interaction: discord.Interaction, _):
        if self.page < self.pages:
            self.page += 1
        await self.update(interaction)

    @discord.ui.button(label="Last ⏭", style=discord.ButtonStyle.secondary, custom_id="last")
    async def last(self, interaction: discord.Interaction, _):
        if self.page != self.pages:
            self.page = self.pages
        await self.update(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="close_units")
    async def close(self, interaction: discord.Interaction, _):
        for c in self.children: c.disabled = True
        await interaction.response.edit_message(view=self)

# ------------------------------- Commands ------------------------------------
def _unit_pool_from_images() -> List[str]:
    pool = []
    for k in IMAGES.keys():
        pretty = " ".join(w.capitalize() for w in k.split())
        pool.append(pretty)
    for u in UNITS:
        if u not in pool: pool.append(u)
    return sorted(pool)

async def unit_detail(interaction: discord.Interaction, name: str):
    name = resolve_alias(name)
    path = build_unit_composite(name)
    e = discord.Embed(title=name, color=discord.Color.teal())
    if path and os.path.isfile(path):
        fn = os.path.basename(path); file = discord.File(path, filename=fn)
        e.set_image(url=f"attachment://{fn}")
        await interaction.response.send_message(embed=e, file=file)
    else:
        await interaction.response.send_message(embed=e)

@tree.command(name="unit", description="Show a unit (image + stats if available)")
@app_commands.describe(name="Unit name (aliases supported)")
async def unit_cmd(interaction: discord.Interaction, name: str):
    await unit_detail(interaction, name)

@tree.command(name="units", description="Browse units or show a specific unit (with pager)")
@app_commands.describe(name="Optional: show details for this unit", per_page="Items per page (default 20)")
async def units_cmd(interaction: discord.Interaction, name: Optional[str]=None, per_page: Optional[int]=20):
    if name:
        await unit_detail(interaction, name); return
    names = _unit_pool_from_images()
    view = UnitsPagerView(names, page_size=per_page or 20)
    await interaction.response.send_message(embed=view.build_embed(), view=view)

@tree.command(name="values", description="Open the official values links")
async def values_cmd(interaction: discord.Interaction):
    v = discord.ui.View()
    v.add_item(discord.ui.Button(label="Values (Main Page)", url=VALUES_URL))
    v.add_item(discord.ui.Button(label="Units/Gamepasses", url="https://sites.google.com/view/garden-td-values/unitsgamepasses?authuser=0"))
    v.add_item(discord.ui.Button(label="Value Calculator", url=CALC_URL))
    e = discord.Embed(title="Garden TD Values", description="Tap a button to open the official site.", color=discord.Color.green())
    await interaction.response.send_message(embed=e, view=v)

@tree.command(name="valueslive", description="(Experimental) Parse values from the site with pagination")
@app_commands.describe(page_size="Items per page (default 10)")
async def valueslive(interaction: discord.Interaction, page_size: Optional[int]=10):
    await interaction.response.defer(thinking=True, ephemeral=False)
    data, err = _try_fetch_values(VALUES_URL)
    if not data:
        msg = f"Could not load values from the website.\n> {err or 'Unknown error'}\n\nUse **/values** to open the official page."
        await interaction.followup.send(msg); return
    view = ValuesPagerView(data, page_size=page_size or 10)
    await interaction.followup.send(embed=view.build_embed(), view=view)

@tree.command(name="assetsinfo", description="Show image folder & counts")
async def assetsinfo(interaction: discord.Interaction):
    total_imgs=sum(len(v) for v in IMAGES.values())
    await interaction.response.send_message(f"Assets folder: `{ASSETS_DIR}`\nImage groups: {len(IMAGES)}\nFiles: {total_imgs}", ephemeral=True)

# ---- Wheel ----
class WheelView(discord.ui.View):
    def __init__(self, pool: List[str]):
        super().__init__(timeout=90); self.pool=pool

    async def case_gif(self, msg: discord.Message):
        e = discord.Embed(title="🎁 Opening case...", color=discord.Color.gold()); await msg.edit(embed=e, view=self)
        gif_path, winner = build_case_gif_stopping(self.pool)
        if not gif_path or not os.path.isfile(gif_path):
            await msg.edit(content="Could not build GIF (is Pillow installed?)", view=self); return
        fn = os.path.basename(gif_path)
        gif_file = discord.File(gif_path, filename=fn)
        e.set_image(url=f"attachment://{fn}")
        await msg.edit(embed=e, attachments=[gif_file], view=self)
        fe = discord.Embed(title="🎉 Winner", description=f"**{winner}**", color=discord.Color.green())
        imgs = find_images_for(winner); main,_ = pick_main_and_stats(imgs)
        if main and os.path.isfile(main):
            await msg.channel.send(embed=fe, file=discord.File(main))
        else:
            await msg.channel.send(embed=fe)

    async def spin(self, msg: discord.Message):
        await self.case_gif(msg)

    @discord.ui.button(label="Respin", style=discord.ButtonStyle.primary)
    async def respin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            msg = await interaction.original_response()
        except Exception:
            msg = await interaction.followup.send("Spinning…")
        await self.spin(msg)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children: c.disabled = True
        await interaction.response.edit_message(view=self)

@tree.command(name="wheel", description="Open a case (animated GIF that stops on winner)")
@app_commands.describe(include="Filter include", exclude="Filter exclude")
async def wheel(interaction: discord.Interaction, include: Optional[str]=None, exclude: Optional[str]=None):
    pool = filter_pool(_unit_pool_from_images(), include, exclude)
    if not pool: await interaction.response.send_message("No units match your filters.", ephemeral=True); return
    await interaction.response.defer(thinking=True)
    holder = await interaction.followup.send(embed=discord.Embed(title="Spinning...", color=discord.Color.gold()))
    await WheelView(pool).spin(holder)

# ---- Team ----
class TeamView(discord.ui.View):
    def __init__(self, pool: List[str], size: int, allow_dup: bool):
        super().__init__(timeout=90); self.pool=pool; self.size=size; self.allow_dup=allow_dup

    async def spin(self, msg: discord.Message):
        e = discord.Embed(title="🎲 Building Team...", color=discord.Color.gold()); await msg.edit(embed=e, view=self)
        picks: List[str] = []
        for slot in range(1, self.size+1):
            for i in range(CONFIG["SPIN_HOPS_SLOT"]):
                cand_pool = self.pool if self.allow_dup else [u for u in self.pool if u not in picks] or self.pool
                cand = random.choice(cand_pool)
                body = ("**Locked:**\n" + "\n".join(f"• {p}" for p in picks) + "\n\n") if picks else ""
                e.description = body + f"**Slot {slot}:** >>> {cand}"
                await msg.edit(embed=e, view=self); await asyncio.sleep(0.08+0.02*i)
            if self.allow_dup: choice = random.choice(self.pool)
            else:
                rem = [u for u in self.pool if u not in picks]
                choice = random.choice(rem) if rem else random.choice(self.pool)
            picks.append(choice)
        final = discord.Embed(title=f"✅ Final Team ({len(picks)})", description="\n".join(f"**{i+1}.** {n}" for i,n in enumerate(picks)), color=discord.Color.green())
        await msg.edit(embed=final, view=self)
        if CONFIG["SHOW_COLLAGE"]:
            coll = build_strip(picks)
            if coll and os.path.isfile(coll):
                fn=os.path.basename(coll); file=discord.File(coll, filename=fn); ce=discord.Embed(title="Team Collage", color=discord.Color.dark_teal()); ce.set_image(url=f"attachment://{fn}")
                await msg.channel.send(embed=ce, file=file)

    @discord.ui.button(label="Respin Team", style=discord.ButtonStyle.primary)
    async def respin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            msg = await interaction.original_response()
        except Exception:
            msg = await interaction.followup.send("Building Team…")
        await self.spin(msg)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children: c.disabled = True
        await interaction.response.edit_message(view=self)

@tree.command(name="team", description="Roulette team builder (with filters)")
@app_commands.describe(size="Team size (1-7, default 7)", allow_duplicates="Allow duplicates", include="Filter include", exclude="Filter exclude")
async def team(interaction: discord.Interaction, size: Optional[int]=7, allow_duplicates: Optional[bool]=False, include: Optional[str]=None, exclude: Optional[str]=None):
    pool = filter_pool(_unit_pool_from_images(), include, exclude)
    if not pool: await interaction.response.send_message("No units match your filters.", ephemeral=True); return
    size = max(1, min(7, int(size or 7)))
    if not allow_duplicates: size = min(size, len(pool))
    await interaction.response.defer(thinking=True)
    holder = await interaction.followup.send(embed=discord.Embed(title="🎲 Building Team...", color=discord.Color.gold()))
    await TeamView(pool, size, bool(allow_duplicates)).spin(holder)

# ---- Clean "GUI" menu ----
class MenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Open Case", style=discord.ButtonStyle.success, emoji="🎁")
    async def open_case(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        pool = _unit_pool_from_images()
        holder = await interaction.followup.send(embed=discord.Embed(title="Spinning...", color=discord.Color.gold()), ephemeral=True)
        await WheelView(pool).spin(holder)

    @discord.ui.button(label="Team (7)", style=discord.ButtonStyle.primary, emoji="🎲")
    async def team7(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        pool = _unit_pool_from_images()
        holder = await interaction.followup.send(embed=discord.Embed(title="🎲 Building Team...", color=discord.Color.gold()), ephemeral=True)
        await TeamView(pool, 7, False).spin(holder)

    @discord.ui.button(label="Values (Links)", style=discord.ButtonStyle.secondary, emoji="📊")
    async def values(self, interaction: discord.Interaction, button: discord.ui.Button):
        v = discord.ui.View()
        v.add_item(discord.ui.Button(label="Values (Main Page)", url=VALUES_URL))
        v.add_item(discord.ui.Button(label="Units/Gamepasses", url="https://sites.google.com/view/garden-td-values/unitsgamepasses?authuser=0"))
        v.add_item(discord.ui.Button(label="Value Calculator", url=CALC_URL))
        e = discord.Embed(title="Garden TD Values", description="Open the official lists:", color=discord.Color.green())
        await interaction.response.send_message(embed=e, view=v, ephemeral=True)
        return

    @discord.ui.button(label="Units List", style=discord.ButtonStyle.secondary, emoji="📜")
    async def units(self, interaction: discord.Interaction, button: discord.ui.Button):
        names = _unit_pool_from_images()
        view = UnitsPagerView(names, page_size=20)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)
        return

@tree.command(name="menu", description="Open the bot menu")
async def menu(interaction: discord.Interaction):
    e = discord.Embed(
        title="🌿 ToukaBot",
        description="Pick an action below. You can also use slash commands like /wheel, /team, /unit.",
        color=discord.Color.dark_green()
    )
    e.set_footer(text="Tip: use /autorole set to auto-assign a role when someone joins")
    await interaction.response.send_message(embed=e, view=MenuView(), ephemeral=True)

# ---- Reload & Config ----
@tree.command(name="reload", description="Reload units and images")
async def reload_all(interaction: discord.Interaction):
    global IMAGES, ALIASES, UNITS, OUTPUT_DIR, CONFIG
    IMAGES = scan_images(ASSETS_DIR)
    ALIASES = load_aliases()
    UNITS = load_units()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    await interaction.response.send_message(f"Reloaded. Units: {len(UNITS)} | Image groups: {len(IMAGES)} | Aliases: {len(ALIASES)} | OUTPUT_DIR: {OUTPUT_DIR}", ephemeral=True)

@tree.command(name="setoutputdir", description="Set the folder where GIFs/PNGs are saved")
@app_commands.describe(path="Folder path (created if missing)")
async def setoutputdir(interaction: discord.Interaction, path: str):
    global OUTPUT_DIR, CONFIG
    path = path.strip()
    if not path:
        await interaction.response.send_message("Path cannot be empty.", ephemeral=True); return
    try:
        os.makedirs(path, exist_ok=True)
        OUTPUT_DIR = path
        CONFIG["OUTPUT_DIR"] = path
        _save_json(CONFIG_JSON, CONFIG)
        await interaction.response.send_message(f"OUTPUT_DIR set to `{path}`.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed to set OUTPUT_DIR: `{e}`", ephemeral=True)

@tree.command(name="configshow", description="Show config")
async def configshow(interaction: discord.Interaction):
    txt = "\n".join(f"{k}: {v}" for k,v in CONFIG.items())
    await interaction.response.send_message(f"```\n{txt}\n```", ephemeral=True)

# ---- Autorole ----
class AutoRoleGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="autorole", description="Configure auto role on member join")

    @app_commands.command(name="show", description="Show current auto-role")
    async def show(self, interaction: discord.Interaction):
        rid = CONFIG.get("AUTO_ROLE_ID")
        if rid:
            r = interaction.guild.get_role(int(rid)) if interaction.guild else None
            await interaction.response.send_message(f"Auto-role: {r.mention if r else f'ID {rid}'}", ephemeral=True)
        else:
            await interaction.response.send_message("Auto-role is **not set**.", ephemeral=True)

    @app_commands.command(name="set", description="Set auto-role")
    @app_commands.describe(role="Role to assign automatically on join")
    async def set(self, interaction: discord.Interaction, role: discord.Role):
        CONFIG["AUTO_ROLE_ID"] = int(role.id)
        _save_json(CONFIG_JSON, CONFIG)
        await interaction.response.send_message(f"Auto-role set to {role.mention}.", ephemeral=True)

    @app_commands.command(name="clear", description="Clear auto-role")
    async def clear(self, interaction: discord.Interaction):
        CONFIG["AUTO_ROLE_ID"] = None
        _save_json(CONFIG_JSON, CONFIG)
        await interaction.response.send_message("Auto-role cleared.", ephemeral=True)

tree.add_command(AutoRoleGroup())

# ---- Upload-to-update commands ----
@tree.command(name="updateset", description="Set the channel where you will upload images/txt/json to update the bot")
@app_commands.describe(channel="Channel to watch for uploads")
async def updateset(interaction: discord.Interaction, channel: discord.TextChannel):
    if not (interaction.user.guild_permissions.manage_guild or (OWNER_ID and interaction.user.id == OWNER_ID)):
        await interaction.response.send_message("You need Manage Server to do that.", ephemeral=True); return
    CONFIG["UPDATE_CHANNEL_ID"] = int(channel.id)
    _save_json(CONFIG_JSON, CONFIG)
    await interaction.response.send_message(f"Update channel set to {channel.mention}. Upload images/zip for assets, units.txt, or aliases.json here.", ephemeral=True)

@tree.command(name="updateinfo", description="Show update upload settings")
async def updateinfo(interaction: discord.Interaction):
    ch_id = CONFIG.get("UPDATE_CHANNEL_ID")
    ch = interaction.guild.get_channel(int(ch_id)) if ch_id and interaction.guild else None
    txt = [
        f"Update channel: {ch.mention if ch else f'ID {ch_id} (not in this guild?)'}",
        "Accepted files: images (.png .jpg .jpeg .webp .gif), units.txt, aliases.json, .zip (extracted into units_assets/)",
        "Permissions: Only users with **Manage Server** (or OWNER_ID) are processed."
    ]
    await interaction.response.send_message("\n".join(txt), ephemeral=True)

@tree.command(name="ingest", description="Upload files to update bot resources (attach up to 5 files)")
@app_commands.describe(file1="Attachment 1", file2="Attachment 2", file3="Attachment 3", file4="Attachment 4", file5="Attachment 5")
async def ingest(interaction: discord.Interaction,
                 file1: Optional[discord.Attachment]=None,
                 file2: Optional[discord.Attachment]=None,
                 file3: Optional[discord.Attachment]=None,
                 file4: Optional[discord.Attachment]=None,
                 file5: Optional[discord.Attachment]=None):
    if not (interaction.user.guild_permissions.manage_guild or (OWNER_ID and interaction.user.id == OWNER_ID)):
        await interaction.response.send_message("You need Manage Server to do that.", ephemeral=True); return
    files = [f for f in [file1,file2,file3,file4,file5] if f]
    if not files:
        await interaction.response.send_message("Attach 1–5 files with the command.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    results = await _ingest_attachments(files)
    summary = "\n".join(f"• {r}" for r in results if r) or "No files processed."
    await interaction.followup.send(f"**Ingest complete.**\n{summary}", ephemeral=True)

# ------------------------------ Token loader ---------------------------------
def load_token() -> str:
    tok = os.getenv("DISCORD_TOKEN")
    if tok: return tok.strip()
    if os.path.exists("token.txt"):
        with open("token.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    raise RuntimeError("No Discord token found! Set DISCORD_TOKEN or create token.txt")

def main():
    print("[boot] starting… OUTPUT_DIR:", OUTPUT_DIR)
    tok = load_token()
    bot.run(tok)

if __name__ == "__main__":
    main()
