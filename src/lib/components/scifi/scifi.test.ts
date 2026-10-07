import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	BOOT_EVERY_MS,
	BOOT_KEY,
	isSectionJump,
	scifiEnabled,
	shouldBoot,
	markBooted,
	WARP_EVENT,
	warp
} from './scifi';

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

describe('page jumps', () => {
	it('streak the stars between parts of the app, not within one', () => {
		expect(isSectionJump('/', '/settings/interface')).toBe(true);
		expect(isSectionJump('/discuss', '/teams')).toBe(true);
		expect(isSectionJump('/', '/c/abc')).toBe(true);
		expect(isSectionJump('/c/abc', '/c/def')).toBe(false);
		expect(isSectionJump('/settings/interface', '/settings/account')).toBe(false);
		expect(isSectionJump(undefined, '/teams')).toBe(false);
	});
});

describe('panel spotlight', () => {
	it('puts the mouse position on the panel under it, mouse only, once a frame', async () => {
		const { trackSpotlight } = await import('./scifi');
		const frames: FrameRequestCallback[] = [];
		vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => frames.push(cb));
		vi.stubGlobal('cancelAnimationFrame', () => {});
		let handler: (e: unknown) => void = () => {};
		const root = {
			addEventListener: (_: string, h: (e: unknown) => void) => (handler = h),
			removeEventListener: vi.fn()
		};
		const props = new Map<string, string>();
		const panel = {
			getBoundingClientRect: () => ({ left: 100, top: 40 }),
			style: { setProperty: (k: string, v: string) => props.set(k, v) }
		};
		const target = { closest: () => panel };
		const stop = trackSpotlight(root as never);
		handler({ pointerType: 'touch', target, clientX: 0, clientY: 0 });
		expect(frames.length).toBe(0);
		handler({ pointerType: 'mouse', target, clientX: 150, clientY: 60 });
		handler({ pointerType: 'mouse', target, clientX: 160.4, clientY: 70 });
		expect(frames.length).toBe(1);
		frames[0](0);
		expect(props.get('--sf-x')).toBe('60px');
		expect(props.get('--sf-y')).toBe('30px');
		stop();
		expect(root.removeEventListener).toHaveBeenCalled();
	});
});
