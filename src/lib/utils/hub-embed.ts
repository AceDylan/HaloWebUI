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
