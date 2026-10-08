import { describe, expect, it } from 'vitest';

import { inAppPath } from './app-links';

describe('inAppPath', () => {
	it('keeps the pages of this app in place', () => {
		expect(inAppPath('/teams/t1/conclusion')).toBe('/teams/t1/conclusion');
		expect(inAppPath('/teams/t1/conclusion#process')).toBe('/teams/t1/conclusion#process');
		expect(inAppPath(' /discuss/d1 ')).toBe('/discuss/d1');
		expect(inAppPath('/c/abc?x=1')).toBe('/c/abc?x=1');
		expect(inAppPath('/teams')).toBe('/teams');
		expect(inAppPath('/workspace/knowledge/k1')).toBe('/workspace/knowledge/k1');
	});

	it('an absolute link to this app counts, other sites do not', () => {
		expect(inAppPath('https://halo.example/teams/t1', 'https://halo.example')).toBe('/teams/t1');
		expect(inAppPath('https://halo.example/teams/t1')).toBeNull();
		expect(inAppPath('https://other.example/teams/t1', 'https://halo.example')).toBeNull();
		expect(inAppPath('//other.example/teams/t1', 'https://halo.example')).toBeNull();
	});

	it('files, downloads and anything else open in a new tab', () => {
		expect(inAppPath('/api/v1/teams/t1/files/a.png')).toBeNull();
		expect(inAppPath('/static/favicon.png')).toBeNull();
		expect(inAppPath('/teamsx')).toBeNull();
		expect(inAppPath('#part')).toBeNull();
		expect(inAppPath('report.md')).toBeNull();
		expect(inAppPath('javascript:alert(1)', 'https://halo.example')).toBeNull();
		expect(inAppPath('data:text/plain,x', 'https://halo.example')).toBeNull();
		expect(inAppPath('')).toBeNull();
		expect(inAppPath(null)).toBeNull();
	});
});
