<script lang="ts">
	import {
		VIDEO_STYLES,
		LEGACY_VIDEO_STYLES,
		ALL_VIDEO_STYLES,
		VIDEO_STYLE_CUSTOM_MAX,
		VIDEO_APPEARANCE_MAX,
		type VideoStyleKey
	} from '$lib/utils/video-styles';
	import { videoSamplePath } from '$lib/utils/video-presentations';
	import VideoStylePreview from './VideoStylePreview.svelte';

	export let value: VideoStyleKey = 'auto';
	export let custom = '';
	export let appearance = '';
	export let recipe = '';
	export let disabled = false;
	export let hasReference = false;
	export let onChange: (value: VideoStyleKey, custom: string) => void;
	export let onAppearance: (value: string) => void = () => {};
	let showLegacy = false;
	$: selected = ALL_VIDEO_STYLES.find((s) => s.key === value);
	$: presentation = VIDEO_STYLES.find((s) => s.key === value);
	$: legacySelected = LEGACY_VIDEO_STYLES.some((s) => s.key === value);
	const modes = [
		{ key: 'auto', label: '自动选择' },
		{ key: 'reference', label: '跟随参考' },
		{ key: 'custom', label: '自定义' }
	] as const;
</script>

<fieldset {disabled} class="min-w-0 space-y-3" data-video-styles>
	<legend class="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">讲解形式</legend>
	<p class="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
		选择怎样演示知识：角色动作、过程推演、镜头和节奏会一起带入制作需求。
	</p>
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
			>描述场景、主体动作、镜头和节奏</label
		>
		<textarea
			id="video-custom-style"
			data-video-custom-style
			value={custom}
			maxlength={VIDEO_STYLE_CUSTOM_MAX}
			rows="3"
			on:input={(event) => onChange('custom', event.currentTarget.value)}
			placeholder="例如：跟随一个快递包裹经过各站，处理后再移动，最后拉远展示全程"
			class="w-full rounded-xl border border-gray-200 bg-transparent p-3 text-sm dark:border-gray-700"
		/>
	{:else if value === 'reference'}
		<p class="text-xs text-gray-500 dark:text-gray-400">
			{hasReference ? '跟随参考的场景、动作、镜头和外观。' : '请添加参考图片或视频后再增强或制作。'}
			合集请在需求里写明类别或时间段；参考不等于剪入原片。
		</p>
	{:else if value === 'auto'}
		<p class="text-xs text-gray-500 dark:text-gray-400">
			优先你的描述和参考，再按主题选择适合的讲解形式。
		</p>
	{/if}

	<div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-2" data-video-style-grid>
		{#each VIDEO_STYLES as preset (preset.key)}
			<button
				type="button"
				aria-pressed={value === preset.key}
				data-video-style={preset.key}
				on:click={() => onChange(preset.key, custom)}
				class="min-w-0 rounded-xl border p-2 text-left transition {value === preset.key
					? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30'
					: 'border-gray-200/70 hover:border-gray-400 dark:border-gray-700/60 dark:hover:border-gray-500'}"
			>
				<img
					src={videoSamplePath(preset.key, 'jpg')}
					alt=""
					loading="lazy"
					width="640"
					height="360"
					class="aspect-video w-full rounded-lg object-cover"
				/>
				<div class="mt-1.5 text-xs font-medium text-gray-900 dark:text-gray-100">
					{preset.label}
				</div>
				<div class="mt-0.5 text-[11px] text-gray-500 dark:text-gray-400">{preset.sub}</div>
			</button>
		{/each}
	</div>

	{#if presentation}
		<div
			class="space-y-2 rounded-xl border border-gray-200 p-3 dark:border-gray-700"
			data-video-presentation
		>
			<p class="text-xs font-medium text-gray-900 dark:text-gray-100">
				{presentation.label} · 原创演示样片
			</p>
			{#key presentation.key}
				<!-- Only the selected sample can load; no autoplay or simultaneous video decoders. -->
				<video
					controls
					muted
					playsinline
					preload="none"
					poster={videoSamplePath(presentation.key, 'jpg')}
					src={videoSamplePath(presentation.key, 'mp4')}
					aria-label={`${presentation.label}演示样片`}
					class="aspect-video w-full rounded-lg"
					data-video-style-sample
				/>
			{/key}
			<p class="text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
				{presentation.example}。8 秒无声样片展示动作与镜头，成片会按你的主题与设置制作。
			</p>
			<dl class="space-y-1.5 text-xs leading-relaxed text-gray-600 dark:text-gray-300">
				<div>
					<dt class="inline font-medium">分镜：</dt>
					<dd class="inline">{presentation.scenes}</dd>
				</div>
				<div>
					<dt class="inline font-medium">动作：</dt>
					<dd class="inline">{presentation.motion}</dd>
				</div>
				<div>
					<dt class="inline font-medium">镜头：</dt>
					<dd class="inline">{presentation.camera}</dd>
				</div>
				<div>
					<dt class="inline font-medium">节奏：</dt>
					<dd class="inline">{presentation.rhythm}</dd>
				</div>
			</dl>
			{#if value === 'exploded'}<p class="text-xs text-amber-700 dark:text-amber-300">
					样片使用简化三维模型。制作前需验证所需模型与渲染能力，无法完成时会说明限制。
				</p>{/if}
			{#if recipe === 'footage'}<p class="text-xs text-gray-500">
					素材剪辑保留原素材，只借用叙事顺序、排版与转场。
				</p>
			{:else if recipe === 'story'}<p class="text-xs text-amber-700 dark:text-amber-300">
					图文成片使用关键画面与运镜；要呈现样片中的连续动作，请选择「讲解动画」。
				</p>{/if}
		</div>
	{/if}

	<button
		type="button"
		on:click={() => (showLegacy = !showLegacy)}
		aria-expanded={showLegacy || legacySelected}
		class="text-xs text-gray-600 dark:text-gray-400"
		data-video-more-styles
	>
		{showLegacy || legacySelected ? '其他视觉风格（旧预设）' : '展开其他视觉风格 · 10 种'}
	</button>
	{#if showLegacy || legacySelected}
		<p class="text-[11px] text-gray-500">保留原来的外观风格；这些选项不包含专门的知识演示结构。</p>
		<div class="grid grid-cols-2 gap-2" data-video-legacy-styles>
			{#each LEGACY_VIDEO_STYLES as preset (preset.key)}
				<button
					type="button"
					aria-pressed={value === preset.key}
					data-video-style={preset.key}
					on:click={() => onChange(preset.key, custom)}
					class="min-w-0 rounded-xl border p-2 text-left {value === preset.key
						? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30'
						: 'border-gray-200 dark:border-gray-700'}"
				>
					<VideoStylePreview {preset} />
					<div class="mt-1 text-xs">{preset.label}</div>
				</button>
			{/each}
		</div>
		{#if legacySelected && selected}<p class="text-xs leading-relaxed text-gray-500">
				{selected.hint}
			</p>{/if}
	{/if}
	<label class="block text-xs text-gray-600 dark:text-gray-300" for="video-appearance"
		>配色与字体偏好（可选）</label
	>
	<input
		id="video-appearance"
		data-video-appearance
		value={appearance}
		maxlength={VIDEO_APPEARANCE_MAX}
		on:input={(event) => onAppearance(event.currentTarget.value)}
		placeholder="例如：暖米色与深绿，清晰黑体；留空沿用所选形式"
		class="w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-xs dark:border-gray-700"
	/>
	<p class="text-[11px] text-gray-500 dark:text-gray-400">
		外观偏好不改变讲解结构、制作方式、音乐、时长或配音。
	</p>
</fieldset>
