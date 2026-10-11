// The new-chat landing page's model orbit (Placeholder/ModelOrbit.svelte): the agent is the core
// in the middle and the other models ride an ellipse around it. Pure geometry and naming, so the
// layout can be tested without a browser. Angles are degrees on the ellipse: 0 is right, 90 is
// straight down (screen y grows downward).

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

/** Below this stage width the labels go under the nodes and everything is smaller. */
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
	/** Height of the core's centre. */
	coreY: number;
};

// The top of the ellipse stays clear for the core. With five: upper left, upper right,
// lower left, right, bottom.
const SLOTS: Record<number, number[]> = {
	0: [],
	1: [-35],
	2: [-145, -35],
	3: [-145, -35, 90],
	4: [-145, -35, 155, 25],
	5: [-145, -35, 155, 25, 90],
	6: [-150, -30, 165, 15, 125, 55],
	7: [-150, -30, 165, 15, 125, 55, 90]
};

export const orbitSlots = (count: number): number[] =>
	SLOTS[count] ??
	// more than the deck ever deals: spread from upper right round the bottom to upper left
	Array.from({ length: count }, (_, i) => -40 + (260 / (count - 1)) * i);

const rad = (deg: number) => (deg * Math.PI) / 180;

export const orbitPoint = (frame: OrbitFrame, angle: number) => ({
	x: frame.cx + frame.rx * Math.cos(rad(angle)),
	y: frame.cy + frame.ry * Math.sin(rad(angle))
});

// Room a node's label needs beside it on wide stages (gap + label), px.
const LABEL_ROOM = 172;

/** The stage's frame for `count` nodes (their outermost slot decides the room the labels need). */
export const orbitFrame = (w: number, h: number, count = 5): OrbitFrame => {
	const compact = w < ORBIT_COMPACT_BELOW;
	const reach = Math.max(0.5, ...orbitSlots(count).map((a) => Math.abs(Math.cos(rad(a)))));
	const node = compact ? 48 : 68;
	const core = compact ? 80 : 112;
	const cx = w / 2;
	const cy = h / 2;
	// Wide: the outer nodes' labels stand beside them, so the ellipse leaves them that room.
	const rx = compact
		? Math.min(w * 0.4, cx - 52)
		: Math.min(w * 0.4, (cx - node / 2 - LABEL_ROOM) / reach);
	// The bottom node and its platform stay inside the stage.
	const ry = cy - node / 2 - 18;
	return { compact, w, h, cx, cy, rx, ry, core, node, coreY: cy - ry * (compact ? 0.32 : 0.3) };
};

/** Where a node's label stands: beside it, outward (wide), or under it (compact). */
export const orbitLabelSide = (angle: number, compact: boolean): 'left' | 'right' | 'below' => {
	const cos = Math.cos(rad(angle));
	const bottom = Math.abs(cos) < 0.25 && Math.sin(rad(angle)) > 0;
	if (bottom) return 'right';
	if (compact) return 'below';
	return cos < 0 ? 'left' : 'right';
};

const round = (n: number) => Math.round(n * 10) / 10;

/** The core's link to a node: from the core's edge to the node's, bowed slightly outward. */
export const orbitLink = (frame: OrbitFrame, to: { x: number; y: number }): string => {
	const dx = to.x - frame.cx;
	const dy = to.y - frame.coreY;
	const len = Math.hypot(dx, dy) || 1;
	const [ux, uy] = [dx / len, dy / len];
	const start = { x: frame.cx + ux * (frame.core / 2 + 14), y: frame.coreY + uy * (frame.core / 2 + 14) };
	const end = { x: to.x - ux * (frame.node / 2 + 8), y: to.y - uy * (frame.node / 2 + 8) };
	// bow away from the vertical axis, so the links fan out like spokes of a wheel
	const bow = len * 0.12 * (ux < 0 ? -1 : 1);
	const mid = { x: (start.x + end.x) / 2 + uy * bow * -1, y: (start.y + end.y) / 2 + ux * bow };
	return `M${round(start.x)} ${round(start.y)}Q${round(mid.x)} ${round(mid.y)} ${round(end.x)} ${round(end.y)}`;
};

/** How wide the greeting may run at the height of the lower nodes without touching them. */
export const orbitGreetingWidth = (frame: OrbitFrame, angles: number[]): number => {
	const sides = angles
		.filter((a) => Math.sin(rad(a)) > 0.2 && Math.abs(Math.cos(rad(a))) > 0.5)
		.map((a) => Math.abs(frame.rx * Math.cos(rad(a))) - frame.node / 2 - 14);
	return Math.round(sides.length ? Math.max(120, Math.min(...sides) * 2) : frame.w - 16);
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

/** Slot indices clockwise from the left (upper left first): the arrow keys' order. */
export const orbitOrder = (angles: number[]): number[] =>
	angles
		.map((angle, index) => ({ index, key: (((angle - 180) % 360) + 720) % 360 }))
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
