"""Turns the raw renders from render_visuals.py into the README pictures:
docs/hero.gif and docs/rule_*.png (titles, labels, captions).

Run after render_visuals.py:  python docs/visuals/compose.py
Needs Pillow and ffmpeg. Fonts: Segoe UI (Windows); swap FONT/BOLD elsewhere.
"""

import json
import os
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "_render")
DOCS = os.path.dirname(HERE)
FONT = r"C:\Windows\Fonts\segoeui.ttf"
BOLD = r"C:\Windows\Fonts\seguisb.ttf" if os.path.exists(r"C:\Windows\Fonts\seguisb.ttf") else r"C:\Windows\Fonts\segoeuib.ttf"

BG = (30, 32, 36)
TEXT = (235, 235, 238)
MUTED = (160, 163, 170)
ORANGE = (255, 140, 20)
KEPT = (120, 124, 132)


def font(size, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


def label(draw, at, text, dx, dy, hot):
    x, y = at
    f = font(26, bold=hot)
    w = draw.textlength(text, font=f)
    bx, by = x + dx, y + dy
    # Keep the box inside the picture.
    bx = max(16, min(bx, draw.im.size[0] - w - 44))
    by = max(16, min(by, draw.im.size[1] - 60))
    box = (bx, by, bx + w + 28, by + 46)
    colour = ORANGE if hot else KEPT
    # Leader from the dot to the nearest edge of the box.
    lx = min(max(x, box[0]), box[2])
    ly = min(max(y, box[1]), box[3])
    draw.line((x, y, lx, ly), fill=colour, width=3)
    draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=colour, outline=(20, 20, 20), width=2)
    draw.rounded_rectangle(box, radius=10, fill=(22, 23, 26), outline=colour, width=3)
    draw.text((bx + 14, by + 6), text, font=f, fill=ORANGE if hot else TEXT)


RULES = {
    "contact": ("1  Contact",
                "A face is selected when other parts lie on all of it. Covers from several parts add up."),
    "planes": ("2  Planes",
               "A plane hides what it lies on when it faces out. Facing in, the plane is the hidden one."),
    "buried": ("3  Buried",
               "A face is selected when it sits inside another closed part."),
    "holes": ("4  Already cleaned",
              "Parts with deleted faces still count as closed when neighbours seal the holes."),
}


def panel(name, labels):
    raw = Image.open(os.path.join(RAW, f"panel_{name}.png")).convert("RGB")
    w, h = raw.size
    head = 130
    out = Image.new("RGB", (w, h + head), BG)
    out.paste(raw, (0, head))
    d = ImageDraw.Draw(out)
    title, sub = RULES[name]
    d.text((40, 24), title, font=font(44, bold=True), fill=TEXT)
    d.text((40, 82), sub, font=font(26), fill=MUTED)
    # Legend, top right.
    lx = w - 360
    d.rounded_rectangle((lx, 34, lx + 26, 60), radius=5, fill=ORANGE)
    d.text((lx + 38, 30), "selected", font=font(24), fill=TEXT)
    d.rounded_rectangle((lx + 170, 34, lx + 196, 60), radius=5, fill=(150, 150, 146))
    d.text((lx + 208, 30), "kept", font=font(24), fill=TEXT)
    for item in labels:
        at = (item["at"][0], item["at"][1] + head)
        label(d, at, item["text"], item["dx"], item["dy"], item["hot"])
    path = os.path.join(DOCS, f"rule_{name}.png")
    out.save(path, optimize=True)
    return path


CAPTIONS = {
    "piece": ("A piece made of {parts} separate parts, {before} faces", None),
    "apart": ("Pulled apart here only so you can see the covered faces", None),
    "selected": ("Select  >  Select All by Trait  >  ", "Covered Faces"),
    "below": ("{selected} faces nobody can ever see, selected in one go", None),
    "deleted": ("X  >  Faces", None),
    "together": ("Back together", None),
    "result": ("Looks exactly the same, with {after} faces instead of {before}", None),
}


def hero(info):
    frames_dir = os.path.join(RAW, "hero")
    tmp = os.path.join(RAW, "hero_captioned")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    f_cap = font(30)
    f_hot = font(30, bold=True)
    for i, key in enumerate(info["timeline"]):
        im = Image.open(os.path.join(frames_dir, f"{i:03d}.png")).convert("RGB")
        w, h = im.size
        d = ImageDraw.Draw(im, "RGBA")
        d.rectangle((0, h - 70, w, h), fill=(16, 17, 20, 225))
        text, hot = CAPTIONS[key]
        text = text.format(**info)
        tw = d.textlength(text, font=f_cap) + (d.textlength(hot, font=f_hot) if hot else 0)
        x = (w - tw) / 2
        d.text((x, h - 56), text, font=f_cap, fill=TEXT)
        if hot:
            d.text((x + d.textlength(text, font=f_cap), h - 56), hot, font=f_hot, fill=ORANGE)
        im.save(os.path.join(tmp, f"{i:03d}.png"))
    out = os.path.join(DOCS, "hero.gif")
    pattern = os.path.join(tmp, "%03d.png")
    graph = "fps=20,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "24", "-i", pattern,
                    "-filter_complex", graph, "-loop", "0", out], check=True)
    return out


if __name__ == "__main__":
    with open(os.path.join(RAW, "labels.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    for name in RULES:
        print(panel(name, data[name]))
    print(hero(data["hero"]))
