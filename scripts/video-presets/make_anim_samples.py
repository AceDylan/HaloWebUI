#!/usr/bin/env python3
"""Generate lightweight animated 9:16 preview samples + 16:9 blurred-backdrop posters
for the four animation-first visual styles in static/video-presets/v2/:
  - anime-cartoon (日漫卡通)
  - comic-pop     (潮酷漫格)
  - guochao       (国潮插画)
  - storybook     (治愈绘本)

Outputs per style:
- <key>.mp4: 360x640, 30fps, 4s, H.264 yuv420p +faststart, muted
- <key>.jpg: 640x360 blurred-backdrop + centered vertical hero frame
"""

import math
import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "static" / "video-presets" / "v2"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 360, 640
FPS = 30
DURATION = 4.0
FRAMES = int(FPS * DURATION)

FONT_SANS_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_SERIF_BOLD = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (path, FONT_SANS_BOLD, FONT_SERIF_BOLD):
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_rgb(c1, c2, t: float):
    t = clamp(t)
    return (int(lerp(c1[0], c2[0], t)), int(lerp(c1[1], c2[1], t)), int(lerp(c1[2], c2[2], t)))


def vertical_gradient(w: int, h: int, top_rgb, mid_rgb, bot_rgb) -> Image.Image:
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        f = y / max(1, h - 1)
        c = lerp_rgb(top_rgb, mid_rgb, f * 2) if f < 0.5 else lerp_rgb(mid_rgb, bot_rgb, (f - 0.5) * 2)
        draw.line([(0, y), (w, y)], fill=c)
    return img


def draw_badge(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, bg, fg):
    font = load_font(FONT_SANS_BOLD, 13)
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.rounded_rectangle((x, y, x + tw + 18, y + th + 10), radius=12, fill=bg)
    draw.text((x + 9, y + 4), text, font=font, fill=fg)


# --- 1. anime-cartoon (日漫卡通：晴空落日 + 眨眼微笑卡通角色 + 云朵樱花) ---
def render_anime_cartoon(i: int) -> Image.Image:
    t = i / FPS
    img = vertical_gradient(W, H, (56, 152, 236), (138, 206, 250), (255, 224, 178))
    draw = ImageDraw.Draw(img, "RGBA")

    # Warm sun & halo
    sun_x, sun_y = 278, int(138 + 6 * math.sin(t * 1.4))
    draw.ellipse((sun_x - 62, sun_y - 62, sun_x + 62, sun_y + 62), fill=(255, 240, 180, 65))
    draw.ellipse((sun_x - 34, sun_y - 34, sun_x + 34, sun_y + 34), fill=(255, 247, 205, 235))

    # Drifting cel-shaded clouds
    for cx0, cy, sc, spd in [(65, 118, 1.0, 14), (245, 210, 0.85, 10), (140, 275, 0.7, 18)]:
        cx = int((cx0 + t * spd) % (W + 140)) - 70
        r = int(28 * sc)
        draw.ellipse((cx - r, cy - r // 2, cx + r, cy + r // 2), fill=(255, 255, 255, 235))
        draw.ellipse((cx - r // 2, cy - r, cx + r // 2 + 12, cy + r // 3), fill=(255, 255, 255, 245))
        draw.ellipse((cx + 4, cy - r // 2 - 4, cx + r + 18, cy + r // 2), fill=(255, 255, 255, 235))

    # Distant hills & cel rooftop skyline (parallax shift)
    px = int(12 * math.sin(t * 1.1))
    draw.polygon([(0, 440), (95 + px, 385), (210 + px, 425), (360, 375), (360, 640), (0, 640)], fill=(116, 165, 214, 255))
    draw.polygon([(0, 468), (130 - px, 430), (265 - px, 455), (360, 425), (360, 640), (0, 640)], fill=(64, 98, 146, 255))

    # Town fence railing
    draw.rectangle((0, 492, W, 502), fill=(36, 52, 82, 255))
    for rx in range(20, W, 38):
        draw.rectangle((rx, 492, rx + 5, 570), fill=(36, 52, 82, 255))

    # Animated cartoon character (bobbing gently, blinking, hair swaying, waving hand)
    bob = int(5 * math.sin(t * 3.1))
    cx, cy = W // 2, 412 + bob
    ink = (30, 38, 62, 255)

    # Back hair (sway)
    sway = int(7 * math.sin(t * 4.2))
    draw.polygon(
        [(cx - 56, cy - 35), (cx + 56, cy - 35), (cx + 68 + sway, cy + 56), (cx - 64 + sway, cy + 56)],
        fill=(48, 62, 108, 255),
        outline=ink,
    )

    # Torso & jacket (cel bright orange-coral + white collar)
    draw.rounded_rectangle((cx - 54, cy + 48, cx + 54, cy + 168), radius=26, fill=(251, 146, 60, 255), outline=ink, width=3)
    draw.polygon([(cx - 24, cy + 50), (cx, cy + 88), (cx + 24, cy + 50)], fill=(255, 250, 240, 255), outline=ink)
    draw.polygon([(cx - 6, cy + 84), (cx + 6, cy + 84), (cx + 9, cy + 122), (cx - 9, cy + 122)], fill=(244, 63, 94, 255), outline=ink)

    # Waving right arm
    wave_ang = -0.55 + 0.38 * math.sin(t * 6.0)
    ax0, ay0 = cx + 48, cy + 86
    ax1 = int(ax0 + 52 * math.cos(wave_ang))
    ay1 = int(ay0 + 52 * math.sin(wave_ang))
    draw.line([(ax0, ay0), (ax1, ay1)], fill=(251, 146, 60, 255), width=20)
    draw.ellipse((ax1 - 12, ay1 - 12, ax1 + 12, ay1 + 12), fill=(255, 224, 198, 255), outline=ink, width=2)

    # Neck & head
    draw.rectangle((cx - 12, cy + 32, cx + 12, cy + 56), fill=(255, 214, 186, 255), outline=ink, width=2)
    draw.ellipse((cx - 48, cy - 58, cx + 48, cy + 42), fill=(255, 229, 206, 255), outline=ink, width=3)

    # Front hair bangs
    draw.pieslice((cx - 52, cy - 66, cx + 52, cy + 28), 185, 355, fill=(56, 74, 128, 255), outline=ink, width=3)
    draw.polygon([(cx - 32, cy - 28), (cx - 16, cy - 4), (cx - 2, cy - 28)], fill=(56, 74, 128, 255))
    draw.polygon([(cx + 2, cy - 28), (cx + 18, cy - 2), (cx + 34, cy - 28)], fill=(56, 74, 128, 255))

    # Eyes (blink once per ~2s)
    blink = (t % 2.1) > 1.96
    for ex in (cx - 20, cx + 20):
        if blink:
            draw.arc((ex - 10, cy - 8, ex + 10, cy + 8), 15, 165, fill=ink, width=3)
        else:
            draw.ellipse((ex - 9, cy - 11, ex + 9, cy + 11), fill=(35, 48, 86, 255))
            draw.ellipse((ex - 5, cy - 8, ex + 1, cy - 2), fill=(255, 255, 255, 255))
            draw.ellipse((ex + 1, cy + 2, ex + 5, cy + 6), fill=(125, 211, 252, 230))
    # Blush & happy smile
    draw.ellipse((cx - 34, cy + 8, cx - 20, cy + 17), fill=(244, 114, 182, 120))
    draw.ellipse((cx + 20, cy + 8, cx + 34, cy + 17), fill=(244, 114, 182, 120))
    draw.arc((cx - 11, cy + 12, cx + 11, cy + 27), 15, 165, fill=(210, 75, 95, 255), width=3)

    # Drifting sakura petals
    for k in range(12):
        px0 = (k * 43 + t * (48 + (k % 3) * 14)) % (W + 40) - 20
        py0 = (k * 67 + t * (52 + (k % 4) * 11)) % (H + 40) - 20
        rot = math.sin(t * 4 + k) * 4
        draw.ellipse((px0 - 6, py0 - 3 + rot, px0 + 6, py0 + 4 + rot), fill=(255, 188, 214, 220))

    draw_badge(draw, "日漫卡通", 20, 24, (30, 41, 59, 195), (255, 255, 255, 255))
    return img


# --- 2. comic-pop (潮酷漫格：上下斜切漫画分格 + 卡通小人反差演绎 + 速度线网点) ---
def render_comic_pop(i: int) -> Image.Image:
    t = i / FPS
    img = Image.new("RGB", (W, H), (17, 19, 34))
    draw = ImageDraw.Draw(img, "RGBA")

    # Top comic panel (coral-red energy, frantic clock & cartoon character)
    split_y = int(312 + 10 * math.sin(t * 2.5))
    draw.polygon([(14, 18), (W - 14, 18), (W - 14, split_y - 18), (14, split_y + 12)], fill=(255, 59, 92, 255), outline=(10, 12, 22, 255))
    # Halftone dots in top panel
    for gx in range(28, W - 20, 22):
        for gy in range(36, split_y - 26, 22):
            draw.ellipse((gx - 2, gy - 2, gx + 2, gy + 2), fill=(255, 214, 10, 55))

    # Top panel animated cartoon character (stressed / tangled swirl)
    jx = int(4 * math.sin(t * 24))
    tx, ty = 115 + jx, 175
    ink = (15, 18, 32, 255)
    draw.ellipse((tx - 38, ty - 38, tx + 38, ty + 38), fill=(255, 232, 200, 255), outline=ink, width=4)
    draw.rounded_rectangle((tx - 36, ty + 34, tx + 36, ty + 104), radius=16, fill=(45, 55, 90, 255), outline=ink, width=4)
    # Dizzy X eyes
    for ex in (tx - 14, tx + 14):
        draw.line([(ex - 6, ty - 8), (ex + 6, ty + 4)], fill=ink, width=3)
        draw.line([(ex + 6, ty - 8), (ex - 6, ty + 4)], fill=ink, width=3)
    draw.arc((tx - 12, ty + 12, tx + 12, ty + 26), 190, 350, fill=ink, width=3)
    # Spinning alarm clock prop on top right
    clx, cly = 258, int(152 + 8 * math.sin(t * 14))
    draw.ellipse((clx - 36, cly - 36, clx + 36, cly + 36), fill=(255, 214, 10, 255), outline=ink, width=4)
    draw.ellipse((clx - 27, cly - 27, clx + 27, cly + 27), fill=(255, 255, 255, 255), outline=ink, width=2)
    ang = t * 7.5
    draw.line([(clx, cly), (int(clx + 18 * math.cos(ang)), int(cly + 18 * math.sin(ang)))], fill=(255, 59, 92, 255), width=4)
    draw.line([(clx, cly), (int(clx + 12 * math.cos(ang * 0.25)), int(cly + 12 * math.sin(ang * 0.25)))], fill=ink, width=4)

    # Bottom comic panel (electric cyan-teal energy, confident rocket & smiling hero)
    draw.polygon([(14, split_y + 26), (W - 14, split_y - 4), (W - 14, H - 18), (14, H - 18)], fill=(20, 184, 166, 255), outline=ink)
    # Radial speed lines from center-right
    ocx, ocy = 248, 488
    for k in range(16):
        a = k * (math.pi * 2 / 16) + t * 0.5
        r1 = 58 + (k % 3) * 14
        r2 = 160
        draw.line([(ocx + r1 * math.cos(a), ocy + r1 * math.sin(a)), (ocx + r2 * math.cos(a), ocy + r2 * math.sin(a))], fill=(255, 255, 255, 80), width=2)

    # Confident hero character on bottom left
    hy = int(474 + 6 * math.sin(t * 4.5))
    hx = 112
    draw.ellipse((hx - 40, hy - 40, hx + 40, hy + 40), fill=(255, 234, 204, 255), outline=ink, width=4)
    draw.rounded_rectangle((hx - 38, hy + 36, hx + 38, hy + 112), radius=18, fill=(255, 214, 10, 255), outline=ink, width=4)
    # Cool sunglasses
    draw.rounded_rectangle((hx - 28, hy - 14, hx - 3, hy + 2), radius=4, fill=ink)
    draw.rounded_rectangle((hx + 3, hy - 14, hx + 28, hy + 2), radius=4, fill=ink)
    draw.line([(hx - 3, hy - 7), (hx + 3, hy - 7)], fill=ink, width=3)
    draw.arc((hx - 14, hy + 8, hx + 14, hy + 24), 15, 165, fill=ink, width=3)

    # Launching cartoon rocket prop on bottom right
    ry = int(495 - 18 * math.sin(t * 3.5))
    rx = 252
    draw.polygon([(rx, ry - 52), (rx + 24, ry - 8), (rx + 20, ry + 34), (rx - 20, ry + 34), (rx - 24, ry - 8)], fill=(255, 255, 255, 255), outline=ink)
    draw.ellipse((rx - 10, ry - 14, rx + 10, ry + 6), fill=(56, 189, 248, 255), outline=ink, width=3)
    flame = int(18 + 10 * math.sin(t * 22))
    draw.polygon([(rx - 12, ry + 34), (rx + 12, ry + 34), (rx, ry + 34 + flame)], fill=(255, 214, 10, 255))

    # Diagonal comic gutter bar + lightning badge
    draw.polygon([(0, split_y + 8), (W, split_y - 22), (W, split_y - 4), (0, split_y + 26)], fill=(17, 19, 34, 255))
    draw.polygon([(168, split_y - 28), (196, split_y - 28), (182, split_y - 4), (198, split_y - 4), (168, split_y + 28), (176, split_y + 2), (160, split_y + 2)], fill=(255, 214, 10, 255), outline=ink)

    draw_badge(draw, "潮酷漫格", 20, 26, (17, 19, 34, 220), (255, 214, 10, 255))
    return img


# --- 3. guochao (国潮插画：黛墨山海 + 朱砂飞檐 + 升腾孔明灯 + 祥云金尘) ---
def render_guochao(i: int) -> Image.Image:
    t = i / FPS
    img = vertical_gradient(W, H, (16, 22, 38), (28, 52, 68), (42, 30, 36))
    draw = ImageDraw.Draw(img, "RGBA")

    # Crimson moon + gold ring halo
    mx, my = 212, 162
    draw.ellipse((mx - 76, my - 76, mx + 76, my + 76), fill=(230, 57, 70, 48))
    draw.ellipse((mx - 54, my - 54, mx + 54, my + 54), fill=(230, 57, 70, 240))
    draw.ellipse((mx - 62, my - 62, mx + 62, my + 62), outline=(233, 196, 106, 185), width=2)

    # Layered turquoise & gold-rimmed mountains
    s1 = int(10 * math.sin(t * 0.9))
    draw.polygon([(0, 400), (88 + s1, 286), (178 + s1, 370), (284 + s1, 268), (360, 345), (360, 640), (0, 640)], fill=(34, 102, 104, 255))
    draw.line([(0, 400), (88 + s1, 286), (178 + s1, 370), (284 + s1, 268), (360, 345)], fill=(233, 196, 106, 200), width=3)

    s2 = int(-14 * math.sin(t * 1.1))
    draw.polygon([(0, 462), (112 + s2, 372), (225 + s2, 438), (320 + s2, 365), (360, 402), (360, 640), (0, 640)], fill=(22, 64, 72, 255))
    draw.line([(0, 462), (112 + s2, 372), (225 + s2, 438), (320 + s2, 365), (360, 402)], fill=(233, 196, 106, 155), width=2)

    # Traditional crimson pavilion silhouette on cliff
    px, py = 104, 412
    draw.rectangle((px - 32, py, px + 32, py + 44), fill=(24, 20, 28, 255))
    draw.polygon([(px - 52, py + 4), (px, py - 24), (px + 52, py + 4)], fill=(214, 48, 58, 255), outline=(233, 196, 106, 230))
    draw.polygon([(px - 38, py - 14), (px, py - 38), (px + 38, py - 14)], fill=(214, 48, 58, 255), outline=(233, 196, 106, 230))
    draw.rectangle((px - 8, py + 12, px + 8, py + 32), fill=(255, 214, 112, 230))

    # Drifting auspicious clouds
    for cy, spd, phase in [(238, 16, 0), (332, -12, 2), (496, 18, 4)]:
        cx = int((phase * 70 + t * spd) % (W + 140)) - 70
        draw.rounded_rectangle((cx - 46, cy - 10, cx + 46, cy + 10), radius=10, fill=(246, 239, 226, 215))
        draw.ellipse((cx - 28, cy - 22, cx + 10, cy + 8), fill=(246, 239, 226, 225))
        draw.rounded_rectangle((cx - 38, cy - 4, cx + 38, cy + 4), radius=4, outline=(233, 196, 106, 180), width=1)

    # Floating glowing lanterns rising smoothly
    for k, (lx0, ly0, sc) in enumerate([(62, 540, 0.9), (268, 500, 1.1), (186, 610, 0.8), (305, 340, 0.7), (144, 280, 0.75)]):
        ly = (ly0 - t * (34 + k * 5)) % (H + 90) - 45
        lx = lx0 + 10 * math.sin(t * 2.1 + k)
        rw, rh = int(14 * sc), int(18 * sc)
        draw.ellipse((lx - rw * 2, ly - rh * 2, lx + rw * 2, ly + rh * 2), fill=(255, 196, 86, 55))
        draw.rounded_rectangle((lx - rw, ly - rh, lx + rw, ly + rh), radius=6, fill=(245, 158, 66, 245), outline=(255, 236, 179, 255), width=2)
        draw.ellipse((lx - rw // 2, ly - rh // 3, lx + rw // 2, ly + rh // 2), fill=(255, 248, 210, 235))

    # Gold dust particles
    for k in range(18):
        gx = (k * 37 + t * 14) % W
        gy = (k * 59 - t * (22 + (k % 3) * 8)) % H
        draw.ellipse((gx - 2, gy - 2, gx + 2, gy + 2), fill=(246, 212, 122, 190))

    draw_badge(draw, "国潮插画", 20, 24, (214, 48, 58, 225), (255, 248, 225, 255))
    return img


# --- 4. storybook (治愈绘本：暖暮窗景 + 晃尾巴小橘猫 + 热气咖啡 + 萤火微光) ---
def render_storybook(i: int) -> Image.Image:
    t = i / FPS
    img = vertical_gradient(W, H, (38, 49, 76), (82, 92, 128), (238, 172, 118))
    draw = ImageDraw.Draw(img, "RGBA")

    # Twinkling stars outside the window
    for k in range(14):
        sx = 34 + (k * 53) % (W - 68)
        sy = 46 + (k * 37) % 190
        alpha = int(120 + 110 * abs(math.sin(t * 2.5 + k)))
        draw.ellipse((sx - 2, sy - 2, sx + 2, sy + 2), fill=(255, 246, 214, alpha))

    # Warm crescent moon
    draw.ellipse((238, 86, 294, 142), fill=(255, 240, 196, 245))
    draw.ellipse((254, 80, 306, 134), fill=(52, 64, 96, 255))

    # Soft swaying tree silhouettes outside
    sway = int(6 * math.sin(t * 1.6))
    draw.ellipse((-30 + sway, 240, 130 + sway, 400), fill=(54, 78, 86, 220))
    draw.ellipse((250 - sway, 250, 400 - sway, 410), fill=(54, 78, 86, 220))

    # Cozy window frame (storybook wood)
    wood = (74, 52, 44, 255)
    draw.rectangle((0, 0, 26, H), fill=wood)
    draw.rectangle((W - 26, 0, W, H), fill=wood)
    draw.rectangle((0, 0, W, 30), fill=wood)
    draw.rectangle((0, 404, W, 430), fill=(116, 82, 64, 255))
    draw.rectangle((0, 430, W, H), fill=(58, 42, 38, 255))
    draw.rectangle((W // 2 - 5, 30, W // 2 + 5, 404), fill=wood)
    draw.rectangle((26, 224, W - 26, 234), fill=wood)

    # Warm window light beam
    beam = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(beam)
    bd.polygon([(26, 260), (W - 26, 190), (W, 560), (0, 610)], fill=(255, 210, 140, 34))
    beam = beam.filter(ImageFilter.GaussianBlur(12))
    img = Image.alpha_composite(img.convert("RGBA"), beam).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    # Cute orange storybook cat sitting on the windowsill, swaying tail
    cx, cy = 128, 366
    ink = (78, 48, 36, 255)
    # Swaying tail
    tail_x = cx - 42 + int(16 * math.sin(t * 3.2))
    draw.line([(cx - 26, cy + 28), (cx - 46, cy + 6), (tail_x, cy - 22)], fill=(244, 162, 97, 255), width=11)
    # Body & head
    draw.ellipse((cx - 34, cy - 8, cx + 34, cy + 44), fill=(244, 162, 97, 255), outline=ink, width=2)
    draw.ellipse((cx - 26, cy - 48, cx + 26, cy - 2), fill=(244, 162, 97, 255), outline=ink, width=2)
    draw.polygon([(cx - 24, cy - 38), (cx - 18, cy - 62), (cx - 4, cy - 44)], fill=(244, 162, 97, 255), outline=ink)
    draw.polygon([(cx + 24, cy - 38), (cx + 18, cy - 62), (cx + 4, cy - 44)], fill=(244, 162, 97, 255), outline=ink)
    # Happy closed eyes
    draw.arc((cx - 15, cy - 30, cx - 3, cy - 20), 190, 350, fill=ink, width=2)
    draw.arc((cx + 3, cy - 30, cx + 15, cy - 20), 190, 350, fill=ink, width=2)

    # Warm steaming mug on the right side of the sill
    mx, my = 248, 378
    draw.rounded_rectangle((mx - 20, my - 12, mx + 20, my + 26), radius=6, fill=(250, 243, 227, 255), outline=ink, width=2)
    draw.arc((mx + 12, my - 4, mx + 30, my + 16), 270, 90, fill=(250, 243, 227, 255), width=4)
    # Rising gentle steam curls
    for k in range(3):
        sy = my - 22 - int((t * 24 + k * 16) % 44)
        sx = mx - 10 + k * 10 + int(5 * math.sin(t * 3 + k))
        alpha = int(170 * (1.0 - ((my - 22 - sy) / 44.0)))
        draw.ellipse((sx - 4, sy - 6, sx + 4, sy + 6), fill=(255, 248, 232, max(20, alpha)))

    # Floating fireflies / warm pollen
    for k in range(10):
        fx = 44 + (k * 67 + int(18 * math.sin(t * 1.5 + k))) % (W - 88)
        fy = 120 + (k * 83 - int(t * 16)) % 360
        r = 3 + (k % 2)
        draw.ellipse((fx - r * 2, fy - r * 2, fx + r * 2, fy + r * 2), fill=(255, 226, 130, 75))
        draw.ellipse((fx - r, fy - r, fx + r, fy + r), fill=(255, 246, 200, 220))

    draw_badge(draw, "治愈绘本", 36, 42, (58, 42, 38, 210), (250, 243, 227, 255))
    return img


STYLES = [
    ("anime-cartoon", render_anime_cartoon, 1.2),
    ("comic-pop", render_comic_pop, 1.5),
    ("guochao", render_guochao, 1.8),
    ("storybook", render_storybook, 2.0),
]


def make_poster(vertical_img: Image.Image, out_jpg: Path) -> None:
    """Create 640x360 blurred-backdrop poster matching hanazi.jpg."""
    bg = vertical_img.resize((640, int(640 * H / W)), Image.LANCZOS)
    top = (bg.height - 360) // 2
    bg = bg.crop((0, top, 640, top + 360)).filter(ImageFilter.GaussianBlur(18))
    fg_w = int(round(360 * W / H))
    fg = vertical_img.resize((fg_w, 360), Image.LANCZOS)
    bg.paste(fg, ((640 - fg_w) // 2, 0))
    bg.save(out_jpg, format="JPEG", quality=88, optimize=True)


def build_style(key: str, renderer, hero_sec: float) -> None:
    mp4_path = OUT / f"{key}.mp4"
    jpg_path = OUT / f"{key}.jpg"
    hero_idx = min(FRAMES - 1, int(hero_sec * FPS))

    cmd = [
        "ffmpeg", "-v", "error", "-y", "-threads", "2",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
        "-i", "pipe:0",
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "24",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(mp4_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    hero_img = None
    for idx in range(FRAMES):
        frame = renderer(idx)
        if idx == hero_idx:
            hero_img = frame.copy()
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed for {key} (rc={rc})")
    assert hero_img is not None
    make_poster(hero_img, jpg_path)
    print(f"generated {key}: mp4={mp4_path.stat().st_size}B jpg={jpg_path.stat().st_size}B")


if __name__ == "__main__":
    for key, fn, hero_sec in STYLES:
        build_style(key, fn, hero_sec)
