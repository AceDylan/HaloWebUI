import { describe, expect, it } from 'vitest';
import {
	formatToolDuration,
	getToolCallOutcome,
	getToolCallPreview,
	truncatePreview
} from './tool-call-preview';

describe('getToolCallPreview', () => {
	it('unwraps the hermes {"input": …} envelope, html-encoded as it arrives in the attribute', () => {
		expect(getToolCallPreview('{&quot;input&quot;: &quot;ls -la /root&quot;}')).toBe(
			'ls -la /root'
		);
	});

	it('collapses whitespace and truncates long previews', () => {
		const preview = getToolCallPreview(JSON.stringify({ input: `a\n${'b'.repeat(200)}` }), 20);
		expect(preview.length).toBe(20);
		expect(preview.endsWith('…')).toBe(true);
		expect(preview.startsWith('a b')).toBe(true);
	});

	it('shows compact json for multi-field native tool arguments', () => {
		expect(getToolCallPreview(JSON.stringify({ city: 'Paris', unit: 'c' }))).toBe(
			'{"city":"Paris","unit":"c"}'
		);
	});

	it('returns an empty string for empty or missing arguments', () => {
		expect(getToolCallPreview('')).toBe('');
		expect(getToolCallPreview(undefined)).toBe('');
		expect(getToolCallPreview('{}')).toBe('');
	});
});

describe('getToolCallOutcome', () => {
	it('reads the hermes status and duration', () => {
		expect(
			getToolCallOutcome('{&quot;status&quot;: &quot;error&quot;, &quot;duration&quot;: 0.5}')
		).toEqual({ status: 'error', duration: 0.5 });
		expect(getToolCallOutcome(JSON.stringify({ status: 'success', duration: 12 }))).toEqual({
			status: 'success',
			duration: 12
		});
	});

	it('is neutral for results without a status envelope', () => {
		expect(getToolCallOutcome('')).toEqual({ status: null, duration: null });
		expect(getToolCallOutcome('[{"link": "x"}]')).toEqual({ status: null, duration: null });
		expect(getToolCallOutcome('plain text')).toEqual({ status: null, duration: null });
	});
});

describe('formatToolDuration', () => {
	it('formats milliseconds, seconds and minutes', () => {
		expect(formatToolDuration(0.479)).toBe('479ms');
		expect(formatToolDuration(3.26)).toBe('3.3s');
		expect(formatToolDuration(46.227)).toBe('46s');
		expect(formatToolDuration(125)).toBe('2m 5s');
		expect(formatToolDuration(null)).toBe('');
	});
});

describe('truncatePreview', () => {
	it('keeps short text untouched', () => {
		expect(truncatePreview('  short   text ')).toBe('short text');
	});
});
