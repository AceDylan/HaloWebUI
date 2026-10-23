#!/bin/sh
# 视频工作台风格样片：从 mg-styles-15（MIT，https://github.com/Vincentwei1021/mg-styles-15）的成片
# 转出轻量预览，写到 static/video-presets/v2/。一次只跑一个 ffmpeg（主机内存小）。
#   git clone --depth 1 https://github.com/Vincentwei1021/mg-styles-15 /tmp/mg-styles-15
#   sh scripts/video-presets/make_samples.sh /tmp/mg-styles-15
set -eu
src="${1:?用法: make_samples.sh <mg-styles-15 仓库目录>}/videos"
out="$(cd "$(dirname "$0")/../.." && pwd)/static/video-presets/v2"
mkdir -p "$out"

# 样片键（src/lib/utils/video-styles.ts）:参考成片[:封面取自成片的秒数，缺省用原片封面]
for item in flat:01-flat-vector sticker:19-paperclip:9.5 isometric:03-isometric line:02-line-art \
	handdrawn:05-cel-boil glass:12-aurora-glass hud:22-hud hanazi:18-hanazi; do
	key="${item%%:*}"
	rest="${item#*:}"
	film="${rest%%:*}"
	at="${rest#"$film"}"
	at="${at#:}"
	if [ "$key" = hanazi ]; then
		# 竖屏原片：预览保持竖屏，封面铺到 16:9 卡片里（模糊底 + 居中原图）
		scale="scale=360:640:flags=lanczos"
		poster="[0:v]split[a][b];[a]scale=640:360:force_original_aspect_ratio=increase,crop=640:360,boxblur=18[bg];[b]scale=-2:360[fg];[bg][fg]overlay=(W-w)/2:0"
	else
		scale="scale=640:360:flags=lanczos"
		poster="scale=640:360:flags=lanczos"
	fi
	ffmpeg -v error -y -threads 2 -i "$src/$film.mp4" -an -vf "$scale" -c:v libx264 -preset slow \
		-crf 30 -pix_fmt yuv420p -movflags +faststart "$out/$key.mp4"
	if [ -n "$at" ]; then
		ffmpeg -v error -y -ss "$at" -i "$src/$film.mp4" -filter_complex "$poster" -frames:v 1 -q:v 4 "$out/$key.jpg"
	else
		ffmpeg -v error -y -i "$src/$film.jpg" -filter_complex "$poster" -frames:v 1 -q:v 4 "$out/$key.jpg"
	fi
	echo "$key ← $film"
done
