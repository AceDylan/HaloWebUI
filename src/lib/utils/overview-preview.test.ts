import { describe, expect, it } from 'vitest';

import { getOverviewPreview } from './overview-preview';

const TOOL =
	'<details type="tool_calls" done="true" id="hermes-0" name="skill_view" arguments="{&quot;input&quot;: &quot;yce&quot;}" result="{&quot;status&quot;: &quot;success&quot;}"><summary>Tool Executed</summary>\n</details>';

describe('getOverviewPreview', () => {
	it('shows the words, and names tools and the HTML card as tags', () => {
		const content = [
			TOOL,
			TOOL,
			'',
			'主要改的是**你本机安装的 YCE**：`/root/.hermes/skills/yce`。',
			'',
			'````html',
			'<div class="hv" data-theme="t"><style>.hv{color:red}</style><h2>YCE 修复</h2></div>',
			'````'
		].join('\n');
		const preview = getOverviewPreview(content);
		expect(preview.text).toBe('主要改的是你本机安装的 YCE：/root/.hermes/skills/yce。');
		expect(preview.tags).toEqual(['HTML 卡片', '工具 ×2']);
		expect(preview.status).toBe('');
	});

	it('reads an answer that is only a card from the card itself', () => {
		const content = '```html\n<!DOCTYPE html><html><head><style>body{margin:0}</style><script>x()</script></head><body><h1>旅行计划</h1><p>第一天&nbsp;泰山</p></body></html>\n```';
		const preview = getOverviewPreview(content);
		expect(preview.text).toBe('旅行计划 第一天 泰山');
		expect(preview.tags).toEqual(['HTML 卡片']);
	});

	it('reads a bare HTML document outside a fence the same way', () => {
		const preview = getOverviewPreview('<!DOCTYPE html>\n<html><body><p>你好</p></body></html>');
		expect(preview.text).toBe('你好');
		expect(preview.tags).toEqual(['HTML 卡片']);
	});

	it('moves a runner report header into the status', () => {
		const content = [
			'✅ cchclaude 运行 20261007-005641-ddc1ffda · 已完成',
			'claude-opus-5-5 · Claude 会话 a7981ca4 · $2.51 · 61 轮 · 20m43s',
			'',
			'已经改好并部署上线。',
			'',
			'**改了哪里**',
			'- Hub `423d4f8`'
		].join('\n');
		const preview = getOverviewPreview(content);
		expect(preview.status).toBe('✅ cchclaude 已完成');
		expect(preview.text).toBe('已经改好并部署上线。 改了哪里 Hub 423d4f8');
	});

	it('flattens tables and counts code blocks and images', () => {
		const content = [
			'| 名称 | 状态 |',
			'| --- | :---: |',
			'| hk | 正常 |',
			'',
			'![图](/api/v1/files/1/content)',
			'',
			'```bash\nls -la\n```'
		].join('\n');
		const preview = getOverviewPreview(content, [{ type: 'image' }, { type: 'file' }]);
		expect(preview.text).toBe('名称 状态 hk 正常');
		expect(preview.tags).toEqual(['代码', '图片 2', '附件 1']);
	});

	it('caps the node text but gives the tooltip more', () => {
		const preview = getOverviewPreview('字'.repeat(1000));
		expect(preview.text).toHaveLength(140);
		expect(preview.detail).toHaveLength(600);
		expect(preview.text.endsWith('…')).toBe(true);
	});

	it('is empty for a reply that is only tool calls', () => {
		const preview = getOverviewPreview(TOOL);
		expect(preview.text).toBe('');
		expect(preview.tags).toEqual(['工具 ×1']);
	});
});
