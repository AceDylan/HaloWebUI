<script lang="ts">
	import { getContext, onDestroy, tick } from 'svelte';

	import { getHermesModelOptions, type HermesModelOptions } from '$lib/apis/hermes';
	import {
		EMPTY_HERMES_RUN_OPTIONS,
		normalizeHermesRunOptions,
		type HermesContinuation,
		type HermesRunOptions
	} from '$lib/utils/hermes';

	const i18n: any = getContext('i18n');

	// How the next hermes run starts. "派发方式" puts /reclaude, /codex or /agy
	// in front of the next message only (left on, every later "进度怎么样？"
	// started another run); right after a runner's report the next message
	// goes back to that run unless "直接" is picked; the model overrides
	// hermes' configured default for this chat. The thinking level is HaloWebUI's: hermes'
	// halowebui-reasoning-sync plugin applies the admin default, and the
	// backend passes the chat's own along.
	export let options: HermesRunOptions = { ...EMPTY_HERMES_RUN_OPTIONS };
	export let disabled = false;
	// The chat ends on this run's report: left alone, the next message goes
	// back to that run's own session ("接着上次"); "直接" then means hermes
	// answers ('hermes'), a runner starts a new task.
	export let continuation: HermesContinuation | null = null;

	const DISPATCHES: { value: HermesRunOptions['dispatch']; label: string; hint: string }[] = [
		{ value: '', label: '直接', hint: 'Hermes 自己做' },
		{ value: 'reclaude', label: 'reclaude', hint: '交给 Claude Code 在后台独占执行' },
		{ value: 'codex', label: 'codex', hint: '交给 Codex 在后台独占执行' },
		{ value: 'agy', label: 'agy', hint: '交给 AGY 在后台独占执行' }
	];

	let open = false;
	let root: HTMLDivElement;
	let button: HTMLButtonElement;
	let panel: HTMLDivElement;
	// The composer sits under the message list's stacking context (the list
	// covered a panel positioned inside it): the panel lives on <body>, placed
	// above the button.
	let panelStyle = '';
	const PANEL_WIDTH = 288;

	const portal = (node: HTMLElement) => {
		document.body.appendChild(node);
		return {
			destroy() {
				node.remove();
			}
		};
	};

	const placePanel = () => {
		if (!button || typeof window === 'undefined') return;
		const rect = button.getBoundingClientRect();
		const width = Math.min(PANEL_WIDTH, window.innerWidth - 16);
		const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
		panelStyle =
			`position: fixed; left: ${Math.round(left)}px; bottom: ${Math.round(window.innerHeight - rect.top + 8)}px; ` +
			`width: ${Math.round(width)}px; z-index: 9999;`;
	};
	let modelOptions: HermesModelOptions | null = null;
	let modelOptionsError = '';
	let loadingModels = false;

	$: current = normalizeHermesRunOptions(options);
	$: continuing = Boolean(continuation) && current.dispatch === '';
	$: direct = current.dispatch === 'hermes' || (!continuation && current.dispatch === '');
	// On the button: what differs from the default ("直接" only when it
	// overrides going back to the run).
	$: dispatchLabel = continuing
		? `接着 ${continuation?.runner}`
		: direct
			? current.dispatch === 'hermes' && continuation
				? '直接'
				: ''
			: (DISPATCHES.find((item) => item.value === current.dispatch)?.label ?? '');
	$: summary = [dispatchLabel, current.model ? current.model : ''].filter(Boolean).join(' · ');
	$: dispatchHint = continuing
		? `${continuation?.status === 'question' ? `${continuation?.runner} 在等你决定：回答` : '消息'}交回 ${continuation?.runner} 运行 ${continuation?.runId} 的原会话继续，它记得之前读过、做过的。只对下一条消息生效；选「直接」改由 Hermes 回答`
		: direct
			? continuation
				? 'Hermes 自己回答，不交回上次的任务'
				: '消息直接交给 Hermes'
			: `${DISPATCHES.find((item) => item.value === current.dispatch)?.hint ?? ''}。只对下一条消息生效，发送后回到「直接」；消息自己以 /命令 开头时以消息为准`;
	$: modelValue = current.model ? `${current.provider}\u0000${current.model}` : '';
	// The configured models (one per hermes provider entry), without the
	// default, which "默认" already stands for.
	$: modelChoices = (modelOptions?.providers ?? []).flatMap((provider) =>
		provider.models
			.filter((model) => !(provider.current && model === modelOptions?.model))
			.map((model) => ({
				value: `${provider.slug}\u0000${model}`,
				label: model,
				provider: provider.name
			}))
	);
	// A model chosen earlier that the list no longer offers stays visible.
	$: pinnedMissing = Boolean(current.model) && !modelChoices.some((item) => item.value === modelValue);

	const update = (patch: Partial<HermesRunOptions>) => {
		options = normalizeHermesRunOptions({ ...current, ...patch });
	};

	const loadModels = async () => {
		if (modelOptions || loadingModels) return;
		loadingModels = true;
		modelOptionsError = '';
		try {
			modelOptions = await getHermesModelOptions(localStorage.token);
		} catch (error) {
			console.warn('hermes model options', error);
			modelOptionsError = '没能读取 Hermes 的模型列表，可以先用默认模型';
		} finally {
			loadingModels = false;
		}
	};

	const onWindowPointer = (event: PointerEvent) => {
		const target = event.target as Node;
		if (open && root && !root.contains(target) && !(panel && panel.contains(target))) open = false;
	};
	const onWindowKey = (event: KeyboardEvent) => {
		if (open && event.key === 'Escape') {
			event.stopPropagation();
			open = false;
			button?.focus();
		}
	};
	// Keyboard users land in the panel, on the current choice.
	const focusCurrentChoice = async () => {
		await tick();
		const selected = panel?.querySelector<HTMLElement>('[role="radio"][aria-checked="true"]');
		selected?.focus();
	};
	$: if (typeof window !== 'undefined') {
		if (open) {
			placePanel();
			window.addEventListener('pointerdown', onWindowPointer, true);
			window.addEventListener('keydown', onWindowKey, true);
			window.addEventListener('resize', placePanel);
			void loadModels();
			void focusCurrentChoice();
		} else {
			window.removeEventListener('pointerdown', onWindowPointer, true);
			window.removeEventListener('keydown', onWindowKey, true);
			window.removeEventListener('resize', placePanel);
		}
	}
	onDestroy(() => {
		if (typeof window === 'undefined') return;
		window.removeEventListener('pointerdown', onWindowPointer, true);
		window.removeEventListener('keydown', onWindowKey, true);
		window.removeEventListener('resize', placePanel);
	});
</script>

<div class="relative" bind:this={root} data-halo-hermes-options>
	<button
		bind:this={button}
		type="button"
		class="flex max-w-[14rem] items-center gap-1 rounded-full px-2.5 py-1.5 text-xs font-medium ring-1 transition max-sm:py-2 {summary
			? 'bg-primary-50 text-primary-700 ring-primary-200 dark:bg-primary-900/30 dark:text-primary-200 dark:ring-primary-800/60'
			: 'text-gray-600 ring-gray-200 hover:bg-gray-100 dark:text-gray-300 dark:ring-gray-700 dark:hover:bg-gray-800'}"
		aria-haspopup="dialog"
		aria-expanded={open}
		aria-label={$i18n.t('Hermes options')}
		{disabled}
		on:click={() => {
			open = !open;
		}}
	>
		<span class="shrink-0">Hermes</span>
		{#if summary}
			<span class="truncate" data-halo-hermes-options-summary>· {summary}</span>
		{/if}
	</button>

	{#if open}
		<div
			bind:this={panel}
			use:portal
			style={panelStyle}
			class="rounded-2xl border border-gray-200 bg-white p-3 text-sm text-gray-900 shadow-lg dark:border-gray-700 dark:bg-gray-850 dark:text-gray-100"
			data-halo-hermes-options-panel
			role="dialog"
			aria-label={$i18n.t('Hermes options')}
		>
			<div class="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">派发方式</div>
			<div class="grid grid-cols-4 gap-1" role="radiogroup" aria-label="派发方式">
				{#if continuation}
					<button
						type="button"
						role="radio"
						aria-checked={continuing}
						title="交回 {continuation.runner} 运行 {continuation.runId} 的原会话"
						data-halo-hermes-dispatch="continue"
						class="col-span-4 truncate rounded-lg px-1.5 py-1.5 text-xs transition {continuing
							? 'bg-primary-600 text-white dark:bg-primary-500'
							: 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700'}"
						on:click={() => update({ dispatch: '' })}
					>
						接着上次 · {continuation.runner}
					</button>
				{/if}
				{#each DISPATCHES as item}
					{@const checked = item.value ? current.dispatch === item.value : direct}
					<button
						type="button"
						role="radio"
						aria-checked={checked}
						title={item.hint}
						data-halo-hermes-dispatch={item.value || 'direct'}
						class="rounded-lg px-1.5 py-1.5 text-xs transition {checked
							? 'bg-primary-600 text-white dark:bg-primary-500'
							: 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700'}"
						on:click={() => update({ dispatch: item.value || (continuation ? 'hermes' : '') })}
					>
						{item.label}
					</button>
				{/each}
			</div>
			<div class="mt-1 text-2xs text-gray-500 dark:text-gray-400" data-halo-hermes-dispatch-hint>
				{dispatchHint}
			</div>

			<label class="mt-3 block">
				<span class="mb-1.5 block text-xs font-medium text-gray-500 dark:text-gray-400">模型</span>
				<select
					class="w-full rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs dark:border-gray-700 dark:bg-gray-900"
					value={modelValue}
					data-halo-hermes-model
					on:change={(event) => {
						const value = event.currentTarget.value;
						if (!value) {
							update({ model: '', provider: '' });
							return;
						}
						const [provider, model] = value.split('\u0000');
						update({ model, provider });
					}}
				>
					<option value="">
						默认{modelOptions?.model ? `（${modelOptions.model}）` : ''}
					</option>
					{#if pinnedMissing}
						<option value={modelValue}>{current.model}</option>
					{/if}
					{#each modelChoices as item (item.value)}
						<option value={item.value} title={item.provider}>{item.label}</option>
					{/each}
				</select>
			</label>
			<div class="mt-1 text-2xs text-gray-400 dark:text-gray-500">
				只管 Hermes 自己这一轮；派发给 reclaude/codex/agy 时它们用自己的模型
			</div>
			{#if loadingModels}
				<div class="mt-1 text-2xs text-gray-400">正在读取 Hermes 的模型列表…</div>
			{:else if modelOptionsError}
				<div class="mt-1 text-2xs text-amber-600 dark:text-amber-400">{modelOptionsError}</div>
			{/if}

			<div class="mt-3 flex items-start justify-between gap-2 text-2xs text-gray-400 dark:text-gray-500">
				<span class="min-w-0">模型对这个对话一直生效；思考强度跟随 HaloWebUI 设置</span>
				{#if summary}
					<button
						type="button"
						class="shrink-0 whitespace-nowrap rounded px-1.5 py-0.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
						on:click={() => {
							options = { ...EMPTY_HERMES_RUN_OPTIONS };
						}}
					>
						恢复默认
					</button>
				{/if}
			</div>
		</div>
	{/if}
</div>
