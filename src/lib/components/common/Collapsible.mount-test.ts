// A single tool card is titled in the same words the finished reply uses.
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

let Collapsible: any;
let app: any;

beforeAll(async () => {
	Collapsible = (await import('./Collapsible.svelte')).default;
}, 60000);

afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
});

const mount = async (attributes: Record<string, string>) => {
	const { writable } = await import('svelte/store');
	const target = document.createElement('div');
	document.body.appendChild(target);
	app = new Collapsible({
		target,
		props: { title: 'Executing...', attributes },
		context: new Map<string, any>([['i18n', writable({ t: (key: string) => key })]])
	});
	await new Promise((resolve) => setTimeout(resolve, 0));
	return target;
};

describe('Collapsible tool card', () => {
	it('names a running hermes tool the way the finished reply does', async () => {
		const target = await mount({
			type: 'tool_calls',
			name: 'execute_code',
			done: 'false',
			arguments: '{"input": "print(1)"}'
		});
		expect(target.textContent).toContain('运行代码');
		expect(target.textContent).not.toContain('execute_code');
	});

	it('keeps a name it has no words for', async () => {
		const target = await mount({ type: 'tool_calls', name: 'get_weather', done: 'false' });
		expect(target.textContent).toContain('get_weather');
	});
});
