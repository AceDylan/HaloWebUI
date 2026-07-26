import { describe, expect, it } from 'vitest';

import { normalizeHtmlVisualMode } from './html-visual-mode';

describe('HTML-Visual mode normalization', () => {
	it.each([
		[true, 'force'],
		[false, 'off'],
		['force', 'force'],
		['auto', 'auto'],
		['off', 'off']
	] as const)('normalizes persisted %s to %s', (value, expected) => {
		expect(normalizeHtmlVisualMode(value)).toBe(expected);
	});

	it('defaults missing persisted values to force but invalid values to off', () => {
		expect(normalizeHtmlVisualMode(undefined)).toBe('force');
		expect(normalizeHtmlVisualMode(null)).toBe('force');
		expect(normalizeHtmlVisualMode('unexpected')).toBe('off');
		expect(normalizeHtmlVisualMode({})).toBe('off');
	});
});
