import { describe, expect, it } from 'vitest';

import { buildHtmlArtifactPreview } from './html-preview';
import { usesHtmlVisualKit, withHtmlVisualKitStyles } from './html-visual-kit';

const KIT_CARD =
	'````html\n<div class="hv" data-theme="aurora"><header class="hv-hero"><h1>标题</h1></header></div>\n````';
const PLAIN_CARD = '````html\n<div style="max-width:920px"><h1>标题</h1></div>\n````';

describe('html visual kit', () => {
	it('recognises only a kit root, not hv-prefixed or other classes', () => {
		expect(usesHtmlVisualKit('<div class="hv" data-theme="ion">x</div>')).toBe(true);
		expect(usesHtmlVisualKit("<div class='card hv'>x</div>")).toBe(true);
		expect(usesHtmlVisualKit('<div class="hv-card">x</div>')).toBe(false);
		expect(usesHtmlVisualKit('<div class="shv">x</div>')).toBe(false);
		expect(usesHtmlVisualKit(null)).toBe(false);
	});

	it('gives kit cards the stylesheet and their own colour scheme', () => {
		const light = buildHtmlArtifactPreview(KIT_CARD) ?? '';
		expect(light).toContain('data-halo-visual-kit="true"');
		expect(light).toContain('<html lang="zh-CN" data-halo-color-scheme="light">');
		const dark = buildHtmlArtifactPreview(KIT_CARD, { colorScheme: 'dark' }) ?? '';
		expect(dark).toContain('data-halo-color-scheme="dark"');
		expect(dark).toContain('.hv[data-theme="aurora"]');
	});

	it('leaves older inline-styled cards exactly as before', () => {
		const preview = buildHtmlArtifactPreview(PLAIN_CARD, { colorScheme: 'dark' }) ?? '';
		expect(preview).not.toContain('data-halo-visual-kit');
		expect(preview).toContain('<html lang="en"><head>');
	});

	it('copies kit cards with their styles', () => {
		const source = '<div class="hv">x</div>';
		expect(withHtmlVisualKitStyles(source)).toMatch(/^<style>[^<]*\.hv\{/);
		expect(withHtmlVisualKitStyles(source)).toContain(source);
		expect(withHtmlVisualKitStyles('<div>x</div>')).toBe('<div>x</div>');
	});
});
