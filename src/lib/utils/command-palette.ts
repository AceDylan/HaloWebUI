// ⌘K command palette: what it lists for a query — places to go, chats (the server's full-text
// hits, or the recent ones before anything is typed) and models to start a chat with.

import { chatHref } from './chat-kind';
import type { Destination } from './destinations';

export type PaletteItem = {
	id: string;
	section: '跳转' | '对话' | '其他端会话' | '用模型开新对话';
	label: string;
	hint?: string;
	href?: string;
	/** a store to flip instead of a page (任务收件箱, 收藏, 已归档) */
	open?: 'inbox' | 'bookmarks' | 'archived';
	kind?: string | null;
	/** search hit: open the chat at this message */
	messageId?: string | null;
	archived?: boolean;
	/** unimported Hermes session (Telegram / QQ / CLI): selecting imports then opens */
	sessionId?: string | null;
	source?: string | null;
};

export type PaletteChat = {
	id: string;
	title: string;
	kind?: string | null;
	snippet?: string | null;
	message_id?: string | null;
	archived?: boolean;
};

export type PaletteRemoteSession = {
	id: string;
	source: string;
	title?: string | null;
	preview?: string | null;
	message_count?: number;
	imported?: boolean;
};

export type PaletteModel = { id: string; name?: string; info?: any; preset?: boolean };

const fold = (s: string) => s.toLowerCase().replace(/\s+/g, '');
const matches = (query: string, ...texts: (string | null | undefined)[]) =>
	!query || texts.some((text) => fold(text ?? '').includes(query));

export const MAX_CHATS = 8;
export const MAX_REMOTE_SESSIONS = 6;
export const MAX_MODELS = 5;

export const REMOTE_SOURCE_LABEL: Record<string, string> = {
	telegram: 'Telegram',
	qqbot: 'QQ',
	cli: 'CLI'
};

export const paletteItems = ({
	query,
	destinations,
	admin,
	recent,
	hits,
	remoteSessions = null,
	models
}: {
	query: string;
	destinations: Destination[];
	admin: boolean;
	/** the sidebar's list, newest first: shown before anything is typed */
	recent: PaletteChat[];
	/** the server's search hits for the query (null while they load) */
	hits: PaletteChat[] | null;
	/** unimported Telegram / QQ / CLI sessions matching the query */
	remoteSessions?: PaletteRemoteSession[] | null;
	models: PaletteModel[];
}): PaletteItem[] => {
	const q = fold(query);
	const places: (PaletteItem & { keywords?: string })[] = [
		{ id: 'go:new', section: '跳转', label: '新对话', href: '/', keywords: 'new chat xinduihua' },
		...destinations.map((d) => ({
			id: `go:${d.key}`,
			section: '跳转' as const,
			label: d.label,
			hint: d.title.split('：')[1] ?? '',
			href: d.href,
			keywords: `${d.key} ${d.title}`
		})),
		{
			id: 'go:inbox',
			section: '跳转',
			label: '任务收件箱',
			hint: '等我处理、进行中与最近结束的任务',
			open: 'inbox',
			keywords: 'inbox tasks running renwu shoujianxiang 任务 收件箱 运行中 待办'
		},
		{ id: 'go:bookmarks', section: '跳转', label: '收藏', open: 'bookmarks', keywords: 'bookmarks' },
		{ id: 'go:archived', section: '跳转', label: '已归档的对话', open: 'archived', keywords: 'archived' },
		{ id: 'go:settings', section: '跳转', label: '设置', href: '/settings/interface', keywords: 'settings' },
		...(admin
			? [{ id: 'go:admin', section: '跳转' as const, label: '管理后台', href: '/admin', keywords: 'admin' }]
			: [])
	];
	const items: PaletteItem[] = places
		.filter((p) => matches(q, p.label, p.keywords, p.hint))
		.map(({ keywords: _k, ...p }) => p);

	const chats = q ? (hits ?? recent.filter((c) => matches(q, c.title))) : recent;
	const seenChatIds = new Set<string>();
	for (const chat of chats.slice(0, MAX_CHATS)) {
		seenChatIds.add(chat.id);
		items.push({
			id: `chat:${chat.id}`,
			section: '对话',
			label: chat.title || '新对话',
			hint: q && chat.snippet ? chat.snippet : undefined,
			href: chatHref(chat.id, chat.kind),
			kind: chat.kind ?? null,
			messageId: q && chat.message_id && chat.kind !== 'discuss' ? chat.message_id : null,
			archived: !!chat.archived
		});
	}

	if (q && Array.isArray(remoteSessions) && remoteSessions.length > 0) {
		for (const session of remoteSessions
			.filter((s) => s?.id && !seenChatIds.has(s.id))
			.slice(0, MAX_REMOTE_SESSIONS)) {
			const title = (session.title ?? '').trim();
			const preview = (session.preview ?? '').trim();
			items.push({
				id: `remote:${session.id}`,
				section: '其他端会话',
				label: title || preview || session.id,
				hint: title && preview ? preview : session.message_count ? `${session.message_count} 条消息` : undefined,
				sessionId: session.id,
				source: session.source
			});
		}
	}

	if (q) {
		const found = models
			.filter((m) => !m?.info?.meta?.hidden && matches(q, m.name, m.id))
			.slice(0, MAX_MODELS);
		for (const model of found) {
			items.push({
				id: `model:${model.id}`,
				section: '用模型开新对话',
				label: model.name || model.id,
				href: `/?models=${encodeURIComponent(model.id)}`
			});
		}
	}
	return items;
};
