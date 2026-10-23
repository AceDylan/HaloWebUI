# 知识讲解形式与原创样片

视频工作台以 15 种知识讲解形式作为主预设：皮影讲典故、等距流程、比例尺对比、白板手绘、汉字演变、3D 拆解、像素典故、绘本科普、数学可视化、地图动画、数据信息图、扁平 MG、卡点金句、漫画分格、时间线。

每项在 `src/lib/utils/video-presentations.ts` 定义分镜结构、主体动作、镜头、节奏与验收重点。`videoStyleLines` 同时将这些规则传入提示词增强和最终制作需求，增强关闭或失败也不丢失。用户原话优先；配色与字体偏好只调整外观。素材剪辑保留原素材，不附加重新表演动作的要求；图文成片说明关键画面与连续动画的区别。

主预设沿用 `style` 设置字段。旧 `flat/isometric/news/whiteboard/type/pixel` 选择分别进入对应讲解形式，其余十个旧键在「其他视觉风格」保留。新增 `appearance` 为可选外观描述，旧设置默认空；修改后参与增强结果的过期判断。无数据库迁移。

## 样片与限制

`static/video-presets/v1/` 是随前端发布的 15 段原创无声 MP4 与 JPG 封面。每段 640×360、15 fps、8 秒；封面来自同次渲染的第 4.5 秒。只加载当前选中的视频，`preload="none"`，不自动播放。示意题材不写入用户的制作需求，避免把样片主题当成任务主题。

这些短片展示基本动作机制，并非用户定制成片的质量承诺，也未使用参考视频的画面、角色或音轨。数学样片通过刚体旋转和平移重组扇形；3D 样片使用带厚度的三维部件、相机旋转投影和深度排序，明确为简化模型。汉字、地图、观察记录和数据样片均标注示意，不作为历史、地理或科学数据来源。

预设仍由 Hermes／所选执行者根据用户主题完成制作，不是预制影片的自动替换文字。不能完成三维渲染或缺乏模型时需说明限制，不能静默降为二维。外观不会更改用户的制作方式、音乐、时长、配音或字幕开关。

## 重建与验证

本地需要 Python 3、Pillow、ffmpeg、Noto Sans CJK 字体；可用 `VIDEO_SAMPLE_FONT` 指定字体路径。无联网、模型调用或音频依赖。渲染逐个进行，ffmpeg 单线程。

```bash
python3 scripts/video-presets/render.py
# 仅重建某一项，或输出到临时目录
python3 scripts/video-presets/render.py --only math --output /tmp/math-preview
python3 scripts/video-presets/verify.py
npx vitest run src/lib/utils/video-brief.test.ts src/lib/utils/video-presentations.test.ts --maxWorkers=1 --minWorkers=1
npx vitest run --config vitest.dom-mount.config.ts src/lib/components/workspace/Videos.mount-test.ts --maxWorkers=1 --minWorkers=1
```

验证脚本检查每段时长、帧数、编码、完整解码、每秒画面变化与封面尺寸。检查动画逻辑还需查看连续关键帧，不能用文件可解码替代视觉验收。
