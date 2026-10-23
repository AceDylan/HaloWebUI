<script lang="ts">
	import {
		VIDEO_STYLES,
		VIDEO_STYLE_CUSTOM_MAX,
		VIDEO_APPEARANCE_MAX,
		videoSamplePath,
		type VideoStyleKey,
		type VideoStylePick
	} from '$lib/utils/video-styles';

	export let value: VideoStyleKey = 'auto';
	export let custom = '';
	export let appearance = '';
	export let recipe = '';
	export let disabled = false;
	export let hasReference = false;
	/** what 自动选择 picked from the request (shown while value is 'auto') */
	export let pick: VideoStylePick | null = null;
	export let onChange: (value: VideoStyleKey, custom: string) => void;
	export let onAppearance: (value: string) => void = () => {};
	$: autoKey = value === 'auto' ? pick?.key : undefined;
	$: shown = VIDEO_STYLES.find((s) => s.key === (value === 'auto' ? autoKey : value));
	const modes = [
		{ key: 'auto', label: '自动选择' },
		{ key: 'reference', label: '跟随参考' },
		{ key: 'custom', label: '自定义' }
	] as const;
</script>

<fieldset {disabled} class="min-w-0 space-y-3" data-video-styles>
	<legend class="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">视觉风格</legend>
	<p class="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
		8 种通用 MG 风格：配色、动作技法和验收标准会一起写进制作需求。
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
			>描述配色、画面元素、动作和节奏</label
		>
		<textarea
			id="video-custom-style"
			data-video-custom-style
			value={custom}
			maxlength={VIDEO_STYLE_CUSTOM_MAX}
			rows="3"
			on:input={(event) => onChange('custom', event.currentTarget.value)}
			placeholder="例如：黑白报纸拼贴，人物剪影白边，定格式抽帧，红色斜体大标题"
			class="w-full rounded-xl border border-gray-200 bg-transparent p-3 text-sm dark:border-gray-700"
		/>
	{:else if value === 'reference'}
		<p class="text-xs text-gray-500 dark:text-gray-400">
			{hasReference ? '跟随参考的场景、动作、镜头和外观。' : '请添加参考图片或视频后再增强或制作。'}
			合集请在需求里写明类别或时间段；参考不等于剪入原片。
		</p>
	{:else if value === 'auto'}
		<p class="text-xs text-gray-500 dark:text-gray-400" data-video-auto-pick>
			{#if pick?.key === 'reference'}
				附件里有参考视频：跟随参考的风格制作。
			{:else if shown}
				将用<span class="font-medium text-gray-900 dark:text-gray-100">「{shown.label}」</span
				>{pick?.words.length
					? `：需求提到「${pick.words.join('」「')}」`
					: '：还没看出题材，先用最通用的一种'}。点下面的卡片可改选。
			{/if}
		</p>
	{/if}

	<div class="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-2" data-video-style-grid>
		{#each VIDEO_STYLES as preset (preset.key)}
			<button
				type="button"
				aria-pressed={value === preset.key}
				data-video-style={preset.key}
				data-video-style-auto={autoKey === preset.key ? '' : undefined}
				on:click={() => onChange(preset.key, custom)}
				class="relative min-w-0 rounded-xl border p-1.5 text-left transition {value === preset.key
					? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/30'
					: autoKey === preset.key
						? 'border-dashed border-indigo-400 dark:border-indigo-500'
						: 'border-gray-200/70 hover:border-gray-400 dark:border-gray-700/60 dark:hover:border-gray-500'}"
			>
				<img
					src={videoSamplePath(preset.key, 'jpg')}
					alt=""
					loading="lazy"
					width="640"
					height="360"
					class="aspect-video w-full rounded-lg bg-gray-100 object-cover dark:bg-gray-800"
				/>
				{#if autoKey === preset.key}<span
						class="absolute left-2.5 top-2.5 rounded-full bg-indigo-600 px-1.5 py-0.5 text-[10px] text-white"
						>自动</span
					>{/if}
				<div class="mt-1.5 px-0.5 text-xs font-medium text-gray-900 dark:text-gray-100">
					{preset.label}
				</div>
				<div class="truncate px-0.5 text-[11px] text-gray-500 dark:text-gray-400">{preset.sub}</div>
			</button>
		{/each}
	</div>

	{#if shown}
		<div
			class="space-y-2 rounded-xl border border-gray-200 p-3 dark:border-gray-700"
			data-video-presentation
		>
			<p class="text-xs font-medium text-gray-900 dark:text-gray-100">
				{shown.label} <span class="font-normal text-gray-500">· {shown.en}</span>
			</p>
			{#key shown.key}
				<!-- Only the shown sample can load; no autoplay or simultaneous video decoders. -->
				<video
					controls
					muted
					playsinline
					preload="none"
					poster={videoSamplePath(shown.key, 'jpg')}
					src={videoSamplePath(shown.key, 'mp4')}
					aria-label={`${shown.label}样片`}
					class="w-full rounded-lg bg-black {'vertical' in shown
						? 'mx-auto aspect-[9/16] max-h-80 object-contain'
						: 'aspect-video'}"
					data-video-style-sample
				/>
			{/key}
			<dl class="space-y-1.5 text-xs leading-relaxed text-gray-600 dark:text-gray-300">
				<div>
					<dt class="inline font-medium">适合：</dt>
					<dd class="inline">{shown.fits}</dd>
				</div>
				<div>
					<dt class="inline font-medium">特征：</dt>
					<dd class="inline">{shown.look}</dd>
				</div>
				{#if recipe !== 'footage' && recipe !== 'story'}
					<div>
						<dt class="inline font-medium">技法：</dt>
						<dd class="inline">{shown.motion}</dd>
					</div>
				{/if}
			</dl>
			{#if recipe === 'footage'}<p class="text-xs text-gray-500">
					素材剪辑保留原素材，只把风格用在标题、字幕、贴纸和转场上。
				</p>
			{:else if recipe === 'story'}<p class="text-xs text-amber-700 dark:text-amber-300">
					图文成片用关键画面加运镜；要样片那样的连续动画，请选择「讲解动画」。
				</p>{/if}
			<p class="text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
				样片来自 <a
					class="underline"
					href="https://github.com/Vincentwei1021/mg-styles-15"
					target="_blank"
					rel="noopener noreferrer">mg-styles-15</a
				>（MIT），无声预览，只示范风格质感；成片按你的主题和设置制作，精细度取决于执行者。
			</p>
		</div>
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
		placeholder="例如：暖米色与深绿，清晰黑体；留空沿用所选风格"
		class="w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-xs dark:border-gray-700"
	/>
	<p class="text-[11px] text-gray-500 dark:text-gray-400">
		外观偏好不改变动作技法、制作方式、音乐、时长或配音。
	</p>
</fieldset>
