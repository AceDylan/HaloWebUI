import type { TransitionConfig } from 'svelte/transition';
import { DUR, exitEase, prefersReducedMotion, springSmooth } from './spring';

export * from './spring';

type FlyAndScaleParams = {
	y?: number;
	start?: number;
	duration?: number;
};

// Menus and dialogs grow from where they were opened (transform-origin follows the trigger —
// see [data-side] in halo.css) on the Halo Motion spring; they leave faster than they arrive.
const defaultFlyAndScaleParams = { y: -4, start: 0.96, duration: DUR.std };

export const flyAndScale = (
	node: Element,
	params?: FlyAndScaleParams,
	options?: { direction?: 'in' | 'out' | 'both' }
): TransitionConfig | ((opts: { direction: 'in' | 'out' }) => TransitionConfig) => {
	// `transition:` (bidirectional) gets its direction through the returned function.
	if (options?.direction === 'both') {
		return (opts) => flyAndScaleConfig(node, params, opts.direction);
	}
	return flyAndScaleConfig(node, params, options?.direction === 'out' ? 'out' : 'in');
};

const flyAndScaleConfig = (
	node: Element,
	params: FlyAndScaleParams | undefined,
	direction: 'in' | 'out'
): TransitionConfig => {
	if (prefersReducedMotion()) {
		return { duration: DUR.exit, css: (t) => `opacity:${t}` };
	}
	const style = getComputedStyle(node);
	const transform = style.transform === 'none' ? '' : style.transform;
	const withDefaults = { ...defaultFlyAndScaleParams, ...params };

	const scaleConversion = (valueA: number, scaleA: [number, number], scaleB: [number, number]) => {
		const [minA, maxA] = scaleA;
		const [minB, maxB] = scaleB;

		const percentage = (valueA - minA) / (maxA - minA);
		const valueB = percentage * (maxB - minB) + minB;

		return valueB;
	};

	const styleToString = (style: Record<string, number | string | undefined>): string => {
		return Object.keys(style).reduce((str, key) => {
			if (style[key] === undefined) return str;
			return str + `${key}:${style[key]};`;
		}, '');
	};

	const leaving = direction === 'out';
	return {
		duration: leaving ? DUR.exit : (withDefaults.duration ?? DUR.std),
		delay: 0,
		css: (t) => {
			const y = scaleConversion(t, [0, 1], [withDefaults.y, 0]);
			const scale = scaleConversion(t, [0, 1], [withDefaults.start, 1]);

			return styleToString({
				transform: `${transform} translate3d(0, ${y}px, 0) scale(${scale})`,
				// the spring overshoots a hair past 1; opacity must not
				opacity: Math.min(1, Math.max(0, t))
			});
		},
		easing: leaving ? exitEase : springSmooth
	};
};
