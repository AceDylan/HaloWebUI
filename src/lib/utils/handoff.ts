// Carrying work between the chat and its modes — 精答 (/answer), 讨论台 (/discuss), 协作台 (/teams),
// the image studio and back to a chat — so nobody types the question twice. The page handing off writes one
// entry to sessionStorage and navigates; the page it goes to takes it once (it is removed either
// way) and shows where it came from with a way back. Only file ids already on this server travel.

export type HandoffTarget = 'answer' | 'discuss' | 'teams' | 'chat' | 'studio';
export type HandoffOriginKind = 'chat' | 'answer' | 'discuss' | 'team' | 'studio';

/** Where the work came from: shown as 「来自对话「标题」」 with a link back. */
export type HandoffOrigin = { kind: HandoffOriginKind; id: string; title: string };
export type HandoffFile = { id: string; name: string; type: 'image' | 'file' };

export type Handoff = {
	to: HandoffTarget;
	/** The question / goal / prompt / draft. */
	text: string;
	/** Seats for a discussion, or the model for a chat. */
	models: string[];
	files: HandoffFile[];
	/** Background the next step should know: an earlier conversation, a conclusion. */
	context: string;
	from: HandoffOrigin | null;
	at: number;
};

export const HANDOFF_KEY = 'halo.handoff';
const TTL_MS = 5 * 60 * 1000;
export const HANDOFF_TEXT_MAX = 8000;
export const HANDOFF_CONTEXT_MAX = 12000;
const MAX_FILES = 4;
const MAX_MODELS = 5;
const ID = /^[A-Za-z0-9_-]{1,128}$/;
const TARGETS: HandoffTarget[] = ['answer', 'discuss', 'teams', 'chat', 'studio'];
const KINDS: HandoffOriginKind[] = ['chat', 'answer', 'discuss', 'team', 'studio'];

type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

const clean = (value: unknown, max: number) => (typeof value === 'string' ? value.trim().slice(0, max) : '');

const normalize = (value: any, now: number): Handoff | null => {
	if (!value || typeof value !== 'object' || !TARGETS.includes(value.to)) return null;
	const at = Number(value.at);
	if (!Number.isFinite(at) || now - at > TTL_MS || at - now > 60_000) return null;
	const files: HandoffFile[] = (Array.isArray(value.files) ? value.files : [])
		.filter((f: any) => f && ID.test(String(f.id ?? '')))
		.slice(0, MAX_FILES)
		.map((f: any) => ({ id: String(f.id), name: clean(f.name, 200) || 'file', type: f.type === 'image' ? 'image' : 'file' }));
	const models = (Array.isArray(value.models) ? value.models : [])
		.map((m: unknown) => clean(m, 300))
		.filter(Boolean)
		.slice(0, MAX_MODELS);
	const from =
		value.from && KINDS.includes(value.from.kind) && ID.test(String(value.from.id ?? ''))
			? { kind: value.from.kind, id: String(value.from.id), title: clean(value.from.title, 120) }
			: null;
	return {
		to: value.to,
		text: clean(value.text, HANDOFF_TEXT_MAX),
		models,
		files,
		context: clean(value.context, HANDOFF_CONTEXT_MAX),
		from,
		at
	};
};

/** Leaves work for the page at `to`. Returns whether it was stored. */
export const handOff = (
	storage: Store | null | undefined,
	entry: Partial<Omit<Handoff, 'at'>> & { to: HandoffTarget },
	now = Date.now()
): boolean => {
	const value = normalize({ text: '', models: [], files: [], context: '', from: null, ...entry, at: now }, now);
	if (!storage || !value) return false;
	try {
		storage.setItem(HANDOFF_KEY, JSON.stringify(value));
		return true;
	} catch {
		return false;
	}
};

/** Takes the work left for `to` (once). An entry for another page stays where it is. */
export const takeHandoff = (
	storage: Store | null | undefined,
	to: HandoffTarget,
	now = Date.now()
): Handoff | null => {
	if (!storage) return null;
	try {
		const raw = storage.getItem(HANDOFF_KEY);
		if (raw === null) return null;
		let parsed: any = null;
		try {
			parsed = JSON.parse(raw);
		} catch {
			storage.removeItem(HANDOFF_KEY);
			return null;
		}
		if (parsed?.to !== to) return null;
		storage.removeItem(HANDOFF_KEY);
		return normalize(parsed, now);
	} catch {
		return null;
	}
};

const KIND_LABEL: Record<HandoffOriginKind, string> = {
	chat: '对话',
	answer: '精答',
	discuss: '讨论',
	team: '协作',
	studio: '生图工作台'
};

/** 「对话「标题」」 */
export const originLabel = (from: HandoffOrigin): string =>
	from.title ? `${KIND_LABEL[from.kind]}「${from.title}」` : KIND_LABEL[from.kind];

/** The page to go back to. */
export const originHref = (from: HandoffOrigin): string =>
	from.kind === 'discuss'
		? `/discuss/${from.id}`
		: from.kind === 'answer'
			? `/answer/${from.id}`
			: from.kind === 'team'
				? `/teams/${from.id}`
				: from.kind === 'studio'
					? '/workspace/images?tab=workbench'
					: `/c/${from.id}`;

type HistoryMessage = { id?: string; parentId?: string | null; role?: string; content?: unknown; model?: string };
type ChatHistory = { currentId?: string | null; messages?: Record<string, HistoryMessage> };

const plain = (content: unknown): string => {
	if (typeof content === 'string') return content;
	if (Array.isArray(content))
		return content
			.map((part: any) => (typeof part === 'string' ? part : part?.type === 'text' ? String(part.text ?? '') : ''))
			.join('\n');
	return '';
};

/**
 * The conversation on screen as plain text for the next step (oldest first): the branch from the
 * root to the current message. Long conversations keep their latest turns; each turn is capped.
 */
export const conversationContext = (history: ChatHistory | null | undefined, max = HANDOFF_CONTEXT_MAX): string => {
	const messages = history?.messages ?? {};
	const branch: HistoryMessage[] = [];
	const seen = new Set<string>();
	let id = history?.currentId ?? null;
	while (id && messages[id] && !seen.has(id)) {
		seen.add(id);
		branch.unshift(messages[id]);
		id = messages[id].parentId ?? null;
	}
	const turns = branch
		.map((m) => {
			// details blocks are tool calls and thinking; images are not text
			const text = plain(m.content)
				.replace(/<details[\s\S]*?<\/details>/g, '')
				.replace(/!\[[^\]]*\]\([^)]*\)/g, '[图片]')
				.trim();
			if (!text) return '';
			const who = m.role === 'user' ? '用户' : '助手';
			return `${who}：${text.length > 3000 ? `${text.slice(0, 3000)}…` : text}`;
		})
		.filter(Boolean);
	const kept: string[] = [];
	let size = 0;
	for (let i = turns.length - 1; i >= 0; i--) {
		if (size + turns[i].length + 2 > max) break;
		kept.unshift(turns[i]);
		size += turns[i].length + 2;
	}
	return kept.join('\n\n');
};

/** Where each kind of handoff goes. */
export const HANDOFF_PATH: Record<HandoffTarget, string> = {
	answer: '/answer',
	discuss: '/discuss',
	teams: '/teams',
	chat: '/',
	studio: '/workspace/images?tab=workbench'
};

type ComposerFile = { id?: string | null; name?: string; type?: string; status?: string };

/** The composer's uploaded attachments as handoff files (still-uploading ones stay behind). */
export const composerFiles = (files: ComposerFile[] | null | undefined): HandoffFile[] =>
	(files ?? [])
		.filter((f) => f && (f.status === undefined || f.status === 'uploaded') && f.id)
		.map((f) => ({ id: String(f.id), name: f.name ?? '', type: f.type === 'image' ? 'image' : 'file' }));

const chatOrigin = (chatId: string | null | undefined, title: string | null | undefined): HandoffOrigin | null =>
	chatId && chatId !== 'local' && ID.test(chatId) ? { kind: 'chat', id: chatId, title: title ?? '' } : null;

/** The composer's draft (and, in a chat with messages, the conversation) handed to a mode. */
export const chatHandoff = (
	to: HandoffTarget,
	opts: {
		text: string;
		files?: ComposerFile[] | null;
		history?: ChatHistory | null;
		chatId?: string | null;
		title?: string | null;
		models?: string[];
	}
): Partial<Omit<Handoff, 'at'>> & { to: HandoffTarget } => {
	const hasMessages = !!opts.history?.currentId;
	return {
		to,
		text: opts.text ?? '',
		models: opts.models ?? [],
		files: composerFiles(opts.files),
		context: hasMessages ? conversationContext(opts.history) : '',
		from: hasMessages ? chatOrigin(opts.chatId, opts.title) : null
	};
};

/** A reply handed to a mode: its question again, with the conversation up to the reply as background. */
export const replyHandoff = (
	to: HandoffTarget,
	opts: { history: ChatHistory | null | undefined; messageId: string; chatId?: string | null; title?: string | null }
): Partial<Omit<Handoff, 'at'>> & { to: HandoffTarget } => {
	const messages = opts.history?.messages ?? {};
	const reply = messages[opts.messageId];
	const question = reply?.parentId ? messages[reply.parentId] : undefined;
	return {
		to,
		text: plain(question?.content).trim(),
		files: composerFiles(((question as any)?.files ?? []) as ComposerFile[]),
		context: conversationContext({ messages, currentId: opts.messageId }),
		from: chatOrigin(opts.chatId, opts.title)
	};
};

/**
 * A goal for 协作台 with the background written under it (the team reads the goal only),
 * within the goal's length limit.
 */
export const goalWithBackground = (goal: string, background: string, from: HandoffOrigin | null, max = 8000): string => {
	const text = goal.trim();
	const extra = background.trim();
	if (!extra) return text.slice(0, max);
	const head = `\n\n背景（来自${from ? originLabel(from) : '之前的对话'}）：\n`;
	const room = max - text.length - head.length;
	if (room < 200) return text.slice(0, max);
	return `${text}${head}${extra.length > room ? `…${extra.slice(extra.length - room + 1)}` : extra}`;
};
