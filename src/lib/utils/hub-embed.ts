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
