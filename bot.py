# bot.py — ToukaBot minimal but full-featured build
# - Token loader: reads DISCORD_TOKEN env var or token.txt
# - /wheel: CS:GO-style case animation GIF that stops on the winner
# - /unit <name>: shows composite (main + stats) image for a unit
# - /units [page]: paged list of available unit names scanned from units_assets/
#
# Startup (Pterodactyl/Cybrancee):
#   if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
#   python3 bot.py

import os
import re
import time
import random
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
import discord
from discord import app_commands

# ----------------------------- Configuration ---------------------------------
ASSETS_DIR = os.getenv("UNITS_ASSETS_DIR", "units_assets")  # folder containing your unit images
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "media")               # where GIFs/PNGs are saved

# Visual config for case animation
WHEEL = {
    "tile_w": 128,
    "tile_h": 96,
    "pad": 6,
    "visible": 7,           # number of tiles visible in the window
    "frame_ms": 90,         # ms per frame during spin
    "final_hold_ms": 1500,  # hold on last frame
    "bg": (196,154,108,255),
    "card": (74,58,42,255),
}

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ------------------------------- Utilities -----------------------------------

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[_\-]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s

def scan_images(root: str) -> Dict[str, List[str]]:
    """
    Walk ASSETS_DIR and build: normalized unit name -> [image paths].
    Files like 'Aloe Vera 1.png' and 'Aloe Vera 2.png' will be grouped under 'aloe vera'.
    """
    mapping: Dict[str, List[str]] = {}
    if not os.path.isdir(root):
        return mapping
    for dp, _, files in os.walk(root):
        for f in files:
            fl = f.lower()
            if fl.endswith((".png", ".jpg", ".jpeg", ".webp")):
                key = _norm(os.path.splitext(f)[0])
                key = re.sub(r"\s+\d+$", "", key)  # strip trailing numbers used for variants
                mapping.setdefault(key, []).append(os.path.join(dp, f))
    for k in mapping:
        mapping[k].sort()
    return mapping

IMAGES: Dict[str, List[str]] = scan_images(ASSETS_DIR)

def rescan_images() -> None:
    global IMAGES
    IMAGES = scan_images(ASSETS_DIR)

def find_images_for(name: str) -> List[str]:
    key = _norm(name)
    if key in IMAGES:
        return IMAGES[key][:]
    # fuzzy fallback (contains)
    for k in IMAGES:
        if key in k or k in key:
            return IMAGES[k][:]
    return []

def pick_main_and_stats(imgs: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Choose a 'main' and an optional 'stats' image from a list.
    Prefers files ending in ' 1' (or no number) as main, and ' 2' as stats.
    """
    if not imgs:
        return (None, None)

    def score_main(p: str) -> int:
        fn = os.path.basename(p).lower()
        s = 0
        if " 1" in fn or fn.endswith("1.png") or fn.endswith("1.jpg"):
            s += 5
        if "2" in fn:
            s -= 1
        if "stats" in fn:
            s -= 2
        return s

    main = max(imgs, key=score_main)
    stats = None
    for p in imgs:
        if p == main:
            continue
        fn = os.path.basename(p).lower()
        if " 2" in fn or "stats" in fn:
            stats = p
            break
    return main, stats

def _text_size(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, text: str) -> Tuple[int,int]:
    try:
        b = draw.textbbox((0,0), text, font=font)
        return b[2]-b[0], b[3]-b[1]
    except Exception:
        try:
            b = font.getbbox(text)
            return b[2]-b[0], b[3]-b[1]
        except Exception:
            return (len(text)*8, 16)

def _save_path(prefix: str, ext: str) -> str:
    return os.path.join(OUTPUT_DIR, f"{prefix}_{int(time.time()*1000)}.{ext}")

# --------------------------- Unit composite builder --------------------------

def build_unit_composite(name: str) -> Optional[str]:
    """Stack main + stats image side-by-side. Falls back to single image if only one exists."""
    imgs = find_images_for(name)
    if not imgs:
        return None
    main, stats = pick_main_and_stats(imgs)

    try:
        im1 = Image.open(main).convert("RGBA") if main else None
        im2 = Image.open(stats).convert("RGBA") if stats else None
    except Exception:
        return None

    if im1 and im2:
        h = max(im1.height, im2.height)
        scale = 450  # scale height for readability
        def scale_to_h(im):
            r = scale / im.height
            return im.resize((int(im.width*r), scale), Image.LANCZOS)
        im1 = scale_to_h(im1)
        im2 = scale_to_h(im2)
        out = Image.new("RGBA", (im1.width + im2.width, scale), (20,20,20,255))
        out.paste(im1, (0,0), im1)
        out.paste(im2, (im1.width,0), im2)
    else:
        im = im1 or im2
        if im is None:
            return None
        scale = 450
        r = scale / im.height
        out = im.resize((int(im.width*r), scale), Image.LANCZOS)

    # add title banner
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except Exception:
        font = ImageFont.load_default()
    title = " ".join(w.capitalize() for w in _norm(name).split())
    tw, th = _text_size(draw, font, title)
    bar_h = th + 10
    draw.rectangle([0,0,out.width,bar_h], fill=(0,0,0,160))
    draw.text((10,(bar_h-th)//2), title, fill=(255,255,255,255), font=font)

    path = _save_path("unit", "png")
    out.save(path)
    return path

# ------------------------- Case animation (CS:GO style) ----------------------

def _unit_pool_from_images() -> List[str]:
    pool = []
    for k in IMAGES.keys():
        pretty = " ".join(w.capitalize() for w in k.split())
        pool.append(pretty)
    return sorted(pool)

def _frame_strip(seq: List[str], offset_px: int) -> Image.Image:
    T = WHEEL
    V = T["visible"]
    TW, TH, PAD = T["tile_w"], T["tile_h"], T["pad"]
    vw = PAD + V*(TW+PAD)
    vh = PAD*2 + TH + 22
    canvas = Image.new("RGBA", (vw, vh), T["bg"])
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    def rrect(x0,y0,x1,y1,rad=10,fill=(0,0,0,180)):
        try:
            draw.rounded_rectangle([x0,y0,x1,y1], radius=rad, fill=fill)
        except Exception:
            draw.rectangle([x0,y0,x1,y1], fill=fill)

    # draw tiles
    x = PAD - offset_px
    for nm in seq:
        if x > vw: break
        rrect(x, PAD, x+TW, PAD+TH, 10, WHEEL["card"])
        imgs = find_images_for(nm)
        main, _ = pick_main_and_stats(imgs)
        if main and os.path.isfile(main):
            try:
                im = Image.open(main).convert("RGBA")
                im.thumbnail((TW-10, TH-28))
                ix = x + (TW-im.width)//2
                iy = PAD + 4
                canvas.paste(im, (ix,iy), im)
            except Exception:
                pass
        w,h = _text_size(draw, font, nm)
        draw.text((x+(TW-w)//2, PAD+TH-2), nm[:22], fill=(240,240,240,255), font=font)
        x += TW + PAD

    # highlight the center slot
    cx = PAD + (V//2)*(TW+PAD)
    rrect(cx-2, PAD-2, cx+TW+2, PAD+TH+2, 8, (250,220,80,120))
    return canvas

def _ease_out_cubic(t: float) -> float:
    return 1 - (1 - t)**3

def build_case_gif_stopping(pool: List[str]) -> Tuple[str, str]:
    """Create an animated GIF that slows down and stops with the winner centered."""
    V = WHEEL["visible"]
    TW, PAD = WHEEL["tile_w"], WHEEL["pad"]

    winner = random.choice(pool)
    # Build a sequence that ensures the winner is in the middle at the end
    pre = random.choices(pool, k=V+5)
    seq = pre + [winner] + random.choices(pool, k=2)

    center_x = PAD + (V//2)*(TW+PAD)
    winner_index = len(pre)
    final_offset = PAD + winner_index*(TW+PAD) - center_x

    frames = max(14, 20)
    offsets = []
    for i in range(frames-1):
        t = i/(frames-1)
        offsets.append(int(final_offset * _ease_out_cubic(t)))
        # ensures monotonic increase
        if i and offsets[i] < offsets[i-1]:
            offsets[i] = offsets[i-1]
    offsets.append(final_offset)

    images = []
    durations = []
    for i, off in enumerate(offsets):
        frame = _frame_strip(seq, off).convert("P", palette=Image.ADAPTIVE)
        images.append(frame)
        durations.append(WHEEL["final_hold_ms"] if i == len(offsets)-1 else WHEEL["frame_ms"])

    out = _save_path("wheel_case", "gif")
    images[0].save(
        out, save_all=True, append_images=images[1:],
        duration=durations, loop=0, disposal=2
    )
    return out, winner

# ----------------------------- Discord setup ---------------------------------

intents = discord.Intents.default()  # no privileged intents required
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

@bot.event
async def on_ready():
    print(f"[ready] Logged in as {bot.user} ({bot.user.id})")
    try:
        await tree.sync()
        print("[ready] Slash commands synced.")
    except Exception as e:
        print("[ready] sync failed:", e)

# ------------------------------- Commands ------------------------------------

@tree.command(name="reload", description="Rescan unit images (admin)")
@app_commands.checks.has_permissions(administrator=True)
async def reload_cmd(interaction: discord.Interaction):
    rescan_images()
    await interaction.response.send_message(f"Rescanned. Found **{len(IMAGES)}** units.", ephemeral=True)

@tree.command(name="units", description="Show a list of available units (paged)")
@app_commands.describe(page="Page number (starting at 1)")
async def units_cmd(interaction: discord.Interaction, page: Optional[int] = 1):
    await interaction.response.defer(thinking=True, ephemeral=False)
    names = sorted(" ".join(w.capitalize() for w in k.split()) for k in IMAGES.keys())
    if not names:
        await interaction.followup.send("No unit images found in `units_assets/`.")
        return
    per_page = 20
    page = max(1, int(page or 1))
    total_pages = (len(names) + per_page - 1) // per_page
    page = min(page, total_pages)
    start = (page-1)*per_page
    subset = names[start:start+per_page]

    desc = "\n".join(f"{i+1}. {n}" for i, n in enumerate(subset, start=start))
    emb = discord.Embed(title=f"Units (page {page}/{total_pages})", description=desc, color=discord.Color.blurple())
    emb.set_footer(text=f"{len(names)} total units — put unit images in /{ASSETS_DIR}")
    await interaction.followup.send(embed=emb)

@tree.command(name="unit", description="Show a unit with image + stats if available")
@app_commands.describe(name="Unit name (case-insensitive; fuzzy)")
async def unit_cmd(interaction: discord.Interaction, name: str):
    await interaction.response.defer(thinking=True, ephemeral=False)
    path = build_unit_composite(name)
    if not path:
        await interaction.followup.send(f"Couldn't find images for **{name}** in `{ASSETS_DIR}`.")
        return
    file = discord.File(path, filename=os.path.basename(path))
    emb = discord.Embed(title="Unit", description=name, color=discord.Color.green())
    emb.set_image(url=f"attachment://{os.path.basename(path)}")
    await interaction.followup.send(embed=emb, file=file)

@tree.command(name="wheel", description="Open a case: animated strip that stops on a winner")
async def wheel_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=False)

    pool = _unit_pool_from_images()
    if not pool:
        await interaction.followup.send("No unit images found. Put them in the `units_assets/` folder.")
        return

    gif_path, winner = build_case_gif_stopping(pool)
    if not os.path.isfile(gif_path):
        await interaction.followup.send("Could not generate GIF (is Pillow installed?)")
        return

    gif_name = os.path.basename(gif_path)
    e = discord.Embed(title="🎁 Opening case…", description=f"Landing on **{winner}**", color=discord.Color.gold())
    e.set_image(url=f"attachment://{gif_name}")
    await interaction.followup.send(embed=e, file=discord.File(gif_path, filename=gif_name))

    imgs = find_images_for(winner)
    main, _ = pick_main_and_stats(imgs)
    if main and os.path.isfile(main):
        await interaction.followup.send(
            embed=discord.Embed(title=f"🎉 Winner: {winner}", color=discord.Color.green()),
            file=discord.File(main, filename=os.path.basename(main))
        )
    else:
        await interaction.followup.send(f"🎉 Winner: **{winner}** (no image was found).")

# ------------------------------ Token loader ---------------------------------

def load_token() -> str:
    tok = os.getenv("DISCORD_TOKEN")
    if tok:
        return tok.strip()
    if os.path.exists("token.txt"):
        with open("token.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    raise RuntimeError("No Discord token found! Set DISCORD_TOKEN or create token.txt")

def main():
    token = load_token()
    bot.run(token)

if __name__ == "__main__":
    print("[boot] starting… OUTPUT_DIR:", OUTPUT_DIR)
    main()
