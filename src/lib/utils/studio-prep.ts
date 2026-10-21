// 提示词增强 in the video and image studios (backend utils/studio_prep.py): gpt-chat reads the
// request, looks things up on the web or asks 精答 / 讨论 first when it needs to, and rewrites it.
// The studio then goes on as before with the enhanced text.

import {
	getStudioPrep,
	type StudioPrepJob,
	type StudioPrepResult
} from '$lib/apis/studio-prep';

/** What the studio lets the enhancement do (remembered between visits). */
export type PrepOptions = {
	/** Enhance the request before it is made (the video studio's 开始制作). */
	enhance: boolean;
	/** Look things up on the web when the request needs facts. */
	research: boolean;
	/** Video: ask 精答 / 讨论 first when the content needs working out. */
	deeper: boolean;
};

export const DEFAULT_PREP_OPTIONS: PrepOptions = { enhance: true, research: true, deeper: true };

export const normalizePrepOptions = (value: unknown): PrepOptions => {
	const raw = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
	const flag = (key: keyof PrepOptions) =>
		typeof raw[key] === 'boolean' ? (raw[key] as boolean) : DEFAULT_PREP_OPTIONS[key];
	return { enhance: flag('enhance'), research: flag('research'), deeper: flag('deeper') };
};

export const PREP_POLL_MS = 1500;
const MISSED_POLLS_MAX = 5;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** The job read again until it ends (done, error, cancelled); `onUpdate` sees every reading.
 * `stopped()` true: stop reading (the page went away), the last reading is returned. A few
 * failed readings in a row (the network) end it as an error. */
export const waitForPrep = async (
	token: string,
	job: StudioPrepJob,
	opts: {
		onUpdate?: (job: StudioPrepJob) => void;
		stopped?: () => boolean;
		get?: typeof getStudioPrep;
		interval?: number;
	} = {}
): Promise<StudioPrepJob> => {
	const get = opts.get ?? getStudioPrep;
	let current = job;
	let missed = 0;
	while (current.status === 'running' && !opts.stopped?.()) {
		await sleep(opts.interval ?? PREP_POLL_MS);
		if (opts.stopped?.()) break;
		try {
			current = await get(token, current.id);
			missed = 0;
			opts.onUpdate?.(current);
		} catch (error: any) {
			missed += 1;
			if (error?.status === 404 || missed >= MISSED_POLLS_MAX) {
				current = {
					...current,
					status: 'error',
					error: error?.status === 404 ? '这次增强已经不在了（服务重启过），再试一次' : '读不到增强进度'
				};
				opts.onUpdate?.(current);
			}
		}
	}
	return current;
};

/** The words of an API error. */
export const prepErrorText = (error: any, fallback = '增强没成功') =>
	typeof error?.detail === 'string' && error.detail.trim() ? error.detail : fallback;

/** A short line on what the enhancement brought: sources, the 精答 / 讨论 it asked. */
export const prepSummary = (result: StudioPrepResult | null | undefined, model = ''): string => {
	if (!result) return '';
	const parts = [`已用 ${model || 'gpt-chat'} 增强`];
	if (result.run) parts.push(`参考了${result.run.label}结论`);
	if (result.sources.length) parts.push(`${result.sources.length} 个网上来源`);
	return parts.join(' · ');
};
