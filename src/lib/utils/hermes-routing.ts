// Labels and pure helpers for the 「Hermes 模型」 settings page (HermesRouting.svelte).
// Hermes validates and writes the routing itself (hermes_cli/routing_admin.py); this only
// shapes what the page shows and what it sends.
import type { HermesRouting, HermesRoutingChange } from '$lib/apis/hermes';

export const ROUTING_MAX_FALLBACKS = 3;
export const ROUTING_MAX_AUX_FALLBACKS = 2;
export const MEDIA_TIMEOUT_MIN = 30;
export const MEDIA_TIMEOUT_MAX = 600;

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

/** A value hermes could not map to a configured model (set from the command line). */
export const isForeignModel = (id: string) => id.startsWith('?');

export const modelLabel = (id: string, empty = '跟随主模型') =>
	!id ? empty : isForeignModel(id) ? `其他：${id.slice(1)}` : id;

export type ModelFamily = 'gpt' | 'deepseek' | 'gemini' | 'claude' | 'other';

export const modelFamily = (id: string): ModelFamily => {
	const s = (id || '').toLowerCase();
	if (s.includes('gpt') || s.includes('openai')) return 'gpt';
	if (s.includes('deepseek')) return 'deepseek';
	if (s.includes('gemini')) return 'gemini';
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
	const m = path.match(/^auxiliary\.([^.]+)\.(model|fallback)$/);
	if (m) return `${auxTaskLabel(m[1])}${m[2] === 'fallback' ? '兜底' : ''}`;
	return path;
};

const valueLabel = (path: string, value: unknown) => {
	if (Array.isArray(value))
		return value.length ? value.map((v) => modelLabel(String(v))).join(' › ') : '无';
	if (path === 'media.timeout') return `${value} 秒`;
	if (path === 'media.model') return modelLabel(String(value ?? ''), '不走首选');
	return modelLabel(String(value ?? ''));
};

/** One plain line per change: 「主模型：deepseek-chat → gpt-chat」. */
export const describeChange = (change: HermesRoutingChange) =>
	`${pathLabel(change.path)}：${valueLabel(change.path, change.before)} → ${valueLabel(change.path, change.after)}`;

export const historySourceLabel = (source: string) =>
	source === 'halowebui' ? '网页' : source.startsWith('rollback:') ? '回滚' : source || '未知';
