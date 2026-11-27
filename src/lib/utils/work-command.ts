/**
 * `/work [runner …] <需求>` typed in a chat: the 协作台's `work` workflow (planning → development →
 * Claude reviews and fixes → commit, push, deploy, clean up), started at once and shown as the team's
 * card in this chat. The same command as Telegram / QQ (the Hermes plugin's tg.split_work_args): a
 * runner named first is used for its family and never falls back to another one.
 */

export type WorkFamily = 'claude' | 'agy' | 'codex';
export type WorkCommand = { goal: string; runnerPrefs: Partial<Record<WorkFamily, string>> };

export const WORK_RUNNERS: Record<string, WorkFamily> = {
	officlaude: 'claude',
	cchclaude: 'claude',
	anyclaude: 'claude',
	reclaude: 'claude',
	offiagy: 'agy',
	agy: 'agy',
	codex: 'codex'
};

export const WORK_USAGE =
	'/work 需求：规划 → 开发 → 审阅修复 → 自动提交推送部署清理。需求里写上项目名或路径。可在 HaloWebUI 设置 → Hermes 模型 自定义各环节执行器、兜底顺序与是否开启规划审阅。/work cchclaude 需求 可单次指定首选属于 Claude 家族的环节。';

const COMMAND_RE = /^\s*\/work(?=$|[\s：:])[\s：:]*([\s\S]*)$/i;
const RUNNER_RE = /^([A-Za-z]+)(?=$|[\s：:，,])/;
const SEPARATORS_RE = /^[\s：:，,　]+/;

/** The command in *text*, or null when the text is not a /work command. */
export const parseWorkCommand = (text: string | null | undefined): WorkCommand | null => {
	const found = COMMAND_RE.exec(text ?? '');
	if (!found) return null;
	let goal = found[1].trim();
	const runnerPrefs: WorkCommand['runnerPrefs'] = {};
	for (;;) {
		const word = RUNNER_RE.exec(goal);
		const name = word?.[1].toLowerCase() ?? '';
		const family = WORK_RUNNERS[name];
		if (!word || !family || runnerPrefs[family]) break;
		runnerPrefs[family] = name;
		goal = goal.slice(word[0].length).replace(SEPARATORS_RE, '');
	}
	return { goal, runnerPrefs };
};

/** The uploaded composer files a team can take (their file ids). */
export const workFileIds = (files: { id?: string | null; type?: string }[] | null | undefined): string[] =>
	(files ?? [])
		.filter((file) => file?.id && file.type !== 'collection' && file.type !== 'doc')
		.map((file) => file.id as string);
