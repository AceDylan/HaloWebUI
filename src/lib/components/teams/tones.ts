import type { Tone } from './model';

/** Tailwind classes per status tone (light + dark), shared by chips, cards and the board. */
export const TONE_CHIP: Record<Tone, string> = {
	run: 'bg-sky-500/10 text-sky-700 ring-sky-500/25 dark:bg-sky-400/10 dark:text-sky-300 dark:ring-sky-400/25',
	wait: 'bg-gray-500/[0.07] text-gray-600 ring-gray-500/15 dark:bg-white/[0.05] dark:text-gray-300 dark:ring-white/10',
	deps: 'bg-amber-500/10 text-amber-700 ring-amber-500/25 dark:bg-amber-400/10 dark:text-amber-300 dark:ring-amber-400/25',
	user: 'bg-violet-500/10 text-violet-700 ring-violet-500/25 dark:bg-violet-400/10 dark:text-violet-300 dark:ring-violet-400/25',
	quota:
		'bg-orange-500/10 text-orange-700 ring-orange-500/25 dark:bg-orange-400/10 dark:text-orange-300 dark:ring-orange-400/25',
	fail: 'bg-red-500/10 text-red-700 ring-red-500/25 dark:bg-red-400/10 dark:text-red-300 dark:ring-red-400/25',
	stop: 'bg-zinc-500/10 text-zinc-600 ring-zinc-500/20 dark:bg-white/[0.06] dark:text-zinc-300 dark:ring-white/10',
	done: 'bg-gray-500/[0.07] text-gray-600 ring-gray-500/15 dark:bg-white/[0.05] dark:text-gray-300 dark:ring-white/10',
	idle: 'bg-gray-500/[0.05] text-gray-500 ring-gray-500/10 dark:bg-white/[0.03] dark:text-gray-400 dark:ring-white/[0.08]'
};

export const TONE_BORDER: Record<Tone, string> = {
	run: 'border-sky-400/50 dark:border-sky-400/40',
	wait: 'border-gray-900/[0.08] dark:border-white/[0.08]',
	deps: 'border-amber-400/60 border-dashed dark:border-amber-400/40',
	user: 'border-violet-400/60 dark:border-violet-400/45',
	quota: 'border-orange-400/60 dark:border-orange-400/45',
	fail: 'border-red-400/60 dark:border-red-400/45',
	stop: 'border-zinc-400/50 dark:border-zinc-500/40',
	done: 'border-gray-900/[0.12] dark:border-white/[0.12]',
	idle: 'border-gray-900/[0.08] border-dashed dark:border-white/[0.08]'
};

/** Edge / accent colour (SVG stroke) per tone. */
export const TONE_STROKE: Record<Tone, string> = {
	run: '#1d8cff',
	wait: '#9ca3af',
	deps: '#f59e0b',
	user: '#8b5cf6',
	quota: '#f97316',
	fail: '#ef4444',
	stop: '#71717a',
	done: '#6b7280',
	idle: '#cbd5e1'
};

export const TONE_DOT: Record<Tone, string> = {
	run: 'bg-sky-500',
	wait: 'bg-gray-400',
	deps: 'bg-amber-500',
	user: 'bg-violet-500',
	quota: 'bg-orange-500',
	fail: 'bg-red-500',
	stop: 'bg-zinc-500',
	done: 'bg-gray-500 dark:bg-gray-400',
	idle: 'bg-gray-300 dark:bg-gray-600'
};

/** Text colour per tone, for status lines that are not chips. */
export const TONE_TEXT: Record<Tone, string> = {
	run: 'text-sky-600 dark:text-sky-300',
	wait: 'text-gray-500 dark:text-gray-400',
	deps: 'text-amber-600 dark:text-amber-300',
	user: 'text-violet-600 dark:text-violet-300',
	quota: 'text-orange-600 dark:text-orange-300',
	fail: 'text-red-600 dark:text-red-300',
	stop: 'text-zinc-500 dark:text-zinc-400',
	done: 'text-gray-600 dark:text-gray-300',
	idle: 'text-gray-400 dark:text-gray-500'
};
