<script lang="ts">
	import { createEventDispatcher, onDestroy } from 'svelte';

	import type { TeamEvent } from '$lib/apis/teams';
	import { formatClock, formatDuration, REPLAY_SPEEDS, replayDelay } from './model';

	/**
	 * Replay = moving a cursor over the recorded events. It only changes what is shown: it never
	 * pauses members, never starts, retries or messages anything. `index` null = live.
	 */
	export let events: TeamEvent[] = [];
	export let index: number | null = null;

	const dispatch = createEventDispatcher<{ seek: number | null }>();
	let playing = false;
	let speed: (typeof REPLAY_SPEEDS)[number] = 1;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let compressed = false;

	$: last = Math.max(0, events.length - 1);
	$: live = index === null;
	$: cursor = live ? last : Math.min(index ?? 0, last);
	$: start = events[0]?.ts ?? 0;
	$: end = events[last]?.ts ?? start;
	$: at = events[cursor]?.ts ?? start;

	const stopTimer = () => {
		if (timer) clearTimeout(timer);
		timer = null;
	};

	// The playback position lives here: the parent's `index` prop only catches up after the
	// next flush, so reading it right after dispatching would replay the same step.
	let pos = 0;

	const step = () => {
		stopTimer();
		if (!playing) return;
		if (pos >= last) {
			playing = false;
			return;
		}
		const delay = replayDelay(events, pos, speed);
		compressed = delay.compressed;
		timer = setTimeout(() => {
			pos = Math.min(last, pos + 1);
			dispatch('seek', pos);
			step();
		}, delay.ms);
	};

	const play = () => {
		if (!events.length) return;
		pos = live || (index ?? 0) >= last ? 0 : (index ?? 0);
		dispatch('seek', pos);
		playing = true;
		step();
	};
	const pause = () => {
		playing = false;
		stopTimer();
	};
	const goLive = () => {
		pause();
		dispatch('seek', null);
	};
	const onSlide = (event: Event) => {
		pause();
		pos = Number((event.target as HTMLInputElement).value);
		dispatch('seek', pos);
	};
	const setSpeed = (value: (typeof REPLAY_SPEEDS)[number]) => {
		speed = value;
		if (playing) step();
	};

	$: if (live && playing) pause();
	onDestroy(stopTimer);
</script>

<div
	class="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-2xl border border-gray-100 bg-white/80 px-3 py-2 text-xs dark:border-gray-850 dark:bg-gray-900/80"
	data-replay-bar
>
	{#if live}
		<span class="inline-flex items-center gap-1.5 font-semibold text-emerald-700 dark:text-emerald-300">
			<span class="size-2 rounded-full bg-emerald-500 animate-pulse" aria-hidden="true" />实时
		</span>
		<button
			type="button"
			class="rounded-full bg-gray-100 px-3 py-1 font-medium text-gray-700 hover:bg-gray-200 disabled:opacity-40 dark:bg-gray-850 dark:text-gray-200"
			disabled={events.length < 2}
			on:click={play}
			aria-label="从头回放协作过程（只回看记录，不影响执行）">▶ 回放</button
		>
	{:else}
		<span class="font-semibold text-sky-700 dark:text-sky-300">回放中</span>
		{#if playing}
			<button
				type="button"
				class="rounded-full bg-gray-100 px-3 py-1 font-medium hover:bg-gray-200 dark:bg-gray-850 dark:text-gray-200"
				on:click={pause}
				aria-label="暂停回放（不影响正在执行的成员）">⏸ 暂停回放</button
			>
		{:else}
			<button
				type="button"
				class="rounded-full bg-gray-100 px-3 py-1 font-medium hover:bg-gray-200 dark:bg-gray-850 dark:text-gray-200"
				on:click={play}
				aria-label="继续回放">▶ 播放</button
			>
		{/if}
		<div class="flex items-center gap-0.5" role="radiogroup" aria-label="回放速度">
			{#each REPLAY_SPEEDS as option}
				<button
					type="button"
					role="radio"
					aria-checked={speed === option}
					class="rounded-md px-1.5 py-0.5 font-mono {speed === option
						? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900'
						: 'text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-850'}"
					on:click={() => setSpeed(option)}>{option}×</button
				>
			{/each}
		</div>
		<button
			type="button"
			class="rounded-full px-3 py-1 font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 dark:bg-emerald-950/40 dark:text-emerald-300"
			on:click={goLive}>回到实时</button
		>
	{/if}
	<label class="flex min-w-[180px] flex-1 items-center gap-2">
		<span class="sr-only">回放时间轴</span>
		<input
			type="range"
			min="0"
			max={last}
			value={cursor}
			disabled={events.length < 2}
			on:input={onSlide}
			class="flex-1 accent-sky-500"
			aria-valuetext="{formatClock(at)}，第 {cursor + 1} / {events.length} 条记录"
		/>
		<span class="font-mono tabular-nums text-gray-500 dark:text-gray-400 whitespace-nowrap">
			{formatClock(at)} · {formatDuration(at - start)}/{formatDuration(end - start)}
		</span>
	</label>
	{#if !live && compressed && playing}
		<span class="text-gray-400">长时间无动静的间隔已压缩</span>
	{/if}
</div>
