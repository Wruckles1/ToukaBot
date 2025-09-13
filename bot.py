# -*- coding: utf-8 -*-
"""
ToukaGTD bot - consolidated build (enhanced, public gambling + stats/history fix)
Python 3.8 compatible (discord.py 2.x)
"""

import os, io, json, random, math, asyncio, time, textwrap, contextlib
from typing import Optional, List, Dict, Tuple

import discord
from discord import app_commands
from discord.ext import commands

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except Exception:
    PIL_OK = False

# -------------------- Configuration --------------------
ASSETS_DIR = os.environ.get("ASSETS_DIR", "units_assets")
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
    "stats": {}
})

def _migrate_econ():
    """Ensure top-level ECON keys exist (handles old economy.json files)."""
    ECON.setdefault("balances", {})
    ECON.setdefault("last_daily", {})
    ECON.setdefault("settings", {})
    ECON.setdefault("history", {})
    ECON.setdefault("stats", {})
    _save_econ()

def _save_econ():
    _save_json(ECON_PATH, ECON)

_migrate_econ()

# -------------------- Helpers --------------------
def norm_key(name: str) -> str:
    return " ".join(name.lower().replace("_", " ").split())

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
    units = list_units()
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
    os.makedirs(OUTPUT_DIR, exist_ok=True)

ensure_dirs()

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

# Fixed: use correct variable name
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

def _now_ts() -> int:
    return int(time.time())

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
    # stats (defensive setdefault on top-level keys)
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

# -------------------- Units commands --------------------
class UnitsPager(discord.ui.View):
    def __init__(self, items: List[str], start: int = 0):
        super().__init__(timeout=180)
        self.items = items
        self.idx = max(0, start)
        self.per = 20
        self.update_state()

    def page(self) -> int:
        return self.idx // self.per

    def pages(self) -> int:
        return max(1, math.ceil(len(self.items)/self.per))

    def slice(self) -> List[str]:
        s = self.page() * self.per
        return self.items[s:s+self.per]

    def update_state(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "prev":
                    child.disabled = (self.page() == 0)
                elif child.custom_id == "next":
                    child.disabled = (self.page() >= self.pages()-1)

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary, custom_id="prev")
    async def prev(self, inter: discord.Interaction, btn: discord.ui.Button):
        self.idx = max(0, self.idx - self.per)
        self.update_state()
        await inter.response.edit_message(**self._render())

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, custom_id="next")
    async def next(self, inter: discord.Interaction, btn: discord.ui.Button):
        self.idx = min((self.pages()-1)*self.per, self.idx + self.per)
        self.update_state()
        await inter.response.edit_message(**self._render())

    def _render(self):
        page = self.page() + 1
        pages = self.pages()
        desc_lines = []
        s = self.slice()
        start_idx = (page-1)*self.per + 1
        for i, name in enumerate(s, start_idx):
            desc_lines.append(f"{i}. {name}")
        embed = discord.Embed(title=f"Units (page {page}/{pages})", description="\n".join(desc_lines) or "_empty_", color=0x5865F2)
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
            embed = discord.Embed(title=u, color=0x2ECC71)
            embed.set_image(url="attachment://unit.png")
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
    if not img:
        return await interaction.response.send_message(f"No images found for **{u}** in `{ASSETS_DIR}`.", ephemeral=True)
    file = discord.File(io.BytesIO(img), filename="unit.png")
    embed = discord.Embed(title=u, color=0x2ECC71)
    embed.set_image(url="attachment://unit.png")
    await interaction.response.send_message(embed=embed, file=file)

class WheelView(discord.ui.View):
    def __init__(self, chosen: str):
        super().__init__(timeout=120)
        self.chosen = chosen

    @discord.ui.button(label="Respin", style=discord.ButtonStyle.primary)
    async def respin(self, inter: discord.Interaction, btn: discord.ui.Button):
        units = list_units()
        if not units:
            return await inter.response.send_message("No units found.", ephemeral=True)
        choice = random.choice(units)
        self.chosen = choice
        img = compose_unit_panel(choice)
        files = []
        embed = discord.Embed(title="🎁 Winner", description=choice, color=0xF1C40F)
        if img:
            files.append(discord.File(io.BytesIO(img), filename="winner.png"))
            embed.set_image(url="attachment://winner.png")
        await inter.response.edit_message(embed=embed, attachments=files)

@tree.command(name="wheel", description="Spin a case and pick a random unit")
async def wheel_cmd(interaction: discord.Interaction):
    units = list_units()
    if not units:
        return await interaction.response.send_message("No units available.", ephemeral=True)
    chosen = random.choice(units)
    strip = build_collage(random.sample(units, min(7, len(units)))) if PIL_OK else None
    files = []
    embed = discord.Embed(title="🎁 Opening case...", color=0xF1C40F)
    if strip:
        files.append(discord.File(io.BytesIO(strip), filename="strip.png"))
        embed.set_image(url="attachment://strip.png")
    view = WheelView(chosen)
    await interaction.response.send_message(embed=embed, view=view, files=files)

class TeamView(discord.ui.View):
    def __init__(self, names: List[str]):
        super().__init__(timeout=180)
        self.names = names

    @discord.ui.button(label="Respin Team", style=discord.ButtonStyle.primary)
    async def respin(self, inter: discord.Interaction, btn: discord.ui.Button):
        units = list_units()
        if not units:
            return await inter.response.send_message("No units found.", ephemeral=True)
        self.names = random.sample(units, min(7, len(units)))
        collage = build_collage(self.names) if PIL_OK else None
        embed = discord.Embed(title="Team Collage", color=0x3498DB)
        files = []
        if collage:
            files.append(discord.File(io.BytesIO(collage), filename="team.png"))
            embed.set_image(url="attachment://team.png")
        await inter.response.edit_message(embed=embed, attachments=files)

@tree.command(name="team", description="Create a random team of 7")
async def team_cmd(interaction: discord.Interaction):
    units = list_units()
    if not units:
        return await interaction.response.send_message("No units available.", ephemeral=True)
    names = random.sample(units, min(7, len(units)))
    collage = build_collage(names) if PIL_OK else None
    embed = discord.Embed(title="Team Collage", color=0x3498DB)
    files = []
    if collage:
        files.append(discord.File(io.BytesIO(collage), filename="team.png"))
        embed.set_image(url="attachment://team.png")
    view = TeamView(names)
    await interaction.response.send_message(embed=embed, view=view, files=files)

@tree.command(name="values", description="Show the official value list link")
async def values_cmd(interaction: discord.Interaction):
    url = "https://sites.google.com/view/garden-td-values/main-page?authuser=0"
    embed = discord.Embed(title="Garden TD Values", description=f"[Open the live value list]({url})", color=0x95A5A6)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# -------------------- Ingest attachments --------------------
def _sanitize_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    if CONFIG.get("UNDERSCORE_TO_SPACE", True):
        name = name.replace("_", " ")
    name = "".join(ch for ch in name if ch >= " " and ch not in ':"<>|')
    return name

async def _save_attachment(att: discord.Attachment) -> str:
    data = await att.read()
    safe = _sanitize_filename(att.filename)
    ext = os.path.splitext(safe)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        out = os.path.join(ASSETS_DIR, safe)
    elif ext == ".txt":
        out = UNITS_TXT if "units" in safe.lower() else os.path.join(OUTPUT_DIR, safe)
    elif ext == ".json":
        out = ALIASES_JSON if "aliases" in safe.lower() else os.path.join(OUTPUT_DIR, safe)
    else:
        out = os.path.join(OUTPUT_DIR, safe)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as f:
        f.write(data)
    if out.endswith(ALIASES_JSON):
        global ALIASES
        ALIASES = load_aliases()
    return out

@tree.command(name="ingest", description="Upload & save files (images, units.txt, aliases.json, etc.)")
@app_commands.describe(
    file1="Attachment", file2="Attachment", file3="Attachment", file4="Attachment", file5="Attachment",
    file6="Attachment", file7="Attachment", file8="Attachment", file9="Attachment", file10="Attachment"
)
async def ingest_cmd(
    interaction: discord.Interaction,
    file1: Optional[discord.Attachment] = None,
    file2: Optional[discord.Attachment] = None,
    file3: Optional[discord.Attachment] = None,
    file4: Optional[discord.Attachment] = None,
    file5: Optional[discord.Attachment] = None,
    file6: Optional[discord.Attachment] = None,
    file7: Optional[discord.Attachment] = None,
    file8: Optional[discord.Attachment] = None,
    file9: Optional[discord.Attachment] = None,
    file10: Optional[discord.Attachment] = None,
):
    files = [f for f in (file1,file2,file3,file4,file5,file6,file7,file8,file9,file10) if f is not None]
    if not files:
        return await interaction.response.send_message("Please supply one or more attachments via the options.", ephemeral=True)
    saved = []
    for att in files[:10]:
        path = await _save_attachment(att)
        saved.append(os.path.basename(path))
    await interaction.response.send_message(f"Saved: {', '.join(saved)}", ephemeral=True)

# -------------------- Economy (existing) --------------------
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

# PUBLIC from here on for gambling/minigames
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
    if bet < min_bet or bet > max_bet:
        return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet:
        return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    res = random.choice(("heads", "tails"))
    if res == side:
        win = int(round(bet * (2.0 - edge)))
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
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
    if bet < min_bet or bet > max_bet:
        return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet:
        return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    reels = [random.choice(SLOT_EMOJI) for _ in range(3)]
    text = " | ".join(reels)
    win = 0
    if len(set(reels)) == 1:
        win = int(round(bet * (9.0 - edge)))
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        win = int(round(bet * (2.0 - edge)))
    if win > 0:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
        log_history(interaction.guild.id, interaction.user.id, "slots", bet, win)
        await interaction.response.send_message(f"{interaction.user.mention} rolled **{text}** — won **{_fmt_currency(win, curr)}**! New balance: **{_fmt_currency(new_bal, curr)}**")
    else:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
        log_history(interaction.guild.id, interaction.user.id, "slots", bet, -bet)
        await interaction.response.send_message(f"{interaction.user.mention} rolled **{text}** — no win. Lost **{_fmt_currency(bet, curr)}** — Balance: **{_fmt_currency(new_bal, curr)}**")

@tree.command(name="give", description="Give currency to another user")
@in_gambling_channel()
@app_commands.describe(user="recipient", amount="amount to transfer")
async def give_cmd(interaction: discord.Interaction, user: discord.Member, amount: int):
    if user.bot or user.id == interaction.user.id:
        return await interaction.response.send_message("Invalid recipient.", ephemeral=True)
    if amount <= 0:
        return await interaction.response.send_message("Amount must be > 0.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < amount:
        return await interaction.response.send_message("Insufficient balance.", ephemeral=True)
    await eco_add(interaction.guild.id, interaction.user.id, -amount)
    new_bal = await eco_add(interaction.guild.id, user.id, amount)
    _,_,_,_,curr = _limits(interaction.guild.id)
    log_history(interaction.guild.id, interaction.user.id, "give", amount, -amount)
    log_history(interaction.guild.id, user.id, "give", amount, amount)
    await interaction.response.send_message(f"💸 {interaction.user.mention} transferred **{_fmt_currency(amount, curr)}** to {user.mention}. (Recipient balance: **{_fmt_currency(new_bal, curr)}**)")

@tree.command(name="leaderboard", description="Top 10 balances")
@in_gambling_channel()
async def leaderboard_cmd(interaction: discord.Interaction):
    g = str(interaction.guild.id)
    _,_,_,_,curr = _limits(interaction.guild.id)
    board = sorted(ECON["balances"].get(g, {}).items(), key=lambda kv: kv[1], reverse=True)[:10]
    lines = []
    for i, (uid, amt) in enumerate(board, 1):
        member = interaction.guild.get_member(int(uid))
        name = member.mention if member else f"<@{uid}>"
        lines.append(f"**{i}.** {name} — {_fmt_currency(amt, curr)}")
    desc = "\n".join(lines) or "_No balances yet_"
    embed = discord.Embed(title="Leaderboard", description=desc, color=0xE67E22)
    await interaction.response.send_message(embed=embed)

# -------------------- Settings & Grant (existing) --------------------
@tree.command(name="gambling_settings", description="Admin: configure gambling settings")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    enabled="Enable/disable gambling",
    currency="Currency symbol (e.g., 🍀, 💎, $)",
    min_bet="Minimum bet",
    max_bet="Maximum bet",
    house_edge="House edge (2 or 0.02 = 2%)",
    daily="Daily payout",
    channel="Restrict gambling commands to this channel",
    clear_channel="Clear the channel restriction",
    banker_role="Role allowed to grant coins (besides Manage Server)",
    clear_banker_role="Clear banker role"
)
async def gambling_settings_cmd(
    interaction: discord.Interaction,
    enabled: Optional[bool] = None,
    currency: Optional[str] = None,
    min_bet: Optional[int] = None,
    max_bet: Optional[int] = None,
    house_edge: Optional[float] = None,
    daily: Optional[int] = None,
    channel: Optional[discord.TextChannel] = None,
    clear_channel: Optional[bool] = None,
    banker_role: Optional[discord.Role] = None,
    clear_banker_role: Optional[bool] = None
):
    if enabled is not None:
        set_guild_setting(interaction.guild.id, "GAMBLING_ENABLED", bool(enabled))
    if currency is not None:
        set_guild_setting(interaction.guild.id, "CURRENCY", currency[:3])
    if min_bet is not None:
        set_guild_setting(interaction.guild.id, "MIN_BET", int(min_bet))
    if max_bet is not None:
        set_guild_setting(interaction.guild.id, "MAX_BET", int(max_bet))
    if house_edge is not None:
        edge = house_edge if house_edge < 1 else (house_edge/100.0)
        set_guild_setting(interaction.guild.id, "HOUSE_EDGE", float(edge))
    if daily is not None:
        set_guild_setting(interaction.guild.id, "DAILY_AMOUNT", int(daily))
    if channel is not None:
        set_guild_setting(interaction.guild.id, "GAMBLING_CHANNEL_ID", int(channel.id))
    if clear_channel:
        set_guild_setting(interaction.guild.id, "GAMBLING_CHANNEL_ID", None)
    if banker_role is not None:
        set_guild_setting(interaction.guild.id, "BANKER_ROLE_ID", int(banker_role.id))
    if clear_banker_role:
        set_guild_setting(interaction.guild.id, "BANKER_ROLE_ID", None)

    min_bet, max_bet, edge, daily_amt, curr = _limits(interaction.guild.id)
    chan_id = _get_gambling_channel_id(interaction.guild.id)
    chan_ref = interaction.guild.get_channel(chan_id) if chan_id else None
    chan_txt = chan_ref.mention if chan_ref else "Any channel"
    br_id = _get_banker_role_id(interaction.guild.id)
    br_ref = interaction.guild.get_role(br_id) if br_id else None
    br_txt = br_ref.mention if br_ref else "Manage Server only"

    await interaction.response.send_message(
        f"Settings for **{interaction.guild.name}**:\n"
        f"Enabled: {guild_setting(interaction.guild.id, 'GAMBLING_ENABLED', True)}\n"
        f"Currency: {curr} | Min: {min_bet} | Max: {max_bet}\n"
        f"Edge: {edge*100:.1f}% | Daily: {daily_amt}\n"
        f"Gambling channel: {chan_txt}\n"
        f"Banker role: {br_txt}",
        ephemeral=True
    )

@tree.command(name="grant", description="(Admin/Banker) Grant coins to a user")
@in_gambling_channel()
@app_commands.describe(user="Recipient", amount="Amount to add (positive only)", reason="Optional note")
async def grant_cmd(interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1, 100000000], reason: Optional[str]=None):
    if not interaction.guild or user.bot:
        return await interaction.response.send_message("Invalid recipient.", ephemeral=True)
    if not user_is_banker(interaction):
        return await interaction.response.send_message("You need Manage Server or the configured Banker role.", ephemeral=True)
    new_bal = await eco_add(interaction.guild.id, user.id, int(amount))
    _,_,_,_,curr = _limits(interaction.guild.id)
    note = f" Reason: {reason}" if reason else ""
    log_history(interaction.guild.id, interaction.user.id, "grant", int(amount), -int(amount))
    log_history(interaction.guild.id, user.id, "grant", int(amount), int(amount))
    await interaction.response.send_message(f"Added **{_fmt_currency(int(amount), curr)}** to {user.mention}. New balance: **{_fmt_currency(new_bal, curr)}**.{note}", ephemeral=True)

# -------------------- NEW GAMES (PUBLIC) --------------------
@tree.command(name="dice", description="Bet high/low on 2d6 (7 is house)")
@in_gambling_channel()
@app_commands.describe(bet="bet amount", guess="high or low")
async def dice_cmd(interaction: discord.Interaction, bet: int, guess: str):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True):
        return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    guess = guess.lower().strip()
    if guess not in ("high","low"):
        return await interaction.response.send_message("Use **high** or **low**.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if bet < min_bet or bet > max_bet:
        return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet:
        return await interaction.response.send_message("Insufficient balance.", ephemeral=True)

    roll = random.randint(1,6) + random.randint(1,6)
    if (roll <= 6 and guess == "low") or (roll >= 8 and guess == "high"):
        win = int(round(bet * (2.0 - edge)))
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
        log_history(interaction.guild.id, interaction.user.id, "dice", bet, win)
        return await interaction.response.send_message(f"🎲 {interaction.user.mention} rolled **{roll}** — won **{_fmt_currency(win,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")
    else:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
        log_history(interaction.guild.id, interaction.user.id, "dice", bet, -bet)
        return await interaction.response.send_message(f"🎲 {interaction.user.mention} rolled **{roll}** — lost **{_fmt_currency(bet,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")

@tree.command(name="roulette", description="Roulette: bet red/black or exact number (0-36)")
@in_gambling_channel()
@app_commands.describe(bet="bet amount", choice="red/black or 0-36")
async def roulette_cmd(interaction: discord.Interaction, bet: int, choice: str):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True):
        return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if bet < min_bet or bet > max_bet:
        return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet:
        return await interaction.response.send_message("Insufficient balance.", ephemeral=True)

    REDS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    num = random.randint(0,36)
    color = "red" if num in REDS else ("green" if num == 0 else "black")

    win = 0
    c = choice.strip().lower()
    if c.isdigit() and 0 <= int(c) <= 36:
        if int(c) == num:
            win = int(round(bet * (35.0 - edge)))
    elif c in ("red","black"):
        if c == color:
            win = int(round(bet * (2.0 - edge)))
    else:
        return await interaction.response.send_message("Choice must be **red**, **black**, or **0..36**.", ephemeral=True)

    if win > 0:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
        log_history(interaction.guild.id, interaction.user.id, "roulette", bet, win)
        await interaction.response.send_message(f"🎡 {interaction.user.mention} → {num} ({color}) — won **{_fmt_currency(win,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")
    else:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
        log_history(interaction.guild.id, interaction.user.id, "roulette", bet, -bet)
        await interaction.response.send_message(f"🎡 {interaction.user.mention} → {num} ({color}) — lost **{_fmt_currency(bet,curr)}**. Balance: **{_fmt_currency(new_bal,curr)}**")

@tree.command(name="blackjack", description="Blackjack vs dealer")
@in_gambling_channel()
@app_commands.describe(bet="bet amount")
async def blackjack_cmd(interaction: discord.Interaction, bet: int):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True):
        return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if bet < min_bet or bet > max_bet:
        return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet:
        return await interaction.response.send_message("Insufficient balance.", ephemeral=True)

    ranks = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
    suits = ["♠","♥","♦","♣"]
    deck = [f"{r}{s}" for r in ranks for s in suits] * 4
    random.shuffle(deck)

    def card_value(hand: List[str]) -> int:
        v = 0; aces = 0
        for c in hand:
            r = c[:-1] if c[:-1] in ("10",) else c[0]
            if r in ("J","Q","K"):
                v += 10
            elif r == "A":
                v += 11; aces += 1
            else:
                v += int(r)
        while v > 21 and aces:
            v -= 10; aces -= 1
        return v

    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]

    class BJView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=90)
            self.current_bet = bet
            self.finished = False

        async def finish(self, inter: discord.Interaction, outcome: str, delta: int):
            if self.finished:
                return
            self.finished = True
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, delta)
            log_history(interaction.guild.id, interaction.user.id, "blackjack", self.current_bet, delta)
            for c in self.children:
                c.disabled = True
            pval = card_value(player)
            dval = card_value(dealer)
            em = discord.Embed(title="♦️ Blackjack — Result",
                               description=f"**{interaction.user.mention}**\n"
                                           f"Your: {' | '.join(player)} (**{pval}**)\n"
                                           f"Dealer: {' | '.join(dealer)} (**{dval}**)\n\n{outcome}\n"
                                           f"Balance: **{_fmt_currency(new_bal,curr)}**",
                               color=0xF1C40F if delta>0 else 0xE74C3C)
            await inter.response.edit_message(embed=em, view=self)

        @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
        async def hit(self, inter: discord.Interaction, _btn: discord.ui.Button):
            player.append(deck.pop())
            pval = card_value(player)
            if pval > 21:
                return await self.finish(inter, f"💥 Bust! Lost **{_fmt_currency(self.current_bet,curr)}**.", -self.current_bet)
            em = discord.Embed(title="♦️ Blackjack",
                               description=f"{interaction.user.mention}\nYour: {' | '.join(player)} (**{pval}**)\nDealer: {dealer[0]} ??\nBet: **{_fmt_currency(self.current_bet,curr)}**",
                               color=0x2ECC71)
            await inter.response.edit_message(embed=em, view=self)

        @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
        async def stand(self, inter: discord.Interaction, _btn: discord.ui.Button):
            while card_value(dealer) < 17:
                dealer.append(deck.pop())
            pval, dval = card_value(player), card_value(dealer)
            if dval > 21 or pval > dval:
                win = int(round(self.current_bet * (2.0 - edge)))
                return await self.finish(inter, f"✅ You win **{_fmt_currency(win,curr)}**!", win)
            elif pval == dval:
                return await self.finish(inter, "➖ Push.", 0)
            else:
                return await self.finish(inter, f"❌ Dealer wins. Lost **{_fmt_currency(self.current_bet,curr)}**.", -self.current_bet)

        @discord.ui.button(label="Double", style=discord.ButtonStyle.success)
        async def double(self, inter: discord.Interaction, _btn: discord.ui.Button):
            if eco_get(inter.guild.id, inter.user.id) < self.current_bet:
                return await inter.response.send_message("Not enough balance to double.", ephemeral=True)
            self.current_bet *= 2
            player.append(deck.pop())
            while card_value(dealer) < 17:
                dealer.append(deck.pop())
            pval, dval = card_value(player), card_value(dealer)
            if pval > 21:
                return await self.finish(inter, f"💥 Bust on double! Lost **{_fmt_currency(self.current_bet,curr)}**.", -self.current_bet)
            if dval > 21 or pval > dval:
                win = int(round(self.current_bet * (2.0 - edge)))
                return await self.finish(inter, f"✅ You win **{_fmt_currency(win,curr)}**!", win)
            elif pval == dval:
                return await self.finish(inter, "➖ Push.", 0)
            else:
                return await self.finish(inter, f"❌ Dealer wins. Lost **{_fmt_currency(self.current_bet,curr)}**.", -self.current_bet)

    start = discord.Embed(
        title="♦️ Blackjack",
        description=f"{interaction.user.mention}\nYour: {' | '.join(player)} (**{card_value(player)}**)\nDealer: {dealer[0]} ??\nBet: **{_fmt_currency(bet, curr)}**",
        color=0x2ECC71
    )
    await interaction.response.send_message(embed=start, view=BJView())

@tree.command(name="crash", description="Crash game — cash out before it explodes")
@in_gambling_channel()
@app_commands.describe(bet="bet amount")
async def crash_cmd(interaction: discord.Interaction, bet: int):
    if not guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True):
        return await interaction.response.send_message("Gambling is disabled here.", ephemeral=True)
    min_bet, max_bet, edge, _, curr = _limits(interaction.guild.id)
    if bet < min_bet or bet > max_bet:
        return await interaction.response.send_message(f"Bet must be between {min_bet} and {max_bet}.", ephemeral=True)
    if eco_get(interaction.guild.id, interaction.user.id) < bet:
        return await interaction.response.send_message("Insufficient balance.", ephemeral=True)

    multiplier = 1.0

    class CrashView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=20)
            self.cashed = False

        @discord.ui.button(label="Cash Out", style=discord.ButtonStyle.success)
        async def cashout(self, inter: discord.Interaction, _btn: discord.ui.Button):
            if self.cashed:
                return
            self.cashed = True
            win = max(0, int(round(bet * (multiplier - edge))))
            new_bal = await eco_add(interaction.guild.id, interaction.user.id, win)
            log_history(interaction.guild.id, interaction.user.id, "crash", bet, win)
            em = discord.Embed(title="🚀 Crash", description=f"{interaction.user.mention} cashed at **{multiplier:.2f}x** — won **{_fmt_currency(win,curr)}**.\nBalance: **{_fmt_currency(new_bal,curr)}**")
            await inter.response.edit_message(embed=em, view=None)

    view = CrashView()
    await interaction.response.send_message(embed=discord.Embed(title="🚀 Crash", description=f"{interaction.user.mention} started a round. Rising... press **Cash Out**!"), view=view)
    msg = await interaction.original_response()

    for _ in range(24):
        await asyncio.sleep(1)
        if view.cashed:
            return
        multiplier *= 1 + random.uniform(0.05, 0.35)
        if random.random() < 0.12 + (multiplier-1)*0.02:
            break
        await msg.edit(embed=discord.Embed(title="🚀 Crash", description=f"**{interaction.user.mention}** Multiplier: **{multiplier:.2f}x**\nCash out before 💥!"), view=view)

    if not view.cashed:
        new_bal = await eco_add(interaction.guild.id, interaction.user.id, -bet)
        log_history(interaction.guild.id, interaction.user.id, "crash", bet, -bet)
        await msg.edit(embed=discord.Embed(title="💥 Crash", description=f"{interaction.user.mention} — crashed at **{multiplier:.2f}x** and lost **{_fmt_currency(bet,curr)}**.\nBalance: **{_fmt_currency(new_bal,curr)}**"), view=None)

# -------------------- Admin Panel (Owner-only) --------------------
@tree.command(name="adminpanel", description="Owner-only admin panel (gambling controls)")
@owner_only()
async def adminpanel_cmd(interaction: discord.Interaction):
    g = str(interaction.guild.id)
    min_bet, max_bet, edge, daily_amt, curr = _limits(interaction.guild.id)
    chan_id = _get_gambling_channel_id(interaction.guild.id)
    chan_txt = interaction.guild.get_channel(chan_id).mention if chan_id else "Any channel"
    enabled = guild_setting(interaction.guild.id, "GAMBLING_ENABLED", True)

    embed = discord.Embed(
        title=f"Admin Panel — {interaction.guild.name}",
        description=(
            f"**Gambling**: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
            f"**Currency**: {curr}\n"
            f"**Min/Max Bet**: {min_bet}/{max_bet}\n"
            f"**House Edge**: {edge*100:.1f}%\n"
            f"**Daily**: {daily_amt}\n"
            f"**Gambling Channel**: {chan_txt}\n"
        ),
        color=0xFF0066
    )

    class LimitsModal(discord.ui.Modal, title="Edit Gambling Settings"):
        def __init__(self):
            super().__init__()
            self.currency = discord.ui.TextInput(label="Currency (1-3 chars)", default=curr, required=False, max_length=3)
            self.min_bet_in = discord.ui.TextInput(label="Min Bet", default=str(min_bet), required=False)
            self.max_bet_in = discord.ui.TextInput(label="Max Bet", default=str(max_bet), required=False)
            self.edge_in = discord.ui.TextInput(label="House Edge (%)", default=f"{edge*100:.2f}", required=False)
            self.daily_in = discord.ui.TextInput(label="Daily Amount", default=str(daily_amt), required=False)
            self.add_item(self.currency); self.add_item(self.min_bet_in)
            self.add_item(self.max_bet_in); self.add_item(self.edge_in); self.add_item(self.daily_in)

        async def on_submit(self, inter: discord.Interaction):
            try:
                if str(self.currency.value).strip():
                    set_guild_setting(inter.guild.id, "CURRENCY", str(self.currency.value)[:3])
                if str(self.min_bet_in.value).strip():
                    set_guild_setting(inter.guild.id, "MIN_BET", int(self.min_bet_in.value))
                if str(self.max_bet_in.value).strip():
                    set_guild_setting(inter.guild.id, "MAX_BET", int(self.max_bet_in.value))
                if str(self.edge_in.value).strip():
                    val = float(self.edge_in.value)
                    set_guild_setting(inter.guild.id, "HOUSE_EDGE", val/100.0 if val >= 1 else val)
                if str(self.daily_in.value).strip():
                    set_guild_setting(inter.guild.id, "DAILY_AMOUNT", int(self.daily_in.value))
                await inter.response.send_message("✅ Settings updated.", ephemeral=True)
            except Exception as e:
                await inter.response.send_message(f"❌ Failed to update: {e}", ephemeral=True)

    class PanelView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=180)

        @discord.ui.button(label="Toggle Gambling", style=discord.ButtonStyle.danger)
        async def toggle(self, inter: discord.Interaction, _btn: discord.ui.Button):
            cur = guild_setting(inter.guild.id, "GAMBLING_ENABLED", True)
            set_guild_setting(inter.guild.id, "GAMBLING_ENABLED", not cur)
            await inter.response.send_message(f"Gambling now **{'enabled' if not cur else 'disabled'}**.", ephemeral=True)

        @discord.ui.button(label="Edit Settings", style=discord.ButtonStyle.primary)
        async def edit(self, inter: discord.Interaction, _btn: discord.ui.Button):
            await inter.response.send_modal(LimitsModal())

        @discord.ui.button(label="Set This Channel", style=discord.ButtonStyle.secondary)
        async def setchan(self, inter: discord.Interaction, _btn: discord.ui.Button):
            set_guild_setting(inter.guild.id, "GAMBLING_CHANNEL_ID", inter.channel.id)
            await inter.response.send_message(f"Gambling channel set to {inter.channel.mention}.", ephemeral=True)

        @discord.ui.button(label="Clear Channel Restriction", style=discord.ButtonStyle.secondary)
        async def clearchan(self, inter: discord.Interaction, _btn: discord.ui.Button):
            set_guild_setting(inter.guild.id, "GAMBLING_CHANNEL_ID", None)
            await inter.response.send_message("Gambling channel restriction cleared.", ephemeral=True)

        @discord.ui.button(label="Reset Leaderboard", style=discord.ButtonStyle.secondary)
        async def resetlb(self, inter: discord.Interaction, _btn: discord.ui.Button):
            ECON.setdefault("balances", {})[g] = {}
            _save_econ()
            await inter.response.send_message("Leaderboard reset.", ephemeral=True)

        @discord.ui.button(label="View Recent Bets", style=discord.ButtonStyle.success)
        async def viewhist(self, inter: discord.Interaction, _btn: discord.ui.Button):
            ECON.setdefault("history", {}).setdefault(g, {})
            items = []
            for uid, arr in ECON["history"][g].items():
                for entry in arr[-10:]:
                    items.append((entry["t"], uid, entry))
            items.sort(key=lambda x: x[0], reverse=True)
            hist_lines = []
            for t, uid, e in items[:15]:
                member = inter.guild.get_member(int(uid))
                name = member.display_name if member else f"User {uid}"
                sign = "+" if e["result"] >= 0 else "-"
                hist_lines.append(f"<t:{t}:R> — {name}: {e['game']} bet {e['bet']} ⇒ {sign}{abs(e['result'])}")
            txt = "\n".join(hist_lines) or "_No recent bets_"
            await inter.response.send_message(txt, ephemeral=True)

    await interaction.response.send_message(embed=embed, view=PanelView(), ephemeral=True)

# -------------------- Player Stats --------------------
@tree.command(name="mystats", description="Show your gambling stats")
async def mystats_cmd(interaction: discord.Interaction):
    g, u = str(interaction.guild.id), str(interaction.user.id)
    s = ECON.setdefault("stats", {}).setdefault(g, {}).setdefault(u, {"bets":0,"won":0,"lost":0,"biggest":0})
    _,_,_,_,curr = _limits(interaction.guild.id)
    net = s["won"] - s["lost"]
    em = discord.Embed(
        title=f"{interaction.user.display_name} — Stats",
        description=(
            f"🎲 **Bets**: {s['bets']}\n"
            f"💰 **Won**: {_fmt_currency(s['won'], curr)}\n"
            f"💸 **Lost**: {_fmt_currency(s['lost'], curr)}\n"
            f"📈 **Net**: {_fmt_currency(net, curr)}\n"
            f"🏆 **Biggest Win**: {_fmt_currency(s['biggest'], curr)}"
        ),
        color=0x9B59B6
    )
    await interaction.response.send_message(embed=em, ephemeral=True)

# -------------------- Startup --------------------
@bot.event
async def on_ready():
    try:
        guild_ids = os.environ.get("GUILD_IDS", "").strip()
        if guild_ids:
            gids = [int(x) for x in guild_ids.split(",") if x.strip().isdigit()]
            for gid in gids:
                try:
                    await tree.sync(guild=discord.Object(id=gid))
                    print(f"[sync] synced for guild {gid}")
                except Exception as e:
                    print("sync error guild", gid, e)
        else:
            await tree.sync()
            print("[sync] global")
    except Exception as e:
        print("sync failure", e)
    print(f"Logged in as {bot.user}")

def _load_token() -> Optional[str]:
    tok = os.environ.get("DISCORD_TOKEN") or os.environ.get("TOKEN")
    if tok:
        return tok.strip()
    if os.path.isfile(TOKEN_PATH):
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None

def main():
    token = _load_token()
    if not token:
        print("[boot] No token found. Set DISCORD_TOKEN or create token.txt")
        return
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    bot.run(token)

if __name__ == "__main__":
    main()
