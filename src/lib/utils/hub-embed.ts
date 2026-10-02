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
// Browser history inside the Hub's frame.
//
// The Hub owns the page's Back: from any of its tabs Back returns to its
// library, and from the library it leaves the Hub. An entry this frame pushes
// (every chat opened from the sidebar) lands behind the Hub's own. Once the Hub
// shows another tab, Back pages through chats in a frame that is hidden, and
// nothing visible happens; and after the Hub shows this tab again the browser
// keeps no record of where the frame was, so the first Back after opening
// another chat does nothing at all. So, framed, a navigation replaces the
// current entry instead of adding one (SvelteKit looks history.pushState up at
// call time). Only the Hub may frame this app (frame-ancestors), so framed at
// all means framed by the Hub.

type HistoryWindow = {
	parent: unknown;
	history: Pick<History, 'pushState' | 'replaceState'>;
};

export const isFramed = (win: { parent: unknown } = window): boolean => {
	try {
		return !!win.parent && win.parent !== win;
	} catch {
		return true;
	}
};

/** Framed: pushState becomes replaceState. Returns whether it did. */
export const keepHistoryWithHub = (
	win: HistoryWindow = window as unknown as HistoryWindow
): boolean => {
	if (!isFramed(win)) {
		return false;
	}
	const history = win.history;
	const replace = history.replaceState;
	history.pushState = function (data: unknown, unused: string, url?: string | URL | null) {
		return replace.call(this, data, unused, url);
	};
	return true;
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

// ---------------------------------------------------------------------------
// Signing in again through the Hub.
//
// A session opened by a Hub ticket ends after 12 hours (HUB_EMBED_SESSION_TTL),
// while a Hub tab — a browser's start page, a phone tab — stays open for days.
// The frame then only said "Your session has expired. Please log in again.",
// though the Hub can sign its administrator in again at no cost. So, framed by
// the Hub, the page asks the Hub to: the Hub opens a fresh frame with a new
// ticket that lands on the same chat (the Hub refuses when it has been locked
// meanwhile, and when it cannot sign tickets at all).

export const HUB_REAUTH_MESSAGE_TYPE = 'reauth';
const HUB_ORIGIN_KEY = 'halowebui.hubOrigin';
const REAUTH_KEY = 'halowebui.hubReauthAt';
// At most one request a minute: if the new session cannot stick (cookies
// blocked, the two deployments disagree), the frame must not bounce forever.
export const HUB_REAUTH_GUARD_MS = 60_000;

type SessionStore = Pick<Storage, 'getItem' | 'setItem'>;

const sessionStore = (): SessionStore | null => {
	try {
		return window.sessionStorage;
	} catch {
		return null;
	}
};

/**
 * Keeps the Hub's origin for this tab. The configuration names the Hub only to
 * a signed-in user, and a request to sign in again is exactly what is needed
 * once the session is gone.
 */
export const rememberHubOrigin = (
	hubOrigin: unknown,
	store: SessionStore | null = sessionStore()
): void => {
	if (typeof hubOrigin !== 'string' || !PLAIN_ORIGIN.test(hubOrigin) || !store) {
		return;
	}
	try {
		store.setItem(HUB_ORIGIN_KEY, hubOrigin);
	} catch {
		// Storage refused: the in-session path still has the origin from the config.
	}
};

/** The chat to land on again: /c/<id>, else home. Never a query: `/?q=` would send its prompt once more. */
export const hubReturnPath = (pathname: unknown): string =>
	typeof pathname === 'string' && /^\/c\/[A-Za-z0-9-]{1,64}$/.test(pathname) ? pathname : '/';

/**
 * Framed by the Hub, asks it to sign this tab in again and come back to
 * `pathname`. Returns true when the request went out (the Hub replaces this
 * frame shortly; the caller need not tell anyone to sign in).
 */
export const requestHubReauth = (
	hubOrigin: unknown,
	pathname: unknown,
	win: FrameWindow = window as unknown as FrameWindow,
	store: SessionStore | null = sessionStore(),
	now: number = Date.now()
): boolean => {
	const parent = win.parent;
	if (!parent || parent === (win as unknown) || !store) {
		return false;
	}
	let origin = typeof hubOrigin === 'string' && PLAIN_ORIGIN.test(hubOrigin) ? hubOrigin : null;
	try {
		origin = origin ?? store.getItem(HUB_ORIGIN_KEY);
		if (!origin || !PLAIN_ORIGIN.test(origin)) {
			return false;
		}
		const last = Number(store.getItem(REAUTH_KEY) || 0);
		if (last > 0 && now - last >= 0 && now - last < HUB_REAUTH_GUARD_MS) {
			return false;
		}
		store.setItem(REAUTH_KEY, String(now));
		parent.postMessage(
			{
				source: HUB_ACTIVITY_MESSAGE_SOURCE,
				type: HUB_REAUTH_MESSAGE_TYPE,
				path: hubReturnPath(pathname)
			},
			origin
		);
		return true;
	} catch {
		return false;
	}
};

// ---------------------------------------------------------------------------
// Which chat is on screen.
//
// The Hub's 「重新载入」 and 「新标签页打开」 used to start over at the home
// page: a stuck frame came back as an empty new chat, and popping the chat out
// into its own tab lost it. So, framed by the Hub, the page tells the Hub (and
// only the Hub) which chat it shows: the same /c/<id> it already sends when
// asking to be signed in again, else '/'. Nothing else about the chat.

export const HUB_PLACE_MESSAGE_TYPE = 'place';

/**
 * The chat on screen as the Hub should reopen it. A new chat gets its id (the
 * chatId store) a moment before the address becomes /c/<id>, so on '/' a real
 * chat id counts too; a temporary chat ('local') has no address to come back to.
 */
export const hubPlacePath = (pathname: unknown, currentChatId: unknown): string => {
	const path = hubReturnPath(pathname);
	if (path !== '/' || pathname !== '/') {
		return path;
	}
	return typeof currentChatId === 'string' && currentChatId !== 'local'
		? hubReturnPath(`/c/${currentChatId}`)
		: '/';
};

/** Tells the framing Hub which chat is on screen. Returns whether a message was posted. */
export const postPlaceToHub = (
	path: unknown,
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
			{ source: HUB_ACTIVITY_MESSAGE_SOURCE, type: HUB_PLACE_MESSAGE_TYPE, path: hubReturnPath(path) },
			hubOrigin
		);
		return true;
	} catch {
		return false;
	}
};

// ---------------------------------------------------------------------------
// The Hub's dark / light.
//
// The Hub keeps its own theme (dark unless changed), while this app follows the
// device by default ("system"): on a light device the dark Hub showed a white
// chat. A cross-origin frame cannot see the Hub's choice (the frame element's
// color-scheme does not reach our prefers-color-scheme), so the Hub tells us:
// in the address when it opens the frame (#...&hub_theme=dark, read by the
// boot script in app.html and kept for this tab), and by a message when it
// changes its theme later. Framed, "system" then means the Hub's theme; an
// explicit dark or light chosen here still wins.

export type HubTheme = 'dark' | 'light';
export const HUB_THEME_KEY = 'halowebui.hubTheme';
export const HUB_THEME_MESSAGE_SOURCE = 'hub';
export const HUB_THEME_MESSAGE_TYPE = 'theme';

const asHubTheme = (value: unknown): HubTheme | null =>
	value === 'dark' || value === 'light' ? value : null;

/** The Hub's theme for this tab, when framed by it and it has told us one. */
export const hubTheme = (
	win: { parent: unknown } = window,
	store: SessionStore | null = sessionStore()
): HubTheme | null => {
	if (!isFramed(win) || !store) {
		return null;
	}
	try {
		return asHubTheme(store.getItem(HUB_THEME_KEY));
	} catch {
		return null;
	}
};

/** What "system" resolves to here: the Hub's theme when framed by it, else the device's. */
export const systemPrefersDark = (): boolean => {
	const theme = hubTheme();
	if (theme) {
		return theme === 'dark';
	}
	return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
};

type HubMessageEvent = { source: unknown; origin: string; data: unknown };

/**
 * The theme in a message from the framing Hub, else null. Only our parent, only
 * from the Hub's origin (from the config, else the one kept at sign-in).
 */
export const acceptHubTheme = (
	event: HubMessageEvent,
	hubOrigin: unknown,
	win: { parent: unknown } = window,
	store: SessionStore | null = sessionStore()
): HubTheme | null => {
	if (!isFramed(win) || event.source !== win.parent) {
		return null;
	}
	let origin = typeof hubOrigin === 'string' && PLAIN_ORIGIN.test(hubOrigin) ? hubOrigin : null;
	try {
		origin = origin ?? store?.getItem(HUB_ORIGIN_KEY) ?? null;
	} catch {
		origin = null;
	}
	if (!origin || event.origin !== origin) {
		return null;
	}
	const data = event.data as { source?: unknown; type?: unknown; theme?: unknown } | null;
	if (
		!data ||
		typeof data !== 'object' ||
		data.source !== HUB_THEME_MESSAGE_SOURCE ||
		data.type !== HUB_THEME_MESSAGE_TYPE
	) {
		return null;
	}
	return asHubTheme(data.theme);
};

/**
 * Keeps the Hub's new theme for this tab and, while the theme setting here is
 * "system", repaints with it (the same classes the boot script sets).
 */
export const followHubTheme = (
	theme: HubTheme,
	storedTheme: unknown,
	doc: Pick<Document, 'documentElement' | 'querySelector'> = document,
	store: SessionStore | null = sessionStore()
): boolean => {
	try {
		store?.setItem(HUB_THEME_KEY, theme);
	} catch {
		// Storage refused: this page still repaints.
	}
	if (storedTheme !== 'system') {
		return false;
	}
	const root = doc.documentElement;
	root.classList.remove(theme === 'dark' ? 'light' : 'dark');
	root.classList.add(theme);
	doc
		.querySelector('meta[name="theme-color"]')
		?.setAttribute('content', theme === 'dark' ? '#0a0b10' : '#ffffff');
	return true;
};
