import { describe, expect, it } from 'vitest';

import { formatElapsedSeconds } from './elapsed';

describe('formatElapsedSeconds', () => {
	it('formats seconds and minutes', () => {
		expect(formatElapsedSeconds(0)).toBe('0s');
		expect(formatElapsedSeconds(59)).toBe('59s');
		expect(formatElapsedSeconds(60)).toBe('1m');
		expect(formatElapsedSeconds(185)).toBe('3m 5s');
	});
});
