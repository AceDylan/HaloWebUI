// The new-chat landing page's model orbit: a centred core and evenly spaced nodes circling
// clockwise on a full ellipse. Labels stay below each node; the greeting lives outside the
// stage. Pure geometry and seating, shared with ModelOrbit.svelte and its layout tests.
// Angles are degrees: -90 is up, 0 is right, 90 is down (screen y grows downward).

import { DARK_MODE_INVERT_ICONS } from './model-icons.manifest';
import type { DeckKind } from './model-deck';

/** Each node's colour family (halo-orbit.css, [data-accent]). */
export type OrbitAccent = 'agent' | 'image' | 'gpt' | 'deepseek' | 'gemini' | 'claude' | 'plain';

export const orbitAccent = (name: string, kind: DeckKind): OrbitAccent => {
	if (kind === 'agent') return 'agent';
	if (kind === 'image') return 'image';
	const key = name.toLowerCase();
	if (key.includes('deepseek')) return 'deepseek';
	if (key.includes('gemini')) return 'gemini';
	if (key.includes('claude')) return 'claude';
	if (key.includes('gpt') || key.includes('openai')) return 'gpt';
	return 'plain';
};

// One-colour, but a drawn portrait (Hermes): as a flat glyph it would turn into a silhouette.
const PORTRAIT_ICONS = new Set(['noushermes.svg']);

/** One-colour icons (OpenAI's knot…) are drawn as a glyph in the node's own colours instead. */
export const isMonoIcon = (src: string | null | undefined): boolean => {
	const file = (src ?? '').split(/[?#]/)[0].split('/').at(-1) ?? '';
	return (
		!!file &&
		(src ?? '').includes('/static/model-icons/') &&
		DARK_MODE_INVERT_ICONS.has(file) &&
		!PORTRAIT_ICONS.has(file)
	);
};

/** Below this stage width the nodes and their labels use the smaller size budget. */
export const ORBIT_COMPACT_BELOW = 760;

export type OrbitFrame = {
	compact: boolean;
	w: number;
	h: number;
	cx: number;
	cy: number;
	rx: number;
	ry: number;
	/** Diameters of the core's avatar and of a node, px. */
	core: number;
	node: number;
	/** Shared CSS budgets, scaled down together on short or narrow stages. */
	unit: number;
	labelWidth: number;
	labelHeight: number;
	labelGap: number;
	coreHalo: number;
	coreTagHeight: number;
	/** Height of the core's centre. */
	coreY: number;
};

/** Full ring, starting at twelve o'clock and proceeding clockwise. */
export const orbitSlots = (count: number): number[] =>
	Array.from({ length: count }, (_, i) => -90 + (360 / count) * i);

const rad = (deg: number) => (deg * Math.PI) / 180;

export const orbitPoint = (frame: OrbitFrame, angle: number) => ({
	x: frame.cx + frame.rx * Math.cos(rad(angle)),
	y: frame.cy + frame.ry * Math.sin(rad(angle))
});

/** Reserve the whole label at the bottom, even when a node passes six o'clock. */
export const orbitFrame = (w: number, h: number, count = 5): OrbitFrame => {
	const compact = w < ORBIT_COMPACT_BELOW;
	const unit = Math.min(1, w / (compact ? 390 : 760), h / (compact ? 400 : 440));
	const node = (compact ? 40 : 56) * unit;
	const core = (compact ? 64 : 88) * unit;
	// Denser rings shorten labels instead of moving seats as they revolve.
	const labelWidth =
		Math.min(compact ? 84 : 132, (compact ? 504 : 812) / Math.max(6, count)) * unit;
	const labelHeight = (compact ? 28 : 34) * unit;
	const labelGap = 10 * unit;
	const coreHalo = 14 * unit;
	const coreTagHeight = (compact ? 28 : 34) * unit;
	const cx = w / 2;
	const cy = h / 2;
	const rx = Math.min(w * 0.42, cx - Math.max(labelWidth / 2, node * 0.84) - 8 * unit);
	const ry = cy - node / 2 - labelGap - labelHeight - 8 * unit;
	return {
		compact,
		w,
		h,
		cx,
		cy,
		rx,
		ry,
		core,
		node,
		coreY: cy,
		unit,
		labelWidth,
		labelHeight,
		labelGap,
		coreHalo,
		coreTagHeight
	};
};

const round = (n: number) => Math.round(n * 10) / 10;

/** The core's link to a node: from the core's edge to the node's, bowed slightly outward. */
export const orbitLink = (frame: OrbitFrame, to: { x: number; y: number }): string => {
	const dx = to.x - frame.cx;
	const dy = to.y - frame.coreY;
	const len = Math.hypot(dx, dy) || 1;
	const [ux, uy] = [dx / len, dy / len];
	const start = {
		x: frame.cx + ux * (frame.core / 2 + 14),
		y: frame.coreY + uy * (frame.core / 2 + 14)
	};
	const end = { x: to.x - ux * (frame.node / 2 + 8), y: to.y - uy * (frame.node / 2 + 8) };
	// bow away from the vertical axis, so the links fan out like spokes of a wheel
	const bow = len * 0.12 * (ux < 0 ? -1 : 1);
	const mid = { x: (start.x + end.x) / 2 + uy * bow * -1, y: (start.y + end.y) / 2 + ux * bow };
	return `M${round(start.x)} ${round(start.y)}Q${round(mid.x)} ${round(mid.y)} ${round(end.x)} ${round(end.y)}`;
};

/** Who sits where: the core (the chosen model) and the ring, slot by slot. */
export type OrbitSeating = { core: string; ring: string[] };

/**
 * The seating for `ids` with `target` in the core. When only the core changes, the new core's
 * seat goes to the old core (a swap, so the other models stay put). A fresh deal starts from the
 * home seating (`home` in the core, the rest in deck order) and swaps the target in, so a page
 * opened with a model already chosen looks the way the swap left it.
 */
export const seatModels = (
	ids: string[],
	target: string,
	prev: OrbitSeating | null,
	home: string = ids[0]
): OrbitSeating => {
	if (!ids.length) return { core: '', ring: [] };
	const core = ids.includes(target) ? target : ids[0];
	const seated = prev ? [prev.core, ...prev.ring] : [];
	const sameModels =
		!!prev?.core && seated.length === ids.length && ids.every((id) => seated.includes(id));
	const base: OrbitSeating = sameModels
		? prev!
		: (() => {
				const centre = ids.includes(home) ? home : ids[0];
				return { core: centre, ring: ids.filter((id) => id !== centre) };
			})();
	if (base.core === core) return base;
	return { core, ring: base.ring.map((id) => (id === core ? base.core : id)) };
};

/** Slot indices clockwise from twelve o'clock at their current angles. */
export const orbitOrder = (angles: number[]): number[] =>
	angles
		.map((angle, index) => ({ index, key: (((angle + 90) % 360) + 360) % 360 }))
		.sort((a, b) => a.key - b.key)
		.map((slot) => slot.index);

/** A point off the straight line from `a` to `b`, so a model flies an arc, not a rail. */
export const orbitBend = (
	a: { x: number; y: number },
	b: { x: number; y: number },
	bend: number
) => {
	const dx = b.x - a.x;
	const dy = b.y - a.y;
	return { x: (a.x + b.x) / 2 - dy * bend, y: (a.y + b.y) / 2 + dx * bend };
};
