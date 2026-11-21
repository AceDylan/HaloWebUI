#!/usr/bin/env python3
"""Generate lightweight animated 9:16 preview samples + 16:9 blurred-backdrop posters
for the four Douyin-native viral styles in static/video-presets/v2/.

Outputs per style:
- <key>.mp4: 360x640, 30fps, 4s, H.264 yuv420p +faststart, muted
- <key>.jpg: 640x360 blurred-backdrop + centered vertical hero frame (matching hanazi.jpg)
"""

import math
import os
import subprocess
import sys
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
FONT_SERIF_REG = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (path, FONT_SANS_BOLD, FONT_SERIF_REG):
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def ease_out_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * ((t - 1.0) ** 3) + c1 * ((t - 1.0) ** 2)


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def draw_centered_text(draw: ImageDraw.ImageDraw, text: str, y: int, font, fill, stroke_width=0, stroke_fill=None, cx=W // 2):
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    tw = bbox[2] - bbox[0]
    x = int(cx - tw / 2)
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# --- 1. douyin-bold (黑金大字) ---
def render_douyin_bold(i: int) -> Image.Image:
    t = i / FPS
    img = Image.new("RGB", (W, H), (10, 11, 15))
    draw = ImageDraw.Draw(img, "RGBA")

    # Subtle ambient amber glow breathing
    glow_r = int(170 + 18 * math.sin(t * 2.2))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((W // 2 - glow_r, 170 - glow_r, W // 2 + glow_r, 170 + glow_r), fill=(212, 175, 55, 36))
    gd.ellipse((W // 2 - 120, 420 - 120, W // 2 + 120, 420 + 120), fill=(255, 59, 48, 22))
    glow = glow.filter(ImageFilter.GaussianBlur(42))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    # Subtle grid lines
    for y in range(80, H, 80):
        draw.line([(24, y), (W - 24, y)], fill=(255, 255, 255, 10), width=1)

    # Top progress pill
    f_small = load_font(FONT_SANS_BOLD, 14)
    f_sub = load_font(FONT_SANS_BOLD, 22)
    f_big = load_font(FONT_SANS_BOLD, 44)
    f_huge = load_font(FONT_SANS_BOLD, 54)

    draw.rounded_rectangle((36, 76, 174, 104), radius=14, fill=(255, 214, 10, 32), outline=(255, 214, 10, 180), width=1)
    draw.text((52, 81), "认知干货 · 01", font=f_small, fill=(255, 214, 10))

    # Progress bar
    prog = clamp(t / DURATION)
    draw.rounded_rectangle((36, 118, W - 36, 123), radius=3, fill=(255, 255, 255, 28))
    draw.rounded_rectangle((36, 118, 36 + int((W - 72) * max(0.06, prog)), 123), radius=3, fill=(255, 214, 10, 230))

    # Beat 1 (0 - 2.0s) vs Beat 2 (2.0 - 4.0s)
    if t < 2.0:
        p1 = ease_out_back(t / 0.42)
        y_off = int((1.0 - p1) * 34)
        draw_centered_text(draw, "前 3 秒抓不住人", 190 + y_off, f_big, (255, 255, 255))

        # Neon yellow highlighter sweeping across "后面全白拍"
        hl = ease_out_cubic((t - 0.35) / 0.45)
        if hl > 0:
            bar_w = int(292 * hl)
            draw.rounded_rectangle((34, 266, 34 + bar_w, 338), radius=10, fill=(255, 214, 10, 245))
        if t > 0.28:
            draw_centered_text(draw, "后面全白拍", 272, f_huge, (14, 15, 20) if hl > 0.5 else (255, 214, 10))

        # Red hand-drawn circle around "前 3 秒"
        c_prog = clamp((t - 0.8) / 0.55)
        if c_prog > 0:
            end_deg = int(-90 + 360 * ease_out_cubic(c_prog))
            draw.arc((40, 178, 176, 250), start=-90, end=end_deg, fill=(255, 59, 48, 240), width=4)

        if t > 0.9:
            alpha = int(255 * clamp((t - 0.9) / 0.35))
            draw_centered_text(draw, "90% 的播放都卡在开头", 374, f_sub, (205, 210, 220, alpha))
    else:
        lt = t - 2.0
        p2 = ease_out_back(lt / 0.38)
        y_off = int((1.0 - p2) * 30)
        # Flash accent bar
        if lt < 0.14:
            draw.rectangle((0, 0, W, H), fill=(255, 214, 10, int(45 * (1 - lt / 0.14))))
        draw_centered_text(draw, "直接抛反差结论", 195 + y_off, f_big, (255, 255, 255))
        hl = ease_out_cubic((lt - 0.25) / 0.4)
        if hl > 0:
            draw.rounded_rectangle((56, 272, 56 + int(248 * hl), 340), radius=8, fill=(255, 59, 48, 240))
        draw_centered_text(draw, "完播翻 3 倍", 276, f_huge, (255, 255, 255))
        # Underline sweep
        ul = ease_out_cubic((lt - 0.65) / 0.45)
        if ul > 0:
            draw.line([(72, 360), (72 + int(216 * ul), 360)], fill=(255, 214, 10, 240), width=5)
        draw_centered_text(draw, "大字居中 · 避开右侧按钮", 386, f_sub, (212, 175, 55))

    # Bottom safe-zone badge
    draw.rounded_rectangle((68, 466, W - 68, 502), radius=18, fill=(255, 255, 255, 16), outline=(212, 175, 55, 110), width=1)
    draw_centered_text(draw, "黑金大字 · 抖音爆款", 475, f_small, (235, 220, 170))
    return img


# --- 2. contrast (红黑反差) ---
def render_contrast(i: int) -> Image.Image:
    t = i / FPS
    img = Image.new("RGB", (W, H), (14, 16, 22))
    draw = ImageDraw.Draw(img, "RGBA")

    f_tag = load_font(FONT_SANS_BOLD, 16)
    f_num = load_font(FONT_SANS_BOLD, 56)
    f_title = load_font(FONT_SANS_BOLD, 34)
    f_body = load_font(FONT_SANS_BOLD, 22)

    # Top header: TOP 3 避坑
    draw.rounded_rectangle((32, 68, 166, 100), radius=10, fill=(250, 204, 21))
    draw.text((46, 74), "TOP 3 避坑", font=f_tag, fill=(14, 16, 22))
    draw.text((180, 74), "正反对比", font=f_tag, fill=(180, 190, 205))

    # Red panel (top half - wrong/pain)
    rp = ease_out_cubic(t / 0.45)
    rx = int((1.0 - rp) * -W)
    shake = int(5 * math.sin(t * 48)) if 0.55 < t < 0.85 else 0
    draw.rounded_rectangle((28 + rx + shake, 126, W - 28 + rx + shake, 294), radius=18, fill=(230, 57, 70, 44), outline=(255, 59, 48, 220), width=2)
    draw.rounded_rectangle((46 + rx + shake, 144, 128 + rx + shake, 174), radius=8, fill=(255, 59, 48))
    draw.text((58 + rx + shake, 149), "× 误区", font=f_tag, fill=(255, 255, 255))
    draw.text((46 + rx + shake, 190), "慢热自我介绍", font=f_title, fill=(255, 235, 235))
    draw.text((46 + rx + shake, 240), "观众 1 秒就划走", font=f_body, fill=(255, 165, 165))

    # Animated red cross strike
    if t > 0.7:
        sp = ease_out_cubic((t - 0.7) / 0.35)
        draw.line([(44, 212), (44 + int(220 * sp), 212)], fill=(255, 59, 48, 235), width=5)

    # VS badge in center
    vs_s = ease_out_back((t - 0.4) / 0.35)
    if vs_s > 0.05:
        r = int(26 * vs_s)
        draw.ellipse((W // 2 - r, 314 - r, W // 2 + r, 314 + r), fill=(250, 204, 21), outline=(14, 16, 22), width=3)
        if vs_s > 0.7:
            draw_centered_text(draw, "VS", 302, f_body, (14, 16, 22))

    # Green panel (bottom half - right/solution)
    gp = ease_out_cubic((t - 0.95) / 0.48)
    gx = int((1.0 - gp) * W)
    draw.rounded_rectangle((28 + gx, 336, W - 28 + gx, 504), radius=18, fill=(16, 185, 129, 42), outline=(16, 185, 129, 230), width=2)
    draw.rounded_rectangle((46 + gx, 354, 128 + gx, 384), radius=8, fill=(16, 185, 129))
    draw.text((58 + gx, 359), "✓ 正解", font=f_tag, fill=(10, 20, 16))
    draw.text((46 + gx, 400), "0.5 秒直给结果", font=f_title, fill=(235, 255, 246))

    # Score bar rising inside green panel
    bar_p = ease_out_cubic((t - 1.5) / 0.8)
    draw.rounded_rectangle((46 + gx, 456, W - 52 + gx, 476), radius=10, fill=(255, 255, 255, 22))
    if bar_p > 0:
        draw.rounded_rectangle((46 + gx, 456, 46 + gx + int((W - 98) * bar_p), 476), radius=10, fill=(16, 185, 129, 240))
    pct = int(92 * bar_p)
    if pct > 0:
        draw.text((W - 110 + gx, 456), f"+{pct}%", font=f_tag, fill=(255, 255, 255))

    # Saveable summary pill at bottom
    if t > 2.2:
        ca = int(255 * clamp((t - 2.2) / 0.4))
        draw.rounded_rectangle((44, 524, W - 44, 560), radius=18, fill=(255, 255, 255, int(ca * 0.12)), outline=(250, 204, 21, ca), width=1)
        draw_centered_text(draw, "★ 截图收藏 · 防踩坑清单", 533, f_tag, (250, 204, 21, ca))

    return img


# --- 3. dossier (档案揭秘) ---
def render_dossier(i: int) -> Image.Image:
    t = i / FPS
    img = Image.new("RGB", (W, H), (17, 19, 24))

    # Spotlight sweep
    spot = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(spot)
    sx = int(W * 0.5 + 55 * math.sin(t * 1.4))
    sy = int(280 + 30 * math.cos(t * 1.1))
    sd.ellipse((sx - 180, sy - 180, sx + 180, sy + 180), fill=(233, 196, 106, 34))
    spot = spot.filter(ImageFilter.GaussianBlur(48))
    img = Image.alpha_composite(img.convert("RGBA"), spot).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    f_code = load_font(FONT_SANS_BOLD, 14)
    f_serif_lg = load_font(FONT_SERIF_BOLD, 34)
    f_serif_md = load_font(FONT_SERIF_BOLD, 23)
    f_stamp = load_font(FONT_SANS_BOLD, 28)

    # Top timecode header
    draw.text((34, 72), "CASE FILE // #2026-07", font=f_code, fill=(233, 196, 106, 210))
    draw.line([(34, 96), (W - 34, 96)], fill=(233, 196, 106, 80), width=1)

    # Paper dossier card sliding in
    cp = ease_out_cubic(t / 0.55)
    cy = int((1.0 - cp) * 70)
    shake_x = int(6 * math.sin(t * 60)) if 1.65 < t < 1.88 else 0
    shake_y = int(4 * math.cos(t * 55)) if 1.65 < t < 1.88 else 0

    card = (30 + shake_x, 126 + cy + shake_y, W - 30 + shake_x, 456 + cy + shake_y)
    draw.rounded_rectangle(card, radius=10, fill=(243, 237, 224), outline=(190, 180, 160), width=2)
    # Red pin dot
    draw.ellipse((W // 2 - 7 + shake_x, 138 + cy + shake_y, W // 2 + 7 + shake_x, 152 + cy + shake_y), fill=(214, 40, 40))

    draw.text((52 + shake_x, 168 + cy + shake_y), "机密调查记录", font=f_code, fill=(140, 45, 45))
    draw.text((52 + shake_x, 196 + cy + shake_y), "为什么它一夜", font=f_serif_lg, fill=(26, 26, 26))
    draw.text((52 + shake_x, 242 + cy + shake_y), "消失在榜单里？", font=f_serif_lg, fill=(26, 26, 26))

    # Redaction bar wiping away to reveal truth
    draw.text((52 + shake_x, 310 + cy + shake_y), "关键线索：算法权重反转", font=f_serif_md, fill=(180, 32, 32))
    redact = 1.0 - ease_out_cubic((t - 0.75) / 0.7)
    if redact > 0.02:
        rw = int(252 * redact)
        draw.rectangle((W - 56 - rw + shake_x, 306 + cy + shake_y, W - 56 + shake_x, 344 + cy + shake_y), fill=(20, 20, 24))

    # Red thread connecting two evidence nodes
    p_line = ease_out_cubic((t - 1.95) / 0.8)
    x1, y1 = 68 + shake_x, 392 + cy + shake_y
    x2, y2 = 290 + shake_x, 420 + cy + shake_y
    draw.ellipse((x1 - 5, y1 - 5, x1 + 5, y1 + 5), fill=(214, 40, 40))
    if p_line > 0:
        draw.line([(x1, y1), (int(x1 + (x2 - x1) * p_line), int(y1 + (y2 - y1) * p_line))], fill=(214, 40, 40), width=3)
    if p_line > 0.9:
        draw.ellipse((x2 - 5, y2 - 5, x2 + 5, y2 + 5), fill=(214, 40, 40))
    draw.text((52 + shake_x, 406 + cy + shake_y), "时间线 A", font=f_code, fill=(85, 80, 72))
    draw.text((228 + shake_x, 392 + cy + shake_y), "幕后真相", font=f_code, fill=(180, 32, 32))

    # Red stamp slamming down (placed cleanly in top-right open space of the dossier card)
    if t > 1.52:
        sp = clamp((t - 1.52) / 0.16)
        scale = 1.6 - 0.6 * ease_out_cubic(sp)
        sw, sh = int(104 * scale), int(38 * scale)
        cx, sy2 = 258 + shake_x, 174 + cy + shake_y
        draw.rounded_rectangle((cx - sw // 2, sy2 - sh // 2, cx + sw // 2, sy2 + sh // 2), radius=6, outline=(214, 40, 40, 230), width=3)
        if sp > 0.6:
            draw_centered_text(draw, "已解密", sy2 - 14, load_font(FONT_SANS_BOLD, 22), (214, 40, 40, 230), cx=cx)

    draw_centered_text(draw, "档案揭秘 · 悬疑叙事", 498, f_code, (233, 196, 106, 210))
    return img


# --- 4. healing (胶片治愈) ---
def render_healing(i: int) -> Image.Image:
    t = i / FPS
    img = Image.new("RGB", (W, H), (20, 18, 16))

    # Warm amber sunset gradient + drifting bokeh particles
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    lx = int(W * 0.72 + 28 * math.sin(t * 0.9))
    ly = int(175 + 22 * math.cos(t * 0.8))
    od.ellipse((lx - 170, ly - 170, lx + 170, ly + 170), fill=(230, 169, 107, 56))
    od.ellipse((-40, 390, 240, 670), fill=(168, 118, 86, 44))

    # Soft floating light dust
    for idx in range(14):
        px = int((idx * 53 + t * (10 + (idx % 4) * 5)) % (W + 40)) - 20
        py = int((idx * 89 - t * (16 + (idx % 3) * 6)) % (H + 40)) - 20
        r = 3 + (idx % 4) * 2
        od.ellipse((px - r, py - r, px + r, py + r), fill=(246, 232, 205, 75))

    overlay = overlay.filter(ImageFilter.GaussianBlur(14))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    f_small = load_font(FONT_SERIF_REG, 14)
    f_main = load_font(FONT_SERIF_BOLD, 30)
    f_sub = load_font(FONT_SERIF_REG, 19)

    # Elegant hairline frame
    draw.rounded_rectangle((28, 84, W - 28, H - 108), radius=6, outline=(246, 241, 231, 48), width=1)
    draw_centered_text(draw, "23:40 · 晚风与独白", 112, f_small, (230, 169, 107, 195))

    # Line 1 gentle fade + rise
    a1 = clamp(t / 0.9)
    y1 = int(248 + (1.0 - ease_out_cubic(a1)) * 14)
    draw_centered_text(draw, "慢一点也没关系", y1, f_main, (246, 241, 231, int(255 * a1)))

    # Line 2 gentle fade + warm amber accent
    a2 = clamp((t - 0.95) / 0.95)
    if a2 > 0:
        y2 = int(304 + (1.0 - ease_out_cubic(a2)) * 14)
        draw_centered_text(draw, "风会吹到你这边", y2, f_main, (230, 169, 107, int(255 * a2)))

    # Subtle divider line expanding
    lp = ease_out_cubic((t - 1.7) / 0.8)
    if lp > 0:
        half = int(64 * lp)
        draw.line([(W // 2 - half, 368), (W // 2 + half, 368)], fill=(246, 241, 231, 120), width=1)

    a3 = clamp((t - 2.0) / 0.85)
    if a3 > 0:
        draw_centered_text(draw, "写给正在赶路的你", 390, f_sub, (186, 178, 168, int(245 * a3)))

    # Film timecode footer
    sec_str = f"00:0{int(t)}:{int((t % 1) * 30):02d}"
    draw_centered_text(draw, f"REC ●  {sec_str}  ·  胶片治愈", 488, f_small, (186, 178, 168, 175))
    return img


STYLES = [
    ("douyin-bold", render_douyin_bold, 1.35),
    ("contrast", render_contrast, 2.7),
    ("dossier", render_dossier, 2.6),
    ("healing", render_healing, 2.8),
]


def make_poster(vertical_img: Image.Image, out_jpg: Path) -> None:
    """Create 640x360 blurred-backdrop poster matching hanazi.jpg."""
    # Scale to cover 640x360 then blur
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
        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "26",
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
