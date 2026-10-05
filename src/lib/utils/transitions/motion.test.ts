import { afterEach, describe, expect, it, vi } from 'vitest';
import { flyAndScale, DUR } from './index';

afterEach(() => vi.unstubAllGlobals());
describe('Halo menu motion', () => {
	it('uses only opacity when the user reduces motion', () => {
		vi.stubGlobal('window', { matchMedia: () => ({ matches: true }) });
		const t = flyAndScale({} as Element) as { duration: number; css: (t: number) => string };
		expect(t.duration).toBeLessThanOrEqual(160);
		expect(t.css(0.5)).toBe('opacity:0.5');
	});
	it('keeps frequent interactions under 250ms and exits faster', () => {
		vi.stubGlobal('getComputedStyle', () => ({ transform: 'none' }));
		const enter = flyAndScale({} as Element) as { duration: number; css: (t: number) => string };
		const exit = flyAndScale({} as Element, undefined, { direction: 'out' }) as {
			duration: number;
		};
		expect(enter.duration).toBeLessThanOrEqual(250);
		expect(exit.duration).toBeLessThan(enter.duration);
		expect(enter.css(1)).toContain('scale(1)');
		expect(DUR.hero).toBeLessThanOrEqual(600);
	});
});

import { acceptHubEnter } from '../hub-embed';
describe('Hub scene messages', () => {
	const parent = {},
		win = { parent },
		origin = 'https://hub.example.com';
	const event = { source: parent, origin, data: { source: 'hub', type: 'enter' } };
	it('accepts an enter only from the configured parent', () => {
		expect(acceptHubEnter(event, origin, win, null)).toBe(true);
		expect(acceptHubEnter({ ...event, source: {} }, origin, win, null)).toBe(false);
		expect(
			acceptHubEnter({ ...event, origin: 'https://other.example.com' }, origin, win, null)
		).toBe(false);
		expect(acceptHubEnter(event, '', win, null)).toBe(false);
	});
});
