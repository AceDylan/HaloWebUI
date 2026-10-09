// The places the sidebar leads to besides the chat list — the chat's modes (精答 / 讨论 / 协作 /
// 生图) and the libraries (助手 / 提示词 / 定时) — with who may see them. The sidebar rows and the
// ⌘K command palette both list these, so a page added here shows up in both.

export type Destination = {
	key: string;
	href: string;
	label: string;
	title: string;
	/** The page is open when the path starts with one of these. */
	match: string[];
};

type UserLike = { role?: string; permissions?: any } | null | undefined;
type ConfigLike = { features?: Record<string, any> } | null | undefined;

export const modeDestinations = (config: ConfigLike, user: UserLike): Destination[] => {
	const admin = user?.role === 'admin';
	const studio =
		!!config?.features?.enable_image_generation &&
		(admin || !!user?.permissions?.features?.image_generation);
	return [
		{
			key: 'answer',
			href: '/answer',
			label: '精答',
			title: '精答：按问题挑选、升级或新建最合适的助手来回答',
			match: ['/answer'],
			show: true
		},
		{
			key: 'discuss',
			href: '/discuss',
			label: '讨论',
			title: '讨论台：几个模型讨论，主持人给结论',
			match: ['/discuss'],
			show: true
		},
		{
			key: 'teams',
			href: '/teams',
			label: '协作',
			title: '协作台：一支 AI 团队拆任务、并行完成',
			match: ['/teams'],
			show: !!config?.features?.enable_agent_teams
		},
		{
			key: 'studio',
			href: '/workspace/images?tab=workbench',
			label: '生图',
			title: '生图工作台：提示词、参考图、图库',
			match: ['/workspace/images'],
			show: studio
		}
	]
		.filter((d) => d.show)
		.map(({ show: _show, ...d }) => d);
};

export const libraryDestinations = (user: UserLike): Destination[] => {
	const admin = user?.role === 'admin';
	const perms = user?.permissions?.workspace ?? {};
	return [
		{
			key: 'assistants',
			href: admin || perms.models ? '/workspace/models' : '/workspace/assistants',
			label: '助手',
			title: '助手：我的助手和内置模板，精答、讨论台、协作台都从这里挑',
			match: ['/workspace/models', '/workspace/assistants'],
			show: admin || perms.models || perms.knowledge || perms.prompts || perms.tools
		},
		{
			key: 'prompts',
			href: '/workspace/prompts',
			label: '提示词',
			title: '提示词：输入框里用 / 调出的常用提示词',
			match: ['/workspace/prompts'],
			show: admin || perms.prompts
		},
		{
			key: 'schedules',
			href: '/workspace/schedules',
			label: '定时',
			title: '定时任务：Hermes 按时间自动去做的事',
			match: ['/workspace/schedules'],
			show: admin
		}
	]
		.filter((d) => !!d.show)
		.map(({ show: _show, ...d }) => d);
};

export const isAt = (destination: Destination, path: string) =>
	destination.match.some((prefix) => path.startsWith(prefix));
