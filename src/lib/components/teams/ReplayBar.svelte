<script lang="ts">
	import { createEventDispatcher, onDestroy } from 'svelte';

	import type { TeamEvent } from '$lib/apis/teams';
	import { formatClock, formatDuration, REPLAY_SPEEDS, replayDelay, replayMarks } from './model';

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
	$: marks = events.length > 1 ? replayMarks(events) : [];

	const MARK: Record<string, string> = {
		fail: 'bg-red-500',
		handoff: 'bg-gray-500 dark:bg-gray-400',
		team: 'bg-indigo-500',
		user: 'bg-violet-500',
		message: 'bg-sky-500'
	};

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
	class="replay tm-card-quiet flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2 text-xs"
	data-replay-bar
	data-live={live ? 'true' : 'false'}
>
	{#if live}
		<span
			class="inline-flex items-center gap-1.5 font-semibold tracking-wide text-[hsl(var(--tm-accent))]"
		>
			<span
				class="tm-pulse-dot size-2 rounded-full bg-[hsl(var(--tm-accent))] text-[hsl(var(--tm-accent))]"
				aria-hidden="true"
			/>实时
		</span>
		<button
			type="button"
			class="tm-btn-ghost"
			disabled={events.length < 2}
			on:click={play}
			aria-label="从头回放协作过程（只回看记录，不影响执行）"
			><svg class="size-3" viewBox="0 0 12 12" aria-hidden="true"
				><path d="M3 1.8v8.4L10 6 3 1.8Z" fill="currentColor" /></svg
			>回放</button
		>
	{:else}
		<span class="font-semibold text-sky-700 dark:text-sky-300">回放中</span>
		{#if playing}
			<button
				type="button"
				class="tm-btn-ghost"
				on:click={pause}
				aria-label="暂停回放（不影响正在执行的成员）"
				><svg class="size-3" viewBox="0 0 12 12" aria-hidden="true"
					><path d="M3 2h2v8H3zM7 2h2v8H7z" fill="currentColor" /></svg
				>暂停回放</button
			>
		{:else}
			<button type="button" class="tm-btn-ghost" on:click={play} aria-label="继续回放"
				><svg class="size-3" viewBox="0 0 12 12" aria-hidden="true"
					><path d="M3 1.8v8.4L10 6 3 1.8Z" fill="currentColor" /></svg
				>播放</button
			>
		{/if}
		<div class="tm-segment !p-[2px]" role="radiogroup" aria-label="回放速度">
			{#each REPLAY_SPEEDS as option}
				<button
					type="button"
					role="radio"
					aria-checked={speed === option}
					class="!px-1.5 !py-0.5 font-mono"
					on:click={() => setSpeed(option)}>{option}×</button
				>
			{/each}
		</div>
		<button
			type="button"
			class="tm-btn-ghost !text-[hsl(var(--tm-accent))]"
			on:click={goLive}>回到实时</button
		>
	{/if}
	<label class="flex min-w-[160px] flex-1 items-center gap-3">
		<span class="sr-only">回放时间轴</span>
		<span class="relative flex flex-1 items-center">
			<input
				type="range"
				min="0"
				max={last}
				value={cursor}
				disabled={events.length < 2}
				on:input={onSlide}
				class="scrub w-full"
				style="--p:{last ? (cursor / last) * 100 : 100}%"
				aria-valuetext="{formatClock(at)}，第 {cursor + 1} / {events.length} 条记录"
			/>
			{#if marks.length}
				<!-- Landmarks: red failure, green handoff, indigo team, violet your note, blue message. -->
				<span
					class="pointer-events-none absolute inset-x-[7px] top-full mt-[6px] h-[4px]"
					aria-hidden="true"
					data-replay-marks
				>
					{#each marks as mark (mark.index)}
						<span
							class="absolute top-0 size-[4px] -translate-x-1/2 rounded-full transition-opacity {MARK[
								mark.kind
							]} {!live && mark.index > cursor ? 'opacity-30' : 'opacity-80'}"
							style="left:{(mark.index / last) * 100}%"
						/>
					{/each}
				</span>
			{/if}
		</span>
		<span class="tm-num whitespace-nowrap text-gray-500 dark:text-gray-400">
			{formatClock(at)}<span class="hidden opacity-70 sm:inline">
				· {formatDuration(at - start)}/{formatDuration(end - start)}</span
			>
		</span>
	</label>
	{#if !live && compressed && playing}
		<span class="text-gray-400">长时间无动静的间隔已压缩</span>
	{/if}
</div>

<style>
	.scrub {
		-webkit-appearance: none;
		appearance: none;
		height: 4px;
		border-radius: 9999px;
		background: linear-gradient(
			90deg,
			hsl(var(--tm-accent)) 0%,
			hsl(var(--tm-accent-2)) var(--p),
			hsl(var(--tm-line-strong)) var(--p)
		);
		outline: none;
	}
	[data-live='true'] .scrub {
		background: linear-gradient(90deg, hsl(var(--tm-accent) / 0.55), hsl(var(--tm-accent)) 60%, hsl(var(--tm-violet)));
	}
	.scrub::-webkit-slider-thumb {
		-webkit-appearance: none;
		width: 14px;
		height: 14px;
		border-radius: 9999px;
		background: hsl(var(--tm-surface));
		border: 2px solid hsl(var(--tm-accent));
		box-shadow: 0 0 0 4px hsl(var(--tm-accent) / 0.15);
		cursor: pointer;
	}
	.scrub::-moz-range-thumb {
		width: 12px;
		height: 12px;
		border-radius: 9999px;
		background: hsl(var(--tm-surface));
		border: 2px solid hsl(var(--tm-accent));
		cursor: pointer;
	}
	[data-live='true'] .scrub::-webkit-slider-thumb {
		border-color: hsl(var(--tm-violet));
		box-shadow: 0 0 0 4px hsl(var(--tm-violet) / 0.15);
	}
	.scrub:disabled {
		opacity: 0.5;
	}
</style>
