// The video studio (/workspace/videos): what you want, how it should be made and who makes it,
// written as one brief for Hermes or a runner. The making happens in a chat (Hermes' video-studio
// skill: Remotion, pictures + camera moves, narration, subtitles); the finished file comes back
// as `MEDIA:` and lands in the video library.
//
// 背景音乐: the user picks the MP3 first and the video is made to it — as long as the music (or
// cut to the chosen length), scene changes on its beats, and the skill's film.py proves the
// finished file plays that track (--check-music) before it is handed over.

import {
	cleanVideoAppearance,
	cleanCustomStyle,
	normalizeVideoStyle,
	videoStyleLines,
	type VideoStyleKey
} from './video-styles';

export type VideoRecipeKey = 'explainer' | 'story' | 'footage' | 'data' | 'free';
export type VideoFrameKey = '16:9' | '9:16' | '1:1';
/** '' is Hermes itself; the rest are runners, started by the command in front of the brief. */
export type VideoMaker =
	| ''
	| 'codex'
	| 'reclaude'
	| 'cchclaude'
	| 'officlaude'
	| 'anyclaude'
	| 'agy';
/** With background music: the video as long as the music, or the music cut to the chosen length. */
export type VideoMusicFit = 'full' | 'trim';

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
export const VIDEO_FILM_SCRIPT = '/root/.hermes/skills/creative/video-studio/scripts/film.py';

/** The longest video and so the longest music it can follow (the length settings' own limit). */
export const MUSIC_MAX_SECONDS = 600;
export const MUSIC_MAX_BYTES = 50 * 1024 * 1024;
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
	maker: VideoMaker;
	musicFit: VideoMusicFit;
	attachments?: { name: string; kind: 'image' | 'video' | 'audio' | 'file' }[];
	music?: VideoMusic | null;
	prep?: VideoPrep | null;
	/** 提示词增强 still going on the server: the chat's Hermes turn waits for it and puts its result
	 * in place of this line (backend utils/studio_prep.py PREP_MARK). */
	prepJob?: string | null;
};

export type VideoSettings = Omit<
	VideoBriefOptions,
	'idea' | 'attachments' | 'music' | 'prep' | 'prepJob'
>;

/** The brief's line for an enhancement still going (backend utils/studio_prep.py PREP_MARK). */
export const prepMarkLine = (id: string) => `（制作前准备：HaloWebUI 正在增强需求，编号 ${id}）`;

export const DEFAULT_VIDEO_SETTINGS: VideoSettings = {
	style: 'auto',
	customStyle: '',
	appearance: '',
	recipe: 'explainer',
	frame: '16:9',
	seconds: 30,
	voice: 'zh-CN-YunxiNeural',
	subtitles: true,
	maker: '',
	musicFit: 'full'
};

const pick = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T =>
	allowed.includes(value as T) ? (value as T) : fallback;

/** The choices remembered between visits (localStorage), whatever shape they were stored in. */
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
		maker: pick(
			raw.maker,
			VIDEO_MAKERS.map((m) => m.key),
			DEFAULT_VIDEO_SETTINGS.maker
		),
		musicFit: pick(raw.musicFit, ['full', 'trim'] as const, DEFAULT_VIDEO_SETTINGS.musicFit)
	};
};

/** Why *file* cannot be the background music ('' when it can): an MP3 by name and type, not
 * empty, not over 50 MB. Its first bytes (*head*, when read) must look like MP3 too. */
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

/** The decided settings as the brief words them (做法, 画幅, 时长, 配音, 字幕), one per line. */
const requirementLines = (opts: Omit<VideoBriefOptions, 'idea'>) => {
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
		`- 字幕：${opts.subtitles ? '烧录中文字幕' : '不要字幕'}`
	];
};

/** The settings for 提示词增强 to size the content to (it never changes them). */
export const videoSettingsText = (opts: Omit<VideoBriefOptions, 'idea'>): string => {
	const lines = requirementLines(opts);
	lines.push(...videoStyleLines(opts.style, opts.customStyle, opts.recipe, opts.appearance));
	const attachments = opts.attachments ?? [];
	if (opts.music)
		lines.push(`- 背景音乐：用户指定（${plainName(opts.music.name)}），视频按音乐的节拍和长度做`);
	// The server accepts 1500 characters. Bound names after the essential constraints.
	if (attachments.length)
		lines.push(
			`- 参考附件：${attachmentCounts(attachments)}（${attachments.map((a) => plainName(a.name).slice(0, 24)).join('、')}）`
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

/** The message the chat sends: the runner's command in front, then the brief. */
export const buildVideoBrief = (opts: VideoBriefOptions): string => {
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
		...requirementLines(opts),
		...videoStyleLines(opts.style, opts.customStyle, opts.recipe, opts.appearance)
	];
	if (attachments.length) {
		const counts = attachmentCounts(attachments);
		lines.push(
			`- 参考附件：${counts}（${attachments.map((a) => plainName(a.name)).join('、')}），随消息附上，原文件路径见消息末尾；先看完再动手，是素材还是风格参考以上面的描述为准`
		);
		if (opts.recipe !== 'footage' && attachments.some((a) => a.kind === 'video')) {
			// A video handed over as "做成这样" (a downloaded short with its watermark) must not
			// end up cut into the result; with 素材剪辑 the attached footage is the material.
			lines.push(
				opts.style === 'auto' || opts.style === 'reference'
					? '- 附件里的视频：描述没说要剪进成片时，只当风格参考——抽帧看构图、配色、字体、节奏和转场，用自己做的画面重现这种风格，不要直接使用原片画面、水印或角色形象'
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
			`- 先听音乐再分镜：python3 ${VIDEO_FILM_SCRIPT} --music-info <音乐路径>，得到时长、节拍（beats）、每秒能量和高潮位置；转场卡在节拍上，最有冲击力的画面放在高潮，结尾落在音乐结尾`,
			'- 用 film.py 出片（"music" 写这首音乐的路径；Remotion 画面用 --picture 交给它混音）：音乐从 0 秒开始，有配音时自动压低',
			`- 交付前核验：python3 ${VIDEO_FILM_SCRIPT} --check-music <成片.mp4> <音乐路径>，必须输出 "music_found": true，否则修好再交付`
		);
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
	// Do not silently truncate the user's words: the workbench reports an overlong brief.
	return buildVideoBrief({ ...opts, prep: minimal });
};

/** Re-enhance a draft without mistaking generated visual details for user requirements. */
export const videoPrepIdea = (idea: string, prep: VideoPrep | null | undefined): string => {
	if (!prep?.stale) return idea.trim();
	return `按当前设置更新下面的旧增强草稿，保留内容与用户文字修改；旧增强补充的视觉和节奏不覆盖新设置。用户原话中明确的视觉要求优先。\n\n用户原话：\n${prep.original}\n\n当前草稿（可能含用户修改）：\n${idea.trim()}`;
};
