// Favourite assistants, kept on the server in the user's settings (`ui.assistantFavorites`, a list
// of `model:<id>` / `builtin:<id>` refs). The home page's 精选助手 shows the first few; the
// workspace stars them. Before this the home page kept built-in ids in localStorage; the first
// read moves those over (or the defaults when the browser had none).
import { get } from 'svelte/store';

import { settings } from '$lib/stores';
import { saveUserSettingsPatch } from '$lib/utils/user-settings';
import {
	FEATURED_ASSISTANT_IDS,
	FEATURED_STORAGE_KEY,
	readLegacyFeaturedAssistantIds
} from '$lib/utils/chat-assistants';

export const FAVORITES_SETTINGS_KEY = 'assistantFavorites';

const REF_RE = /^(model|builtin):\S/;

export const normalizeFavoriteRefs = (value: unknown): string[] => {
	if (!Array.isArray(value)) return [];
	const seen = new Set<string>();
	const out: string[] = [];
	for (const item of value) {
		const ref = typeof item === 'string' ? item.trim() : '';
		if (!REF_RE.test(ref) || seen.has(ref)) continue;
		seen.add(ref);
		out.push(ref);
	}
	return out;
};

export const defaultFavoriteRefs = () => FEATURED_ASSISTANT_IDS.map((id) => `builtin:${id}`);

/** The favourites to use: the saved list, or — when the user has none saved yet — the old
 * featured ids of this browser as built-in refs, else the defaults. `migrated` says it must be
 * saved. */
export const migrateFavoriteRefs = (
	saved: unknown,
	legacyIds: string[] | null
): { refs: string[]; migrated: boolean } => {
	if (Array.isArray(saved)) return { refs: normalizeFavoriteRefs(saved), migrated: false };
	const ids = legacyIds ?? [...FEATURED_ASSISTANT_IDS];
	return { refs: normalizeFavoriteRefs(ids.map((id) => `builtin:${id}`)), migrated: true };
};

export const toggleFavoriteRef = (refs: string[], ref: string): string[] =>
	refs.includes(ref) ? refs.filter((r) => r !== ref) : [...refs, ref];

/** Favourites first (in favourite order), the rest as they were. */
export const sortFavoritesFirst = <T>(items: T[], refOf: (item: T) => string, refs: string[]): T[] => {
	const rank = new Map(refs.map((ref, index) => [ref, index]));
	return items
		.map((item, index) => ({ item, index, rank: rank.get(refOf(item)) }))
		.sort((a, b) => {
			const ra = a.rank ?? Number.POSITIVE_INFINITY;
			const rb = b.rank ?? Number.POSITIVE_INFINITY;
			return ra === rb ? a.index - b.index : ra - rb;
		})
		.map((entry) => entry.item);
};

const clearLegacyFeatured = () => {
	if (typeof localStorage === 'undefined') return;
	try {
		for (const key of Object.keys(localStorage)) {
			if (key === FEATURED_STORAGE_KEY || key.startsWith(`${FEATURED_STORAGE_KEY}::`)) {
				localStorage.removeItem(key);
			}
		}
	} catch {
		// Storage unavailable: the server list wins anyway.
	}
};

/** Save the whole list (optimistically into the settings store). Throws when the save fails;
 * the store is put back unless the server answered with a newer revision. */
export const saveFavoriteRefs = async (refs: string[]): Promise<string[]> => {
	const previous = get(settings) ?? {};
	const next = normalizeFavoriteRefs(refs);
	settings.set({ ...(previous as any), [FAVORITES_SETTINGS_KEY]: next });
	try {
		await saveUserSettingsPatch(localStorage.token, { [FAVORITES_SETTINGS_KEY]: next });
	} catch (error) {
		if ((error as { status?: number })?.status !== 409) settings.set(previous as any);
		throw error;
	}
	return next;
};

let migration: Promise<string[]> | null = null;

/** The current favourites, moving the old localStorage list to the server the first time. */
export const ensureFavoriteRefs = async (): Promise<string[]> => {
	const saved = (get(settings) as any)?.[FAVORITES_SETTINGS_KEY];
	const { refs, migrated } = migrateFavoriteRefs(saved, readLegacyFeaturedAssistantIds());
	if (!migrated) return refs;
	if (!migration) {
		migration = saveFavoriteRefs(refs)
			.then((savedRefs) => {
				clearLegacyFeatured();
				return savedRefs;
			})
			// Not saved this time (offline, conflict): use the seeded list, try again next read.
			.catch(() => refs)
			.finally(() => {
				migration = null;
			});
	}
	return migration;
};

/** Star / unstar one ref. Returns the new list. */
export const toggleFavorite = async (ref: string): Promise<string[]> => {
	const current = await ensureFavoriteRefs();
	return saveFavoriteRefs(toggleFavoriteRef(current, ref));
};
