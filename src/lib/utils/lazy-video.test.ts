import { describe, expect, it } from 'vitest';

import { lazyVideoHtml, storedFileId, videoThumbUrl } from './lazy-video';

describe('lazy videos', () => {
	it('finds the stored file a player plays', () => {
		expect(storedFileId('/api/v1/files/64666e74-8720/content')).toBe('64666e74-8720');
		expect(storedFileId('https://h.example:3001/api/v1/files/ab-12/content#t=0.1')).toBe('ab-12');
		expect(storedFileId('https://elsewhere.example/v.mp4')).toBe('');
	});

	it('fetches nothing until played and shows the first frame', () => {
		const html = lazyVideoHtml(
			'<div><video src="/api/v1/files/f1/content" controls preload="metadata" playsinline style="max-width:100%"></video></div>'
		);
		expect(html).toContain('preload="none"');
		expect(html).not.toContain('metadata');
		expect(html).toContain(`poster="${videoThumbUrl('f1')}"`);
		expect(html).toContain('style="max-width:100%"');
	});

	it('keeps a poster of its own and leaves other videos without one', () => {
		expect(lazyVideoHtml('<video src="/api/v1/files/f1/content" poster="/c.jpg">')).toBe(
			'<video src="/api/v1/files/f1/content" poster="/c.jpg" preload="none">'
		);
		const outside = lazyVideoHtml('<video controls src="https://x.example/a.mp4"></video>');
		expect(outside).toContain('preload="none"');
		expect(outside).not.toContain('poster');
		expect(lazyVideoHtml('<audio src="/api/v1/files/a/content" preload="metadata">')).toContain('preload="metadata"');
	});
});
