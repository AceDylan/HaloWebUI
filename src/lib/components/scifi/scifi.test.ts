import { afterEach, describe, expect, it, vi } from 'vitest';
import { BOOT_KEY, scifiEnabled, shouldBoot, markBooted, WARP_EVENT, warp } from './scifi';

const storage = () => {
	const m = new Map<string, string>();
	return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
};
afterEach(() => vi.unstubAllGlobals());

describe('sci-fi layer switch', () => {
	it('is on unless the user turned it off', () => {
		expect(scifiEnabled(null)).toBe(true);
		expect(scifiEnabled({})).toBe(true);
		expect(scifiEnabled({ scifiEffects: false })).toBe(false);
	});
});

describe('opening titles', () => {
	it('play once per session, never framed, never with reduced motion', () => {
		const session = storage();
		vi.stubGlobal('sessionStorage', session);
		vi.stubGlobal('window', { matchMedia: () => ({ matches: false }) });
		expect(shouldBoot(true)).toBe(false);
		expect(shouldBoot(false)).toBe(true);
		markBooted();
		expect(session.getItem(BOOT_KEY)).toBe('1');
		expect(shouldBoot(false)).toBe(false);
		vi.stubGlobal('sessionStorage', storage());
		vi.stubGlobal('window', { matchMedia: () => ({ matches: true }) });
		expect(shouldBoot(false)).toBe(false);
	});
	it('warp announces itself with its length', () => {
		const seen: unknown[] = [];
		vi.stubGlobal('window', { dispatchEvent: (e: CustomEvent) => seen.push([e.type, e.detail]) });
		warp(500);
		expect(seen).toEqual([[WARP_EVENT, { ms: 500 }]]);
	});
});
