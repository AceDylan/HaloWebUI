// Mounts the per-answer web search badge: while the model decides whether to
// search it must look in progress (spinner, the searching colours), not like
// the grey "未联网" badge it fell back to before.
import { afterEach, describe, expect, it } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

let app: any = null;
let target: any = null;

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
});

const mount = async (state: string, label: string) => {
	const { default: WebSearchBadge } = await import('./WebSearchBadge.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new WebSearchBadge({ target, props: { state, label } });
	return target.querySelector('span');
};

describe('web search badge', () => {
	it('shows deciding as in progress, like searching', async () => {
		const badge = await mount('deciding', '判断是否联网…');
		expect(badge.textContent).toContain('判断是否联网…');
		expect(badge.getAttribute('class')).toContain('text-blue-700');
		expect(badge.querySelector('.spinner_ajPY')).toBeTruthy();
	});

	it('keeps skipped grey and still', async () => {
		const badge = await mount('skipped', '未联网');
		expect(badge.getAttribute('class')).toContain('text-gray-600');
		expect(badge.querySelector('.spinner_ajPY')).toBeFalsy();
	});
});
