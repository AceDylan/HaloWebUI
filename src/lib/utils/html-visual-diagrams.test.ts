import { describe, expect, it } from 'vitest';

import { buildHtmlArtifactPreview } from './html-preview';
import { hasHtmlVisualDiagrams, renderHtmlVisualDiagrams } from './html-visual-diagrams';
import { withHtmlVisualKitStyles } from './html-visual-kit';

const card = (inner: string) => `<div class="hv" data-theme="ion">${inner}</div>`;

describe('html visual diagrams', () => {
	it('draws a flow with computed boxes, arrows and edge labels', () => {
		const html = renderHtmlVisualDiagrams(
			card(
				'<pre class="hv-dia" data-kind="flow">(Hermes 生图) -&gt; 网关回调: POST\n网关回调 -> {已存在?}\n{已存在?} -> 跳过: 是\n{已存在?} -> [(图库)]: 否\n*生图工作台 --> 跳过</pre>'
			)
		);
		expect(html).not.toContain('<pre');
		expect(html).toContain('<div class="hv-dia" data-kind="flow">');
		expect(html).toMatch(/<svg viewBox="0 0 \d+ \d+"/);
		expect(html).toContain('aria-label="流程图：Hermes 生图、网关回调');
		expect(html).toContain('am-node--diamond');
		expect(html).toContain('am-node--db');
		expect(html).toContain('am-node--hi');
		expect(html).toContain('am-edge--dashed');
		expect(html).toContain('>POST</text>');
		expect(html).toContain('marker-end="url(#hvd1-arrow)"');
	});

	it('draws a sideways flow twice so phones get it top to bottom', () => {
		const html = renderHtmlVisualDiagrams(
			card('<pre class="hv-dia" data-kind="flow LR">A -> B -> C</pre>')
		);
		expect(html).toContain('hv-dia-wide');
		expect(html).toContain('hv-dia-narrow');
		// Two drawings, two marker ids: references never cross between them.
		expect(html).toContain('id="hvd1-arrow"');
		expect(html).toContain('id="hvd2-arrow"');
	});

	it('draws sequences and trees, with change markers', () => {
		const html = renderHtmlVisualDiagrams(
			card(
				'<pre class="hv-dia" data-kind="sequence num">用户 -&gt; HaloWebUI: 发起\nHaloWebUI --&gt; 用户: 结论\nnote 用户, HaloWebUI: 完成</pre>' +
					'<pre class="hv-dia" data-kind="tree">\n  src/\n    lib/\n      + diagrams.ts | 新增\n    ~ app.css\n</pre>'
			)
		);
		expect(html).toContain('am-seq');
		expect(html).toContain('am-lifeline');
		expect(html).toContain('class="am-step"');
		expect(html).toContain('am-tree');
		expect(html).toContain('data-delta="added"');
		expect(html).toContain('+1 新增');
	});

	it('escapes labels in drawings and trees', () => {
		const html = renderHtmlVisualDiagrams(
			card(
				'<pre class="hv-dia" data-kind="flow">A &amp; B -> &lt;img src=x onerror=alert(1)&gt;</pre>' +
					'<pre class="hv-dia" data-kind="tree">根\n  &lt;b onclick=x&gt;子&lt;/b&gt;\n  子2 | **重点**</pre>'
			)
		);
		expect(html).not.toMatch(/<img|<b onclick/);
		expect(html).toContain('&lt;img');
		expect(html).toContain('<strong>重点</strong>');
	});

	it('draws misplaced change markers as a plain diagram', () => {
		const html = renderHtmlVisualDiagrams(
			card(
				'<pre class="hv-dia" data-kind="flow">~ 生成 -> [直接调用] &amp; [后台任务]\n[直接调用] -> + [(存储)]</pre>'
			)
		);
		expect(html).toContain('<svg');
		expect(html).toContain('data-key="存储"');
	});

	it('accepts group members written like nodes', () => {
		const html = renderHtmlVisualDiagrams(
			card(
				'<pre class="hv-dia" data-kind="flow">group 后端: 网关, *服务, [(库)]\n网关 -> *服务 -> [(库)]</pre>'
			)
		);
		expect(html).toContain('class="am-cluster"');
		expect(html).toContain('>后端</text>');
	});

	it('lets a wide drawing shrink only so far, then scroll', () => {
		const html = renderHtmlVisualDiagrams(
			card('<pre class="hv-dia" data-kind="flow">A -> B</pre>')
		);
		const [, width] = html.match(/<svg viewBox="0 0 (\d+)/) ?? [];
		expect(html).toContain(`style="min-width:${Math.round(Number(width) * 0.75)}px"`);
	});

	it('keeps a block that does not parse as readable source text', () => {
		const html = renderHtmlVisualDiagrams(
			card(
				'<pre class="hv-dia" data-kind="flow">A -&gt;</pre><pre class="hv-dia" data-kind="pie">x</pre>'
			)
		);
		expect(html).toContain('<pre class="hv-dia hv-dia-src">A -&gt;</pre>');
		expect(html).toContain('<pre class="hv-dia hv-dia-src">x</pre>');
	});

	it('leaves other pre blocks and cards without diagrams untouched', () => {
		const plain = card('<pre><code>A -> B</code></pre><div class="hv-dial">x</div>');
		expect(hasHtmlVisualDiagrams('<pre class="hv-code">x</pre>')).toBe(false);
		expect(renderHtmlVisualDiagrams(plain)).toBe(plain);
	});

	it('is applied to kit cards in the preview and the copied source', () => {
		const source = card('<pre class="hv-dia" data-kind="flow">A -> B</pre>');
		const preview = buildHtmlArtifactPreview(`\`\`\`\`html\n${source}\n\`\`\`\``) ?? '';
		expect(preview).toContain('<svg');
		expect(preview).toContain('.hv-dia .am-node-shape');
		expect(withHtmlVisualKitStyles(source)).toContain('<svg');
		// Not a kit card: the author's own markup is shown as written.
		const foreign = buildHtmlArtifactPreview(
			'````html\n<div><pre class="hv-dia" data-kind="flow">A -> B</pre></div>\n````'
		);
		expect(foreign).not.toContain('<svg');
	});
});
