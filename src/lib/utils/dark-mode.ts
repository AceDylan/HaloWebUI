import { readable } from 'svelte/store';

/**
 * Whether the app is currently rendering its dark palette. Tracks the `dark`
 * class on <html> (what Tailwind's `dark:` variants key off), so it follows the
 * theme setting, the `system` option and live theme switches alike.
 */
export const isDarkMode = readable(false, (set) => {
	if (typeof document === 'undefined') {
		return;
	}
	const root = document.documentElement;
	const update = () => set(root.classList.contains('dark'));
	update();
	const observer = new MutationObserver(update);
	observer.observe(root, { attributes: true, attributeFilter: ['class'] });
	return () => observer.disconnect();
});
