import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get, writable } from 'svelte/store';

const mocks = vi.hoisted(() => ({
	saveUserSettingsPatch: vi.fn()
}));

vi.mock('$lib/stores', () => ({ settings: writable<any>({}) }));
vi.mock('$lib/utils/user-settings', () => ({ saveUserSettingsPatch: mocks.saveUserSettingsPatch }));

import { settings } from '$lib/stores';
import {
	ensureFavoriteRefs,
	migrateFavoriteRefs,
	normalizeFavoriteRefs,
	sortFavoritesFirst,
	toggleFavorite,
	toggleFavoriteRef
} from './assistant-favorites';
import { FEATURED_ASSISTANT_IDS } from './chat-assistants';

const store = new Map<string, string>();
const localStorageStub = {
	getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
	setItem: (key: string, value: string) => void store.set(key, String(value)),
	removeItem: (key: string) => void store.delete(key),
	clear: () => store.clear(),
	key: (i: number) => [...store.keys()][i] ?? null,
	get length() {
		return store.size;
	}
};
// Object.keys(localStorage) lists the stored keys, like a real Storage.
const localStorageProxy = new Proxy(localStorageStub as any, {
	ownKeys: () => [...store.keys()],
	getOwnPropertyDescriptor: (target, key) =>
		typeof key === 'string' && store.has(key)
			? { enumerable: true, configurable: true, value: store.get(key) }
			: Reflect.getOwnPropertyDescriptor(target, key)
});
vi.stubGlobal('localStorage', localStorageProxy);

beforeEach(() => {
	store.clear();
	(settings as any).set({});
	mocks.saveUserSettingsPatch.mockReset();
	mocks.saveUserSettingsPatch.mockResolvedValue({});
});

describe('favourite refs', () => {
	it('keeps only well-formed, distinct refs', () => {
		expect(normalizeFavoriteRefs(['model:a', 'builtin:1', 'model:a', 'x', 3, 'model:', ' builtin:2 '])).toEqual([
			'model:a',
			'builtin:1',
			'builtin:2'
		]);
		expect(normalizeFavoriteRefs(null)).toEqual([]);
	});

	it('toggles and sorts favourites first in favourite order', () => {
		expect(toggleFavoriteRef(['model:a'], 'model:b')).toEqual(['model:a', 'model:b']);
		expect(toggleFavoriteRef(['model:a', 'model:b'], 'model:a')).toEqual(['model:b']);
		const rows = ['a', 'b', 'c', 'd'];
		expect(sortFavoritesFirst(rows, (id) => `model:${id}`, ['model:c', 'model:a'])).toEqual(['c', 'a', 'b', 'd']);
	});
});

describe('migrating the old featured list', () => {
	it('uses the saved list as it is', () => {
		expect(migrateFavoriteRefs(['model:x'], ['1'])).toEqual({ refs: ['model:x'], migrated: false });
		expect(migrateFavoriteRefs([], ['1'])).toEqual({ refs: [], migrated: false });
	});

	it('seeds from the browser list, else the defaults', () => {
		expect(migrateFavoriteRefs(undefined, ['15', '9'])).toEqual({
			refs: ['builtin:15', 'builtin:9'],
			migrated: true
		});
		expect(migrateFavoriteRefs(undefined, null)).toEqual({
			refs: FEATURED_ASSISTANT_IDS.map((id) => `builtin:${id}`),
			migrated: true
		});
	});

	it('saves the seeded list once and clears the old keys', async () => {
		store.set('featuredAssistantIds::anonymous', JSON.stringify(['14', '10']));
		const refs = await ensureFavoriteRefs();
		expect(refs).toEqual(['builtin:14', 'builtin:10']);
		expect(mocks.saveUserSettingsPatch).toHaveBeenCalledTimes(1);
		expect(mocks.saveUserSettingsPatch.mock.calls[0][1]).toEqual({
			assistantFavorites: ['builtin:14', 'builtin:10']
		});
		expect(get(settings as any)).toMatchObject({ assistantFavorites: ['builtin:14', 'builtin:10'] });
		expect(store.has('featuredAssistantIds::anonymous')).toBe(false);

		// Already on the server: nothing more to save.
		await ensureFavoriteRefs();
		expect(mocks.saveUserSettingsPatch).toHaveBeenCalledTimes(1);
	});

	it('still answers with the seeded list when the save fails', async () => {
		mocks.saveUserSettingsPatch.mockRejectedValue(new Error('offline'));
		const refs = await ensureFavoriteRefs();
		expect(refs).toEqual(FEATURED_ASSISTANT_IDS.map((id) => `builtin:${id}`));
		expect((get(settings as any) as any).assistantFavorites).toBeUndefined();
	});

	it('stars on top of the migrated list', async () => {
		(settings as any).set({ assistantFavorites: ['builtin:1'] });
		expect(await toggleFavorite('model:m1')).toEqual(['builtin:1', 'model:m1']);
		expect(await toggleFavorite('builtin:1')).toEqual(['model:m1']);
	});
});
