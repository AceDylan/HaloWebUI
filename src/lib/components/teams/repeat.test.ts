import { describe, expect, it } from 'vitest';

import { scheduleWhen } from './repeat';

describe('scheduleWhen', () => {
	it('reads a time in words', () => {
		const at = new Date(2026, 9, 12, 9, 5).getTime() / 1000;
		expect(scheduleWhen(at)).toBe('10 月 12 日 周一 09:05');
		expect(scheduleWhen(null)).toBe('');
	});
});
