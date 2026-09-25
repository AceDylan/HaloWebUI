import { readable } from 'svelte/store';

import { activeChatIds, hermesActiveRuns } from '$lib/stores';

/**
 * What the browser tab shows about replies: `running` while a reply or a
 * hermes run is in progress, `done` when one finished while nobody was looking
 * at the tab (cleared as soon as the tab is looked at again), `idle` otherwise.
 * Drives the title prefix and the favicon dot.
 */
export type TabActivity = 'idle' | 'running' | 'done';

export const nextTabActivity = (
	previous: TabActivity,
	running: boolean,
	attended: boolean
): TabActivity => {
	if (running) return 'running';
	if (!attended && (previous === 'running' || previous === 'done')) return 'done';
	return 'idle';
};

export const TAB_ACTIVITY_TITLE_PREFIX: Record<TabActivity, string> = {
	idle: '',
	running: '● ',
	done: '✓ '
};

export const tabActivity = readable<TabActivity>('idle', (set) => {
	if (typeof window === 'undefined' || typeof document === 'undefined') {
		return () => {};
	}

	let state: TabActivity = 'idle';
	let chatRunning = false;
	let hermesRunning = false;

	const attended = () => document.visibilityState === 'visible' && document.hasFocus();
	const update = () => {
		const next = nextTabActivity(state, chatRunning || hermesRunning, attended());
		if (next !== state) {
			state = next;
			set(state);
		}
	};

	const unsubscribeChats = activeChatIds.subscribe((ids) => {
		chatRunning = (ids?.size ?? 0) > 0;
		update();
	});
	const unsubscribeRuns = hermesActiveRuns.subscribe((runs) => {
		hermesRunning = (runs?.length ?? 0) > 0;
		update();
	});

	window.addEventListener('focus', update);
	window.addEventListener('pointerdown', update, true);
	window.addEventListener('keydown', update, true);
	document.addEventListener('visibilitychange', update);

	return () => {
		unsubscribeChats();
		unsubscribeRuns();
		window.removeEventListener('focus', update);
		window.removeEventListener('pointerdown', update, true);
		window.removeEventListener('keydown', update, true);
		document.removeEventListener('visibilitychange', update);
	};
});

const FAVICON_DOT_COLORS: Record<Exclude<TabActivity, 'idle'>, string> = {
	running: '#3b82f6',
	done: '#10b981'
};

const faviconCache = new Map<string, Promise<string | null>>();

/**
 * The favicon with a status dot in its corner, as a data URL; null when the
 * base icon cannot be drawn (the caller keeps the plain icon).
 */
export const getFaviconWithDot = (
	baseHref: string,
	activity: Exclude<TabActivity, 'idle'>
): Promise<string | null> => {
	const key = `${baseHref}|${activity}`;
	const cached = faviconCache.get(key);
	if (cached) return cached;

	const drawn = new Promise<string | null>((resolve) => {
		const image = new Image();
		image.crossOrigin = 'anonymous';
		image.onload = () => {
			try {
				const size = 64;
				const canvas = document.createElement('canvas');
				canvas.width = size;
				canvas.height = size;
				const context = canvas.getContext('2d');
				if (!context) {
					resolve(null);
					return;
				}
				context.drawImage(image, 0, 0, size, size);
				const radius = 13;
				const center = size - radius - 2;
				context.beginPath();
				context.arc(center, center, radius + 3, 0, Math.PI * 2);
				context.fillStyle = '#ffffff';
				context.fill();
				context.beginPath();
				context.arc(center, center, radius, 0, Math.PI * 2);
				context.fillStyle = FAVICON_DOT_COLORS[activity];
				context.fill();
				resolve(canvas.toDataURL('image/png'));
			} catch {
				resolve(null);
			}
		};
		image.onerror = () => resolve(null);
		image.src = baseHref;
	});
	faviconCache.set(key, drawn);
	return drawn;
};
