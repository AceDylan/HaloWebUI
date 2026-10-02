/**
 * 协作台 pure logic: dependency layout, the replay fold, member / team status, delivery state
 * of user notes, replay timing. No Svelte, no fetch — unit-tested in model.test.ts.
 *
 * Live view and replay share one rule: the state at a point in time is the fold of the event
 * stream up to that point (each event carries the task status after it, computed by Hermes).
 * The live view additionally trusts Hermes' authoritative snapshot for the current state.
 */
import type { LiveTask, TeamEvent, TeamExecutor } from '$lib/apis/teams';

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
export const toneOf = (value: string | null | undefined): Tone =>
	SUB_STATUS_TONE[value ?? ''] ?? 'idle';

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

export const LAYOUT = {
	laneWidth: 248,
	laneGap: 56,
	cardWidth: 220,
	cardHeight: 104,
	rowGap: 18,
	pad: 24,
	/** Top-to-bottom layout: gap between lanes (rows) and between cards in a lane. */
	laneGapV: 46,
	colGap: 22
};

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
	(a.seq ?? 0) - (b.seq ?? 0) ||
	(a.key ?? a.id).localeCompare(b.key ?? b.id, 'en', { numeric: true });

/** One lane per dependency depth ("#4 and #6 side by side, #5 after them"): left to right
 *  (`LR`, lanes are columns) or top to bottom (`TB`, lanes are rows — for long chains on a
 *  narrow board). */
export const layoutTasks = (tasks: LayoutTask[], direction: 'LR' | 'TB' = 'LR'): BoardLayout => {
	const depths = taskDepths(tasks);
	const lanes = new Map<number, LayoutTask[]>();
	for (const t of [...tasks].sort(order)) {
		const d = depths.get(t.id) ?? 0;
		lanes.set(d, [...(lanes.get(d) ?? []), t]);
	}
	const columns = tasks.length ? Math.max(...depths.values()) + 1 : 0;
	const rows = Math.max(0, ...[...lanes.values()].map((l) => l.length));
	const positions = new Map<string, PositionedTask>();
	const laneList: BoardLayout['lanes'] = [];
	if (direction === 'TB') {
		const across = (n: number) => n * LAYOUT.cardWidth + Math.max(0, n - 1) * LAYOUT.colGap;
		for (let depth = 0; depth < columns; depth++) {
			const lane = lanes.get(depth) ?? [];
			const y = LAYOUT.pad + depth * (LAYOUT.cardHeight + LAYOUT.laneGapV);
			const offset = (across(rows) - across(lane.length)) / 2;
			lane.forEach((t, row) => {
				positions.set(t.id, {
					id: t.id,
					depth,
					row,
					x: LAYOUT.pad + offset + row * (LAYOUT.cardWidth + LAYOUT.colGap),
					y
				});
			});
			laneList.push({ depth, x: y, count: lane.length });
		}
		return {
			positions,
			columns,
			rows,
			width: LAYOUT.pad * 2 + across(rows),
			height:
				LAYOUT.pad * 2 + columns * LAYOUT.cardHeight + Math.max(0, columns - 1) * LAYOUT.laneGapV,
			lanes: laneList
		};
	}
	const stack = (n: number) => n * LAYOUT.cardHeight + Math.max(0, n - 1) * LAYOUT.rowGap;
	const height = LAYOUT.pad * 2 + stack(rows);
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
	const width =
		LAYOUT.pad * 2 + columns * LAYOUT.laneWidth + Math.max(0, columns - 1) * LAYOUT.laneGap;
	return { positions, columns, rows, width, height, lanes: laneList };
};

/** Which way to lay the board out in a box `boxWidth` wide (height capped at `maxHeight`): the
 *  direction whose fitted zoom is larger, preferring left-to-right unless it would shrink the
 *  cards below `minZoom`. */
export const boardDirection = (
	tasks: LayoutTask[],
	boxWidth: number,
	maxHeight: number,
	minZoom = 0.8
): 'LR' | 'TB' => {
	if (!boxWidth || tasks.length < 2) return 'LR';
	// fitView keeps a little padding round the cards (TeamBoard: 6% each side).
	const zoom = (l: BoardLayout) =>
		Math.min(1, boxWidth / (l.width * 1.12), maxHeight / (l.height * 1.12));
	const lr = zoom(layoutTasks(tasks, 'LR'));
	if (lr >= minZoom) return 'LR';
	return zoom(layoutTasks(tasks, 'TB')) > lr + 0.05 ? 'TB' : 'LR';
};

// --- fold -----------------------------------------------------------------------------------

/** Task states after applying events[0..upto] (inclusive). Tasks without an event yet are "pending". */
export const foldStates = (
	tasks: Pick<LiveTask, 'id'>[],
	events: TeamEvent[],
	upto: number = events.length - 1
): Map<string, TaskState> => {
	const states = new Map<string, TaskState>(
		tasks.map((t) => [t.id, { status: 'pending', sub_status: 'pending' }])
	);
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

const MEMBER_PRIORITY = [
	'running',
	'quota_wait',
	'waiting_user',
	'failed',
	'stopped',
	'blocked',
	'queued',
	'waiting_deps'
];

export const memberStatus = (states: TaskState[]): string => {
	if (!states.length) return 'idle';
	const subs = new Set(states.map((s) => s.sub_status));
	for (const s of MEMBER_PRIORITY) if (subs.has(s)) return s;
	if (states.every((s) => s.status === 'done' || s.status === 'archived')) return 'done';
	if (states.every((s) => s.status === 'pending')) return 'idle';
	return 'idle';
};

/** Team phase at the end of events[0..upto] (replay) — same rules as Hermes' team_phase. */
export const phaseAt = (
	states: Map<string, TaskState>,
	events: TeamEvent[],
	upto: number
): string => {
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
	if (list.length && list.every((s) => s.status === 'done' || s.status === 'archived'))
		return 'completed';
	if (paused) return 'paused';
	if (
		list.some(
			(s) => ['failed', 'blocked', 'waiting_user'].includes(s.sub_status) || s.status === 'triage'
		)
	)
		return 'attention';
	return 'running';
};

export const leadStatus = (phase: string) =>
	({ completed: 'done', stopped: 'stopped', paused: 'paused', attention: 'waiting_user' })[phase] ??
	'coordinating';

export const countStates = (states: Map<string, TaskState>) => {
	const counts = { done: 0, running: 0, waiting: 0, attention: 0, total: states.size };
	for (const s of states.values()) {
		if (s.status === 'done' || s.status === 'archived') counts.done++;
		else if (s.sub_status === 'running' || s.sub_status === 'review') counts.running++;
		else if (['failed', 'blocked', 'waiting_user', 'stopped', 'triage'].includes(s.sub_status))
			counts.attention++;
		else counts.waiting++;
	}
	return counts;
};

/** Why a task is waiting on its dependencies: the parents not done yet at this point. */
export const openParents = (
	task: Pick<LiveTask, 'parents'>,
	states: Map<string, TaskState>
): string[] =>
	task.parents.filter((p) => !['done', 'archived'].includes(states.get(p)?.status ?? ''));

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

/** What a member is doing, in one line, from its latest event (null = nothing to show). */
export const activityText = (ev: TeamEvent): string | null => {
	const text = (ev.text ?? '').replace(/\s+/g, ' ').trim();
	switch (ev.type) {
		case 'tool': {
			const name = ev.data?.name ? String(ev.data.name) : '工具';
			return text ? `${name} · ${text}` : name;
		}
		case 'subagent':
			return ev.data?.phase === 'start' ? '派出子代理' : '子代理结束';
		case 'runner': {
			const runner = ev.data?.runner ? String(ev.data.runner) : 'runner';
			const phase = RUNNER_EVENT_LABEL[ev.data?.phase as string] ?? ev.data?.phase ?? '';
			return `${runner} ${phase}${text ? ` · ${text}` : ''}`.trim();
		}
		case 'handoff':
			return text ? `完成并交接 · ${text}` : '完成并交接';
		case 'message':
			if (ev.who === 'user') return null;
			return text || null;
		case 'status':
		case 'attempt':
			return text || (ev.sub_status ? statusLabel(ev.sub_status) : null);
		default:
			return null;
	}
};

export const RUNNER_EVENT_LABEL: Record<string, string> = {
	launched: '已启动',
	continued: '续跑',
	answered: '已回答',
	quota_wait: '额度等待',
	question: '等你回答',
	failed: '失败',
	stopped: '已停止',
	fallback: '改派'
};

/** Each member's latest activity among the events (newest first scan, stops when all found). */
export const latestActivity = (
	events: TeamEvent[],
	members: string[]
): Map<string, { text: string; ts: number; type: string }> => {
	const out = new Map<string, { text: string; ts: number; type: string }>();
	const wanted = new Set(members);
	for (let i = events.length - 1; i >= 0 && out.size < wanted.size; i--) {
		const ev = events[i];
		if (!ev.member || !wanted.has(ev.member) || out.has(ev.member)) continue;
		const text = activityText(ev);
		if (text) out.set(ev.member, { text, ts: ev.ts, type: ev.type });
	}
	return out;
};

/** Markdown written by members, as plain text for a short preview (feed bubbles): headings,
 *  emphasis, inline code and link syntax removed; line breaks kept. */
export const plainPreview = (text: string): string =>
	(text ?? '')
		.replace(/```[a-z0-9_-]*\n?/gi, '')
		.replace(/^\s{0,3}#{1,6}\s+/gm, '')
		.replace(/^\s{0,3}>\s?/gm, '')
		.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
		.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
		.replace(/(\*\*|__)(.+?)\1/g, '$2')
		.replace(/(^|[^*\w])\*(?!\s)([^*\n]+?)\*(?!\w)/g, '$1$2')
		.replace(/`([^`\n]+)`/g, '$1')
		.replace(/\n{3,}/g, '\n\n')
		.trim();

export type Delivery = {
	state: 'queued' | 'delivered' | 'undelivered';
	via?: string;
	label: string;
};

/** Delivery of a user note as it stood at event index `cursorSeq` (null = now). */
export const deliveryAt = (ev: TeamEvent, cursorSeq: number | null): Delivery | null => {
	if (ev.type !== 'message' || ev.who !== 'user') return null;
	const seq = ev.data?.delivered_seq;
	if (typeof seq === 'number' && (cursorSeq === null || seq <= cursorSeq)) {
		const via = ev.data?.delivered_via as string;
		const label =
			(
				{
					steer: '已送达（运行中注入）',
					attempt_context: '已随新的执行尝试送达',
					runner_answer: '已通过续跑送达',
					task_read: '已送达（成员读取任务时看到）',
					runner_task: '已写入任务说明'
				} as Record<string, string>
			)[via] ?? '已送达';
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
	const real =
		typeof a === 'number' && typeof b === 'number' && b > a ? (b - a) * 1000 : REPLAY_MIN_GAP_MS;
	const clamped = Math.min(REPLAY_MAX_GAP_MS, Math.max(REPLAY_MIN_GAP_MS, real));
	return { ms: clamped / speed, compressed: real > REPLAY_MAX_GAP_MS };
};

export type ReplayMark = {
	index: number;
	kind: 'fail' | 'handoff' | 'team' | 'user' | 'message';
};

/**
 * Landmarks on the replay track: failures, handoffs, team milestones, your notes and member
 * messages. Over `max`, member messages go first, then the rest is thinned evenly.
 */
export const replayMarks = (events: TeamEvent[], max = 80): ReplayMark[] => {
	const marks: ReplayMark[] = [];
	events.forEach((ev, index) => {
		const failed =
			['failed', 'blocked'].includes(ev.sub_status ?? '') ||
			(ev.type === 'runner' && ev.data?.phase === 'failed');
		const kind: ReplayMark['kind'] | null = failed
			? 'fail'
			: ev.type === 'handoff'
				? 'handoff'
				: ev.type === 'team'
					? 'team'
					: ev.type === 'message'
						? ev.who === 'user'
							? 'user'
							: 'message'
						: null;
		if (kind) marks.push({ index, kind });
	});
	if (marks.length <= max) return marks;
	const kept = marks.filter((m) => m.kind !== 'message');
	if (kept.length <= max) return kept;
	const step = kept.length / max;
	return Array.from({ length: max }, (_, i) => kept[Math.floor(i * step)]);
};

// --- avatars / formatting -------------------------------------------------------------------

export type AvatarKind =
	| 'lead'
	| 'backend'
	| 'frontend'
	| 'qa'
	| 'reviewer'
	| 'docs'
	| 'data'
	| 'ops'
	| 'design'
	| 'generic';

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

export const avatarKind = (
	member: { name?: string; role?: string },
	isLead = false
): AvatarKind => {
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

/** Who can run a member, as offered when reviewing a plan (the runners are the ones `/reclaude`, `/codex` … start). */
export const EXECUTOR_OPTIONS: { value: TeamExecutor; label: string }[] = [
	{ value: 'hermes', label: 'Hermes 代理' },
	{ value: 'reclaude', label: 'reclaude · Claude' },
	{ value: 'cchclaude', label: 'cchclaude · Claude' },
	{ value: 'anyclaude', label: 'anyclaude · 慢' },
	{ value: 'codex', label: 'codex' },
	{ value: 'agy', label: 'agy' }
];

export const EXECUTOR_LABEL: Record<string, string> = Object.fromEntries(
	EXECUTOR_OPTIONS.map((o) => [o.value, o.value === 'hermes' ? o.label : o.value])
);

/** A member run by an external runner: it cannot take notes mid-run and is stopped through the runner. */
export const isRunnerExecutor = (executor: string | null | undefined): boolean =>
	!!executor && executor !== 'hermes' && EXECUTOR_OPTIONS.some((o) => o.value === executor);

// --- runners: chosen vs actual ---------------------------------------------------------------

/** Labels when the live registry (GET /teams/meta) is not loaded yet. */
export const KIND_LABEL: Record<string, string> = {
	code: '后端 / 通用代码',
	ui: '前端 / UI / UX',
	complex: '复杂任务',
	research: '调研 / 分析',
	writing: '写作 / 文档'
};

export const SOURCE_LABEL: Record<string, string> = {
	auto: '按任务类型自动选择',
	goal: '目标里点名',
	user: '你手动指定'
};

export type RunnerDecision = {
	chosen: string;
	actual: string | null;
	changed: boolean;
	reason: string;
	source: 'auto' | 'goal' | 'user';
};

/** A plan member's runner: where its chain starts and what will actually run it now. */
export const memberRunner = (m: {
	executor?: string;
	runner?: string | null;
	runner_note?: string;
	executor_source?: string;
}): RunnerDecision => {
	const chosen = m.executor || 'hermes';
	const actual = m.runner === undefined ? chosen : m.runner;
	const source = (
		['auto', 'goal', 'user'].includes(m.executor_source ?? '') ? m.executor_source : 'auto'
	) as RunnerDecision['source'];
	return { chosen, actual, changed: actual !== chosen, reason: m.runner_note ?? '', source };
};

/** A live task's runner: chosen (the member's) vs the one on it now, and why it moved. */
export const taskRunner = (t: {
	executor?: string;
	chosen?: string;
	chosen_by?: string;
	trail?: { from: string; to: string | null; reason: string }[];
}): RunnerDecision => {
	const actual = t.executor || 'hermes';
	const chosen = t.chosen || actual;
	const last = [...(t.trail ?? [])].reverse().find((s) => s.from !== s.to);
	const source = (
		['auto', 'goal', 'user'].includes(t.chosen_by ?? '') ? t.chosen_by : 'auto'
	) as RunnerDecision['source'];
	return {
		chosen,
		actual,
		changed: actual !== chosen || !!(t.trail ?? []).length,
		reason: last?.reason ?? '',
		source
	};
};

export const RUNNER_PHASE_LABEL: Record<string, string> = {
	plan: '批准时',
	launch: '启动前',
	runtime: '运行中',
	retry: '重试时'
};

// --- the conclusion report ------------------------------------------------------------------

const IMAGE_RE = /\.(png|jpe?g|gif|webp|svg|avif|bmp)(\?[^\s)]*)?$/i;
const SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;

export const isImagePath = (path: string) => IMAGE_RE.test(path.trim());

/** A link target in the report → URL: workspace-relative (or absolute inside the workspace)
 *  paths go to the workspace file route, anything with a scheme / anchor stays as written. */
export const reportHref = (
	href: string,
	opts: { workspace?: string | null; fileUrl: (path: string) => string }
): string => {
	const raw = href.trim().replace(/^<|>$/g, '');
	if (!raw || raw.startsWith('#') || SCHEME_RE.test(raw) || raw.startsWith('//')) return raw;
	let path = raw;
	const ws = (opts.workspace ?? '').replace(/\/+$/, '');
	if (path.startsWith('/')) {
		if (!ws || !(path === ws || path.startsWith(ws + '/'))) return raw;
		path = path.slice(ws.length + 1);
	}
	path = path.replace(/^\.\//, '');
	if (!path || path.split('/').includes('..')) return raw;
	const [clean, query] = path.split(/(?=[?#])/);
	let decoded = clean;
	try {
		decoded = decodeURIComponent(clean);
	} catch {
		/* a literal % in a file name */
	}
	return opts.fileUrl(decoded) + (query ?? '');
};

const looksLikeYaml = (text: string) => {
	const lines = text.split('\n').filter((l) => l.trim() && !l.trim().startsWith('#'));
	if (lines.length < 3) return false;
	if (/^\s*(#{1,6}\s|[-*]\s+\S.*[.。]$|>|\|)/m.test(text) && !/^\s*[\w.-]+:\s*$/m.test(text))
		return false;
	const keyed = lines.filter((l) => /^\s*(- )?[\w.-]+:(\s|$)/.test(l)).length;
	return keyed / lines.length >= 0.6;
};

/**
 * Make an agent's report renderable whatever shape it came in: a whole-JSON or YAML reply
 * becomes a code block; workspace paths in links / images point at the workspace file route;
 * a bare image URL or a known image file on its own line becomes an image. Fenced code is left
 * untouched.
 */
export const prepareReport = (
	text: string,
	opts: { workspace?: string | null; fileUrl: (path: string) => string; files?: string[] }
): string => {
	const src = (text ?? '').replace(/\r\n?/g, '\n').trim();
	if (!src) return '';
	if (/^[[{]/.test(src)) {
		try {
			return '```json\n' + JSON.stringify(JSON.parse(src), null, 2) + '\n```';
		} catch {
			/* not JSON: fall through */
		}
	}
	if (!src.includes('```') && looksLikeYaml(src)) return '```yaml\n' + src + '\n```';
	const known = new Set(opts.files ?? []);
	const ws = (opts.workspace ?? '').replace(/\/+$/, '');
	let fence: string | null = null;
	const out: string[] = [];
	for (const line of src.split('\n')) {
		const marker = line.match(/^\s*(`{3,}|~{3,})/);
		if (marker) {
			if (fence === null) fence = marker[1][0];
			else if (marker[1][0] === fence) fence = null;
			out.push(line);
			continue;
		}
		if (fence !== null) {
			out.push(line);
			continue;
		}
		const bare = line.trim();
		if (/^https?:\/\/\S+$/i.test(bare) && isImagePath(bare)) {
			out.push(`![](${bare})`);
			continue;
		}
		const local = bare.replace(/^`|`$/g, '');
		const rel = ws && local.startsWith(ws + '/') ? local.slice(ws.length + 1) : local;
		if (rel && known.has(rel) && isImagePath(rel) && !/\s/.test(rel)) {
			out.push(`![${rel}](${opts.fileUrl(rel)})`);
			continue;
		}
		out.push(
			line.replace(
				/(!?\[[^\]]*\]\()(\s*<?[^)\s>]+>?)((?:\s+"[^"]*")?\))/g,
				(_m, head, href, tail) => {
					return head + reportHref(href, opts) + tail;
				}
			)
		);
	}
	return out.join('\n');
};

export const formatBytes = (n: number) => {
	if (!Number.isFinite(n) || n < 0) return '';
	if (n < 1024) return `${n} B`;
	if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
	return `${(n / 1024 / 1024).toFixed(1)} MB`;
};

export const formatStamp = (ts: number | null | undefined) => {
	if (!ts) return '';
	const d = new Date(ts * 1000);
	const today = new Date();
	const sameDay = d.toDateString() === today.toDateString();
	return sameDay
		? d.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' })
		: d.toLocaleString('zh-CN', {
				hour12: false,
				month: 'numeric',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
};

/** A runner's display name ("Hermes" for the native agent, the command name otherwise). */
export const runnerLabel = (name: string | null | undefined) =>
	name === 'hermes' ? 'Hermes' : (name ?? '');
