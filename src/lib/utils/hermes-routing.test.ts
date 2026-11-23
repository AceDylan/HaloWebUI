import { describe, expect, it } from 'vitest';
import {
	chainAdd,
	chainCandidates,
	chainMove,
	chainRemove,
	describeChange,
	diffRouting,
	historySourceLabel,
	modelFamily,
	modelLabel,
	orderedAuxTasks,
	withPrimary
} from './hermes-routing';

const routing = () => ({
	main: 'deepseek-chat',
	fallback: ['gpt-chat', 'gemini-chat'],
	delegation: { model: '', fallback: [] as string[] },
	auxiliary: { compression: { model: 'gemini-chat', fallback: ['deepseek-chat'] } },
	media: { model: 'gemini-chat', timeout: 300 }
});

describe('hermes routing helpers', () => {
	it('edits a chain without duplicates or going past the limit', () => {
		expect(chainAdd(['a'], 'b', 3)).toEqual(['a', 'b']);
		expect(chainAdd(['a'], 'a', 3)).toEqual(['a']);
		expect(chainAdd(['a', 'b'], 'c', 2)).toEqual(['a', 'b']);
		expect(chainMove(['a', 'b', 'c'], 2, -1)).toEqual(['a', 'c', 'b']);
		expect(chainMove(['a', 'b'], 0, -1)).toEqual(['a', 'b']);
		expect(chainRemove(['a', 'b', 'c'], 1)).toEqual(['a', 'c']);
		expect(chainCandidates(['a', 'b', 'c', 'd'], ['b'], 'a')).toEqual(['c', 'd']);
		expect(withPrimary(['a', 'b'], 'a')).toEqual(['b']);
	});

	it('describes changes in plain words', () => {
		const after = routing();
		after.main = 'gpt-chat';
		after.fallback = ['gemini-chat'];
		after.auxiliary.compression = { model: '', fallback: [] };
		after.media.timeout = 120;
		const lines = diffRouting(routing(), after).map(describeChange);
		expect(lines).toEqual([
			'主模型：deepseek-chat → gpt-chat',
			'兜底链：gpt-chat › gemini-chat → gemini-chat',
			'上下文压缩：gemini-chat → 跟随主模型',
			'上下文压缩兜底：deepseek-chat → 无',
			'媒体超时：300 秒 → 120 秒'
		]);
		expect(diffRouting(routing(), routing())).toEqual([]);
	});

	it('labels models, families, sources and orders tasks', () => {
		expect(modelLabel('')).toBe('跟随主模型');
		expect(modelLabel('?openrouter/x')).toBe('其他：openrouter/x');
		expect(modelFamily('claude-chat')).toBe('claude');
		expect(modelFamily('gpt-chat')).toBe('gpt');
		expect(modelFamily('mystery')).toBe('other');
		expect(historySourceLabel('halowebui')).toBe('网页');
		expect(historySourceLabel('rollback:1')).toBe('回滚');
		expect(orderedAuxTasks(['zzz', 'vision', 'compression'])).toEqual([
			'compression',
			'vision',
			'zzz'
		]);
	});
});
