import re
# -*- coding: utf-8 -*-
"""
ToukaGTD bot - consolidated build (public gambling + editable redeem + extra games)
Python 3.8 compatible (discord.py 2.x)
"""

import os
import asyncio, io, json, random, math, asyncio, time
from typing import Optional, List, Dict, Tuple

import discord
from discord import app_commands
from discord.ext import commands

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except Exception:
    PIL_OK = False




# -------------------- Units.txt helper --------------------
UNITS_TXT_PATH = "units.txt"
def read_units_txt():
    """Return a list of unit names from units.txt (ignores blank lines and # comments)."""
    out = []
    try:
        with open(UNITS_TXT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                out.append(s)
    except Exception:
        pass
    return out
# -------------------- JJK-style message spawns --------------------
import json, time, random

UNITSPAWN_JJK_PATH = "unitspawn_jjk.json"
# guild_id -> {
#   "channel_id": int, "min_msgs": 20, "max_msgs": 60,
#   "reward_min": 0, "reward_max": 0, "chance": 100
# }
JJK_CFG = {}
# Per-channel counters/state (non-persistent): (guild_id, channel_id) -> {"count": int, "threshold": int}
JJK_STATE = {}
# Active spawns: (guild_id, channel_id) -> {"unit": str, "deadline": float, "message_id": int}
JJK_ACTIVE = {}

def _jjk_load():
    global JJK_CFG
    try:
        with open(UNITSPAWN_JJK_PATH, "r", encoding="utf-8") as f:
            JJK_CFG = json.load(f)
    except Exception:
        JJK_CFG = {}

def _jjk_save():
    try:
        with open(UNITSPAWN_JJK_PATH, "w", encoding="utf-8") as f:
            json.dump(JJK_CFG, f)
    except Exception:
        pass

def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())

def _jjk_threshold(min_msgs: int, max_msgs: int) -> int:
    if max_msgs < min_msgs: max_msgs = min_msgs
    return random.randint(min_msgs, max_msgs)
# -------------------- Unit Spawn Auto Config --------------------
import json
UNITSPAWN_CFG_PATH = "unitspawn.json"
UNITSPAWN = {}  # guild_id -> {"channel_id": int, "min_min": 5, "max_min": 15, "reward_min": 0, "reward_max": 0, "chance": 100}
UNITSPAWN_TASKS = {}  # guild_id -> asyncio.Task

def _unitspawn_load():
    global UNITSPAWN
    try:
        with open(UNITSPAWN_CFG_PATH, "r", encoding="utf-8") as f:
            UNITSPAWN = json.load(f)
    except Exception:
        UNITSPAWN = {}

def _unitspawn_save():
    try:
        with open(UNITSPAWN_CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(UNITSPAWN, f)
    except Exception:
        pass
# -------------------- Configuration --------------------
ASSETS_DIR = os.environ.get("ASSETS_DIR", "units_assets")
CASINO_ASSETS_DIR = os.environ.get("CASINO_ASSETS_DIR", "casino_assets")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "media")
CONFIG_PATH = "config.json"
ECON_PATH = "economy.json"
UNITS_TXT = "units.txt"
ALIASES_JSON = "aliases.json"
TOKEN_PATH = "token.txt"

DEFAULT_CONFIG: Dict[str, object] = {
    "UPDATE_CHANNEL_ID": None,
    "UNDERSCORE_TO_SPACE": True,
    "SPIN_STRIP_W": 640,
    "SPIN_STRIP_H": 120,
    "SPIN_VISIBLE": 7,
    "SPIN_HOPS_SLOT": 12,
    "GAMBLING_ENABLED": True,
    "CURRENCY": "🍀",
    "MIN_BET": 10,
    "MAX_BET": 50000,
    "HOUSE_EDGE": 0.02,
    "DAILY_AMOUNT": 500,
    "GAMBLING_CHANNEL_ID": None,
    "BANKER_ROLE_ID": None
}

def _load_json(path: str, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback

def _save_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

CONFIG: Dict[str, object] = _load_json(CONFIG_PATH, DEFAULT_CONFIG.copy())
for k, v in DEFAULT_CONFIG.items():
    CONFIG.setdefault(k, v)

ECON: Dict[str, Dict] = _load_json(ECON_PATH, {
    "balances": {},
    "last_daily": {},
    "settings": {},
    "history": {},
    "stats": {},
    "redeem": {}
})

def _save_econ():
    _save_json(ECON_PATH, ECON)

def _migrate_econ():
    """Ensure top-level ECON keys exist (handles old economy.json files)."""
    ECON.setdefault("balances", {})
    ECON.setdefault("last_daily", {})
    ECON.setdefault("settings", {})
    ECON.setdefault("history", {})
    ECON.setdefault("stats", {})
    ECON.setdefault("redeem", {})
    _save_econ()

_migrate_econ()

# -------------------- Helpers --------------------
def norm_key(name: str) -> str:
    return " ".join(name.lower().replace("_", " ").split())

def _now_ts() -> int:
    return int(time.time())

def list_units() -> List[str]:
    try:
        with open(UNITS_TXT, "r", encoding="utf-8") as f:
            out = []
            for ln in f:
                s = ln.strip()
                if not s or s.startswith("#"):
                    continue
                out.append(s)
            return out
    except Exception:
        return []

def load_aliases() -> Dict[str, str]:
    data = _load_json(ALIASES_JSON, {})
    return {norm_key(k): v for k, v in data.items()}

ALIASES = load_aliases()

def unit_to_filename(name: str) -> str:
    base = name
    if CONFIG.get("UNDERSCORE_TO_SPACE", True):
        base = base.replace("_", " ")
    return base

def asset_path_for(name: str, panel: int = 1) -> Optional[str]:
    if not os.path.isdir(ASSETS_DIR):
        return None
    candidates = []
    base = unit_to_filename(name)
    roots = {base, base.replace(" ", "_"), base.replace("_", " ")}
    exts = [".png", ".jpg", ".jpeg"]
    suffixes = [f" {panel}", f"_{panel}", ""] if panel == 1 else [f" {panel}", f"_{panel}"]
    for root in roots:
        for suf in suffixes:
            for ext in exts:
                p = os.path.join(ASSETS_DIR, f"{root}{suf}{ext}")
                if os.path.isfile(p):
                    candidates.append(p)
    return candidates[0] if candidates else None

def find_unit(query: str) -> Optional[str]:
    key = norm_key(query)
    if key in ALIASES:
        return ALIASES[key]
    units = read_units_txt()
    if not units:
        return None
    low = [u.lower() for u in units]
    if key in low:
        return units[low.index(key)]
    for u in units:
        if norm_key(u).startswith(key):
            return u
    for u in units:
        if key in norm_key(u):
            return u
    return None

def ensure_dirs():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(CASINO_ASSETS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

ensure_dirs()



def list_unit_images_one_panel() -> list:
    """Return absolute paths of images in units_assets that end with '1.png'."""
    paths = []
    if os.path.isdir(ASSETS_DIR):
        for fn in sorted(os.listdir(ASSETS_DIR)):
            if fn.lower().endswith("1.png"):
                paths.append(os.path.join(ASSETS_DIR, fn))
    return paths





def _download_image_sync(url: str, dest_path: str) -> bool:
    """Small sync downloader (urllib) used only by admin or background task."""
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = resp.read()
        with open(dest_path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False

def _ensure_online_casino_images(min_count: int = 6) -> None:
    """If casino_assets is empty, fetch a few square images from Picsum."""
    try:
        os.makedirs(CASINO_ASSETS_DIR, exist_ok=True)
        existing = [fn for fn in os.listdir(CASINO_ASSETS_DIR) if fn.lower().endswith(('.png','.jpg','.jpeg'))]
    except Exception:
        existing = []
    if len(existing) >= min_count:
        return
    seeds = [f"casino{i}" for i in range(1, 16)]
    for i, seed in enumerate(seeds[:max(min_count, 8)], start=1):
        url = f"https://picsum.photos/seed/{seed}/256/256"
        dest = os.path.join(CASINO_ASSETS_DIR, f"pic_{i}.png")
        _download_image_sync(url, dest)

def casino_banner_image(max_tiles: int = 6, tile_size: int = 110, pad: int = 8) -> Optional[bytes]:
    """Create a banner image from units_assets files ending with '1.png'. Returns PNG bytes or None."""
    if not PIL_OK:
        return None
    if not os.path.isdir(CASINO_ASSETS_DIR):
        return None
    files = [os.path.join(ASSETS_DIR, fn) for fn in sorted(os.listdir(ASSETS_DIR)) if fn.lower().endswith("1.png")]
    if not files:
        return None
    import random
    chosen = files[:max_tiles] if len(files) <= max_tiles else random.sample(files, max_tiles)
    from PIL import Image
    tiles = []
    for p in chosen:
        try:
            im = Image.open(p).convert("RGBA")
            im = im.resize((tile_size, tile_size), Image.LANCZOS)
            tiles.append(im)
        except Exception:
            continue
    if not tiles:
        return None
    w = pad + sum(t.width + pad for t in tiles)
    h = pad*2 + tile_size
    out = Image.new("RGBA", (w, h), (20, 20, 26, 255))
    x = pad
    for t in tiles:
        out.paste(t, (x, pad), t)
        x += t.width + pad
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()

# -------------------- Image helpers --------------------
FONT = None
if PIL_OK:
    try:
        FONT = ImageFont.load_default()
    except Exception:
        FONT = None

def compose_unit_panel(name: str) -> Optional[bytes]:
    p1 = asset_path_for(name, 1) or asset_path_for(name, 0) or asset_path_for(name, -1)
    p2 = asset_path_for(name, 2)
    if not p1 and not p2:
        return None
    if not PIL_OK or not p1:
        target = p1 or p2
        with open(target, "rb") as f:
            return f.read()
    try:
        img1 = Image.open(p1).convert("RGBA")
        if p2 and os.path.isfile(p2):
            img2 = Image.open(p2).convert("RGBA")
            w = max(img1.width, img2.width)
            h = img1.height + img2.height
            out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            out.paste(img1, (0, 0), img1)
            out.paste(img2, (0, img1.height), img2)
        else:
            out = img1
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        with open(p1, "rb") as f:
            return f.read()

def build_collage(names: List[str], price_labels: Optional[List[str]] = None) -> Optional[bytes]:
    if not PIL_OK:
        return None
    tiles: List[Image.Image] = []
    for nm in names:
        p = asset_path_for(nm, 1) or asset_path_for(nm, 0) or asset_path_for(nm, -1)
        if not p:
            continue
        try:
            im = Image.open(p).convert("RGBA")
            im = im.resize((110, 110), Image.LANCZOS)
            fr = Image.new("RGBA", (126, 126), (60, 42, 16, 255))
            fr.paste(im, (8, 8), im)
            tiles.append(fr)
        except Exception:
            continue
    if not tiles:
        return None
    pad = 8
    w = pad + sum(t.width + pad for t in tiles)
    h = tiles[0].height + pad * 2
    out = Image.new("RGBA", (w, h), (35, 26, 18, 255))
    x = pad
    draw = ImageDraw.Draw(out)
    for idx, t in enumerate(tiles):
        out.paste(t, (x, pad), t)
        if price_labels and idx < len(price_labels) and FONT:
            lbl = price_labels[idx]
            tw, th = draw.textsize(lbl, font=FONT)
            draw.rectangle([x+4, pad + t.height - th - 6, x+4+tw+6, pad + t.height - 4], fill=(0,0,0,160))
            draw.text((x+7, pad + t.height - th - 5), lbl, font=FONT, fill=(0,255,0))
        x += t.width + pad
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()

# -------------------- Bot setup --------------------
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Casino admin slash command group
casinoadmin = app_commands.Group(name="casinoadmin", description="Casino admin tools")
tree.add_command(casinoadmin)


async def send_text(inter: discord.Interaction, text: str, ephemeral: bool = True):
    try:
        if hasattr(inter, "response") and not inter.response.is_done():
            return await inter.response.send_message(text, ephemeral=ephemeral)
        else:
            return await inter.followup.send(text, ephemeral=ephemeral)
    except Exception:
        pass

# --------------- Economy helpers ---------------
def guild_settings(guild_id: int) -> Dict[str, object]:
    g = str(guild_id)
    return ECON["settings"].setdefault(g, {})

def set_guild_setting(guild_id: int, key: str, value) -> None:
    ECON.setdefault("settings", {}).setdefault(str(guild_id), {})[key] = value
    _save_econ()

def guild_setting(guild_id: int, key: str, default=None):
    g = str(guild_id)
    if g in ECON.get("settings", {}) and key in ECON["settings"][g]:
        return ECON["settings"][g][key]
    return CONFIG.get(key, default)

def _limits(guild_id: int) -> Tuple[int, int, float, int, str]:
    s = guild_settings(guild_id)
    min_bet = int(s.get("MIN_BET", CONFIG.get("MIN_BET", 10)))
    max_bet = int(s.get("MAX_BET", CONFIG.get("MAX_BET", 50000)))
    edge = float(s.get("HOUSE_EDGE", CONFIG.get("HOUSE_EDGE", 0.02)))
    daily = int(s.get("DAILY_AMOUNT", CONFIG.get("DAILY_AMOUNT", 500)))
    curr = str(s.get("CURRENCY", CONFIG.get("CURRENCY", "🍀")))
    return (min_bet, max_bet, edge, daily, curr)

async def eco_add(guild_id: int, user_id: int, delta: int) -> int:
    """Add delta and update stats (safe for old economy.json)."""
    g = str(guild_id); u = str(user_id)
    ECON.setdefault("balances", {}).setdefault(g, {})
    ECON["balances"][g][u] = int(ECON["balances"][g].get(u, 0)) + int(delta)
    ECON.setdefault("stats", {}).setdefault(g, {}).setdefault(u, {"bets":0,"won":0,"lost":0,"biggest":0})
    if delta > 0:
        ECON["stats"][g][u]["won"] += int(delta)
        if int(delta) > ECON["stats"][g][u]["biggest"]:
            ECON["stats"][g][u]["biggest"] = int(delta)
    elif delta < 0:
        ECON["stats"][g][u]["lost"] += int(-delta)
    _save_econ()
    return ECON["balances"][g][u]

def log_history(guild_id: int, user_id: int, game: str, bet: int, result_delta: int) -> None:
    g = str(guild_id); u = str(user_id)
    ECON.setdefault("history", {}).setdefault(g, {}).setdefault(u, [])
    ECON["history"][g][u].append({"t": _now_ts(), "game": game, "bet": int(bet), "result": int(result_delta)})
    if len(ECON["history"][g][u]) > 100:
        ECON["history"][g][u] = ECON["history"][g][u][-100:]
    ECON.setdefault("stats", {}).setdefault(g, {}).setdefault(u, {"bets":0,"won":0,"lost":0,"biggest":0})
    ECON["stats"][g][u]["bets"] += 1
    _save_econ()

def eco_get(guild_id: int, user_id: int) -> int:
    return int(ECON.get("balances", {}).get(str(guild_id), {}).get(str(user_id), 0))

def _fmt_currency(n: int, symbol: str) -> str:
    return f"{symbol}{n:,}" if symbol.strip() != "" else f"{n:,}"

def _get_gambling_channel_id(guild_id: int) -> Optional[int]:
    val = guild_setting(guild_id, "GAMBLING_CHANNEL_ID", None)
    return int(val) if val else None

def _get_banker_role_id(guild_id: int) -> Optional[int]:
    val = guild_setting(guild_id, "BANKER_ROLE_ID", None)
    return int(val) if val else None

def user_is_banker(inter: discord.Interaction) -> bool:
    if not inter.guild:
        return False
    if inter.user.guild_permissions.manage_guild:
        return True
    role_id = _get_banker_role_id(inter.guild.id)
    if not role_id:
        return False
    if hasattr(inter.user, "roles"):
        return any(getattr(r, "id", 0) == role_id for r in inter.user.roles)
    return False

def banker_only():
    async def predicate(inter: discord.Interaction) -> bool:
        if not inter.guild:
            raise app_commands.CheckFailure("This command can only be used in a server.")
        if not user_is_banker(inter):
            raise app_commands.CheckFailure("Manage Server or the configured Banker role required.")
        return True
    return app_commands.check(predicate)

def in_gambling_channel():
    async def predicate(inter: discord.Interaction) -> bool:
        if not inter.guild:
            raise app_commands.CheckFailure("Gambling commands can only be used in a server.")
        allowed_id = _get_gambling_channel_id(inter.guild.id)
        if allowed_id is None:
            return True
        if inter.channel and inter.channel.id == int(allowed_id):
            return True
        chan = inter.guild.get_channel(int(allowed_id))
        where = chan.mention if chan else f"<#{allowed_id}>"
        raise app_commands.CheckFailure(f"Gambling commands are restricted to {where}.")
    return app_commands.check(predicate)

def owner_only():
    async def predicate(inter: discord.Interaction) -> bool:
        if not inter.guild:
            raise app_commands.CheckFailure("This command can only be used in a server.")
        if inter.guild.owner_id != inter.user.id:
            raise app_commands.CheckFailure("Only the **server owner** can use this panel.")
        return True
    return app_commands.check(predicate)

@tree.error
async def _on_app_error(inter: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        try:
            if not inter.response.is_done():
                await inter.response.send_message(str(error), ephemeral=True)
            else:
                await inter.followup.send(str(error), ephemeral=True)
        except Exception:
            pass
        return

# -------------------- Commands: admin sync --------------------
@tree.command(name="sync", description="Admin: force re-sync of commands to this server")
@app_commands.checks.has_permissions(manage_guild=True)
async def sync_cmd(interaction: discord.Interaction):
    try:
        await tree.sync(guild=interaction.guild)
        await interaction.response.send_message("✅ Synced slash commands to this server.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Sync failed: {e}", ephemeral=True)

# -------------------- Units, wheel, team, ingest, values (unchanged) --------------------
# ... (omitted here for brevity in this comment block; same as previous build) ...
# Keeping all unit features intact below:

class UnitsPager(discord.ui.View):
    def __init__(self, items: List[str], start: int = 0):
        super().__init__(timeout=180)
        self.items = items
        self.idx = max(0, start)
        self.per = 20
        self.update_state()
    def page(self) -> int: return self.idx // self.per
    def pages(self) -> int: return max(1, math.ceil(len(self.items)/self.per))
    def slice(self) -> List[str]:
        s = self.page() * self.per
        return self.items[s:s+self.per]
    def update_state(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "prev": child.disabled = (self.page()==0)
                elif child.custom_id == "next": child.disabled = (self.page()>=self.pages()-1)
    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="prev")
    async def prev(self, inter: discord.Interaction, btn: discord.ui.Button):
        self.idx = max(0, self.idx - self.per); self.update_state()
        await inter.response.edit_message(**self._render())
    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, custom_id="next")
    async def next(self, inter: discord.Interaction, btn: discord.ui.Button):
        self.idx = min((self.pages()-1)*self.per, self.idx + self.per); self.update_state()
        await inter.response.edit_message(**self._render())
    def _render(self):
        page = self.page()+1; pages = self.pages()
        s = self.slice(); start_idx = (page-1)*self.per + 1
        desc = "\n".join(f"{i}. {name}" for i, name in enumerate(s, start_idx)) or "_empty_"
        embed = discord.Embed(title=f"Units (page {page}/{pages})", description=desc, color=0x5865F2)
        embed.set_footer(text=f"{len(self.items)} total units — tip: /unit name:<unit> for details")
        return {"embed": embed, "view": self}

@tree.command(name="units", description="List all units (paginated) or show details for a unit")
@app_commands.describe(name="Optional unit to show")
async def units_cmd(interaction: discord.Interaction, name: Optional[str] = None):
    if name:
        u = find_unit(name)
        if not u:
            return await interaction.response.send_message(f"Couldn't find a unit named **{name}**.", ephemeral=True)
        img = compose_unit_panel(u)
        if img:
            file = discord.File(io.BytesIO(img), filename="unit.png")
            embed = discord.Embed(title=u, color=0x2ECC71); embed.set_image(url="attachment://unit.png")
            await interaction.response.send_message(embed=embed, file=file)
        else:
            await interaction.response.send_message(f"**{u}** — no images found in {ASSETS_DIR}", ephemeral=True)
        return
    items = list_units()
    if not items:
        return await interaction.response.send_message("No units found. Upload **units.txt** or add items.", ephemeral=True)
    view = UnitsPager(items, start=0)
    await interaction.response.send_message(**view._render())

@tree.command(name="unit", description="Show a unit's picture (and stats if available)")
async def unit_cmd(interaction: discord.Interaction, name: str):
    u = find_unit(name) or name
    img = compose_unit_panel(u)
    if not img: return await interaction.response.send_message(f"No images found for **{u}** in `{ASSETS_DIR}`.", ephemeral=True)
    file = discord.File(io.BytesIO(img), filename="unit.png")
    embed = discord.Embed(title=u, color=0x2ECC71); embed.set_image(url="attachment://unit.png")
    await interaction.response.send_message(embed=embed, file=file)

class WheelView(discord.ui.View):
    def __init__(self, chosen: str):
        super().__init__(timeout=120); self.chosen = chosen
    @discord.ui.button(label="Respin", style=discord.ButtonStyle.primary)
    async def respin(self, inter: discord.Interaction, btn: discord.ui.Button):
        units = read_units_txt()
        if not units: return await inter.response.send_message("No units found.", ephemeral=True)
        choice = random.choice(units); self.chosen = choice
        img = compose_unit_panel(choice); files = []; embed = discord.Embed(title="🎁 Winner", description=choice, color=0xF1C40F)
        if img: files.append(discord.File(io.BytesIO(img), filename="winner.png")); embed.set_image(url="attachment://winner.png")
        await inter.response.edit_message(embed=embed, attachments=files)

@tree.command(name="wheel", description="Spin a case and pick a random unit")
async def wheel_cmd(interaction: discord.Interaction):
    units = read_units_txt()
    if not units: return await interaction.response.send_message("No units available.", ephemeral=True)
    chosen = random.choice(units)
    files = []; embed = discord.Embed(title="🎁 Opening case...", color=0xF1C40F)
    view = WheelView(chosen)
    await interaction.response.send_message(embed=embed, view=view, files=files)

class TeamView(discord.ui.View):
    def __init__(self, names: List[str]): super().__init__(timeout=180); self.names = names
    @discord.ui.button(label="Respin Team", style=discord.ButtonStyle.primary)
    async def respin(self, inter: discord.Interaction, btn: discord.ui.Button):
        units = read_units_txt()
        if not units: return await inter.response.send_message("No units found.", ephemeral=True)
        self.names = random.sample(units, min(7, len(units)))
        embed = discord.Embed(title="Team Collage", color=0x3498DB); await inter.response.edit_message(embed=embed)

@tree.command(name="team", description="Create a random team of 7")
async def team_cmd(interaction: discord.Interaction):
    units = read_units_txt()
    if not units: return await interaction.response.send_message("No units available.", ephemeral=True)
    names = random.sample(units, min(7, len(units))); embed = discord.Embed(title="Team Collage", color=0x3498DB)
    view = TeamView(names); await interaction.response.send_message(embed=embed, view=view)

@tree.command(name="values", description="Show the official value list link")
async def values_cmd(interaction: discord.Interaction):
    url = "https://sites.google.com/view/garden-td-values/main-page?authuser=0"
    embed = discord.Embed(title="Garden TD Values", description=f"[Open the live value list]({url})", color=0x95A5A6)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# -------------------- Ingest attachments --------------------
def _sanitize_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    if CONFIG.get("UNDERSCORE_TO_SPACE", True): name = name.replace("_", " ")
    return "".join(ch for ch in name if ch >= " " and ch not in ':"<>|')

async def _save_attachment(att: discord.Attachment) -> str:
    data = await att.read()
    safe = _sanitize_filename(att.filename); ext = os.path.splitext(safe)[1].lower()
    if ext in (".png",".jpg",".jpeg",".webp",".gif"): out = os.path.join(ASSETS_DIR, safe)
    elif ext == ".txt": out = UNITS_TXT if "units" in safe.lower() else os.path.join(OUTPUT_DIR, safe)
    elif ext == ".json": out = ALIASES_JSON if "aliases" in safe.lower() else os.path.join(OUTPUT_DIR, safe)
    else: out = os.path.join(OUTPUT_DIR, safe)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as f: f.write(data)
    if out.endswith(ALIASES_JSON):
        global ALIASES; ALIASES = load_aliases()
    return out

@tree.command(name="ingest", description="Upload & save files (images, units.txt, aliases.json, etc.)")
@app_commands.describe(file1="Attachment", file2="Attachment", file3="Attachment", file4="Attachment", file5="Attachment",
                       file6="Attachment", file7="Attachment", file8="Attachment", file9="Attachment", file10="Attachment")
async def ingest_cmd(interaction: discord.Interaction, file1: Optional[discord.Attachment]=None, file2: Optional[discord.Attachment]=None,
                     file3: Optional[discord.Attachment]=None, file4: Optional[discord.Attachment]=None, file5: Optional[discord.Attachment]=None,
                     file6: Optional[discord.Attachment]=None, file7: Optional[discord.Attachment]=None, file8: Optional[discord.Attachment]=None,
                     file9: Optional[discord.Attachment]=None, file10: Optional[discord.Attachment]=None):
    files = [f for f in (file1,file2,file3,file4,file5,file6,file7,file8,file9,file10) if f is not None]
    if not files: return await interaction.response.send_message("Please supply one or more attachments via the options.", ephemeral=True)
    saved = []
    for att in files[:10]:
        path = await _save_attachment(att); saved.append(os.path.basename(path))
    await interaction.response.send_message(f"Saved: {', '.join(saved)}", ephemeral=True)

# -------------------- Economy basics --------------------
@tree.command(name="daily", description="Claim your daily reward")
@in_gambling_channel()
async def daily_cmd(interaction: discord.Interaction):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True):
        return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    _,_,_,daily,curr = _limits(interaction.guild.id)
    last = ECON["last_daily"].setdefault(str(interaction.guild.id), {}).get(str(interaction.user.id), 0)
    now = _now_ts()
    if now - last < 23*3600 + 30*60:
        remain = (23*3600 + 30*60) - (now - last)
        return await interaction.response.send_message(f"You already claimed daily. Try again in **{remain//3600}h {(remain%3600)//60}m**.", ephemeral=True)
    ECON["last_daily"].setdefault(str(interaction.guild.id), {})[str(interaction.user.id)] = now
    new_bal = await eco_add(interaction.guild.id, interaction.user.id, daily)
    await interaction.response.send_message(f"You received **{_fmt_currency(daily, curr)}**. Balance: **{_fmt_currency(new_bal, curr)}**.", ephemeral=True)

@tree.command(name="balance", description="Check your balance (or someone else's)")
async def balance_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user
    bal = eco_get(interaction.guild.id, target.id)
    _,_,_,_,curr = _limits(interaction.guild.id)
    await interaction.response.send_message(f"{target.mention} balance: **{_fmt_currency(bal, curr)}**.", ephemeral=True)

# -------------------- PUBLIC gambling commands --------------------
@tree.command(name="coinflip", description="Coinflip (2x minus house edge)")
@in_gambling_channel()
@app_commands.describe(side="heads/tails", bet="bet amount")
async def coinflip_cmd(interaction: discord.Interaction, side: str, bet: int):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True):
        return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    side = side.lower().strip()
    if side not in ("heads", "tails"):
        return await interaction.response.send_message("Choose **heads** or **tails**.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if not (min_bet <= bet <= max_bet): return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet: return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    res = random.choice(("heads", "tails"))
    if res == side:
        win = int(round(bet * (2.0 - edge))); new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
        log_history(interaction.guild.id, interaction.user.id, "coinflip", bet, win)
        await interaction.response.send_message(f"🪙 **{res.upper()}**! {interaction.user.mention} won **{_fmt_currency(win, curr)}**. New balance: **{_fmt_currency(new_bal, curr)}**.")
    else:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
        log_history(interaction.guild.id, interaction.user.id, "coinflip", bet, -bet)
        await interaction.response.send_message(f"🪙 **{res.upper()}**. {interaction.user.mention} lost **{_fmt_currency(bet, curr)}**. Balance: **{_fmt_currency(new_bal, curr)}**.")

SLOT_EMOJI = ["🍒", "🍋", "🍇", "🔔", "⭐"]
@tree.command(name="slots", description="Slots (3 reels) – 3x ≈9x, 2 in a row ≈2x (minus edge)")
@in_gambling_channel()
@app_commands.describe(bet="bet amount")
async def slots_cmd(interaction: discord.Interaction, bet: int):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True):
        return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if not (min_bet <= bet <= max_bet): return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet: return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    reels = [random.choice(SLOT_EMOJI) for _ in range(3)]
    text = " | ".join(reels); win = 0
    if len(set(reels)) == 1: win = int(round(bet * (9.0 - edge)))
    elif reels[0] == reels[1] or reels[1] == reels[2]: win = int(round(bet * (2.0 - edge)))
    if win > 0:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, win); log_history(interaction.guild.id, interaction.user.id, "slots", bet, win)
        await interaction.response.send_message(f"{interaction.user.mention} rolled **{text}** — won **{_fmt_currency(win, curr)}**! New balance: **{_fmt_currency(new_bal, curr)}**")
    else:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet); log_history(interaction.guild.id, interaction.user.id, "slots", bet, -bet)
        await interaction.response.send_message(f"{interaction.user.mention} rolled **{text}** — no win. Lost **{_fmt_currency(bet, curr)}** — Balance: **{_fmt_currency(new_bal, curr)}**")

@tree.command(name="dice", description="Bet high/low on 2d6 (7 is house)")
@in_gambling_channel()
@app_commands.describe(bet="bet amount", guess="high or low")
async def dice_cmd(interaction: discord.Interaction, bet: int, guess: str):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True):
        return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    guess = guess.lower().strip()
    if guess not in ("high","low"): return await interaction.response.send_message("Use **high** or **low**.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if not (min_bet <= bet <= max_bet): return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet: return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    roll = random.randint(1,6) + random.randint(1,6)
    if (roll <= 6 and guess == "low") or (roll >= 8 and guess == "high"):
        win = int(round(bet * (2.0 - edge))); new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
        log_history(interaction.guild.id, interaction.user.id, "dice", bet, win)
        return await interaction.response.send_message(f"🎲 {interaction.user.mention} rolled **{roll}** — won **{_fmt_currency(win,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")
    else:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet); log_history(interaction.guild.id, interaction.user.id, "dice", bet, -bet)
        return await interaction.response.send_message(f"🎲 {interaction.user.mention} rolled **{roll}** — lost **{_fmt_currency(bet,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")

@tree.command(name="roulette", description="Roulette: bet red/black or exact number (0-36)")
@in_gambling_channel()
@app_commands.describe(bet="bet amount", choice="red/black or 0-36")
async def roulette_cmd(interaction: discord.Interaction, bet: int, choice: str):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True):
        return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if not (min_bet <= bet <= max_bet): return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet: return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    REDS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    num = random.randint(0,36); color = "red" if num in REDS else ("green" if num == 0 else "black")
    win = 0; c = choice.strip().lower()
    if c.isdigit() and 0 <= int(c) <= 36:
        if int(c) == num: win = int(round(bet * (35.0 - edge)))
    elif c in ("red","black"):
        if c == color: win = int(round(bet * (2.0 - edge)))
    else:
        return await interaction.response.send_message("Choice must be **red**, **black**, or **0..36**.", ephemeral=True)
    if win > 0:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, win); log_history(interaction.guild.id, interaction.user.id, "roulette", bet, win)
        await interaction.response.send_message(f"🎡 {interaction.user.mention} → {num} ({color}) — won **{_fmt_currency(win,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")
    else:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet); log_history(interaction.guild.id, interaction.user.id, "roulette", bet, -bet)
        await interaction.response.send_message(f"🎡 {interaction.user.mention} → {num} ({color}) — lost **{_fmt_currency(bet,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")

@tree.command(name="blackjack", description="Blackjack vs dealer")
@in_gambling_channel()
@app_commands.describe(bet="bet amount")
async def blackjack_cmd(interaction: discord.Interaction, bet: int):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True): return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if not (min_bet <= bet <= max_bet): return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet: return await interaction.response.send_message("Insufficient balance.", ephemeral=True)

    ranks = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]; suits = ["♠","♥","♦","♣"]
    deck = [f"{r}{s}" for r in ranks for s in suits] * 4; random.shuffle(deck)

    def card_value(hand: List[str]) -> int:
        v = 0; aces = 0
        for c in hand:
            r = c[:-1] if c[:-1] in ("10",) else c[0]
            if r in ("J","Q","K"): v += 10
            elif r == "A": v += 11; aces += 1
            else: v += int(r)
        while v > 21 and aces: v -= 10; aces -= 1
        return v

    player = [deck.pop(), deck.pop()]; dealer = [deck.pop(), deck.pop()]

    class BJView(discord.ui.View):
        def __init__(self): super().__init__(timeout=90); self.current_bet = bet; self.finished = False
        async def finish(self, inter: discord.Interaction, outcome: str, delta: int):
            if self.finished: return
            self.finished = True
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, delta)
            log_history(interaction.guild.id, interaction.user.id, "blackjack", self.current_bet, delta)
            for c in self.children: c.disabled = True
            pval, dval = card_value(player), card_value(dealer)
            em = discord.Embed(title="♦️ Blackjack — Result",
                               description=f"**{interaction.user.mention}**\nYour: {' | '.join(player)} (**{pval}**)\nDealer: {' | '.join(dealer)} (**{dval}**)\n\n{outcome}\nBalance: **{_fmt_currency(new_bal,curr)}**",
                               color=0xF1C40F if delta>0 else 0xE74C3C)
            await inter.response.edit_message(embed=em, view=self)
        @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
        async def hit(self, inter: discord.Interaction, _btn: discord.ui.Button):
            player.append(deck.pop()); pval = card_value(player)
            if pval > 21: return await self.finish(inter, f"💥 Bust! Lost **{_fmt_currency(self.current_bet,curr)}**.", -self.current_bet)
            em = discord.Embed(title="♦️ Blackjack", description=f"{interaction.user.mention}\nYour: {' | '.join(player)} (**{pval}**)\nDealer: {dealer[0]} ??\nBet: **{_fmt_currency(self.current_bet,curr)}**", color=0x2ECC71)
            await inter.response.edit_message(embed=em, view=self)
        @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
        async def stand(self, inter: discord.Interaction, _btn: discord.ui.Button):
            while card_value(dealer) < 17: dealer.append(deck.pop())
            pval, dval = card_value(player), card_value(dealer)
            if dval > 21 or pval > dval:
                win = int(round(self.current_bet * (2.0 - edge))); return await self.finish(inter, f"✅ You win **{_fmt_currency(win,curr)}**!", win)
            elif pval == dval:
                return await self.finish(inter, "➖ Push.", 0)
            else:
                return await self.finish(inter, f"❌ Dealer wins. Lost **{_fmt_currency(self.current_bet,curr)}**.", -self.current_bet)
        @discord.ui.button(label="Double", style=discord.ButtonStyle.success)
        async def double(self, inter: discord.Interaction, _btn: discord.ui.Button):
            if eco_get(inter.guild.id, inter.user.id) < self.current_bet: return await inter.response.send_message("Not enough balance to double.", ephemeral=True)
            self.current_bet *= 2; player.append(deck.pop())
            while card_value(dealer) < 17: dealer.append(deck.pop())
            pval, dval = card_value(player), card_value(dealer)
            if pval > 21: return await self.finish(inter, f"💥 Bust on double! Lost **{_fmt_currency(self.current_bet,curr)}**.", -self.current_bet)
            if dval > 21 or pval > dval:
                win = int(round(self.current_bet * (2.0 - edge))); return await self.finish(inter, f"✅ You win **{_fmt_currency(win,curr)}**!", win)
            elif pval == dval: return await self.finish(inter, "➖ Push.", 0)
            else: return await self.finish(inter, f"❌ Dealer wins. Lost **{_fmt_currency(self.current_bet,curr)}**.", -self.current_bet)

    start = discord.Embed(title="♦️ Blackjack", description=f"{interaction.user.mention}\nYour: {' | '.join(player)} (**{card_value(player)}**)\nDealer: {dealer[0]} ??\nBet: **{_fmt_currency(bet, curr)}**", color=0x2ECC71)
    await interaction.response.send_message(embed=start, view=BJView())

@tree.command(name="crash", description="Crash game — cash out before it explodes")
@in_gambling_channel()
@app_commands.describe(bet="bet amount")

async def crash_cmd(interaction: discord.Interaction, bet: int):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True):
        return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if not (min_bet <= bet <= max_bet):
        return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet:
        return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    MIN_CASHOUT = 1.25
    multiplier = 1.0
    bust_at = 1.05 + (random.random() ** 3.0) * 2.95
    class CrashView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=25)
            self.cashed = False
        @discord.ui.button(label="Cash Out", style=discord.ButtonStyle.success)
        async def cashout(self, inter: discord.Interaction, _btn: discord.ui.Button):
            nonlocal multiplier
            if self.cashed:
                return
            if multiplier < MIN_CASHOUT:
                return await inter.response.send_message(f"You can't cash out before **{MIN_CASHOUT:.2f}x**.", ephemeral=True)
            self.cashed = True
            profit_mult = max(0.0, multiplier - 1.0 - edge)
            win = int(round(bet * profit_mult))
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
            log_history(interaction.guild.id, interaction.user.id, "crash", bet, win)
            em = discord.Embed(title="🚀 Crash", description=(f"{interaction.user.mention} cashed at **{multiplier:.2f}x** — won **{_fmt_currency(win, curr)}**.\nBalance: **{_fmt_currency(new_bal, curr)}**"))
            await inter.response.edit_message(embed=em, view=None)
    view = CrashView()
    await interaction.response.send_message(embed=discord.Embed(title="🚀 Crash", description=(f"{interaction.user.mention} started a round. Rising... press **Cash Out** after **{MIN_CASHOUT:.2f}x**!")), view=view)
    msg = await interaction.original_response()
    while not view.cashed:
        await asyncio.sleep(0.9)
        if view.cashed:
            return
        multiplier *= 1 + random.uniform(0.06, 0.22)
        if multiplier >= bust_at:
            break
        await msg.edit(embed=discord.Embed(title="🚀 Crash", description=(f"**{interaction.user.mention}** Multiplier: **{multiplier:.2f}x**\nCash out before 💥 (min **{MIN_CASHOUT:.2f}x**)!")), view=view)
    if not view.cashed:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
        log_history(interaction.guild.id, interaction.user.id, "crash", bet, -bet)
        await msg.edit(embed=discord.Embed(title="💥 Crash", description=(f"{interaction.user.mention} — crashed at **{multiplier:.2f}x** and lost **{_fmt_currency(bet, curr)}**.\nBalance: **{_fmt_currency(new_bal, curr)}**")), view=None)

@tree.command(name="hilo", description="Hi/Lo — guess if the next card is higher or lower")
@in_gambling_channel()
@app_commands.describe(bet="bet amount")
async def hilo_cmd(interaction: discord.Interaction, bet: int):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True): return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if not (min_bet <= bet <= max_bet): return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet: return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    ranks = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]; order = {r:i+1 for i,r in enumerate(ranks)}
    def draw_card(): return random.choice(ranks) + random.choice(["♠","♥","♦","♣"])
    base = draw_card(); base_v = order[base[:-1] if base[:-1] in ("10",) else base[0]]
    class HiLoView(discord.ui.View):
        def __init__(self): super().__init__(timeout=30); self.done = False
        async def settle(self, inter: discord.Interaction, pick: str):
            if self.done: return
            self.done = True
            nxt = draw_card(); nxt_v = order[nxt[:-1] if nxt[:-1] in ("10",) else nxt[0]]
            result = "push"
            if nxt_v > base_v: result = "high"
            elif nxt_v < base_v: result = "low"
            if result == pick:
                win = int(round(bet * (2.0 - edge))); new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
                log_history(interaction.guild.id, interaction.user.id, "hilo", bet, win)
                txt = f"🃏 {interaction.user.mention} — **{base} → {nxt}** → **WIN** **{_fmt_currency(win,curr)}**. Bal: **{_fmt_currency(new_bal,curr)}**"
            elif result == "push":
                log_history(interaction.guild.id, interaction.user.id, "hilo", bet, 0)
                txt = f"🃏 {interaction.user.mention} — **{base} → {nxt}** → **PUSH**."
            else:
                new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
                log_history(interaction.guild.id, interaction.user.id, "hilo", bet, -bet)
                txt = f"🃏 {interaction.user.mention} — **{base} → {nxt}** → **LOSS** **{_fmt_currency(bet,curr)}**. Bal: **{_fmt_currency(new_bal,curr)}**"
            for c in self.children: c.disabled = True
            await inter.response.edit_message(content=txt, view=self)
        @discord.ui.button(label="Higher", style=discord.ButtonStyle.success)
        async def higher(self, inter: discord.Interaction, _btn: discord.ui.Button): await self.settle(inter, "high")
        @discord.ui.button(label="Lower", style=discord.ButtonStyle.danger)
        async def lower(self, inter: discord.Interaction, _btn: discord.ui.Button): await self.settle(inter, "low")
    await interaction.response.send_message(content=f"🃏 {interaction.user.mention} started **Hi/Lo** — base card: **{base}**. Pick Higher or Lower!", view=HiLoView())

# ---------- NEW: Guess the number ----------
@tree.command(name="guess", description="Guess the number (1..N) for big payout")
@in_gambling_channel()
@app_commands.describe(bet="bet amount", range_max="One of 3, 5, or 10", guess="Your guess between 1 and range_max")
async def guess_cmd(interaction: discord.Interaction, bet: int, range_max: int, guess: int):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True): return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    if range_max not in (3,5,10): return await interaction.response.send_message("range_max must be **3**, **5**, or **10**.", ephemeral=True)
    if not (1 <= guess <= range_max): return await interaction.response.send_message("Your guess must be within the chosen range.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if not (min_bet <= bet <= max_bet): return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet: return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    target = random.randint(1, range_max)
    if guess == target:
        payout = int(round(bet * (float(range_max) - edge)))  # ≈ fair r× minus edge
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, payout)
        log_history(interaction.guild.id, interaction.user.id, f"guess{range_max}", bet, payout)
        await interaction.response.send_message(f"🎯 {interaction.user.mention} guessed **{guess}** in **1..{range_max}** → target **{target}** — **WIN { _fmt_currency(payout,curr) }**. Bal: **{_fmt_currency(new_bal,curr)}**")
    else:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
        log_history(interaction.guild.id, interaction.user.id, f"guess{range_max}", bet, -bet)
        await interaction.response.send_message(f"🎯 {interaction.user.mention} guessed **{guess}** in **1..{range_max}** → target **{target}** — **LOSS {_fmt_currency(bet,curr)}**. Bal: **{_fmt_currency(new_bal,curr)}**")

# -------------------- Give / Leaderboard / Settings / Grant (unchanged) --------------------
@tree.command(name="give", description="Give currency to another user")
@in_gambling_channel()
@app_commands.describe(user="recipient", amount="amount to transfer")
async def give_cmd(interaction: discord.Interaction, user: discord.Member, amount: int):
    if user.bot or user.id == interaction.user.id: return await interaction.response.send_message("Invalid recipient.", ephemeral=True)
    if amount <= 0: return await interaction.response.send_message("Amount must be > 0.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < amount: return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    await eco_add(interaction.guild.id, interaction.user.id, -amount); new_bal = await eco_add(interaction.guild.id, user.id, amount)
    _,_,_,_,curr = _limits(interaction.guild.id)
    log_history(interaction.guild.id, interaction.user.id, "give", amount, -amount); log_history(interaction.guild.id, user.id, "give", amount, amount)
    await interaction.response.send_message(f"💸 {interaction.user.mention} transferred **{_fmt_currency(amount, curr)}** to {user.mention}. (Recipient balance: **{_fmt_currency(new_bal, curr)}**)")

@tree.command(name="leaderboard", description="Top 10 balances")
@in_gambling_channel()
async def leaderboard_cmd(interaction: discord.Interaction):
    g = str(interaction.guild.id); _,_,_,_,curr = _limits(interaction.guild.id)
    board = sorted(ECON["balances"].get(g, {}).items(), key=lambda kv: kv[1], reverse=True)[:10]
    lines = []
    for i, (uid, amt) in enumerate(board, 1):
        member = interaction.guild.get_member(int(uid)); name = member.mention if member else f"<@{uid}>"
        lines.append(f"**{i}.** {name} — {_fmt_currency(amt, curr)}")
    embed = discord.Embed(title="Leaderboard", description="\n".join(lines) or "_No balances yet_", color=0xE67E22)
    await interaction.response.send_message(embed=embed)

@tree.command(name="gambling_settings", description="Admin: configure gambling settings")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(enabled="Enable/disable gambling", currency="Currency symbol", min_bet="Minimum bet", max_bet="Maximum bet",
                       house_edge="House edge (2 or 0.02 = 2%)", daily="Daily payout", channel="Restrict to this channel",
                       clear_channel="Clear channel restriction", banker_role="Role allowed to grant coins", clear_banker_role="Clear banker role")
async def gambling_settings_cmd(interaction: discord.Interaction, enabled: Optional[bool]=None, currency: Optional[str]=None,
                                min_bet: Optional[int]=None, max_bet: Optional[int]=None, house_edge: Optional[float]=None,
                                daily: Optional[int]=None, channel: Optional[discord.TextChannel]=None, clear_channel: Optional[bool]=None,
                                banker_role: Optional[discord.Role]=None, clear_banker_role: Optional[bool]=None):
    if enabled is not None: set_guild_setting(interaction.guild.id, "GAMBLING_ENABLED", bool(enabled))
    if currency is not None: set_guild_setting(interaction.guild.id, "CURRENCY", currency[:3])
    if min_bet is not None: set_guild_setting(interaction.guild.id, "MIN_BET", int(min_bet))
    if max_bet is not None: set_guild_setting(interaction.guild.id, "MAX_BET", int(max_bet))
    if house_edge is not None:
        edge = house_edge if house_edge < 1 else (house_edge/100.0); set_guild_setting(interaction.guild.id, "HOUSE_EDGE", float(edge))
    if daily is not None: set_guild_setting(interaction.guild.id, "DAILY_AMOUNT", int(daily))
    if channel is not None: set_guild_setting(interaction.guild.id, "GAMBLING_CHANNEL_ID", int(channel.id))
    if clear_channel: set_guild_setting(interaction.guild.id, "GAMBLING_CHANNEL_ID", None)
    if banker_role is not None: set_guild_setting(interaction.guild.id, "BANKER_ROLE_ID", int(banker_role.id))
    if clear_banker_role: set_guild_setting(interaction.guild.id, "BANKER_ROLE_ID", None)
    min_bet, max_bet, edge, daily_amt, curr = _limits(interaction.guild.id)
    chan_id = _get_gambling_channel_id(interaction.guild.id); chan_ref = interaction.guild.get_channel(chan_id) if chan_id else None
    chan_txt = chan_ref.mention if chan_ref else "Any channel"
    br_id = _get_banker_role_id(interaction.guild.id); br_ref = interaction.guild.get_role(br_id) if br_id else None
    br_txt = br_ref.mention if br_ref else "Manage Server only"
    await interaction.response.send_message(f"Settings for **{interaction.guild.name}**:\nEnabled: {guild_setting(interaction.guild.id,'GAMBLING_ENABLED',True)}\nCurrency: {curr} | Min: {min_bet} | Max: {max_bet}\nEdge: {edge*100:.1f}% | Daily: {daily_amt}\nGambling channel: {chan_txt}\nBanker role: {br_txt}", ephemeral=True)

@tree.command(name="grant", description="(Admin/Banker) Grant coins to a user")
@in_gambling_channel()
@app_commands.describe(user="Recipient", amount="Amount to add (positive only)", reason="Optional note")
async def grant_cmd(interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, 100000000], reason: Optional[str]=None):
    if not interaction.guild or user.bot: return await interaction.response.send_message("Invalid recipient.", ephemeral=True)
    if not user_is_banker(interaction): return await interaction.response.send_message("You need Manage Server or the configured Banker role.", ephemeral=True)
    new_bal = await eco_add(interaction.guild.id, user.id, int(amount)); _,_,_,_,curr = _limits(interaction.guild.id)
    note = f" Reason: {reason}" if reason else ""; log_history(interaction.guild.id, interaction.user.id, "grant", int(amount), -int(amount))
    log_history(interaction.guild.id, user.id, "grant", int(amount), int(amount))
    await interaction.response.send_message(f"Added **{_fmt_currency(int(amount), curr)}** to {user.mention}. New balance: **{_fmt_currency(new_bal, curr)}**.{note}", ephemeral=True)

# -------------------- Editable Redeem System --------------------
def _redeem_bucket(guild_id: int) -> Dict[str, dict]:
    return ECON.setdefault("redeem", {}).setdefault(str(guild_id), {})

@tree.command(name="redeem", description="Redeem a code for currency")
async def redeem_cmd(interaction: discord.Interaction, code: str):
    code = code.strip()
    bucket = _redeem_bucket(interaction.guild.id)
    if code not in bucket:
        return await interaction.response.send_message("❌ Invalid or expired code.", ephemeral=True)
    entry = bucket[code]
    now = _now_ts()
    if entry.get("disabled"): return await interaction.response.send_message("❌ This code is disabled.", ephemeral=True)
    exp = int(entry.get("expires", 0))
    if exp and now > exp: return await interaction.response.send_message("⏰ This code has expired.", ephemeral=True)
    used_by = set(entry.setdefault("claimed_by", []))
    if str(interaction.user.id) in used_by: return await interaction.response.send_message("You already redeemed this code.", ephemeral=True)
    if int(entry.get("uses", 0)) >= int(entry.get("max_uses", 1)):
        return await interaction.response.send_message("This code has reached its max uses.", ephemeral=True)
    # apply
    amount = int(entry.get("amount", 0))
    new_bal = await eco_add(interaction.guild.id, interaction.user.id, amount)
    entry["uses"] = int(entry.get("uses", 0)) + 1
    entry["claimed_by"] = list(used_by | {str(interaction.user.id)})
    _save_econ()
    _,_,_,_,curr = _limits(interaction.guild.id)
    note = f" — {entry.get('note','')}" if entry.get("note") else ""
    await interaction.response.send_message(f"✅ Redeemed **{code}** for **{_fmt_currency(amount, curr)}**{note}. New balance: **{_fmt_currency(new_bal, curr)}**", ephemeral=True)

# Admin/banker management
redeemadmin = app_commands.Group(name="redeemadmin", description="Manage redeem codes")

@redeemadmin.command(name="create", description="Create a redeem code")
@banker_only()
@app_commands.describe(code="The code text (case-sensitive)", amount="Currency amount", max_uses="Max uses", expires_minutes="Expires in N minutes (0=no expiry)", note="Optional note")
async def redeem_create(interaction: discord.Interaction, code: str, amount: int, max_uses: int = 1, expires_minutes: Optional[int] = None, note: Optional[str] = None):
    bucket = _redeem_bucket(interaction.guild.id)
    if code in bucket: return await interaction.response.send_message("Code already exists. Use /redeemadmin edit.", ephemeral=True)
    exp = 0
    if expires_minutes and int(expires_minutes) > 0:
        exp = _now_ts() + int(expires_minutes) * 60
    bucket[code] = {"amount": int(amount), "max_uses": int(max_uses), "uses": 0, "expires": int(exp), "note": note or "", "claimed_by": [], "disabled": False}
    _save_econ()
    when = f"<t:{exp}:R>" if exp else "never"
    await interaction.response.send_message(f"✅ Created code **{code}** → amount {amount}, max_uses {max_uses}, expires {when}.", ephemeral=True)

@redeemadmin.command(name="edit", description="Edit a redeem code")
@banker_only()
@app_commands.describe(code="Existing code", amount="New amount", max_uses="New max uses", expires_minutes="New expiry (minutes, 0=clear)", note="New note", disable="Disable this code")
async def redeem_edit(interaction: discord.Interaction, code: str, amount: Optional[int] = None, max_uses: Optional[int] = None, expires_minutes: Optional[int] = None, note: Optional[str] = None, disable: Optional[bool] = None):
    bucket = _redeem_bucket(interaction.guild.id)
    if code not in bucket: return await interaction.response.send_message("Unknown code.", ephemeral=True)
    e = bucket[code]
    if amount is not None: e["amount"] = int(amount)
    if max_uses is not None: e["max_uses"] = int(max_uses)
    if expires_minutes is not None:
        e["expires"] = 0 if int(expires_minutes) == 0 else _now_ts() + int(expires_minutes)*60
    if note is not None: e["note"] = note
    if disable is not None: e["disabled"] = bool(disable)
    _save_econ()
    when = f"<t:{e['expires']}:R>" if e.get("expires") else "never"
    await interaction.response.send_message(f"✏️ Updated **{code}** — amount {e['amount']}, uses {e.get('uses',0)}/{e.get('max_uses',1)}, expires {when}, disabled {e.get('disabled',False)}.", ephemeral=True)

@redeemadmin.command(name="delete", description="Delete a redeem code")
@banker_only()
async def redeem_delete(interaction: discord.Interaction, code: str):
    bucket = _redeem_bucket(interaction.guild.id)
    if bucket.pop(code, None) is None: return await interaction.response.send_message("Unknown code.", ephemeral=True)
    _save_econ()
    await interaction.response.send_message(f"🗑️ Deleted code **{code}**.", ephemeral=True)

@redeemadmin.command(name="list", description="List current redeem codes (public)")
@banker_only()
async def redeem_list(interaction: discord.Interaction):
    bucket = _redeem_bucket(interaction.guild.id)
    if not bucket:
        embed = discord.Embed(
            title="🎟️ Redeem Codes",
            description="_No codes available_",
            color=0x808080
        )
        return await interaction.response.send_message(embed=embed)

    codes = sorted(bucket.items(), key=lambda kv: kv[0])
    images = list_unit_images_one_panel()
    has_images = bool(images)

    CHUNK = 10
    for i in range(0, len(codes), CHUNK):
        batch = codes[i:i+CHUNK]
        embeds, files = [], []
        now = _now_ts()

        for j, (code, e) in enumerate(batch):
            disabled = bool(e.get("disabled", False))
            exp_val = int(e.get("expires", 0))
            expired = bool(exp_val and now > exp_val)
            uses = int(e.get("uses", 0))
            max_uses = int(e.get("max_uses", 1))
            rem = max(0, max_uses - uses)

            if disabled or expired or rem == 0:
                color = 0x7f8c8d
                status = "⛔ Disabled" if disabled else ("⏰ Expired" if expired else "☑️ Depleted")
            else:
                color = 0x2ecc71
                status = "✅ Active"

            exp_txt = f"<t:{exp_val}:R>" if exp_val else "never"

            desc = "\n".join([
                f"**Status:** {status}",
                f"**Amount:** {e.get('amount', 0)}",
                f"**Uses:** {uses}/{max_uses} (**{rem}** left)",
                f"**Expires:** {exp_txt}",
            ])

            em = discord.Embed(title=f"🎟️ {code}", color=color, description=desc)

            note = (e.get("note") or "").strip()
            if note:
                em.add_field(name="Note", value=note, inline=False)

            if has_images:
                path_img = images[j % len(images)]
                with open(path_img, "rb") as f_img:
                    filedata = f_img.read()
                fname = f"redeem_{i+j}_{os.path.basename(path_img)}"
                files.append(discord.File(io.BytesIO(filedata), filename=fname))
                em.set_thumbnail(url=f"attachment://{fname}")

            embeds.append(em)

        if i == 0:
            await interaction.response.send_message(embeds=embeds, files=files)
        else:
            await interaction.followup.send(embeds=embeds, files=files)
# -------------------- Admin Panel (owner) & mystats (same as before) --------------------
@tree.command(name="adminpanel", description="Owner-only admin panel (gambling controls)")
@owner_only()
async def adminpanel_cmd(interaction: discord.Interaction):
    g = str(interaction.guild.id)
    min_bet, max_bet, edge, daily_amt, curr = _limits(interaction.guild.id)
    chan_id = _get_gambling_channel_id(interaction.guild.id); chan_txt = interaction.guild.get_channel(chan_id).mention if chan_id else "Any channel"
    enabled = guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True)
    embed = discord.Embed(title=f"Admin Panel — {interaction.guild.name}",
                          description=(f"**Gambling**: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
                                       f"**Currency**: {curr}\n**Min/Max Bet**: {min_bet}/{max_bet}\n"
                                       f"**House Edge**: {edge*100:.1f}%\n**Daily**: {daily_amt}\n**Gambling Channel**: {chan_txt}\n"),
                          color=0xFF0066)
    class LimitsModal(discord.ui.Modal, title="Edit Gambling Settings"):
        def __init__(self):
            super().__init__()
            self.currency = discord.ui.TextInput(label="Currency (1-3 chars)", default=curr, required=False, max_length=3)
            self.min_bet_in = discord.ui.TextInput(label="Min Bet", default=str(min_bet), required=False)
            self.max_bet_in = discord.ui.TextInput(label="Max Bet", default=str(max_bet), required=False)
            self.edge_in = discord.ui.TextInput(label="House Edge (%)", default=f"{edge*100:.2f}", required=False)
            self.daily_in = discord.ui.TextInput(label="Daily Amount", default=str(daily_amt), required=False)
            self.add_item(self.currency); self.add_item(self.min_bet_in); self.add_item(self.max_bet_in); self.add_item(self.edge_in); self.add_item(self.daily_in)
        async def on_submit(self, inter: discord.Interaction):
            try:
                if str(self.currency.value).strip(): set_guild_setting(inter.guild.id, "CURRENCY", str(self.currency.value)[:3])
                if str(self.min_bet_in.value).strip(): set_guild_setting(inter.guild.id, "MIN_BET", int(self.min_bet_in.value))
                if str(self.max_bet_in.value).strip(): set_guild_setting(inter.guild.id, "MAX_BET", int(self.max_bet_in.value))
                if str(self.edge_in.value).strip():
                    val = float(self.edge_in.value); set_guild_setting(inter.guild.id, "HOUSE_EDGE", val/100.0 if val >= 1 else val)
                if str(self.daily_in.value).strip(): set_guild_setting(inter.guild.id, "DAILY_AMOUNT", int(self.daily_in.value))
                await inter.response.send_message("✅ Settings updated.", ephemeral=True)
            except Exception as e:
                await inter.response.send_message(f"❌ Failed to update: {e}", ephemeral=True)
    class PanelView(discord.ui.View):
        def __init__(self): super().__init__(timeout=180)
        @discord.ui.button(label="Toggle Gambling", style=discord.ButtonStyle.danger)
        async def toggle(self, inter: discord.Interaction, _btn: discord.ui.Button):
            cur = guild_setting(inter.guild.id, "GAMBLING_ENABLED", True); set_guild_setting(inter.guild.id, "GAMBLING_ENABLED", not cur)
            await inter.response.send_message(f"Gambling now **{'enabled' if not cur else 'disabled'}**.", ephemeral=True)
        @discord.ui.button(label="Edit Settings", style=discord.ButtonStyle.primary)
        async def edit(self, inter: discord.Interaction, _btn: discord.ui.Button): await inter.response.send_modal(LimitsModal())
        @discord.ui.button(label="Set This Channel", style=discord.ButtonStyle.secondary)
        async def setchan(self, inter: discord.Interaction, _btn: discord.ui.Button):
            set_guild_setting(inter.guild.id, "GAMBLING_CHANNEL_ID", inter.channel.id)
            await inter.response.send_message(f"Gambling channel set to {inter.channel.mention}.", ephemeral=True)
        @discord.ui.button(label="Clear Channel Restriction", style=discord.ButtonStyle.secondary)
        async def clearchan(self, inter: discord.Interaction, _btn: discord.ui.Button):
            set_guild_setting(inter.guild.id, "GAMBLING_CHANNEL_ID", None); await inter.response.send_message("Gambling channel restriction cleared.", ephemeral=True)
        @discord.ui.button(label="Reset Leaderboard", style=discord.ButtonStyle.secondary)
        async def resetlb(self, inter: discord.Interaction, _btn: discord.ui.Button):
            ECON.setdefault("balances", {})[g] = {}; _save_econ(); await inter.response.send_message("Leaderboard reset.", ephemeral=True)
        @discord.ui.button(label="View Recent Bets", style=discord.ButtonStyle.success)
        async def viewhist(self, inter: discord.Interaction, _btn: discord.ui.Button):
            ECON.setdefault("history", {}).setdefault(g, {}); items = []
            for uid, arr in ECON["history"][g].items():
                for entry in arr[-10:]: items.append((entry["t"], uid, entry))
            items.sort(key=lambda x: x[0], reverse=True)
            hist_lines = []
            for t, uid, e in items[:15]:
                member = inter.guild.get_member(int(uid)); name = member.display_name if member else f"User {uid}"
                sign = "+" if e["result"] >= 0 else "-"
                hist_lines.append(f"<t:{t}:R> — {name}: {e['game']} bet {e['bet']} ⇒ {sign}{abs(e['result'])}")
            await inter.response.send_message("\n".join(hist_lines) or "_No recent bets_", ephemeral=True)
    await interaction.response.send_message(embed=embed, view=PanelView(), ephemeral=True)

@tree.command(name="mystats", description="Show your gambling stats")
async def mystats_cmd(interaction: discord.Interaction):
    g, u = str(interaction.guild.id), str(interaction.user.id)
    s = ECON.setdefault("stats", {}).setdefault(g, {}).setdefault(u, {"bets":0,"won":0,"lost":0,"biggest":0})
    _,_,_,_,curr = _limits(interaction.guild.id); net = s["won"] - s["lost"]
    em = discord.Embed(title=f"{interaction.user.display_name} — Stats",
                       description=(f"🎲 **Bets**: {s['bets']}\n💰 **Won**: {_fmt_currency(s['won'], curr)}\n"
                                    f"💸 **Lost**: {_fmt_currency(s['lost'], curr)}\n📈 **Net**: {_fmt_currency(net, curr)}\n"
                                    f"🏆 **Biggest Win**: {_fmt_currency(s['biggest'], curr)}"),
                       color=0x9B59B6)
    await interaction.response.send_message(embed=em, ephemeral=True)



# -------------------- Casino GUI --------------------
class SetBetModal(discord.ui.Modal, title="Set Casino Bet"):
    bet_input = discord.ui.TextInput(label="Bet amount", placeholder="Enter a number", required=True)
    def __init__(self, view_ref):
        super().__init__()
        self.view_ref = view_ref
        self.add_item(self.bet_input)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(str(self.bet_input.value).replace(",", "").strip())
            min_bet, max_bet, _, _, _ = _limits(interaction.guild.id)
            if val < min_bet or val > max_bet:
                return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
            self.view_ref.bet = val
            await interaction.response.edit_message(embed=self.view_ref.render_embed(), view=self.view_ref)
        except Exception:
            await interaction.response.send_message("Invalid bet.", ephemeral=True)

class GuessModal(discord.ui.Modal, title="Guess the Number"):
    range_input = discord.ui.TextInput(label="Range (3, 5, or 10)", placeholder="5", required=True, max_length=2)
    guess_input = discord.ui.TextInput(label="Your guess", placeholder="3", required=True, max_length=3)
    def __init__(self, view_ref):
        super().__init__()
        self.view_ref = view_ref
        self.add_item(self.range_input)
        self.add_item(self.guess_input)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            rmax = int(str(self.range_input.value).strip())
            gnum = int(str(self.guess_input.value).strip())
        except Exception:
            return await interaction.response.send_message("Enter valid numbers.", ephemeral=True)
        await self.view_ref.play_guess(interaction, rmax, gnum)

class RouletteNumberModal(discord.ui.Modal, title="Roulette Number Bet"):
    num_input = discord.ui.TextInput(label="Number (0-36)", placeholder="17", required=True, max_length=2)
    def __init__(self, view_ref):
        super().__init__()
        self.view_ref = view_ref
        self.add_item(self.num_input)
    async def on_submit(self, interaction: discord.Interaction):
        v = str(self.num_input.value).strip()
        if not v.isdigit():
            return await interaction.response.send_message("Enter a number 0..36.", ephemeral=True)
        await self.view_ref.play_roulette_number(interaction, int(v))


class CasinoView(discord.ui.View):
    def __init__(self, opener_id: int, guild_id: int, initial_bet: int):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.per_user_bet: dict[int, int] = {opener_id: max(0, int(initial_bet))}

    # --- utilities ---
    def get_bet(self, user_id: int) -> int:
        min_bet, max_bet, _, _, _ = _limits(self.guild_id)
        return max(min_bet, min(self.per_user_bet.get(user_id, min_bet), max_bet))

    def set_bet(self, user_id: int, value: int) -> int:
        min_bet, max_bet, _, _, _ = _limits(self.guild_id)
        v = max(min_bet, min(int(value), max_bet))
        self.per_user_bet[user_id] = v
        return v

    
def render_embed(self) -> discord.Embed:
    min_bet, max_bet, edge, _, curr = _limits(self.guild_id)
    desc_lines = [
        "**How to play:** Use the buttons below — no need to type commands.",
        "**Bets:** Everyone controls their own bet. Default = min bet.",
        f"**Limits:** Min {min_bet} {curr}, Max {max_bet} {curr}",
        "",
        "Tip: Press **Set Bet** to choose your bet. Results & balances post publicly."
    ]
    em = discord.Embed(title="🎰 Casino", description="\n".join(desc_lines), color=0x00A38B)
    em.set_footer(text="Use /gambling_settings to tune currency and limits.")
    return em


    async def _guard(self, interaction: discord.Interaction, bet: int) -> bool:
        if not guild_setting(self.guild_id, "GAMBLING_ENABLED", True):
            await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
            return False
        min_bet, max_bet, _, _, _ = _limits(self.guild_id)
        if bet < min_bet or bet > max_bet:
            await interaction.response.send_message(f"Set a bet between {min_bet} and {max_bet} with **Set Bet**.", ephemeral=True)
            return False
        if eco_get(self.guild_id, interaction.user.id) < bet:
            await interaction.response.send_message("Insufficient balance for your current bet.", ephemeral=True)
            return False
        return True

    # --- bet controls ---
    @discord.ui.button(label="Set Bet", style=discord.ButtonStyle.primary, row=0)
    async def set_bet_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        await interaction.response.send_modal(SetBetModal(self))

    @discord.ui.button(label="+10", style=discord.ButtonStyle.secondary, row=0)
    async def plus10(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        v = self.set_bet(interaction.user.id, self.get_bet(interaction.user.id) + 10)
        await interaction.response.send_message(f"Your bet is now **{v:,}**.", ephemeral=True)

    @discord.ui.button(label="+100", style=discord.ButtonStyle.secondary, row=0)
    async def plus100(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        v = self.set_bet(interaction.user.id, self.get_bet(interaction.user.id) + 100)
        await interaction.response.send_message(f"Your bet is now **{v:,}**.", ephemeral=True)

    @discord.ui.button(label="Clear", style=discord.ButtonStyle.secondary, row=0)
    async def clear_bet(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        min_bet, _, _, _, _ = _limits(self.guild_id)
        self.per_user_bet[interaction.user.id] = min_bet
        await interaction.response.send_message(f"Your bet reset to **{min_bet:,}**.", ephemeral=True)

    # --- coinflip ---
    @discord.ui.button(label="Coinflip: Heads", style=discord.ButtonStyle.success, row=1)
    async def cf_heads(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
        res = random.choice(("heads", "tails"))
        if res == "heads":
            win = int(round(bet * (2.0 - edge)))
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
            log_history(interaction.guild.id, interaction.user.id, "coinflip", bet, win)
            await interaction.response.send_message(f"🪙 **HEADS!** {interaction.user.mention} won **{_fmt_currency(win,curr)}**. New balance: **{_fmt_currency(new_bal,curr)}**.")
        else:
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
            log_history(interaction.guild.id, interaction.user.id, "coinflip", bet, -bet)
            await interaction.response.send_message(f"🪙 **TAILS.** {interaction.user.mention} lost **{_fmt_currency(bet,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**.")

    @discord.ui.button(label="Coinflip: Tails", style=discord.ButtonStyle.danger, row=1)
    async def cf_tails(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
        res = random.choice(("heads", "tails"))
        if res == "tails":
            win = int(round(bet * (2.0 - edge)))
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
            log_history(interaction.guild.id, interaction.user.id, "coinflip", bet, win)
            await interaction.response.send_message(f"🪙 **TAILS!** {interaction.user.mention} won **{_fmt_currency(win,curr)}**. New balance: **{_fmt_currency(new_bal,curr)}**.")
        else:
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
            log_history(interaction.guild.id, interaction.user.id, "coinflip", bet, -bet)
            await interaction.response.send_message(f"🪙 **HEADS.** {interaction.user.mention} lost **{_fmt_currency(bet,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**.")

    # --- slots ---
    @discord.ui.button(label="Slots", style=discord.ButtonStyle.primary, row=1)
    async def slots_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
        reels = [random.choice(SLOT_EMOJI) for _ in range(3)]
        text = " | ".join(reels); win = 0
        if len(set(reels)) == 1: win = int(round(bet * (9.0 - edge)))
        elif reels[0] == reels[1] or reels[1] == reels[2]: win = int(round(bet * (2.0 - edge)))
        if win > 0:
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
            log_history(interaction.guild.id, interaction.user.id, "slots", bet, win)
            await interaction.response.send_message(f"{interaction.user.mention} rolled **{text}** — won **{_fmt_currency(win, curr)}**! New balance: **{_fmt_currency(new_bal, curr)}**")
        else:
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
            log_history(interaction.guild.id, interaction.user.id, "slots", bet, -bet)
            await interaction.response.send_message(f"{interaction.user.mention} rolled **{text}** — no win. Lost **{_fmt_currency(bet, curr)}** — Balance: **{_fmt_currency(new_bal, curr)}**")

    # --- dice ---
    @discord.ui.button(label="Dice: High", style=discord.ButtonStyle.success, row=2)
    async def dice_high(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
        roll = random.randint(1,6) + random.randint(1,6)
        if roll >= 8:
            win = int(round(bet * (2.0 - edge)))
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
            log_history(interaction.guild.id, interaction.user.id, "dice", bet, win)
            await interaction.response.send_message(f"🎲 {interaction.user.mention} rolled **{roll}** (High) — won **{_fmt_currency(win,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")
        else:
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
            log_history(interaction.guild.id, interaction.user.id, "dice", bet, -bet)
            await interaction.response.send_message(f"🎲 {interaction.user.mention} rolled **{roll}** (High) — lost **{_fmt_currency(bet,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")

    @discord.ui.button(label="Dice: Low", style=discord.ButtonStyle.danger, row=2)
    async def dice_low(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
        roll = random.randint(1,6) + random.randint(1,6)
        if roll <= 6:
            win = int(round(bet * (2.0 - edge)))
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
            log_history(interaction.guild.id, interaction.user.id, "dice", bet, win)
            await interaction.response.send_message(f"🎲 {interaction.user.mention} rolled **{roll}** (Low) — won **{_fmt_currency(win,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")
        else:
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
            log_history(interaction.guild.id, interaction.user.id, "dice", bet, -bet)
            await interaction.response.send_message(f"🎲 {interaction.user.mention} rolled **{roll}** (Low) — lost **{_fmt_currency(bet,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")

    # --- roulette ---
    @discord.ui.button(label="Roulette: Red", style=discord.ButtonStyle.danger, row=3)
    async def roul_red(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        REDS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
        min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
        num = random.randint(0,36); color = "red" if num in REDS else ("green" if num == 0 else "black")
        if color == "red":
            win = int(round(bet * (2.0 - edge)))
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
            log_history(interaction.guild.id, interaction.user.id, "roulette", bet, win)
            await interaction.response.send_message(f"🎡 {interaction.user.mention} → {num} ({color}) — won **{_fmt_currency(win,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")
        else:
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
            log_history(interaction.guild.id, interaction.user.id, "roulette", bet, -bet)
            await interaction.response.send_message(f"🎡 {interaction.user.mention} → {num} ({color}) — lost **{_fmt_currency(bet,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")

    @discord.ui.button(label="Roulette: Black", style=discord.ButtonStyle.secondary, row=3)
    async def roul_black(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        REDS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
        min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
        num = random.randint(0,36); color = "red" if num in REDS else ("green" if num == 0 else "black")
        if color == "black":
            win = int(round(bet * (2.0 - edge)))
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
            log_history(interaction.guild.id, interaction.user.id, "roulette", bet, win)
            await interaction.response.send_message(f"🎡 {interaction.user.mention} → {num} ({color}) — won **{_fmt_currency(win,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")
        else:
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
            log_history(interaction.guild.id, interaction.user.id, "roulette", bet, -bet)
            await interaction.response.send_message(f"🎡 {interaction.user.mention} → {num} ({color}) — lost **{_fmt_currency(bet,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")

    @discord.ui.button(label="Roulette: Number", style=discord.ButtonStyle.primary, row=3)
    async def roul_number(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        await interaction.response.send_modal(RouletteNumberModal(self))

    async def play_roulette_number(self, interaction: discord.Interaction, number: int):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        if number < 0 or number > 36:
            return await interaction.response.send_message("Number must be 0..36.", ephemeral=True)
        REDS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
        min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
        num = random.randint(0,36); color = "red" if num in REDS else ("green" if num == 0 else "black")
        if num == number:
            win = int(round(bet * (35.0 - edge)))
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
            log_history(interaction.guild.id, interaction.user.id, "roulette", bet, win)
            await interaction.response.send_message(f"🎡 {interaction.user.mention} → **{num}** ({color}) — exact hit! **{_fmt_currency(win,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")
        else:
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
            log_history(interaction.guild.id, interaction.user.id, "roulette", bet, -bet)
            await interaction.response.send_message(f"🎡 {interaction.user.mention} → **{num}** ({color}) — miss. Lost **{_fmt_currency(bet,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")

    # --- blackjack/crash/hilo/guess reuse handlers ---
    @discord.ui.button(label="Blackjack", style=discord.ButtonStyle.success, row=4)
    async def blackjack_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        await blackjack_cmd.callback(interaction, bet=bet)  # type: ignore

    @discord.ui.button(label="Crash", style=discord.ButtonStyle.danger, row=4)
    async def crash_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        await crash_cmd.callback(interaction, bet=bet)  # type: ignore

    @discord.ui.button(label="Hi/Lo", style=discord.ButtonStyle.primary, row=4)
    async def hilo_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        await hilo_cmd.callback(interaction, bet=bet)  # type: ignore

    @discord.ui.button(label="Guess #", style=discord.ButtonStyle.secondary, row=4)
    async def guess_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button):
        await interaction.response.send_modal(GuessModal(self))

    async def play_guess(self, interaction: discord.Interaction, range_max: int, guess: int):
        bet = self.get_bet(interaction.user.id)
        if not await self._guard(interaction, bet): return
        if range_max not in (3,5,10):
            return await interaction.response.send_message("Range must be 3, 5, or 10.", ephemeral=True)
        if not (1 <= guess <= range_max):
            return await interaction.response.send_message("Guess must be within range.", ephemeral=True)
        min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
        target = random.randint(1, range_max)
        if guess == target:
            payout = int(round(bet * (float(range_max) - edge)))
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, payout)
            log_history(interaction.guild.id, interaction.user.id, f"guess{range_max}", bet, payout)
            await interaction.response.send_message(f"🎯 {interaction.user.mention} guessed **{guess}** in **1..{range_max}** → target **{target}** — **WIN { _fmt_currency(payout,curr) }**. Bal: **{_fmt_currency(new_bal,curr)}**")
        else:
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
            log_history(interaction.guild.id, interaction.user.id, f"guess{range_max}", bet, -bet)
            await interaction.response.send_message(f"🎯 {interaction.user.mention} guessed **{guess}** in **1..{range_max}** → target **{target}** — **LOSS {_fmt_currency(bet,curr)}**. Bal: **{_fmt_currency(new_bal,curr)}**")



# --- paging ---
@discord.ui.button(label="⟨ Prev", style=discord.ButtonStyle.secondary, row=0)
async def prev_page(self, interaction: discord.Interaction, _btn: discord.ui.Button):
    embed = self.render_embed()
    await interaction.response.edit_message(embed=embed, view=self)

@discord.ui.button(label="Next ⟩", style=discord.ButtonStyle.secondary, row=4)
async def next_page(self, interaction: discord.Interaction, _btn: discord.ui.Button):
    embed = self.render_embed()
    await interaction.response.edit_message(embed=embed, view=self)


@tree.command(name="casino", description="Show all gambling slash commands")
@in_gambling_channel()
async def casino_cmd(interaction: discord.Interaction):
    """Lightweight /casino: lists game commands so it never times out."""
    cmds = [
        ("/blackjack", "Play 21 vs the dealer"),
        ("/coinflip", "Bet on heads or tails"),
        ("/crash", "Cash out before it explodes"),
        ("/roulette", "Red/Black/Number or 0-36"),
        ("/slots", "Spin the slot machine"),
        ("/guess", "Guess the number"),
        ("/hilo", "Higher or Lower"),
        ("/dice", "High/Low dice"),
        ("/daily", "Claim your daily reward"),
        ("/balance", "Check your balance"),
        ("/leaderboard", "Top balances"),
        ("/give", "Send coins to someone"),
    ]
    lines = "\n".join(f"**{c}** — {d}" for c, d in cmds)
    em = discord.Embed(title="🎰 Casino — Commands", description=f"Use these commands to play:\n\n{lines}", color=0x00A38B)
    await interaction.response.send_message(embed=em, ephemeral=False)
@casinoadmin.command(name="images_add", description="Download an image URL into the casino banner folder")
@banker_only()
@app_commands.describe(url="Direct image URL (.png/.jpg)")
async def casino_images_add(interaction: discord.Interaction, url: str):
    os.makedirs(CASINO_ASSETS_DIR, exist_ok=True)
    fname = f"web_{int(time.time())}.png"
    dest = os.path.join(CASINO_ASSETS_DIR, fname)
    ok = _download_image_sync(url, dest)
    if ok:
        await interaction.response.send_message(f"✅ Saved **{fname}**", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Failed to download. Check the URL.", ephemeral=True)

@casinoadmin.command(name="images_clear", description="Clear the casino banner folder")
@banker_only()
async def casino_images_clear(interaction: discord.Interaction):
    if not os.path.isdir(CASINO_ASSETS_DIR):
        return await interaction.response.send_message("Folder not found.", ephemeral=True)
    n = 0
    for fn in os.listdir(CASINO_ASSETS_DIR):
        try:
            os.remove(os.path.join(CASINO_ASSETS_DIR, fn))
            n += 1
        except Exception:
            pass
    await interaction.response.send_message(f"🧹 Cleared {n} files.", ephemeral=True)

@casinoadmin.command(name="images_list", description="List banner images")
@banker_only()
async def casino_images_list(interaction: discord.Interaction):
    if not os.path.isdir(CASINO_ASSETS_DIR):
        return await interaction.response.send_message("_No folder_", ephemeral=True)
    files = [fn for fn in os.listdir(CASINO_ASSETS_DIR) if fn.lower().endswith(('.png','.jpg','.jpeg'))]
    if not files:
        return await interaction.response.send_message("_No images stored_", ephemeral=True)
    txt = "\n".join(f"- {fn}" for fn in files[:40])
    await interaction.response.send_message(f"**{len(files)}** image(s):\n{txt}", ephemeral=True)


# -------------------- Ready / sync --------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"🔧 Slash commands synced: {len(synced)}")
    except Exception as e:
        print("⚠️ Slash sync failed:", e)


# -------------------- Mini-game: Unit Quiz --------------------
@tree.command(name="unitquiz", description="Guess the unit from a picture (uses your units_assets and units.txt)")
@in_gambling_channel()
@app_commands.describe(bet="Bet amount")
async def unitquiz_cmd(interaction: discord.Interaction, bet: int):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True):
        return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    units = read_units_txt()
    if not units:
        return await interaction.response.send_message("No units in **units.txt**.", ephemeral=True)
    import random, os, io
    candidates = [u for u in units if asset_path_for(u, 1)]
    if not candidates:
        return await interaction.response.send_message(f"No images ending with '1.png' found in `{ASSETS_DIR}`.", ephemeral=True)
    correct = random.choice(candidates)
    correct_path = asset_path_for(correct, 1)
    others = [u for u in units if u != correct]
    random.shuffle(others)
    choices = [correct] + others[:3]
    random.shuffle(choices)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if not (min_bet <= bet <= max_bet):
        return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet:
        return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    file = None
    try:
        with open(correct_path, "rb") as f:
            imgdata = f.read()
        fname = "unitquiz.png"
        file = discord.File(io.BytesIO(imgdata), filename=fname)
        image_url = f"attachment://{fname}"
    except Exception:
        file = None
        image_url = None

    class QuizView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)
            self.answered = False
            for label in choices:
                self.add_item(self.UnitButton(label=label))

        class UnitButton(discord.ui.Button):
            def __init__(self, label: str):
                super().__init__(label=label, style=discord.ButtonStyle.secondary)
            async def callback(self, inter: discord.Interaction):
                view: QuizView = self.view  # type: ignore
                if not inter.user or inter.user.id != interaction.user.id:
                    return await inter.response.send_message("Only the player who started this game can answer.", ephemeral=True)
                if view.answered:
                    return
                view.answered = True
                picked = self.label
                win_delta = 0
                if picked == correct:
                    payout = max(0, int(round(bet * (3.0 - edge))))
                    win_delta = payout
                else:
                    win_delta = -bet
                new_bal = await eco_add(interaction.guild.id, interaction.user.id, win_delta)
                log_history(interaction.guild.id, interaction.user.id, "unitquiz", bet, win_delta)
                for c in view.children:
                    if isinstance(c, discord.ui.Button):
                        c.disabled = True
                        if c.label == correct:
                            c.style = discord.ButtonStyle.success
                        elif c.label == picked:
                            c.style = discord.ButtonStyle.danger
                if picked == correct:
                    outcome = f"✅ Correct! You win **{_fmt_currency(win_delta, curr)}**."
                else:
                    outcome = f"❌ Wrong ({picked}). The answer was **{correct}**. You lost **{_fmt_currency(bet, curr)}**."
                em2 = discord.Embed(title="🧩 Unit Quiz — Result", description=f"{interaction.user.mention}\n{outcome}\nBalance: **{_fmt_currency(new_bal, curr)}**", color=0x2ECC71 if win_delta>0 else 0xE74C3C)
                if image_url:
                    em2.set_image(url=image_url)
                await inter.response.edit_message(embed=em2, view=view)

    em = discord.Embed(title="🧩 Unit Quiz", description=f"{interaction.user.mention}, pick the correct unit!", color=0x5865F2)
    if image_url:
        em.set_image(url=image_url)
    await interaction.response.send_message(embed=em, view=QuizView(), file=file if file else discord.utils.MISSING)


# -------------------- Mini-game: Unit Spawn --------------------
@tree.command(name="unitspawn", description="Spawn a random unit; first person to claim wins (optional prize)")
@app_commands.describe(reward="Optional prize amount to award the claimer (default 0)")
async def unitspawn_cmd(interaction: discord.Interaction, reward: int = 0):
    import random, os, io
    # Load available units that have panel 1.png
    units = read_units_txt()
    candidates = [u for u in units if asset_path_for(u, 1)]
    if not candidates:
        return await interaction.response.send_message(f"No images ending with '1.png' found in `{ASSETS_DIR}`.", ephemeral=True)
    unit = random.choice(candidates)
    img_path = asset_path_for(unit, 1)

    # Prepare attachment
    file = None; image_url = None
    try:
        with open(img_path, "rb") as f:
            data = f.read()
        fname = "spawn.png"
        file = discord.File(io.BytesIO(data), filename=fname)
        image_url = f"attachment://{fname}"
    except Exception:
        pass

    # Spawn view: first click wins
    class SpawnView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)
            self.claimed_by: discord.User | None = None
        @discord.ui.button(label="Claim", style=discord.ButtonStyle.success)
        async def claim(self, inter: discord.Interaction, _btn: discord.ui.Button):
            if self.claimed_by is not None:
                return await inter.response.send_message("Already claimed!", ephemeral=True)
            self.claimed_by = inter.user
            # disable button
            for c in self.children:
                if isinstance(c, discord.ui.Button):
                    c.disabled = True
            desc = f"**{inter.user.mention}** claimed **{unit}**!"
            # Optional prize
            prize_line = ""
            if reward and reward > 0:
                new_bal = await eco_add(interaction.guild.id, inter.user.id, reward)
                prize_line = f"\nPrize: **{_fmt_currency(reward, _limits(interaction.guild.id)[4])}** — Balance: **{_fmt_currency(new_bal, _limits(interaction.guild.id)[4])}**"
                log_history(interaction.guild.id, inter.user.id, "unitspawn", reward, reward)
            em2 = discord.Embed(title="✨ A unit was claimed!", description=desc + prize_line, color=0xF1C40F)
            if image_url: em2.set_image(url=image_url)
            await inter.response.edit_message(embed=em2, view=self)

    em = discord.Embed(title="✨ A wild unit appeared!", description="Be the first to press **Claim**!", color=0xF1C40F)
    if image_url: em.set_image(url=image_url)
    await interaction.response.send_message(embed=em, view=SpawnView(), file=file if file else discord.utils.MISSING)


async def _unitspawn_send(channel: discord.TextChannel, reward_min: int, reward_max: int):
    # Reuse logic from /unitspawn
    import random, io, os
    units = read_units_txt()
    candidates = [u for u in units if asset_path_for(u, 1)]
    if not candidates:
        return
    unit = random.choice(candidates)
    img_path = asset_path_for(unit, 1)
    file = None; image_url = None
    try:
        with open(img_path, "rb") as f:
            data = f.read()
        fname = "spawn.png"
        file = discord.File(io.BytesIO(data), filename=fname)
        image_url = f"attachment://{fname}"
    except Exception:
        pass

    reward = 0
    if reward_max and reward_max >= reward_min >= 0:
        reward = random.randint(reward_min, reward_max)

    class SpawnView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)
            self.claimed_by = None
        @discord.ui.button(label="Claim", style=discord.ButtonStyle.success)
        async def claim(self, inter: discord.Interaction, _btn: discord.ui.Button):
            if self.claimed_by is not None:
                return await inter.response.send_message("Already claimed!", ephemeral=True)
            self.claimed_by = inter.user
            for c in self.children:
                if isinstance(c, discord.ui.Button):
                    c.disabled = True
            desc = f"**{inter.user.mention}** claimed **{unit}**!"
            prize_line = ""
            if reward and reward > 0:
                curr = _limits(channel.guild.id)[4]
                new_bal = await eco_add(channel.guild.id, inter.user.id, reward)
                log_history(channel.guild.id, inter.user.id, "unitspawn", reward, reward)
                prize_line = f"\nPrize: **{_fmt_currency(reward, curr)}** — Balance: **{_fmt_currency(new_bal, curr)}**"
            em2 = discord.Embed(title="✨ A unit was claimed!", description=desc + prize_line, color=0xF1C40F)
            if image_url: em2.set_image(url=image_url)
            await inter.response.edit_message(embed=em2, view=self)

    em = discord.Embed(title="✨ A wild unit appeared!", description="Be the first to press **Claim**!", color=0xF1C40F)
    if image_url: em.set_image(url=image_url)
    await channel.send(embed=em, view=SpawnView(), file=file if file else discord.utils.MISSING)

async def _unitspawn_worker(guild_id: int):
    cfg = UNITSPAWN.get(str(guild_id))
    if not cfg: 
        return
    while UNITSPAWN.get(str(guild_id)) is cfg:
        try:
            min_min = int(cfg.get("min_min", 5))
            max_min = int(cfg.get("max_min", 15))
            chance = int(cfg.get("chance", 100))
            reward_min = int(cfg.get("reward_min", 0))
            reward_max = int(cfg.get("reward_max", 0))
            delay = random.randint(min_min, max(min_min, max_min)) * 60
            await asyncio.sleep(delay)
            # Random chance gate
            roll = random.randint(1, 100)
            if roll > chance:
                continue
            guild = bot.get_guild(int(guild_id))
            if not guild: 
                continue
            channel = guild.get_channel(int(cfg["channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                continue
            await _unitspawn_send(channel, reward_min, reward_max)
        except asyncio.CancelledError:
            break
        except Exception as e:
            # keep worker alive
            print(f"[unitspawn] worker error for {guild_id}: {e}")
            await asyncio.sleep(5)


@tree.command(name="unitspawn_auto_on", description="Enable random unit spawns in a channel")
@app_commands.describe(channel="Channel for spawns", min_minutes="Minimum minutes between spawns", max_minutes="Maximum minutes between spawns", reward_min="Min reward", reward_max="Max reward", chance="Percent chance to spawn after each interval")
async def unitspawn_auto_on(interaction: discord.Interaction, channel: discord.TextChannel, min_minutes: int = 5, max_minutes: int = 15, reward_min: int = 0, reward_max: int = 0, chance: int = 100):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("You need **Manage Server** to use this.", ephemeral=True)
    _unitspawn_load()
    UNITSPAWN[str(interaction.guild.id)] = {"channel_id": channel.id, "min_min": min_minutes, "max_min": max_minutes, "reward_min": reward_min, "reward_max": reward_max, "chance": max(1, min(100, chance))}
    _unitspawn_save()
    # restart worker
    t = UNITSPAWN_TASKS.pop(interaction.guild.id, None)
    if t: t.cancel()
    UNITSPAWN_TASKS[interaction.guild.id] = asyncio.create_task(_unitspawn_worker(interaction.guild.id))
    await interaction.response.send_message(f"✅ Enabled auto spawns in {channel.mention}. Interval **{min_minutes}–{max_minutes} min**, chance **{chance}%**, reward **{reward_min}–{reward_max}**.", ephemeral=True)

@tree.command(name="unitspawn_auto_off", description="Disable random unit spawns")
async def unitspawn_auto_off(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("You need **Manage Server** to use this.", ephemeral=True)
    _unitspawn_load()
    cfg = UNITSPAWN.pop(str(interaction.guild.id), None)
    _unitspawn_save()
    t = UNITSPAWN_TASKS.pop(interaction.guild.id, None)
    if t: t.cancel()
    await interaction.response.send_message("🛑 Auto spawns disabled for this server.", ephemeral=True)

@tree.command(name="unitspawn_settings", description="Show current auto spawn settings")
async def unitspawn_settings(interaction: discord.Interaction):
    _unitspawn_load()
    cfg = UNITSPAWN.get(str(interaction.guild.id))
    if not cfg:
        return await interaction.response.send_message("Auto spawns are **off**.", ephemeral=True)
    ch = interaction.guild.get_channel(int(cfg["channel_id"]))
    await interaction.response.send_message(f"Channel: {ch.mention if ch else 'unknown'}\nInterval: **{cfg.get('min_min',5)}–{cfg.get('max_min',15)} min**\nChance: **{cfg.get('chance',100)}%**\nReward: **{cfg.get('reward_min',0)}–{cfg.get('reward_max',0)}**", ephemeral=True)


@bot.event
async def on_message(message: discord.Message):
    # Let commands still work
    await bot.process_commands(message)

    # Ignore DMs, bots, webhooks
    if not message.guild or message.author.bot or getattr(message, "webhook_id", None):
        return

    # If no content intent, quietly skip (Discord setting)
    if not hasattr(message, "content"):
        return

    _jjk_load()
    cfg = JJK_CFG.get(str(message.guild.id))
    if not cfg:
        return  # not enabled

    ch_id = int(cfg.get("channel_id", 0))
    if ch_id and ch_id != message.channel.id:
        return

    key = (message.guild.id, message.channel.id)

    # If there is an active spawn: check for correct answer
    active = JJK_ACTIVE.get(key)
    if active:
        # Check time
        if time.time() > active["deadline"]:
            JJK_ACTIVE.pop(key, None)
        else:
            unit = active["unit"]
            if _norm_name(message.content) == _norm_name(unit):
                # Winner!
                reward_min = int(cfg.get("reward_min", 0))
                reward_max = int(cfg.get("reward_max", 0))
                reward = random.randint(reward_min, reward_max) if reward_max >= reward_min and reward_max > 0 else 0
                curr = _limits(message.guild.id)[4]
                if reward > 0:
                    new_bal = await eco_add(message.guild.id, message.author.id, reward)
                    log_history(message.guild.id, message.author.id, "unitspawn_jjk", reward, reward)
                    prize = f"\nPrize: **{_fmt_currency(reward, curr)}** — Balance: **{_fmt_currency(new_bal, curr)}**"
                else:
                    prize = ""
                try:
                    msg = await message.channel.fetch_message(active["message_id"])
                    em2 = discord.Embed(title="✨ Unit Captured!", description=f"**{message.author.mention}** captured **{unit}**!{prize}", color=0xF1C40F)
                    # Preserve image if present
                    if msg.embeds and msg.embeds[0].image and msg.embeds[0].image.url:
                        em2.set_image(url=msg.embeds[0].image.url)
                    await msg.edit(embed=em2, view=None)
                except Exception:
                    pass
                JJK_ACTIVE.pop(key, None)
                return  # stop processing to avoid also incrementing counter

    # If no active spawn: increment counter and maybe spawn
    min_msgs = int(cfg.get("min_msgs", 20))
    max_msgs = int(cfg.get("max_msgs", 60))
    chance = int(cfg.get("chance", 100))
    st = JJK_STATE.get(key) or {"count": 0, "threshold": _jjk_threshold(min_msgs, max_msgs)}
    st["count"] += 1
    # Trigger when count >= threshold and chance gate passes
    if st["count"] >= st["threshold"] and random.randint(1, 100) <= chance and key not in JJK_ACTIVE:
        # reset counter/threshold
        st["count"] = 0
        st["threshold"] = _jjk_threshold(min_msgs, max_msgs)
        # Try to spawn
        units = read_units_txt()
        candidates = [u for u in units if asset_path_for(u, 1)]
        if candidates:
            unit = random.choice(candidates)
            img_path = asset_path_for(unit, 1)
            file = None; image_url = None
            try:
                with open(img_path, "rb") as f:
                    data = f.read()
                fname = "spawn.png"
                file = discord.File(io.BytesIO(data), filename=fname)
                image_url = f"attachment://{fname}"
            except Exception:
                pass
            em = discord.Embed(title="✨ A wild unit appeared!", description="Type the **exact name** of the unit to capture it!", color=0xF1C40F)
            if image_url: em.set_image(url=image_url)
            view = discord.ui.View()
            # Optional give-up button to reveal after timeout
            class Dummy(discord.ui.Button):
                def __init__(self): super().__init__(label="Waiting for answer…", style=discord.ButtonStyle.secondary, disabled=True)
            view.add_item(Dummy())
            msg = await message.channel.send(embed=em, view=view, file=file if file else discord.utils.MISSING)
            # Arm active spawn with 120s deadline
            JJK_ACTIVE[key] = {"unit": unit, "deadline": time.time()+120, "message_id": msg.id}
    JJK_STATE[key] = st


@tree.command(name="unitspawn_jjk_on", description="Enable JJK-style message spawns in a channel")
@app_commands.describe(channel="Channel for spawns", min_msgs="Minimum messages", max_msgs="Maximum messages", reward_min="Min reward", reward_max="Max reward", chance="Percent chance to spawn when threshold is met")
async def unitspawn_jjk_on(interaction: discord.Interaction, channel: discord.TextChannel, min_msgs: int = 20, max_msgs: int = 60, reward_min: int = 0, reward_max: int = 0, chance: int = 100):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("You need **Manage Server** to use this.", ephemeral=True)
    _jjk_load()
    JJK_CFG[str(interaction.guild.id)] = {"channel_id": channel.id, "min_msgs": min_msgs, "max_msgs": max_msgs, "reward_min": reward_min, "reward_max": reward_max, "chance": max(1, min(100, chance))}
    _jjk_save()
    # Reset per-channel state and clear any active spawn in that guild
    for key in list(JJK_STATE.keys()):
        if key[0] == interaction.guild.id:
            JJK_STATE.pop(key, None)
    for key in list(JJK_ACTIVE.keys()):
        if key[0] == interaction.guild.id:
            JJK_ACTIVE.pop(key, None)
    await interaction.response.send_message(f"✅ Enabled message spawns in {channel.mention}. Threshold **{min_msgs}–{max_msgs} msgs**, chance **{chance}%**, reward **{reward_min}–{reward_max}**.", ephemeral=True)

@tree.command(name="unitspawn_jjk_off", description="Disable JJK-style message spawns")
async def unitspawn_jjk_off(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("You need **Manage Server** to use this.", ephemeral=True)
    _jjk_load()
    JJK_CFG.pop(str(interaction.guild.id), None)
    _jjk_save()
    for key in list(JJK_STATE.keys()):
        if key[0] == interaction.guild.id:
            JJK_STATE.pop(key, None)
    for key in list(JJK_ACTIVE.keys()):
        if key[0] == interaction.guild.id:
            JJK_ACTIVE.pop(key, None)
    await interaction.response.send_message("🛑 Message spawns disabled for this server.", ephemeral=True)

@tree.command(name="unitspawn_jjk_settings", description="Show current JJK-style spawn settings")
async def unitspawn_jjk_settings(interaction: discord.Interaction):
    _jjk_load()
    cfg = JJK_CFG.get(str(interaction.guild.id))
    if not cfg:
        return await interaction.response.send_message("JJK-style spawns are **off**.", ephemeral=True)
    ch = interaction.guild.get_channel(int(cfg["channel_id"]))
    await interaction.response.send_message(f"Channel: {ch.mention if ch else 'unknown'}\nThreshold: **{cfg.get('min_msgs',20)}–{cfg.get('max_msgs',60)} msgs**\nChance: **{cfg.get('chance',100)}%**\nReward: **{cfg.get('reward_min',0)}–{cfg.get('reward_max',0)}**", ephemeral=True)

# -------------------- Startup --------------------
if __name__ == "__main__":
    import logging, os
    logging.basicConfig(level=logging.INFO)

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        try:
            with open("token.txt","r",encoding="utf-8") as f:
                token = f.read().strip()
        except Exception:
            token = None

    if not token:
        print("❌ No token. Set DISCORD_TOKEN or create token.txt next to bot.py")
        raise SystemExit(1)

    try:
        bot.run(token)
    except Exception as e:
        logging.exception("Failed to start bot: %s", e)
        raise
