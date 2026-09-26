// LaTeX inside HTML answers goes through KaTeX auto-render, which pairs any two `$` in a
// text node. It must follow the markdown path's rule instead: amounts stay text.
import { describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');
vi.mock('katex/dist/katex.min.css', () => ({}));

const render = async (html: string) => {
	const { renderKatexInHtml } = await import('./katex-auto-render');
	const node = document.createElement('div');
	node.innerHTML = html;
	renderKatexInHtml(node);
	return node;
};

describe('renderKatexInHtml', () => {
	it('leaves dollar amounts as text', async () => {
		const node = await render('<p>剩余 <b>$74.48</b> / $80.00，本轮 $0.21 与 $1.5 之间</p>');
		expect(node.querySelectorAll('.katex').length).toBe(0);
		expect(node.textContent).toBe('剩余 $74.48 / $80.00，本轮 $0.21 与 $1.5 之间');
		const same = await render('<span>[runner] 额度预检通过：剩余 $12.79 / $80.00。</span>');
		expect(same.querySelectorAll('.katex').length).toBe(0);
		expect(same.textContent).toBe('[runner] 额度预检通过：剩余 $12.79 / $80.00。');
	});

	it('still renders math', async () => {
		const node = await render('<p>面积 $a^2+b^2$ 与 $$E=mc^2$$，价格 $5 起</p>');
		expect(node.querySelectorAll('.katex').length).toBe(2);
		expect(node.textContent).toContain('价格 $5 起');
	});
});
