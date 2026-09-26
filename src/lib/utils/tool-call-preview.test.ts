import { describe, expect, it } from 'vitest';
import {
	formatToolDuration,
	getToolCallInput,
	getToolCallOutcome,
	getToolCallPreview,
	getToolCallStartedAt,
	getToolCallState,
	isOutcomeOnlyResult,
	summarizeToolNames,
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

describe('tool call state after the run', () => {
	it('reads an interrupted outcome and its reason', () => {
		expect(
			getToolCallOutcome('{&quot;status&quot;: &quot;interrupted&quot;, &quot;reason&quot;: &quot;网关重启&quot;}')
		).toEqual({ status: 'interrupted', duration: null, reason: '网关重启' });
	});

	it('treats a call still running in a finished reply as interrupted', () => {
		expect(getToolCallState({ done: 'false' }, false)).toBe('running');
		expect(getToolCallState({ done: 'false' }, true)).toBe('interrupted');
		expect(
			getToolCallState({ done: 'true', result: JSON.stringify({ status: 'error' }) }, true)
		).toBe('error');
		expect(getToolCallState({ done: 'true', result: JSON.stringify({ duration: 1 }) })).toBe(
			'done'
		);
	});

	it('summarizes names by count, most used first', () => {
		expect(
			summarizeToolNames([
				'terminal',
				'skill_view',
				'skill_view',
				'terminal',
				'skill_view',
				'read_file',
				'web',
				'web',
				'x'
			])
		).toBe('skill_view ×3 · terminal ×2 · web ×2 · +2');
		expect(summarizeToolNames(['terminal'])).toBe('terminal');
	});

	it('gives the whole hermes input and recognises outcome-only results', () => {
		const long = `echo ${'a'.repeat(300)}`;
		expect(getToolCallInput(JSON.stringify({ input: long }))).toBe(long);
		expect(getToolCallInput(JSON.stringify({ city: 'Paris', unit: 'c' }))).toBeNull();
		expect(isOutcomeOnlyResult(JSON.stringify({ status: 'success', duration: 1.2 }))).toBe(true);
		expect(isOutcomeOnlyResult(JSON.stringify([{ link: 'x' }]))).toBe(false);
	});

	it('reads the start time hermes stamps on a call', () => {
		expect(getToolCallStartedAt({ started: '1790000000.5' })).toBe(1790000000.5);
		expect(getToolCallStartedAt({})).toBeNull();
	});
});
