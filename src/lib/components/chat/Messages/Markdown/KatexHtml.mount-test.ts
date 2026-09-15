import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom();

const { tick } = await import('svelte');
const { default: KatexHtml } = await import('./KatexHtml.svelte');

let app: InstanceType<typeof KatexHtml> | null = null;
let target: HTMLDivElement | null = null;

const mount = async (html: string) => {
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new KatexHtml({ target, props: { html } });
	await tick();
	return target;
};

const update = async (html: string) => {
	app?.$set({ html });
	await tick();
};

afterEach(() => {
	app?.$destroy();
	app = null;
	target?.remove();
	target = null;
	vi.restoreAllMocks();
});

describe('KatexHtml', () => {
	it('renders the markup and the LaTeX inside it', async () => {
		const node = await mount('<b>标题</b> 能量 $E = mc^2$ 守恒');

		expect(node.querySelector('b')?.textContent).toBe('标题');
		expect(node.querySelectorAll('.katex').length).toBe(1);
		expect(node.textContent).toContain('守恒');
	});

	it('replaces the previous content instead of stacking a copy per update', async () => {
		// Regression: with `{@html ...}` on the same element, KaTeX's auto-render detached the
		// nodes Svelte was tracking, so every update left another rendered copy in the DOM.
		// A streamed answer grew the DOM without bound until the tab froze.
		const node = await mount('<b>标题</b> 能量 $E = mc^2$ 守恒 0');
		const lengths = [node.textContent?.length ?? 0];

		for (let i = 1; i <= 6; i++) {
			await update(`<b>标题</b> 能量 $E = mc^2$ 守恒 ${i}`);
			lengths.push(node.textContent?.length ?? 0);
		}

		expect(node.querySelectorAll('.katex').length).toBe(1);
		expect(node.textContent).toContain('守恒 6');
		expect(node.textContent).not.toContain('守恒 5');
		expect(new Set(lengths).size).toBe(1);
	});

	it('leaves the subtree alone when the markup did not change', async () => {
		// Svelte re-runs action updates on any dirty flag; rebuilding identical markup would
		// re-request every <img> in it on each streamed chunk.
		const node = await mount('<img src="/api/v1/files/abc/content" alt=""> 公式 $x^2$');
		const image = node.querySelector('img');

		await update('<img src="/api/v1/files/abc/content" alt=""> 公式 $x^2$');

		expect(node.querySelector('img')).toBe(image);
	});

	it('does not flood the console with strict-mode warnings for CJK in math mode', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

		await mount('前言 $能量守恒定律 E = mc^2$ 结尾');

		expect(warn).not.toHaveBeenCalled();
	});

	it('skips markup without any math delimiter', async () => {
		const node = await mount('<p>普通段落，没有公式。</p>');

		expect(node.querySelectorAll('.katex').length).toBe(0);
		expect(node.textContent).toContain('普通段落');
	});
});
