// Full-ring geometry: sample every five degrees to cover moving nodes and their labels.
import { describe, expect, it } from 'vitest';

import {
	isMonoIcon,
	orbitAccent,
	orbitBend,
	orbitFrame,
	orbitLink,
	orbitOrder,
	orbitPoint,
	orbitSlots,
	seatModels
} from './model-orbit';

describe('orbitAccent', () => {
	it('gives every model of the landing page its colour family', () => {
		expect(orbitAccent('hermes-agent', 'agent')).toBe('agent');
		expect(orbitAccent('gpt-image', 'image')).toBe('image');
		expect(orbitAccent('gpt-chat', 'chat')).toBe('gpt');
		expect(orbitAccent('deepseek-chat', 'chat')).toBe('deepseek');
		expect(orbitAccent('gemini-chat', 'chat')).toBe('gemini');
		expect(orbitAccent('claude-chat', 'chat')).toBe('claude');
		expect(orbitAccent('qwen-max', 'chat')).toBe('plain');
	});
});

describe('isMonoIcon', () => {
	it('knows the one-colour model icons', () => {
		expect(isMonoIcon('/static/model-icons/openai.svg')).toBe(true);
		// a portrait stays a picture
		expect(isMonoIcon('/static/model-icons/noushermes.svg')).toBe(false);
		expect(isMonoIcon('/static/model-icons/gemini-color.svg?v=2')).toBe(false);
		expect(isMonoIcon('data:image/png;base64,AAAA')).toBe(false);
		expect(isMonoIcon(null)).toBe(false);
	});
});

describe('orbit layout', () => {
	const wide = orbitFrame(992, 496);
	const phone = orbitFrame(358, 448);

	it('switches to the compact layout on narrow stages', () => {
		expect(wide.compact).toBe(false);
		expect(phone.compact).toBe(true);
		expect(phone.node).toBeLessThan(wide.node);
		expect(phone.core).toBeLessThan(wide.core);
	});

	it('spaces every count evenly around the whole core, starting directly above it', () => {
		expect(orbitSlots(0)).toEqual([]);
		for (const count of [1, 2, 4, 5, 6, 7, 9]) {
			const angles = orbitSlots(count);
			expect(angles).toHaveLength(count);
			expect(angles[0]).toBe(-90);
			angles.forEach((angle, i) => expect(angle).toBeCloseTo(-90 + (360 / count) * i));
			const top = orbitPoint(wide, angles[0]);
			expect(top.x).toBeCloseTo(wide.cx);
			expect(top.y).toBeLessThan(wide.cy);
		}
		expect(wide.coreY).toBe(wide.cy);
		expect(phone.coreY).toBe(phone.cy);
	});

	const overlaps = (a: number[], b: number[]) =>
		a[0] < b[2] && a[2] > b[0] && a[1] < b[3] && a[3] > b[1];

	it.each([
		[1100, 440],
		[390, 400],
		[358, 400],
		[760, 400],
		[992, 448],
		[358, 272]
	])(
		'keeps spheres and labels separated and inside a %ix%i stage throughout a revolution',
		(w, h) => {
			for (let count = 4; count <= 7; count++) {
				const f = orbitFrame(w, h, count);
				// Include maximum depth, hover enlargement and the floating sphere's travel.
				const sphere = f.node * 0.57 + 5 * f.unit;
				const halfWidth = Math.max(f.labelWidth / 2, sphere);
				const bottom = f.node / 2 + f.labelGap + f.labelHeight;
				const halo = f.core / 2 + f.coreHalo;
				const core = [f.cx - halo, f.cy - halo, f.cx + halo, f.cy + halo];
				const tag = [
					f.cx - halo,
					f.cy + f.core / 2 + 8 * f.unit,
					f.cx + halo,
					f.cy + f.core / 2 + 8 * f.unit + f.coreTagHeight
				];
				for (let spin = 0; spin <= 360; spin += 5) {
					const bounds = orbitSlots(count).map((angle) => {
						const p = orbitPoint(f, angle + spin);
						return [p.x - halfWidth, p.y - sphere, p.x + halfWidth, p.y + bottom];
					});
					const context = `${w}x${h}, n=${count}, spin=${spin}`;
					bounds.forEach((box, i) => {
						expect(box[0], context).toBeGreaterThanOrEqual(0);
						expect(box[1], context).toBeGreaterThanOrEqual(0);
						expect(box[2], context).toBeLessThanOrEqual(w);
						expect(box[3], context).toBeLessThanOrEqual(h);
						expect(overlaps(box, core), `${context}, core vs ${i}`).toBe(false);
						expect(overlaps(box, tag), `${context}, core tag vs ${i}`).toBe(false);
						bounds
							.slice(i + 1)
							.forEach((other, j) =>
								expect(overlaps(box, other), `${context}, ${i} vs ${i + j + 1}`).toBe(false)
							);
					});
				}
			}
		}
	);

	it('draws links from the core edge to the node', () => {
		const to = orbitPoint(wide, -145);
		expect(orbitLink(wide, to)).toMatch(/^M[\d.]+ [\d.]+Q[\d.-]+ [\d.-]+ [\d.]+ [\d.]+$/);
	});

	it('walks clockwise from the top using the current rotated angles', () => {
		expect(orbitOrder(orbitSlots(5))).toEqual([0, 1, 2, 3, 4]);
		expect(orbitOrder(orbitSlots(5).map((angle) => angle + 90))).toEqual([4, 0, 1, 2, 3]);
		expect(orbitOrder([-450, 0, 450, 180])).toEqual([0, 1, 2, 3]);
	});

	it('bends a flight off the straight line, to either side', () => {
		const a = { x: 0, y: 0 };
		const b = { x: 100, y: 0 };
		expect(orbitBend(a, b, 0.2)).toEqual({ x: 50, y: 20 });
		expect(orbitBend(a, b, -0.2)).toEqual({ x: 50, y: -20 });
	});
});

describe('seatModels', () => {
	const ids = ['hermes', 'gpt-chat', 'deepseek', 'gpt-image', 'gemini', 'claude'];

	it('seats the target in the core and deals the rest in deck order', () => {
		expect(seatModels(ids, 'hermes', null)).toEqual({
			core: 'hermes',
			ring: ['gpt-chat', 'deepseek', 'gpt-image', 'gemini', 'claude']
		});
		expect(seatModels(ids, 'gone', null).core).toBe('hermes');
		// opened with gemini chosen: the home seating with gemini swapped in
		expect(seatModels(ids, 'gemini', null, 'hermes')).toEqual({
			core: 'gemini',
			ring: ['gpt-chat', 'deepseek', 'gpt-image', 'hermes', 'claude']
		});
		expect(seatModels([], 'hermes', null)).toEqual({ core: '', ring: [] });
	});

	it('swaps the picked model with the core and leaves the others where they are', () => {
		const first = seatModels(ids, 'hermes', null);
		const second = seatModels(ids, 'gemini', first);
		expect(second).toEqual({
			core: 'gemini',
			ring: ['gpt-chat', 'deepseek', 'gpt-image', 'hermes', 'claude']
		});
		const third = seatModels(ids, 'gpt-chat', second);
		expect(third).toEqual({
			core: 'gpt-chat',
			ring: ['gemini', 'deepseek', 'gpt-image', 'hermes', 'claude']
		});
		// nothing to do: the same seating comes back
		expect(seatModels(ids, 'gpt-chat', third)).toBe(third);
	});

	it('deals afresh when the models change', () => {
		const first = seatModels(ids, 'gemini', seatModels(ids, 'hermes', null));
		expect(seatModels([...ids, 'qwen'], 'gemini', first, 'hermes')).toEqual({
			core: 'gemini',
			ring: ['gpt-chat', 'deepseek', 'gpt-image', 'hermes', 'claude', 'qwen']
		});
	});
});
