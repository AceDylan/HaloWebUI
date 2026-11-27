import { describe, expect, it } from 'vitest';
import type { HermesWorkConfigResponse, WorkWorkflowConfig } from '$lib/apis/hermes';
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
	setWorkStepRunner,
	withPrimary,
	workChanges,
	workConfigEquals,
	workDraftFrom,
	workFlowSummary
} from './hermes-routing';

const routing = () => ({
	main: 'deepseek-chat',
	fallback: ['gpt-chat', 'gemini-chat'],
	delegation: { model: '', fallback: [] as string[] },
	auxiliary: { compression: { model: 'gemini-chat', fallback: ['deepseek-chat'] } },
	media: { model: 'gemini-chat', timeout: 300 }
});

const workConfig = (): WorkWorkflowConfig => ({
	plan_review: false,
	steps: {
		plan: { runner: 'offiagy', fallback: ['agy'] },
		plan_review: { runner: 'officlaude', fallback: ['cchclaude'] },
		dev: { runner: 'codex', fallback: [] },
		review: { runner: 'officlaude', fallback: ['cchclaude', 'anyclaude'] }
	}
});

describe('/work workflow helpers', () => {
	it('copies the configuration and fills missing steps from the defaults', () => {
		const defaults = workConfig();
		const config = { plan_review: true, steps: { plan: { runner: 'hermes', fallback: [] } } };
		const res = { defaults, config, runners: [], steps_meta: [] } as unknown as HermesWorkConfigResponse;
		const draft = workDraftFrom(res);
		expect(draft.steps).toEqual({ ...defaults.steps, ...config.steps });
		draft.steps.plan.fallback.push('codex');
		draft.steps.review.fallback.pop();
		expect(config.steps.plan.fallback).toEqual([]);
		expect(defaults.steps.review.fallback).toEqual(['cchclaude', 'anyclaude']);
	});

	it('removes the selected primary from fallback and reports the exact changes', () => {
		const before = workConfig();
		const after = setWorkStepRunner(before, 'review', 'cchclaude');
		after.plan_review = true;
		expect(before.steps.review.fallback).toEqual(['cchclaude', 'anyclaude']);
		expect(after.steps.review.fallback).toEqual(['anyclaude']);
		expect(workChanges(before, after)).toEqual({
			changed: true,
			lines: [
				'规划后审阅：关闭 → 开启',
				'/work 验收修复首选：officlaude → cchclaude',
				'/work 验收修复兜底：cchclaude › anyclaude → anyclaude'
			]
		});
		expect(workConfigEquals(before, workConfig())).toBe(true);
		expect(workConfigEquals(before, after)).toBe(false);
		expect(workFlowSummary(before).map((step) => step.key)).toEqual(['plan', 'dev', 'review']);
		expect(workFlowSummary(after).map((step) => step.key)).toEqual([
			'plan', 'plan_review', 'dev', 'review'
		]);
	});
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

		const withEffortBefore = {
			...routing(),
			reasoning_effort: 'medium',
			reasoning_overrides: { 'claude-chat': 'xhigh' }
		};
		const withEffortAfter = {
			...routing(),
			main: 'openai-codex:gpt-6.2-sol',
			reasoning_effort: 'high',
			reasoning_overrides: {}
		};
		expect(diffRouting(withEffortBefore, withEffortAfter).map(describeChange)).toEqual([
			'主模型：deepseek-chat → Codex · gpt-6.2-sol',
			'思考强度：中 → 高',
			'claude-chat 思考强度：超高 → 跟随全局'
		]);
	});

	it('labels models, families, sources and orders tasks', () => {
		expect(modelLabel('')).toBe('跟随主模型');
		expect(modelLabel('?openrouter/x')).toBe('其他：openrouter/x');
		expect(modelLabel('openai-codex:gpt-6.2-sol')).toBe('Codex · gpt-6.2-sol');
		expect(modelFamily('claude-chat')).toBe('claude');
		expect(modelFamily('gpt-chat')).toBe('gpt');
		expect(modelFamily('codex')).toBe('gpt');
		expect(modelFamily('offiagy')).toBe('gemini');
		expect(modelFamily('agy')).toBe('gemini');
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

describe('agy preferences', () => {
	it('sends only what changed, with plain lines', async () => {
		const { agyChanges } = await import('./hermes-routing');
		const before = { card_model: 'gemini-4-argon-high', ui_runner: 'offiagy', offiagy_model: '' };
		expect(agyChanges(before, { ...before })).toEqual({ update: {}, lines: [] });
		const out = agyChanges(before, {
			card_model: undefined as any,
			ui_runner: 'agy',
			offiagy_model: 'gemini-4-neon-high'
		});
		expect(out.update).toEqual({
			card_model: '',
			ui_runner: 'agy',
			offiagy_model: 'gemini-4-neon-high'
		});
		expect(out.lines).toEqual([
			'回答卡片：gemini-4-argon-high → 关闭（直接走网关 agy）',
			'界面任务起点：offiagy（Google 账号） → agy（网关 gemini-chat）',
			'offiagy 模型：AGY 默认 → gemini-4-neon-high'
		]);
	});
});
