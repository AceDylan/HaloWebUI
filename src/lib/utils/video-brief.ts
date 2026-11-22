// The video studio (/workspace/videos): what you want, how it should be made and who makes it,
// written as one brief for Hermes or a runner. Animation-first for both normal videos and MVs:
// never pure kinetic text or simplistic stills; concrete multi-style animation closely matching
// subtitles or lyrics, restrained on-screen text when subtitles are burned in, and first-class
// integration with the home PC's JIZURA kinetic engine (split-screen half-cartoon + half-JIZURA
// for MVs & split-mix normal videos, or JIZURA beat accents/transitions).

import {
	cleanVideoAppearance,
	cleanCustomStyle,
	normalizeVideoStyle,
	pickVideoStyle,
	videoStyleLines,
	VIDEO_STYLES,
	type VideoStyleKey
} from './video-styles';

export type VideoRecipeKey = 'explainer' | 'story' | 'split-jizura' | 'data' | 'footage' | 'free';
export type VideoFrameKey = '16:9' | '9:16' | '1:1';
/** Opening 3-second visual hook pattern for Douyin optimization. */
export type VideoHookKey = 'auto' | 'reversal' | 'pain' | 'result' | 'list';
/** Directorial animation choreography & storytelling strategy (for both enhancement and maker). */
export type VideoCreativeKey = 'auto' | 'metaphor' | 'contrast' | 'montage' | 'oneshot';
/** Split-screen direction for cartoon + JIZURA hybrid videos. */
export type SplitLayoutKey = 'auto' | 'tb' | 'lr';
/** Home PC JIZURA visual style (--style in jizura_mv.py; 'auto' lets --theme / omakase choose). */
export type JizuraStyleKey =
	| 'auto'
	| 'noir'
	| 'crimson'
	| 'caution'
	| 'magenta'
	| 'paper'
	| 'hud'
	| 'mint'
	| 'specimen'
	| 'transit'
	| 'blueprint'
	| 'rouge'
	| 'mono';
/** '' is Hermes itself; the rest are runners, started by the command in front of the brief. */
export type VideoMaker =
	| ''
	| 'codex'
	| 'reclaude'
	| 'cchclaude'
	| 'officlaude'
	| 'anyclaude'
	| 'agy'
	| 'offiagy';
/** With background music: the video as long as the music, or the music cut to the chosen length. */
export type VideoMusicFit = 'full' | 'trim';
/** Where the rendering runs: the home PC (RTX 3070; back to the server by itself when the PC is
 * off — the skill's `pc-video`), or the server. Pictures, narration and the chat stay on the server. */
export type VideoPlace = 'pc' | 'server';

export const VIDEO_RECIPES: { key: VideoRecipeKey; label: string; sub: string; hint: string }[] = [
	{
		key: 'explainer',
		label: '剧情动画',
		sub: '贴合字幕 · 多风格全动画',
		hint: '用 Remotion 分层角色与场景制作贴近字幕内容的连续动画，用画面把每句台词演活，绝不做纯文字动效'
	},
	{
		key: 'story',
		label: '绘本动画',
		sub: '统一画风分镜 · 动效运镜',
		hint: '先画统一风格的高质感动画分镜（或用你的图片），分层叠光影、天气、角色微动与镜头视差，不做静态幻灯片'
	},
	{
		key: 'split-jizura',
		label: '分屏混搭',
		sub: '卡通动画 · JIZURA 动效',
		hint: '上下或左右分屏：一半是贴合字幕的卡通/多风格动画场景，另一半由家里电脑 JIZURA 生成高能节奏动效与视觉装饰（PC 离线自动回落 Remotion）'
	},
	{
		key: 'data',
		label: '动态图解',
		sub: '场景可视化 · 动画图表',
		hint: '把原理、流程或数据做成具象动画场景与动态图表，用画面直观演活逻辑，拒绝枯燥纯文字'
	},
	{
		key: 'footage',
		label: '素材精剪',
		sub: '剪你上传的视频 · 动画包装',
		hint: '从你上传的视频里精选高光段落卡点剪辑，叠贴合氛围的卡通贴纸、动态转场与轻字幕'
	},
	{
		key: 'free',
		label: '自由混搭',
		sub: '按题材组合动画 + JIZURA',
		hint: '由执行者按主题自由组合全屏动画、绘本分镜或家里电脑 JIZURA 分屏/转场动效'
	}
];

export const VIDEO_FRAMES: { key: VideoFrameKey; label: string; size: string; tag?: string }[] = [
	{ key: '9:16', label: '竖屏', size: '1080×1920', tag: '抖音' },
	{ key: '16:9', label: '横屏', size: '1920×1080' },
	{ key: '1:1', label: '方形', size: '1080×1080' }
];

export const VIDEO_LENGTHS = [15, 30, 45, 60, 90, 180];

export const SPLIT_LAYOUTS: { key: SplitLayoutKey; label: string; sub: string }[] = [
	{ key: 'auto', label: '自动适配', sub: '竖屏上下分 · 横屏左右分' },
	{ key: 'tb', label: '上下分屏', sub: '上卡通动画 · 下 JIZURA 动效' },
	{ key: 'lr', label: '左右分屏', sub: '左卡通动画 · 右 JIZURA 动效' }
];

/** Curated JIZURA styles on the home PC (12 named skins + 'auto' across all 27 omakase styles). */
export const JIZURA_STYLES: { key: JizuraStyleKey; label: string; sub: string }[] = [
	{ key: 'auto', label: '自动配对', sub: '从 27 种风格按氛围挑' },
	{ key: 'caution', label: '潮酷黄黑', sub: 'caution · 冲击警示' },
	{ key: 'magenta', label: '赛博霓虹', sub: 'magenta · 潮流电音' },
	{ key: 'crimson', label: '绯红张力', sub: 'crimson · 热血高燃' },
	{ key: 'mint', label: '清新薄荷', sub: 'mint · 明快清爽' },
	{ key: 'paper', label: '复古纸感', sub: 'paper · 温柔胶片' },
	{ key: 'noir', label: '暗黑电影', sub: 'noir · 高级冷峻' },
	{ key: 'hud', label: '战术光栅', sub: 'hud · 科技数据' },
	{ key: 'blueprint', label: '工程蓝图', sub: 'blueprint · 精密网格' },
	{ key: 'rouge', label: '复古胭脂', sub: 'rouge · 东方韵味' },
	{ key: 'specimen', label: '杂志标本', sub: 'specimen · 精致刊物' },
	{ key: 'transit', label: '都市导视', sub: 'transit · 现代节奏' },
	{ key: 'mono', label: '极简黑白', sub: 'mono · 利落反差' }
];

export const VIDEO_HOOKS: { key: VideoHookKey; label: string; sub: string; guide: string }[] = [
	{
		key: 'auto',
		label: '自动匹配',
		sub: '按主题选最强高概念开场',
		guide: '前 3 秒直接切入最有视觉奇观或情绪张力的动画意象（夸张尺度反差、超现实隐喻或高能冲突），第 0.5 秒画面立刻动起来'
	},
	{
		key: 'reversal',
		label: '反差反转',
		sub: '一秒制造强烈视觉反差',
		guide: '前 3 秒用极强的正反动画画面对比（如巨大脑内暗影瞬间坍缩成巴掌大纸团）破冰，用视觉反差留住观众而非靠大字喊口号'
	},
	{
		key: 'pain',
		label: '情景代入',
		sub: '动画意象直击共鸣瞬间',
		guide: '前 3 秒用高共鸣生活瞬间叠加超现实心理可视化直接击中痛点，紧接用创意变形转场展开转折与解法'
	},
	{
		key: 'result',
		label: '高能前置',
		sub: '先抛全片最炸动画名场面',
		guide: '第 1 秒直接抛最有视觉冲击力的动画高潮帧或奇观隐喻，再以变速节奏层层揭晓前因与反转'
	},
	{
		key: 'list',
		label: '视觉清单',
		sub: '用同一母题串起 3 幕演进',
		guide: '前 3 秒先抛出贯穿全片的视觉母题与核心悬念，再用递进式动画场景与道具变形依次演完每个要点，越往后越惊艳'
	}
];

export const VIDEO_CREATIVES: {
	key: VideoCreativeKey;
	label: string;
	sub: string;
	short: string;
	guide: string;
}[] = [
	{
		key: 'auto',
		label: '智能导演',
		sub: '按题材自动定隐喻、变速与转场',
		short: '自动构思核心视觉隐喻、变速节奏与创意匹配转场，忌平淡流水账',
		guide: '按题材自由组合核心视觉隐喻、正反世界反差、变速快切与匹配变形转场；严禁把一件琐碎日常平摊成等长流水账'
	},
	{
		key: 'metaphor',
		label: '视觉隐喻',
		sub: '把抽象情绪/道理化成动画奇观',
		short: '以超现实视觉隐喻贯穿全片（如尺度夸张、影子怪兽坍缩、意象变形），忌写实流水账',
		guide: '必须设计只有动画才演得出的核心视觉隐喻（如脑内聚光灯把小石子投射成百米巨兽阴影、一碰现实阳光便泄气缩成纸偶），用强轮廓、大光影反差和形态变形外化内心或原理'
	},
	{
		key: 'contrast',
		label: '反差双世界',
		sub: '想象与现实 / 误区与真相强对撞',
		short: '冷暖色温与尺度极强对撞（如压抑暗影脑补世界 vs 轻盈通透现实），用破壁转场反转',
		guide: '建立两套视觉反差极强的世界（压抑冷暗/夸张扭曲的脑补或误区态 vs 暖光开阔/轻盈松弛的真相态），通过多次拉扯与高潮破壁一举反转情绪'
	},
	{
		key: 'montage',
		label: '多幕共鸣',
		sub: '同一视觉母题串起 2–3 个高共鸣切面',
		short: '用同一贯穿视觉母题无缝串联 2–3 个直击人心的生活切面，节奏递进收束',
		guide: '拒绝死磕一件平淡小事撑满全片：提炼 2–3 个高度共鸣的真实生活切面，用同一个标志性视觉母题（如同一束光、同一只变形纸怪或同一枚跳动红点）无缝串接并层层升华'
	},
	{
		key: 'oneshot',
		label: '一镜变形',
		sub: '匹配剪辑与图形变形丝滑穿梭',
		short: '全程匹配剪辑、图形变形与穿门/穿镜穿梭，镜头如流体连贯流动，零生硬硬切',
		guide: '把全片编排为流动的视觉长卷：镜头通过物体变形（Morph）、形状匹配剪辑（Match Cut）、穿门/穿瞳孔/前景擦除无缝切入下一幕，让每次转场本身成为惊喜'
	}
];

export const VIDEO_VOICES: { key: string; label: string }[] = [
	{ key: 'zh-CN-YunxiNeural', label: '男声 · 讲述' },
	{ key: 'zh-CN-XiaoxiaoNeural', label: '女声 · 温和' },
	{ key: 'zh-CN-YunyangNeural', label: '男声 · 新闻' },
	{ key: 'zh-CN-XiaoyiNeural', label: '女声 · 活泼' },
	{ key: '', label: '不配音' }
];

export const VIDEO_MAKERS: { key: VideoMaker; label: string; sub: string }[] = [
	{ key: '', label: 'Hermes', sub: '直接做' },
	{ key: 'codex', label: 'codex', sub: 'OpenAI Codex' },
	{ key: 'reclaude', label: 'reclaude', sub: 'Claude · 拼车' },
	{ key: 'cchclaude', label: 'cchclaude', sub: 'Claude · 自有中转' },
	{ key: 'officlaude', label: '官方 Claude', sub: 'Claude · 官网订阅' },
	{ key: 'anyclaude', label: 'anyclaude', sub: 'Claude · 免费较慢' },
	{ key: 'agy', label: 'agy', sub: 'Gemini · 快' },
	{ key: 'offiagy', label: 'offiagy', sub: 'AGY · Google 官方登录' }
];

/** One-click animation-first Douyin recipes: sets frame, duration, recipe, visual style, voice, hook and JIZURA config. */
export type DouyinTemplate = {
	key: string;
	label: string;
	badge: string;
	sub: string;
	sample: string;
	patch: Partial<VideoSettings>;
};

export const DOUYIN_TEMPLATES: DouyinTemplate[] = [
	{
		key: 'anime-story',
		label: '动漫剧情',
		badge: '推荐',
		sub: '9:16 · 45秒 · 日漫卡通',
		sample: '用 45 秒日漫卡通动画讲“为什么越想自律越容易摆烂”，用生动卡通角色演活日常心理变化，画面紧贴旁白字幕',
		patch: {
			kind: 'normal',
			douyin: true,
			hook: 'pain',
			creative: 'metaphor',
			frame: '9:16',
			seconds: 45,
			recipe: 'explainer',
			style: 'anime-cartoon',
			jizuraAccent: true,
			voice: 'zh-CN-YunxiNeural',
			subtitles: true
		}
	},
	{
		key: 'split-jizura',
		label: '分屏动画×JIZURA',
		badge: 'PC特色',
		sub: '9:16 · 30秒 · 上下分屏',
		sample: '30 秒上下分屏动画短片：上半屏用夸张视觉隐喻演活职场反常识反转，下半屏联动家里电脑 JIZURA 潮酷动效卡拍呼应',
		patch: {
			kind: 'normal',
			douyin: true,
			hook: 'reversal',
			creative: 'contrast',
			frame: '9:16',
			seconds: 30,
			recipe: 'split-jizura',
			style: 'anime-cartoon',
			splitLayout: 'tb',
			mvTheme: 'kinetic',
			jizuraStyle: 'auto',
			jizuraAccent: true,
			voice: 'zh-CN-XiaoyiNeural',
			subtitles: true
		}
	},
	{
		key: 'comic-contrast',
		label: '漫格避坑',
		badge: '高互动',
		sub: '9:16 · 30秒 · 潮酷漫格',
		sample: '30 秒波普漫画风避坑动画：用卡通分格正反世界强对比演活 3 个日常踩坑习惯，节奏明快有趣',
		patch: {
			kind: 'normal',
			douyin: true,
			hook: 'reversal',
			creative: 'contrast',
			frame: '9:16',
			seconds: 30,
			recipe: 'explainer',
			style: 'comic-pop',
			jizuraAccent: true,
			voice: 'zh-CN-XiaoyiNeural',
			subtitles: true
		}
	},
	{
		key: 'guochao-tale',
		label: '国潮叙事',
		badge: '高完播',
		sub: '9:16 · 60秒 · 国潮插画',
		sample: '60 秒国潮插画动画讲述一个跌宕起伏的历史典故：先抛悬念高潮名场面，山水云雾与人物剪影层层推进',
		patch: {
			kind: 'normal',
			douyin: true,
			hook: 'result',
			creative: 'metaphor',
			frame: '9:16',
			seconds: 60,
			recipe: 'story',
			style: 'guochao',
			mvTheme: 'wa',
			jizuraAccent: true,
			voice: 'zh-CN-YunyangNeural',
			subtitles: true
		}
	},
	{
		key: 'sticker-science',
		label: '贴纸科普',
		badge: '涨粉',
		sub: '9:16 · 60秒 · 贴纸大画布',
		sample: '60 秒贴纸大画布科普动画：一镜到底用可视化道具与微缩机关拆解日常现象背后的科学原理',
		patch: {
			kind: 'normal',
			douyin: true,
			hook: 'list',
			creative: 'oneshot',
			frame: '9:16',
			seconds: 60,
			recipe: 'explainer',
			style: 'sticker',
			jizuraAccent: false,
			voice: 'zh-CN-YunxiNeural',
			subtitles: true
		}
	},
	{
		key: 'storybook-heal',
		label: '治愈绘本',
		badge: '高转发',
		sub: '9:16 · 30秒 · 水彩绘本',
		sample: '30 秒水彩绘本治愈动画：脑海里把小担忧投射成遮天蔽日的巨兽影子，阳光一照“啵”地缩成掌心暖光纸偶，温柔治愈',
		patch: {
			kind: 'normal',
			douyin: true,
			hook: 'reversal',
			creative: 'metaphor',
			frame: '9:16',
			seconds: 30,
			recipe: 'story',
			style: 'storybook',
			mvTheme: 'ballad',
			jizuraAccent: false,
			voice: 'zh-CN-XiaoxiaoNeural',
			subtitles: true
		}
	}
];

/** 两类视频: an ordinary animated video, or an MP3 made into an animated / split-screen MV. */
export type VideoKind = 'normal' | 'mv';
export type MvTheme = 'kinetic' | 'pop' | 'ballad' | 'lyricpv' | 'wa' | 'any';
export const VIDEO_KINDS: { key: VideoKind; label: string; sub: string }[] = [
	{ key: 'normal', label: '普通视频', sub: '多风格动画、剧情、分屏、科普…' },
	{ key: 'mv', label: 'MP3 做 MV', sub: '动画 MV · 卡通×JIZURA 分屏' }
];

/** JIZURA's おまかせ directions (skill video-studio, --theme). */
export const MV_THEMES: { key: MvTheme; label: string; sub: string }[] = [
	{ key: 'kinetic', label: '动感潮酷', sub: '跳跃快切 · 强鼓点' },
	{ key: 'pop', label: '明快流行', sub: '活力多彩 · 轻快感' },
	{ key: 'ballad', label: '温柔抒情', sub: '慢歌氛围 · 柔光感' },
	{ key: 'lyricpv', label: '精致排版', sub: '设计感强 · 百搭曲风' },
	{ key: 'wa', label: '东方和风', sub: '国风/古风 · 诗意感' },
	{ key: 'any', label: '随机探索', sub: '交给 JIZURA 自动挑' }
];

/** What an MV shows — NEVER pure text PV:
 *  - split-tb: top half cartoon/multi-style animation + bottom half PC JIZURA motion (ideal for 9:16)
 *  - split-lr: left half cartoon/multi-style animation + right half PC JIZURA motion (ideal for 16:9 / 1:1)
 *  - animated: full-frame rich multi-style animation with dynamic lyrics integrated into the scenes
 */
export type MvVisual = 'split-tb' | 'split-lr' | 'animated';
export const MV_VISUALS: { key: MvVisual; label: string; sub: string; tag?: string }[] = [
	{
		key: 'split-tb',
		label: '上下分屏 · 卡通 + 动效',
		sub: '上半屏贴歌词卡通动画，下半屏 PC JIZURA 动效',
		tag: '竖屏推荐'
	},
	{
		key: 'split-lr',
		label: '左右分屏 · 卡通 + 动效',
		sub: '左半屏贴歌词卡通动画，右半屏 PC JIZURA 动效',
		tag: '横屏推荐'
	},
	{
		key: 'animated',
		label: '全屏动画 · 多风格融字',
		sub: '全屏贴歌词意境的多风格动画，动态歌词融入画面'
	}
];

/** Lyrics pasted for an MV (a whole song's lines, LRC times included). */
export const MV_LYRICS_MAX = 4000;

/** 发布标准: every video is animation-first and made to be published — never pure text motion,
 * never simplistic stills, holding people from frame 0 to the end. */
export const publishLines = (place: VideoPlace) => [
	'',
	'## 发布标准（默认要求，每个视频都要做到）',
	'- 拒绝纯文字动效与简陋画面：无论普通视频还是 MV，都要做贴近字幕或歌词意境的丰富动画（具象角色、视觉隐喻、场景、道具、光影与镜头运动），绝不做纯黑底飞大字或单图干放大',
	'- 动画导演级创意与转场：用只有动画才演得出的视觉隐喻、夸张尺度反差与冷暖光影外化主题，严禁平淡写实流水账；幕间优先使用匹配剪辑（Match Cut）、图形变形（Morph）、前景遮挡擦除或穿门/穿镜转场，少用生硬硬切',
	'- 第 0.5 秒内就要进入有吸引力的动态画面，不要黑场、静止片名卡或静态干等',
	'- 变速节奏与呼吸感：片头片尾即使只有音乐没有人声，动画画面也要持续流动（任何画面静止不超过 2 秒，同一构图停留不超过 4 秒）；紧张或堆叠处可 1.5–3 秒快切，反转或高潮前留短暂顿挫，严禁整片机械均分等长镜头',
	'- 动画要贴内容：动作直接演绎画面在讲的事和情绪（讲故事有角色大姿态与意象变形、讲对比有双世界反差、讲流程有物件运转，抒情缓高潮快），不做无意义的整屏乱晃或生硬碎微动作',
	'- 全程连续、节奏跟着音乐或旁白走，约 60–75% 处放最有冲击力的动画高潮镜头；结尾 1–2 秒内回扣开场意象并收在一个仍有微动的完整构图上',
	place === 'server'
		? '- 封面：交付前按技能 video-studio「封面」一节运行 scripts/cover.py all，用 gpt-image 依据首帧画好动画风封面并放进视频第 0 帧'
		: '- 封面：交付前按技能 video-studio「封面」一节，用 gpt-image 依据首帧画好动画风封面并放进视频第 0 帧（pc-video deliver 会自动做；家里电脑不在线、改在服务器做时运行 scripts/cover.py all）'
];

/** Describe the PC JIZURA configuration cleanly (shared between normal split-mix / accent and MV). */
export const jizuraSpecText = (themeKey: MvTheme, styleKey: JizuraStyleKey): string => {
	const theme = MV_THEMES.find((t) => t.key === themeKey) ?? MV_THEMES[0];
	const style = JIZURA_STYLES.find((s) => s.key === styleKey) ?? JIZURA_STYLES[0];
	const styleFlag = style.key === 'auto' ? '（样式由主题从 27 种里自动配对）' : `，指定 --style ${style.key}（${style.label}）`;
	return `--theme ${theme.key}（${theme.label}）${styleFlag}`;
};

export const resolveSplitDirection = (layout: SplitLayoutKey, frame: VideoFrameKey): 'tb' | 'lr' => {
	if (layout === 'tb' || layout === 'lr') return layout;
	return frame === '9:16' ? 'tb' : 'lr';
};

/** Directorial animation choreography line(s) for both 提示词增强 and the final maker brief. */
export const creativeLines = (
	opts: Pick<VideoBriefOptions, 'creative' | 'recipe'>,
	forMaker = false
): string[] => {
	if (opts.recipe === 'footage') return [];
	const mode = VIDEO_CREATIVES.find((c) => c.key === opts.creative) ?? VIDEO_CREATIVES[0];
	if (!forMaker) {
		return [`- 动画编排：${mode.label}（${mode.short}）`];
	}
	return [
		`- 动画编排（${mode.label}）：${mode.guide}`,
		'- 镜头与转场编排：景别在极近特写、中景与开阔全景间拉开反差；用强轮廓、大光影变化与图形变形打造适合 Remotion/SVG 分层动画演活的标志性镜头，幕间以匹配剪辑、变形或前景遮挡衔接'
	];
};

/** 抖音爆款规格: animation-first short-video rules (never pushing pure-text kinetic walls;
 * respects burned-in subtitles by keeping on-screen text minimal when subtitles are on). */
export const douyinLines = (
	opts: Pick<VideoBriefOptions, 'douyin' | 'hook' | 'frame' | 'subtitles'>,
	forMaker = false
): string[] => {
	if (!opts.douyin) return [];
	const hook = VIDEO_HOOKS.find((h) => h.key === opts.hook) ?? VIDEO_HOOKS[0];
	const vertical = opts.frame === '9:16';
	if (!forMaker) {
		return [
			`- 抖音爆款优化：开启（前 3 秒「${hook.label}」动画钩子禁寒暄；2–4 秒换动画景别/动作；${vertical ? '严守 9:16 安全区；' : ''}${opts.subtitles ? '已有字幕不堆文字动效，专注动画演活台词；' : '动画为主、短标题克制融入；'}结尾动画收束+拟 6–10 字动画风封面标题）`
		];
	}
	return [
		'',
		'## 抖音爆款规格（动画叙事优先，按高完播与高互动标准执行）',
		`- 前 3 秒动画视觉钩子（${hook.label}）：${hook.guide}；严禁“大家好/今天聊聊”式慢热开场或纯黑底大字卡`,
		'- 高密动画节拍：旁白短句口语化（每句 ≤ 14 字），每 2–4 秒必有一次画面演进（角色动作切换、景别推拉、场景转换或道具互动），每一幕画面紧扣当前字幕内容，约 60–75% 处给最高能动画反转或视觉高潮',
		...(opts.subtitles
			? [
					'- 有字幕不凸显文字动效：视频已开启底部烧录字幕，画面不必再堆叠满屏弹跳大字、花字或繁复文字动效；把视觉焦点全部留给贴合字幕内容的动画剧情与细节表演，仅在章节转场或关键数据时点缀极简标签'
				]
			: [
					'- 无字幕轻排版：未开烧录字幕时，仅把极少量关键短句克制融入动画构图，画面主体仍必须是生动动画场景，绝不退化成纯文字视频'
				]),
		...(vertical
			? [
					'- 抖音 9:16 安全区（硬规范）：顶部留 12%（状态/搜索栏）、右侧留 14%（点赞/评论/收藏/转发按钮列）、底部留 22%（作者名/标题/进度条）；动画主角焦点与字幕严格放在安全区内（X: 6%–84%，Y: 14%–76%），字幕清晰易读不挡角色表情'
				]
			: ['- 构图可读性：动画主体居中聚焦，字幕与画面对比清晰，手机小屏一眼看清']),
		'- 动画收尾与高点击封面：结尾 3–4 秒用一组完整呼应主题的动画定格画面自然收束（配一句轻互动提问或收藏提示，不做丑陋文字墙）；第 0 帧封面延用本片动画画风，构图集中、配 6–10 字干净短标题'
	];
};

export const VIDEO_PLACES: { key: VideoPlace; label: string; sub: string }[] = [
	{ key: 'pc', label: '家里电脑', sub: 'RTX 3070 · 支持 JIZURA · 存 D 盘' },
	{ key: 'server', label: '服务器', sub: '一直在线 · 渲染较慢' }
];

export const VIDEO_SKILL_PATH = '/root/.hermes/skills/creative/video-studio/SKILL.md';
export const VIDEO_FILM_SCRIPT = '/root/.hermes/skills/creative/video-studio/scripts/film.py';

/** The longest music a video follows (「跟随音乐」, e.g. an MP3 made into an MP4). An hour still fits
 * HaloWebUI's 500 MB limit for a delivered video at 720p; longer music is cut to the chosen length. */
export const MUSIC_MAX_SECONDS = 60 * 60;
/** nginx in front of HaloWebUI takes uploads up to 100 MB (an hour of MP3 at ~200 kbps). */
export const MUSIC_MAX_BYTES = 100 * 1024 * 1024;
/** Beyond this a video following its music gets the long-video guidance (light pictures, 720p, ≤ 500 MB). */
export const LONG_VIDEO_SECONDS = 10 * 60;
/** HaloWebUI fetches a delivered file of at most 500 MB (utils/hermes_media.py MEDIA_FETCH_MAX_BYTES). */
const DELIVERY_MAX_MB = 500;
const MP3_TYPES = ['', 'audio/mpeg', 'audio/mp3', 'audio/mpeg3', 'audio/x-mpeg-3', 'audio/x-mp3'];

/** The background music the brief names: its file name and length (null: not known yet). */
export type VideoMusic = { name: string; seconds: number | null };

/** What 提示词增强 brought (utils/studio-prep.ts): the request as the user wrote it, the key facts
 * from the web or the 精答 / 讨论 it asked first, and where they come from. */
export type VideoPrep = {
	original: string;
	/** The draft predates the current settings; only its content remains useful. */
	stale?: boolean;
	notes: string;
	sources: { title: string; url: string }[];
	run?: { label: string; href: string } | null;
};

export type VideoBriefOptions = {
	idea: string;
	style: VideoStyleKey;
	customStyle: string;
	appearance: string;
	recipe: VideoRecipeKey;
	frame: VideoFrameKey;
	seconds: number;
	voice: string;
	subtitles: boolean;
	douyin: boolean;
	hook: VideoHookKey;
	creative?: VideoCreativeKey;
	splitLayout: SplitLayoutKey;
	jizuraStyle: JizuraStyleKey;
	jizuraAccent: boolean;
	maker: VideoMaker;
	musicFit: VideoMusicFit;
	place: VideoPlace;
	attachments?: { name: string; kind: 'image' | 'video' | 'audio' | 'file' }[];
	music?: VideoMusic | null;
	prep?: VideoPrep | null;
	/** 提示词增强 still going on the server: the chat's Hermes turn waits for it and puts its result
	 * in place of this line (backend utils/studio_prep.py PREP_MARK). */
	prepJob?: string | null;
	/** What 自动选择 reads to pick a style: the user's own words (the idea before enhancement). */
	styleTopic?: string;
	/** 普通视频 (default) or MP3 做 MV. */
	kind?: VideoKind;
	mvTheme?: MvTheme;
	mvVisual?: MvVisual;
	/** MP3 做 MV: the lyrics the user pasted ('' = none: they are transcribed). */
	lyrics?: string;
};

export type VideoSettings = Omit<
	VideoBriefOptions,
	'idea' | 'attachments' | 'music' | 'prep' | 'prepJob' | 'styleTopic' | 'lyrics'
>;

/** The brief's line for an enhancement still going (backend utils/studio_prep.py PREP_MARK). */
export const prepMarkLine = (id: string) => `（制作前准备：HaloWebUI 正在增强需求，编号 ${id}）`;

export const DEFAULT_VIDEO_SETTINGS: VideoSettings = {
	style: 'auto',
	customStyle: '',
	appearance: '',
	recipe: 'explainer',
	frame: '9:16',
	seconds: 30,
	voice: 'zh-CN-YunxiNeural',
	subtitles: true,
	douyin: true,
	hook: 'auto',
	creative: 'auto',
	splitLayout: 'auto',
	jizuraStyle: 'auto',
	jizuraAccent: true,
	maker: '',
	musicFit: 'full',
	place: 'pc',
	kind: 'normal',
	mvTheme: 'kinetic',
	mvVisual: 'split-tb'
};

const pick = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T =>
	allowed.includes(value as T) ? (value as T) : fallback;

/** The choices remembered between visits (localStorage), whatever shape they were stored in.
 * Legacy mvVisual='lyrics' migrates to 'split-tb' (half cartoon + half JIZURA motion). */
export const normalizeVideoSettings = (value: unknown): VideoSettings => {
	const raw = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
	const seconds = Number(raw.seconds);
	return {
		style: normalizeVideoStyle(raw.style),
		customStyle: cleanCustomStyle(raw.customStyle),
		appearance: cleanVideoAppearance(raw.appearance),
		recipe: pick(
			raw.recipe,
			VIDEO_RECIPES.map((r) => r.key),
			DEFAULT_VIDEO_SETTINGS.recipe
		),
		frame: pick(
			raw.frame,
			VIDEO_FRAMES.map((f) => f.key),
			DEFAULT_VIDEO_SETTINGS.frame
		),
		seconds:
			Number.isFinite(seconds) && seconds >= 5 && seconds <= 600
				? Math.round(seconds)
				: DEFAULT_VIDEO_SETTINGS.seconds,
		voice: pick(
			raw.voice,
			VIDEO_VOICES.map((v) => v.key),
			DEFAULT_VIDEO_SETTINGS.voice
		),
		subtitles:
			typeof raw.subtitles === 'boolean' ? raw.subtitles : DEFAULT_VIDEO_SETTINGS.subtitles,
		douyin: typeof raw.douyin === 'boolean' ? raw.douyin : DEFAULT_VIDEO_SETTINGS.douyin,
		hook: pick(
			raw.hook,
			VIDEO_HOOKS.map((h) => h.key),
			DEFAULT_VIDEO_SETTINGS.hook
		),
		creative: pick(
			raw.creative,
			VIDEO_CREATIVES.map((c) => c.key),
			DEFAULT_VIDEO_SETTINGS.creative ?? 'auto'
		),
		splitLayout: pick(
			raw.splitLayout,
			SPLIT_LAYOUTS.map((l) => l.key),
			DEFAULT_VIDEO_SETTINGS.splitLayout
		),
		jizuraStyle: pick(
			raw.jizuraStyle,
			JIZURA_STYLES.map((s) => s.key),
			DEFAULT_VIDEO_SETTINGS.jizuraStyle
		),
		jizuraAccent:
			typeof raw.jizuraAccent === 'boolean'
				? raw.jizuraAccent
				: DEFAULT_VIDEO_SETTINGS.jizuraAccent,
		maker: pick(
			raw.maker,
			VIDEO_MAKERS.map((m) => m.key),
			DEFAULT_VIDEO_SETTINGS.maker
		),
		musicFit: pick(raw.musicFit, ['full', 'trim'] as const, DEFAULT_VIDEO_SETTINGS.musicFit),
		place: pick(
			raw.place,
			VIDEO_PLACES.map((p) => p.key),
			DEFAULT_VIDEO_SETTINGS.place
		),
		kind: pick(
			raw.kind,
			VIDEO_KINDS.map((k) => k.key),
			'normal'
		),
		mvTheme: pick(
			raw.mvTheme,
			MV_THEMES.map((t) => t.key),
			DEFAULT_VIDEO_SETTINGS.mvTheme
		),
		mvVisual: pick(
			raw.mvVisual,
			MV_VISUALS.map((v) => v.key),
			DEFAULT_VIDEO_SETTINGS.mvVisual
		)
	};
};

/** Why *file* cannot be the background music ('' when it can): an MP3 by name and type, not
 * empty, not over 100 MB. Its first bytes (*head*, when read) must look like MP3 too. */
export const musicFileProblem = (
	file: { name: string; type: string; size: number },
	head?: Uint8Array
): string => {
	if (!/\.mp3$/i.test(file.name || '') || !MP3_TYPES.includes((file.type || '').toLowerCase())) {
		return '背景音乐只支持 MP3 文件';
	}
	if (!file.size) return '这个 MP3 是空的';
	if (file.size > MUSIC_MAX_BYTES) return `背景音乐不能超过 ${MUSIC_MAX_BYTES / 1024 / 1024} MB`;
	if (head && head.length >= 3 && !isMp3Head(head)) return '文件内容不是 MP3';
	return '';
};

/** An ID3 tag or an MPEG audio frame (11 sync bits) at the start. */
export const isMp3Head = (head: Uint8Array): boolean =>
	(head[0] === 0x49 && head[1] === 0x44 && head[2] === 0x33) ||
	(head[0] === 0xff && (head[1] & 0xe0) === 0xe0);

/** m:ss for a music length, as an audio player shows it (whole seconds, rounded down). */
export const clockLabel = (seconds: number) => {
	const s = Math.max(0, Math.floor(seconds));
	return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

/** A file name as plain text inside one line of the brief: it cannot add lines or headings, nor
 * a `MEDIA:` tag that an echoing reply would hand over as a file. */
const plainName = (name: string) =>
	(name || '')
		.replace(/[\u0000-\u001f\u007f]+/g, ' ')
		.replace(/\s+/g, ' ')
		.replace(/MEDIA:/gi, 'MEDIA：')
		.trim()
		.slice(0, 120) || '未命名';

const ATTACHMENT_KIND: Record<string, string> = {
	image: '图片',
	video: '视频',
	audio: '音频',
	file: '文件'
};

export const attachmentKind = (type: string, name = ''): 'image' | 'video' | 'audio' | 'file' => {
	const t = (type || '').toLowerCase();
	if (t.startsWith('image/')) return 'image';
	if (t.startsWith('video/') || /\.(mp4|m4v|mov|webm|mkv)$/i.test(name)) return 'video';
	if (t.startsWith('audio/') || /\.(mp3|m4a|wav|ogg|opus|flac|aac)$/i.test(name)) return 'audio';
	return 'file';
};

const lengthLabel = (seconds: number) =>
	seconds >= 60 && seconds % 60 === 0 ? `${seconds / 60} 分钟` : `${seconds} 秒`;

/** The video follows the music's length: chosen, and the music not longer than a video can be. */
export const musicSetsLength = (music: VideoMusic | null | undefined, fit: VideoMusicFit) =>
	!!music && fit === 'full' && (music.seconds == null || music.seconds <= MUSIC_MAX_SECONDS);

const attachmentCounts = (attachments: NonNullable<VideoBriefOptions['attachments']>) =>
	Object.entries(
		attachments.reduce<Record<string, number>>(
			(acc, a) => ({ ...acc, [a.kind]: (acc[a.kind] ?? 0) + 1 }),
			{}
		)
	)
		.map(([kind, n]) => `${n} 个${ATTACHMENT_KIND[kind] ?? '文件'}`)
		.join('、');

/** Normal-video JIZURA integration lines (split-screen hybrid OR beat-synced accent layer on PC). */
const normalJizuraLines = (opts: Omit<VideoBriefOptions, 'idea'>, forMaker = false): string[] => {
	const jizuraCfg = jizuraSpecText(opts.mvTheme ?? 'kinetic', opts.jizuraStyle ?? 'auto');
	if (opts.recipe === 'split-jizura') {
		const dir = resolveSplitDirection(opts.splitLayout ?? 'auto', opts.frame);
		const dirLabel = dir === 'tb' ? '上下分屏（上半屏约 56% 卡通/多风格动画 + 下半屏约 44% 节奏动效）' : '左右分屏（左半屏约 56% 卡通/多风格动画 + 右半屏约 44% 节奏动效）';
		if (!forMaker) {
			return [
				`- 分屏混搭（动画 × PC JIZURA）：${dirLabel}；动效半屏风格 ${jizuraCfg}，两半配色统一、绝不做纯文字全屏`
			];
		}
		return [
			`- 分屏布局：${dirLabel}，两半之间用精致动态分割线或声波条衔接，配色与主动画画风呼应`,
			opts.place === 'server'
				? `- 动效半屏（服务器模式）：用 Remotion 做出等效的节奏图形、几何脉冲与动效层（${jizuraCfg} 风格方向），不退化成纯白底大字`
				: `- 动效半屏（家里电脑 JIZURA）：调用家里电脑 pc-video jizura（${jizuraCfg}）渲染高质感节奏动效层（传入对应章节短词/情绪词或节奏锚点，而非满屏长字幕），与 Remotion 卡通动画半屏合成；家里电脑不在线时自动改用 Remotion 制作同等动效半屏`
		];
	}
	if (opts.recipe !== 'footage' && opts.jizuraAccent) {
		if (!forMaker) {
			return [`- PC JIZURA 动效加持：开启（片头/转场/高潮可融合家里电脑 JIZURA ${jizuraCfg} 动效，主体保持全动画）`];
		}
		return [
			opts.place === 'server'
				? '- 动效转场加持：开头钩子、章节切换与高潮处加入强节奏动态图形转场，主体始终是贴合字幕的多风格动画'
				: `- PC JIZURA 动效加持：可调用家里电脑 pc-video jizura（${jizuraCfg}）制作高冲击力的片头视觉转场、章节卡点叠层或高潮短切（控制在局部点缀，绝不做整片纯文字，且有底部字幕时不抢戏）；PC 离线自动改用 Remotion`
		];
	}
	return [];
};

/** The decided settings as the brief words them (做法, 画幅, 时长, 配音, 字幕), one per line. */
const requirementLines = (opts: Omit<VideoBriefOptions, 'idea'>, forMaker = false) => {
	const recipe = VIDEO_RECIPES.find((r) => r.key === opts.recipe) ?? VIDEO_RECIPES[0];
	const frame = VIDEO_FRAMES.find((f) => f.key === opts.frame) ?? VIDEO_FRAMES[0];
	const voice = VIDEO_VOICES.find((v) => v.key === opts.voice);
	const music = opts.music ?? null;
	const musicClock = music?.seconds ? clockLabel(music.seconds) : '';
	return [
		`- 做法：${recipe.label}（${recipe.hint}）`,
		`- 画幅：${frame.label} ${frame.key}（${frame.size}，30fps）`,
		musicSetsLength(music, opts.musicFit)
			? `- 时长：跟背景音乐一样长${musicClock ? `（${musicClock}）` : ''}`
			: `- 时长：约 ${lengthLabel(opts.seconds)}`,
		`- 配音：${voice && voice.key ? `中文配音，${voice.label}（edge-tts ${voice.key}）` : '不要配音'}`,
		`- 字幕：${opts.subtitles ? '烧录中文字幕（已有字幕，画面不必凸显文字动效）' : '不要字幕'}`,
		...creativeLines(opts, forMaker),
		...normalJizuraLines(opts, forMaker)
	];
};

/** The brief's line on where to render (the skill's 「生成位置」 section acts on it). */
export const placeLine = (place: VideoPlace) =>
	place === 'server'
		? '- 生成位置：服务器（直接在服务器渲染，不用家里电脑）'
		: '- 生成位置：家里电脑（按技能 video-studio「生成位置」一节，渲染都用 pc-video；成片用 pc-video deliver 留在家里电脑 D:\\HermesWork\\视频\\，回复只写 Windows 路径；家里电脑不在线时自动改在服务器渲染并照常交付，交付时说明实际在哪渲染）';

/** The settings for 提示词增强 to size the content to (it never changes them). */
export const videoSettingsText = (opts: Omit<VideoBriefOptions, 'idea'>): string => {
	const lines = requirementLines(opts, false);
	const attachments = opts.attachments ?? [];
	lines.push(...douyinLines(opts, false));
	lines.push(...videoStyleLines({ ...opts, topic: opts.styleTopic ?? '' }, false));
	if (opts.music)
		lines.push(`- 背景音乐：用户指定（${plainName(opts.music.name)}），视频按音乐的节拍和长度做`);
	// The server accepts 1500 characters. Bound names after the essential constraints.
	if (attachments.length)
		lines.push(
			`- 参考附件：${attachmentCounts(attachments)}（${attachments.map((a) => plainName(a.name).slice(0, 14)).join('、')}）`
		);
	return lines.join('\n');
};

const PREP_ORIGINAL_MAX = 1500;

/** The brief's part from 提示词增强: the user's own words, the key facts and their sources. */
const prepLines = (prep: VideoPrep, idea: string): string[] => {
	const lines: string[] = [];
	if (prep.stale)
		lines.push(
			'',
			'## 设置已更新',
			'“待更新的增强草稿”段基于旧设置；如有“增强后的需求”段，以该段为更新结果。保留内容与用户文字修改，按下方当前制作设置协调分镜和视觉；旧增强补充的风格、节奏不得覆盖当前设置。用户原话中明确的视觉要求仍优先于预设。'
		);
	const original = prep.original.trim();
	if (original && original !== idea.trim()) {
		lines.push(
			'',
			'## 用户原话（上面是据此增强的需求；两者冲突时以原话为准）',
			original.length > PREP_ORIGINAL_MAX ? `${original.slice(0, PREP_ORIGINAL_MAX)}…` : original
		);
	}
	const sources = prep.sources.filter((s) => /^https?:\/\//i.test(s.url));
	if (prep.notes.trim() || sources.length || prep.run) {
		lines.push('', '## 资料与依据（制作前已查好：事实和数字以此为准，不要编造）');
		if (prep.notes.trim()) lines.push(prep.notes.trim());
		if (prep.run)
			lines.push(`- ${prep.run.label}结论：HaloWebUI ${prep.run.href}（完整内容在那里）`);
		if (sources.length) {
			lines.push('- 来源：');
			sources.forEach((s, i) =>
				lines.push(`  ${i + 1}. ${plainName(s.title)} ${s.url.replace(/\s/g, '')}`)
			);
		}
	}
	return lines;
};

/** The delivery paragraph's last instruction: where the finished video goes. */
const MEDIA_DELIVERY = '最后单独一行写「MEDIA:」紧跟成片 mp4 的绝对路径（这一行不要放进代码块）';
const deliveryLine = (place: VideoPlace) =>
	place === 'server'
		? `完成后用一小段话说明做法、动画风格、时长和分镜；先用 scripts/cover.py all 放好封面，${MEDIA_DELIVERY}。`
		: `完成后用一小段话说明做法、动画风格、是否联动 JIZURA、时长和分镜。在家里电脑做的：按技能用 pc-video deliver 交付（自动放封面、存到 D:\\HermesWork\\视频\\），回复里只写 Windows 路径，不写 MEDIA；家里电脑不在线、改在服务器做的：先用 scripts/cover.py all 放好封面，${MEDIA_DELIVERY}。`;

/** Resolve the MV's cartoon/animation visual style label for UI and brief clarity. */
export const resolveMvStyleLabel = (opts: Pick<VideoBriefOptions, 'style' | 'styleTopic' | 'idea' | 'attachments'>): string => {
	if (opts.style === 'reference') return '跟随参考';
	if (opts.style === 'custom') return '自定义动画风';
	const key =
		opts.style === 'auto'
			? pickVideoStyle(opts.styleTopic ?? opts.idea ?? '', { attachments: opts.attachments, kind: 'mv' }).key
			: opts.style;
	return VIDEO_STYLES.find((s) => s.key === key)?.label ?? '日漫卡通';
};

/** Split-screen MV (half cartoon/multi-style animation + half PC JIZURA kinetic motion). */
const splitMvLines = (
	place: VideoPlace,
	mvVisual: 'split-tb' | 'split-lr',
	theme: (typeof MV_THEMES)[number],
	jizuraStyle: JizuraStyleKey,
	frame: VideoFrameKey
) => {
	const isTb = mvVisual === 'split-tb';
	const dirName = isTb ? '上下分屏' : '左右分屏';
	const cartoonPos = isTb ? '上半屏（约 55–58% 高度）' : '左半屏（约 55–58% 宽度）';
	const motionPos = isTb ? '下半屏（约 42–45% 高度）' : '右半屏（约 42–45% 宽度）';
	const jizuraAspect = isTb ? (frame === '9:16' ? '1:1 或 4:3' : '16:9') : frame === '16:9' ? '1:1 或 3:4' : '9:16';
	const jizuraCfg = jizuraSpecText(theme.key, jizuraStyle);
	return [
		`- 做法：分屏动画 MV（${dirName}：一半卡通动画 + 一半动效）—— 按技能 video-studio「分屏动画 MV」流程制作，严禁纯文字 PV 或单图慢放；无旁白、不另加底部字幕条`,
		`- 卡通动画半屏（${cartoonPos}）：用 Remotion${place === 'server' ? '（服务器）' : '（pc-video remotion render）'}按歌曲段落（前奏、主歌、副歌、间奏、尾奏）制作紧贴歌词意象与情绪的多场景动画（角色表情动作、天气光影、道具演变与镜头视差），切镜卡在鼓点上，副歌最满最炸`,
		place === 'server'
			? `- 动效半屏（${motionPos}）：在服务器用 Remotion 制作随节拍跳动的潮流歌词动效、音频律动图形与几何装饰（风格基调：${theme.label}），与卡通动画半屏在配色和节拍上严格呼应`
			: `- 动效半屏（${motionPos}，家里电脑 JIZURA）：调用家里电脑 pc-video jizura（${jizuraCfg}，--aspect 按半屏比例匹配如 ${jizuraAspect}）渲染高质感歌词动效与视觉装饰层（保留 JIZURA 丰富动态版式与鼓点卡切），再与 Remotion 卡通半屏通过 Remotion 合成或 FFmpeg ${isTb ? 'vstack' : 'hstack'} 拼合成完整分屏 MV，中间加一条随节拍律动的精致分割线；家里电脑不在线时改用 Remotion 做同等动效半屏并说明`,
		`- 样片核验：先选副歌 15–20 秒同时出卡通半屏 + 动效半屏的合成样片与拼图，确认两半节奏同步、画风和谐、都不静止且歌词清晰，再出整首`
	];
};

/** Full-frame multi-style animated MV with integrated dynamic lyrics (and optional JIZURA accents). */
const fullAnimatedMvLines = (
	place: VideoPlace,
	theme: (typeof MV_THEMES)[number],
	jizuraStyle: JizuraStyleKey
) => {
	const jizuraCfg = jizuraSpecText(theme.key, jizuraStyle);
	return [
		`- 做法：全屏动画 MV（多风格动画 + 融字动效）—— 按技能 video-studio「全屏动画 MV」流程，用 Remotion${place === 'server' ? ' 在服务器' : '（pc-video remotion render）'}做：全屏贴近歌词意象的丰富动画场景 + 随节拍融入画面的动态歌词；无旁白、不另加生硬字幕条`,
		'- 动画画面：按歌曲段落（前奏、主歌、副歌、间奏、尾奏）分场景，画面直接演绎每段歌词的人物、物件、风景与情绪，全片统一画风；镜头推移、角色动作、粒子光影与图形随节拍持续变化，副歌最满，绝不只拿单图慢放',
		place === 'server'
			? `- 歌词与动效融合（基调：${theme.label}）：歌词在 Remotion 里做成贴合画面的动态排版，重点词随鼓点弹出或变色，不遮挡角色主角；前奏间奏尾奏用动画场景 + 歌名动效撑住`
			: `- 歌词与动效融合（基调：${theme.label}，可联动 PC JIZURA）：歌词做成贴合画面的动态排版，前奏/间奏/副歌爆发转场可借力家里电脑 pc-video jizura（${jizuraCfg}）做高能视觉转场或局部动效叠层，但全片绝不退化成纯文字 PV`,
		'- 样片核验：先选副歌渲 15–20 秒样片看拼图，确认动画与歌词都贴合旋律与拍点，再出整首'
	];
};

/** Lyrics recognition / alignment (skill video-studio「歌词识别与对齐」): the home PC's GPU by
 * default, back to the server's CPU by itself; the server when the brief chose it. */
const asrTool = (place: VideoPlace) =>
	place === 'server'
		? '识别与对齐在服务器 CPU 上跑，见技能「歌词识别与对齐」'
		: '识别与对齐用 pc-video asr，在家里电脑显卡上跑，不在线自动回服务器，见技能「歌词识别与对齐」';

/** MP3 做 MV: split-screen (half cartoon animation + half PC JIZURA motion) or full-frame multi-style animation. */
export const buildMvBrief = (opts: VideoBriefOptions): string => {
	const music = opts.music ?? null;
	const theme = MV_THEMES.find((t) => t.key === opts.mvTheme) ?? MV_THEMES[0];
	const mvVisual: MvVisual = opts.mvVisual ?? 'split-tb';
	const frame = VIDEO_FRAMES.find((f) => f.key === opts.frame) ?? VIDEO_FRAMES[0];
	const lyrics = (opts.lyrics ?? '').trim().slice(0, MV_LYRICS_MAX);
	const timed = /^\s*\[\d+:\d+(?:[.:]\d+)?\]/m.test(lyrics);
	const attachments = opts.attachments ?? [];
	const visualLabel =
		mvVisual === 'split-tb'
			? '上下分屏动画 MV（一半卡通动画 + 一半动效）'
			: mvVisual === 'split-lr'
				? '左右分屏动画 MV（一半卡通动画 + 一半动效）'
				: '全屏多风格动画 MV';
	const styleLines = videoStyleLines(
		{
			style: opts.style,
			customStyle: opts.customStyle,
			appearance: opts.appearance,
			topic: `${opts.styleTopic ?? opts.idea} ${music?.name ?? ''}`,
			attachments,
			kind: 'mv',
			douyin: frame.key === '9:16'
		},
		true
	);
	const lines = [
		'请制作一个视频（来自 HaloWebUI 视频工作台）。',
		'',
		'## 想要的视频',
		`把这首歌做成${visualLabel}（MP4）。${opts.idea.trim() ? `\n${opts.idea.trim()}` : ''}`,
		'',
		'## 要求',
		...(mvVisual === 'animated'
			? fullAnimatedMvLines(opts.place, theme, opts.jizuraStyle ?? 'auto')
			: splitMvLines(opts.place, mvVisual, theme, opts.jizuraStyle ?? 'auto', frame.key)),
		...styleLines,
		music
			? `- 歌曲：${plainName(music.name)}${music.seconds ? `（${clockLabel(music.seconds)}）` : ''}，随消息附上，原文件路径见消息末尾的附件原文件；成片和这首歌一样长，音乐从 0 秒开始，不换、不加别的配乐`
			: '- 歌曲：（还没选）',
		`- 画幅：${frame.label} ${frame.key}（${frame.size}）`,
		...(frame.key === '9:16'
			? ['- 抖音 9:16 安全区：卡通主角焦点与动态歌词避开顶部 12%、右侧 14% 互动按钮列与底部 22% 文案栏']
			: []),
		lyrics
			? `- 歌词：用户已提供（见下面「## 歌词」）${timed ? '，带时间轴，直接用' : `，没有时间轴：先与人声对齐成 LRC 再做，对不上的地方以人声为准（${asrTool(opts.place)}）`}`
			: `- 歌词：用户没给。先识别歌词并与人声对齐成 LRC（${asrTool(opts.place)}）；听不清、拿不准的词不要猜，列出来交给用户确认后再做整首`,
		placeLine(opts.place)
	];
	if (attachments.length) {
		lines.push(
			`- 参考附件：${attachmentCounts(attachments)}（${attachments.map((a) => plainName(a.name)).join('、')}），先看完；LRC/SRT 歌词文件优先于下面贴的歌词；图片当动画画风、角色或场景参考`
		);
	}
	if (lyrics) lines.push('', '## 歌词', lyrics);
	lines.push(...publishLines(opts.place), '', '## 怎么做', `先读技能 video-studio（${VIDEO_SKILL_PATH}）。`, deliveryLine(opts.place));
	const brief = lines.join('\n');
	return opts.maker ? `/${opts.maker} ${brief}` : brief;
};

export const buildVideoBrief = (opts: VideoBriefOptions): string => {
	if (opts.kind === 'mv') return buildMvBrief(opts);
	const recipe = VIDEO_RECIPES.find((r) => r.key === opts.recipe) ?? VIDEO_RECIPES[0];
	const attachments = opts.attachments ?? [];
	const music = opts.music ?? null;
	const fullLength = musicSetsLength(music, opts.musicFit);
	const musicClock = music?.seconds ? clockLabel(music.seconds) : '';
	const lines = [
		'请制作一个视频（来自 HaloWebUI 视频工作台）。',
		'',
		opts.prep?.stale ? '## 待更新的增强草稿（旧视觉与节奏须按当前设置调整）' : '## 想要的视频',
		opts.idea.trim(),
		...(opts.prepJob && /^[0-9a-f]{32}$/.test(opts.prepJob)
			? ['', prepMarkLine(opts.prepJob)]
			: []),
		...(opts.prep ? prepLines(opts.prep, opts.idea) : []),
		'',
		'## 要求',
		...requirementLines(opts, true),
		...videoStyleLines({ ...opts, topic: opts.styleTopic ?? opts.idea }, true),
		placeLine(opts.place)
	];
	if (attachments.length) {
		const counts = attachmentCounts(attachments);
		lines.push(
			`- 参考附件：${counts}（${attachments.map((a) => plainName(a.name)).join('、')}），随消息附上，原文件路径见消息末尾；先看完再动手，是素材还是风格参考以上面的描述为准`
		);
		if (opts.recipe !== 'footage' && attachments.some((a) => a.kind === 'video')) {
			lines.push(
				opts.style === 'auto' || opts.style === 'reference'
					? '- 附件里的视频：描述没说要剪进成片时，只当风格参考——抽帧看构图、配色、字体、节奏和转场，用自己做的动画重现这种风格，不要直接使用原片画面、水印或角色形象'
					: '- 附件里的视频：描述没说要剪进成片时，仅分析用户指定的内容、构图或动作，不覆盖所选视觉风格，不直接使用原片画面、水印或角色形象'
			);
		}
	}
	if (music) {
		const loops = !fullLength && music.seconds != null && music.seconds < opts.seconds;
		lines.push(
			'',
			'## 背景音乐（用户指定：先定音乐，再按音乐做视频）',
			`- 音乐文件：${plainName(music.name)}${musicClock ? `（${musicClock}）` : ''}，随消息附上，原文件路径见消息末尾的附件原文件；这是成片唯一的背景音乐，不要换、不要另加配乐或合成音`,
			fullLength
				? '- 长度：视频和这首音乐一样长（film.py 用 "music_fit": "full"），旁白要放得进音乐的长度'
				: `- 长度：视频约 ${lengthLabel(opts.seconds)}，音乐从开头截取、结尾淡出（film.py 用 "music_fit": "trim", "seconds": ${opts.seconds}）${loops ? '；音乐比视频短，会循环播放' : ''}`,
			`- 先听音乐再分镜：python3 ${VIDEO_FILM_SCRIPT} --music-info <音乐路径>，得到时长、节拍（beats）、每秒能量和高潮位置；转场卡在节拍上，最有冲击力的动画画面放在高潮，结尾落在音乐结尾`,
			'- 用 film.py 出片（"music" 写这首音乐的路径；Remotion 画面用 --picture 交给它混音）：音乐从 0 秒开始，有配音时自动压低',
			`- 交付前核验：python3 ${VIDEO_FILM_SCRIPT} --check-music <成片.mp4> <音乐路径>，必须输出 "music_found": true，否则修好再交付`
		);
		if (fullLength && music.seconds != null && music.seconds > LONG_VIDEO_SECONDS) {
			const kbps = Math.max(150, Math.floor(((DELIVERY_MAX_MB - 10) * 8 * 1024) / music.seconds) - 128);
			lines.push(
				`- 长视频（${musicClock}）：画面以少量关键画面的慢速运镜、循环动效为主，不必每个节拍都转场；画幅按所选比例用 720p（如 1280×720）`,
				`- 成片必须小于 ${DELIVERY_MAX_MB} MB（HaloWebUI 收片上限）：film.py 出片后若超出，用 ffmpeg 重新压一遍（libx264 -b:v ${kbps}k -maxrate ${kbps}k -bufsize ${kbps * 2}k，音频 aac 128k，+faststart），再做一次 --check-music`
			);
		}
	}
	lines.push(
		...douyinLines(opts, true),
		...publishLines(opts.place),
		'',
		'## 怎么做',
		`先读技能 video-studio（${VIDEO_SKILL_PATH}），按其中「${recipe.label}」的做法和流程制作；正式渲染前先出样片或分镜拼图自己检查一遍。`,
		deliveryLine(opts.place)
	);
	const brief = lines.join('\n');
	return opts.maker ? `/${opts.maker} ${brief}` : brief;
};

/** The brief within *max* characters (a handoff carries at most that much): the enhancement's
 * parts give way first — the user's original words, then the notes cut short, then all of it —
 * so the requirements and the delivery line always arrive whole. */
export const fitVideoBrief = (opts: VideoBriefOptions, max: number): string => {
	const prep = opts.prep;
	const minimal = prep?.stale ? { ...prep, original: '', notes: '', sources: [], run: null } : null;
	const tries: (VideoPrep | null | undefined)[] = prep
		? [
				prep,
				{ ...prep, original: '' },
				{ ...prep, original: '', notes: prep.notes.slice(0, 400) },
				{ ...prep, original: '', notes: '', sources: prep.sources.slice(0, 3) },
				minimal
			]
		: [prep];
	for (const attempt of tries) {
		const brief = buildVideoBrief({ ...opts, prep: attempt });
		if (brief.length <= max) return brief;
	}
	return buildVideoBrief({ ...opts, prep: minimal });
};

/** Re-enhance a draft without mistaking generated visual details for user requirements. */
export const videoPrepIdea = (idea: string, prep: VideoPrep | null | undefined): string => {
	if (!prep?.stale) return idea.trim();
	return `按当前设置更新下面的旧增强草稿，保留内容与用户文字修改；旧增强补充的视觉和节奏不覆盖新设置。用户原话中明确的视觉要求优先。\n\n用户原话：\n${prep.original}\n\n当前草稿（可能含用户修改）：\n${idea.trim()}`;
};
