// 视频工作台的视觉风格：八种通用 MG 风格，取自 mg-styles-15（MIT，github.com/Vincentwei1021/mg-styles-15）
// 每种风格的「风格特征 + 关键技法」，改写成 Hermes 本机能做的路线（Remotion + SVG/CSS，已装的 Noto CJK 字体）。
// 样片是该仓库成片的无声轻量预览（scripts/video-presets/make_samples.sh）。
//
// 「自动选择」按需求原话里的题材词挑一种（pickVideoStyle），结果写进需求，增强和制作者看到的是同一种。

export const VIDEO_STYLES = [
	{
		key: 'flat',
		label: '扁平 MG',
		en: 'Flat Vector MG',
		sub: '纯色几何 · 弹性入场',
		fits: '产品介绍、企业宣传、通用解说',
		marks: '扁平 矢量 MG',
		words: '产品 介绍 宣传 企业 公司 品牌 服务 功能 教程 指南 步骤 方法 营销 推广 招聘 年报 团队',
		look: '纯色大色块撞色、几何化角色与场景、无渐变无描边、干净留白',
		palette: '群青 #2B2BFF、珊瑚 #FF5A4E、向日葵 #FFC62B、薄荷 #2EE6A8、奶油 #FFF6E9、墨 #151433；粗黑体标题',
		motion: '入场「预备-冲出-回弹」，过冲用 cubic-bezier(0.34,1.56,0.64,1)；元素错峰 2–4 帧，同一时刻只让一个主体动；位移带约 10% 挤压拉伸；转场用色块擦除或元素飞出带走整场',
		route: 'Remotion + SVG 形状，spring 与 Easing.bezier；角色四肢按关节锚点旋转',
		still: '扁平矢量插画，纯色大色块，几何化角色，无渐变无描边，高饱和撞色',
		check: '没有渐变和描边；每次入场都有回弹；转场由元素带动'
	},
	{
		key: 'sticker',
		label: '贴纸科普',
		en: 'Sticker Explainer（回形针式）',
		sub: '白描边贴纸 · 大画布运镜',
		fits: '硬核科普、财经、历史与数据讲解',
		marks: '回形针 贴纸 硬核',
		words: '科普 知识 原理 为什么 揭秘 解读 历史 财经 经济 金融 数据 统计 图表 排名 对比 比较 地图 时间线 年代 百科 元素 多少 算法',
		look: '照片或物件抠图加 8–12px 粗白描边成「贴纸」，蓝灰米白冷静底，扁平图标配精确图表，信息密度高',
		palette: '底 #E9EEF2、石板灰 #3A4654、单一强调色 #FF5A36；等线黑体，严格对齐',
		motion: '一张超大画布一镜到底，镜头平移缩放（长尾缓动）串起信息点；每句解说带一个新视觉元素；柱子生长、数字滚动计数、路线描边生长',
		route: 'Remotion 大画布容器整体 transform 当镜头；SVG 图表按数据计算；贴纸用附件图片或 image_generate，加白描边与软投影',
		still: '白描边贴纸拼贴，冷静蓝灰底，扁平图标与精确图表，杂志式排版',
		check: '图表按比例、数字前后一致；镜头连续不硬切；每个节拍都有新元素'
	},
	{
		key: 'isometric',
		label: '等轴 2.5D',
		en: 'Isometric 2.5D',
		sub: '微缩场景 · 生长搭建',
		fits: '流程、系统架构、城市与物流',
		marks: '等距 等轴 2.5D 微缩',
		words: '流程 架构 系统 运作 工作原理 物流 快递 工厂 生产 城市 网络 数据中心 机房 服务器 供应链 部署 管道 微服务 云计算 园区',
		look: '真等轴投影（无透视灭点、处处等比）的微缩场景，柔和阴影与环境光遮蔽，精致模型质感',
		palette: '薰衣草底 #E9E4FF、薄荷 #9EE6C9、蜜桃 #FFC9A8、天蓝 #9CCBFF、白；标题贴在等轴平面上',
		motion: '地砖由中心波浪落下带小回弹；楼体先落底面，立面 scaleY 从 0 拉起带过冲，顶面晚 2–3 帧盖上；车流和数据流沿网格循环；镜头只整组平移不旋转，前中后景 1 : 0.8 : 0.6 视差',
		route: 'Remotion + SVG：三个面按纵向缩放 86.6% → 斜切 30° → 旋转 ±30° 拼合，按画面 y 排层级，移动保持 2:1 斜率',
		still: '等轴测微缩场景，正交视角无透视，粉彩配色，柔和阴影，白色模型质感',
		check: '全片同一投影角度；物体沿网格移动；没有透视变形'
	},
	{
		key: 'line',
		label: '一笔线条',
		en: 'Line Art',
		sub: '连续描绘 · 线转面',
		fits: '品牌、建筑、人文与高级感短片',
		marks: '线条 一笔 线描 极简',
		words: '建筑 艺术 设计 奢侈 高端 高级 诗 人文 文化 哲学 优雅 标志 logo 品牌故事 珠宝 香水 地产 纪念',
		look: '单色细线是唯一造型语言，大量负空间；上一图形的尾线就是下一图形的起线，结尾线转面',
		palette: '午夜底 #0B1320 + 香槟金线 #E9D7A5（或暖白底配墨线）；宽字距细宋体或细黑体',
		motion: '线宽全片恒定 2–4px、圆头；转角处描绘减速 cubic-bezier(0.65,0,0.35,1)；发光笔尖领跑、镜头跟随笔尖，旧线段淡到约 35%；结尾拉远成海报构图，标志从锚点填充',
		route: 'Remotion + SVG path，按路径总长驱动 strokeDashoffset；路径预先连成一笔',
		still: '单线插画，深色底金色细线，大量留白，极简奢华',
		check: '一笔连续不断；线宽恒定；有一次线转面'
	},
	{
		key: 'handdrawn',
		label: '手绘逐帧',
		en: 'Cel Animation & Line Boil',
		sub: '线条沸腾 · 纸纹手作',
		fits: '故事、寓言典故、童趣与温暖题材',
		marks: '手绘 手作 逐帧 涂鸦 蜡笔',
		words: '故事 童话 寓言 典故 成语 传说 神话 儿童 孩子 小朋友 绘本 温暖 治愈 可爱 亲子 动物',
		look: '墨线持续轻微抖动（line boil），一拍二节奏，快动作有拖影帧，手绘烟雾火花与速度线点缀，纸纹底，填色略出边',
		palette: '墨黑、番茄红、向日葵黄、奶油纸 3–4 色，纸纹正片叠底 10–15%；标题用 Noto Serif CJK Black 代替手写字',
		motion: '24fps 一拍二为主，快动作一拍一、停顿一拍三；每 2 帧换一版微差线稿（3–4 版循环）；拖影帧把物体拉长 150–300% 只留 1 帧；角色动作有预备和挤压',
		route: 'Remotion + SVG/Canvas：同一线稿用固定种子噪声生成 3–4 版微抖变体按帧切换，叠纸纹层',
		still: '手绘墨线卡通，纸张纹理，蜡笔填色略出边，暖色童趣',
		check: '静止时线条也在呼吸；动作是逐帧感而非平滑补间'
	},
	{
		key: 'glass',
		label: '弥散玻璃',
		en: 'Aurora & Glassmorphism',
		sub: '极光渐变 · 磨砂卡片',
		fits: 'AI 与 App 产品、发布会、科技品牌',
		marks: '玻璃 毛玻璃 极光 弥散',
		words: 'AI 人工智能 大模型 LLM GPT App 应用 软件 发布会 新品 手机 智能 助手 Agent 未来 互联网',
		look: '深靛黑底上 4–5 团极光色斑缓慢漂移混成网格渐变，磨砂玻璃卡片浮在上面，1px 高光描边，慢、透、高级',
		palette: '只用邻近色：紫 #7B5CFF、蓝 #3D7BFF、青 #3FE0E8、品红 #E05CFF，底 #0B0A1F；细黑体，叠 3–5% 噪点防色带',
		motion: '色斑沿贝塞尔路径漂移（模糊 80–150px）；卡片毛玻璃模糊 20–40px、白色 5–10% 填充、大圆角，带视差与轻微 3D 倾斜浮入；文字只用透明度加 8px 上移；全程 sine 呼吸缓动，没有快动作',
		route: 'Remotion + CSS（filter blur、backdrop-filter、混合模式），高光与噪点用 SVG 滤镜',
		still: '极光弥散渐变背景，磨砂玻璃界面卡片，柔光高光描边，深色高级科技感',
		check: '没有色带和撞色；节奏慢而连续'
	},
	{
		key: 'hud',
		label: '科幻 HUD',
		en: 'Cyberpunk HUD / FUI',
		sub: '线框扫描 · 目标锁定',
		fits: '科技数码、网络安全、航天军事与游戏',
		marks: 'HUD 赛博 科幻 霓虹',
		words: '黑客 安全 攻击 漏洞 游戏 电竞 航天 火箭 卫星 太空 军事 雷达 无人机 芯片 监控 数码 测评 汽车 自动驾驶 机器人',
		look: '深青黑底、青色霓虹线框、环形仪表与刻度、雷达扫描、等宽小字数据流、六边形网格，关键时刻切到橙红警示',
		palette: '底 #04141A、青 #00E5FF、警示橙 #FF6A00；等宽数字配细黑体，全局辉光、轻微色差与扫描线',
		motion: '线框按层级错帧描出；数字先乱跳 3–5 帧再落定真实值；打字机文字带光标；锁定框四角从 1.4 倍收缩到 1.0（快出缓入）；锁定瞬间整屏转警示橙',
		route: 'Remotion + SVG（strokeDashoffset 描线、锥形渐变扫描扇区），随机数据用固定种子',
		still: '科幻电影界面 HUD，青色霓虹线框，雷达与环形仪表，深色背景，目标锁定框',
		check: '数据由固定种子生成；信息分层不堆砌；锁定瞬间清楚'
	},
	{
		key: 'hanazi',
		label: '综艺花字',
		en: 'Variety Show Captions',
		sub: '描边花字 · 弹跳入场',
		fits: 'vlog、萌宠、生活与搞笑短视频',
		marks: '花字 综艺',
		words: 'vlog 日常 萌宠 宠物 猫 狗 搞笑 吐槽 生活 美食 探店 旅行 开箱 段子 记录 聚会 朋友',
		look: '多层描边胖体花字（填充色 + 粗白描边 + 彩色外描边 + 投影），高饱和撞色，爆炸框、汗滴、闪光等手绘符号随情绪变化',
		palette: '粉 #FF5FA2、黄 #FFD23F、青 #3DD6F5 配白描边；Noto Sans CJK Black 叠多层描边代替圆体',
		motion: '入场 scale 0 → 1.15 → 1.0 约 8 帧，逐字弹跳错 2 帧并带轻微旋转；驻留时轻微摆动；比画面笑点晚 2–3 帧出现；惊讶用放射线爆炸框，尴尬用汗滴',
		route: 'Remotion DOM/SVG 花字组件（多层描边 paint-order），画面用素材或图片加缓慢推拉、轻微手持晃动与推近',
		still: '综艺花字风格画面，高饱和粉黄青配色，白色粗描边文字贴纸，爆炸框与闪光装饰',
		check: '花字三层结构完整；每次出现都对准一个画面瞬间；中文自然无错字',
		vertical: true
	}
] as const;

export type VideoStyle = (typeof VIDEO_STYLES)[number];
export type VideoPresetKey = VideoStyle['key'];
export type VideoStyleKey = 'auto' | 'reference' | 'custom' | VideoPresetKey;
export const VIDEO_STYLE_CUSTOM_MAX = 300;
export const VIDEO_APPEARANCE_MAX = 160;

export const videoSamplePath = (key: VideoPresetKey, extension: 'mp4' | 'jpg') =>
	`/video-presets/v2/${key}.${extension}`;

/** Unknown keys (the earlier 讲解形式 and appearance presets among them) fall back to 自动选择. */
export const normalizeVideoStyle = (value: unknown): VideoStyleKey =>
	value === 'reference' || value === 'custom' || VIDEO_STYLES.some((s) => s.key === value)
		? (value as VideoStyleKey)
		: 'auto';
const cleanLine = (value: unknown, max: number): string =>
	typeof value === 'string'
		? value
				.replace(/[\u0000-\u001f\u007f]+/g, ' ')
				.replace(/MEDIA:/gi, 'MEDIA：')
				.trim()
				.slice(0, max)
		: '';
export const cleanCustomStyle = (value: unknown) => cleanLine(value, VIDEO_STYLE_CUSTOM_MAX);
export const cleanVideoAppearance = (value: unknown) => cleanLine(value, VIDEO_APPEARANCE_MAX);

/** Latin words match whole (「AI」 is not in 「detail」); Chinese ones anywhere in the text. */
const mentions = (text: string, word: string) =>
	/[a-z0-9]/i.test(word)
		? new RegExp(`(?<![a-z0-9])${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![a-z0-9])`, 'i').test(
				text
			)
		: text.includes(word);

export type VideoStylePick = {
	key: VideoPresetKey | 'reference';
	/** the words in the request that decided it (at most three), none for the fallback */
	words: string[];
};

/** 自动选择: the style the request points at. A style's own name counts three times a topic word;
 * 数据动画 leans to 贴纸科普 and 素材剪辑 to 综艺花字; ties go to the earlier style, nothing at all
 * to 扁平 MG. A reference video (not the footage being edited) is followed instead. */
export const pickVideoStyle = (
	topic: string,
	opts: { recipe?: string; attachments?: { kind: string }[] } = {}
): VideoStylePick => {
	if (opts.recipe !== 'footage' && (opts.attachments ?? []).some((a) => a.kind === 'video'))
		return { key: 'reference', words: [] };
	let best: VideoStylePick = { key: 'flat', words: [] };
	let bestScore = 0;
	for (const style of VIDEO_STYLES) {
		const marks = style.marks.split(' ').filter((w) => mentions(topic, w));
		const words = style.words.split(' ').filter((w) => mentions(topic, w));
		const score =
			marks.length * 3 +
			words.length +
			(opts.recipe === 'data' && style.key === 'sticker' ? 2 : 0) +
			(opts.recipe === 'footage' && style.key === 'hanazi' ? 1 : 0);
		if (score > bestScore) {
			bestScore = score;
			best = { key: style.key, words: [...marks, ...words].slice(0, 3) };
		}
	}
	return best;
};

const REFERENCE_DIRECTION =
	'跟随参考：制作前读取参考图片或视频，提取场景结构、主体动作、镜头、节奏及外观。合集须按用户指定的片段；未指定则选最贴合主题的一类并说明，不混合全部示例。';

export type VideoStyleOptions = {
	style: VideoStyleKey;
	customStyle?: string;
	recipe?: string;
	appearance?: string;
	/** the request the auto choice reads (the user's own words, before any enhancement) */
	topic?: string;
	attachments?: { kind: string }[];
};

/** The brief's style lines. *forMaker* adds what only the maker needs (the technical route and
 * the craft standard); 提示词增强 gets the rest, within its 1500-character settings budget. */
export const videoStyleLines = (opts: VideoStyleOptions, forMaker = false): string[] => {
	const recipe = opts.recipe ?? '';
	const pick =
		opts.style === 'auto'
			? pickVideoStyle(opts.topic ?? '', { recipe, attachments: opts.attachments })
			: null;
	const key = pick ? pick.key : opts.style;
	const preset = VIDEO_STYLES.find((s) => s.key === key);
	const why = pick
		? pick.key === 'reference'
			? '自动选择 → 附件里有参考视频，'
			: `自动选择 → ${pick.words.length ? `需求提到「${pick.words.join('」「')}」，选` : '需求没有明显的题材线索，选最通用的'}`
		: '';
	const lines: string[] = [];
	if (preset) {
		lines.push(
			`- 视觉风格：${why}${preset.label}（${preset.en}，适合${preset.fits}）`,
			`- 风格特征：${preset.look}`,
			`- 配色字体：${preset.palette}`
		);
		if (recipe === 'footage')
			lines.push(
				'- 素材剪辑保持原素材主体，只把该风格用于标题、字幕、贴纸、包装与转场，不要求重绘或重演素材。'
			);
		else if (recipe === 'story')
			lines.push(
				`- 图文成片：每张画面都用同一句风格描述「${preset.still}」，用关键画面加运镜表现，不宣称完成连续动画。`
			);
		else {
			lines.push(`- 关键技法：${preset.motion}`);
			if (forMaker)
				lines.push(`- 实现路线：${preset.route}（确有更好的路线可以换，说明理由）`);
		}
		lines.push(`- 验收：${preset.check}`);
	} else
		lines.push(
			`- 视觉风格：${why}${
				key === 'reference'
					? REFERENCE_DIRECTION
					: `自定义。${cleanCustomStyle(opts.customStyle) || '根据用户描述确定风格。'}`
			}`
		);
	if (cleanVideoAppearance(opts.appearance))
		lines.push(
			`- 配色与字体偏好：${cleanVideoAppearance(opts.appearance)}（只调整外观，不替换上述风格的动作与技法）`
		);
	lines.push(
		'- 风格优先级：用户明确的视觉要求优先；所选风格约束增强补充的配色、动作与镜头。做法、画幅、时长、配音、字幕与配乐设置不因风格改变；关闭字幕时不烧录旁白字幕，风格本身的标题、花字和图表标签不算字幕。',
		recipe === 'footage'
			? '- 参考作品的水印和角色不直接复用。'
			: preset || key === 'custom'
				? '- 参考处理：以所选风格为视觉基准；附件只提供用户指定的内容、构图或动作参考，不自动覆盖风格。参考作品的水印和角色不直接复用。'
				: '- 参考作品的水印和角色不直接复用。'
	);
	if (forMaker && recipe !== 'footage')
		lines.push(
			'- 制作标准（mg-styles-15 的做法）：开头 0.5 秒内有钩子，约 60–75% 处安排一个高潮画面，结尾构图停留约 1 秒并保留微动；先渲 6–10 张关键帧静帧检查构图与字体再做动画；缓动有目的（机械感之外不用线性），转场由元素带动而不是淡入淡出；交付前对照风格特征逐条自评，最弱的一项先改。'
		);
	return lines;
};
