/**
 * Pure narrative & swimlane engine for 协作台 (/teams).
 *
 * Transforms the flat `TeamEvent[]` stream + `LiveTask[]` snapshot into:
 * 1. `buildStages()` — dependency-layer / phase segments for the top colored stage progress bar.
 * 2. `groupNarrative()` — chronological narrative items with collapsed tool/subagent step groups,
 *    semantic badges (handoff, approval, fail, retry, runner, milestone, deploy), durations & files.
 * 3. `layoutSwimlanes()` — Git-graph-style vertical member lanes, evenly spaced nodes, and
 *    cross-lane Bézier edges (handoff, user/lead steer, fail→retry loopback, merge convergence).
 *
 * Pure TypeScript (no Svelte / DOM): consumes `shownEvents` so `ReplayBar` playback naturally
 * grows both the narrative stream and swimlane graph step by step.
 */
import type { LiveTask, TeamDeployState, TeamEvent } from '$lib/apis/teams';
import {
	deliveryAt,
	plainPreview,
	RUNNER_EVENT_LABEL,
	statusLabel,
	taskDepths,
	type Delivery,
	type TaskState
} from './model';

export const LEAD_LANE_ID = '__lead__';
export const SWIMLANE_HEADER_HEIGHT = 44;

export type NarrativeKind =
	| 'message'
	| 'handoff'
	| 'tool_group'
	| 'approval'
	| 'fail'
	| 'retry'
	| 'runner'
	| 'milestone'
	| 'deploy'
	| 'status';

export type LanePalette = {
	hue: number;
	/** Primary stroke / dot color (CSS color string, light + dark safe). */
	stroke: string;
	/** Soft tinted background. */
	soft: string;
	/** Border tint. */
	border: string;
};

const MEMBER_HUES = [194, 262, 158, 34, 344, 210, 22, 174];

const hashString = (value: string): number => {
	let h = 2166136261;
	for (let i = 0; i < value.length; i++) {
		h ^= value.charCodeAt(i);
		h = Math.imul(h, 16777619);
	}
	return Math.abs(h);
};

/** Deterministic, light+dark legible Starcore color palette per lane. */
export const lanePalette = (laneId: string, laneIndex: number): LanePalette => {
	if (laneId === LEAD_LANE_ID || laneIndex === 0) {
		return {
			hue: 227,
			stroke: 'hsl(var(--tm-accent))',
			soft: 'hsl(var(--tm-accent) / 0.12)',
			border: 'hsl(var(--tm-accent) / 0.35)'
		};
	}
	const idx = laneIndex - 1;
	const hue =
		idx >= 0 && idx < MEMBER_HUES.length
			? MEMBER_HUES[idx]
			: (hashString(laneId) * 47) % 360;
	return {
		hue,
		stroke: `hsl(${hue} 78% 50%)`,
		soft: `hsl(${hue} 78% 50% / 0.12)`,
		border: `hsl(${hue} 78% 50% / 0.34)`
	};
};

// --- stages (top colored bar + stage filter pills) ---------------------------------------------

export type StageSegment = {
	id: string;
	index: number;
	label: string;
	shortLabel: string;
	taskIds: string[];
	taskKeys: string[];
	done: number;
	total: number;
	status: 'done' | 'running' | 'attention' | 'pending';
	hue: number;
	color: string;
	weight: number;
};

const STAGE_HUES = [222, 194, 262, 158, 34, 344];

export const buildStages = (
	tasks: Pick<LiveTask, 'id' | 'key' | 'seq' | 'title' | 'parents'>[],
	states: Map<string, TaskState>,
	deploy?: TeamDeployState | null
): StageSegment[] => {
	if (!tasks.length && !deploy?.steps?.length) return [];
	const depths = taskDepths(tasks);
	const byDepth = new Map<number, typeof tasks>();
	const sorted = [...tasks].sort(
		(a, b) => (a.seq ?? 0) - (b.seq ?? 0) || a.key.localeCompare(b.key, 'en', { numeric: true })
	);
	for (const t of sorted) {
		const d = depths.get(t.id) ?? 0;
		const list = byDepth.get(d) ?? [];
		list.push(t);
		byDepth.set(d, list);
	}
	const maxDepth = byDepth.size ? Math.max(...byDepth.keys()) : -1;
	const segments: StageSegment[] = [];
	for (let d = 0; d <= maxDepth; d++) {
		const list = byDepth.get(d) ?? [];
		if (!list.length) continue;
		let done = 0;
		let running = 0;
		let attention = 0;
		for (const t of list) {
			const s = states.get(t.id);
			if (s?.status === 'done' || s?.status === 'archived') done++;
			else if (s?.sub_status === 'running' || s?.sub_status === 'review') running++;
			else if (['failed', 'blocked', 'waiting_user', 'stopped', 'triage'].includes(s?.sub_status ?? ''))
				attention++;
		}
		const status: StageSegment['status'] =
			attention > 0
				? 'attention'
				: running > 0
					? 'running'
					: done === list.length
						? 'done'
						: 'pending';
		const firstTitle = list[0]?.title ?? '';
		const concise = firstTitle.length > 10 ? `${firstTitle.slice(0, 10)}…` : firstTitle;
		const shortLabel =
			list.length === 1 ? `第${d + 1}步 · ${concise || `#${list[0].key}`}` : `第${d + 1}步 · ${list.length}并行`;
		const label =
			list.length === 1
				? `第 ${d + 1} 步 · #${list[0].key} ${firstTitle}`
				: `第 ${d + 1} 步 · ${list.map((t) => `#${t.key}`).join(' / ')}`;
		const hue = STAGE_HUES[d % STAGE_HUES.length];
		segments.push({
			id: `layer-${d}`,
			index: d,
			label,
			shortLabel,
			taskIds: list.map((t) => t.id),
			taskKeys: list.map((t) => t.key),
			done,
			total: list.length,
			status,
			hue,
			color: `hsl(${hue} 78% 52%)`,
			weight: Math.max(1, list.length)
		});
	}

	if (deploy?.steps?.length) {
		const activeSteps = deploy.steps.filter((s) => s.status !== 'skipped');
		const doneSteps = activeSteps.filter((s) => s.status === 'done').length;
		const status: StageSegment['status'] =
			deploy.status === 'failed'
				? 'attention'
				: deploy.status === 'running'
					? 'running'
					: deploy.status === 'succeeded'
						? 'done'
						: 'pending';
		segments.push({
			id: 'deploy',
			index: segments.length,
			label: '审查与部署',
			shortLabel: '审查与部署',
			taskIds: [],
			taskKeys: [],
			done: doneSteps,
			total: Math.max(1, activeSteps.length),
			status,
			hue: 158,
			color: 'hsl(var(--tm-ok))',
			weight: 1
		});
	}
	return segments;
};

// --- artifact extraction & tool summarization --------------------------------------------------

const FILE_TOKEN_RE =
	/(?:^|[\s`"'(\[])((?:[\w.-]+\/)*[\w.-]+\.(?:ts|tsx|js|mjs|cjs|svelte|py|md|json|yaml|yml|css|html|sh|sql|png|jpe?g|webp|gif|svg|mp4|mp3|wav|pdf|csv|txt|log))(?=$|[\s`"'),:;\]])/gi;

/** Extract distinct workspace-like filenames mentioned in tool output / handoff text. */
export const extractArtifacts = (text: string, limit = 4): string[] => {
	if (!text) return [];
	const found: string[] = [];
	const seen = new Set<string>();
	let m: RegExpExecArray | null;
	FILE_TOKEN_RE.lastIndex = 0;
	while ((m = FILE_TOKEN_RE.exec(text)) !== null) {
		const raw = m[1].replace(/^\.\//, '');
		if (!raw || raw.startsWith('http') || seen.has(raw)) continue;
		seen.add(raw);
		found.push(raw);
		if (found.length >= limit) break;
	}
	return found;
};

export type ToolIcon = 'search' | 'edit' | 'terminal' | 'image' | 'subagent' | 'generic';

const TOOL_GROUP_TITLES: [RegExp, string, ToolIcon][] = [
	[
		/^(read_file|view_file|cat|grep|search|glob|find|rg|halo-search|web_search)/i,
		'检索与阅读',
		'search'
	],
	[/^(write_file|edit_file|replace|patch|create_file|apply_patch)/i, '编写与修改', 'edit'],
	[/^(terminal|bash|shell|exec|run_command|execute_code)/i, '命令与验证', 'terminal'],
	[/^(image|draw|generate_image|illustrate)/i, '生成视觉产物', 'image']
];

const summarizeToolGroup = (
	steps: TeamEvent[]
): { badge: string; title: string; files: string[]; toolIcon: ToolIcon } => {
	const counts = new Map<string, number>();
	const files: string[] = [];
	const seenFiles = new Set<string>();
	let subagents = 0;
	for (const ev of steps) {
		if (ev.type === 'subagent') {
			subagents++;
		} else {
			const name = String(ev.data?.name ?? 'tool').trim() || 'tool';
			counts.set(name, (counts.get(name) ?? 0) + 1);
		}
		for (const f of extractArtifacts(ev.text ?? '', 3)) {
			if (!seenFiles.has(f) && files.length < 4) {
				seenFiles.add(f);
				files.push(f);
			}
		}
	}
	if (subagents > 0 && counts.size === 0) {
		return {
			badge: '子代理',
			toolIcon: 'subagent',
			title:
				subagents === 1
					? steps[0].data?.phase === 'start'
						? '派出子代理'
						: '子代理完成'
					: `子代理协作 · ${subagents} 步`,
			files
		};
	}
	const topTools = [...counts.entries()].sort((a, b) => b[1] - a[1]);
	const primary = topTools[0]?.[0] ?? '工具';
	const [, category = '执行步骤', toolIcon = 'generic'] =
		TOOL_GROUP_TITLES.find(([pattern]) => pattern.test(primary)) ?? [];
	const firstText = (steps[0]?.text ?? '').replace(/\s+/g, ' ').trim();
	const title =
		steps.length === 1
			? `${primary}${firstText ? ` · ${firstText.slice(0, 64)}` : ''}`
			: files.length
				? `${category} · ${files[0]}${files.length > 1 ? ` 等 ${files.length} 个文件` : ''}`
				: `${category} · ${topTools
						.slice(0, 2)
						.map(([k, n]) => (n > 1 ? `${k}×${n}` : k))
						.join('、')}`;
	return { badge: category, title, files, toolIcon };
};

// --- narrative grouping ------------------------------------------------------------------------

export type HandoffTarget = { task_id?: string; key?: string; member: string };

export type NarrativeItem = {
	id: string;
	seq: number;
	endSeq: number;
	ts: number;
	endTs: number;
	durationSec: number;
	stepCount: number;
	/** Lane key: member name, or LEAD_LANE_ID for lead/team/deploy events. */
	lane: string;
	member: string | null;
	who?: TeamEvent['who'];
	author?: string;
	taskId: string | null;
	taskKey: string | null;
	stageId: string;
	kind: NarrativeKind;
	badge: string;
	title: string;
	body: string;
	files: string[];
	handoffTo: HandoffTarget[];
	/** Target member lane for user/lead messages directed at a member. */
	targetLane: string | null;
	/** Runner name / transition summary for runner & retry events. */
	runnerMeta: string;
	delivery: Delivery | null;
	steps: TeamEvent[];
	toolIcon?: ToolIcon;
	sourceEvent: TeamEvent | null;
	/** True when this item is actionable in live view (e.g. waiting_user question or failed task). */
	actionable?: 'reply' | 'retry' | null;
};

export type GroupNarrativeOptions = {
	cursorSeq?: number | null;
	deploy?: TeamDeployState | null;
	includeDeploy?: boolean;
};

const DEPLOY_STEP_STATUS_LABEL: Record<string, string> = {
	done: '完成',
	running: '进行中',
	failed: '失败',
	skipped: '跳过',
	pending: '待执行'
};

/**
 * Fold raw chronological `TeamEvent[]` into structured `NarrativeItem[]`.
 * Always returns ascending chronological order; callers can reverse for newest-first if desired.
 */
export const groupNarrative = (
	events: TeamEvent[],
	tasks: Pick<LiveTask, 'id' | 'key' | 'parents' | 'member'>[] = [],
	options: GroupNarrativeOptions = {}
): NarrativeItem[] => {
	const cursorSeq = options.cursorSeq ?? null;
	const depths = taskDepths(tasks);
	const taskById = new Map(tasks.map((t) => [t.id, t]));
	const stageOfTask = (taskId: string | null): string => {
		if (!taskId) return 'layer-0';
		const d = depths.get(taskId);
		return d === undefined ? 'layer-0' : `layer-${d}`;
	};

	// Track which seqs are messages so redundant standalone delivery events can stay quiet.
	const messageDeliveredSeqs = new Set<number>();
	for (const ev of events) {
		if (ev.type === 'message' && typeof ev.data?.delivered_seq === 'number') {
			messageDeliveredSeqs.add(ev.data.delivered_seq);
		}
	}

	const items: NarrativeItem[] = [];
	const failedTasks = new Set<string>();
	let toolBuf: TeamEvent[] = [];

	const flushTools = () => {
		if (!toolBuf.length) return;
		const first = toolBuf[0];
		const last = toolBuf[toolBuf.length - 1];
		const summary = summarizeToolGroup(toolBuf);
		const member = first.member || (first.task_id ? taskById.get(first.task_id)?.member ?? null : null);
		items.push({
			id: `tg-${first.id}`,
			seq: first.seq,
			endSeq: last.seq,
			ts: first.ts,
			endTs: last.ts,
			durationSec: Math.max(0, Math.round((last.ts || 0) - (first.ts || 0))),
			stepCount: toolBuf.length,
			lane: member || LEAD_LANE_ID,
			member,
			taskId: first.task_id,
			taskKey: first.key ?? (first.task_id ? taskById.get(first.task_id)?.key ?? null : null),
			stageId: stageOfTask(first.task_id),
			kind: 'tool_group',
			badge: summary.badge,
			toolIcon: summary.toolIcon,
			title: summary.title,
			body: '',
			files: summary.files,
			handoffTo: [],
			targetLane: null,
			runnerMeta: '',
			delivery: null,
			steps: [...toolBuf],
			sourceEvent: first
		});
		toolBuf = [];
	};

	const canAppendTool = (ev: TeamEvent): boolean => {
		if (!toolBuf.length) return false;
		const prev = toolBuf[toolBuf.length - 1];
		return (
			(prev.member ?? '') === (ev.member ?? '') &&
			(prev.task_id ?? '') === (ev.task_id ?? '')
		);
	};

	for (const ev of events) {
		if (ev.type === 'tool' || ev.type === 'subagent') {
			if (!canAppendTool(ev)) flushTools();
			toolBuf.push(ev);
			continue;
		}
		flushTools();

		// Skip redundant delivery event when its parent message already carries the delivery pill.
		if (ev.type === 'delivery' && messageDeliveredSeqs.has(ev.seq)) continue;

		const member = ev.member || (ev.task_id ? taskById.get(ev.task_id)?.member ?? null : null);
		const taskKey = ev.key ?? (ev.task_id ? taskById.get(ev.task_id)?.key ?? null : null);
		const stageId = stageOfTask(ev.task_id);
		const rawText = (ev.text ?? '').trim();
		const plain = plainPreview(rawText);
		const files = extractArtifacts(rawText, 4);

		if (ev.type === 'handoff') {
			const targets: HandoffTarget[] = Array.isArray(ev.data?.to)
				? ev.data.to
						.filter((t: any) => t && t.member)
						.map((t: any) => ({ task_id: t.task_id, key: t.key, member: String(t.member) }))
				: [];
			const toText = targets.length
				? targets.map((t) => `${t.member}${t.key ? `(#${t.key})` : ''}`).join('、')
				: '下一阶段';
			items.push({
				id: `ev-${ev.id}`,
				seq: ev.seq,
				endSeq: ev.seq,
				ts: ev.ts,
				endTs: ev.ts,
				durationSec: 0,
				stepCount: 1,
				lane: member || LEAD_LANE_ID,
				member,
				taskId: ev.task_id,
				taskKey,
				stageId,
				kind: 'handoff',
				badge: '交接',
				title: `交接 → ${toText}`,
				body: plain,
				files,
				handoffTo: targets,
				targetLane: null,
				runnerMeta: '',
				delivery: null,
				steps: [],
				sourceEvent: ev
			});
			continue;
		}

		if (ev.type === 'message') {
			const isUser = ev.who === 'user';
			const isLead = ev.who === 'lead';
			const lane = isUser || isLead ? LEAD_LANE_ID : member || LEAD_LANE_ID;
			const targetLane = (isUser || isLead) && member ? member : null;
			const title = isUser
				? `${ev.author ?? '你'} → ${member ?? '团队'}`
				: isLead
					? `负责人 → ${member ?? '团队'}`
					: `${member ?? ev.author ?? '成员'} 发言`;
			items.push({
				id: `ev-${ev.id}`,
				seq: ev.seq,
				endSeq: ev.seq,
				ts: ev.ts,
				endTs: ev.ts,
				durationSec: 0,
				stepCount: 1,
				lane,
				member,
				who: ev.who,
				author: ev.author,
				taskId: ev.task_id,
				taskKey,
				stageId,
				kind: 'message',
				badge: isUser ? '指令' : isLead ? '协调' : '发言',
				title,
				body: plain || rawText,
				files,
				handoffTo: [],
				targetLane,
				runnerMeta: '',
				delivery: deliveryAt(ev, cursorSeq),
				steps: [],
				sourceEvent: ev
			});
			continue;
		}

		const isApproval =
			ev.sub_status === 'waiting_user' ||
			ev.status === 'triage' ||
			(ev.type === 'runner' && ev.data?.phase === 'question');
		if (isApproval) {
			items.push({
				id: `ev-${ev.id}`,
				seq: ev.seq,
				endSeq: ev.seq,
				ts: ev.ts,
				endTs: ev.ts,
				durationSec: 0,
				stepCount: 1,
				lane: member || LEAD_LANE_ID,
				member,
				taskId: ev.task_id,
				taskKey,
				stageId,
				kind: 'approval',
				badge: '待确认',
				title: `${member ?? '成员'} 等你回复`,
				body: plain || rawText || '需要你的指示才能继续',
				files,
				handoffTo: [],
				targetLane: null,
				runnerMeta: ev.data?.runner ? String(ev.data.runner) : '',
				delivery: null,
				steps: [],
				sourceEvent: ev,
				actionable: 'reply'
			});
			continue;
		}

		const isFail =
			['failed', 'blocked'].includes(ev.sub_status ?? '') ||
			(ev.type === 'runner' && ev.data?.phase === 'failed');
		if (isFail) {
			if (ev.task_id) failedTasks.add(ev.task_id);
			items.push({
				id: `ev-${ev.id}`,
				seq: ev.seq,
				endSeq: ev.seq,
				ts: ev.ts,
				endTs: ev.ts,
				durationSec: 0,
				stepCount: 1,
				lane: member || LEAD_LANE_ID,
				member,
				taskId: ev.task_id,
				taskKey,
				stageId,
				kind: 'fail',
				badge: ev.sub_status === 'blocked' ? '受阻' : '失败',
				title: `${member ?? '任务'} ${ev.sub_status === 'blocked' ? '执行受阻' : '执行失败'}`,
				body: plain || rawText || statusLabel(ev.sub_status),
				files,
				handoffTo: [],
				targetLane: null,
				runnerMeta: ev.data?.runner ? String(ev.data.runner) : '',
				delivery: null,
				steps: [],
				sourceEvent: ev,
				actionable: 'retry'
			});
			continue;
		}

		if (ev.type === 'runner') {
			const phase = String(ev.data?.phase ?? '');
			const runner = String(ev.data?.runner ?? 'runner');
			const isRetry = phase === 'continued' || phase === 'fallback';
			const phaseLabel = RUNNER_EVENT_LABEL[phase] ?? (phase || '运行事件');
			items.push({
				id: `ev-${ev.id}`,
				seq: ev.seq,
				endSeq: ev.seq,
				ts: ev.ts,
				endTs: ev.ts,
				durationSec: 0,
				stepCount: 1,
				lane: member || LEAD_LANE_ID,
				member,
				taskId: ev.task_id,
				taskKey,
				stageId,
				kind: isRetry ? 'retry' : 'runner',
				badge: phase === 'fallback' ? '改派' : phase === 'quota_wait' ? '额度等待' : phaseLabel,
				title: `${runner} · ${phaseLabel}`,
				body: plain || rawText,
				files,
				handoffTo: [],
				targetLane: null,
				runnerMeta: runner,
				delivery: null,
				steps: [],
				sourceEvent: ev
			});
			continue;
		}

		if (ev.type === 'attempt') {
			const attemptNumMatch = rawText.match(/第\s*(\d+)\s*次/);
			const attemptNum = attemptNumMatch ? Number(attemptNumMatch[1]) : 1;
			const isRetry = attemptNum > 1 || (!!ev.task_id && failedTasks.has(ev.task_id));
			items.push({
				id: `ev-${ev.id}`,
				seq: ev.seq,
				endSeq: ev.seq,
				ts: ev.ts,
				endTs: ev.ts,
				durationSec: 0,
				stepCount: 1,
				lane: member || LEAD_LANE_ID,
				member,
				taskId: ev.task_id,
				taskKey,
				stageId,
				kind: isRetry ? 'retry' : 'status',
				badge: isRetry ? '重跑' : '开始',
				title: rawText || `${member ?? '成员'} 开始执行`,
				body: '',
				files,
				handoffTo: [],
				targetLane: null,
				runnerMeta: '',
				delivery: null,
				steps: [],
				sourceEvent: ev
			});
			continue;
		}

		if (ev.type === 'team') {
			items.push({
				id: `ev-${ev.id}`,
				seq: ev.seq,
				endSeq: ev.seq,
				ts: ev.ts,
				endTs: ev.ts,
				durationSec: 0,
				stepCount: 1,
				lane: LEAD_LANE_ID,
				member: null,
				taskId: ev.task_id,
				taskKey,
				stageId,
				kind: 'milestone',
				badge: '里程碑',
				title: rawText || '团队状态更新',
				body: '',
				files,
				handoffTo: [],
				targetLane: null,
				runnerMeta: '',
				delivery: null,
				steps: [],
				sourceEvent: ev
			});
			continue;
		}

		// status / remaining delivery
		items.push({
			id: `ev-${ev.id}`,
			seq: ev.seq,
			endSeq: ev.seq,
			ts: ev.ts,
			endTs: ev.ts,
			durationSec: 0,
			stepCount: 1,
			lane: member || LEAD_LANE_ID,
			member,
			taskId: ev.task_id,
			taskKey,
			stageId,
			kind: 'status',
			badge: ev.sub_status ? statusLabel(ev.sub_status) : '状态',
			title: rawText || (ev.sub_status ? `${member ?? ''} ${statusLabel(ev.sub_status)}`.trim() : '状态更新'),
			body: '',
			files,
			handoffTo: [],
			targetLane: null,
			runnerMeta: '',
			delivery: null,
			steps: [],
			sourceEvent: ev
		});
	}
	flushTools();

	// Append deploy pipeline milestones in live mode (merge → main, push, CI, deploy, cleanup).
	if (options.includeDeploy && options.deploy?.steps?.length) {
		const baseSeq = (items[items.length - 1]?.endSeq ?? 0) + 1;
		options.deploy.steps.forEach((step, idx) => {
			if (step.status === 'pending' || step.status === 'skipped') return;
			items.push({
				id: `deploy-${step.key}-${idx}`,
				seq: baseSeq + idx,
				endSeq: baseSeq + idx,
				ts: step.at ?? options.deploy?.started_at ?? 0,
				endTs: step.at ?? options.deploy?.started_at ?? 0,
				durationSec: 0,
				stepCount: 1,
				lane: LEAD_LANE_ID,
				member: null,
				taskId: null,
				taskKey: null,
				stageId: 'deploy',
				kind: step.status === 'failed' ? 'fail' : 'deploy',
				badge: step.key === 'merge' ? '合并' : step.key === 'review' ? '审查' : '部署',
				title: `${step.label} · ${DEPLOY_STEP_STATUS_LABEL[step.status] ?? step.status}`,
				body: step.detail ?? '',
				files: [],
				handoffTo: [],
				targetLane: null,
				runnerMeta: options.deploy?.sha ? options.deploy.sha.slice(0, 7) : '',
				delivery: null,
				steps: [],
				sourceEvent: null
			});
		});
	}

	return items;
};

// --- swimlane graph layout ---------------------------------------------------------------------

export type SwimlaneLane = {
	id: string;
	name: string;
	role: string;
	index: number;
	x: number;
	palette: LanePalette;
	firstRow: number | null;
	lastRow: number | null;
	nodeCount: number;
};

export type SwimlaneNode = {
	id: string;
	itemId: string;
	seq: number;
	row: number;
	laneIndex: number;
	laneId: string;
	x: number;
	y: number;
	kind: NarrativeKind;
	label: string;
	sublabel: string;
	color: string;
	taskId: string | null;
	taskKey: string | null;
	stageId: string;
	isHead: boolean;
	stepCount: number;
	fullTitle: string;
	memberName: string;
	durationSec: number;
	files: string[];
	badge: string;
};

export type SwimlaneEdgeKind = 'handoff' | 'steer' | 'retry' | 'merge';

export type SwimlaneEdge = {
	id: string;
	kind: SwimlaneEdgeKind;
	fromNodeId: string;
	toNodeId: string | null;
	fromX: number;
	fromY: number;
	toX: number;
	toY: number;
	color: string;
	dashed: boolean;
	compact: boolean;
	label?: string;
};

export type SwimlaneLayout = {
	lanes: SwimlaneLane[];
	nodes: SwimlaneNode[];
	edges: SwimlaneEdge[];
	stageBands: SwimlaneStageBand[];
	width: number;
	height: number;
	rowHeight: number;
	topPad: number;
	laneWidth: number;
};

export type SwimlaneStageBand = {
	id: string;
	stageId: string;
	label: string;
	color: string;
	startRow: number;
	endRow: number;
	topY: number;
	bottomY: number;
};

const MAX_EDGE_SPAN_ROWS = 10;

const nodeColorForKind = (kind: NarrativeKind, laneStroke: string): string => {
	switch (kind) {
		case 'fail':
			return 'hsl(var(--tm-bad))';
		case 'approval':
			return 'hsl(var(--tm-violet))';
		case 'retry':
			return 'hsl(var(--tm-warn))';
		case 'deploy':
			return 'hsl(var(--tm-ok))';
		case 'milestone':
			return 'hsl(var(--tm-accent))';
		default:
			return laneStroke;
	}
};

const shortNodeLabel = (item: NarrativeItem): string => {
	if (item.kind === 'tool_group') {
		if (item.files.length) {
			return item.files[0].split('/').pop() ?? item.files[0];
		}
		return `${item.badge} ×${item.stepCount}`;
	}
	if (item.kind === 'handoff') {
		const first = item.handoffTo[0];
		return first ? `→ ${first.member}` : '交接';
	}
	if (item.kind === 'approval') return '等你回复';
	if (item.kind === 'fail') return item.badge;
	if (item.kind === 'retry') return item.badge;
	if (item.kind === 'deploy') return item.title.split('·')[0].trim();
	if (item.kind === 'message') {
		if (item.who === 'user') return '指令';
		if (item.who === 'lead') return '协调';
		return item.taskKey ? `#${item.taskKey} 发言` : '发言';
	}
	return item.title.replace(/^#\S+\s*/, '');
};

// Budget both the text and its SVG background in the same units. Leave room for an ellipsis.
export const fitSwimlaneLabel = (
	text: string,
	maxWidth: number
): { text: string; width: number } => {
	const chars = Array.from(text);
	const widths = chars.map((char) => (/^[\x00-\x7f]$/.test(char) ? 7 : 11));
	const maxChars = chars.some((char, i) => widths[i] === 11 && char !== '…') ? 6 : 10;
	if (chars.length <= maxChars) {
		const width = widths.reduce((total, next) => total + next, 0);
		if (width <= maxWidth) return { text, width };
	}
	const ellipsisWidth = 11;
	if (maxWidth < ellipsisWidth) return { text: '', width: 0 };
	let width = 0;
	let count = 0;
	while (count < Math.min(chars.length, maxChars - 1)) {
		if (width + widths[count] + ellipsisWidth > maxWidth) break;
		width += widths[count++];
	}
	return { text: `${chars.slice(0, count).join('')}…`, width: width + ellipsisWidth };
};

export const layoutSwimlanes = (
	items: NarrativeItem[],
	members: { name: string; role?: string }[],
	options: {
		leadName?: string;
		laneWidth?: number;
		rowHeight?: number;
		stages?: StageSegment[];
	} = {}
): SwimlaneLayout => {
	const rowHeight = options.rowHeight ?? 52;
	const topPad = 30;
	const bottomPad = 36;

	// Build ordered lane list: Lane 0 = lead/team, then planned members, then any unplanned members.
	const laneOrder: { id: string; name: string; role: string }[] = [
		{ id: LEAD_LANE_ID, name: options.leadName || '负责人', role: '统筹 / 系统' }
	];
	const seen = new Set<string>([LEAD_LANE_ID]);
	for (const m of members) {
		if (!m.name || seen.has(m.name)) continue;
		seen.add(m.name);
		laneOrder.push({ id: m.name, name: m.name, role: m.role ?? '成员' });
	}
	for (const item of items) {
		if (item.lane && !seen.has(item.lane)) {
			seen.add(item.lane);
			laneOrder.push({ id: item.lane, name: item.lane, role: '成员' });
		}
		for (const target of item.handoffTo) {
			if (target.member && !seen.has(target.member)) {
				seen.add(target.member);
				laneOrder.push({ id: target.member, name: target.member, role: '成员' });
			}
		}
		if (item.targetLane && !seen.has(item.targetLane)) {
			seen.add(item.targetLane);
			laneOrder.push({ id: item.targetLane, name: item.targetLane, role: '成员' });
		}
	}

	const laneWidth = options.laneWidth ?? (laneOrder.length <= 4 ? 112 : 96);
	const laneSpan = (laneOrder.length - 1) * laneWidth;
	const width = Math.max(240, laneSpan + laneWidth + 16);
	const leftPad = (width - laneSpan) / 2;
	const lanes: SwimlaneLane[] = laneOrder.map((entry, index) => ({
		...entry,
		index,
		x: leftPad + index * laneWidth,
		palette: lanePalette(entry.id, index),
		firstRow: null,
		lastRow: null,
		nodeCount: 0
	}));
	const laneMap = new Map(lanes.map((l) => [l.id, l]));

	const nodes: SwimlaneNode[] = items.map((item, row) => {
		const lane = laneMap.get(item.lane) ?? lanes[0];
		if (lane.firstRow === null) lane.firstRow = row;
		lane.lastRow = row;
		lane.nodeCount++;
		const color = nodeColorForKind(item.kind, lane.palette.stroke);
		return {
			id: item.id,
			itemId: item.id,
			seq: item.seq,
			row,
			laneIndex: lane.index,
			laneId: lane.id,
			x: lane.x,
			y: topPad + row * rowHeight,
			kind: item.kind,
			label: fitSwimlaneLabel(shortNodeLabel(item), Math.max(0, laneWidth - 34)).text,
			sublabel: item.taskKey ? `#${item.taskKey}` : item.runnerMeta || '',
			color,
			taskId: item.taskId,
			taskKey: item.taskKey,
			stageId: item.stageId,
			isHead: row === items.length - 1,
			stepCount: item.stepCount,
			fullTitle: item.title,
			memberName: item.member ?? lane.name,
			durationSec: item.durationSec,
			files: item.files,
			badge: item.badge
		};
	});

	// Build edges (handoff, steer, retry loopback, merge convergence).
	const edges: SwimlaneEdge[] = [];
	const lastFailByTask = new Map<string, SwimlaneNode>();
	const lastNodeByLane = new Map<string, SwimlaneNode>();

	for (let i = 0; i < items.length; i++) {
		const item = items[i];
		const node = nodes[i];

		if (item.kind === 'fail' && item.taskId) {
			lastFailByTask.set(item.taskId, node);
		}

		// Retry / runner fallback edge pointing from last failure of same task.
		if (item.kind === 'retry' && item.taskId && lastFailByTask.has(item.taskId)) {
			const failNode = lastFailByTask.get(item.taskId)!;
			const span = node.row - failNode.row;
			edges.push({
				id: `retry-${failNode.id}-${node.id}`,
				kind: 'retry',
				fromNodeId: failNode.id,
				toNodeId: node.id,
				fromX: failNode.x,
				fromY: failNode.y,
				toX: node.x,
				toY: node.y,
				color: 'hsl(var(--tm-warn))',
				dashed: true,
				compact: span > MAX_EDGE_SPAN_ROWS,
				label: item.badge
			});
		}

		// Handoff cross-lane edges to each downstream target member.
		if (item.kind === 'handoff' && item.handoffTo.length) {
			for (const target of item.handoffTo) {
				const targetLane = laneMap.get(target.member);
				if (!targetLane || targetLane.id === node.laneId) continue;
				// Find next node on targetLane (preferring matching task_id) after row i.
				let nextNode: SwimlaneNode | null = null;
				for (let j = i + 1; j < nodes.length; j++) {
					if (nodes[j].laneId !== targetLane.id) continue;
					if (target.task_id && nodes[j].taskId === target.task_id) {
						nextNode = nodes[j];
						break;
					}
					if (!nextNode) nextNode = nodes[j];
				}
				const toRow = nextNode ? nextNode.row : Math.min(items.length - 0.35, i + 0.85);
				const span = toRow - i;
				const compact = span > MAX_EDGE_SPAN_ROWS;
				edges.push({
					id: `ho-${node.id}-${targetLane.id}-${target.key ?? ''}`,
					kind: 'handoff',
					fromNodeId: node.id,
					toNodeId: nextNode?.id ?? null,
					fromX: node.x,
					fromY: node.y,
					toX: targetLane.x,
					toY: compact ? node.y + rowHeight * 1.4 : nextNode ? nextNode.y : topPad + toRow * rowHeight,
					color: targetLane.palette.stroke,
					dashed: !nextNode,
					compact,
					label: target.key ? `#${target.key}` : undefined
				});
			}
		}

		// User / lead steer arrows directed to a member lane.
		if (item.kind === 'message' && item.targetLane && item.targetLane !== node.laneId) {
			const targetLane = laneMap.get(item.targetLane);
			if (targetLane) {
				let nextNode: SwimlaneNode | null = null;
				for (let j = i + 1; j < nodes.length; j++) {
					if (nodes[j].laneId === targetLane.id) {
						nextNode = nodes[j];
						break;
					}
				}
				const span = nextNode ? nextNode.row - i : 1;
				const compact = span > MAX_EDGE_SPAN_ROWS;
				edges.push({
					id: `steer-${node.id}-${targetLane.id}`,
					kind: 'steer',
					fromNodeId: node.id,
					toNodeId: nextNode?.id ?? null,
					fromX: node.x,
					fromY: node.y,
					toX: targetLane.x,
					toY: compact
						? node.y + rowHeight * 1.15
						: nextNode
							? nextNode.y
							: node.y + rowHeight * 0.75,
					color: item.who === 'user' ? 'hsl(var(--tm-violet))' : 'hsl(var(--tm-accent))',
					dashed: true,
					compact
				});
			}
		}

		// Merge / deploy convergence from member lanes back into Lane 0.
		if (item.kind === 'deploy' && item.badge === '合并') {
			for (const [lid, prev] of lastNodeByLane.entries()) {
				if (lid === LEAD_LANE_ID) continue;
				const span = node.row - prev.row;
				edges.push({
					id: `merge-${prev.id}-${node.id}`,
					kind: 'merge',
					fromNodeId: prev.id,
					toNodeId: node.id,
					fromX: prev.x,
					fromY: span > MAX_EDGE_SPAN_ROWS ? node.y - rowHeight * 1.5 : prev.y,
					toX: node.x,
					toY: node.y,
					color: 'hsl(var(--tm-ok))',
					dashed: false,
					compact: span > MAX_EDGE_SPAN_ROWS
				});
			}
		}

		lastNodeByLane.set(node.laneId, node);
	}

	const stageById = new Map(options.stages?.map((stage) => [stage.id, stage]));
	const stageBands: SwimlaneStageBand[] = [];
	for (const node of nodes) {
		const prev = stageBands[stageBands.length - 1];
		const bottomY = node.y + rowHeight / 2;
		if (prev?.stageId === node.stageId) {
			prev.endRow = node.row;
			prev.bottomY = bottomY;
			continue;
		}
		const stage = stageById.get(node.stageId);
		const layer = /^layer-(\d+)$/.exec(node.stageId);
		const hue = STAGE_HUES[layer ? Number(layer[1]) % STAGE_HUES.length : 0];
		stageBands.push({
			id: `${node.stageId}-${node.id}`,
			stageId: node.stageId,
			label:
				stage?.shortLabel ??
				(layer
					? `第${Number(layer[1]) + 1}步`
					: node.stageId === 'deploy'
						? '审查与部署'
						: node.stageId),
			color:
				stage?.color ?? (node.stageId === 'deploy' ? 'hsl(var(--tm-ok))' : `hsl(${hue} 78% 52%)`),
			startRow: node.row,
			endRow: node.row,
			topY: Math.max(0, node.y - rowHeight / 2),
			bottomY
		});
	}
	const height = Math.max(180, topPad + Math.max(1, nodes.length) * rowHeight + bottomPad);
	return { lanes, nodes, edges, stageBands, width, height, rowHeight, topPad, laneWidth };
};

export const connectedSwimlaneIds = (
	layout: SwimlaneLayout,
	focusId: string | null
): { nodeIds: Set<string>; edgeIds: Set<string> } => {
	const nodeIds = new Set<string>();
	const edgeIds = new Set<string>();
	if (focusId && layout.nodes.some((node) => node.id === focusId)) {
		nodeIds.add(focusId);
		for (const edge of layout.edges) {
			if (edge.fromNodeId !== focusId && edge.toNodeId !== focusId) continue;
			edgeIds.add(edge.id);
			nodeIds.add(edge.fromNodeId);
			if (edge.toNodeId) nodeIds.add(edge.toNodeId);
		}
	}
	return { nodeIds, edgeIds };
};

export const SWIMLANE_LEGEND: { kind: NarrativeKind; label: string; color: string }[] = [
	{ kind: 'status', label: '开始/状态', color: 'hsl(var(--tm-accent))' },
	{ kind: 'tool_group', label: '工具步骤', color: 'hsl(194 78% 50%)' },
	{ kind: 'handoff', label: '交接流转', color: 'hsl(158 70% 46%)' },
	{ kind: 'message', label: '对话指令', color: 'hsl(262 78% 60%)' },
	{ kind: 'approval', label: '等你回复', color: 'hsl(var(--tm-violet))' },
	{ kind: 'retry', label: '重跑/改派', color: 'hsl(var(--tm-warn))' },
	{ kind: 'fail', label: '失败/受阻', color: 'hsl(var(--tm-bad))' },
	{ kind: 'deploy', label: '合并/部署', color: 'hsl(var(--tm-ok))' },
	{ kind: 'milestone', label: '里程碑', color: 'hsl(var(--tm-accent))' }
];
