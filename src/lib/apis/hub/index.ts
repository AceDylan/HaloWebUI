import { WEBUI_API_BASE_URL } from '$lib/constants';

/**
 * Trade the single-use ticket the Bookmark Hub put in the frame's address for a
 * session. Resolves to the same shape as a password sign-in; throws the
 * server's `detail` (`{ error, reason }`) when the ticket is refused.
 */
export const exchangeHubTicket = async (ticket: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/hub/session`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json'
		},
		credentials: 'include',
		body: JSON.stringify({ ticket })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err?.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
