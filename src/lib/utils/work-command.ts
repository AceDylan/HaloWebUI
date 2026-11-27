/**
 * `/work [runner …] <需求>` typed in a chat: the 协作台's `work` workflow (planning → development →
 * Claude reviews and fixes → commit, push, deploy, clean up), started at once and shown as the team's
 * card in this chat. The same command as Telegram / QQ (the Hermes plugin's tg.split_work_args): a
 * runner named first is used for its family and never falls back to another one.
 */

export type WorkFamily = 'claude' | 'agy' | 'codex';
export type WorkPreset = 'deep' | 'fast';
export type WorkCommand = {
	goal: string;
	runnerPrefs: Partial<Record<WorkFamily, string>>;
	preset?: WorkPreset;
};

export const WORK_RUNNERS: Record<string, WorkFamily> = {
	officlaude: 'claude',
	cchclaude: 'claude',
	anyclaude: 'claude',
	reclaude: 'claude',
	offiagy: 'agy',
	agy: 'agy',
	codex: 'codex'
};

const WORK_PRESET_WORDS: readonly [string, WorkPreset][] = [
	['深度多模型', 'deep'],
	['多模型研发', 'deep'],
	['多模型', 'deep'],
	['深度', 'deep'],
	['完整', 'deep'],
	['deep', 'deep'],
	['快速精简', 'fast'],
	['快速', 'fast'],
	['精简', 'fast'],
	['fast', 'fast']
];

export const WORK_USAGE =
	'/work 需求：按「默认工作流」执行；/work 深度 需求 按「深度多模型」执行；/work 快速 需求 按「快速精简」执行（均可在「设置 → Hermes 模型」中独立自定义模块与前后端执行器）；/work cchclaude 需求 单次指定执行器。';

const COMMAND_RE = /^\s*\/work(?=$|[\s：:])[\s：:]*([\s\S]*)$/i;
const RUNNER_RE = /^([A-Za-z]+)(?=$|[\s：:，,])/;
const SEPARATORS_RE = /^[\s：:，,　]+/;
const SEP_CHAR_RE = /^[\s：:，,　]/;

/** The command in *text*, or null when the text is not a /work command. */
export const parseWorkCommand = (text: string | null | undefined): WorkCommand | null => {
	const found = COMMAND_RE.exec(text ?? '');
	if (!found) return null;
	let goal = found[1].trim();
	const runnerPrefs: WorkCommand['runnerPrefs'] = {};
	let preset: WorkPreset | undefined;
	for (;;) {
		if (!preset) {
			const lower = goal.toLowerCase();
			let matched = false;
			for (const [word, key] of WORK_PRESET_WORDS) {
				if (lower.startsWith(word)) {
					const rest = goal.slice(word.length);
					if (!rest || SEP_CHAR_RE.test(rest)) {
						preset = key;
						goal = rest.replace(SEPARATORS_RE, '');
						matched = true;
						break;
					}
				}
			}
			if (matched) continue;
		}
		const word = RUNNER_RE.exec(goal);
		const name = word?.[1].toLowerCase() ?? '';
		const family = WORK_RUNNERS[name];
		if (!word || !family || runnerPrefs[family]) break;
		runnerPrefs[family] = name;
		goal = goal.slice(word[0].length).replace(SEPARATORS_RE, '');
	}
	return preset ? { goal, runnerPrefs, preset } : { goal, runnerPrefs };
};

/** The uploaded composer files a team can take (their file ids). */
export const workFileIds = (files: { id?: string | null; type?: string }[] | null | undefined): string[] =>
	(files ?? [])
		.filter((file) => file?.id && file.type !== 'collection' && file.type !== 'doc')
		.map((file) => file.id as string);
