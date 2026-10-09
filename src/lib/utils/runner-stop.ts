import { toast } from 'svelte-sonner';

import { stopHermesBackgroundRunner } from '$lib/apis/hermes';
import { hermesBackgroundRuns } from '$lib/stores';

// Stopping a background runner (reclaude / codex / agy …) from the chat banner or
// the sidebar's 运行中 list: one place for the call, the list update and the words.

export const backgroundRunnerLabel = (agent: string) =>
	agent === 'officlaude' ? '官方 Claude' : agent;

/** Stop the run; true when it stopped. Errors become a toast, not a throw. */
export const stopBackgroundRun = async (run: { run_id: string; agent: string }) => {
	const label = backgroundRunnerLabel(run.agent);
	try {
		const result = await stopHermesBackgroundRunner(localStorage.token, run.run_id);
		hermesBackgroundRuns.update((runs) => runs.filter((item) => item.run_id !== run.run_id));
		toast.success(
			result.report_shown && result.resumable !== false
				? `已停止 ${label}，直接回复就能让它按新说明接着做`
				: `已停止 ${label}`
		);
		return true;
	} catch (error) {
		toast.error(`没能停止 ${label}：${error}`);
		return false;
	}
};

/**
 * Stopping ends a task that may have been running for an hour: the first press
 * only arms the button ("确认停止"), a second press within 5 s stops it.
 * `onChange` re-renders the caller with the armed / stopping run ids.
 */
export const createRunStopper = (
	onChange: (state: { armed: string | null; stopping: string | null }) => void
) => {
	let armed: string | null = null;
	let stopping: string | null = null;
	let timer: ReturnType<typeof setTimeout> | null = null;
	const emit = () => onChange({ armed, stopping });

	const press = async (run: { run_id: string; agent: string }) => {
		if (stopping) return;
		if (armed !== run.run_id) {
			armed = run.run_id;
			if (timer) clearTimeout(timer);
			timer = setTimeout(() => {
				armed = null;
				emit();
			}, 5000);
			emit();
			return;
		}
		armed = null;
		stopping = run.run_id;
		emit();
		try {
			await stopBackgroundRun(run);
		} finally {
			stopping = null;
			emit();
		}
	};
	const dispose = () => {
		if (timer) clearTimeout(timer);
	};
	return { press, dispose };
};
