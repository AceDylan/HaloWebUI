import { describe, expect, it } from 'vitest';
import { isPublicSharePath } from './public-share';

describe('isPublicSharePath', () => {
	it('matches a shared-chat link only', () => {
		expect(isPublicSharePath('/s/1b2c-3d')).toBe(true);
		expect(isPublicSharePath('/s/1b2c-3d/')).toBe(true);
		for (const path of ['/', '/s', '/s/', '/c/abc', '/s/abc/more', '/settings/s/abc', null]) {
			expect(isPublicSharePath(path)).toBe(false);
		}
	});
});
