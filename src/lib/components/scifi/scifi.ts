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

/** The boot sequence plays once per browser session, never inside the Hub frame. */
export const shouldBoot = (framed: boolean): boolean => {
	if (typeof window === 'undefined' || framed) return false;
	if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return false;
	try {
		return sessionStorage.getItem(BOOT_KEY) !== '1';
	} catch {
		return false;
	}
};

export const markBooted = () => {
	try {
		sessionStorage.setItem(BOOT_KEY, '1');
	} catch {
		/* private mode: it just plays again next time */
	}
};
