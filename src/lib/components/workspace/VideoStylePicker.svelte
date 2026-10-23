<script lang="ts">
	import {
		VIDEO_STYLES,
		VIDEO_STYLE_CUSTOM_MAX,
		type VideoStyleKey
	} from '$lib/utils/video-styles';
	import VideoStylePreview from './VideoStylePreview.svelte';
	export let value: VideoStyleKey = 'auto';
	export let custom = '';
	export let disabled = false;
	export let hasReference = false;
	export let onChange: (value: VideoStyleKey, custom: string) => void;
	let expanded = false;
	$: selected = VIDEO_STYLES.find((s) => s.key === value);
	$: visible =
		expanded || VIDEO_STYLES.slice(6).some((s) => s.key === value)
			? VIDEO_STYLES
			: VIDEO_STYLES.slice(0, 6);
	const modes = [
		{ key: 'auto', label: '自动选择' },
		{ key: 'reference', label: '跟随参考' },
		{ key: 'custom', label: '自定义' }
	] as const;
</script>

<fieldset {disabled} class="min-w-0 space-y-3" data-video-styles>
	<legend class="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">视觉风格</legend>
	<div class="flex flex-wrap gap-2">
		{#each modes as mode}
			<button
				type="button"
				aria-pressed={value === mode.key}
				data-video-style={mode.key}
				on:click={() => onChange(mode.key, custom)}
				class="rounded-full border px-3 py-1.5 text-xs transition {value === mode.key
					? 'border-gray-900 bg-gray-900 text-white dark:border-white dark:bg-white dark:text-gray-900'
					: 'border-gray-200 text-gray-600 dark:border-gray-700 dark:text-gray-300'}"
				>{mode.label}</button
			>
		{/each}
	</div>
	{#if value === 'custom'}
		<label class="block text-xs text-gray-600 dark:text-gray-300" for="video-custom-style"
			>描述配色、字体、构图和运动</label
		>
		<textarea
			id="video-custom-style"
			data-video-custom-style
			value={custom}
			maxlength={VIDEO_STYLE_CUSTOM_MAX}
			rows="3"
			on:input={(event) => onChange('custom', event.currentTarget.value)}
			placeholder="例如：暖色绘本，纸张质感，缓慢平移，字幕简洁"
			class="w-full rounded-xl border border-gray-200 bg-transparent p-3 text-sm dark:border-gray-700"
		/>
	{:else if value === 'reference'}
		<p class="text-xs text-gray-500 dark:text-gray-400">
			{hasReference
				? '跟随附件的配色、构图和运动；多个参考时可在需求里指定主参考。'
				: '请添加参考图片或视频后再增强或制作。'}参考不等于剪入原片。
		</p>
	{:else if value === 'auto'}
		<p class="text-xs text-gray-500 dark:text-gray-400">
			优先你的描述和风格参考，再按内容选择统一的视觉。
		</p>
	{/if}
	<div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-2" data-video-style-grid>
		{#each visible as preset (preset.key)}
			<button
				type="button"
				aria-pressed={value === preset.key}
				data-video-style={preset.key}
				on:click={() => onChange(preset.key, custom)}
				class="min-w-0 rounded-xl border p-2 text-left transition {value === preset.key
					? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30'
					: 'border-gray-200/70 hover:border-gray-400 dark:border-gray-700/60 dark:hover:border-gray-500'}"
			>
				<VideoStylePreview {preset} />
				<div class="mt-1.5 text-xs font-medium text-gray-900 dark:text-gray-100">
					{preset.label}
				</div>
				<div class="mt-0.5 text-[11px] text-gray-500 dark:text-gray-400">{preset.sub}</div>
			</button>
		{/each}
	</div>
	{#if visible.length < VIDEO_STYLES.length}
		<button
			type="button"
			on:click={() => (expanded = true)}
			class="text-xs font-medium text-indigo-600 dark:text-indigo-300"
			data-video-more-styles>更多风格 · 10 种</button
		>
	{:else if !VIDEO_STYLES.slice(6).some((s) => s.key === value)}
		<button type="button" on:click={() => (expanded = false)} class="text-xs text-gray-500"
			>收起更多风格</button
		>
	{/if}
	{#if selected}<p class="text-xs leading-relaxed text-gray-600 dark:text-gray-300">
			{selected.hint}
		</p>{/if}
	<p class="text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
		预览为配色与构图示意。风格独立于做法，不改变音乐、时长或配音设置。
	</p>
</fieldset>
