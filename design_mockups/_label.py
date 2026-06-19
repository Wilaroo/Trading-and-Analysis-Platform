from PIL import Image, ImageDraw, ImageFont

SANS = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
MONO = "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"

# (file, track_tag, track_color, title)
JOBS = [
    ("trackA_mission_control.png", "TRACK A", (6, 182, 212),
     "Incremental v5  \u00b7  Mission Control + Regime Weather + mini provenance-rings + inline Trade-Trace"),
    ("trackA_whytrace_modal.png", "TRACK A", (6, 182, 212),
     "Incremental v5  \u00b7  Why-Trace modal (7 plain-language stages, incl. non-trade)"),
    ("trackB_cockpit_hero.png", "TRACK B", (245, 158, 11),
     "V6 Cockpit Redesign  \u00b7  Heartbeat bar + Risk rail + Regime header + Why-Trace funnel (hero) + consoles"),
    ("trackB_provenance_verdict.png", "TRACK B", (245, 158, 11),
     "V6 Cockpit Redesign  \u00b7  Provenance Ring + unified Decision Authority verdict + STAND-DOWN state"),
    ("trackB_strategy_autonomy.png", "TRACK B", (245, 158, 11),
     "V6 Cockpit Redesign  \u00b7  Strategy Autonomy console (family \u00d7 regime-fit \u00d7 edge-decay \u00d7 ON/OFF)"),
]

BAR_H = 84
BG = (21, 28, 36)

for fn, tag, color, title in JOBS:
    src = Image.open(fn).convert("RGB")
    W = src.width
    out = Image.new("RGB", (W, src.height + BAR_H), BG)
    out.paste(src, (0, BAR_H))
    d = ImageDraw.Draw(out)
    # left color accent block
    d.rectangle([0, 0, 10, BAR_H], fill=color)
    # track tag pill
    tag_font = ImageFont.truetype(SANS, 34)
    sub_font = ImageFont.truetype(MONO, 19)
    tb = d.textbbox((0, 0), tag, font=tag_font)
    pad = 16
    pill_w = (tb[2] - tb[0]) + pad * 2
    d.rounded_rectangle([28, 22, 28 + pill_w, 22 + 40], radius=8, fill=color)
    d.text((28 + pad, 26), tag, font=tag_font, fill=(10, 14, 18))
    # title text
    d.text((28 + pill_w + 24, 18), title.split("  \u00b7  ")[0], font=sub_font, fill=(248, 250, 252))
    d.text((28 + pill_w + 24, 46), title.split("  \u00b7  ", 1)[1], font=sub_font, fill=(148, 163, 184))
    # bottom hairline
    d.line([0, BAR_H - 1, W, BAR_H - 1], fill=(60, 72, 88), width=2)
    out.save("labeled_" + fn)
    print("labeled_" + fn, out.size)
