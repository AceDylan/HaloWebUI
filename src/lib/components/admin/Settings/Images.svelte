<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, getContext, onMount, tick } from 'svelte';
	import { config as backendConfig, user } from '$lib/stores';
	import { getBackendConfig } from '$lib/apis';
	import { getConfig, updateConfig, getImageGenerationConfig, updateImageGenerationConfig } from '$lib/apis/images';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import InlineDirtyActions from './InlineDirtyActions.svelte';
	import { cloneSettingsSnapshot, isSettingsSnapshotEqual } from '$lib/utils/settings-dirty';

	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	let loading = false;
	let config = null;
	let imageGenerationConfig = {
		IMAGE_MODEL_FILTER_REGEX: '',
		IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT: ''
	};
	let initialSnapshot = null;

	// 能力覆盖表以 JSON 文本形式编辑，便于复用现有"字符串快照"脏检测。
	const stringifyOverrides = (value) => {
		if (
			!value ||
			typeof value !== 'object' ||
			Array.isArray(value) ||
			Object.keys(value).length === 0
		)
			return '';
		try {
			return JSON.stringify(value, null, 2);
		} catch {
			return '';
		}
	};

	// 解析编辑框文本：空 → {}；合法对象 → 该对象；非法 → null（用于报错/拦截保存）。
	const parseCapabilityOverrides = (text) => {
		const trimmed = `${text ?? ''}`.trim();
		if (!trimmed) return {};
		try {
			const parsed = JSON.parse(trimmed);
			if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
			return parsed;
		} catch {
			return null;
		}
	};

	$: capabilityOverridesInvalid =
		!!`${imageGenerationConfig.IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT ?? ''}`.trim() &&
		parseCapabilityOverrides(imageGenerationConfig.IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT) === null;

	$: capabilityOverridesEmpty =
		!`${imageGenerationConfig.IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT ?? ''}`.trim();

	// 一键插入的可编辑模板：用户即使完全忘记写法，点一下照着改即可。
	const capabilityOverrideExample = `{
  "gemini:gemini-4-flash-image": {
    "supports_image_size": true
  }
}`;

	const insertCapabilityOverrideExample = () => {
		imageGenerationConfig = {
			...imageGenerationConfig,
			IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT: capabilityOverrideExample
		};
	};

	const getErrorText = (error) => {
		if (typeof error === 'string') return error;
		if (error instanceof Error) return error.message;
		if (Array.isArray(error)) return error.map(getErrorText).filter(Boolean).join(', ');
		if (error && typeof error === 'object') {
			const value = error as Record<string, unknown>;
			const message =
				typeof value.msg === 'string'
					? value.msg
					: typeof value.message === 'string'
						? value.message
						: '';
			const loc = Array.isArray(value.loc)
				? value.loc
						.filter((part) => part !== 'body')
						.map((part) => `${part}`)
						.join('.')
				: '';
			if (message) return loc ? `${loc}: ${message}` : message;
			if ('detail' in value) return getErrorText(value.detail);

			try {
				return JSON.stringify(value);
			} catch {
				return '';
			}
		}
		return `${error ?? ''}`;
	};

	const formatImageSettingsError = (error) => {
		const message = getErrorText(error).trim();
		return message ? $i18n.t(message) : $i18n.t('Connection failed');
	};

	const normalizeImageSettingsSnapshot = (
		sourceConfig = config,
		sourceImageConfig = imageGenerationConfig
	) => ({
		enabled: sourceConfig?.enabled === true,
		shared_key_enabled: sourceConfig?.shared_key_enabled === true,
		IMAGE_MODEL_FILTER_REGEX: `${sourceImageConfig?.IMAGE_MODEL_FILTER_REGEX ?? ''}`,
		IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT: `${
			sourceImageConfig?.IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT ?? ''
		}`
	});

	$: snapshot = normalizeImageSettingsSnapshot(config, imageGenerationConfig);
	$: isDirty = !!(initialSnapshot && config && !isSettingsSnapshotEqual(snapshot, initialSnapshot));

	const syncBaseline = (sourceConfig = config, sourceImageConfig = imageGenerationConfig) => {
		initialSnapshot = cloneSettingsSnapshot(
			normalizeImageSettingsSnapshot(sourceConfig, sourceImageConfig)
		);
	};

	const resetChanges = () => {
		if (!initialSnapshot) return;
		config = {
			...config,
			enabled: initialSnapshot.enabled,
			shared_key_enabled: initialSnapshot.shared_key_enabled
		};
		imageGenerationConfig = {
			...imageGenerationConfig,
			IMAGE_MODEL_FILTER_REGEX: initialSnapshot.IMAGE_MODEL_FILTER_REGEX,
			IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT:
				initialSnapshot.IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT
		};
	};

	const serializeConfigForSave = (draftConfig) => ({
		enabled: draftConfig?.enabled === true,
		shared_key_enabled: draftConfig?.shared_key_enabled === true
	});

	const serializeImageGenerationConfigForSave = (draftImageConfig) => ({
		IMAGE_MODEL_FILTER_REGEX: `${draftImageConfig?.IMAGE_MODEL_FILTER_REGEX ?? ''}`
	});

	const loadImageSettings = async () => {
		const [loadedConfig, loadedImageConfig] = await Promise.all([
			getConfig(localStorage.token).catch((error) => {
				toast.error(formatImageSettingsError(error));
				return null;
			}),
			getImageGenerationConfig(localStorage.token).catch((error) => {
				toast.error(formatImageSettingsError(error));
				return null;
			})
		]);

		if (loadedConfig) config = normalizeImageSettingsSnapshot(loadedConfig, imageGenerationConfig);
		if (loadedImageConfig) {
			imageGenerationConfig = {
				...imageGenerationConfig,
				IMAGE_MODEL_FILTER_REGEX: `${loadedImageConfig?.IMAGE_MODEL_FILTER_REGEX ?? ''}`,
				IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT: stringifyOverrides(
					loadedImageConfig?.IMAGES_MODEL_CAPABILITY_OVERRIDES
				)
			};
		}
	};

	const saveHandler = async () => {
		const parsedOverrides = parseCapabilityOverrides(
			imageGenerationConfig.IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT
		);
		if (parsedOverrides === null) {
			toast.error(
				$i18n.t('Model capability overrides must be valid JSON (an object of objects).')
			);
			return;
		}

		loading = true;

		const updatedConfig = await updateConfig(localStorage.token, serializeConfigForSave(config)).catch((error) => {
			toast.error(formatImageSettingsError(error));
			return null;
		});

		const updatedImageGenerationConfig = await updateImageGenerationConfig(localStorage.token, {
			...serializeImageGenerationConfigForSave(imageGenerationConfig),
			IMAGES_MODEL_CAPABILITY_OVERRIDES: parsedOverrides
		}).catch((error) => {
			toast.error(formatImageSettingsError(error));
			return null;
		});

		if (!updatedConfig || !updatedImageGenerationConfig) {
			loading = false;
			return;
		}

		config = normalizeImageSettingsSnapshot(updatedConfig, imageGenerationConfig);
		imageGenerationConfig = {
			...imageGenerationConfig,
			IMAGE_MODEL_FILTER_REGEX: `${updatedImageGenerationConfig?.IMAGE_MODEL_FILTER_REGEX ?? ''}`,
			IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT: stringifyOverrides(
				updatedImageGenerationConfig?.IMAGES_MODEL_CAPABILITY_OVERRIDES
			)
		};
		backendConfig.set(await getBackendConfig());
		await tick();
		syncBaseline(config, imageGenerationConfig);
		dispatch('save');
		loading = false;
	};

	onMount(async () => {
		if ($user?.role !== 'admin') return;

		await loadImageSettings();
		await tick();
		syncBaseline();
	});
</script>

<form class="flex h-full min-h-0 flex-col text-sm" on:submit|preventDefault={saveHandler}>
	<div class="h-full space-y-6 overflow-y-auto scrollbar-hidden">
		{#if config}
			<div class="max-w-6xl mx-auto space-y-6">
				<section class="glass-section p-5 space-y-5 {isDirty ? 'glass-section-dirty' : ''}">
					<div class="flex items-center justify-between gap-3">
						<div class="text-base font-semibold text-gray-800 dark:text-gray-100">
							{$i18n.t('Image Settings')}
						</div>
						<InlineDirtyActions dirty={isDirty} saving={loading} on:reset={resetChanges} />
					</div>

					<div class="space-y-3">
						<div class="flex items-center justify-between glass-item px-4 py-3">
							<div>
								<div class="text-sm font-medium">{$i18n.t('Image Generation')}</div>
								<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
									{$i18n.t('Users can generate images by selecting an image model in chat or in the image workspace.')}
								</div>
							</div>
							<Switch bind:state={config.enabled} />
						</div>

						<div class="flex items-center justify-between glass-item px-4 py-3">
							<div>
								<div class="text-sm font-medium">{$i18n.t('Allow users to use the workspace shared key')}</div>
								<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
									{$i18n.t('When enabled, users without personal connections can fall back to the workspace shared key.')}
								</div>
							</div>
							<Switch bind:state={config.shared_key_enabled} />
						</div>
					</div>
				</section>

				<section class="glass-section p-5 space-y-5 {isDirty ? 'glass-section-dirty' : ''}">
					<div class="text-base font-semibold text-gray-800 dark:text-gray-100">
						{$i18n.t('Model Filter Regex')}
					</div>
					<div class="glass-item p-4">
						<Tooltip content={$i18n.t('Regex pattern to filter image models (leave empty to show all)')} placement="top-start">
							<input
								class="w-full py-2 px-3 text-sm dark:text-gray-300 glass-input"
								placeholder={$i18n.t('e.g. dall-e|gpt-image')}
								bind:value={imageGenerationConfig.IMAGE_MODEL_FILTER_REGEX}
							/>
						</Tooltip>
					</div>
				</section>

				<section class="glass-section p-5 space-y-5 {isDirty ? 'glass-section-dirty' : ''}">
					<div class="flex items-center justify-between gap-3">
						<div class="text-base font-semibold text-gray-800 dark:text-gray-100">
							{$i18n.t('Model Capability Overrides')}
						</div>
						{#if capabilityOverridesEmpty}
							<button
								type="button"
								class="shrink-0 rounded-md border border-gray-200 px-2.5 py-1 text-xs text-gray-600 transition hover:bg-gray-100 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
								on:click={insertCapabilityOverrideExample}
							>
								{$i18n.t('Insert example')}
							</button>
						{/if}
					</div>
					<div class="glass-item p-4 space-y-2">
						<div class="text-xs text-gray-400 dark:text-gray-500">
							{$i18n.t(
								'Optional. Leave empty unless a new model is not detected correctly (e.g. its 2K/4K size tiers are greyed out). You usually do not need this — unsupported tiers are learned and hidden automatically.'
							)}
						</div>
						<textarea
							class="w-full min-h-[7rem] py-2 px-3 text-xs font-mono dark:text-gray-300 glass-input resize-y {capabilityOverridesInvalid
								? 'border border-red-400'
								: ''}"
							spellcheck="false"
							placeholder={'{\n  "gemini:gemini-4-flash-image": { "supports_image_size": true }\n}'}
							bind:value={imageGenerationConfig.IMAGES_MODEL_CAPABILITY_OVERRIDES_TEXT}
						/>
						{#if capabilityOverridesInvalid}
							<div class="text-xs text-red-500">
								{$i18n.t('Invalid JSON — changes cannot be saved until this is fixed.')}
							</div>
						{/if}

						<details class="mt-1 text-xs text-gray-500 dark:text-gray-400">
							<summary class="cursor-pointer select-none text-gray-600 dark:text-gray-300">
								{$i18n.t('Format & example')}
							</summary>
							<div class="mt-2 space-y-2">
								<div>
									{$i18n.t('Key format')}: <code class="font-mono">engine:model</code>
									({$i18n.t('engine is openai / gemini / grok')})
								</div>
								<pre
									class="overflow-x-auto rounded-md bg-gray-100 p-2 font-mono text-[11px] leading-5 text-gray-700 dark:bg-gray-800 dark:text-gray-200">{capabilityOverrideExample}</pre>
								<div>{$i18n.t('Common capability flags:')}</div>
								<ul class="ml-4 list-disc space-y-0.5">
									<li>
										<code class="font-mono">supports_image_size</code> — {$i18n.t(
											'size tiers such as 2K / 4K (Gemini)'
										)}
									</li>
									<li>
										<code class="font-mono">supports_resolution</code> — {$i18n.t(
											'resolution tiers (Grok)'
										)}
									</li>
									<li>
										<code class="font-mono">supports_background</code> — {$i18n.t(
											'transparent / white / black background'
										)}
									</li>
									<li>
										<code class="font-mono">supports_batch</code> — {$i18n.t(
											'generate multiple images at once'
										)}
									</li>
								</ul>
							</div>
						</details>
					</div>
				</section>
			</div>
		{/if}
	</div>
</form>
