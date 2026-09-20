// Where /auth is allowed to send someone once they are signed in.
//
// `?redirect=` is attacker-reachable: anybody can mail out a link to our own
// sign-in page and put whatever they like in that parameter. Handed straight to
// `goto()` it is an open redirect — a phishing page wearing our address in the
// referrer chain, and, with `javascript:`, script running on our origin.
//
// So only a path on this very site is ever accepted, and it is rebuilt from a
// parsed URL rather than passed through as typed. Anything else silently
// becomes the fallback: a sign-in that lands on the home page is a small
// annoyance, a sign-in that lands on somebody else's site is not.
//
// The Bookmark Hub uses this parameter for real: it opens
// `/auth?redirect=%2F%3Fq%3D<prompt>` so a question typed over there arrives in
// a new chat here. That is a same-site path with a query string, which is
// exactly what is allowed through.

export const MAX_REDIRECT_LENGTH = 2048;

// Only used to resolve the candidate; never navigated to.
const RESOLVE_BASE = 'https://redirect.invalid';

/**
 * A same-site `path[?query][#hash]`, or `fallback` when the candidate is
 * anything else (absolute URL, protocol-relative `//host`, `javascript:`,
 * control characters, oversized).
 */
export const safeRedirectPath = (value: unknown, fallback = '/'): string => {
	if (typeof value !== 'string' || !value || value.length > MAX_REDIRECT_LENGTH) {
		return fallback;
	}

	// Browsers strip tabs and newlines out of URLs before parsing them, so
	// "/\thttps://evil.example" is a foreign address wearing a leading slash.
	// Control characters have no business in a path either way.
	// eslint-disable-next-line no-control-regex
	if (/[\u0000- \u007f]/.test(value)) {
		return fallback;
	}

	// A backslash is a slash to every browser: "/\evil.example" is "//evil.example".
	if (value[0] !== '/' || value[1] === '/' || value.includes('\\')) {
		return fallback;
	}

	let url: URL;
	try {
		url = new URL(value, RESOLVE_BASE);
	} catch {
		return fallback;
	}

	// `..` segments resolve away here; an origin change cannot survive the checks
	// above, but confirm rather than assume.
	if (url.origin !== RESOLVE_BASE || !url.pathname.startsWith('/')) {
		return fallback;
	}

	return `${url.pathname}${url.search}${url.hash}`;
};
