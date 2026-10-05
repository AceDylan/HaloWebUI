/**
 * Halo sci-fi layer: one switch (Settings → Interface → 科幻特效, `settings.scifiEffects`,
 * on unless turned off) puts `halo-scifi` on <html>; scifi.css keys everything off that class,
 * so turning it off is the plain Halo look again with nothing else to undo.
 */

export const WARP_EVENT = 'halo:warp';
export const BOOT_KEY = 'halo.scifi.boot';

export const scifiEnabled = (settings: { scifiEffects?: boolean } | null | undefined): boolean =>
	settings?.scifiEffects ?? true;

export const applyScifi = (on: boolean) => {
	if (typeof document === 'undefined') return;
	document.documentElement.classList.toggle('halo-scifi', on);
};

/** Stars streak for a moment (new chat, sign-in, end of the boot sequence). */
export const warp = (ms = 900) => {
	if (typeof window === 'undefined') return;
	window.dispatchEvent(new CustomEvent(WARP_EVENT, { detail: { ms } }));
};

/** Opening titles at most once every 6 hours (new tabs and the phone app would otherwise
 *  replay them every time), never inside the Hub frame, never with reduced motion. */
export const BOOT_EVERY_MS = 6 * 60 * 60 * 1000;

export const shouldBoot = (framed: boolean, now = Date.now()): boolean => {
	if (typeof window === 'undefined' || framed) return false;
	if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return false;
	try {
		const last = Number(localStorage.getItem(BOOT_KEY) || 0);
		return !(now - last < BOOT_EVERY_MS);
	} catch {
		return false;
	}
};

export const markBooted = (now = Date.now()) => {
	try {
		localStorage.setItem(BOOT_KEY, String(now));
	} catch {
		/* private mode: it just plays again next time */
	}
};

/** Panels on the mode pages that carry a light following the mouse (scifi-modes.css reads
 *  --sf-x / --sf-y; keep in step with its panel list). Plain-coloured panels only: the tinted
 *  ones keep their own gradient. One delegated listener for the whole app; mouse only, one
 *  write a frame. */
export const SPOT_SELECTOR =
	'[data-discuss-row], [data-team-row], [data-teams-ui] .tm-card-quiet.tm-hover, .dc-turn, #team-inspector, [data-halo-mode] .glass-item:not(.group)';

export const trackSpotlight = (root: Pick<Document, 'addEventListener' | 'removeEventListener'> = document) => {
	let frame = 0;
	let last: PointerEvent | null = null;
	const paint = () => {
		frame = 0;
		const el = (last?.target as Element | null)?.closest?.(SPOT_SELECTOR) as HTMLElement | null;
		if (!last || !el) return;
		const r = el.getBoundingClientRect();
		el.style.setProperty('--sf-x', `${Math.round(last.clientX - r.left)}px`);
		el.style.setProperty('--sf-y', `${Math.round(last.clientY - r.top)}px`);
	};
	const move = (e: PointerEvent) => {
		if (e.pointerType !== 'mouse') return;
		last = e;
		if (!frame) frame = requestAnimationFrame(paint);
	};
	root.addEventListener('pointermove', move as EventListener, { passive: true });
	return () => {
		root.removeEventListener('pointermove', move as EventListener);
		if (frame) cancelAnimationFrame(frame);
	};
};
