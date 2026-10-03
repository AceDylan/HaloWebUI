import { describe, expect, it } from 'vitest';

import { imageDownloadName } from './image-download';

describe('imageDownloadName', () => {
	it('names a generated image after its caption with the real extension', () => {
		expect(imageDownloadName('/api/v1/files/abc/content', '日落 海边', 'image/png')).toBe(
			'日落 海边.png'
		);
		expect(imageDownloadName('/api/v1/files/abc/content?x=1', '', 'image/jpeg')).toBe('image.jpg');
		expect(imageDownloadName('data:image/webp;base64,AAAA', 'a/b:c', 'image/webp')).toBe(
			'a b c.webp'
		);
	});

	it("keeps the URL's own file name when it has one", () => {
		expect(imageDownloadName('https://x.test/img/cat%20one.jpeg', 'Cat', 'image/jpeg')).toBe(
			'cat one.jpeg'
		);
	});

	it('falls back to the given name and png, and trims long captions', () => {
		expect(imageDownloadName('blob:abc', '', '', 'generated-image-2')).toBe(
			'generated-image-2.png'
		);
		expect(imageDownloadName('/c', 'x'.repeat(100), 'image/svg+xml')).toBe(`${'x'.repeat(60)}.svg`);
	});
});
