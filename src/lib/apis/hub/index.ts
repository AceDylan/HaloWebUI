import { WEBUI_API_BASE_URL } from '$lib/constants';

export type HubHandshake = {
	/** true: the Hub accepts our tickets; false: it refuses them; null: unknown (unreachable / not configured). */
	ok: boolean | null;
	reason: string;
	checked_at: number | null;
	/** Origins the Hub allows to frame it, as reported by the Hub itself. */
	frame_ancestors: string[] | null;
};

export type HubEmbed = {
	hub_url: string;
	/** Address for the iframe; carries a single-use sign-in ticket when `sso` is true. */
	url: string;
	sso: boolean;
	handshake: HubHandshake;
};

/**
 * Ask the backend for the Bookmark Hub address. Admins only. Every call mints
 * a fresh single-use ticket (valid for two minutes), so call it right before
 * pointing an iframe or a new tab at the result and never cache it.
 */
export const createHubEmbed = async (token: string): Promise<HubEmbed> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/hub/embed`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	});

	if (!res.ok) {
		const body = await res.json().catch(() => null);
		throw new Error(body?.detail ?? `HTTP ${res.status}`);
	}

	return res.json();
};

/**
 * Open the Hub in a new tab, signed in. The tab is opened synchronously (while
 * the click still counts as a user gesture) and pointed at the Hub once the
 * ticket arrives; `fallbackUrl` is used when no ticket can be had.
 */
export const openHubInNewTab = async (token: string, fallbackUrl?: string | null) => {
	const tab = window.open('about:blank', '_blank');
	let url = fallbackUrl ?? null;
	try {
		url = (await createHubEmbed(token)).url;
	} catch (error) {
		console.error('hub embed:', error);
	}

	if (!url) {
		tab?.close();
		return false;
	}
	if (tab) {
		tab.opener = null;
		tab.location.replace(url);
	} else {
		// Pop-up blocked: a plain navigation of a new tab is still allowed from a link click.
		window.open(url, '_blank', 'noopener');
	}
	return true;
};
