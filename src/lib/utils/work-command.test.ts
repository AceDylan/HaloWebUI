import { describe, expect, it } from 'vitest';

import { parseWorkCommand, workFileIds } from './work-command';

describe('parseWorkCommand', () => {
	it('reads the goal and the runners named first', () => {
		expect(parseWorkCommand('/work 给 HaloWebUI 加按钮')).toEqual({
			goal: '给 HaloWebUI 加按钮',
			runnerPrefs: {}
		});
		expect(parseWorkCommand('/work cchclaude 给 HaloWebUI 加按钮')).toEqual({
			goal: '给 HaloWebUI 加按钮',
			runnerPrefs: { claude: 'cchclaude' }
		});
		expect(parseWorkCommand('/WORK：AnyClaude，修 bug')).toEqual({
			goal: '修 bug',
			runnerPrefs: { claude: 'anyclaude' }
		});
		expect(parseWorkCommand('/work agy reclaude 修 bug')?.runnerPrefs).toEqual({
			agy: 'agy',
			claude: 'reclaude'
		});
	});

	it('keeps one runner per family and words that are not runners', () => {
		expect(parseWorkCommand('/work cchclaude anyclaude 修')?.goal).toBe('anyclaude 修');
		expect(parseWorkCommand('/work hermes 修')).toEqual({ goal: 'hermes 修', runnerPrefs: {} });
		expect(parseWorkCommand('/work')).toEqual({ goal: '', runnerPrefs: {} });
	});

	it('parses one-shot deep and fast presets in any order with runners without false positives', () => {
		expect(parseWorkCommand('/work 深度 给 HaloWebUI 加按钮')).toEqual({
			goal: '给 HaloWebUI 加按钮',
			runnerPrefs: {},
			preset: 'deep'
		});
		expect(parseWorkCommand('/work 深度 cchclaude 给 HaloWebUI 加按钮')).toEqual({
			goal: '给 HaloWebUI 加按钮',
			runnerPrefs: { claude: 'cchclaude' },
			preset: 'deep'
		});
		expect(parseWorkCommand('/work cchclaude 快速：修个文案')).toEqual({
			goal: '修个文案',
			runnerPrefs: { claude: 'cchclaude' },
			preset: 'fast'
		});
		expect(parseWorkCommand('/work 深度优化一下接口')).toEqual({
			goal: '深度优化一下接口',
			runnerPrefs: {}
		});
	});

	it('is not a command otherwise', () => {
		expect(parseWorkCommand('/workspace 打开')).toBeNull();
		expect(parseWorkCommand('帮我 /work 一下')).toBeNull();
		expect(parseWorkCommand('')).toBeNull();
		expect(parseWorkCommand(null)).toBeNull();
	});
});

describe('workFileIds', () => {
	it('keeps uploaded files only', () => {
		expect(
			workFileIds([
				{ id: 'f1', type: 'file' },
				{ id: 'i1', type: 'image' },
				{ type: 'image' },
				{ id: 'k1', type: 'collection' }
			])
		).toEqual(['f1', 'i1']);
	});
});
