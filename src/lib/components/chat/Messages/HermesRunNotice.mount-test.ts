// A runner's completion notice renders as a system line, not a bubble signed "你".
import { afterEach, describe, expect, it } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

let app: any;
let target: any;

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
});

describe('HermesRunNotice', () => {
	it('shows status and duration, with the ids behind 详情', async () => {
		const { default: HermesRunNotice } = await import('./HermesRunNotice.svelte');
		const { parseHermesRunNotice } = await import('$lib/utils/hermes');
		const content =
			'[后台任务完成通知] reclaude 运行 20260926-1 已结束，状态：success，Claude 会话：f111-2222。';
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new HermesRunNotice({
			target,
			props: {
				notice: parseHermesRunNotice({ role: 'user', content }),
				content,
				report: '✅ reclaude 运行 20260926-1 · 已完成\nClaude 会话 f111-2222 · 12 轮 · 1m55s\n\n正文'
			}
		});
		const button: any = target.querySelector('[data-halo-hermes-run-notice] button');
		expect(button.textContent).toContain('✅ reclaude 已完成 · 1 分 55 秒');
		expect(target.textContent).not.toContain('f111-2222');
		button.click();
		await new Promise((resolve) => setTimeout(resolve, 0));
		const details: any = target.querySelector('[data-halo-hermes-run-notice-details]');
		expect(details.textContent).toContain('20260926-1');
		expect(details.textContent).toContain('Claude 会话');
		expect(details.textContent).toContain('f111-2222');
	});
});
