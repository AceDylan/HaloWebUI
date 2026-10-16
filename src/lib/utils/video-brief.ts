// The video studio (/workspace/videos): what you want, how it should be made and who makes it,
// written as one brief for Hermes or a runner. The making happens in a chat (Hermes' video-studio
// skill: Remotion, pictures + camera moves, narration, subtitles); the finished file comes back
// as `MEDIA:` and lands in the video library.

export type VideoRecipeKey = 'explainer' | 'story' | 'footage' | 'data' | 'free';
export type VideoFrameKey = '16:9' | '9:16' | '1:1';
/** '' is Hermes itself; the rest are runners, started by the command in front of the brief. */
export type VideoMaker = '' | 'codex' | 'reclaude' | 'cchclaude' | 'officlaude' | 'anyclaude' | 'agy';

export const VIDEO_RECIPES: { key: VideoRecipeKey; label: string; sub: string; hint: string }[] = [
	{
		key: 'explainer',
		label: '讲解动画',
		sub: '动态图形 · 配音字幕',
		hint: 'Remotion 写的动态图形：标题、示意图、要点逐个动起来，配音和字幕对齐'
	},
	{
		key: 'story',
		label: '图文成片',
		sub: '生成画面 · 运镜转场',
		hint: '先画出统一风格的关键画面（或用你的图片），再加推拉平移运镜、转场、配音和字幕'
	},
	{
		key: 'footage',
		label: '素材剪辑',
		sub: '剪你上传的视频',
		hint: '从你上传的视频里挑段落剪辑拼接，加字幕、配音或音乐'
	},
	{
		key: 'data',
		label: '数据动画',
		sub: '图表动起来',
		hint: '把数据做成会动的图表：数字滚动、柱子长高、曲线画出来，每张图一句结论'
	},
	{ key: 'free', label: '自由发挥', sub: '执行者自己判断', hint: '由执行者按内容选最合适的做法' }
];

export const VIDEO_FRAMES: { key: VideoFrameKey; label: string; size: string }[] = [
	{ key: '16:9', label: '横屏', size: '1920×1080' },
	{ key: '9:16', label: '竖屏', size: '1080×1920' },
	{ key: '1:1', label: '方形', size: '1080×1080' }
];

export const VIDEO_LENGTHS = [15, 30, 60, 90, 180];

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
	{ key: 'agy', label: 'agy', sub: 'Gemini · 快' }
];

export const VIDEO_SKILL_PATH = '/root/.hermes/skills/creative/video-studio/SKILL.md';

export type VideoBriefOptions = {
	idea: string;
	recipe: VideoRecipeKey;
	frame: VideoFrameKey;
	seconds: number;
	voice: string;
	subtitles: boolean;
	maker: VideoMaker;
	attachments?: { name: string; kind: 'image' | 'video' | 'audio' | 'file' }[];
};

export type VideoSettings = Omit<VideoBriefOptions, 'idea' | 'attachments'>;

export const DEFAULT_VIDEO_SETTINGS: VideoSettings = {
	recipe: 'explainer',
	frame: '16:9',
	seconds: 30,
	voice: 'zh-CN-YunxiNeural',
	subtitles: true,
	maker: ''
};

const pick = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T =>
	allowed.includes(value as T) ? (value as T) : fallback;

/** The choices remembered between visits (localStorage), whatever shape they were stored in. */
export const normalizeVideoSettings = (value: unknown): VideoSettings => {
	const raw = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
	const seconds = Number(raw.seconds);
	return {
		recipe: pick(raw.recipe, VIDEO_RECIPES.map((r) => r.key), DEFAULT_VIDEO_SETTINGS.recipe),
		frame: pick(raw.frame, VIDEO_FRAMES.map((f) => f.key), DEFAULT_VIDEO_SETTINGS.frame),
		seconds: Number.isFinite(seconds) && seconds >= 5 && seconds <= 600 ? Math.round(seconds) : DEFAULT_VIDEO_SETTINGS.seconds,
		voice: pick(raw.voice, VIDEO_VOICES.map((v) => v.key), DEFAULT_VIDEO_SETTINGS.voice),
		subtitles: typeof raw.subtitles === 'boolean' ? raw.subtitles : DEFAULT_VIDEO_SETTINGS.subtitles,
		maker: pick(raw.maker, VIDEO_MAKERS.map((m) => m.key), DEFAULT_VIDEO_SETTINGS.maker)
	};
};

const ATTACHMENT_KIND: Record<string, string> = { image: '图片', video: '视频', audio: '音频', file: '文件' };

export const attachmentKind = (type: string, name = ''): 'image' | 'video' | 'audio' | 'file' => {
	const t = (type || '').toLowerCase();
	if (t.startsWith('image/')) return 'image';
	if (t.startsWith('video/') || /\.(mp4|m4v|mov|webm|mkv)$/i.test(name)) return 'video';
	if (t.startsWith('audio/') || /\.(mp3|m4a|wav|ogg|opus|flac|aac)$/i.test(name)) return 'audio';
	return 'file';
};

const lengthLabel = (seconds: number) =>
	seconds >= 60 && seconds % 60 === 0 ? `${seconds / 60} 分钟` : `${seconds} 秒`;

/** The message the chat sends: the runner's command in front, then the brief. */
export const buildVideoBrief = (opts: VideoBriefOptions): string => {
	const recipe = VIDEO_RECIPES.find((r) => r.key === opts.recipe) ?? VIDEO_RECIPES[0];
	const frame = VIDEO_FRAMES.find((f) => f.key === opts.frame) ?? VIDEO_FRAMES[0];
	const voice = VIDEO_VOICES.find((v) => v.key === opts.voice);
	const attachments = opts.attachments ?? [];
	const lines = [
		'请制作一个视频（来自 HaloWebUI 视频工作台）。',
		'',
		'## 想要的视频',
		opts.idea.trim(),
		'',
		'## 要求',
		`- 做法：${recipe.label}（${recipe.hint}）`,
		`- 画幅：${frame.label} ${frame.key}（${frame.size}，30fps）`,
		`- 时长：约 ${lengthLabel(opts.seconds)}`,
		`- 配音：${voice && voice.key ? `中文配音，${voice.label}（edge-tts ${voice.key}）` : '不要配音'}`,
		`- 字幕：${opts.subtitles ? '烧录中文字幕' : '不要字幕'}`
	];
	if (attachments.length) {
		const counts = Object.entries(
			attachments.reduce<Record<string, number>>((acc, a) => ({ ...acc, [a.kind]: (acc[a.kind] ?? 0) + 1 }), {})
		)
			.map(([kind, n]) => `${n} 个${ATTACHMENT_KIND[kind] ?? '文件'}`)
			.join('、');
		lines.push(
			`- 参考附件：${counts}（${attachments.map((a) => a.name).join('、')}），随消息附上，原文件路径见消息末尾；先看完再动手，是素材还是风格参考以上面的描述为准`
		);
		if (opts.recipe !== 'footage' && attachments.some((a) => a.kind === 'video')) {
			// A video handed over as "做成这样" (a downloaded short with its watermark) must not
			// end up cut into the result; with 素材剪辑 the attached footage is the material.
			lines.push(
				'- 附件里的视频：描述没说要剪进成片时，只当风格参考——抽帧看构图、配色、字体、节奏和转场，用自己做的画面重现这种风格，不要直接使用原片画面、水印或角色形象'
			);
		}
	}
	lines.push(
		'',
		'## 怎么做',
		`先读技能 video-studio（${VIDEO_SKILL_PATH}），按其中「${recipe.label}」的做法和流程制作；正式渲染前先出样片或分镜拼图自己检查一遍。`,
		'完成后用一小段话说明做法、时长和分镜，最后单独一行写「MEDIA:」紧跟成片 mp4 的绝对路径来交付（这一行不要放进代码块）。'
	);
	const brief = lines.join('\n');
	return opts.maker ? `/${opts.maker} ${brief}` : brief;
};
