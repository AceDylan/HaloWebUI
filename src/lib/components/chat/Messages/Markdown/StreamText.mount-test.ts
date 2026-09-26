// Mounts the fade-in text run used while an answer streams. Guards the long-reply
// stutter: characters must stop being animated spans once their fade is over,
// while the newest ones still fade and keep their own element.
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

let StreamText: any;
let app: any;
let target: any;

beforeAll(async () => {
	StreamText = (await import('./StreamText.svelte')).default;
});

afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
});

const spans = () => Array.from(target.querySelectorAll('span.stream-char')) as any[];

describe('StreamText', () => {
	it('fades new characters in and then folds them into plain text', async () => {
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new StreamText({ target, props: { text: '你好' } });
		await sleep(0);
		expect(spans().map((span) => span.textContent)).toEqual(['你', '好']);
		expect(target.textContent).toBe('你好');

		await sleep(450);
		expect(spans()).toHaveLength(0);
		expect(target.textContent).toBe('你好');

		app.$set({ text: '你好，世界' });
		await sleep(0);
		expect(spans().map((span) => span.textContent)).toEqual(['，', '世', '界']);
		const fading = spans()[0];

		app.$set({ text: '你好，世界！' });
		await sleep(0);
		expect(spans()[0]).toBe(fading); // still the same element, so its fade is not restarted
		expect(spans().map((span) => span.textContent)).toEqual(['，', '世', '界', '！']);
		expect(target.textContent).toBe('你好，世界！');

		await sleep(800);
		expect(spans()).toHaveLength(0);
		expect(target.textContent).toBe('你好，世界！');
	});

	it('shows rewritten text as it is now', async () => {
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new StreamText({ target, props: { text: 'run **docker' } });
		await sleep(450);
		app.$set({ text: 'run docker ps' });
		await sleep(0);
		expect(target.textContent).toBe('run docker ps');
		expect(spans().length).toBeLessThanOrEqual('docker ps'.length);
		await sleep(800);
		expect(spans()).toHaveLength(0);
		expect(target.textContent).toBe('run docker ps');
	});
});
