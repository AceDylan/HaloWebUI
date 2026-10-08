// A link in a reply to a page of this app — a 协作台 team's result page, a discussion, another
// chat — opens where you are, the way the sidebar's links do. Websites, files the API serves and
// downloads still open in a new tab.

const APP_ROUTE = /^\/(?:c|s|teams|discuss|answer|workspace|channels|settings|notes)(?:[/?#]|$)/;

/**
 * The path to navigate to in place for `href`, or null when it should open in a new tab.
 * `origin`: the page's own origin, so an absolute link to this app counts too.
 */
export const inAppPath = (
	href: string | null | undefined,
	origin?: string | null
): string | null => {
	const raw = String(href ?? '').trim();
	if (!raw) return null;
	let path = raw;
	if (raw.startsWith('//') || /^[a-z][a-z0-9+.-]*:/i.test(raw)) {
		if (!origin) return null;
		try {
			const url = new URL(raw);
			if (url.origin !== origin) return null;
			path = `${url.pathname}${url.search}${url.hash}`;
		} catch {
			return null;
		}
	}
	if (!path.startsWith('/') || path.startsWith('//')) return null;
	return APP_ROUTE.test(path) ? path : null;
};
