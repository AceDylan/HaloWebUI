import { describe, expect, it } from 'vitest';
import {
	EMPTY_HERMES_RUN_OPTIONS,
	getUpstreamModelId,
	hermesRunOptionsForRequest,
	isHermesAgentModel,
	isHermesAgentModelId,
	isHermesRunSteerable,
	normalizeHermesRunOptions,
	describeHermesReply,
	describeHermesRunNotice,
	findHermesContinuation,
	hermesDispatchToRestore,
	hermesOptionsForMessage,
	hermesOptionsForReply,
	hermesOptionsToKeep,
	parseHermesRunNotice,
	reportDurationSeconds
} from './hermes';

describe('isHermesAgentModelId', () => {
	it('matches the bare id, the selection id and the legacy prefixed id', () => {
		expect(isHermesAgentModelId('hermes-agent')).toBe(true);
		expect(isHermesAgentModelId('modelref::openai::personal::id:ee5e02db::hermes-agent')).toBe(
			true
		);
		expect(isHermesAgentModelId('ee5e02db.hermes-agent')).toBe(true);
	});

	it('rejects other models and empty values', () => {
		expect(isHermesAgentModelId('modelref::openai::personal::id:13c104eb::gpt-chat')).toBe(false);
		expect(isHermesAgentModelId('gpt-image')).toBe(false);
		expect(isHermesAgentModelId('')).toBe(false);
		expect(isHermesAgentModelId(undefined)).toBe(false);
	});

	it('honours the configured id list and falls back to the default when it is empty', () => {
		expect(isHermesAgentModelId('my-agent', ['my-agent'])).toBe(true);
		expect(isHermesAgentModelId('hermes-agent', ['my-agent'])).toBe(false);
		expect(isHermesAgentModelId('hermes-agent', [])).toBe(true);
	});

	it('extracts the upstream id from a selection id', () => {
		expect(getUpstreamModelId('modelref::openai::personal::id:ee5e02db::hermes-agent')).toBe(
			'hermes-agent'
		);
		expect(getUpstreamModelId('plain')).toBe('plain');
	});
});

describe('isHermesAgentModel', () => {
	it('reads the upstream id of a resolved model entry, even behind a prefixed id', () => {
		expect(
			isHermesAgentModel({
				id: 'modelref::openai::personal::id:ee5e02db::hermes-agent',
				model_id: 'hermes-agent'
			})
		).toBe(true);
		expect(isHermesAgentModel({ id: 'ee5e02db.hermes-agent', original_id: 'hermes-agent' })).toBe(
			true
		);
		expect(isHermesAgentModel({ id: 'x', model_ref: { model_id: 'hermes-agent' } })).toBe(true);
		expect(isHermesAgentModel({ id: 'ee5e02db.hermes-agent' })).toBe(true);
	});

	it('rejects other models, missing entries and ids outside the configured list', () => {
		expect(
			isHermesAgentModel({
				id: 'modelref::openai::personal::id:13c104eb::gpt-chat',
				model_id: 'gpt-chat'
			})
		).toBe(false);
		expect(isHermesAgentModel(null)).toBe(false);
		expect(isHermesAgentModel({})).toBe(false);
		expect(isHermesAgentModel({ id: 'hermes-agent' }, ['my-agent'])).toBe(false);
		expect(isHermesAgentModel({ id: 'my-agent' }, ['my-agent'])).toBe(true);
	});
});

describe('isHermesRunSteerable', () => {
	const running = { role: 'assistant', done: false, model: 'ee5e02db.hermes-agent' };

	it('offers to steer an unfinished hermes reply', () => {
		expect(isHermesRunSteerable(running)).toBe(true);
		expect(
			isHermesRunSteerable({ role: 'assistant', done: false }, undefined, 'hermes-agent')
		).toBe(true);
	});

	it('stops once the backend says the run ended, even though the message still streams', () => {
		expect(isHermesRunSteerable({ ...running, hermesRun: { active: false } })).toBe(false);
		expect(
			isHermesRunSteerable({ ...running, hermesRun: { active: false, reason: 'steer_rejected' } })
		).toBe(false);
		expect(isHermesRunSteerable({ ...running, hermesRun: { active: true } })).toBe(true);
	});

	it('never offers to steer a finished reply, a user message or another model', () => {
		expect(isHermesRunSteerable({ ...running, done: true })).toBe(false);
		expect(isHermesRunSteerable({ ...running, role: 'user' })).toBe(false);
		expect(isHermesRunSteerable({ ...running, model: 'gpt-chat' })).toBe(false);
		expect(isHermesRunSteerable(null)).toBe(false);
	});
});

describe('hermes run options', () => {
	it('keeps only valid choices', () => {
		expect(
			normalizeHermesRunOptions({
				dispatch: 'reclaude',
				model: ' claude-opus-5 ',
				provider: 'anthropic',
				// Saved before the thinking level followed the chat's own.
				reasoning_effort: 'high'
			})
		).toEqual({
			dispatch: 'reclaude',
			model: 'claude-opus-5',
			provider: 'anthropic'
		});
		expect(normalizeHermesRunOptions({ provider: 'anthropic' }).provider).toBe('');
		expect(normalizeHermesRunOptions(null)).toEqual(EMPTY_HERMES_RUN_OPTIONS);
	});

	it('sends nothing when every choice is the default', () => {
		expect(hermesRunOptionsForRequest(EMPTY_HERMES_RUN_OPTIONS)).toBeNull();
		expect(
			hermesRunOptionsForRequest({ ...EMPTY_HERMES_RUN_OPTIONS, dispatch: 'codex' })
		).toEqual({ dispatch: 'codex' });
	});
});

describe('per-message hermes options', () => {
	it('keeps the model for the chat but never a dispatch', () => {
		expect(hermesOptionsToKeep({ dispatch: 'reclaude', model: 'claude-chat', provider: 'p' })).toEqual({
			dispatch: '',
			model: 'claude-chat',
			provider: 'p'
		});
	});

	it('regenerates with what the message was sent with', () => {
		const panel = { dispatch: 'codex', model: 'deepseek-chat', provider: 'd' } as const;
		expect(hermesOptionsForReply({ dispatch: 'agy', model: '', provider: '' }, panel)).toEqual({
			dispatch: 'agy',
			model: '',
			provider: ''
		});
		// Sent before options were recorded: the panel's model, no dispatch.
		expect(hermesOptionsForReply(undefined, panel)).toEqual({
			dispatch: '',
			model: 'deepseek-chat',
			provider: 'd'
		});
	});
});

describe('describeHermesReply', () => {
	it('names the runner and the model hermes actually used', () => {
		expect(describeHermesReply({ dispatch: 'codex', model: 'claude-chat' }, null)?.label).toBe(
			'codex · claude-chat'
		);
		const fallback = describeHermesReply(
			{ model: 'deepseek-chat', fallback_from: 'gemini-chat' },
			{ model: 'gemini-chat' }
		);
		expect(fallback?.label).toBe('gemini-chat → deepseek-chat');
		expect(fallback?.fallback).toBe(true);
		expect(fallback?.title).toContain('gemini-chat 不可用，已改用 deepseek-chat');
	});

	it('falls back to what was asked for, and says nothing for a plain default reply', () => {
		expect(describeHermesReply(null, { dispatch: '', model: 'claude-chat' })?.label).toBe(
			'claude-chat'
		);
		expect(describeHermesReply({ active: false } as any, { dispatch: '', model: '' })).toBeNull();
		const fast = describeHermesReply(
			{ dispatch: 'reclaude', fast_dispatch: true, runner_run_id: 'r1', model: 'x' },
			null
		);
		expect(fast?.label).toBe('reclaude');
		expect(fast?.title).toContain('没有经过模型');
	});
});

describe('runner completion notices', () => {
	const content =
		'[后台任务完成通知] reclaude 运行 20260926-214156-38f80bb8 已结束，状态：success，Claude 会话：f11131eb-4cc9-44a4-929b-c0c5b3cef3b6。';

	it('recognises the notice the runner writes', () => {
		const notice = parseHermesRunNotice({ role: 'user', content });
		expect(notice).toEqual({
			agent: 'reclaude',
			runId: '20260926-214156-38f80bb8',
			status: 'success',
			sessionLabel: 'Claude 会话',
			sessionId: 'f11131eb-4cc9-44a4-929b-c0c5b3cef3b6'
		});
		expect(describeHermesRunNotice(notice!)).toBe('✅ reclaude 已完成');
		expect(
			describeHermesRunNotice(parseHermesRunNotice({ role: 'user', content: content.replace('success', 'question') })!)
		).toBe('❓ reclaude 等你决定');
	});

	it('leaves the person\'s own messages alone', () => {
		expect(parseHermesRunNotice({ role: 'user', content: '后台任务完成通知是什么？' })).toBeNull();
		expect(parseHermesRunNotice({ role: 'assistant', content })).toBeNull();
		expect(
			parseHermesRunNotice({ role: 'user', content: 'x', hermes_notice: { source: 'codex-runner' } })
				?.agent
		).toBe('codex-runner');
	});

	it('reads the duration from the report', () => {
		expect(
			reportDurationSeconds('✅ reclaude 运行 r · 已完成\nClaude 会话 s · 116 轮 · 27m47s\n\n正文')
		).toBe(27 * 60 + 47);
		expect(reportDurationSeconds('✅ codex 运行 r · 已完成\ncodex thread t · 1h2m\n')).toBe(3720);
		expect(reportDurationSeconds('<div>card</div>')).toBeNull();
	});
});

describe('接着上次: a follow-up goes back to the run whose report ends the chat', () => {
	const runId = '20260927-005655-f2dd355f';
	const chat = (extra: Record<string, any> = {}, status = 'success') => ({
		currentId: 'report',
		messages: {
			ask: { id: 'ask', role: 'user', content: '如何破局呢', hermesOptions: { dispatch: 'reclaude' } },
			launch: { id: 'launch', parentId: 'ask', role: 'assistant', done: true, content: 'reclaude 已启动' },
			notice: {
				id: 'notice',
				parentId: 'launch',
				role: 'user',
				content: `[后台任务完成通知] reclaude 运行 ${runId} 已结束，状态：${status}，Claude 会话：s-1。`,
				hermes_notice: { source: 'reclaude-runner', run_id: runId }
			},
			report: { id: 'report', parentId: 'notice', role: 'assistant', done: true, content: '✅ …' },
			...extra
		}
	});

	it('finds the run from the report at the end of the chat', () => {
		expect(findHermesContinuation(chat())).toEqual({ runner: 'reclaude', runId, status: 'success' });
		expect(findHermesContinuation(chat({}, 'question'))?.status).toBe('question');
		// The notice as the backend stores it, without the text the runner wrote.
		const stored = chat();
		stored.messages.notice.content = '通知';
		stored.messages.notice.hermes_notice = { source: 'codex-runner', run_id: `${runId}-a1` };
		expect(findHermesContinuation(stored)).toEqual({ runner: 'codex', runId: `${runId}-a1`, status: '' });
	});

	it('finds nothing once anything else ends the chat', () => {
		// Still going: the launch reply is the last message.
		expect(findHermesContinuation({ ...chat(), currentId: 'launch' })).toBeNull();
		// Said since: hermes answered the next message.
		const answered = chat({
			next: { id: 'next', parentId: 'report', role: 'user', content: '多久一次？' },
			reply: { id: 'reply', parentId: 'next', role: 'assistant', done: true, content: '每季度' }
		});
		expect(findHermesContinuation({ ...answered, currentId: 'reply' })).toBeNull();
		// A report still streaming, a run that never started, a malformed id.
		const streaming = chat();
		streaming.messages.report.done = false;
		expect(findHermesContinuation(streaming)).toBeNull();
		expect(findHermesContinuation(chat({}, 'quota_blocked'))).toBeNull();
		const odd = chat();
		odd.messages.notice.content = '[后台任务完成通知] reclaude 运行 ../x 已结束，状态：success。';
		expect(findHermesContinuation(odd)).toBeNull();
		expect(findHermesContinuation(null)).toBeNull();
	});

	it('sends "直接" back to the run, and anything picked as picked', () => {
		const continuation = findHermesContinuation(chat());
		const panel = { dispatch: '', model: 'claude-chat', provider: 'p' } as const;
		expect(hermesOptionsForMessage(panel, continuation, '多久一次？')).toEqual({
			dispatch: 'reclaude',
			model: 'claude-chat',
			provider: 'p',
			continue_run: runId
		});
		// "直接" picked on purpose: hermes answers.
		expect(hermesOptionsForMessage({ ...panel, dispatch: 'hermes' }, continuation, 'x')).toEqual(panel);
		// A runner picked: a new task, as before.
		expect(hermesOptionsForMessage({ ...panel, dispatch: 'codex' }, continuation, 'x')).toEqual({
			...panel,
			dispatch: 'codex'
		});
		// A typed command wins; no report at the end: hermes, as before.
		expect(hermesOptionsForMessage(panel, continuation, '/codex 新任务').continue_run).toBeUndefined();
		expect(hermesOptionsForMessage(panel, null, 'x')).toEqual(panel);
	});

	it('keeps the resolved choice on the message, never in the chat', () => {
		const sent = { dispatch: 'reclaude', model: '', provider: '', continue_run: runId } as const;
		expect(normalizeHermesRunOptions(sent)).toEqual(sent);
		expect(hermesRunOptionsForRequest(sent)).toEqual({ dispatch: 'reclaude', continue_run: runId });
		// Regenerating goes back to the same run.
		expect(hermesOptionsForReply(sent, EMPTY_HERMES_RUN_OPTIONS)).toEqual(sent);
		expect(hermesOptionsToKeep(sent)).toEqual(EMPTY_HERMES_RUN_OPTIONS);
		expect(hermesOptionsToKeep({ dispatch: 'hermes', model: '', provider: '' })).toEqual(
			EMPTY_HERMES_RUN_OPTIONS
		);
		// Only a run id, and only with a runner.
		expect(normalizeHermesRunOptions({ dispatch: 'reclaude', continue_run: '../x' })).toEqual({
			dispatch: 'reclaude',
			model: '',
			provider: ''
		});
		expect(normalizeHermesRunOptions({ dispatch: '', continue_run: runId }).continue_run).toBeUndefined();
		// Taken back into the input: the panel goes back to following the chat.
		expect(hermesDispatchToRestore(sent)).toBe('');
		expect(hermesDispatchToRestore({ dispatch: 'agy' })).toBe('agy');
	});

	it('labels the reply with the run it went back to', () => {
		const continued = describeHermesReply(
			{ active: false, dispatch: 'reclaude', fast_dispatch: true, runner_run_id: `${runId}-a1`, continued_from: runId },
			{ dispatch: 'reclaude', model: '', provider: '', continue_run: runId }
		);
		expect(continued?.label).toBe('reclaude · 接着上次');
		expect(continued?.title).toContain(`交回 reclaude 运行 ${runId} 的原会话继续`);
		// Hermes' model took it after all (the run was still going): say who answered.
		const answered = describeHermesReply(
			{ active: false, dispatch: 'reclaude', model: 'gpt-chat' },
			{ dispatch: 'reclaude', model: '', provider: '', continue_run: runId }
		);
		expect(answered?.label).toBe('gpt-chat');
		expect(answered?.title).toContain(`没能直接交回 reclaude 运行 ${runId}，由 Hermes 处理`);
		expect(answered?.title).not.toContain('模型只管 Hermes 这一轮');
	});
});
