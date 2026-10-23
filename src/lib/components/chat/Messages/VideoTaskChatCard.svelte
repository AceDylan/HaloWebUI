<script lang="ts">
	/**
	 * 视频工作台 task on its chat's reply (``video_task``): the workbench's card for this chat,
	 * read again while the video is being made. The reply under it streams Hermes' own work.
	 */
	import { onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { getVideoTask, stopVideoTask, videoTaskLive, type VideoTask } from '$lib/apis/video-studio';
	import VideoTaskCard from '$lib/components/workspace/VideoTaskCard.svelte';

	export let chatId: string;

	const POLL_MS = { running: 3000, background: 10000 };
	const POLL_HIDDEN_MS = 30000;

	let task: VideoTask | null = null;
	let stopping = false;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;

	const schedule = () => {
		if (timer) clearTimeout(timer);
		if (destroyed || !videoTaskLive(task)) return;
		const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden';
		timer = setTimeout(load, hidden ? POLL_HIDDEN_MS : POLL_MS[task!.state as 'running' | 'background']);
	};

	const load = async () => {
		try {
			task = await getVideoTask(localStorage.token, chatId);
		} catch (error) {
			if ((error as any)?.status === 404) return; // not a task (any more): no card
			console.warn('video task unavailable', error);
		}
		schedule();
	};

	const stop = async () => {
		if (stopping) return;
		stopping = true;
		try {
			task = await stopVideoTask(localStorage.token, chatId);
		} catch (error) {
			toast.error(`${(error as any)?.detail ?? (error as Error)?.message ?? error}`);
		} finally {
			stopping = false;
		}
		schedule();
	};

	const onVisibility = () => {
		if (document.visibilityState === 'visible' && videoTaskLive(task)) load();
	};

	onMount(() => {
		load();
		document.addEventListener('visibilitychange', onVisibility);
	});
	onDestroy(() => {
		destroyed = true;
		if (timer) clearTimeout(timer);
		if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility);
	});
</script>

{#if task}
	<div class="my-2">
		<VideoTaskCard {task} where="chat" {stopping} on:stop={stop} />
	</div>
{/if}
