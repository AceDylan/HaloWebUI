// Labels and pure helpers for the 「Hermes 模型」 settings page (HermesRouting.svelte).
// Hermes validates and writes the routing itself (hermes_cli/routing_admin.py); this only
// shapes what the page shows and what it sends.
import type {
	HermesAgyPrefs,
	HermesRouting,
	HermesRoutingChange,
	HermesWorkConfigResponse,
	WorkPresetKey,
	WorkProfileConfig,
	WorkRunnerOption,
	WorkStepConfig,
	WorkStepKey,
	WorkWorkflowConfig
} from '$lib/apis/hermes';

export const ROUTING_MAX_FALLBACKS = 3;
export const ROUTING_MAX_AUX_FALLBACKS = 2;
export const MEDIA_TIMEOUT_MIN = 30;
export const MEDIA_TIMEOUT_MAX = 600;

export const isValidMediaTimeout = (value: unknown): boolean =>
	typeof value === 'number' &&
	Number.isInteger(value) &&
	value >= MEDIA_TIMEOUT_MIN &&
	value <= MEDIA_TIMEOUT_MAX;

/** Auxiliary tasks hermes runs on a side model: what each one is for, in plain words. */
export const AUX_TASKS: Record<string, { label: string; hint: string }> = {
	compression: { label: '上下文压缩', hint: '对话太长时把旧消息总结掉' },
	title_generation: { label: '会话标题', hint: '给新对话起标题' },
	web_extract: { label: '网页提取', hint: '抓网页后提炼要点' },
	vision: { label: '辅助看图', hint: '主模型不能看图时替它看' },
	approval: { label: '命令审批', hint: '判断危险命令能不能执行' },
	skills_hub: { label: '技能检索', hint: '挑选、安装技能' },
	mcp: { label: 'MCP 工具', hint: 'MCP 工具调用的辅助判断' },
	memory_query_rewrite: { label: '记忆检索', hint: '改写查询去翻记忆' },
	triage_specifier: { label: '任务分诊', hint: '把看板任务写清楚' },
	kanban_decomposer: { label: '任务拆解', hint: '把大任务拆成子任务' },
	goal_judge: { label: '目标判定', hint: '判断目标是否已完成' },
	monitor: { label: '后台监控', hint: '监控类任务的判断' },
	background_review: { label: '后台复盘', hint: '对话结束后的自我复盘' },
	review: { label: '审查', hint: '' },
	curator: { label: '整理', hint: '' }
};

export const auxTaskLabel = (task: string) => AUX_TASKS[task]?.label ?? task;

/** Tasks in a stable, meaningful order: the known ones first, then whatever hermes added. */
export const orderedAuxTasks = (tasks: string[]) => {
	const known = Object.keys(AUX_TASKS);
	return [...tasks].sort((a, b) => {
		const ia = known.indexOf(a);
		const ib = known.indexOf(b);
		return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib) || a.localeCompare(b);
	});
};

export const EFFORT_OPTIONS: { value: string; label: string; hint: string }[] = [
	{ value: 'none', label: '关闭', hint: '关闭额外思考，回复最快' },
	{ value: 'low', label: '低', hint: '轻量思考，适合简单问答' },
	{ value: 'medium', label: '中', hint: '速度与质量均衡' },
	{ value: 'high', label: '高', hint: '深度推理，适合复杂任务' },
	{ value: 'xhigh', label: '超高', hint: '更充分的推理预算' },
	{ value: 'max', label: '最大', hint: '最高强度（不支持的模型会自动降档）' }
];

export const EFFORT_LABELS: Record<string, string> = Object.fromEntries(
	EFFORT_OPTIONS.map((item) => [item.value, item.label])
);

export const effortLabel = (value: unknown, empty = '未设') => {
	const key = String(value ?? '')
		.trim()
		.toLowerCase();
	return !key ? empty : (EFFORT_LABELS[key] ?? key);
};

export const PROVIDER_SHORT_LABELS: Record<string, string> = {
	'openai-codex': 'Codex',
	nous: 'Nous',
	'qwen-oauth': 'Qwen',
	'minimax-oauth': 'MiniMax',
	'xai-oauth': 'xAI'
};

export const isOAuthModelId = (id: string) => {
	const idx = (id || '').indexOf(':');
	return idx > 0 && id.slice(0, idx) in PROVIDER_SHORT_LABELS;
};

export const shortModelName = (id: string) => {
	const idx = (id || '').indexOf(':');
	return idx > 0 && id.slice(0, idx) in PROVIDER_SHORT_LABELS ? id.slice(idx + 1) : id;
};

/** A value hermes could not map to a configured model (set from the command line). */
export const isForeignModel = (id: string) => id.startsWith('?');

export const modelLabel = (id: string, empty = '跟随主模型') => {
	if (!id) return empty;
	if (isForeignModel(id)) return `其他：${id.slice(1)}`;
	const idx = id.indexOf(':');
	if (idx > 0 && id.slice(0, idx) in PROVIDER_SHORT_LABELS) {
		return `${PROVIDER_SHORT_LABELS[id.slice(0, idx)]} · ${id.slice(idx + 1)}`;
	}
	return id;
};

export type ModelFamily = 'gpt' | 'deepseek' | 'gemini' | 'claude' | 'other';

export const modelFamily = (id: string): ModelFamily => {
	const s = (id || '').toLowerCase();
	if (s.includes('gpt') || s.includes('openai') || s.includes('codex')) return 'gpt';
	if (s.includes('deepseek')) return 'deepseek';
	if (s.includes('gemini') || s.includes('agy')) return 'gemini';
	if (s.includes('claude')) return 'claude';
	return 'other';
};

export const API_MODE_LABELS: Record<string, string> = {
	codex_responses: 'Responses',
	chat_completions: 'Chat',
	anthropic_messages: 'Anthropic'
};

// ---- fallback chains ----

export const chainAdd = (chain: string[], id: string, limit: number) =>
	!id || chain.includes(id) || chain.length >= limit ? chain : [...chain, id];

export const chainRemove = (chain: string[], index: number) => chain.filter((_, i) => i !== index);

export const chainMove = (chain: string[], index: number, delta: number) => {
	const to = index + delta;
	if (to < 0 || to >= chain.length) return chain;
	const next = [...chain];
	[next[index], next[to]] = [next[to], next[index]];
	return next;
};

/** Models that can still join a chain: not in it, and not the slot's own primary. */
export const chainCandidates = (modelIds: string[], chain: string[], primary: string) =>
	modelIds.filter((id) => id !== primary && !chain.includes(id));

/** Picking a new primary drops it from that slot's own chain (hermes refuses a chain that
 * repeats its primary). */
export const withPrimary = (chain: string[], primary: string) =>
	chain.filter((id) => id !== primary);

// ---- changes ----

export const diffRouting = (before: HermesRouting, after: HermesRouting): HermesRoutingChange[] => {
	const out: HermesRoutingChange[] = [];
	const walk = (a: any, b: any, path: string) => {
		const isObj = (v: any) => v && typeof v === 'object' && !Array.isArray(v);
		if (isObj(a) && isObj(b)) {
			for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) {
				walk(a[key], b[key], path ? `${path}.${key}` : key);
			}
		} else if (JSON.stringify(a) !== JSON.stringify(b)) {
			out.push({ path, before: a, after: b });
		}
	};
	walk(before, after, '');
	return out;
};

const pathLabel = (path: string) => {
	if (path === 'main') return '主模型';
	if (path === 'fallback') return '兜底链';
	if (path === 'delegation.model') return '子代理';
	if (path === 'delegation.fallback') return '子代理兜底';
	if (path === 'media.model') return '媒体识别';
	if (path === 'media.timeout') return '媒体超时';
	if (path === 'reasoning_effort') return '思考强度';
	if (path.startsWith('reasoning_overrides.')) {
		return `${modelLabel(path.slice('reasoning_overrides.'.length))} 思考强度`;
	}
	const m = path.match(/^auxiliary\.([^.]+)\.(model|fallback)$/);
	if (m) return `${auxTaskLabel(m[1])}${m[2] === 'fallback' ? '兜底' : ''}`;
	return path;
};

const valueLabel = (path: string, value: unknown) => {
	if (Array.isArray(value))
		return value.length ? value.map((v) => modelLabel(String(v))).join(' › ') : '无';
	if (path === 'media.timeout')
		return typeof value === 'number' && !Number.isNaN(value) ? `${value} 秒` : '未填';
	if (path === 'media.model') return modelLabel(String(value ?? ''), '不走首选');
	if (path === 'reasoning_effort') return effortLabel(value, '未设');
	if (path.startsWith('reasoning_overrides.')) return effortLabel(value, '跟随全局');
	return modelLabel(String(value ?? ''));
};

/** One plain line per change: 「主模型：deepseek-chat → gpt-chat」. */
export const describeChange = (change: HermesRoutingChange) =>
	`${pathLabel(change.path)}：${valueLabel(change.path, change.before)} → ${valueLabel(change.path, change.after)}`;

export const historySourceLabel = (source: string) =>
	source === 'halowebui' ? '网页' : source.startsWith('rollback:') ? '回滚' : source || '未知';

// ---- AGY 优先 ----

export type AgyDraft = { card_model: string; ui_runner: string; offiagy_model: string };

export const RUNNER_LABELS: Record<string, string> = {
	officlaude: 'officlaude（官方 Claude）',
	offiagy: 'offiagy（Google 账号）',
	agy: 'agy（网关 gemini-chat）',
	hermes: 'Hermes',
	reclaude: 'reclaude',
	cchclaude: 'cchclaude',
	anyclaude: 'anyclaude',
	codex: 'Codex'
};

export const runnerLabel = (name: string) => RUNNER_LABELS[name] ?? name;

export const agyDraftFrom = (prefs: HermesAgyPrefs): AgyDraft => ({
	card_model: prefs.card.model,
	ui_runner: prefs.teams.ui_runner ?? '',
	offiagy_model: prefs.teams.offiagy_model ?? ''
});

/** The fields that changed (what the save sends) and one plain line for each. */
export const agyChanges = (before: AgyDraft, rawAfter: AgyDraft) => {
	const after: AgyDraft = {
		card_model: rawAfter.card_model ?? '',
		ui_runner: rawAfter.ui_runner ?? '',
		offiagy_model: rawAfter.offiagy_model ?? ''
	};
	const update: Partial<AgyDraft> = {};
	const lines: string[] = [];
	if (before.card_model !== after.card_model) {
		update.card_model = after.card_model;
		const label = (v: string) => v || '关闭（直接走网关 agy）';
		lines.push(`回答卡片：${label(before.card_model)} → ${label(after.card_model)}`);
	}
	if (before.ui_runner !== after.ui_runner) {
		update.ui_runner = after.ui_runner;
		lines.push(`界面任务起点：${runnerLabel(before.ui_runner)} → ${runnerLabel(after.ui_runner)}`);
	}
	if (before.offiagy_model !== after.offiagy_model) {
		update.offiagy_model = after.offiagy_model;
		const label = (v: string) => v || 'AGY 默认';
		lines.push(`offiagy 模型：${label(before.offiagy_model)} → ${label(after.offiagy_model)}`);
	}
	return { update, lines };
};

export const WORK_STEP_KEYS: readonly WorkStepKey[] = [
	'plan',
	'plan_review',
	'dev',
	'frontend',
	'review'
];
export const WORK_PRESET_KEYS: readonly WorkPresetKey[] = ['default', 'deep', 'fast'];

export const WORK_PRESET_INFO: Record<
	WorkPresetKey,
	{ key: WorkPresetKey; command: string; label: string; laneTitle: string; hint: string }
> = {
	default: {
		key: 'default',
		command: '/work',
		label: '默认工作流',
		laneTitle: '默认 /work',
		hint: '直接发 /work 需求 时使用，可自由组合模块与全部环节执行器'
	},
	deep: {
		key: 'deep',
		command: '/work 深度',
		label: '深度多模型',
		laneTitle: '深度 /work',
		hint: '发 /work 深度 需求 时使用，适合复杂或高风险需求，支持独立配置'
	},
	fast: {
		key: 'fast',
		command: '/work 快速',
		label: '快速精简',
		laneTitle: '快速 /work',
		hint: '发 /work 快速 需求 时使用，适合轻量改动与小修小补，支持独立配置'
	}
};

const WORK_STEP_LABELS: Record<WorkStepKey, string> = {
	plan: '规划',
	plan_review: '规划审阅',
	dev: '后端 / 全栈开发',
	frontend: '前端开发',
	review: '审阅修复'
};

export const workStepLabel = (key: WorkStepKey) => WORK_STEP_LABELS[key];

const FALLBACK_STEP_DEFAULTS: Record<WorkStepKey, WorkStepConfig> = {
	plan: { runner: 'offiagy', fallback: ['agy'] },
	plan_review: { runner: 'officlaude', fallback: ['cchclaude', 'anyclaude', 'reclaude'] },
	dev: { runner: 'codex', fallback: [] },
	frontend: { runner: 'offiagy', fallback: ['agy'] },
	review: { runner: 'officlaude', fallback: ['cchclaude', 'anyclaude', 'reclaude'] }
};

const FALLBACK_PRESET_FLAGS: Record<'deep' | 'fast', Omit<WorkProfileConfig, 'steps'>> = {
	deep: {
		plan_review: true,
		dual_plan: true,
		plan_approval: true,
		ui_review: true,
		split_dev: true,
		codex_review: true
	},
	fast: {
		plan_review: false,
		dual_plan: false,
		plan_approval: false,
		ui_review: false,
		split_dev: false,
		codex_review: false
	}
};

const cloneWorkProfile = (
	raw: Partial<WorkProfileConfig> | undefined,
	fallback: Partial<WorkProfileConfig> | undefined,
	stepFallback?: Partial<Record<WorkStepKey, WorkStepConfig>>
): WorkProfileConfig => {
	const steps = {} as Record<WorkStepKey, WorkStepConfig>;
	for (const key of WORK_STEP_KEYS) {
		const step =
			raw?.steps?.[key] ??
			fallback?.steps?.[key] ??
			stepFallback?.[key] ??
			FALLBACK_STEP_DEFAULTS[key];
		steps[key] = { runner: step.runner, fallback: [...(step.fallback ?? [])] };
	}
	return {
		plan_review: Boolean(raw?.plan_review ?? fallback?.plan_review ?? false),
		dual_plan: Boolean(raw?.dual_plan ?? fallback?.dual_plan ?? false),
		plan_approval: Boolean(raw?.plan_approval ?? fallback?.plan_approval ?? false),
		ui_review: Boolean(raw?.ui_review ?? fallback?.ui_review ?? false),
		split_dev: Boolean(raw?.split_dev ?? fallback?.split_dev ?? false),
		codex_review: Boolean(raw?.codex_review ?? fallback?.codex_review ?? false),
		steps
	};
};

export const workProfileOf = (
	config: WorkWorkflowConfig,
	preset: WorkPresetKey = 'default'
): WorkProfileConfig => {
	if (preset === 'deep' || preset === 'fast') {
		return config.presets?.[preset] ?? cloneWorkProfile(undefined, FALLBACK_PRESET_FLAGS[preset], config.steps);
	}
	return {
		plan_review: config.plan_review,
		dual_plan: config.dual_plan,
		plan_approval: config.plan_approval,
		ui_review: config.ui_review,
		split_dev: config.split_dev,
		codex_review: config.codex_review,
		steps: config.steps
	};
};

export const withWorkProfile = (
	config: WorkWorkflowConfig,
	preset: WorkPresetKey,
	profile: WorkProfileConfig
): WorkWorkflowConfig => {
	if (preset === 'deep' || preset === 'fast') {
		return {
			...config,
			presets: {
				...config.presets,
				[preset]: profile
			}
		};
	}
	return {
		...config,
		...profile,
		presets: config.presets
	};
};

export const workDraftFrom = ({ config, defaults }: HermesWorkConfigResponse): WorkWorkflowConfig => {
	const base = cloneWorkProfile(config, defaults);
	const deep = cloneWorkProfile(
		config.presets?.deep,
		defaults.presets?.deep ?? FALLBACK_PRESET_FLAGS.deep,
		base.steps
	);
	const fast = cloneWorkProfile(
		config.presets?.fast,
		defaults.presets?.fast ?? FALLBACK_PRESET_FLAGS.fast,
		base.steps
	);
	return {
		...base,
		presets: { deep, fast }
	};
};

export const setWorkStepRunner = (
	draft: WorkWorkflowConfig,
	key: WorkStepKey,
	runner: string,
	preset: WorkPresetKey = 'default'
): WorkWorkflowConfig => {
	const profile = workProfileOf(draft, preset);
	const nextProfile: WorkProfileConfig = {
		...profile,
		steps: {
			...profile.steps,
			[key]: { runner, fallback: profile.steps[key].fallback.filter((id) => id !== runner) }
		}
	};
	return withWorkProfile(draft, preset, nextProfile);
};

const WORK_FLAG_CHANGES: readonly [keyof Omit<WorkProfileConfig, 'steps'>, string][] = [
	['plan_review', '规划后审阅'],
	['dual_plan', '双方案并行对照'],
	['plan_approval', '方案定稿后强制拍板'],
	['ui_review', 'UI 交互与文案互审'],
	['split_dev', '前后端分拆开发'],
	['codex_review', '交付前 Codex 2 轮审查']
];

const workProfileChanges = (
	before: WorkProfileConfig,
	after: WorkProfileConfig,
	prefix: string
): string[] => {
	const lines: string[] = [];
	const toggle = (value: boolean) => (value ? '开启' : '关闭');
	for (const [key, label] of WORK_FLAG_CHANGES) {
		const prev = Boolean(before[key]);
		const next = Boolean(after[key]);
		if (prev !== next) lines.push(`${prefix}${label}：${toggle(prev)} → ${toggle(next)}`);
	}
	for (const key of WORK_STEP_KEYS) {
		const label = workStepLabel(key);
		const prev = before.steps[key];
		const next = after.steps[key];
		if (prev.runner !== next.runner) {
			lines.push(`${prefix}${label}首选：${prev.runner} → ${next.runner}`);
		}
		const prevChain = prev.fallback.join(' › ') || '无';
		const nextChain = next.fallback.join(' › ') || '无';
		if (prevChain !== nextChain) lines.push(`${prefix}${label}兜底：${prevChain} → ${nextChain}`);
	}
	return lines;
};

export const workProfileEquals = (a: WorkProfileConfig, b: WorkProfileConfig) =>
	workProfileChanges(a, b, '').length === 0;

export const workChanges = (before: WorkWorkflowConfig, after: WorkWorkflowConfig) => {
	const lines: string[] = [];
	for (const preset of WORK_PRESET_KEYS) {
		const prefix = `${WORK_PRESET_INFO[preset].laneTitle} · `;
		lines.push(...workProfileChanges(workProfileOf(before, preset), workProfileOf(after, preset), prefix));
	}
	return { changed: lines.length > 0, lines };
};

export const workConfigEquals = (a: WorkWorkflowConfig, b: WorkWorkflowConfig) =>
	!workChanges(a, b).changed;

export type WorkFlowSummaryItem = {
	key: string;
	title: string;
	runner: string;
	fallback: string[];
	fixed?: boolean;
};

export const workFlowSummary = (
	config: WorkWorkflowConfig | WorkProfileConfig,
	preset: WorkPresetKey = 'default'
): WorkFlowSummaryItem[] => {
	const profile =
		'presets' in config ? workProfileOf(config as WorkWorkflowConfig, preset) : (config as WorkProfileConfig);
	const items: WorkFlowSummaryItem[] = [];
	const approve = profile.plan_approval ? '·拍板' : '';
	if (profile.dual_plan) {
		items.push({
			key: 'dual_plan',
			title: `双方案合成${approve}`,
			runner: `${profile.steps.plan_review.runner} + ${profile.steps.plan.runner}`,
			fallback: profile.steps.plan_review.fallback
		});
	} else {
		items.push({
			key: 'plan',
			title: profile.plan_review ? '规划' : `规划${approve}`,
			...profile.steps.plan
		});
		if (profile.plan_review) {
			items.push({
				key: 'plan_review',
				title: `规划审阅${approve}`,
				...profile.steps.plan_review
			});
		}
	}
	if (profile.ui_review) {
		items.push({
			key: 'ui_review',
			title: '交互审稿',
			runner: `${profile.steps.plan_review.runner} ⇄ ${profile.steps.plan.runner}`,
			fallback: profile.steps.plan.fallback
		});
	}
	if (profile.split_dev) {
		items.push({ key: 'dev', title: '后端开发', ...profile.steps.dev });
		items.push({ key: 'frontend', title: '前端开发', ...profile.steps.frontend });
		items.push({ key: 'review', title: '审阅修复', ...profile.steps.review });
	} else {
		items.push({ key: 'dev', title: '全栈开发', ...profile.steps.dev });
		items.push({ key: 'review', title: '审阅修复', ...profile.steps.review });
	}
	if (profile.codex_review) {
		items.push({ key: 'codex_review', title: 'Codex 2 轮审查', runner: 'codex', fallback: [], fixed: true });
	}
	return items;
};

export const workSelfReviewWarning = (
	profile: WorkProfileConfig,
	runners: WorkRunnerOption[]
): string => {
	if (profile.codex_review) return '';
	const familyOf = (name: string) =>
		runners.find((item) => item.name === name)?.family ?? modelFamily(name);
	const reviewFam = familyOf(profile.steps.review.runner);
	if (profile.split_dev) {
		const feFam = familyOf(profile.steps.frontend.runner);
		if (feFam && feFam === reviewFam) {
			return '提示：当前前端开发与审阅修复同属一个模型家族；建议给前端与审阅选不同家族执行器，或开启「交付前 Codex 2 轮独立审查」以保证交叉复核。';
		}
		return '';
	}
	const devFam = familyOf(profile.steps.dev.runner);
	if (devFam && devFam === reviewFam) {
		return '提示：当前全栈开发与审阅修复同属一个模型家族；建议选不同家族执行器或开启「交付前 Codex 2 轮独立审查」。';
	}
	return '';
};
