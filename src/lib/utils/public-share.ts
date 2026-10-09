/**
 * Shared-chat links (`/s/<id>`) open without signing in: the page shows that one
 * conversation and nothing else, so the sign-in redirect skips it.
 */
export const isPublicSharePath = (pathname: string | null | undefined): boolean =>
	/^\/s\/[^/]+\/?$/.test(String(pathname ?? ''));
