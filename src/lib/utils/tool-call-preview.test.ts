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
	it('says a call\'s time in the same words as a run\'s', () => {
		expect(formatToolDuration(0.479)).toBe('0.5 秒');
		expect(formatToolDuration(0.04)).toBe('不到 0.1 秒');
		expect(formatToolDuration(3.26)).toBe('3.3 秒');
		expect(formatToolDuration(46.227)).toBe('46 秒');
		expect(formatToolDuration(125)).toBe('2 分 5 秒');
		expect(formatToolDuration(3725)).toBe('1 小时 2 分');
		expect(formatToolDuration(null)).toBe('');
	});

	it('shows a ticking clock in whole seconds', () => {
		expect(formatToolDuration(0)).toBe('0 秒');
		expect(formatToolDuration(7)).toBe('7 秒');
		expect(formatToolDuration(754)).toBe('12 分 34 秒');
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
		).toBe('技能 3 · 终端 2 · web 2 · +2');
		expect(summarizeToolNames(['terminal'])).toBe('终端');
		expect(summarizeToolNames(['browser_click', 'browser_navigate'])).toBe('浏览器 2');
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
