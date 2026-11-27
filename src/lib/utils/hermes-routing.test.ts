import { describe, expect, it } from 'vitest';
import type { HermesWorkConfigResponse, WorkProfileConfig, WorkWorkflowConfig } from '$lib/apis/hermes';
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
	withWorkProfile,
	workChanges,
	workConfigEquals,
	workDraftFrom,
	workFlowSummary,
	workProfileOf,
	workSelfReviewWarning
} from './hermes-routing';

const routing = () => ({
	main: 'deepseek-chat',
	fallback: ['gpt-chat', 'gemini-chat'],
	delegation: { model: '', fallback: [] as string[] },
	auxiliary: { compression: { model: 'gemini-chat', fallback: ['deepseek-chat'] } },
	media: { model: 'gemini-chat', timeout: 300 }
});

const workProfile = (over: Partial<WorkProfileConfig> = {}): WorkProfileConfig => ({
	plan_review: true,
	dual_plan: false,
	plan_approval: false,
	ui_review: false,
	split_dev: true,
	codex_review: false,
	steps: {
		plan: { runner: 'offiagy', fallback: ['agy'] },
		plan_review: { runner: 'officlaude', fallback: ['cchclaude'] },
		dev: { runner: 'codex', fallback: [] },
		frontend: { runner: 'offiagy', fallback: ['agy'] },
		review: { runner: 'officlaude', fallback: ['cchclaude', 'anyclaude'] }
	},
	...over
});

const workConfig = (): WorkWorkflowConfig => ({
	...workProfile(),
	presets: {
		deep: workProfile({
			plan_review: true,
			dual_plan: true,
			plan_approval: true,
			ui_review: true,
			split_dev: true,
			codex_review: true
		}),
		fast: workProfile({
			plan_review: false,
			dual_plan: false,
			plan_approval: false,
			ui_review: false,
			split_dev: false,
			codex_review: false
		})
	}
});

describe('/work workflow helpers', () => {
	it('copies all three presets and fills missing fields from defaults', () => {
		const defaults = workConfig();
		const config = {
			plan_review: false,
			steps: { plan: { runner: 'hermes', fallback: [] } }
		};
		const res = {
			defaults,
			config,
			runners: [],
			steps_meta: []
		} as unknown as HermesWorkConfigResponse;
		const draft = workDraftFrom(res);
		expect(draft.plan_review).toBe(false);
		expect(draft.steps.plan).toEqual({ runner: 'hermes', fallback: [] });
		expect(draft.steps.frontend).toEqual(defaults.steps.frontend);
		expect(draft.presets.deep.dual_plan).toBe(true);
		expect(draft.presets.fast.split_dev).toBe(false);
		draft.steps.plan.fallback.push('codex');
		draft.presets.deep.steps.review.fallback.pop();
		expect(config.steps.plan.fallback).toEqual([]);
		expect(defaults.presets.deep.steps.review.fallback).toEqual(['cchclaude', 'anyclaude']);
	});

	it('edits each preset independently, tracks changes, and builds flow summaries', () => {
		const before = workConfig();
		let after = setWorkStepRunner(before, 'review', 'cchclaude', 'default');
		after = setWorkStepRunner(after, 'frontend', 'officlaude', 'deep');
		after = withWorkProfile(after, 'fast', {
			...workProfileOf(after, 'fast'),
			plan_review: true
		});
		expect(before.steps.review.fallback).toEqual(['cchclaude', 'anyclaude']);
		expect(after.steps.review.fallback).toEqual(['anyclaude']);
		expect(after.presets.deep.steps.frontend.runner).toBe('officlaude');
		expect(after.presets.fast.plan_review).toBe(true);
		expect(workChanges(before, after)).toEqual({
			changed: true,
			lines: [
				'默认 /work · 审阅修复首选：officlaude → cchclaude',
				'默认 /work · 审阅修复兜底：cchclaude › anyclaude → anyclaude',
				'深度 /work · 前端开发首选：offiagy → officlaude',
				'快速 /work · 规划后审阅：关闭 → 开启'
			]
		});
		expect(workConfigEquals(before, workConfig())).toBe(true);
		expect(workConfigEquals(before, after)).toBe(false);
		expect(workFlowSummary(before, 'default').map((step) => step.key)).toEqual([
			'plan',
			'plan_review',
			'dev',
			'frontend',
			'review'
		]);
		expect(workFlowSummary(before, 'deep').map((step) => step.key)).toEqual([
			'dual_plan',
			'ui_review',
			'dev',
			'frontend',
			'review',
			'codex_review'
		]);
		expect(workFlowSummary(before, 'fast').map((step) => step.key)).toEqual([
			'plan',
			'dev',
			'review'
		]);
	});

	it('warns when frontend and review share a family without codex_review', () => {
		const runners = [
			{ name: 'offiagy', label: 'offiagy', engine: 'AGY', family: 'agy', note: '' },
			{ name: 'officlaude', label: 'officlaude', engine: 'Claude', family: 'claude', note: '' },
			{ name: 'codex', label: 'codex', engine: 'Codex', family: 'codex', note: '' }
		];
		const ok = workProfile();
		expect(workSelfReviewWarning(ok, runners)).toBe('');
		const same = workProfile();
		same.steps.frontend = { runner: 'officlaude', fallback: [] };
		expect(workSelfReviewWarning(same, runners)).toContain('前端开发与审阅修复同属一个模型家族');
		same.codex_review = true;
		expect(workSelfReviewWarning(same, runners)).toBe('');
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
