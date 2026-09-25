import domino from '@mixmark-io/domino';
import { describe, expect, it } from 'vitest';

import {
	buildHtmlArtifactPreview,
	buildInlineHtmlArtifactPreview,
	hardenHtmlPreviewDocument,
	isInlineHtmlPreviewCitationMessage
} from './html-preview';

const CITATION_SCRIPT_RE = /<script data-halo-html-preview-citations="true">([\s\S]*?)<\/script>/;

const answer = (html: string) => `Summary [1]\n\n\`\`\`html\n${html}\n\`\`\``;

// Runs the frame's citation bridge against a DOM built from the preview
// document and returns what it posted to the parent.
const runBridge = (preview: string) => {
	const script = preview.match(CITATION_SCRIPT_RE)?.[1];
	expect(script).toBeTruthy();
	const window = domino.createWindow(preview);
	const document = window.document;
	const posted: unknown[] = [];
	const listeners: Array<(event: unknown) => void> = [];
	const fakeDocument = new Proxy(document, {
		get(target, key) {
			if (key === 'addEventListener') {
				return (type: string, listener: (event: unknown) => void) => {
					if (type === 'click') listeners.push(listener);
				};
			}
			if (key === 'readyState') return 'complete';
			const value = Reflect.get(target, key);
			return typeof value === 'function' ? value.bind(target) : value;
		}
	});
	class FakeMutationObserver {
		observe() {}
	}
	new Function(
		'document',
		'parent',
		'NodeFilter',
		'Element',
		'requestAnimationFrame',
		'MutationObserver',
		script as string
	)(
		fakeDocument,
		{ postMessage: (message: unknown) => posted.push(message) },
		window.NodeFilter,
		window.Element,
		() => 0,
		FakeMutationObserver
	);
	const click = (element: Element) => {
		const event = { target: element, preventDefault() {}, stopPropagation() {} };
		listeners.forEach((listener) => listener(event));
	};
	return { document, posted, click };
};

describe('html preview citations', () => {
	it('adds the bridge only when the answer has sources', () => {
		const html = '<p>Traffic is up [1].</p>';
		expect(buildHtmlArtifactPreview(answer(html))).not.toMatch(CITATION_SCRIPT_RE);
		expect(buildHtmlArtifactPreview(answer(html), { citations: [] })).not.toMatch(
			CITATION_SCRIPT_RE
		);
		expect(
			buildInlineHtmlArtifactPreview(answer(html), {
				enabled: true,
				streaming: false,
				citations: ['a.example']
			})
		).toMatch(CITATION_SCRIPT_RE);
	});

	it('makes markers that name sources clickable and leaves the rest as text', () => {
		const preview = buildHtmlArtifactPreview(
			answer(
				'<p>Traffic is up 1.26x [1]. Peaks [2, 3]【2】 and [9], in [2026].</p>' +
					'<pre>arr[1]</pre><code>[1]</code><a href="https://x.example/">see [3]</a>'
			),
			{ citations: ['a.example', 'b.example', 'c.example'] }
		) as string;
		const { document, posted, click } = runBridge(preview);

		const chips = Array.from(document.querySelectorAll('[data-halo-cite]'));
		expect(chips.map((chip) => [chip.textContent, chip.getAttribute('data-halo-cite')])).toEqual([
			['[1]', '1'],
			['2', '2'],
			['3', '3'],
			['【2】', '2'],
			['[3]', '3']
		]);
		expect(chips[0].getAttribute('title')).toBe('a.example');
		expect(chips[0].getAttribute('role')).toBe('button');
		// The visible text is unchanged; only the markers became elements.
		expect(document.querySelector('p')?.textContent).toBe(
			'Traffic is up 1.26x [1]. Peaks [2, 3]【2】 and [9], in [2026].'
		);
		expect(document.querySelector('pre')?.innerHTML).toBe('arr[1]');
		expect(document.querySelector('code')?.innerHTML).toBe('[1]');

		click(chips[2]);
		expect(posted).toEqual([{ type: 'halo-html-preview-citation', index: 3 }]);
		click(document.querySelector('p') as Element);
		expect(posted).toHaveLength(1);
	});

	it('is stripped and re-added when a document is hardened again', () => {
		const once = hardenHtmlPreviewDocument('<p>[1]</p>', undefined, 'light', ['a.example']);
		const twice = hardenHtmlPreviewDocument(once, undefined, 'light', ['a.example']);
		expect(twice.match(new RegExp(CITATION_SCRIPT_RE.source, 'g'))).toHaveLength(1);
	});

	it('escapes source labels inside the script', () => {
		const preview = hardenHtmlPreviewDocument('<p>[1]</p>', undefined, 'light', [
			'</script><script>alert(1)</script>'
		]);
		expect(preview).not.toContain('</script><script>alert(1)');
	});

	it('accepts only positive integer citation messages', () => {
		expect(
			isInlineHtmlPreviewCitationMessage({ type: 'halo-html-preview-citation', index: 2 })
		).toBe(true);
		for (const index of [0, -1, 1.5, '2', null]) {
			expect(
				isInlineHtmlPreviewCitationMessage({ type: 'halo-html-preview-citation', index })
			).toBe(false);
		}
		expect(isInlineHtmlPreviewCitationMessage({ type: 'halo-html-preview-copy', index: 1 })).toBe(
			false
		);
	});
});
