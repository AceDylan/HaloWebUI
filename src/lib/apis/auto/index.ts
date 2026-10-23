import { WEBUI_API_BASE_URL } from '$lib/constants';
import type { DecisionTrace } from '$lib/apis/decision-model';

export type AutoMode = 'answer' | 'discuss' | 'team';
export type AutoRoute = {
	id: string;
	title?: string;
	routing_model?: string | null;
	/** 辅助决策模型: which model chose, what, and whether it fell back. */
	decision?: DecisionTrace | null;
	/** The chat it was dispatched from (the result goes back there). */
	origin_chat_id?: string | null;
	question: string;
	status: 'routing' | 'dispatching' | 'dispatched' | 'error' | 'cancelled' | 'interrupted';
	mode: AutoMode | null;
	target_id: string | null;
	target_status: string | null;
	reason: string;
	error: string;
	href: string | null;
	created_at: number;
	auto_start: boolean;
};
export type AutoInput = {
	question: string;
	client_key: string;
	files: string[];
	context: string;
	research: boolean;
	preference: 'standard' | 'economy';
	mode: 'auto' | AutoMode;
	auto_start: boolean;
};

export class AutoApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}
async function call<T>(token: string, path = '', body?: object): Promise<T> {
	const res = await fetch(`${WEBUI_API_BASE_URL}/auto/${path}`, {
		method: body === undefined ? 'GET' : 'POST',
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
		...(body === undefined ? {} : { body: JSON.stringify(body) })
	});
	const data = await res.json();
	if (!res.ok)
		throw new AutoApiError(
			res.status,
			typeof data.detail === 'string' ? data.detail : '请求失败，请稍后再试'
		);
	return data;
}
export const createAutoRoute = (token: string, input: AutoInput) =>
	call<AutoRoute>(token, '', input);
export const getAutoRoute = (token: string, id: string) =>
	call<AutoRoute>(token, encodeURIComponent(id));
export const listAutoRoutes = (
	token: string,
	opts: { before?: string | null; q?: string; mode?: string } = {}
) => {
	const params = new URLSearchParams({ limit: '30' });
	if (opts.before) params.set('before', opts.before);
	if (opts.q?.trim()) params.set('q', opts.q.trim());
	if (opts.mode) params.set('mode', opts.mode);
	return call<{ items: AutoRoute[]; more: boolean; next: string | null }>(token, `?${params}`);
};
export const cancelAutoRoute = (token: string, id: string) =>
	call<AutoRoute>(token, `${encodeURIComponent(id)}/cancel`, {});
/** Route a failed / interrupted / cancelled request again (the chat's card follows the new one). */
export const retryAutoRoute = (token: string, id: string, mode: 'auto' | AutoMode = 'auto') =>
	call<AutoRoute>(token, `${encodeURIComponent(id)}/retry`, { mode });
export const targetAutoRoute = (token: string, mode: AutoMode, id: string) =>
	call<AutoRoute | null>(token, `target/${mode}/${encodeURIComponent(id)}`);
export const MODE_LABEL: Record<AutoMode, string> = {
	answer: '精答',
	discuss: '讨论',
	team: '协作台'
};
export const routePending = (row: AutoRoute) =>
	row.status === 'routing' || row.status === 'dispatching';
export const routeStatus = (row: AutoRoute) => {
	if (row.status !== 'dispatched')
		return {
			routing: '正在选择处理方式',
			dispatching: '正在创建任务',
			error: '派发失败',
			cancelled: '已取消',
			interrupted: '已中断'
		}[row.status];
	const names: Record<string, string> = {
		done: '已完成',
		completed: '已完成',
		plan_ready: '等你批准',
		planning: '正在规划',
		plan_failed: '规划失败',
		starting: '正在启动',
		start_failed: '启动失败',
		attention: '需要处理',
		paused: '已暂停',
		running: '进行中',
		concluding: '正在写结论',
		answering: '正在作答',
		researching: '正在查资料',
		routing: '正在匹配助手',
		error: '任务出错',
		failed: '任务失败',
		stopped: '已停止',
		interrupted: '已中断',
		deleted: '任务已删除',
		cancelled: '已取消'
	};
	return names[row.target_status ?? ''] ?? '已派发';
};
