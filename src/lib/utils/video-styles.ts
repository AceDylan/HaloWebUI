/** Visual direction only: recipes, duration and sound remain independent choices. */
export const VIDEO_STYLES = [
	{
		key: 'flat',
		label: '扁平 MG 动画',
		sub: '清晰图形 · 轻快讲解',
		colors: ['#f1f5ff', '#315bea', '#ffb84d'],
		hint: '浅底蓝橙配色，无衬线标题，扁平图形分层构图；图形逐步展开、平滑位移，以形状匹配转场，字幕清晰克制。'
	},
	{
		key: 'isometric',
		label: '等轴 2.5D',
		sub: '立体层次 · 系统关系',
		colors: ['#edf7f4', '#207968', '#e6b352'],
		hint: '青绿与米白配色，简洁无衬线字，等轴投影与统一光向；模块分层升起、路径流动、平移转场，用二维层次表现空间，不承诺完整三维仿真。'
	},
	{
		key: 'news',
		label: '数据新闻',
		sub: '图表叙事 · 结论突出',
		colors: ['#f5f2eb', '#222d45', '#de5938'],
		hint: '米白底、深蓝文字、橙红重点，网格排版与大数字；图表按叙事逐步绘制、切换时保留坐标参照，字幕简洁；标明来源，不编造数据。'
	},
	{
		key: 'product',
		label: '产品界面演示',
		sub: '界面特写 · 功能引导',
		colors: ['#f3f5fa', '#5e65d8', '#53b5c5'],
		hint: '浅灰与品牌色，大留白、简洁无衬线字，真实界面作为主体；局部缩放、光标引导、平滑推移转场，字幕不遮挡操作；缺少界面素材时明确用示意稿。'
	},
	{
		key: 'whiteboard',
		label: '白板手绘',
		sub: '线条推演 · 逐步理解',
		colors: ['#fffdf5', '#303c47', '#edaa47'],
		hint: '白底黑线与少量黄色重点，清晰手写感标题；线条逐笔显现、箭头串联思路、擦除转场，字幕用易读正文字体，不依赖真实手部素材。'
	},
	{
		key: 'type',
		label: '动态排版',
		sub: '文字节奏 · 关键词聚焦',
		colors: ['#191923', '#f4f1e8', '#d3ee62'],
		hint: '黑白高对比与荧光黄点缀，粗体标题和大留白；词组分批入场、字重与尺度变化、文字遮罩转场，保证阅读停留，避免整屏持续抖动。'
	},
	{
		key: 'bauhaus',
		label: '包豪斯几何',
		sub: '基础形状 · 大胆配色',
		colors: ['#f4e8cc', '#c84432', '#254a9b'],
		hint: '米色底、红黄蓝主色，几何无衬线字，圆形方形与非对称平衡；旋转拼合、几何遮罩转场，字幕保持稳定。'
	},
	{
		key: 'ink',
		label: '水墨山水',
		sub: '墨色留白 · 舒缓铺展',
		colors: ['#efece0', '#37443f', '#b44938'],
		hint: '宣纸白、墨灰与朱红，山水留白、标题书法感但须有可用字体；墨迹渐显、分层山峦缓慢平移、淡墨转场，正文易读，节奏服从用户时长与配乐。'
	},
	{
		key: 'paper',
		label: '纸叠剪纸',
		sub: '纸张层次 · 温暖故事',
		colors: ['#f5e6cd', '#c56848', '#5d8a78'],
		hint: '暖米色、砖红和草绿，圆润标题，纸片层叠与轻柔阴影；分层视差、折叠展开、纸片遮罩转场，统一角色造型，字幕放在留白区。'
	},
	{
		key: 'line',
		label: '一笔线条',
		sub: '连续描绘 · 简洁联想',
		colors: ['#faf8f0', '#242f3e', '#c67a52'],
		hint: '暖白底、深色细线与少量赭色，轻量无衬线字；连续路径描绘和线条延伸串联场景，留白构图，字幕独立于主线保持清楚。'
	},
	{
		key: 'film',
		label: '默片胶片',
		sub: '黑白颗粒 · 复古叙事',
		colors: ['#e4ddce', '#39352e', '#97866a'],
		hint: '黑白或棕褐色、适量颗粒和暗角，衬线标题、胶片构图；轻微帧抖动、叠化与光圈转场。默片仅指视觉风格，不关闭用户选定的声音；字卡服从字幕设置。'
	},
	{
		key: 'pixel',
		label: '像素游戏',
		sub: '像素场景 · 闯关趣味',
		colors: ['#222345', '#72dab3', '#e6b55d'],
		hint: '深蓝底、薄荷绿与金黄，像素图形和有限色板；按像素网格移动、逐格切换场景，中文使用清晰字体，保持像素边缘，不添加未授权游戏角色。'
	},
	{
		key: 'blueprint',
		label: '工程蓝图',
		sub: '结构拆解 · 技术标注',
		colors: ['#123659', '#b8dfed', '#e6af65'],
		hint: '蓝底、白青细线与橙色重点，等宽标注与网格；轮廓逐步绘制、部件分解和线框转场，标注可读，不虚构尺寸或工程数据。'
	},
	{
		key: 'hud',
		label: '科幻 HUD',
		sub: '科技界面 · 扫描构建',
		colors: ['#101c2d', '#68d9e7', '#dc9d54'],
		hint: '深蓝黑底、青色线条与少量橙色，无衬线标题，环形仪表与信息分区；扫描显现、局部追踪和线框转场，减少装饰噪声，虚构仪表须标示为示意。'
	},
	{
		key: 'synthwave',
		label: '复古合成波',
		sub: '霓虹网格 · 八十年代',
		colors: ['#27183e', '#ef71c7', '#67caed'],
		hint: '紫黑底、品红与青蓝霓虹，大标题与透视网格；慢推镜、光带擦拭转场、适量辉光，字幕保持高对比，不因风格自行添加或替换配乐。'
	},
	{
		key: 'ascii',
		label: 'ASCII 字符渲染',
		sub: '字符图像 · 终端美学',
		colors: ['#141c18', '#a6d9a3', '#d8e5d2'],
		hint: '近黑底、绿白字符，等宽字体与字符明暗网格；字符逐步构形、行扫描转场，控制刷新密度；中文说明独立排版，不把字幕变成不可读的字符纹理。'
	}
] as const;

export type VideoStyleKey = 'auto' | 'reference' | 'custom' | (typeof VIDEO_STYLES)[number]['key'];
export const VIDEO_STYLE_CUSTOM_MAX = 300;
export const normalizeVideoStyle = (value: unknown): VideoStyleKey =>
	value === 'reference' || value === 'custom' || VIDEO_STYLES.some((s) => s.key === value)
		? (value as VideoStyleKey)
		: 'auto';
export const cleanCustomStyle = (value: unknown): string =>
	typeof value === 'string'
		? value
				.replace(/[\u0000-\u001f\u007f]+/g, ' ')
				.replace(/MEDIA:/gi, 'MEDIA：')
				.trim()
				.slice(0, VIDEO_STYLE_CUSTOM_MAX)
		: '';

export const videoStyleLines = (style: VideoStyleKey = 'auto', custom = ''): string[] => {
	const preset = VIDEO_STYLES.find((s) => s.key === style);
	const direction = preset
		? `${preset.label}。${preset.hint}`
		: style === 'reference'
			? '跟随参考：制作前读取用户指定的参考图片或视频，提取配色、构图、字体与运动；有多个参考时按用户指定的主参考，未指定则选最贴合主题的一份并说明。'
			: style === 'custom'
				? `自定义。${cleanCustomStyle(custom) || '根据用户描述确定视觉方向。'}`
				: '自动选择：优先用户明确的视觉描述；有风格参考时沿用参考，否则按主题选择一套统一视觉。';
	return [
		`- 视觉风格：${direction}`,
		'- 风格优先级：用户明确的视觉要求优先；所选风格约束增强补充的视觉细节。做法、画幅、时长、配音、字幕与配乐设置不因风格改变；关闭字幕时不生成旁白字幕或花字，用户明确要求的标题、图表标签可保留。',
		...(style !== 'auto' && style !== 'reference'
			? [
					'- 参考处理：以所选风格为视觉基准；附件只提供用户指定的内容、构图或动作参考，不自动覆盖风格。'
				]
			: []),
		'- 素材剪辑保持原素材主体，风格用于排版、调色与转场，不默认重绘实拍。参考作品的水印和角色不直接复用。'
	];
};
