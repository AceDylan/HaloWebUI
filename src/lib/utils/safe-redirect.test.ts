import { describe, expect, it } from 'vitest';

import { MAX_REDIRECT_LENGTH, safeRedirectPath } from './safe-redirect';

describe('safeRedirectPath', () => {
	it('keeps an ordinary same-site path, query and fragment', () => {
		expect(safeRedirectPath('/')).toBe('/');
		expect(safeRedirectPath('/c/2f0b1c')).toBe('/c/2f0b1c');
		expect(safeRedirectPath('/?q=hello%20there')).toBe('/?q=hello%20there');
		expect(safeRedirectPath('/notes?folder=inbox#top')).toBe('/notes?folder=inbox#top');
	});

	it('keeps a percent-encoded prompt byte for byte (the Bookmark Hub sends one)', () => {
		const prompt = encodeURIComponent('帮我读一下 https://example.com 这个页面');
		expect(safeRedirectPath(`/?q=${prompt}`)).toBe(`/?q=${prompt}`);
	});

	it('refuses to leave this site', () => {
		for (const hostile of [
			'https://evil.example/phish',
			'http://evil.example',
			'//evil.example',
			'//evil.example/path',
			'/\\evil.example',
			'/\\\\evil.example',
			'\\\\evil.example',
			'javascript:alert(1)',
			'javascript:alert(1)//',
			'data:text/html,<script>alert(1)</script>',
			'mailto:someone@example.com'
		]) {
			expect(safeRedirectPath(hostile)).toBe('/');
		}
	});

	it('refuses control characters a browser would strip back out', () => {
		expect(safeRedirectPath('/\thttps://evil.example')).toBe('/');
		expect(safeRedirectPath('/\nhttps://evil.example')).toBe('/');
		expect(safeRedirectPath('/\r/evil.example')).toBe('/');
		expect(safeRedirectPath(' /c/1')).toBe('/');
		expect(safeRedirectPath('/c/\u00001')).toBe('/');
	});

	it('refuses anything that is not a non-empty string, and anything oversized', () => {
		for (const bad of [undefined, null, '', 0, 42, {}, [], true]) {
			expect(safeRedirectPath(bad)).toBe('/');
		}
		expect(safeRedirectPath(`/${'a'.repeat(MAX_REDIRECT_LENGTH)}`)).toBe('/');
		expect(safeRedirectPath(`/${'a'.repeat(MAX_REDIRECT_LENGTH - 1)}`)).toBe(
			`/${'a'.repeat(MAX_REDIRECT_LENGTH - 1)}`
		);
	});

	it('resolves dot segments away instead of passing them on', () => {
		expect(safeRedirectPath('/a/../c/1')).toBe('/c/1');
		expect(safeRedirectPath('/../../etc/passwd')).toBe('/etc/passwd');
	});

	it('uses the fallback it was given', () => {
		expect(safeRedirectPath('https://evil.example', '/home')).toBe('/home');
		expect(safeRedirectPath(null, '/home')).toBe('/home');
	});
});
