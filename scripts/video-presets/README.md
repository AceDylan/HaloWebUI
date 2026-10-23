# 视频工作台风格样片

视觉风格定义在 `src/lib/utils/video-styles.ts`：八种通用 MG 风格（扁平 MG、贴纸科普、等轴 2.5D、一笔线条、手绘逐帧、弥散玻璃、科幻 HUD、综艺花字），取自 [mg-styles-15](https://github.com/Vincentwei1021/mg-styles-15)（MIT）的「风格特征 + 关键技法」，改写成 Hermes 本机能做的路线（Remotion + SVG/CSS、已装的 Noto CJK 字体，不合成配乐）。

- 「自动选择」用 `pickVideoStyle` 按需求原话里的词挑一种：风格名本身记 3 分、题材词记 1 分，数据动画偏向贴纸科普、素材剪辑偏向综艺花字，平分取靠前的，什么都没提到用扁平 MG；附件里有参考视频（不是素材剪辑）时跟随参考。增强后仍按用户原话选，增强结果不会因此过期。
- 写进需求的行：风格特征、配色字体、关键技法、验收进增强设置和最终需求；实现路线和「制作标准」（0.5 秒钩子、60–75% 高潮、结尾停留、关键帧先行、逐条自评）只给制作者。素材剪辑只把风格用于标题字幕包装，图文成片给统一的画面风格描述。
- 旧的 15 个讲解形式和 10 个外观预设已删除，存着的旧键回到「自动选择」。

## 样片

`static/video-presets/v2/` 是八支参考成片的无声预览（640×360，综艺花字为 360×640 竖屏，H.264 CRF 30，约 3 MB），许可见同目录 `LICENSE.txt`。只加载当前显示的那一支，`preload="none"`，不自动播放。

```bash
git clone --depth 1 https://github.com/Vincentwei1021/mg-styles-15 /tmp/mg-styles-15
sh scripts/video-presets/make_samples.sh /tmp/mg-styles-15
npx vitest run src/lib/utils/video-brief.test.ts --maxWorkers=1 --minWorkers=1
npx vitest run --config vitest.dom-mount.config.ts src/lib/components/workspace/Videos.mount-test.ts --maxWorkers=1 --minWorkers=1
```
