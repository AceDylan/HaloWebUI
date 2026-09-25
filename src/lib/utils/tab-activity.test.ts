import { describe, expect, it } from 'vitest';

import { nextTabActivity } from './tab-activity';

describe('nextTabActivity', () => {
	it('shows running whenever something runs', () => {
		expect(nextTabActivity('idle', true, true)).toBe('running');
		expect(nextTabActivity('done', true, false)).toBe('running');
	});

	it('marks a run that finished unattended as done until the tab is looked at', () => {
		expect(nextTabActivity('running', false, false)).toBe('done');
		expect(nextTabActivity('done', false, false)).toBe('done');
		expect(nextTabActivity('done', false, true)).toBe('idle');
	});

	it('goes straight back to idle when the finish was watched', () => {
		expect(nextTabActivity('running', false, true)).toBe('idle');
		expect(nextTabActivity('idle', false, false)).toBe('idle');
	});
});
