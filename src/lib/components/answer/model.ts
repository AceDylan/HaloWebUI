// 精答工作台: labels, the stages a run goes through, and live socket events applied to a run.
import type { AnswerPart, AnswerRun, AnswerStatus, AssistantAction } from '$lib/apis/answers';

export const STATUS_LABEL: Record<AnswerStatus, string> = {
	routing: '挑选助手',
	researching: '查资料',
	answering: '回答中',
	done: '已答完',
	stopped: '已停止',
	error: '出错',
	interrupted: '已中断'
};

export const isLive = (status: AnswerStatus | string | null | undefined) =>
	status === 'routing' || status === 'researching' || status === 'answering';

export const ACTION_LABEL: Record<AssistantAction, string> = {
	use: '选用',
	template: '选用模板',
	update: '升级',
	create: '新建',
	temporary: '临时',
	direct: '直接回答'
};

/** What happened to the assistant, as a sentence: 「新建了「合同审查」」. */
export const actionSentence = (action: AssistantAction | undefined, name: string) =>
	action === 'create'
		? `新建了「${name}」`
		: action === 'update'
			? `升级了「${name}」`
			: action === 'temporary'
				? `临时组了一个「${name}」`
				: action === 'template'
					? `选用了内置模板「${name}」`
				: action === 'direct'
					? `由 ${name} 直接回答`
					: `选用了「${name}」`;

export type StageState = 'waiting' | 'active' | 'done' | 'error' | 'stopped' | 'skipped';
export type Stage = { key: 'route' | 'assistant' | 'research' | 'answer'; label: string; state: StageState; note: string };

const partState = (status: string | undefined, started: boolean): StageState =>
	status === 'done'
		? 'done'
		: status === 'error'
			? 'error'
			: status === 'stopped'
				? 'stopped'
				: status === 'streaming' || status === 'running' || (status === 'waiting' && started)
					? 'active'
					: 'waiting';

/** The steps of a run as the page shows them: 理解问题 → 助手 → (查资料) → 作答. */
export const stagesOf = (run: AnswerRun): Stage[] => {
	const ended = !isLive(run.status);
	const plan = run.plan ?? { status: 'running' };
	const assistant = run.assistant;
	const route: Stage = {
		key: 'route',
		label: '理解问题',
		state: plan.status === 'running' ? 'active' : plan.status === 'error' ? 'error' : plan.status === 'stopped' ? 'stopped' : 'done',
		note: plan.status === 'running' ? `${run.planner.name} 正在读你的助手库` : plan.status === 'error' ? '调度没成功' : ''
	};
	const pick: Stage = {
		key: 'assistant',
		label: assistant ? `${ACTION_LABEL[assistant.action] ?? '选用'}助手` : '挑选助手',
		state: assistant ? 'done' : ended ? 'skipped' : 'waiting',
		note: assistant ? assistant.name : ''
	};
	const stages: Stage[] = [route, pick];
	if (plan.webSearch || run.research) {
		const research = run.research;
		const state: StageState = research
			? research.status === 'done' || research.status === 'empty'
				? 'done'
				: research.status === 'skipped'
					? 'skipped'
					: research.status === 'error'
					? 'error'
					: research.status === 'stopped'
						? 'stopped'
						: 'active'
			: ended
				? 'skipped'
				: 'waiting';
		stages.push({
			key: 'research',
			label: '联网查资料',
			state,
			note: research?.status === 'done' ? `${research.sources.length} 个来源` : research?.status === 'empty' ? '没查到' : research?.status === 'error' ? '没查成' : research?.status === 'skipped' ? '不需要' : ''
		});
	}
	const answer = run.answer;
	const answerState = partState(answer?.status, !!(answer?.startedAt || answer?.retry));
	stages.push({
		key: 'answer',
		label: '作答',
		state: answerState === 'waiting' && ended ? 'skipped' : answerState,
		note: answer?.retry ? `${answer.retry.reason}，稍后重试` : answer?.thinking && !answer.content ? '思考中' : ''
	});
	return stages;
};

export type AnswerEvent = {
	kind: 'state' | 'delta' | 'answer' | 'end' | 'meta';
	chatId: string;
	runId?: string;
	v?: number;
	run?: AnswerRun;
	offset?: number;
	text?: string;
	answer?: Partial<AnswerPart>;
	status?: AnswerStatus;
	title?: string;
	folderId?: string | null;
};

/**
 * Apply one live event to a run. Returns the new run and whether the page fell behind (a delta
 * that does not line up with the text it has): then it should fetch the run again.
 */
export const applyEvent = (run: AnswerRun | null, event: AnswerEvent): { run: AnswerRun | null; stale: boolean } => {
	if (event.kind === 'state' && event.run) return { run: event.run, stale: false };
	if (!run || (event.runId && event.runId !== run.id)) return { run, stale: event.kind === 'delta' };
	if (event.kind === 'delta') {
		const have = run.answer.content ?? '';
		const offset = event.offset ?? 0;
		if (offset > have.length) return { run, stale: true };
		const answer = {
			...run.answer,
			content: have.slice(0, offset) + (event.text ?? ''),
			status: run.answer.status === 'waiting' ? 'streaming' : run.answer.status,
			thinking: event.text ? false : run.answer.thinking
		} as AnswerPart;
		return { run: { ...run, answer }, stale: false };
	}
	if (event.kind === 'answer' && event.answer) {
		return { run: { ...run, answer: { ...run.answer, ...event.answer } }, stale: false };
	}
	if (event.kind === 'end' && event.status) return { run: { ...run, status: event.status }, stale: false };
	return { run, stale: false };
};

/** The question with its answer, for handing to another mode as background. */
export const answerContext = (run: AnswerRun): string => {
	const who = run.assistant ? `「${run.assistant.name}」` : '助手';
	const sources = (run.research?.sources ?? []).map((s) => `[${s.n}] ${s.title || s.url} ${s.url}`).join('\n');
	return `问题：${run.question}\n\n${who}的回答：\n${run.answer.content}${sources ? `\n\n资料：\n${sources}` : ''}`;
};

export const QUICK: { title: string; hint: string; text: string }[] = [
	{ title: '合同条款', hint: '会找或建一位合同审查助手', text: '租房合同里写「押金在退租后 60 天内退还，房屋有任何损坏从押金扣除」，这条对租客有什么风险？怎么改？' },
	{ title: '代码排错', hint: '会用懂这门语言的助手', text: 'Python 里 `for i in range(len(lst)): lst.remove(lst[i])` 为什么会报 IndexError？正确写法是什么？' },
	{ title: '旅行规划', hint: '需要最新信息时会先联网', text: '十一月去成都玩 3 天，预算 3000 元，给我一个不赶的行程。' },
	{ title: '写作润色', hint: '会按写作要求升级助手', text: '把这段话改得更像正式邮件：\n\n（把原文贴在这里）' }
];
