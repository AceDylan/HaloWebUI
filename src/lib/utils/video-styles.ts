// 视频工作台的视觉风格（全面动画优先：拒绝纯文字动效与简陋单图）：
// - 4 种动画剧情原创风格（日漫卡通、潮酷漫格、国潮插画、治愈绘本），专为贴近字幕/歌词的叙事动画与分屏 MV 设计；
// - 8 种通用动画/MG 风格，取自 mg-styles-15（MIT，github.com/Vincentwei1021/mg-styles-15）。
// 每种风格的「风格特征 + 关键技法」均对应 Remotion + SVG/分层插画（可联动家里电脑 JIZURA 动效）可落地路线。
//
// 「自动选择」按需求原话里的题材词挑一种（pickVideoStyle），结果写进需求，增强和制作者看到的是同一种。

export const VIDEO_STYLES = [
	{
		key: 'anime-cartoon',
		label: '日漫卡通',
		en: 'Anime Cel Cartoon',
		sub: '卡通角色 · 剧情演绎',
		fits: '剧情故事、情感日常、青春校园、人物解说与卡通 MV',
		marks: '日漫 卡通 动漫 二次元 赛璐璐 剧情',
		words: '日常 青春 校园 职场 成长 自律 内耗 认知 心理 朋友 人物 冒险 夏日 阳光 城市 梦想 恋爱 治愈',
		look: '明亮赛璐璐卡通动画风，清晰线条与层次光影，有具象卡通角色表情动作与前中后景完整场景，直接把字幕或歌词内容演出来',
		palette: '晴空蓝 #38BDF8、落日橙 #FB923C、奶油米 #FFF7ED、暖靛影 #1E293B、樱粉 #F472B6',
		motion: '角色眨眼、表情切换与肢体关节微动；云朵、风吹发丝、落樱与光斑持续流动；全景/中景/特写随台词或鼓点切镜并带多层视差',
		route: 'Remotion 分层动画 + SVG 卡通角色/场景组件（或 gpt-image 统一赛璐璐分镜角色与背景分层动效）；可联动家里电脑 JIZURA 做分屏或卡点转场',
		still: '日系赛璐璐卡通动画帧，干净清晰线条，生动卡通角色与完整立体场景，通透暖阳逆光，故事感强',
		check: '每幕都有贴合台词/歌词的具象卡通表演与持续环境动画，绝无纯文字黑屏或静态贴图',
		vertical: true,
		douyin: true,
		source: 'halo'
	},
	{
		key: 'comic-pop',
		label: '潮酷漫格',
		en: 'Pop Comic Motion',
		sub: '漫画分格 · 反差冲击',
		fits: '避坑对比、认知反转、热点拆解、吐槽盘点与强节奏 MV',
		marks: '漫格 美漫 波普 潮酷 漫画 反差 对比',
		words: '避坑 踩坑 智商税 别买 误区 正确 区别 差距 反转 拆解 盘点 TOP 测评 揭秘 吐槽 搞笑 搞钱 职场 效率 狠话',
		look: '高饱和波普漫画动画风，粗黑描边、半调网点与斜切/上下漫画分格，用夸张卡通角色与拟人道具演活正反反差，不靠纯大字撑场',
		palette: '深靛底 #111322、电光黄 #FFD60A、漫画红 #FF3B5C、薄荷青 #14B8A6、纯白高光 #FFFFFF',
		motion: '漫画分格斜切拉开、正反角色同框对比动作；速度线、冲击波、弹簧回弹与卡通道具随重拍切换，抽象观点用夸张小剧场演清楚',
		route: 'Remotion 漫画分格容器 + SVG 卡通小人/道具/网点与速度线动画；可联动家里电脑 JIZURA（caution/kinetic/magenta）做半屏动效或卡点转场',
		still: '高饱和波普美漫动画画面，粗黑轮廓与半调网点，斜切漫画分格，生动卡通角色与夸张道具对比',
		check: '用漫画分格与卡通角色演清反差，画面饱和有动感，不退化成纯黑底大字',
		vertical: true,
		douyin: true,
		source: 'halo'
	},
	{
		key: 'guochao',
		label: '国潮插画',
		en: 'Guochao Illustrated Anime',
		sub: '东方美学 · 浓彩插画',
		fits: '历史典故、国风故事、文化揭秘、热血励志与国风 MV',
		marks: '国潮 国风 东方 古风 水墨 敦煌 插画',
		words: '历史 典故 传说 古风 东方 文化 诗词 山海 江湖 朝代 真相 秘密 传奇 英雄 热血 传统 节日 城楼',
		look: '浓郁东方国潮插画动画风，朱砂红、石青与鎏金撞色配宣纸肌理，层叠山水、飞檐楼阁、灯火祥云与人物剪影层次丰富',
		palette: '黛墨底 #141824、朱砂红 #E63946、石青 #2A9D8F、鎏金 #E9C46A、宣纸白 #F6EFE2',
		motion: '云雾水墨与金箔光尘持续流动，折扇/窗格/红绸带动场景切换；远山近景多层视差推进；高潮处朱砂光影与人物道具同步发力',
		route: 'Remotion 分层视差 + 国潮插画（gpt-image 统一画风场景 + SVG 动态祥云、孔明灯与金尘）；可联动家里电脑 JIZURA（rouge/crimson/wa）做分屏或高潮叠层',
		still: '新国潮东方插画动画画面，朱砂红与石青鎏金撞色，层叠山水楼阁与流动祥云灯火，电影光影与细腻纸纹',
		check: '东方意象紧扣字幕或歌词，前中后景持续流动有电影层次，无廉价文字模板感',
		vertical: true,
		douyin: true,
		source: 'halo'
	},
	{
		key: 'storybook',
		label: '治愈绘本',
		en: 'Storybook Watercolor Anime',
		sub: '水彩绘本 · 暖光氛围',
		fits: '情感治愈、生活感悟、书单影评、晚安故事与抒情 MV',
		marks: '绘本 水彩 治愈 童话 温暖 晚霞 氛围',
		words: '孤独 深夜 独白 感悟 人生 遗憾 爱情 风景 晚霞 电影 温柔 慢生活 写给 释怀 走心 情绪 森林 大海 猫 咖啡 书单',
		look: '温暖水彩绘本动画风，细腻纸纹与柔和笔触，完整窗景、小镇、海边或小动物与人物日常场景，配柔和丁达尔暖光与景深',
		palette: '暖暮蓝 #263147、琥珀暖阳 #F4A261、奶油纸 #FAF3E3、鼠尾草绿 #6B9080、柔粉 #F2B5D4',
		motion: '镜头如翻开立体绘本般温柔推进；树影、窗帘、热气、水波、萤火与飘花持续呼吸；转场用暖光晕、翻页或前景剪影自然衔接',
		route: 'Remotion 立体绘本分层视差 + gpt-image 水彩绘本分镜 + SVG 光斑/微风/角色微动；抒情 MV 可搭家里电脑 JIZURA（ballad/paper/mint）分屏动效',
		still: '温暖水彩绘本动画插画，细腻水彩纸纹，柔美丁达尔暖光与丰富生活场景细节，可爱角色与梦幻氛围',
		check: '场景细腻温暖且贴合台词/歌词意境，自然元素持续微动，拒绝单调暗底纯文字金句',
		vertical: true,
		douyin: true,
		source: 'halo'
	},
	{
		key: 'flat',
		label: '扁平动画',
		en: 'Flat Vector MG',
		sub: '几何角色 · 弹性叙事',
		fits: '产品介绍、通用科普、生活指南与轻快动画短片',
		marks: '扁平 矢量 MG',
		words: '产品 介绍 宣传 企业 公司 品牌 服务 功能 教程 指南 步骤 方法 营销 推广 招聘 年报 团队',
		look: '纯色大色块撞色、几何化卡通角色与完整生活场景、无渐变无描边、画面干净明快',
		palette: '群青 #2B2BFF、珊瑚 #FF5A4E、向日葵 #FFC62B、薄荷 #2EE6A8、奶油 #FFF6E9、墨 #151433',
		motion: '入场「预备-冲出-回弹」，过冲用 cubic-bezier(0.34,1.56,0.64,1)；角色四肢按关节锚点动画；元素错峰 2–4 帧带挤压拉伸；转场由图形飞出带动',
		route: 'Remotion + SVG 角色与场景形状，spring 与 Easing.bezier；角色关节独立动画',
		still: '扁平矢量动画插画，纯色大色块，几何化卡通角色与完整场景，高饱和撞色',
		check: '没有渐变和描边；有角色/物件动画表演；每次入场都有回弹；转场由元素带动',
		source: 'mg-styles-15'
	},
	{
		key: 'sticker',
		label: '贴纸科普',
		en: 'Sticker Explainer（回形针式）',
		sub: '白描边贴纸 · 大画布运镜',
		fits: '硬核科普、财经原理、历史脉络与数据拆解',
		marks: '回形针 贴纸 硬核',
		words: '科普 知识 原理 为什么 解读 财经 经济 金融 数据 统计 图表 排名 比较 地图 时间线 年代 百科 元素 多少 算法',
		look: '物件与场景插画抠图加 8–12px 粗白描边成「贴纸」，蓝灰米白底上铺开视觉信息地图，道具图标与动态图表协同演活原理',
		palette: '底 #E9EEF2、石板灰 #3A4654、强调色 #FF5A36；严格对齐的图示排版',
		motion: '一张超大画布一镜到底，镜头平移缩放串起具象道具、流程演示与动态图表；柱子生长、路线描边、贴纸零件拼装演示原理',
		route: 'Remotion 大画布容器整体 transform 当镜头；SVG 图表与白描边贴纸插画协同动画',
		still: '白描边贴纸拼贴动画场景，冷静蓝灰底，丰富物件图标与精确图示，杂志式构图',
		check: '用贴纸道具与图表直观演清原理，镜头连续不硬切，每幕都有新动画元素',
		douyin: true,
		source: 'mg-styles-15'
	},
	{
		key: 'isometric',
		label: '等轴 2.5D',
		en: 'Isometric 2.5D',
		sub: '微缩世界 · 生长搭建',
		fits: '流程拆解、系统架构、城市物流与微缩场景动画',
		marks: '等距 等轴 2.5D 微缩',
		words: '流程 架构 系统 运作 工作原理 物流 快递 工厂 生产 城市 网络 数据中心 机房 服务器 供应链 部署 管道 微服务 云计算 园区',
		look: '真等轴投影（无透视灭点、处处等比）的微缩立体世界，柔和阴影与环境光遮蔽，小车、人物与建筑像精致沙盘模型般运转',
		palette: '薰衣草底 #E9E4FF、薄荷 #9EE6C9、蜜桃 #FFC9A8、天蓝 #9CCBFF、白',
		motion: '地砖由中心波浪落下带回弹；建筑立面从底面生长盖顶；车流、人物与数据流沿网格循环穿梭；镜头整组平移带前中后景视差',
		route: 'Remotion + SVG：等轴三面拼合按 y 排层级，微缩角色与车辆沿 2:1 网格循环运动',
		still: '等轴测微缩世界场景，正交视角无透视，粉彩配色，柔和阴影，精致立体模型质感',
		check: '全片同一投影角度；沙盘建筑与流动元素持续运转；无透视变形',
		source: 'mg-styles-15'
	},
	{
		key: 'line',
		label: '一笔线条',
		en: 'Line Art',
		sub: '连续描绘 · 线转面',
		fits: '品牌故事、建筑人文、诗意抒情与高级感动画',
		marks: '线条 一笔 线描 极简',
		words: '建筑 艺术 设计 奢侈 高端 高级 诗 人文 哲学 优雅 标志 logo 品牌故事 珠宝 香水 地产 纪念',
		look: '流畅细线在负空间中连续勾勒人物、建筑与意象轮廓，上一图形的尾线自然化成下一场景的起线，高潮处线转面点亮色彩',
		palette: '午夜底 #0B1320 + 香槟金线 #E9D7A5（或暖白底配墨线）',
		motion: '线宽恒定 2–4px 圆头；发光笔尖领跑绘制完整场景轮廓，镜头跟随笔尖流动，旧线段淡至约 35%；关键帧线转面成完整插画',
		route: 'Remotion + SVG path，按路径总长驱动 strokeDashoffset，图形连成连续叙事长卷',
		still: '单线插画动画场景，深色底香槟金细线勾勒建筑与人物，大量留白，极简高级',
		check: '一笔连续勾勒具象画面；线宽恒定；有线转面高潮画面',
		source: 'mg-styles-15'
	},
	{
		key: 'handdrawn',
		label: '手绘逐帧',
		en: 'Cel Animation & Line Boil',
		sub: '线条沸腾 · 纸纹手作',
		fits: '寓言故事、童趣动画、生活小剧场与温暖手作 MV',
		marks: '手绘 手作 逐帧 涂鸦 蜡笔',
		words: '故事 童话 寓言 成语 神话 儿童 孩子 小朋友 温暖 可爱 亲子 动物 宠物 涂鸦 脑洞 小剧场',
		look: '墨线持续轻微抖动（line boil），一拍二逐帧节奏，快动作带拖影帧，手绘烟雾火花与蜡笔质感填色略出边，纸纹底生动有趣',
		palette: '墨黑、番茄红、向日葵黄、奶油纸 3–4 色，纸纹正片叠底 10–15%',
		motion: '24fps 一拍二为主，每 2 帧切换微抖线稿变体；角色动作带预备、挤压拉伸与 1 帧拖影；手绘拟态烟雾、水花与表情符号同步互动',
		route: 'Remotion + SVG/Canvas：固定种子生成 3–4 版微抖线稿按帧循环，叠纸纹层与手绘角色动画',
		still: '手绘墨线卡通动画，纸张纹理，蜡笔填色略出边，生动角色与暖色童趣场景',
		check: '静止时线条也在呼吸；动作是逐帧卡通感而非生硬补间',
		douyin: true,
		source: 'mg-styles-15'
	},
	{
		key: 'glass',
		label: '弥散玻璃',
		en: 'Aurora & Glassmorphism',
		sub: '极光场景 · 立体玻璃',
		fits: 'AI 与 App 产品、科技演进、未来感短片与电子 MV',
		marks: '玻璃 毛玻璃 极光 弥散',
		words: 'AI 人工智能 大模型 LLM GPT App 应用 软件 发布会 新品 手机 智能 助手 Agent 未来 互联网',
		look: '深靛黑底上极光色斑流动，前景悬浮立体磨砂玻璃装置、图标模型与动态波形界面，1px 高光描边，拒绝空白文字卡片',
		palette: '邻近色：紫 #7B5CFF、蓝 #3D7BFF、青 #3FE0E8、品红 #E05CFF，底 #0B0A1F，叠 3–5% 噪点防色带',
		motion: '极光云团沿贝塞尔漂移；磨砂立体设备、动态图标与能量光环带视差与 3D 倾斜浮入；全程 sine 呼吸缓动，光效流畅高级',
		route: 'Remotion + CSS（blur、backdrop-filter）配 SVG 立体图标/装置/光流粒子动画',
		still: '极光弥散渐变背景，悬浮立体磨砂玻璃装置与科技图形，柔光高光描边，深色高级质感',
		check: '有立体科技图形与光效层次，无色带撞色，不是简陋透明文本框',
		source: 'mg-styles-15'
	},
	{
		key: 'hud',
		label: '科幻 HUD',
		en: 'Cyberpunk HUD / FUI',
		sub: '全息蓝图 · 战术推演',
		fits: '科技数码、网络安全、航天军事、机甲与赛博 MV',
		marks: 'HUD 赛博 科幻 霓虹',
		words: '黑客 安全 攻击 漏洞 游戏 电竞 航天 火箭 卫星 太空 军事 雷达 无人机 芯片 监控 数码 汽车 自动驾驶 机器人',
		look: '深青黑底上悬浮全息三维线框物体（飞船、芯片、城市地图、机甲等）配环形仪表、雷达扫描与锁定框，关键时刻切橙红警示',
		palette: '底 #04141A、青 #00E5FF、警示橙 #FF6A00；全息辉光、轻微色差与扫描线',
		motion: '全息主体线框旋转与分层拆解；雷达扇区扫描、路径光点追踪、锁定框 1.4→1.0 收缩触发整屏橙红警示，画面充满科幻动作细节',
		route: 'Remotion + SVG（strokeDashoffset 描线、全息线框图形、雷达扇区与数据追踪动画）',
		still: '科幻全息蓝图与 HUD 界面，青色霓虹三维线框主体，雷达仪表与目标锁定框，深色科技感',
		check: '画面有具体全息主体与动态推演，信息分层不堆砌，锁定瞬间清楚',
		source: 'mg-styles-15'
	},
	{
		key: 'hanazi',
		label: '轻漫综艺',
		en: 'Variety Comic Stickers',
		sub: '卡通贴纸 · 趣味演活',
		fits: 'vlog 素材剪辑、萌宠日常、探店旅行与搞笑短视频',
		marks: '花字 综艺 轻漫',
		words: 'vlog 萌宠 猫 狗 探店 旅行 开箱 段子 记录 聚会 美食',
		look: '高饱和轻漫卡通贴纸与趣味手绘道具（爆炸框、汗滴、闪电、小表情、动态箭头与卡通边框）叠加在生动画面或素材上，趣味互动感强',
		palette: '粉 #FF5FA2、黄 #FFD23F、青 #3DD6F5 配粗白描边与轻投影',
		motion: '卡通道具与情绪贴纸对准笑点 0→1.15→1.0 弹性蹦出并轻微摇摆；配合画面推近、速度变化与元素擦除转场，有字幕时不堆满屏大字',
		route: 'Remotion SVG 卡通贴纸与漫画特效叠层 + 画面推拉/推近与卡点转场',
		still: '高饱和轻漫综艺贴纸风格，粉黄青撞色，可爱漫画表情贴纸、爆炸框与闪光装饰',
		check: '卡通贴纸与特效精准呼应画面瞬间，不遮挡主角，有字幕时不滥用大字',
		vertical: true,
		source: 'mg-styles-15'
	}
] as const;

export type VideoStyle = (typeof VIDEO_STYLES)[number];
export type VideoPresetKey = VideoStyle['key'];
export type VideoStyleKey = 'auto' | 'reference' | 'custom' | VideoPresetKey;
export const VIDEO_STYLE_CUSTOM_MAX = 300;
export const VIDEO_APPEARANCE_MAX = 160;

export const videoSamplePath = (key: VideoPresetKey, extension: 'mp4' | 'jpg') =>
	`/video-presets/v2/${key}.${extension}`;

/** Unknown keys (retired text-only or earlier presets) fall back to 自动选择. */
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

/** 自动选择: the animation style the request points at. A style's own name counts three times a
 * topic word; 数据/动态图解 leans to 贴纸科普, 素材精剪 to 轻漫综艺, and fallback defaults to
 * 日漫卡通 (when Douyin/animation mode or MV is active) or 扁平动画. */
export const pickVideoStyle = (
	topic: string,
	opts: { recipe?: string; attachments?: { kind: string }[]; douyin?: boolean; kind?: string } = {}
): VideoStylePick => {
	if (opts.recipe !== 'footage' && (opts.attachments ?? []).some((a) => a.kind === 'video'))
		return { key: 'reference', words: [] };
	let best: VideoStylePick = {
		key: opts.douyin || opts.kind === 'mv' || opts.recipe === 'split-jizura' ? 'anime-cartoon' : 'flat',
		words: []
	};
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
	douyin?: boolean;
	subtitles?: boolean;
	kind?: string;
	/** the request the auto choice reads (the user's own words, before any enhancement) */
	topic?: string;
	attachments?: { kind: string }[];
};

/** The brief's style lines. *forMaker* adds what only the maker needs (the technical route and
 * the craft standard); 提示词增强 gets the rest, within its 1500-character settings budget. */
export const videoStyleLines = (opts: VideoStyleOptions, forMaker = false): string[] => {
	const recipe = opts.recipe ?? '';
	const isMv = opts.kind === 'mv';
	const pick =
		opts.style === 'auto'
			? pickVideoStyle(opts.topic ?? '', {
					recipe,
					attachments: opts.attachments,
					douyin: opts.douyin,
					kind: opts.kind
				})
			: null;
	const key = pick ? pick.key : opts.style;
	const preset = VIDEO_STYLES.find((s) => s.key === key);
	const why = pick
		? pick.key === 'reference'
			? '自动选择 → 附件里有参考视频，'
			: `自动选择 → ${pick.words.length ? `需求提到「${pick.words.join('」「')}」，选` : opts.douyin || isMv || recipe === 'split-jizura' ? '动画叙事默认推荐，选' : '需求没有明显的题材线索，选最通用的'}`
		: '';
	const lines: string[] = [];
	if (preset) {
		lines.push(
			`- 视觉风格：${why}${preset.label}（${preset.en}，适合${preset.fits}）`,
			`- 风格特征：${preset.look}`,
			`- 配色：${preset.palette}`
		);
		if (recipe === 'footage')
			lines.push(
				'- 素材精剪保持原素材主体，只把该风格用于卡通贴纸、动态转场、重点标注与包装，不重绘原素材；包装随节拍动。'
			);
		else if (recipe === 'story')
			lines.push(
				`- 绘本动画：每张分镜用同一风格描述「${preset.still}」；画面必须动起来：运镜之外叠贴合内容的光效、天气粒子、角色微动或前景视差，同构图不超 4 秒就换景别或特写。`
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
					: `自定义。${cleanCustomStyle(opts.customStyle) || '根据用户描述确定动画风格。'}`
			}`
		);
	if (cleanVideoAppearance(opts.appearance))
		lines.push(
			`- 配色与外观偏好：${cleanVideoAppearance(opts.appearance)}（只调外观，不替换动画技法）`
		);
	if (!isMv) {
		lines.push(
			opts.subtitles
				? '- 画面与字幕分工：严禁纯文字动效或简陋背景；已有底部烧录字幕，画面不必凸显文字动效，把画面留给贴合字幕内容的生动动画场景与角色动作。'
				: '- 画面原则：严禁纯文字动效或简陋背景，每幕用贴合内容的生动动画场景与角色动作讲故事；必要短标题融入画面不喧宾夺主。'
		);
	}
	lines.push(
		isMv
			? '- 风格优先级：用户明确视觉要求优先；所选画风约束动画场景与角色造型，不改变分屏布局、画幅与歌曲设置。'
			: '- 风格优先级：用户明确视觉要求优先；所选风格约束画风与动作，不改变做法、画幅、时长、配音、字幕与配乐设置。',
		recipe === 'footage'
			? '- 参考作品的水印和角色不直接复用。'
			: preset || key === 'custom'
				? '- 参考处理：以所选动画风格为准；附件仅作内容/构图参考，不覆盖风格，不复用水印与原角色。'
				: '- 参考作品的水印和角色不直接复用。'
	);
	if (forMaker && recipe !== 'footage')
		lines.push(
			'- 制作标准：开头 0.5 秒直接进入会动的动画画面，60–75% 处给最高能动画镜头，结尾停留约 1 秒并保留微动；先渲 6–10 张关键帧静帧检查画风与构图再出片；缓动有目的，转场由元素或镜头带动，交付前逐条自评。'
		);
	return lines;
};
