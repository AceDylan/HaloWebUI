import type { Tone } from './model';

/** Tailwind classes per status tone (light + dark), shared by chips, cards and the board. */
export const TONE_CHIP: Record<Tone, string> = {
	run: 'bg-sky-50 text-sky-700 ring-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:ring-sky-800',
	wait: 'bg-gray-100 text-gray-600 ring-gray-200 dark:bg-gray-850 dark:text-gray-300 dark:ring-gray-700',
	deps: 'bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:ring-amber-800',
	user: 'bg-violet-50 text-violet-700 ring-violet-200 dark:bg-violet-950/40 dark:text-violet-300 dark:ring-violet-800',
	quota: 'bg-orange-50 text-orange-700 ring-orange-200 dark:bg-orange-950/40 dark:text-orange-300 dark:ring-orange-800',
	fail: 'bg-red-50 text-red-700 ring-red-200 dark:bg-red-950/40 dark:text-red-300 dark:ring-red-800',
	stop: 'bg-zinc-100 text-zinc-600 ring-zinc-300 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-600',
	done: 'bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-800',
	idle: 'bg-gray-50 text-gray-500 ring-gray-200 dark:bg-gray-900 dark:text-gray-400 dark:ring-gray-800'
};

export const TONE_BORDER: Record<Tone, string> = {
	run: 'border-sky-300 dark:border-sky-700',
	wait: 'border-gray-200 dark:border-gray-800',
	deps: 'border-amber-300 border-dashed dark:border-amber-700',
	user: 'border-violet-300 dark:border-violet-700',
	quota: 'border-orange-300 dark:border-orange-700',
	fail: 'border-red-300 dark:border-red-700',
	stop: 'border-zinc-300 dark:border-zinc-700',
	done: 'border-emerald-300 dark:border-emerald-800',
	idle: 'border-gray-200 dark:border-gray-800'
};

/** Edge / accent colour (SVG stroke) per tone. */
export const TONE_STROKE: Record<Tone, string> = {
	run: '#0ea5e9',
	wait: '#9ca3af',
	deps: '#f59e0b',
	user: '#8b5cf6',
	quota: '#f97316',
	fail: '#ef4444',
	stop: '#71717a',
	done: '#10b981',
	idle: '#d1d5db'
};

export const TONE_DOT: Record<Tone, string> = {
	run: 'bg-sky-500',
	wait: 'bg-gray-400',
	deps: 'bg-amber-500',
	user: 'bg-violet-500',
	quota: 'bg-orange-500',
	fail: 'bg-red-500',
	stop: 'bg-zinc-500',
	done: 'bg-emerald-500',
	idle: 'bg-gray-300 dark:bg-gray-600'
};
