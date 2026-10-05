import { afterEach, describe, expect, it, vi } from 'vitest';
import { BOOT_EVERY_MS, BOOT_KEY, scifiEnabled, shouldBoot, markBooted, WARP_EVENT, warp } from './scifi';

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
	it('play at most every 6 hours, never framed, never with reduced motion', () => {
		const local = storage();
		vi.stubGlobal('localStorage', local);
		vi.stubGlobal('window', { matchMedia: () => ({ matches: false }) });
		const t0 = 1_000_000_000_000;
		expect(shouldBoot(true, t0)).toBe(false);
		expect(shouldBoot(false, t0)).toBe(true);
		markBooted(t0);
		expect(local.getItem(BOOT_KEY)).toBe(String(t0));
		expect(shouldBoot(false, t0 + 60_000)).toBe(false);
		expect(shouldBoot(false, t0 + BOOT_EVERY_MS)).toBe(true);
		vi.stubGlobal('localStorage', storage());
		vi.stubGlobal('window', { matchMedia: () => ({ matches: true }) });
		expect(shouldBoot(false, t0)).toBe(false);
	});
	it('warp announces itself with its length', () => {
		const seen: unknown[] = [];
		vi.stubGlobal('window', { dispatchEvent: (e: CustomEvent) => seen.push([e.type, e.detail]) });
		warp(500);
		expect(seen).toEqual([[WARP_EVENT, { ms: 500 }]]);
	});
});
