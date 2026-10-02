/**
 * 协作台 pure logic: dependency layout, the replay fold, member / team status, delivery state
 * of user notes, replay timing. No Svelte, no fetch — unit-tested in model.test.ts.
 *
 * Live view and replay share one rule: the state at a point in time is the fold of the event
 * stream up to that point (each event carries the task status after it, computed by Hermes).
 * The live view additionally trusts Hermes' authoritative snapshot for the current state.
 */
import type { LiveTask, TeamEvent } from '$lib/apis/teams';

export type TaskState = { status: string; sub_status: string };

export const SUB_STATUS_LABEL: Record<string, string> = {
	pending: '未创建',
	queued: '等待派发',
	waiting_deps: '等待前置任务',
	running: '执行中',
	quota_wait: '额度等待',
	waiting_user: '等你回复',
	failed: '失败',
	blocked: '受阻',
	stopped: '已停止',
	done: '已完成',
	review: '评审中',
	triage: '需人工处理',
	scheduled: '已排期',
	archived: '已归档',
	idle: '空闲',
	coordinating: '协调中',
	paused: '已暂停'
};

export type Tone = 'run' | 'wait' | 'deps' | 'user' | 'quota' | 'fail' | 'stop' | 'done' | 'idle';

export const SUB_STATUS_TONE: Record<string, Tone> = {
	pending: 'idle',
	queued: 'wait',
	waiting_deps: 'deps',
	running: 'run',
	quota_wait: 'quota',
	waiting_user: 'user',
	failed: 'fail',
	blocked: 'fail',
	stopped: 'stop',
	done: 'done',
	review: 'run',
	triage: 'user',
	scheduled: 'wait',
	archived: 'stop',
	idle: 'idle',
	coordinating: 'run',
	paused: 'stop'
};

export const PHASE_LABEL: Record<string, string> = {
	planning: '负责人正在制定计划',
	plan_ready: '等你批准计划',
	plan_failed: '计划没做出来',
	starting: '正在启动',
	start_failed: '启动失败',
	cancelled: '已取消',
	running: '进行中',
	attention: '需要处理',
	paused: '已暂停派发',
	stopped: '已停止',
	completed: '已完成'
};

export const statusLabel = (value: string | null | undefined) =>
	SUB_STATUS_LABEL[value ?? ''] ?? value ?? '';
export const toneOf = (value: string | null | undefined): Tone => SUB_STATUS_TONE[value ?? ''] ?? 'idle';

// --- layout ---------------------------------------------------------------------------------

export type LayoutTask = { id: string; key?: string; seq?: number; parents: string[] };
export type PositionedTask = { id: string; depth: number; row: number; x: number; y: number };
export type BoardLayout = {
	positions: Map<string, PositionedTask>;
	columns: number;
	rows: number;
	width: number;
	height: number;
	lanes: { depth: number; x: number; count: number }[];
};

export const LAYOUT = { laneWidth: 248, laneGap: 56, cardWidth: 220, cardHeight: 104, rowGap: 18, pad: 24 };

/** Longest dependency path per task; cycles and unknown parents count as depth 0. */
export const taskDepths = (tasks: LayoutTask[]): Map<string, number> => {
	const byId = new Map(tasks.map((t) => [t.id, t]));
	const depths = new Map<string, number>();
	const visiting = new Set<string>();
	const depthOf = (id: string): number => {
		const cached = depths.get(id);
		if (cached !== undefined) return cached;
		if (visiting.has(id)) return 0;
		const task = byId.get(id);
		if (!task) return 0;
		visiting.add(id);
		const parents = task.parents.filter((p) => byId.has(p));
		const depth = parents.length === 0 ? 0 : 1 + Math.max(...parents.map(depthOf));
		visiting.delete(id);
		depths.set(id, depth);
		return depth;
	};
	for (const t of tasks) depthOf(t.id);
	return depths;
};

const order = (a: LayoutTask, b: LayoutTask) =>
	(a.seq ?? 0) - (b.seq ?? 0) || (a.key ?? a.id).localeCompare(b.key ?? b.id, 'en', { numeric: true });

/** One left-to-right lane per dependency depth ("#4 and #6 side by side, #5 to their right"). */
export const layoutTasks = (tasks: LayoutTask[]): BoardLayout => {
	const depths = taskDepths(tasks);
	const lanes = new Map<number, LayoutTask[]>();
	for (const t of [...tasks].sort(order)) {
		const d = depths.get(t.id) ?? 0;
		lanes.set(d, [...(lanes.get(d) ?? []), t]);
	}
	const columns = tasks.length ? Math.max(...depths.values()) + 1 : 0;
	const rows = Math.max(0, ...[...lanes.values()].map((l) => l.length));
	const stack = (n: number) => n * LAYOUT.cardHeight + Math.max(0, n - 1) * LAYOUT.rowGap;
	const height = LAYOUT.pad * 2 + stack(rows);
	const positions = new Map<string, PositionedTask>();
	const laneList: BoardLayout['lanes'] = [];
	for (let depth = 0; depth < columns; depth++) {
		const lane = lanes.get(depth) ?? [];
		const x = LAYOUT.pad + depth * (LAYOUT.laneWidth + LAYOUT.laneGap);
		const offset = (stack(rows) - stack(lane.length)) / 2; // centre short lanes
		lane.forEach((t, row) => {
			positions.set(t.id, {
				id: t.id,
				depth,
				row,
				x: x + (LAYOUT.laneWidth - LAYOUT.cardWidth) / 2,
				y: LAYOUT.pad + offset + row * (LAYOUT.cardHeight + LAYOUT.rowGap)
			});
		});
		laneList.push({ depth, x, count: lane.length });
	}
	const width = LAYOUT.pad * 2 + columns * LAYOUT.laneWidth + Math.max(0, columns - 1) * LAYOUT.laneGap;
	return { positions, columns, rows, width, height, lanes: laneList };
};

// --- fold -----------------------------------------------------------------------------------

/** Task states after applying events[0..upto] (inclusive). Tasks without an event yet are "pending". */
export const foldStates = (
	tasks: Pick<LiveTask, 'id'>[],
	events: TeamEvent[],
	upto: number = events.length - 1
): Map<string, TaskState> => {
	const states = new Map<string, TaskState>(tasks.map((t) => [t.id, { status: 'pending', sub_status: 'pending' }]));
	const end = Math.min(upto, events.length - 1);
	for (let i = 0; i <= end; i++) {
		const ev = events[i];
		if (!ev.task_id || !states.has(ev.task_id)) continue;
		if (ev.status || ev.sub_status) {
			const prev = states.get(ev.task_id)!;
			states.set(ev.task_id, {
				status: ev.status ?? prev.status,
				sub_status: ev.sub_status ?? ev.status ?? prev.sub_status
			});
		}
	}
	return states;
};

/** The authoritative live states (snapshot). */
export const liveStates = (tasks: LiveTask[]): Map<string, TaskState> =>
	new Map(tasks.map((t) => [t.id, { status: t.status, sub_status: t.sub_status }]));

const MEMBER_PRIORITY = ['running', 'quota_wait', 'waiting_user', 'failed', 'stopped', 'blocked', 'queued', 'waiting_deps'];

export const memberStatus = (states: TaskState[]): string => {
	if (!states.length) return 'idle';
	const subs = new Set(states.map((s) => s.sub_status));
	for (const s of MEMBER_PRIORITY) if (subs.has(s)) return s;
	if (states.every((s) => s.status === 'done' || s.status === 'archived')) return 'done';
	if (states.every((s) => s.status === 'pending')) return 'idle';
	return 'idle';
};

/** Team phase at the end of events[0..upto] (replay) — same rules as Hermes' team_phase. */
export const phaseAt = (states: Map<string, TaskState>, events: TeamEvent[], upto: number): string => {
	let paused = false;
	let stopped = false;
	for (let i = 0; i <= Math.min(upto, events.length - 1); i++) {
		const ev = events[i];
		if (ev.type !== 'team') continue;
		const action = ev.data?.action;
		if (action === 'stopped') stopped = true;
		if (action === 'paused') paused = true;
		if (action === 'resumed') paused = false;
	}
	const list = [...states.values()];
	if (stopped) return 'stopped';
	if (list.length && list.every((s) => s.status === 'done' || s.status === 'archived')) return 'completed';
	if (paused) return 'paused';
	if (list.some((s) => ['failed', 'blocked', 'waiting_user'].includes(s.sub_status) || s.status === 'triage'))
		return 'attention';
	return 'running';
};

export const leadStatus = (phase: string) =>
	({ completed: 'done', stopped: 'stopped', paused: 'paused', attention: 'waiting_user' })[phase] ?? 'coordinating';

export const countStates = (states: Map<string, TaskState>) => {
	const counts = { done: 0, running: 0, waiting: 0, attention: 0, total: states.size };
	for (const s of states.values()) {
		if (s.status === 'done' || s.status === 'archived') counts.done++;
		else if (s.sub_status === 'running' || s.sub_status === 'review') counts.running++;
		else if (['failed', 'blocked', 'waiting_user', 'stopped', 'triage'].includes(s.sub_status)) counts.attention++;
		else counts.waiting++;
	}
	return counts;
};

/** Why a task is waiting on its dependencies: the parents not done yet at this point. */
export const openParents = (
	task: Pick<LiveTask, 'parents'>,
	states: Map<string, TaskState>
): string[] => task.parents.filter((p) => !['done', 'archived'].includes(states.get(p)?.status ?? ''));

// --- events ----------------------------------------------------------------------------------

/** Merge a fetched page into the list: dedupe by id, keep event order (seq, then id). */
export const mergeEvents = (existing: TeamEvent[], incoming: TeamEvent[]): TeamEvent[] => {
	if (!incoming.length) return existing;
	const seen = new Set(existing.map((e) => e.id));
	const fresh = incoming.filter((e) => !seen.has(e.id));
	if (!fresh.length) return existing;
	const merged = [...existing, ...fresh];
	const last = existing[existing.length - 1];
	if (!last || fresh.every((e) => e.seq >= last.seq)) return merged;
	return merged.sort((a, b) => a.seq - b.seq || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
};

export type FeedCategory = 'message' | 'tool' | 'system';

export const feedCategory = (ev: TeamEvent): FeedCategory => {
	if (ev.type === 'message' || ev.type === 'handoff' || ev.type === 'delivery') return 'message';
	if (ev.type === 'tool' || ev.type === 'subagent') return 'tool';
	return 'system';
};

export type Delivery = { state: 'queued' | 'delivered' | 'undelivered'; via?: string; label: string };

/** Delivery of a user note as it stood at event index `cursorSeq` (null = now). */
export const deliveryAt = (ev: TeamEvent, cursorSeq: number | null): Delivery | null => {
	if (ev.type !== 'message' || ev.who !== 'user') return null;
	const seq = ev.data?.delivered_seq;
	if (typeof seq === 'number' && (cursorSeq === null || seq <= cursorSeq)) {
		const via = ev.data?.delivered_via as string;
		const label =
			({
				steer: '已送达（运行中注入）',
				attempt_context: '已随新的执行尝试送达',
				runner_answer: '已通过续跑送达',
				task_read: '已送达（成员读取任务时看到）',
				runner_task: '已写入任务说明'
			} as Record<string, string>)[via] ?? '已送达';
		return { state: 'delivered', via, label };
	}
	if (ev.data?.delivery === 'undelivered' && cursorSeq === null) {
		return { state: 'undelivered', label: '未送达（任务已结束）' };
	}
	return { state: 'queued', label: '排队中，尚未送达' };
};

// --- replay -----------------------------------------------------------------------------------

export const REPLAY_SPEEDS = [0.5, 1, 2, 4] as const;
export const REPLAY_MAX_GAP_MS = 2500;
export const REPLAY_MIN_GAP_MS = 120;

/** Wait before showing event i+1: the real gap scaled by speed, long idle gaps compressed. */
export const replayDelay = (events: TeamEvent[], index: number, speed: number) => {
	const a = events[index]?.ts;
	const b = events[index + 1]?.ts;
	const real = typeof a === 'number' && typeof b === 'number' && b > a ? (b - a) * 1000 : REPLAY_MIN_GAP_MS;
	const clamped = Math.min(REPLAY_MAX_GAP_MS, Math.max(REPLAY_MIN_GAP_MS, real));
	return { ms: clamped / speed, compressed: real > REPLAY_MAX_GAP_MS };
};

// --- avatars / formatting -------------------------------------------------------------------

export type AvatarKind = 'lead' | 'backend' | 'frontend' | 'qa' | 'reviewer' | 'docs' | 'data' | 'ops' | 'design' | 'generic';

const AVATAR_RULES: [AvatarKind, RegExp][] = [
	['reviewer', /review|评审|审查|audit|security|检查/],
	['qa', /\bqa\b|test|quality|测试|验证|verify/],
	['frontend', /front|\bui\b|\bux\b|page|页面|前端|界面/],
	['backend', /back|server|\bapi\b|service|后端|服务|接口/],
	['design', /design|设计|product|产品/],
	['docs', /doc|writer|spec|文档|说明|写作/],
	['data', /data|research|analy|调研|数据|研究|资料/],
	['ops', /ops|deploy|release|运维|部署|发布/]
];

export const avatarKind = (member: { name?: string; role?: string }, isLead = false): AvatarKind => {
	if (isLead) return 'lead';
	const text = `${member.name ?? ''} ${member.role ?? ''}`.toLowerCase();
	for (const [kind, re] of AVATAR_RULES) if (re.test(text)) return kind;
	return 'generic';
};

export const formatClock = (ts: number | null | undefined) => {
	if (!ts) return '--:--:--';
	const d = new Date(ts * 1000);
	return d.toLocaleTimeString('zh-CN', { hour12: false });
};

export const formatDuration = (seconds: number) => {
	const s = Math.max(0, Math.round(seconds));
	const h = Math.floor(s / 3600);
	const m = Math.floor((s % 3600) / 60);
	const r = s % 60;
	return h > 0
		? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
		: `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
};

export const EXECUTOR_LABEL: Record<string, string> = { hermes: 'Hermes 代理', reclaude: 'reclaude' };
