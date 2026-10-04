import type {
	AskStatus,
	DiscussAsk,
	DiscussMode,
	DiscussSeat,
	DiscussTurn,
	TurnStatus
} from '$lib/apis/discussions';

/** 讨论台: the formats, the seat colours and the reducer for the live events. */

export type ModeSpec = {
	value: DiscussMode;
	label: string;
	/** One line under the label. */
	hint: string;
	rounds: number;
	/** Fixed rounds (review: answer, then review). */
	fixedRounds?: boolean;
	/** Roles the first seats get when left empty (the backend fills the same). */
	roles: string[];
	/** What each round is called. */
	roundName: (round: number, total: number) => string;
};

export const MODES: ModeSpec[] = [
	{
		value: 'roundtable',
		label: '圆桌讨论',
		hint: '先各自作答，再互相补充、纠错',
		rounds: 2,
		roles: [],
		roundName: (r) => (r === 1 ? '各自作答' : '互相回应')
	},
	{
		value: 'debate',
		label: '正反辩论',
		hint: '分正反方交锋，主持人裁决',
		rounds: 3,
		roles: ['正方', '反方', '评审', '正方二辩', '反方二辩'],
		roundName: (r, total) => (r === 1 ? '立论' : r < total ? '反驳' : '总结陈词')
	},
	{
		value: 'review',
		label: '独立评审',
		hint: '各自作答后匿名互评打分，择优合成',
		rounds: 2,
		fixedRounds: true,
		roles: [],
		roundName: (r) => (r === 1 ? '各自作答' : '匿名互评')
	},
	{
		value: 'brainstorm',
		label: '头脑风暴',
		hint: '发散点子、互相延伸，挑出最值得做的',
		rounds: 2,
		roles: [],
		roundName: (r) => (r === 1 ? '发散' : '延伸与筛选')
	}
];

export const modeSpec = (mode: string | null | undefined): ModeSpec =>
	MODES.find((m) => m.value === mode) ?? MODES[0];

/** A seat of a discussion not started yet. */
export type SeatDraft = { model: string; role: string };

export const MIN_SEATS = 2;
export const MAX_SEATS = 5;
export const MAX_ROUNDS = 4;

/** Each seat keeps one hue everywhere (ring, card edge, stance list): ion blue, violet, amber, teal, rose. */
export const SEAT_HUES = [226, 268, 38, 172, 344];
export const seatHue = (index: number) => SEAT_HUES[index % SEAT_HUES.length];

export const seatIndex = (seats: DiscussSeat[], seatId: string) =>
	Math.max(
		0,
		seats.findIndex((s) => s.id === seatId)
	);

export const STATUS_LABEL: Record<AskStatus, string> = {
	running: '讨论中',
	concluding: '主持人总结中',
	done: '已有结论',
	stopped: '已停止',
	error: '出错',
	interrupted: '被中断'
};

export const isLive = (status: AskStatus | string | null | undefined) =>
	status === 'running' || status === 'concluding';

/** Rounds of an ask with their turns, in seat order. */
export const roundsOf = (ask: DiscussAsk): { round: number; turns: DiscussTurn[] }[] => {
	const byRound = new Map<number, DiscussTurn[]>();
	for (const turn of ask.turns ?? []) {
		if (!byRound.has(turn.round)) byRound.set(turn.round, []);
		byRound.get(turn.round)!.push(turn);
	}
	const order = new Map(ask.seats.map((s, i) => [s.id, i]));
	return [...byRound.entries()]
		.sort((a, b) => a[0] - b[0])
		.map(([round, turns]) => ({
			round,
			turns: [...turns].sort((a, b) => (order.get(a.seat) ?? 0) - (order.get(b.seat) ?? 0))
		}));
};

export type Section = { title: string; body: string };

/** Split a conclusion into its "## " sections (same rule as the backend). */
export const parseSections = (content: string): Section[] => {
	const sections: Section[] = [];
	let current: Section | null = null;
	for (const line of (content ?? '').split('\n')) {
		const m = line.match(/^##\s+(.+?)\s*$/);
		if (m) {
			current = { title: m[1].trim(), body: '' };
			sections.push(current);
		} else if (current) {
			current.body += line + '\n';
		} else if (line.trim()) {
			current = { title: '', body: line + '\n' };
			sections.push(current);
		}
	}
	return sections.map((s) => ({ ...s, body: trimRules(s.body) }));
};

const RULE_LINE = /^\s*([-*_])(\s*\1){2,}\s*$/;

/** A section without the --- separators models like to put between sections. */
const trimRules = (body: string) => {
	const lines = body.trim().split('\n');
	while (lines.length && (!lines[0].trim() || RULE_LINE.test(lines[0]))) lines.shift();
	while (lines.length && (!lines[lines.length - 1].trim() || RULE_LINE.test(lines[lines.length - 1]))) lines.pop();
	return lines.join('\n');
};

export type SectionKind = 'answer' | 'agree' | 'disagree' | 'positions' | 'next' | 'other';

const SECTION_KINDS: [SectionKind, RegExp][] = [
	['answer', /^(结论|conclusion|verdict|answer)/i],
	['agree', /^(共识|agreements?|consensus)/i],
	['disagree', /^(分歧|disagreements?)/i],
	['positions', /^(各方立场|立场|positions?|stances?)/i],
	['next', /^(下一步|next steps?)/i]
];

export const sectionKind = (title: string, index: number): SectionKind => {
	for (const [kind, re] of SECTION_KINDS) if (re.test(title.trim())) return kind;
	return index === 0 ? 'answer' : 'other';
};

/** The answer part of a conclusion (its first section). */
export const conclusionAnswer = (content: string) => {
	const sections = parseSections(content);
	return sections.length ? sections[0].body || content.trim() : (content ?? '').trim();
};

export const tokens = (n: number | undefined | null) => {
	if (!n) return '';
	return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : `${n}`;
};

export const seconds = (from?: number | null, to?: number | null) =>
	from && to ? Math.max(0, Math.round((to - from) / 1000)) : null;

/** Short status text of a turn for its header. */
export const turnStatusText = (turn: { status: TurnStatus; thinking?: boolean; error?: string | null }) => {
	if (turn.status === 'waiting') return '等待发言';
	if (turn.status === 'streaming') return turn.thinking ? '思考中' : '发言中';
	if (turn.status === 'error') return '未能发言';
	if (turn.status === 'stopped') return '已停止';
	return '';
};

// -------------------------------------------------------------------------------------------
// Live events: { kind: 'state' | 'delta' | 'turn' | 'end' | 'meta', askId, v, ... }

export type DiscussEvent = {
	kind: 'state' | 'delta' | 'turn' | 'end' | 'meta';
	chatId: string;
	askId: string;
	v: number;
	ask?: DiscussAsk;
	parts?: { t: string; o: number; x: string }[];
	turn?: Partial<DiscussTurn> & { id: string };
	status?: AskStatus;
	title?: string;
	folderId?: string | null;
};

/**
 * Apply one live event to the asks of a discussion. Returns the new asks and whether the
 * client fell behind (a delta that does not line up with what it has): then it should fetch
 * the whole discussion again.
 */
export const applyEvent = (
	asks: DiscussAsk[],
	event: DiscussEvent
): { asks: DiscussAsk[]; stale: boolean } => {
	const index = asks.findIndex((a) => a.id === event.askId);
	if (event.kind === 'state' && event.ask) {
		if (index === -1) return { asks: [...asks, event.ask], stale: false };
		const next = [...asks];
		next[index] = event.ask;
		return { asks: next, stale: false };
	}
	if (index === -1) return { asks, stale: event.kind === 'delta' || event.kind === 'turn' };
	const ask: DiscussAsk = { ...asks[index], turns: [...asks[index].turns], conclusion: { ...asks[index].conclusion } };
	let stale = false;

	const target = (key: string): { content: string } & Record<string, any> | null => {
		if (key === 'conclusion') return ask.conclusion;
		const i = ask.turns.findIndex((t) => t.id === key);
		if (i === -1) return null;
		ask.turns[i] = { ...ask.turns[i] };
		return ask.turns[i];
	};

	if (event.kind === 'delta') {
		for (const part of event.parts ?? []) {
			const t = target(part.t);
			if (!t) {
				stale = true;
				continue;
			}
			const have = t.content ?? '';
			if (part.o > have.length) {
				stale = true;
				continue;
			}
			t.content = have.slice(0, part.o) + part.x;
			if (t.status === 'waiting') t.status = 'streaming';
			if (part.x) t.thinking = false;
		}
	} else if (event.kind === 'turn' && event.turn) {
		const t = target(event.turn.id);
		if (!t) {
			stale = true;
		} else {
			const { content, ...rest } = event.turn;
			Object.assign(t, rest);
			if (typeof content === 'string') t.content = content;
		}
	} else if (event.kind === 'end' && event.status) {
		ask.status = event.status;
	}
	const next = [...asks];
	next[index] = ask;
	return { asks: next, stale };
};

/** Markdown of a whole discussion, for copying / saving. */
export const discussionMarkdown = (title: string, asks: DiscussAsk[]): string => {
	const out: string[] = [`# ${title}`];
	for (const ask of asks) {
		const spec = modeSpec(ask.mode);
		out.push(`\n## 问题\n\n${ask.question}`);
		out.push(
			`\n> ${spec.label} · ${ask.seats.map((s) => s.label + (s.role && !s.label.includes(s.role) ? `（${s.role}）` : '')).join('、')} · 主持人 ${ask.moderator.name}`
		);
		for (const { round, turns } of roundsOf(ask)) {
			out.push(`\n### 第 ${round} 轮 · ${spec.roundName(round, ask.rounds)}`);
			for (const turn of turns) {
				const seat = ask.seats.find((s) => s.id === turn.seat);
				const body = turn.status === 'done' ? turn.content : `（${turnStatusText(turn) || turn.status}${turn.error ? '：' + turn.error : ''}）`;
				out.push(`\n**${seat?.label ?? turn.seat}**\n\n${body}`);
			}
		}
		if (ask.conclusion?.content) out.push(`\n### 主持人结论（${ask.conclusion.name}）\n\n${ask.conclusion.content}`);
	}
	return out.join('\n') + '\n';
};

// -------------------------------------------------------------------------------------------
// Models

type ModelLike = {
	id: string;
	name?: string;
	selection_id?: string;
	owned_by?: string;
	info?: { meta?: { profile_image_url?: string; hidden?: boolean } };
	meta?: { profile_image_url?: string };
};

/** The model a seat or a selection id points at (selection id or plain id). */
export const modelById = <T extends ModelLike>(models: T[] | null | undefined, id: string): T | undefined =>
	(models ?? []).find((m) => m.selection_id === id || m.id === id);

export const modelIcon = (model: ModelLike | undefined) =>
	model?.info?.meta?.profile_image_url ?? model?.meta?.profile_image_url ?? '/static/favicon.png';

/** The id a seat is sent with. */
export const modelRef = (model: ModelLike) => model.selection_id || model.id;
