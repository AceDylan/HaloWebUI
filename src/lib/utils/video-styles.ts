import { VIDEO_PRESENTATIONS } from './video-presentations';

// Original appearance-only presets remain selectable and keep their stored keys.
export const LEGACY_VIDEO_STYLES = [
	{
		key: 'product',
		label: '产品界面演示',
		sub: '界面特写 · 功能引导',
		colors: ['#f3f5fa', '#5e65d8', '#53b5c5'],
		hint: '浅灰与品牌色，大留白、简洁无衬线字，真实界面作为主体；局部缩放、光标引导、平滑推移转场，字幕不遮挡操作；缺少界面素材时明确用示意稿。'
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

export const VIDEO_STYLES = VIDEO_PRESENTATIONS;
export const ALL_VIDEO_STYLES = [...VIDEO_STYLES, ...LEGACY_VIDEO_STYLES] as const;
export type VideoStyleKey =
	| 'auto'
	| 'reference'
	| 'custom'
	| (typeof ALL_VIDEO_STYLES)[number]['key'];
export const VIDEO_STYLE_CUSTOM_MAX = 300;
export const VIDEO_APPEARANCE_MAX = 160;
export const normalizeVideoStyle = (value: unknown): VideoStyleKey =>
	value === 'reference' || value === 'custom' || ALL_VIDEO_STYLES.some((s) => s.key === value)
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

export const videoStyleLines = (
	style: VideoStyleKey = 'auto',
	custom = '',
	recipe = '',
	appearance = ''
): string[] => {
	const preset = ALL_VIDEO_STYLES.find((s) => s.key === style);
	const direction = preset
		? `${preset.label}。${preset.hint}`
		: style === 'reference'
			? '跟随参考：制作前读取参考图片或视频，提取场景结构、主体动作、镜头、节奏及外观。合集须按用户指定的片段；未指定则选最贴合主题的一类并说明，不混合全部示例。'
			: style === 'custom'
				? `自定义。${cleanCustomStyle(custom) || '根据用户描述确定讲解形式。'}`
				: `自动选择：用户明确要求优先，有参考先分析参考；否则从${VIDEO_STYLES.map((s) => s.label).join('、')}中选适合主题的一类，写明选择及演示过程。`;
	const lines = [`- 视觉风格：${direction}`];
	if (preset && 'scenes' in preset && recipe !== 'footage') {
		lines.push(
			`- 分镜结构：${preset.scenes}`,
			`- 主体动作：${preset.motion}`,
			`- 镜头规则：${preset.camera}`,
			`- 节奏规则：${preset.rhythm}`,
			`- 验收重点：${preset.verify}`
		);
		if (recipe === 'story')
			lines.push(
				'- 图文成片只用关键画面与运镜表达上述结构，不宣称完成连续动作或三维拆解；需要完整动态演示时说明应选讲解动画。'
			);
		else
			lines.push(
				'- 制作约束：把上述过程做成可见的状态变化，不能只做标题、图标入场或整页淡入；先验证关键动作样片再完整渲染。'
			);
	}
	if (cleanVideoAppearance(appearance))
		lines.push(
			`- 配色与字体偏好：${cleanVideoAppearance(appearance)}（只调整外观，不替换上述讲解结构与动作）`
		);
	lines.push(
		'- 风格优先级：用户明确的视觉要求优先；所选形式约束增强补充的分镜、动作与镜头。做法、画幅、时长、配音、字幕与配乐设置不因风格改变；关闭字幕时不生成旁白字幕或花字，用户明确要求的标题、图表标签可保留。',
		recipe === 'footage'
			? '- 素材剪辑保持原素材主体，只借用所选形式的叙事顺序、排版与转场，不要求重绘或重演素材。参考作品的水印和角色不直接复用。'
			: style !== 'auto' && style !== 'reference'
				? '- 参考处理：以所选风格为视觉基准；附件只提供用户指定的内容、构图或动作参考，不自动覆盖风格。参考作品的水印和角色不直接复用。'
				: '- 参考作品的水印和角色不直接复用。'
	);
	return lines;
};
