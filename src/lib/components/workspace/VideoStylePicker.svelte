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
	export let title = '动画画风';
	export let mvMode = false;
	/** what 自动选择 picked from the request (shown while value is 'auto') */
	export let pick: VideoStylePick | null = null;
	export let onChange: (value: VideoStyleKey, custom: string) => void;
	export let onAppearance: (value: string) => void = () => {};

	type Category = 'all' | 'anime' | 'mg';
	let category: Category = 'all';

	$: autoKey = value === 'auto' ? pick?.key : undefined;
	$: shown = VIDEO_STYLES.find((s) => s.key === (value === 'auto' ? autoKey : value));
	$: animeCount = VIDEO_STYLES.filter((s) => 'douyin' in s && s.douyin).length;
	$: mgCount = VIDEO_STYLES.filter((s) => s.source === 'mg-styles-15').length;
	$: visibleStyles =
		category === 'anime'
			? VIDEO_STYLES.filter((s) => 'douyin' in s && s.douyin)
			: category === 'mg'
				? VIDEO_STYLES.filter((s) => s.source === 'mg-styles-15')
				: VIDEO_STYLES;

	const modes = [
		{ key: 'auto', label: '自动选择' },
		{ key: 'reference', label: '跟随参考' },
		{ key: 'custom', label: '自定义' }
	] as const;
</script>

<fieldset {disabled} class="min-w-0 space-y-3" data-video-styles>
	<div class="flex flex-wrap items-center justify-between gap-2">
		<legend class="text-sm font-semibold text-gray-900 dark:text-gray-100">{title}</legend>
		<div class="inline-flex rounded-full border border-gray-200/80 bg-gray-50/80 p-0.5 text-[11px] dark:border-gray-700/70 dark:bg-gray-900/60" role="group" aria-label="风格分类" data-video-style-filter>
			<button
				type="button"
				class="rounded-full px-2.5 py-0.5 font-medium transition {category === 'all'
					? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
					: 'text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white'}"
				on:click={() => (category = 'all')}
				data-video-style-cat="all"
			>全部 {VIDEO_STYLES.length}</button>
			<button
				type="button"
				class="rounded-full px-2.5 py-0.5 font-medium transition {category === 'anime'
					? 'bg-indigo-600 text-white dark:bg-indigo-500 dark:text-white'
					: 'text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white'}"
				on:click={() => (category = 'anime')}
				data-video-style-cat="anime"
			>动画精选 {animeCount}</button>
			<button
				type="button"
				class="rounded-full px-2.5 py-0.5 font-medium transition {category === 'mg'
					? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
					: 'text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white'}"
				on:click={() => (category = 'mg')}
				data-video-style-cat="mg"
			>通用 MG {mgCount}</button>
		</div>
	</div>

	<div class="flex flex-wrap items-center gap-1.5">
		{#each modes as mode}
			<button
				type="button"
				aria-pressed={value === mode.key}
				data-video-style={mode.key}
				on:click={() => onChange(mode.key, custom)}
				class="rounded-full border px-3 py-1 text-xs font-medium transition {value === mode.key
					? 'border-gray-900 bg-gray-900 text-white dark:border-white dark:bg-white dark:text-gray-900'
					: 'border-gray-200/80 text-gray-600 hover:border-gray-300 dark:border-gray-700 dark:text-gray-300 dark:hover:border-gray-500'}"
				>{mode.label}</button
			>
		{/each}
		<span class="text-[11px] text-gray-500 dark:text-gray-400">
			{mvMode
				? '决定 MV 卡通/动画画面的美术风格（绝不做纯文字）'
				: '每幕做贴合字幕的动画场景，不做纯文字黑屏'}
		</span>
	</div>

	{#if value === 'custom'}
		<div class="space-y-1.5">
			<label class="block text-xs text-gray-600 dark:text-gray-300" for="video-custom-style"
				>描述想要的动画画风、角色造型、场景光影与节奏</label
			>
			<textarea
				id="video-custom-style"
				data-video-custom-style
				value={custom}
				maxlength={VIDEO_STYLE_CUSTOM_MAX}
				rows="3"
				on:input={(event) => onChange('custom', event.currentTarget.value)}
				placeholder="例如：吉卜力暖色手绘动画，主角背着书包走过夏日海边铁道，镜头温柔推近，风吹衣角与海浪微动"
				class="w-full rounded-xl border border-gray-200 bg-transparent p-2.5 text-sm dark:border-gray-700"
			/>
		</div>
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
					: '：按当前模式默认推荐'}。点下方卡片可改选。
			{/if}
		</p>
	{/if}

	<div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-3" data-video-style-grid>
		{#each visibleStyles as preset (preset.key)}
			{@const isAnime = 'douyin' in preset && preset.douyin}
			{@const isVertical = 'vertical' in preset && preset.vertical}
			<button
				type="button"
				aria-pressed={value === preset.key}
				data-video-style={preset.key}
				data-video-style-auto={autoKey === preset.key ? '' : undefined}
				on:click={() => onChange(preset.key, custom)}
				class="relative min-w-0 rounded-xl border p-1.5 text-left transition {value === preset.key
					? 'border-indigo-500 bg-indigo-50/90 ring-1 ring-indigo-500/30 dark:bg-indigo-950/35'
					: autoKey === preset.key
						? 'border-dashed border-indigo-400 bg-indigo-50/30 dark:border-indigo-500 dark:bg-indigo-950/15'
						: 'border-gray-200/70 bg-white/50 hover:border-gray-400 dark:border-gray-700/60 dark:bg-white/[0.02] dark:hover:border-gray-500'}"
			>
				<div class="relative overflow-hidden rounded-lg bg-gray-900">
					<img
						src={videoSamplePath(preset.key, 'jpg')}
						alt=""
						loading="lazy"
						width="640"
						height="360"
						class="aspect-video w-full object-cover"
					/>
					{#if autoKey === preset.key}
						<span class="absolute left-1.5 top-1.5 rounded-full bg-indigo-600/95 px-1.5 py-0.5 text-[10px] font-medium text-white shadow-sm">自动</span>
					{:else if isAnime}
						<span class="absolute left-1.5 top-1.5 rounded-full bg-violet-600/90 px-1.5 py-0.5 text-[10px] font-medium text-white shadow-sm">动画</span>
					{/if}
					{#if isVertical}
						<span class="absolute right-1.5 top-1.5 rounded bg-black/65 px-1 py-0.5 text-[9.5px] font-medium text-white/95 backdrop-blur-sm">9:16</span>
					{/if}
				</div>
				<div class="mt-1.5 truncate px-0.5 text-xs font-semibold text-gray-900 dark:text-gray-100">
					{preset.label}
				</div>
				<div class="truncate px-0.5 text-[10.5px] text-gray-500 dark:text-gray-400">{preset.sub}</div>
			</button>
		{/each}
	</div>

	{#if shown}
		{@const isVertical = 'vertical' in shown && shown.vertical}
		<div
			class="rounded-xl border border-gray-200/80 bg-gray-50/60 p-3 dark:border-gray-700/70 dark:bg-gray-900/40"
			data-video-presentation
		>
			<div class="flex flex-col gap-3 sm:flex-row sm:items-start">
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
						class="shrink-0 rounded-lg bg-black {isVertical
							? 'mx-auto aspect-[9/16] w-32 sm:mx-0 sm:w-28 object-contain'
							: 'w-full aspect-video sm:w-44'}"
						data-video-style-sample
					/>
				{/key}
				<div class="min-w-0 flex-1 space-y-1.5">
					<div class="flex flex-wrap items-center gap-1.5">
						<span class="text-xs font-semibold text-gray-900 dark:text-gray-100">{shown.label}</span>
						<span class="text-[11px] text-gray-500 dark:text-gray-400">· {shown.en}</span>
						{#if 'douyin' in shown && shown.douyin}
							<span class="rounded-full bg-indigo-500/15 px-1.5 py-0.5 text-[10px] font-medium text-indigo-600 dark:text-indigo-300">动画推荐</span>
						{/if}
					</div>
					<dl class="space-y-1 text-xs leading-relaxed text-gray-600 dark:text-gray-300">
						<div>
							<dt class="inline font-medium text-gray-800 dark:text-gray-200">适合：</dt>
							<dd class="inline">{shown.fits}</dd>
						</div>
						<div>
							<dt class="inline font-medium text-gray-800 dark:text-gray-200">特征：</dt>
							<dd class="inline">{shown.look}</dd>
						</div>
						{#if recipe !== 'footage' && recipe !== 'story'}
							<div>
								<dt class="inline font-medium text-gray-800 dark:text-gray-200">技法：</dt>
								<dd class="inline">{shown.motion}</dd>
							</div>
						{/if}
					</dl>
					{#if !mvMode && recipe === 'footage'}
						<p class="text-[11px] text-gray-500">
							素材精剪保留原素材主体，只把该风格用在卡通贴纸、动态转场与包装上。
						</p>
					{:else if !mvMode && recipe === 'story'}
						<p class="text-[11px] text-amber-700 dark:text-amber-300">
							绘本动画用统一画风分镜叠动态光影、天气与视差；要角色关节连续动画可选「剧情动画」。
						</p>
					{/if}
					<p class="text-[10.5px] leading-relaxed text-gray-500 dark:text-gray-400">
						{#if shown.source === 'mg-styles-15'}
							样片来自 <a
								class="underline"
								href="https://github.com/Vincentwei1021/mg-styles-15"
								target="_blank"
								rel="noopener noreferrer">mg-styles-15</a
							>（MIT），无声预览，只示范风格质感；成片按你的主题和设置制作。
						{:else}
							原创动画风动态样片，无声预览，示范角色与场景氛围；成片按你的字幕或歌词量身制作。
						{/if}
					</p>
				</div>
			</div>
		</div>
	{/if}

	<div class="space-y-1">
		<label class="block text-xs text-gray-600 dark:text-gray-300" for="video-appearance"
			>配色与画面偏好（可选）</label
		>
		<input
			id="video-appearance"
			data-video-appearance
			value={appearance}
			maxlength={VIDEO_APPEARANCE_MAX}
			on:input={(event) => onAppearance(event.currentTarget.value)}
			placeholder="例如：夏日薄荷蓝与暖橙光影，主角戴眼镜；留空沿用所选画风"
			class="w-full rounded-lg border border-gray-200/80 bg-transparent px-3 py-1.5 text-xs dark:border-gray-700"
		/>
		<p class="text-[10.5px] text-gray-500 dark:text-gray-400">
			外观偏好不改变动画技法、做法、音乐、时长或配音。
		</p>
	</div>
</fieldset>
