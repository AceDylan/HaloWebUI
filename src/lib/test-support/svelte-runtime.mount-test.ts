import { it, expect } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';
installDominoDom('http://localhost/');
it('resolves svelte to the browser runtime (onMount must not be a no-op)', async () => {
	const svelte = await import('svelte');
	expect(svelte.onMount.toString()).toMatch(/on_mount|get_current_component/);
});
it('shim exposes the DOM APIs the settings page needs', () => {
	const el: any = document.createElement('button');
	console.log(
		'[diag] getBoundingClientRect:',
		typeof el.getBoundingClientRect,
		'dataset:',
		typeof el.dataset,
		'click:',
		typeof el.click,
		'style.setProperty:',
		typeof el.style?.setProperty,
		'closest:',
		typeof el.closest
	);
	expect(typeof el.getBoundingClientRect).toBe('function');
	expect(typeof el.dataset).toBe('object');
});
