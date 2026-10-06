import agentsData from '$lib/data/agents-zh.json';

export type ChatAssistantSnapshot = {
	id: string;
	name: string;
	emoji: string;
	prompt: string;
	description?: string | null;
};

export const PENDING_ASSISTANT_STORAGE_KEY = 'pendingAssistant';
// Where the home page kept its featured template ids before favourites moved to the server
// (utils/assistant-favorites.ts); read once for the migration.
export const FEATURED_STORAGE_KEY = 'featuredAssistantIds';
export const MAX_FEATURED_ASSISTANTS = 6;

export const FEATURED_ASSISTANT_IDS = ['1', '15', '14', '10', '11', '9'] as const;

const normalizeString = (value: unknown) =>
	typeof value === 'string' && value.trim() !== '' ? value.trim() : null;

const VALID_ASSISTANT_IDS = new Set(
	(agentsData as Array<Record<string, unknown>>)
		.map((agent) => normalizeString(agent.id))
		.filter(Boolean)
);

const decodeTokenUserId = (token: unknown): string | null => {
	if (typeof token !== 'string') {
		return null;
	}

	try {
		const parts = token.split('.');
		if (parts.length < 2) {
			return null;
		}

		const payload = parts[1];
		if (!payload) {
			return null;
		}

		const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
		const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), '=');
		const decoded = JSON.parse(atob(padded));
		return normalizeString(decoded?.id);
	} catch {
		return null;
	}
};

const getAssistantStorageUserScope = () => {
	if (typeof localStorage === 'undefined') {
		return 'anonymous';
	}

	return decodeTokenUserId(localStorage.token) ?? 'anonymous';
};

const buildFeaturedStorageKey = () => `${FEATURED_STORAGE_KEY}::${getAssistantStorageUserScope()}`;

const normalizeFeaturedAssistantIds = (value: unknown): string[] => {
	if (!Array.isArray(value)) {
		return [];
	}

	const seen = new Set<string>();
	const normalized: string[] = [];

	for (const item of value) {
		const id = normalizeString(item);
		if (!id || !VALID_ASSISTANT_IDS.has(id) || seen.has(id)) {
			continue;
		}
		seen.add(id);
		normalized.push(id);
		if (normalized.length >= MAX_FEATURED_ASSISTANTS) {
			break;
		}
	}

	return normalized;
};

/** The featured ids this browser stored before favourites moved to the server, or null when it
 * never stored any (then the defaults apply). Read once, for the migration. */
export const readLegacyFeaturedAssistantIds = (): string[] | null => {
	if (typeof localStorage === 'undefined') {
		return null;
	}

	try {
		const rawValue =
			localStorage.getItem(buildFeaturedStorageKey()) ?? localStorage.getItem(FEATURED_STORAGE_KEY);
		if (!rawValue) {
			return null;
		}
		return normalizeFeaturedAssistantIds(JSON.parse(rawValue));
	} catch {
		return null;
	}
};

export const toChatAssistantSnapshot = (
	value: Record<string, unknown> | null | undefined
): ChatAssistantSnapshot | null => {
	if (!value) {
		return null;
	}

	const id = normalizeString(value.id);
	const name = normalizeString(value.name);
	const prompt = normalizeString(value.prompt);

	if (!id || !name || !prompt) {
		return null;
	}

	return {
		id,
		name,
		emoji: normalizeString(value.emoji) ?? '🤖',
		prompt,
		description: normalizeString(value.description)
	};
};

/** A built-in template by id (`'15'` or `'builtin:15'`). */
export const findBuiltinAssistant = (id: string): Record<string, unknown> | null => {
	const key = String(id ?? '').replace(/^builtin:/, '');
	return (
		((agentsData as Array<Record<string, unknown>>).find((agent) => agent.id === key) as
			| Record<string, unknown>
			| undefined) ?? null
	);
};

/** A user assistant from the library (GET /api/v1/assistant-library) as a chat assistant: its
 * prompt goes on the chat's current model like a template's. */
export const libraryEntryToSnapshot = (
	entry: { ref?: string; id?: string; name?: string; emoji?: string; prompt?: string; description?: string } | null | undefined
): ChatAssistantSnapshot | null => {
	if (!entry) {
		return null;
	}

	return toChatAssistantSnapshot({
		id: entry.ref ?? (entry.id ? `model:${entry.id}` : null),
		name: entry.name,
		emoji: entry.emoji || '🤖',
		prompt: entry.prompt,
		description: entry.description
	});
};
