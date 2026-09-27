// Bookmark Hub embed: the Hub frames HaloWebUI and, for its unlocked
// administrator, points the frame at /auth#hub_ticket=<single-use ticket>.
// The sign-in page trades that ticket for a session (POST /api/v1/hub/session).
//
// The ticket travels in the fragment on purpose: a fragment never reaches a
// server log or a Referer header. It is removed from the address before
// anything else happens, so it does not linger in the frame's history either.

export const HUB_TICKET_PARAM = 'hub_ticket';

// v2.<purpose>.<expiry>.<nonce>.<issuer>.<audience>.<hmac>; the server does the
// real check, this only keeps junk from being posted at all.
const TICKET_SHAPE = /^v2(?:\.[A-Za-z0-9_-]{1,400}){6}$/;

export const parseHubTicket = (hash: string): string | null => {
	const fragment = hash.startsWith('#') ? hash.slice(1) : hash;
	if (!fragment) {
		return null;
	}
	const ticket = new URLSearchParams(fragment).get(HUB_TICKET_PARAM);
	return ticket && ticket.length <= 1024 && TICKET_SHAPE.test(ticket) ? ticket : null;
};

/** Address without the ticket; other fragment parameters are kept. */
export const stripHubTicket = (url: URL): string => {
	const params = new URLSearchParams(url.hash.startsWith('#') ? url.hash.slice(1) : url.hash);
	params.delete(HUB_TICKET_PARAM);
	const rest = params.toString();
	return `${url.pathname}${url.search}${rest ? `#${rest}` : ''}`;
};

/**
 * Reads the ticket from the current address and removes it from the address
 * bar and the history entry. Returns null when there is none.
 */
export const takeHubTicket = (
	location: Pick<Location, 'href'> = window.location,
	history: Pick<History, 'replaceState' | 'state'> = window.history
): string | null => {
	const url = new URL(location.href);
	if (!url.hash.includes(`${HUB_TICKET_PARAM}=`)) {
		return null;
	}
	const ticket = parseHubTicket(url.hash);
	// Scrub even a malformed one: whatever it is, it has no business staying there.
	history.replaceState(history.state, '', stripHubTicket(url));
	return ticket;
};

// ---------------------------------------------------------------------------
// Reply activity for the Hub's "AI 聊天" tab.
//
// When the Hub shows another of its pages it only hides this frame, so our
// socket stays connected and the server treats us as being looked at (no
// Telegram push); our toasts and unread dots are hidden with the frame, and the
// browser tab's title belongs to the Hub. So the page tells the Hub, and only
// the Hub, whether a reply is running or has finished unseen; the Hub marks its
// tab. The message carries the state only, nothing about the chat.

export type HubActivityState = 'idle' | 'running' | 'done';

export const HUB_ACTIVITY_MESSAGE_SOURCE = 'halowebui';
export const HUB_ACTIVITY_MESSAGE_TYPE = 'activity';

export type HubActivityMessage = {
	source: typeof HUB_ACTIVITY_MESSAGE_SOURCE;
	type: typeof HUB_ACTIVITY_MESSAGE_TYPE;
	state: HubActivityState;
};

type FrameWindow = {
	parent: { postMessage: (message: unknown, targetOrigin: string) => void } | null;
};

/**
 * Posts `state` to the framing Hub. Does nothing unless the page is framed and
 * the server named the Hub (`hub_origin` in /api/config); the message is
 * addressed to that origin, so the browser drops it for any other parent.
 * Returns whether a message was posted.
 */
export const postActivityToHub = (
	state: HubActivityState,
	hubOrigin: string | null | undefined,
	win: FrameWindow = window as unknown as FrameWindow
): boolean => {
	if (!hubOrigin || typeof hubOrigin !== 'string' || !/^https?:\/\/[^/]+$/.test(hubOrigin)) {
		return false;
	}
	const parent = win.parent;
	if (!parent || parent === (win as unknown)) {
		return false;
	}
	const message: HubActivityMessage = {
		source: HUB_ACTIVITY_MESSAGE_SOURCE,
		type: HUB_ACTIVITY_MESSAGE_TYPE,
		state
	};
	try {
		parent.postMessage(message, hubOrigin);
		return true;
	} catch {
		return false;
	}
};

// ---------------------------------------------------------------------------
// Notes named in a reply.
//
// Hermes names the notes it writes by their path on the host
// (`/root/Documents/Obsidian Vault/项目/HaloWebUI.md`). When the server names
// that vault root (`hub_vault_root` in /api/config, from HUB_VAULT_ROOT), such a
// path becomes a link to the note in the Hub's 笔记 tab: framed by the Hub, the
// page asks the Hub (and only the Hub) to open it there; on its own, the link is
// an ordinary address of the Hub (/?note=<path>#vault) opening in a new tab.

export const HUB_OPEN_NOTE_MESSAGE_TYPE = 'open-note';

const NOTE_PATH_MAX = 512;
const PLAIN_ORIGIN = /^https?:\/\/[^/]+$/;

const cleanRoot = (root: unknown): string | null => {
	if (typeof root !== 'string') {
		return null;
	}
	const base = root.trim().replace(/\/+$/, '');
	return base.startsWith('/') ? base : null;
};

/**
 * The vault-relative path when `value` is the absolute path of a Markdown note
 * under `root`, else null. Nothing outside the vault, no `..`, no dot-folders.
 */
export const vaultNotePath = (value: unknown, root: unknown): string | null => {
	const base = cleanRoot(root);
	if (typeof value !== 'string' || !base) {
		return null;
	}
	let text = value.trim();
	if (text.startsWith('file://')) {
		text = text.slice('file://'.length);
	}
	if (!text.startsWith(`${base}/`) && text.includes('%')) {
		// A Markdown link target arrives percent-encoded (spaces, CJK).
		try {
			text = decodeURI(text);
		} catch {
			return null;
		}
	}
	if (!text.startsWith(`${base}/`)) {
		return null;
	}
	const rel = text.slice(base.length + 1);
	if (
		!rel ||
		rel.length > NOTE_PATH_MAX ||
		!/\.md$/i.test(rel) ||
		// eslint-disable-next-line no-control-regex
		/[\\\u0000-\u001f\u007f]/.test(rel)
	) {
		return null;
	}
	return rel.split('/').some((part) => !part || part.startsWith('.')) ? null : rel;
};

export type NotePathPiece = { text: string; path: string | null };

/**
 * Splits plain text around the absolute note paths in it. A path may contain
 * spaces, so it runs from the vault root to the first `.md` that ends a word.
 */
export const splitVaultNotePaths = (text: string, root: unknown): NotePathPiece[] => {
	const base = cleanRoot(root);
	const marker = base ? `${base}/` : '';
	if (!marker || !text.includes(marker)) {
		return [{ text, path: null }];
	}
	const pieces: NotePathPiece[] = [];
	let rest = text;
	for (let at = rest.indexOf(marker); at >= 0; at = rest.indexOf(marker)) {
		const match = /^[^\n`<>"|*]*?\.md(?![\p{L}\p{N}_.])/iu.exec(rest.slice(at));
		if (!match) {
			break;
		}
		if (at > 0) {
			pieces.push({ text: rest.slice(0, at), path: null });
		}
		pieces.push({ text: match[0], path: vaultNotePath(match[0], base) });
		rest = rest.slice(at + match[0].length);
	}
	if (rest) {
		pieces.push({ text: rest, path: null });
	}
	return pieces;
};

/** The Hub's own address for a note: it switches to 笔记 and opens it. */
export const hubNoteUrl = (path: string, hubOrigin: unknown): string | null =>
	typeof hubOrigin === 'string' && PLAIN_ORIGIN.test(hubOrigin)
		? `${hubOrigin}/?note=${encodeURIComponent(path)}#vault`
		: null;

/**
 * When framed by the Hub, asks it to open `path` in its 笔记 tab and returns
 * true; the message is addressed to the Hub's origin, so any other parent never
 * sees it. Returns false when not framed: the caller lets the link open the
 * Hub's address in a new tab instead.
 */
export const openNoteInHub = (
	path: string,
	hubOrigin: unknown,
	win: FrameWindow = window as unknown as FrameWindow
): boolean => {
	if (typeof hubOrigin !== 'string' || !PLAIN_ORIGIN.test(hubOrigin)) {
		return false;
	}
	const parent = win.parent;
	if (!parent || parent === (win as unknown)) {
		return false;
	}
	try {
		parent.postMessage(
			{ source: HUB_ACTIVITY_MESSAGE_SOURCE, type: HUB_OPEN_NOTE_MESSAGE_TYPE, path },
			hubOrigin
		);
		return true;
	} catch {
		return false;
	}
};
