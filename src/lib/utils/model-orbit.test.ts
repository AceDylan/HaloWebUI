import { describe, expect, it } from 'vitest';

import {
	isMonoIcon,
	orbitAccent,
	orbitBend,
	orbitFrame,
	orbitGreetingWidth,
	orbitLabelSide,
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

	it('puts five models upper left, upper right, lower left, right and bottom', () => {
		const at = orbitSlots(5).map((angle) => orbitPoint(wide, angle));
		const [ul, ur, ll, r, bottom] = at;
		expect(ul.x).toBeLessThan(wide.cx);
		expect(ul.y).toBeLessThan(wide.cy);
		expect(ur.x).toBeGreaterThan(wide.cx);
		expect(ur.y).toBeLessThan(wide.cy);
		expect(ll.x).toBeLessThan(wide.cx);
		expect(ll.y).toBeGreaterThan(wide.cy);
		expect(r.x).toBeGreaterThan(wide.cx);
		expect(r.y).toBeGreaterThan(wide.cy);
		expect(Math.round(bottom.x)).toBe(wide.cx);
		expect(bottom.y).toBeGreaterThan(Math.max(ll.y, r.y));
	});

	it('keeps every node and wide label inside the stage', () => {
		for (const [w, h] of [[992, 496], [358, 448], [760, 448], [852, 448], [1024, 496]]) {
			for (const count of [1, 2, 3, 4, 5, 6, 7]) {
				const frame = orbitFrame(w, h, count);
				for (const angle of orbitSlots(count)) {
					const p = orbitPoint(frame, angle);
					const side = orbitLabelSide(angle, frame.compact);
					const reach = frame.node / 2 + (frame.compact || side === 'right' ? 0 : 172);
					expect(p.x - reach).toBeGreaterThanOrEqual(0);
					expect(p.y + frame.node / 2).toBeLessThanOrEqual(frame.h);
				}
			}
		}
	});

	it('labels stand outward on wide stages, under the nodes on compact ones', () => {
		expect(orbitSlots(5).map((a) => orbitLabelSide(a, false))).toEqual([
			'left',
			'right',
			'left',
			'right',
			'right'
		]);
		expect(orbitSlots(5).map((a) => orbitLabelSide(a, true))).toEqual([
			'below',
			'below',
			'below',
			'below',
			'right'
		]);
	});

	it('spreads more models than the table knows without using the top', () => {
		const angles = orbitSlots(9);
		expect(angles).toHaveLength(9);
		for (const angle of angles) expect(Math.sin((angle * Math.PI) / 180)).toBeGreaterThan(-0.95);
	});

	it('draws links from the core edge to the node', () => {
		const to = orbitPoint(wide, -145);
		expect(orbitLink(wide, to)).toMatch(/^M[\d.]+ [\d.]+Q[\d.-]+ [\d.-]+ [\d.]+ [\d.]+$/);
	});

	it('walks the slots clockwise from the upper left', () => {
		// slots: UL, UR, LL, R, bottom → UL, UR, R, bottom, LL
		expect(orbitOrder(orbitSlots(5))).toEqual([0, 1, 3, 4, 2]);
	});

	it('bends a flight off the straight line, to either side', () => {
		const a = { x: 0, y: 0 };
		const b = { x: 100, y: 0 };
		expect(orbitBend(a, b, 0.2)).toEqual({ x: 50, y: 20 });
		expect(orbitBend(a, b, -0.2)).toEqual({ x: 50, y: -20 });
	});

	it('narrows the greeting between the lower nodes only when there are some', () => {
		expect(orbitGreetingWidth(wide, orbitSlots(5))).toBeLessThan(wide.w);
		expect(orbitGreetingWidth(wide, orbitSlots(2))).toBe(wide.w - 16);
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
		expect(second).toEqual({ core: 'gemini', ring: ['gpt-chat', 'deepseek', 'gpt-image', 'hermes', 'claude'] });
		const third = seatModels(ids, 'gpt-chat', second);
		expect(third).toEqual({ core: 'gpt-chat', ring: ['gemini', 'deepseek', 'gpt-image', 'hermes', 'claude'] });
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
