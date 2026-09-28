// A hermes call picked in a tool group shows what it returned.
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

let ToolCallGroup: any;
let app: any;

beforeAll(async () => {
	ToolCallGroup = (await import('./ToolCallGroup.svelte')).default;
}, 60000);

afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
});

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

const call = (input: string, result: Record<string, unknown>) => ({
	attributes: {
		type: 'tool_calls',
		name: 'terminal',
		done: 'true',
		arguments: JSON.stringify({ input }),
		result: JSON.stringify(result)
	}
});

describe('ToolCallGroup detail', () => {
	it('shows the output hermes previewed under the outcome, and nothing when it sent none', async () => {
		const { writable } = await import('svelte/store');
		const target = document.createElement('div');
		document.body.appendChild(target);
		app = new ToolCallGroup({
			target,
			props: {
				id: 't',
				expanded: true,
				tokens: [
					call('ls /srv', {
						status: 'success',
						duration: 0.2,
						output: JSON.stringify({ output: 'app\nlogs', exit_code: 0 })
					}),
					call('true', { status: 'success', duration: 0.1 })
				]
			},
			context: new Map<string, any>([['i18n', writable({ t: (key: string) => key })]])
		});
		await tick();
		const rows = target.querySelectorAll('[data-halo-tool-row]');
		expect(rows.length).toBe(2);

		(rows[0] as any).click();
		await tick();
		let outputs = target.querySelectorAll('[data-halo-tool-output]');
		expect(outputs.length).toBe(1);
		expect(outputs[0].textContent).toBe('app\nlogs\nexit_code: 0');
		expect(target.querySelectorAll('[data-halo-tool-input]')[0].textContent).toBe('ls /srv');

		(rows[1] as any).click();
		await tick();
		outputs = target.querySelectorAll('[data-halo-tool-output]');
		expect(outputs.length).toBe(0);
		expect(target.querySelectorAll('[data-halo-tool-input]')[0].textContent).toBe('true');
	});
});
