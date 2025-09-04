# gtd_bot_pro.py
# Garden TD helper bot
# - /wheel (case GIF stops on winner, saves to OUTPUT_DIR)
# - /team roulette with collage (saves to OUTPUT_DIR)
# - /unit combines "1" + "2" images into one composite (saves to OUTPUT_DIR)
# - /menu shows a clean button-based UI (GUI-ish)
# - Auto-role on member join (configure via /autorole set <role>)
# - All generated media saved under configurable OUTPUT_DIR (default: media/)

import os, json, re, asyncio, random, time
from typing import List, Optional, Dict, Tuple

import discord
from discord import app_commands

# ========= Config & Paths =========
UNITS_TXT    = os.getenv("UNITS_TXT", "units.txt")
UNITS_JSON   = os.getenv("UNITS_JSON", "units_db.json")
ASSETS_DIR   = os.getenv("UNITS_ASSETS_DIR", "units_assets")
ALIASES_JSON = os.getenv("ALIASES_JSON", "aliases.json")
CONFIG_JSON  = os.getenv("CONFIG_JSON", "config.json")

VALUES_URL   = os.getenv("VALUES_URL", "https://sites.google.com/view/garden-td-values/unitsgamepasses?authuser=0")
CALC_URL     = os.getenv("CALC_URL",   "https://sites.google.com/view/garden-td-values/value-calculator?authuser=0")

DEFAULT_CONFIG = {
    "SHOW_COLLAGE": True,
    "STRIP_TILE_W": 128,
    "STRIP_TILE_H": 96,
    "STRIP_PAD": 6,
    "STRIP_BG": "#c49a6c",
    "STRIP_CARD": "#4a3a2a",
    "SPIN_HOPS_WHEEL": 14,
    "SPIN_HOPS_SLOT": 9,
    # Case GIF animation
    "CASE_VISIBLE": 7,          # tiles visible
    "CASE_FRAMES": 18,          # frames
    "CASE_DURATION_MS": 90,     # ms per frame
    "CASE_FINAL_HOLD_MS": 1800, # ms final frame
    "GIF_LOOP": 1,              # 1 = play once
    "OUTPUT_DIR": "media",
    # Auto role
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

# ========= Data loading =========
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
    elif os.path.isfile(UNITS_JSON):
        try:
            data = json.load(open(UNITS_JSON, "r", encoding="utf-8"))
            for k, obj in (data.get("units") or {}).items():
                nm = (obj.get("name") or k or "").strip()
                if nm: units.append(nm)
        except Exception:
            pass
    if not units:
        units = ["Tomato","Cactus","Pumpkin","Rose","Umbra","Onion","Bee"]
    # de-dupe, sort
    return sorted({u:None for u in units}.keys(), key=str.lower)

def _autodetect_assets_dir(cwd="."):
    best = None
    for root, _, files in os.walk(cwd):
        depth = os.path.abspath(root).count(os.sep) - os.path.abspath(cwd).count(os.sep)
        if depth > 2: continue
        imgs = [f for f in files if f.lower().endswith((".png",".jpg",".jpeg",".webp"))]
        if len(imgs) >= 20:
            score = sum(kw in root.lower() for kw in ("units","garden","tower","defense"))
            cand = (score, len(imgs), root)
            if not best or cand > best: best = cand
    return best[2] if best else None

def scan_images(root: Optional[str]) -> Dict[str, List[str]]:
    mp: Dict[str, List[str]] = {}
    if not root or not os.path.isdir(root): return mp
    for dirpath, _, files in os.walk(root):
        for f in files:
            if not f.lower().endswith((".png",".jpg",".jpeg",".webp")): continue
            base = os.path.splitext(f)[0]
            base = re.sub(r"\s+(\d+)$", "", base)  # drop trailing numbers for key
            key  = _norm(base)
            mp.setdefault(key, []).append(os.path.join(dirpath, f))
    for k in mp: mp[k].sort(key=lambda p: p.lower())
    return mp

def load_units_db() -> Dict[str, dict]:
    db: Dict[str, dict] = {}
    try:
        if os.path.isfile(UNITS_JSON):
            data = json.load(open(UNITS_JSON, "r", encoding="utf-8"))
            for k, obj in (data.get("units") or {}).items():
                nm = (obj.get("name") or k or "").strip()
                if nm: db[_norm(nm)] = obj
    except Exception:
        pass
    return db

def load_aliases() -> Dict[str, str]:
    al = {}
    j = _load_json(ALIASES_JSON)
    if j:
        for k, v in j.items():
            if k and v: al[_norm(k)] = v.strip()
    for k,v in {"rb":"Rosebeam","bb":"Blueberries","gc":"Galactic Shroom"}.items():
        al.setdefault(_norm(k), v)
    return al

UNITS: List[str] = load_units()
USED_ASSETS_DIR = ASSETS_DIR if os.path.isdir(ASSETS_DIR) else (_autodetect_assets_dir(os.getcwd()) or ASSETS_DIR)
IMAGES: Dict[str, List[str]] = scan_images(USED_ASSETS_DIR)
UNITS_DB: Dict[str, dict] = load_units_db()
ALIASES: Dict[str, str] = load_aliases()

def resolve_alias(name: str) -> str: return ALIASES.get(_norm(name), name)

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

def unit_record(name: str) -> Optional[dict]:
    key = _norm(name)
    if key in UNITS_DB: return UNITS_DB[key]
    for k in UNITS_DB:
        if key.startswith(k) or k.startswith(key): return UNITS_DB[k]
    return None

def filter_pool(src: List[str], include: Optional[str], exclude: Optional[str]) -> List[str]:
    inc = [t.strip().lower() for t in (include or "").replace(",", " ").split() if t.strip()]
    exc = [t.strip().lower() for t in (exclude or "").replace(",", " ").split() if t.strip()]
    out = []
    for n in src:
        low = n.lower(); tags=[]
        rec = unit_record(n)
        if rec:
            tags = [str(t).lower() for t in (rec.get("tags") or [])]
            if rec.get("rarity"): tags.append(str(rec["rarity"]).lower())
        keep=True
        if inc and not any(tok in low or tok in tags for tok in inc): keep=False
        if exc and any(tok in low or tok in tags for tok in exc): keep=False
        if keep: out.append(n)
    return out

# ========= Pillow helpers =========
def _parse_color(s: str):
    s = str(s)
    if s.startswith("#") and len(s) == 7:
        return (int(s[1:3],16), int(s[3:5],16), int(s[5:7],16), 255)
    return (196,154,108,255)

def _get_fonts():
    try:
        from PIL import ImageFont
        try:
            return (
                ImageFont.truetype("arial.ttf", 14),
                ImageFont.truetype("arialbd.ttf", 18),
                ImageFont.truetype("arialbd.ttf", 16)
            )
        except Exception:
            f = ImageFont.load_default()
            return (f, f, f)
    except Exception:
        return (None, None, None)

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

def _cost_str(rec: Optional[dict])->Optional[str]:
    if not rec: return None
    c = rec.get("cost")
    if c is None: return None
    try:
        if isinstance(c, (int, float)): return f"${int(c):,}"
        if isinstance(c, str):
            m=re.search(r"\d[\d,]*", c); 
            return f"${int(m.group(0).replace(',','')):,}" if m else c
        if isinstance(c, dict):
            for k in ("base","initial","cost","price"):
                if k in c:
                    v=c[k]
                    if isinstance(v,(int,float)): return f"${int(v):,}"
                    if isinstance(v,str):
                        m=re.search(r"\d[\d,]*", v)
                        if m: return f"${int(m.group(0).replace(',','')):,}"
        if isinstance(c, list) and c:
            v=c[0]
            if isinstance(v,(int,float)): return f"${int(v):,}"
    except Exception: return None
    return None

# ========= Builders (save to OUTPUT_DIR) =========
def _save_path(prefix: str, ext: str) -> str:
    fn = f"{prefix}_{int(time.time()*1000)}.{ext}"
    return os.path.join(OUTPUT_DIR, fn)

def build_strip(names: List[str]) -> Optional[str]:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
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
        # number badge
        cx,cy = x+12, y+12
        draw.ellipse((cx-11,cy-11,cx+11,cy+11), fill=(30,30,30,220))
        txt = str(i+1); w,h = _text_wh(draw, font_num, txt)
        draw.text((cx-w/2,cy-h/2-1), txt, fill=(255,255,255,255), font=font_num)
        # price (if present)
        cost = _cost_str(unit_record(nm)) or ""
        if cost:
            pw,ph = TW-16, 22; px,py = x+(TW-pw)//2, y+TH-ph-6
            rrect(px,py,px+pw,py+ph,6,(42,135,14,255))
            w,h = _text_wh(draw, font_cost, cost)
            tx,ty = px+(pw-w)//2, py+(ph-h)//2-1
            for ox,oy in [(-1,0),(1,0),(0,-1),(0,1)]: draw.text((tx+ox,ty+oy), cost, fill=(0,0,0,200), font=font_cost)
            draw.text((tx,ty), cost, fill=(230,255,180,255), font=font_cost)
    out = _save_path("collage_strip", "png"); canvas.save(out); return out

def build_unit_composite(main_path: Optional[str], stats_path: Optional[str]) -> Optional[str]:
    if not (main_path or stats_path): return None
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    images = []
    for p in [main_path, stats_path]:
        if p and os.path.isfile(p):
            try:
                images.append(Image.open(p).convert("RGBA"))
            except Exception:
                images.append(None)
        else:
            images.append(None)
    top, bottom = images
    if bottom is None: return main_path
    if top is None: return stats_path
    maxw=768
    def scale(im):
        w,h=im.size
        if w>maxw:
            nh=int(h*(maxw/w)); im=im.resize((maxw,nh))
        return im
    top=scale(top); bottom=scale(bottom)
    W=max(top.width, bottom.width); H=top.height+bottom.height+8
    canvas=Image.new("RGBA",(W,H),(18,18,18,255)); draw=ImageDraw.Draw(canvas)
    canvas.paste(top,((W-top.width)//2,0),top)
    canvas.paste(bottom,((W-bottom.width)//2, top.height+8),bottom)
    draw.rectangle([0,0,W-1,H-1], outline=(90,90,90,255), width=2)
    out=_save_path("unit_combo", "png"); canvas.save(out); return out

def _build_case_frame_image(seq: List[str], offset_px: int):
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    TW=CONFIG["STRIP_TILE_W"]; TH=CONFIG["STRIP_TILE_H"]; PAD=CONFIG["STRIP_PAD"]
    V=CONFIG["CASE_VISIBLE"]
    card=_parse_color(CONFIG["STRIP_CARD"]); bg=_parse_color(CONFIG["STRIP_BG"])
    VW = PAD + V*(TW+PAD); VH = PAD*2 + TH + 20
    canvas = Image.new("RGBA", (VW,VH), bg); draw = ImageDraw.Draw(canvas)
    def rrect(x0,y0,x1,y1,r=10,fill=(0,0,0,255)):
        try: draw.rounded_rectangle([x0,y0,x1,y1], radius=r, fill=fill)
        except Exception: draw.rectangle([x0,y0,x1,y1], fill=fill)
    x0 = PAD - offset_px
    from PIL import ImageFont
    font_name = _get_fonts()[2]
    for nm in seq:
        x = x0; y = PAD
        if x > VW: break
        rrect(x,y,x+TW,y+TH,10,card)
        # picture
        imgs = find_images_for(nm)
        main,_ = pick_main_and_stats(imgs)
        if main and os.path.isfile(main):
            try:
                im = Image.open(main).convert("RGBA")
                im.thumbnail((TW-10, TH-28))
                ix = x + (TW-im.width)//2; iy = y + 4
                canvas.paste(im, (ix,iy), im)
            except Exception: pass
        # name
        if font_name:
            w,h = _text_wh(draw, font_name, nm)
            draw.text((x+(TW-w)//2, y+TH-2), nm[:20], fill=(240,240,240,255), font=font_name)
        x0 += TW + PAD
    # highlight center
    cx = PAD + (V//2)*(TW+PAD)
    rrect(cx-2, PAD-2, cx+TW+2, PAD+TH+2, 8, (250,220,80,120))
    return canvas

def build_case_gif_stopping(pool: List[str]) -> Tuple[str, str]:
    """Return (gif_path, winner) - non-looping GIF that ends on winner centered, with long final frame."""
    try:
        from PIL import Image
    except Exception:
        return ("", random.choice(pool))
    V = CONFIG["CASE_VISIBLE"]
    winner = random.choice(pool)
    pre = random.choices(pool, k=V+5)
    seq = pre + [winner] + random.choices(pool, k=1)
    TW=CONFIG["STRIP_TILE_W"]; PAD=CONFIG["STRIP_PAD"]
    center_x = PAD + (V//2)*(TW+PAD)
    winner_index = len(pre)  # index of winner in seq
    final_offset = PAD + winner_index*(TW+PAD) - center_x

    frames = max(8, int(CONFIG["CASE_FRAMES"]))
    # Ease-out offsets so the strip slows down naturally.
    # t in [0..1], offset = final_offset * (1 - (1 - t)^3)
    offsets = []
    for i in range(frames-1):
        t = i/(frames-1)
        eased = 1 - (1 - t)**3
        offsets.append(int(final_offset * eased))
    offsets.append(final_offset)  # exact stop on last frame

    imgs=[]; durations=[]
    for idx, off in enumerate(offsets):
        frame = _build_case_frame_image(seq, off)
        if frame is None: continue
        imgs.append(frame.convert("P", palette=Image.ADAPTIVE))
        if idx == len(offsets)-1:
            durations.append(int(CONFIG["CASE_FINAL_HOLD_MS"]))  # hold on final
        else:
            durations.append(int(CONFIG["CASE_DURATION_MS"]))

    if not imgs:
        return ("", winner)
    path = _save_path("case_spin_stop", "gif")
    imgs[0].save(
        path,
        save_all=True,
        append_images=imgs[1:],
        duration=durations,
        loop=int(CONFIG.get("GIF_LOOP", 1)),
        disposal=2
    )
    return (path, winner)

# ========= Discord setup =========
intents = discord.Intents.default()
intents.members = True  # needed for auto-role
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

def get_token() -> Optional[str]:
    t = os.getenv("DISCORD_TOKEN")
    if t: return t.strip()
    if os.path.isfile("token.txt"):
        try: return open("token.txt","r",encoding="utf-8").read().strip() or None
        except Exception: return None
    return None

@bot.event
async def on_ready():
    print(f"[ready] Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"[units] {len(UNITS)} names loaded")
    print(f"[assets] {USED_ASSETS_DIR} | groups: {len(IMAGES)} | files: {sum(len(v) for v in IMAGES.values())}")
    try:
        gid = os.getenv("GUILD_ID")
        if gid:
            await tree.sync(guild=discord.Object(id=int(gid)))
            print(f"[sync] guild {gid}")
        else:
            await tree.sync()
            print("[sync] global (few minutes)")
    except Exception as e:
        print("[sync] failed", e)

# ========= Auto-role =========
@bot.event
async def on_member_join(member: discord.Member):
    role_id = CONFIG.get("AUTO_ROLE_ID")
    if not role_id: return
    try:
        role = member.guild.get_role(int(role_id))
        if not role:
            print("[autorole] role id not found in guild")
            return
        await member.add_roles(role, reason="Auto role on join")
        print(f"[autorole] gave {role.name} to {member.display_name}")
    except Exception as e:
        print("[autorole] failed:", e)

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

# ========= Embed helpers =========
def embed_fields_from_record(e: discord.Embed, rec: dict):
    if not isinstance(rec, dict): return
    skip = {"name","aka","aliases","images","icon","picture","last_updated","last_updated_utc","id","slug"}
    def titleize(k): return " ".join(p.capitalize() for p in k.replace("_"," ").split())
    for key,val in rec.items():
        if key in skip or val in (None,""): continue
        if isinstance(val, (list,tuple)): text = ", ".join(str(x) for x in val)
        elif isinstance(val, dict):
            pairs = [f"{titleize(k2)}: {v2}" for k2,v2 in val.items() if v2 not in (None,"")]
            text = "; ".join(pairs) if pairs else ""
        else: text = str(val)
        if not text: continue
        e.add_field(name=titleize(key), value=text[:1024], inline=True if len(text) < 60 else False)

# ========= Commands =========
async def unit_detail(interaction: discord.Interaction, name: str):
    name = resolve_alias(name)
    rec = unit_record(name)
    imgs = find_images_for(name)
    main, stats = pick_main_and_stats(imgs)
    composed = build_unit_composite(main, stats)
    e = discord.Embed(title=name, color=discord.Color.teal())
    if rec: embed_fields_from_record(e, rec)
    if composed and os.path.isfile(composed):
        fn = os.path.basename(composed)
        file = discord.File(composed, filename=fn)
        e.set_image(url=f"attachment://{fn}")
        await interaction.response.send_message(embed=e, file=file)
    elif main and os.path.isfile(main):
        fn = os.path.basename(main)
        file = discord.File(main, filename=fn)
        e.set_image(url=f"attachment://{fn}")
        await interaction.response.send_message(embed=e, file=file)
    elif stats and os.path.isfile(stats):
        fn = os.path.basename(stats)
        file = discord.File(stats, filename=fn)
        e.set_image(url=f"attachment://{fn}")
        await interaction.response.send_message(embed=e, file=file)
    else:
        await interaction.response.send_message(embed=e)

@tree.command(name="unit", description="Show one unit (image + stats; auto-combines 1+2 images)")
@app_commands.describe(name="Unit name (aliases supported)")
async def unit_cmd(interaction: discord.Interaction, name: str):
    await unit_detail(interaction, name)

@tree.command(name="units", description="Browse units or show a specific unit")
@app_commands.describe(name="Optional: show details for this unit", page="Page (1..)", per_page="Items per page (default 20)")
async def units_cmd(interaction: discord.Interaction, name: Optional[str]=None, page: Optional[int]=1, per_page: Optional[int]=20):
    if name:
        await unit_detail(interaction, name); return
    await interaction.response.defer(thinking=True)
    per_page=max(1,min(50,per_page or 20))
    total=len(UNITS); pages=max(1,(total+per_page-1)//per_page)
    page=max(1,min(page or 1,pages)); start=(page-1)*per_page
    items = UNITS[start:start+per_page]
    body = "\n".join(f"{start+i+1}. {nm}" for i,nm in enumerate(items)) or "—"
    e = discord.Embed(title=f"Units (page {page}/{pages})", description=body, color=discord.Color.blurple())
    e.set_footer(text=f"{total} total units — tip: /units name:<unit> for details")
    await interaction.followup.send(embed=e)

@tree.command(name="valueslink", description="Open the values & calculator links")
async def valueslink(interaction: discord.Interaction):
    v = discord.ui.View()
    v.add_item(discord.ui.Button(label="Values", url=VALUES_URL))
    v.add_item(discord.ui.Button(label="Calculator", url=CALC_URL))
    e = discord.Embed(title="Garden TD Values", description="Open the official lists:", color=discord.Color.green())
    await interaction.response.send_message(embed=e, view=v, ephemeral=True)

@tree.command(name="assetsinfo", description="Show image folder & counts")
async def assetsinfo(interaction: discord.Interaction):
    total_imgs=sum(len(v) for v in IMAGES.values())
    await interaction.response.send_message(f"Assets folder: `{USED_ASSETS_DIR}`\nImage groups: {len(IMAGES)}\nFiles: {total_imgs}", ephemeral=True)

# ---- Wheel (case GIF that stops) ----
class WheelView(discord.ui.View):
    def __init__(self, pool: List[str], k: int, style: str):
        super().__init__(timeout=90); self.pool=pool; self.k=k; self.style=(style or "case").lower()

    async def case_gif(self, msg: discord.Message):
        e = discord.Embed(title="🎁 Opening case...", color=discord.Color.gold()); await msg.edit(embed=e, view=self)
        gif_path, winner = build_case_gif_stopping(self.pool)
        if not gif_path or not os.path.isfile(gif_path):
            await msg.edit(content="Could not build GIF (is Pillow installed?)", view=self); return
        fn = os.path.basename(gif_path)
        gif_file = discord.File(gif_path, filename=fn)
        e.set_image(url=f"attachment://{fn}")
        await msg.edit(embed=e, attachments=[gif_file], view=self)
        # Winner card
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
        await self.spin(await interaction.original_response())

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children: c.disabled = True
        await interaction.response.edit_message(view=self)

@tree.command(name="wheel", description="Open a case (animated GIF that stops on winner)")
@app_commands.describe(include="Filter include", exclude="Filter exclude")
async def wheel(interaction: discord.Interaction, include: Optional[str]=None, exclude: Optional[str]=None):
    pool = filter_pool(UNITS[:], include, exclude)
    if not pool: await interaction.response.send_message("No units match your filters.", ephemeral=True); return
    await interaction.response.defer(thinking=True)
    holder = await interaction.followup.send(embed=discord.Embed(title="Spinning...", color=discord.Color.gold()), wait=True)
    await WheelView(pool, 1, "case").spin(holder)

# ---- Team ----
class TeamView(discord.ui.View):
    def __init__(self, pool: List[str], size: int, allow_dup: bool):
        super().__init__(timeout=90); self.pool=pool; self.size=size; self.allow_dup=allow_dup

    async def spin(self, msg: discord.Message):
        e = discord.Embed(title="🎲 Building Team...", color=discord.Color.gold()); await msg.edit(embed=e, view=self)
        picks: List[str] = []
        for slot in range(1, self.size+1):
            for i in range(CONFIG["SPIN_HOPS_SLOT"]):
                cand = random.choice(self.pool if self.allow_dup else [u for u in self.pool if u not in picks] or self.pool)
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
        await self.spin(await interaction.original_response())

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children: c.disabled = True
        await interaction.response.edit_message(view=self)

@tree.command(name="team", description="Roulette team builder (with filters)")
@app_commands.describe(size="Team size (1-7, default 7)", allow_duplicates="Allow duplicates", include="Filter include", exclude="Filter exclude")
async def team(interaction: discord.Interaction, size: Optional[int]=7, allow_duplicates: Optional[bool]=False, include: Optional[str]=None, exclude: Optional[str]=None):
    pool = filter_pool(UNITS[:], include, exclude)
    if not pool: await interaction.response.send_message("No units match your filters.", ephemeral=True); return
    size = max(1, min(7, int(size or 7)))
    if not allow_duplicates: size = min(size, len(pool))
    await interaction.response.defer(thinking=True)
    holder = await interaction.followup.send(embed=discord.Embed(title="🎲 Building Team...", color=discord.Color.gold()), wait=True)
    await TeamView(pool, size, bool(allow_duplicates)).spin(holder)

# ---- Clean "GUI" menu ----
class MenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Open Case", style=discord.ButtonStyle.success, emoji="🎁")
    async def open_case(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        pool = UNITS[:]
        holder = await interaction.followup.send(embed=discord.Embed(title="Spinning...", color=discord.Color.gold()), ephemeral=True, wait=True)
        await WheelView(pool, 1, "case").spin(holder)

    @discord.ui.button(label="Team (7)", style=discord.ButtonStyle.primary, emoji="🎲")
    async def team7(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True, ephemeral=True)
        pool = UNITS[:]
        holder = await interaction.followup.send(embed=discord.Embed(title="🎲 Building Team...", color=discord.Color.gold()), ephemeral=True, wait=True)
        await TeamView(pool, 7, False).spin(holder)

    @discord.ui.button(label="Values Links", style=discord.ButtonStyle.secondary, emoji="🔗")
    async def values(self, interaction: discord.Interaction, button: discord.ui.Button):
        v = discord.ui.View()
        v.add_item(discord.ui.Button(label="Values", url=VALUES_URL))
        v.add_item(discord.ui.Button(label="Calculator", url=CALC_URL))
        await interaction.response.send_message("Open the official lists:", view=v, ephemeral=True)

    @discord.ui.button(label="Units List", style=discord.ButtonStyle.secondary, emoji="📜")
    async def units(self, interaction: discord.Interaction, button: discord.ui.Button):
        total=len(UNITS); per_page=20; items=UNITS[:per_page]
        desc = "\n".join(f"{i+1}. {nm}" for i,nm in enumerate(items)) or "—"
        e = discord.Embed(title=f"Units (1/{(total+per_page-1)//per_page})", description=desc, color=discord.Color.blurple())
        await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="menu", description="Open the bot menu")
async def menu(interaction: discord.Interaction):
    e = discord.Embed(
        title="🌿 Garden TD Helper",
        description="Pick an action below. You can also use slash commands like /wheel, /team, /unit.",
        color=discord.Color.dark_green()
    )
    e.set_footer(text="Tip: use /autorole set to auto-assign a role when someone joins")
    await interaction.response.send_message(embed=e, view=MenuView(), ephemeral=True)

# ---- Reload & Config ----
@tree.command(name="reload", description="Reload units/images/db/aliases")
async def reload_all(interaction: discord.Interaction):
    global UNITS, USED_ASSETS_DIR, IMAGES, UNITS_DB, ALIASES, OUTPUT_DIR, CONFIG
    UNITS = load_units()
    USED_ASSETS_DIR = ASSETS_DIR if os.path.isdir(ASSETS_DIR) else (_autodetect_assets_dir(os.getcwd()) or ASSETS_DIR)
    IMAGES = scan_images(USED_ASSETS_DIR)
    UNITS_DB = load_units_db()
    ALIASES = load_aliases()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    await interaction.response.send_message(f"Reloaded. Units: {len(UNITS)} | Image groups: {len(IMAGES)} | DB entries: {len(UNITS_DB)} | Aliases: {len(ALIASES)} | OUTPUT_DIR: {OUTPUT_DIR}", ephemeral=True)

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

# ========= Main =========
def main():
    print("[boot] starting… OUTPUT_DIR:", OUTPUT_DIR)
    tok = os.getenv("DISCORD_TOKEN") or (open("token.txt","r",encoding="utf-8").read().strip() if os.path.isfile("token.txt") else None)
    if not tok:
        print("[boot] No token found. Set DISCORD_TOKEN or create token.txt")
        return
    bot.run(tok)

if __name__ == "__main__":
    main()
