#!/usr/bin/env python3
"""Render original silent 8-second demonstration clips, sequentially with one encoder.
Requires Pillow, ffmpeg and a CJK font. No network, model API, borrowed footage or audio.
The projection in exploded() uses rotating 3D cuboids with depth-sorted faces.
Usage: python3 scripts/video-presets/render.py [--only math] [--output /tmp/samples]
"""
import argparse
import math
import os
from pathlib import Path
import random
import subprocess
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

W, H, SS, FPS, SECONDS = 640, 360, 2, 15, 8
FONT = os.environ.get('VIDEO_SAMPLE_FONT', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
ROOT = Path(__file__).resolve().parents[2]
SAMPLES = [
    ('shadow', '皮影讲典故', '投下石子，水位上升'),
    ('isometric', '等距流程', '同一包裹，三个节点'),
    ('scale', '比例尺对比', '半径翻倍，面积变为四倍'),
    ('whiteboard', '白板手绘', '行动与图解同步'),
    ('glyph', '汉字演变', '从意象到字形 · 示意'),
    ('exploded', '3D 拆解', '拆开看清，再原位合拢'),
    ('pixel', '像素典故', '一步一步，也能到终点'),
    ('storybook', '绘本科普', '种子醒来，叶片展开'),
    ('math', '数学可视化', '分割、移动、交错重组'),
    ('map', '地图动画', '沿线前进，逐站讲解'),
    ('news', '数据信息图', '每一轮，数量都翻倍'),
    ('flat', '扁平 MG', '跟着水滴，走完一个循环'),
    ('type', '卡点金句', '让观点有节奏地出现'),
    ('comic', '漫画分格', '一次动作，连续后果'),
    ('timeline', '时间线', '沿时间轴看见变化'),
]


def clamp(v):
    return max(0., min(1., v))


def ease(v):
    v = clamp(v)
    return v * v * (3 - 2 * v)


def mix(a, b, t):
    return a + (b - a) * t


@lru_cache(maxsize=32)
def font(size):
    return ImageFont.truetype(FONT, round(size * SS))


class Canvas:
    def __init__(self, bg):
        self.im = Image.new('RGB', (W * SS, H * SS), bg)
        self.d = ImageDraw.Draw(self.im)

    def box(self, xy, fill, outline=None, width=1, radius=0):
        xy = tuple(round(v * SS) for v in xy)
        if radius:
            self.d.rounded_rectangle(xy, radius=round(radius * SS), fill=fill, outline=outline, width=max(1, round(width * SS)))
        else:
            self.d.rectangle(xy, fill=fill, outline=outline, width=max(1, round(width * SS)))

    def oval(self, xy, fill, outline=None, width=1):
        self.d.ellipse(tuple(round(v * SS) for v in xy), fill=fill, outline=outline, width=max(1, round(width * SS)))

    def line(self, points, fill, width=2):
        self.d.line([(round(x * SS), round(y * SS)) for x, y in points], fill=fill, width=max(1, round(width * SS)), joint='curve')

    def poly(self, points, fill, outline=None):
        pts = [(round(x * SS), round(y * SS)) for x, y in points]
        if fill is not None:
            self.d.polygon(pts, fill=fill)
        if outline:
            self.d.line(pts + pts[:1], fill=outline, width=SS * 2)

    def text(self, xy, text, size=18, fill='#ecf3f3', anchor='mm'):
        self.d.text((round(xy[0] * SS), round(xy[1] * SS)), text, font=font(size), fill=fill, anchor=anchor)

    def finish(self, label, caption, dark=True):
        fg = '#edf2ef' if dark else '#263c40'
        self.text((26, 24), label, 16, fg, 'lm')
        self.text((614, 24), 'Halo · 原创样片', 11, fg, 'rm')
        self.text((320, 334), caption, 17, fg)
        return self.im.resize((W, H), Image.Resampling.LANCZOS)


def arrow(c, a, b, color, width=3):
    c.line([a, b], color, width)
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    c.poly([b, (b[0] - 10 * math.cos(angle - .5), b[1] - 10 * math.sin(angle - .5)),
            (b[0] - 10 * math.cos(angle + .5), b[1] - 10 * math.sin(angle + .5))], color)


def shadow(t):
    c = Canvas('#30231e')
    c.box((32, 56, 608, 305), '#d9bc7e', '#82372c', 8)
    # Backlit hills and a proscenium.
    c.poly([(38, 256), (180, 160), (320, 258), (480, 178), (602, 245), (602, 300), (38, 300)], '#baa26f')
    for x in range(38, 604, 28):
        c.oval((x, 52, x + 32, 76), '#82372c')
    c.box((38, 72, 58, 300), '#843e2c'); c.box((582, 72, 602, 300), '#843e2c')
    c.line([(62, 282), (578, 282)], '#573524', 5)
    # Jar, transparent water and stones; state changes persist after every drop.
    progress = clamp((t - .6) / 5.6)
    drops = min(4, int(progress * 4))
    water = 258 - 13 * drops
    c.box((344, water, 436, 279), '#71938c')
    c.poly([(334, 169), (350, 280), (430, 280), (446, 169)], None, '#513625')
    c.line([(330, 170), (450, 170)], '#513625', 5)
    for i in range(drops):
        c.oval((354 + i * 18, 267, 367 + i * 18, 279), '#6a4c33')
    # Articulated bird: rotating wing, head dipping with each stone.
    cycle = ((t - .6) / 1.4) % 1
    dip = math.sin(cycle * math.pi) * 15 if .6 < t < 6.2 else 0
    c.oval((191, 175, 282, 240), '#392a23', '#b37b42')
    c.poly([(199, 218), (155, 200), (176, 237)], '#392a23')
    c.oval((259, 153 + dip, 307, 195 + dip), '#392a23')
    c.poly([(302, 170 + dip), (337, 179 + dip), (304, 185 + dip)], '#392a23')
    c.oval((286, 164 + dip, 292, 170 + dip), '#ecd7a1')
    angle = -.5 + math.sin(cycle * math.pi * 2) * .35
    wing = [(222, 192), (222 + 48 * math.cos(angle), 192 + 48 * math.sin(angle)), (251, 226)]
    c.poly(wing, '#a46e39', '#392a23'); c.oval((218, 188, 226, 196), '#e5c681')
    c.line([(222, 237), (219, 280), (203, 280)], '#392a23', 4)
    c.line([(255, 235), (265, 280), (280, 280)], '#392a23', 4)
    if .6 < t < 6.2:
        q = ease(cycle)
        x, y = mix(320, 390, q), 176 - 35 * math.sin(q * math.pi) + q * 65
        c.oval((x - 7, y - 6, x + 7, y + 6), '#634c36')
    c.text((504, 115), f'{drops} 颗', 22, '#533224')
    return c.finish('皮影讲典故', '投石改变水位，动作带来可见结果')


def iso_box(c, x, y, w, h, colors):
    c.poly([(x, y), (x + w, y - w / 2), (x + 2 * w, y), (x + w, y + w / 2)], colors[0])
    c.poly([(x, y), (x + w, y + w / 2), (x + w, y + w / 2 + h), (x, y + h)], colors[1])
    c.poly([(x + w, y + w / 2), (x + 2 * w, y), (x + 2 * w, y + h), (x + w, y + w / 2 + h)], colors[2])


def isometric(t):
    c = Canvas('#e9f0e9')
    stations = [(100, 183), (285, 183), (470, 183)]
    c.poly([(38, 227), (320, 78), (612, 227), (326, 306)], '#c5d8cd')
    c.line([(108, 219), (526, 219)], '#fffdfa', 19)
    for i, (x, y) in enumerate(stations):
        iso_box(c, x, y, 35, 35, ['#79a99a', '#27675c', '#408677'])
        c.text((x + 35, 270), ['1 揽收', '2 分拣', '3 送达'][i], 17, '#28564c')
    pos = ease((t - .4) / 6.2) * 2
    x = 122 + pos * 185
    bounce = -12 * math.sin((pos % 1) * math.pi)
    iso_box(c, x, 144 + bounce, 18, 26, ['#efc26d', '#ad713c', '#cf9850'])
    stage = min(2, int(pos + .2))
    c.box((185, 72, 455, 111), '#ffffff', radius=12)
    c.text((320, 91), ['扫描入库', '按目的地分拣', '完成配送'][stage], 20, '#286154')
    return c.finish('等距流程', '始终跟踪同一个包裹', False)


def scale(t):
    c = Canvas('#111d32')
    sizes = [20, 40, 80]
    p = ease((t - 1) / 5)
    zoom = mix(1.3, 1., p)
    for i, r in enumerate(sizes):
        x = 150 + i * 170
        rr = r * zoom
        c.oval((x - rr, 180 - rr, x + rr, 180 + rr), ['#7aabc9', '#579b9e', '#e9b85c'][i])
        c.line([(x, 180), (x + rr, 180)], '#16233a', 2)
        c.text((x, 180 - rr - 18), f'r = {2 ** i}', 16)
        c.text((x, 289), f'面积 {4 ** i}π', 18)
    return c.finish('比例尺对比', '共同缩放，半径比始终为 1 : 2 : 4')


def person(c, x, y, color='#30383c', arm=0):
    c.oval((x - 11, y - 48, x + 11, y - 26), None, color, 2)
    c.line([(x, y - 25), (x, y + 12), (x - 15, y + 35)], color, 2)
    c.line([(x, y + 12), (x + 15, y + 35)], color, 2)
    c.line([(x - 21, y + arm), (x, y - 14), (x + 24, y - arm)], color, 2)


def whiteboard(t):
    c = Canvas('#fbf8ed')
    c.line([(205, 88), (205, 270), (575, 270)], '#35434a', 3)
    c.text((207, 70), '感受（示意）', 16, '#35434a')
    c.text((490, 294), '第几次尝试', 14, '#35434a')
    n = clamp((t - .3) / 6) * 4
    person(c, 110, 200, arm=math.sin(t * 4) * 17)
    for i, h in enumerate([135, 95, 60, 37]):
        q = ease(n - i)
        if q > 0:
            x = 242 + i * 80
            c.box((x, 270 - h * q, x + 42, 270), '#ead4a0', '#35434a', 2)
            for yy in range(0, int(h * q) - 10, 10):
                c.line([(x + 3, 269 - yy), (x + 39, 259 - yy)], '#a89471', 1)
            c.text((x + 21, 287), str(i + 1), 13, '#35434a')
    c.text((110, 108), f'第 {min(4, int(n) + 1)} 次', 20, '#b9503d')
    if t > 6.4:
        c.line([(263, 130), (343, 171), (423, 205), (503, 230)], '#b9503d', 3)
    return c.finish('白板手绘', '每次行动，图上出现对应的一笔', False)


def glyph(t):
    c = Canvas('#32271f')
    # Deterministic paper/bronze texture, not a claim of authentic historical glyphs.
    rng = random.Random(17)
    for _ in range(350):
        x, y = rng.randint(30, 610), rng.randint(58, 302)
        c.line([(x, y), (x + rng.randint(2, 16), y)], '#443225', 1)
    q = ease((t - 1.5) / 4.5)
    pts = []
    for i in range(121):
        a = i / 120 * math.tau
        x, y = math.cos(a), math.sin(a)
        # Superellipse gradually changes the round outline into a squared glyph.
        exponent = mix(1., .14, q)
        pts.append((320 + 70 * math.copysign(abs(x) ** exponent, x), 180 + 86 * math.copysign(abs(y) ** exponent, y)))
    for w, color in [(13, '#704724'), (7, '#d69e51'), (3, '#f4d794')]:
        c.line(pts, color, w)
    half = mix(4, 66, q)
    c.line([(320 - half, 180), (320 + half, 180)], '#f2c77a', 7)
    c.text((320, 291), '意象轮廓' if q < .5 else '规范写法：日', 23, '#f3d698')
    return c.finish('汉字演变', '字形转换示意 · 不作为古文字考据')


def exploded(t):
    c = Canvas('#e9edf0')
    split = ease((t - .6) / 2) * (1 - ease((t - 5.7) / 1.8))
    yaw, pitch = .35 + .6 * math.sin(t * .4), -.48
    def project(v):
        x, y, z = v
        x, z = x * math.cos(yaw) + z * math.sin(yaw), -x * math.sin(yaw) + z * math.cos(yaw)
        y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
        factor = 640 / (640 + z)
        return 280 + x * factor, 184 + y * factor, z
    faces = []
    labels = []
    colors = [('#c2d1db', '#718b9d', '#9aafbe'), ('#608c79', '#284c41', '#42725e'), ('#adb8c3', '#556575', '#8898a8')]
    for i in range(3):
        yy = (i - 1) * (24 + split * 62)
        points = [project((x, y + yy, z)) for x, y, z in [(-90,-8,-53),(90,-8,-53),(90,-8,53),(-90,-8,53),(-90,8,-53),(90,8,-53),(90,8,53),(-90,8,53)]]
        for j, indices in enumerate([(0,1,2,3),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]):
            faces.append((sum(points[k][2] for k in indices) / 4, [(points[k][0], points[k][1]) for k in indices], colors[i][j % 3]))
        labels.append(project((95, yy, 0)))
    for _, points, color in sorted(faces, key=lambda f: f[0], reverse=True):
        c.poly(points, color, '#526675')
    if split > .6:
        for i, (x, y, _) in enumerate(labels):
            target_y = 105 + i * 78
            c.line([(x, y), (455, target_y), (477, target_y)], '#657987', 1)
            c.text((486, target_y), ['上盖', '电路板', '底座'][i], 18, '#344d5e', 'lm')
    return c.finish('3D 拆解', '简化传感器模型 · 真实三维投影与遮挡', False)


def pixel(t):
    c = Canvas('#202940')
    for x in range(0, 640, 32):
        c.box((x, 258 + (x % 64) // 8, x + 31, 307), '#4b7458')
    c.box((548, 83, 554, 260), '#e6ca8a')
    for i in range(4):
        for j in range(3):
            c.box((554 + i * 12, 83 + j * 12, 565 + i * 12, 94 + j * 12), '#f5ecd0' if (i+j)%2 else '#232c40')
    turtle = round((70 + ease(t / 7.3) * 465) / 4) * 4
    rabbit = 95 + ease(t / 2.5) * 270 + ease((t - 7) / 1) * 170
    def sprite(x, y, rows, palette):
        for iy, row in enumerate(rows):
            for ix, code in enumerate(row):
                if code != '.': c.box((x+ix*5, y+iy*5, x+ix*5+4, y+iy*5+4), palette[code])
    sprite(turtle, 212 + int(t*5)%2*4, ['..gggg....', '.gggggg.h.', 'gggggggghh', '.gggggg...', '..b..b....'], {'g':'#91ba76','h':'#e9c477','b':'#486348'})
    sprite(rabbit, 143, ['.w.w.', '.w.w.', '.wwww', '.wwbw', '..ww.', '.wwww', 'w..w.'], {'w':'#eae7d7','b':'#26354a'})
    if 3 < t < 7: c.text((rabbit + 20, 121), 'Z z', 17, '#e6ca8a')
    return c.finish('像素典故', '坚持前进的小龟，越过停下的小兔')


def leaf(c, x, y, length, flip=False):
    s = -1 if flip else 1
    c.poly([(x,y),(x+s*length*.35,y-length*.6),(x+s*length,y-length*.5),(x+s*length*.6,y),(x,y)], '#72a478', '#44694d')
    c.line([(x,y),(x+s*length*.85,y-length*.43)], '#d4d7a3', 1)


def storybook(t):
    c = Canvas('#f4eedb')
    rng = random.Random(21)
    for _ in range(650):
        x,y=rng.randint(0,639),rng.randint(52,303)
        c.line([(x,y),(x+7,y-3)], '#e5dfc9', 1)
    c.box((30, 255, 610, 303), '#c6aa7b')
    c.line([(30,255),(610,255)], '#7d6849', 2)
    growth = ease((t - .6) / 5.6)
    c.oval((297, 255, 343, 283), '#a7794e', '#5e6549', 2)
    top = 258 - growth * 148
    c.line([(320, 268),(316, mix(262,220,growth)),(323, top)], '#537b59', 5)
    if growth > .3: leaf(c, 320, 237 - growth*50, 65*ease((growth-.3)/.4), True)
    if growth > .5: leaf(c, 321, top+25, 72*ease((growth-.5)/.4))
    c.oval((316,top-8,329,top+5), '#8aa867', '#537b59')
    c.oval((495,74,546,125), '#e8bb63')
    c.text((154, 159), '先长根' if t < 3 else '再展叶', 22, '#537b59')
    c.line([(320, 279), (310, 298)], '#73543c', 2)
    return c.finish('绘本科普', '发芽过程示意 · 真实生长需要更长时间', False)


def math_scene(t):
    c = Canvas('#101b27')
    r, n = 77, 16
    q = ease((t - 1.5) / 3.8)
    half = math.pi/n
    for i in range(n):
        a = math.tau * i/n
        mid = math.pi/2 if i%2==0 else -math.pi/2
        x = mix(240, 201 + i*r*math.sin(half), q)
        y = mix(178, 178 + (-1 if i%2==0 else 1)*r*math.cos(half)/2, q)
        # Rigid rotation + translation: every sector retains its area at every frame.
        delta = (mid - half - a + math.pi) % math.tau - math.pi
        angle = a + delta*q
        pts = [(x,y)] + [(x+r*math.cos(angle+j*2*half/14), y+r*math.sin(angle+j*2*half/14)) for j in range(15)]
        c.poly(pts, '#72c2cf' if i%2==0 else '#e6b65b', '#243749')
    c.text((320, 80), '16 个扇形 · 保留每一块的面积', 21)
    if t > 5.4:
        c.line([(201,236),(436,236)], '#bbcbd2', 1)
        c.text((320,260), '分割越细，越接近长方形', 18)
        c.text((320,291), '底 → πr     高 → r     面积 = πr²', 18, '#e7ba65')
    return c.finish('数学可视化', '有限分割是近似，重组过程保持面积')


ROUTE = [(86,235),(174,197),(258,218),(346,132),(435,163),(549,105)]


def route_point(p):
    i=min(len(ROUTE)-2,int(p))
    q=clamp(p-i)
    return mix(ROUTE[i][0],ROUTE[i+1][0],q),mix(ROUTE[i][1],ROUTE[i+1][1],q)


def map_scene(t):
    c=Canvas('#eee1bf')
    c.box((25,58,615,306), None, '#a5946e', 2)
    c.line([(37,111),(156,128),(230,175),(335,188),(432,250),(600,264)], '#9cb8b2', 9)
    for x,y in [(95,132),(270,100),(393,250),(492,215)]:
        for k in range(3):
            c.poly([(x+k*22,y),(x+12+k*22,y-28),(x+25+k*22,y)], '#a8aa83', '#788160')
    p=ease((t-.4)/6.5)*(len(ROUTE)-1)
    current=route_point(p)
    c.line(ROUTE[:int(p)+1]+[current], '#ac4d3d', 4)
    for i in [0,2,5]:
        x,y=ROUTE[i]
        c.oval((x-6,y-6,x+6,y+6), '#eee1bf', '#ac4d3d', 2)
        c.text((x,y+22), ['起点','山谷','终点'][[0,2,5].index(i)], 16, '#524c37')
    x,y=current
    c.oval((x-10,y-10,x+10,y+10), '#ac4d3d')
    c.oval((x-4,y-4,x+4,y+4), '#f4e9cb')
    return c.finish('地图动画', '示意路线 · 不代表真实地理与里程', False)


def news(t):
    c=Canvas('#142139')
    c.line([(78,91),(78,282),(567,282)], '#6d8498', 2)
    p=clamp((t-.4)/6)*4
    for i,value in enumerate([1,2,4,8]):
        q=ease(p-i)
        height=value*23*q
        x=116+i*116
        c.box((x,282-height,x+62,282), '#e5b85a' if i==3 else '#6ea5c8', radius=3)
        if q>0: c.text((x+31,262-height), str(round(value*q,1)).removesuffix('.0'), 25)
        c.text((x+31,298), f'第 {i+1} 轮', 14)
    c.text((320,76), '× 2      × 2      × 2', 24, '#e5b85a')
    return c.finish('数据信息图', '示例数据 · 数字与柱高由同一数值驱动')


def flat(t):
    c=Canvas('#dceef4')
    c.poly([(318,287),(468,138),(610,287)], '#80ad80')
    c.poly([(423,183),(468,138),(506,181),(478,171),(462,182),(449,171)], '#f5f6e9')
    c.box((28,270,612,306), '#62a6c3')
    c.oval((79,77,129,127), '#f0c561')
    for x,y in [(325,105),(350,91),(378,105)]: c.oval((x-26,y-18,x+26,y+18), '#f5f7ed')
    nodes=[(170,266),(245,103),(364,109),(442,212),(170,266)]
    p=clamp(t/7.5)*4
    idx=min(3,int(p)); q=ease(p-idx)
    x,y=mix(nodes[idx][0],nodes[idx+1][0],q),mix(nodes[idx][1],nodes[idx+1][1],q)
    for i in range(4): arrow(c,nodes[i],nodes[i+1], '#97c5cd', 2)
    c.poly([(x,y-24),(x-17,y+2),(x-12,y+17),(x+12,y+17),(x+17,y+2)], '#3984ae')
    c.oval((x-8,y+1,x-4,y+6), '#173a50'); c.oval((x+4,y+1,x+8,y+6), '#173a50')
    c.text((320,66), ['蒸发','凝结','降水','汇流'][idx], 25, '#285b70')
    return c.finish('扁平 MG', '同一水滴，四个阶段，形成循环', False)


def type_scene(t):
    i=min(3,int(t/2))
    c=Canvas(['#172039','#254e69','#3c355a','#24594e'][i])
    q=ease((t%2)/.45)
    c.text((508,170), str(i+1), 145, ['#293951','#38617c','#55496e','#367465'][i])
    c.text((68,110), ['先提出问题','把问题变小','用证据检查','用自己的话'][i], 25, '#e7cf9b', 'lm')
    c.text((68+mix(50,0,q),191), ['观察','拆解','验证','理解'][i], 65, '#faf1de', 'lm')
    c.box((68,246,68+q*330,251), '#edbd61')
    return c.finish('卡点金句', '无声节奏示例 · 成片按用户音乐或阅读节奏')


def comic(t):
    c=Canvas('#f4f0e5')
    phase=min(2,int(t/2.6))
    for i in range(3):
        left=28+i*199
        c.box((left,67,left+186,302), '#fffcf1', '#252d34', 3)
        for x in range(left+8,left+182,12):
            for y in range(75,298,12): c.oval((x,y,x+1,y+1), '#c5c0b4')
        c.text((left+93,94), ['一推','接着倒','连锁反应'][i], 21, '#30353c')
        p=clamp((t-i*2.6)/1.7)
        for j in range(3):
            angle=ease(p*3-j)*1.2
            x=left+45+j*43; y=258
            pts=[]
            for xx,yy in [(-7,0),(7,0),(7,-74),(-7,-74)]:
                pts.append((x+xx*math.cos(angle)-yy*math.sin(angle),y+xx*math.sin(angle)+yy*math.cos(angle)))
            c.poly(pts, '#b34d3d' if j==0 else '#555d61', '#252d34')
        if i==phase:
            c.box((left,67,left+186,302), None, '#b34d3d', 4)
            c.text((left+90,151), '啪！' if p>.2 else '→', 30, '#b34d3d')
    return c.finish('漫画分格', '依次读格，动作与后果相连', False)


def timeline(t):
    c=Canvas('#131e2c')
    p=ease((t-.4)/6.7)*2
    # Camera follows the active time; historical nodes stay on the same axis.
    offset=mix(0,180,p/2)
    c.line([(92-offset,225),(740-offset,225)], '#667d87', 2)
    positions=[140,410,680]
    for i,x0 in enumerate(positions):
        x=x0-offset
        c.oval((x-7,218,x+7,232), '#e9b35a' if p>=i-.1 else '#637b84')
        if 35<x<605:
            c.text((x,254), ['第 0 天','第 3 天','第 7 天'][i], 17)
    i=min(2,int(p+.4)); active_x=positions[i]-offset
    c.text((320,106), ['播种','发芽','展叶'][i], 41, '#e9b35a')
    c.text((320,164), ['种子进入湿润土壤','根与嫩芽出现','叶片展开，继续生长'][i], 21)
    c.line([(320,187),(active_x,209)], '#8fbdb6', 2)
    return c.finish('时间线', '观察记录示例 · 节点间距不按时间比例')


DRAW = {'shadow':shadow, 'isometric':isometric, 'scale':scale, 'whiteboard':whiteboard,
        'glyph':glyph, 'exploded':exploded, 'pixel':pixel, 'storybook':storybook, 'math':math_scene,
        'map':map_scene, 'news':news, 'flat':flat, 'type':type_scene, 'comic':comic, 'timeline':timeline}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=list(DRAW))
    parser.add_argument('--output', type=Path, default=ROOT/'static/video-presets/v1')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    for key,_,_ in SAMPLES:
        if args.only and key!=args.only: continue
        target=args.output/f'{key}.mp4'
        temporary=args.output/f'{key}.partial.mp4'
        command=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24',
                 '-s',f'{W}x{H}','-r',str(FPS),'-i','pipe:0','-an','-c:v','libx264','-threads','1',
                 '-preset','medium','-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',str(temporary)]
        proc=subprocess.Popen(command,stdin=subprocess.PIPE)
        try:
            for frame in range(FPS*SECONDS):
                im=DRAW[key](frame/FPS)
                proc.stdin.write(im.tobytes())
                if frame==int(FPS*4.5): im.save(args.output/f'{key}.jpg',quality=88)
            proc.stdin.close()
            if proc.wait()!=0: raise RuntimeError(f'ffmpeg failed for {key}')
            temporary.replace(target)
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait()
            temporary.unlink(missing_ok=True)
        print(f'{key}: {SECONDS}s {W}x{H} {FPS}fps {target.stat().st_size} bytes',flush=True)


if __name__=='__main__': main()
