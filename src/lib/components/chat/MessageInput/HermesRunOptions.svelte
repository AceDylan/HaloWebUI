<script lang="ts">
	import { getContext, onDestroy, tick } from 'svelte';

	import { getHermesModelOptions, type HermesModelOptions } from '$lib/apis/hermes';
	import { user } from '$lib/stores';
	import {
		EMPTY_HERMES_RUN_OPTIONS,
		isModeDispatch,
		normalizeHermesRunOptions,
		type HermesContinuation,
		type HermesRunOptions
	} from '$lib/utils/hermes';

	const i18n: any = getContext('i18n');

	// How the next hermes run starts. "派发方式" puts /reclaude, /cchclaude, /anyclaude, /officlaude, /codex or /agy
	// in front of the next message only (left on, every later "进度怎么样？"
	// started another run), or hands it to 精答 / 讨论台 / 协作台 instead of a run (the result
	// comes back into the chat); right after a runner's report the next message
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

	// label + a few words on each choice (sub) so the grid says who does the work without
	// hovering; hint is the full sentence under the grid for the one picked. The runners do the
	// message in Hermes' place; the modes ask it another way and send the result back here.
	const RUNNERS: {
		value: HermesRunOptions['dispatch'];
		label: string;
		sub: string;
		hint: string;
	}[] = [
		{ value: '', label: '直接', sub: 'Hermes 回答', hint: 'Hermes 自己做' },
		{
			value: 'reclaude',
			label: 'reclaude',
			sub: 'Claude · 拼车',
			hint: '交给 Claude Code（reclaude 拼车）在后台独占执行'
		},
		{
			value: 'cchclaude',
			label: 'cchclaude',
			sub: 'Claude · 自有中转',
			hint: '交给 Claude Code（自己的 cch 中转）在后台独占执行'
		},
		{
			value: 'anyclaude',
			label: 'anyclaude',
			sub: 'Claude · 免费较慢',
			hint: '交给 Claude Code（anyrouter 免费服务，较慢，失败会自动重试）在后台独占执行'
		},
		{
			value: 'officlaude',
			label: '官方 Claude',
			sub: 'Claude · 官网订阅',
			hint: '交给官方 Claude（claude.ai 订阅 OAuth 账号）在后台独占执行；需本人登录，额度用尽后手动续跑'
		},
		{ value: 'codex', label: 'codex', sub: 'OpenAI Codex', hint: '交给 Codex 在后台独占执行' },
		{ value: 'agy', label: 'agy', sub: 'Gemini · 快', hint: '交给 AGY 在后台独占执行' }
	];
	const MODES: typeof RUNNERS = [
		{
			value: 'answer',
			label: '精答',
			sub: '挑最合适的助手答',
			hint: '交给精答：调度器从助手库挑最合适的助手（没有就现写一个）来回答，对话前文作背景，答完发回这里'
		},
		{
			value: 'discuss',
			label: '讨论',
			sub: '几个模型讨论',
			hint: '交给讨论台：几个模型按你上次的设置讨论（附件放上讨论桌），主持人写的结论发回这里'
		},
		{
			value: 'team',
			label: '协作台',
			sub: '团队分工做',
			hint: '交给一支团队：负责人拆任务、成员并行（含生图），进度在对话里实时显示，完整结果发回这里'
		}
	];
	const DISPATCHES = [...RUNNERS, ...MODES];

	let open = false;
	let root: HTMLDivElement;
	let button: HTMLButtonElement;
	let panel: HTMLDivElement;
	// The composer sits under the message list's stacking context (the list
	// covered a panel positioned inside it): the panel lives on <body>, placed
	// next to the button.
	let panelStyle = '';
	const PANEL_WIDTH = 288;
	const GAP = 8;

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
		// What is on screen: on a phone the keyboard and the browser bars take part of the window.
		const view = window.visualViewport;
		const viewTop = view?.offsetTop ?? 0;
		const viewLeft = view?.offsetLeft ?? 0;
		const viewWidth = view?.width ?? window.innerWidth;
		const viewHeight = view?.height ?? window.innerHeight;
		// On a phone the dispatch choices need the width: at 288px "reclaude" broke
		// mid-word into "reclaud / e". The choices sit three to a row.
		const width = viewWidth < 640 ? viewWidth - GAP * 2 : PANEL_WIDTH;
		const left = Math.max(viewLeft + GAP, Math.min(rect.left, viewLeft + viewWidth - width - GAP));
		// Above the button unless it only fits below (a new chat's composer mid-screen), and never
		// taller than the room on that side: on a phone the panel always opened upward and its top,
		// the 派发给谁 choices, went past the top of the screen. What does not fit scrolls.
		const above = rect.top - viewTop - GAP * 2;
		const below = viewTop + viewHeight - rect.bottom - GAP * 2;
		const needed = panel?.scrollHeight ?? 0;
		const up = above >= needed || above >= below;
		const place = up
			? `top: ${Math.round(rect.top - GAP)}px; transform: translateY(-100%);`
			: `top: ${Math.round(rect.bottom + GAP)}px;`;
		panelStyle =
			`position: fixed; left: ${Math.round(left)}px; ${place} ` +
			`max-height: ${Math.max(0, Math.round(up ? above : below))}px; ` +
			`width: ${Math.round(width)}px; z-index: 9999;`;
	};
	let modelOptions: HermesModelOptions | null = null;
	let modelOptionsError = '';
	let loadingModels = false;

	$: current = normalizeHermesRunOptions(options);
	$: continuationLabel =
		DISPATCHES.find((item) => item.value === continuation?.runner)?.label ?? continuation?.runner;
	$: continuing = Boolean(continuation) && current.dispatch === '';
	$: direct = current.dispatch === 'hermes' || (!continuation && current.dispatch === '');
	// On the button: what differs from the default ("直接" only when it
	// overrides going back to the run).
	$: dispatchLabel = continuing
		? `接着 ${continuationLabel}`
		: direct
			? current.dispatch === 'hermes' && continuation
				? '直接'
				: ''
			: (DISPATCHES.find((item) => item.value === current.dispatch)?.label ?? '');
	$: summary = [dispatchLabel, current.model ? current.model : ''].filter(Boolean).join(' · ');
	$: dispatchHint = continuing
		? `${continuation?.status === 'question' ? `${continuationLabel} 在等你决定：回答` : '消息'}交回 ${continuationLabel} 运行 ${continuation?.runId} 的原会话继续，它记得之前读过、做过的。只对下一条消息生效；选「直接」改由 Hermes 回答`
		: direct
			? continuation
				? 'Hermes 自己回答，不交回上次的任务'
				: '消息直接交给 Hermes'
			: `${DISPATCHES.find((item) => item.value === current.dispatch)?.hint ?? ''}。只对下一条消息生效，发送后回到「直接」；消息自己以 /命令 开头时以消息为准，交给 Hermes`;
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
	// The thinking level is not per chat: hermes' reasoning-sync plugin sets the
	// Message Gateway default on every request (Telegram too). Saying which
	// level, and where it is changed, is the one speed lever the panel can point at.
	const EFFORT_LABELS: Record<string, string> = {
		none: '关闭',
		low: '低',
		medium: '中',
		high: '高',
		xhigh: '超高',
		max: '最大'
	};
	$: effortLabel = EFFORT_LABELS[modelOptions?.reasoning_effort ?? ''] ?? '';
	// A model chosen earlier that the list no longer offers stays visible.
	$: pinnedMissing =
		Boolean(current.model) && !modelChoices.some((item) => item.value === modelValue);

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
	// Placed again once drawn (its height picks the side), then keyboard users land in the
	// panel, on the current choice.
	const focusCurrentChoice = async () => {
		await tick();
		placePanel();
		const selected = panel?.querySelector<HTMLElement>('[role="radio"][aria-checked="true"]');
		selected?.focus();
	};
	// The phone keyboard opening or closing moves the button without resizing the window.
	const listenViewport = (on: boolean) => {
		const view = window.visualViewport;
		if (!view) return;
		if (on) {
			view.addEventListener('resize', placePanel);
			view.addEventListener('scroll', placePanel);
		} else {
			view.removeEventListener('resize', placePanel);
			view.removeEventListener('scroll', placePanel);
		}
	};
	$: if (typeof window !== 'undefined') {
		if (open) {
			placePanel();
			window.addEventListener('pointerdown', onWindowPointer, true);
			window.addEventListener('keydown', onWindowKey, true);
			window.addEventListener('resize', placePanel);
			listenViewport(true);
			void loadModels();
			void focusCurrentChoice();
		} else {
			window.removeEventListener('pointerdown', onWindowPointer, true);
			window.removeEventListener('keydown', onWindowKey, true);
			window.removeEventListener('resize', placePanel);
			listenViewport(false);
		}
	}
	onDestroy(() => {
		if (typeof window === 'undefined') return;
		window.removeEventListener('pointerdown', onWindowPointer, true);
		window.removeEventListener('keydown', onWindowKey, true);
		window.removeEventListener('resize', placePanel);
		listenViewport(false);
	});
</script>

<div class="relative" bind:this={root} data-halo-hermes-options>
	<button
		bind:this={button}
		type="button"
		class="flex h-8 max-w-[14rem] items-center gap-1 whitespace-nowrap rounded-full border px-2.5 text-xs font-medium transition {summary
			? 'border-primary-200 bg-primary-50 text-primary-700 dark:border-primary-800/60 dark:bg-primary-900/30 dark:text-primary-200'
			: 'border-gray-200 text-gray-600 hover:bg-gray-100 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800'}"
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
			class="halo-dispatch rounded-2xl p-3 text-sm text-gray-900 dark:text-gray-100"
			data-halo-hermes-options-panel
			role="dialog"
			aria-label={$i18n.t('Hermes options')}
		>
			<div class="halo-dispatch__label mb-2">派发给谁</div>
			<div class="grid grid-cols-3 gap-1.5" role="radiogroup" aria-label="派发方式">
				{#if continuation}
					<button
						type="button"
						role="radio"
						aria-checked={continuing}
						title="交回 {continuationLabel} 运行 {continuation.runId} 的原会话"
						data-halo-hermes-dispatch="continue"
						class="halo-dispatch__choice col-span-3 {continuing ? 'is-on' : ''}"
						on:click={() => update({ dispatch: '' })}
					>
						<span class="halo-dispatch__name">接着上次 · {continuationLabel}</span>
						<span class="halo-dispatch__sub"
							>{continuation.status === 'question'
								? '它在等你决定，回到同一个会话'
								: '回到同一个会话，之前读过、做过的都在'}</span
						>
					</button>
				{/if}
				{#each RUNNERS as item}
					{@const checked = item.value ? current.dispatch === item.value : direct}
					<button
						type="button"
						role="radio"
						aria-checked={checked}
						title={item.hint}
						data-halo-hermes-dispatch={item.value || 'direct'}
						class="halo-dispatch__choice {checked ? 'is-on' : ''}"
						on:click={() => update({ dispatch: item.value || (continuation ? 'hermes' : '') })}
					>
						<span class="halo-dispatch__name">{item.label}</span>
						<span class="halo-dispatch__sub">{item.sub}</span>
					</button>
				{/each}
				<div class="halo-dispatch__label col-span-3 mt-1.5" data-halo-hermes-modes-label>
					换一种方式问 · 结果发回这里
				</div>
				{#each MODES as item}
					{@const checked = current.dispatch === item.value}
					<button
						type="button"
						role="radio"
						aria-checked={checked}
						title={item.hint}
						data-halo-hermes-dispatch={item.value}
						class="halo-dispatch__choice {checked ? 'is-on' : ''}"
						on:click={() => update({ dispatch: item.value })}
					>
						<span class="halo-dispatch__name">{item.label}</span>
						<span class="halo-dispatch__sub">{item.sub}</span>
					</button>
				{/each}
			</div>
			<div
				class="mt-2 text-2xs leading-relaxed text-gray-500 dark:text-gray-400"
				data-halo-hermes-dispatch-hint
			>
				{dispatchHint}
			</div>

			<label class="mt-3 block">
				<span class="halo-dispatch__label mb-1.5 block">Hermes 用的模型</span>
				<select
					class="halo-dispatch__select w-full rounded-xl px-2.5 py-2 text-xs"
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
			<div class="mt-1 text-2xs text-gray-400 dark:text-gray-500" data-halo-hermes-model-note>
				{#if isModeDispatch(current.dispatch)}
					这条消息交给{DISPATCHES.find((item) => item.value === current.dispatch)?.label}，不经过
					Hermes 的模型；之后的消息照常用它
				{:else}
					只管 Hermes 自己这一轮；派发给 reclaude/cchclaude/anyclaude/officlaude/codex/agy
					时它们用自己的模型
				{/if}
			</div>
			{#if loadingModels}
				<div class="mt-1 text-2xs text-gray-400">正在读取 Hermes 的模型列表…</div>
			{:else if modelOptionsError}
				<div class="mt-1 text-2xs text-amber-600 dark:text-amber-400">{modelOptionsError}</div>
			{/if}

			<div
				class="mt-3 flex items-start justify-between gap-2 text-2xs text-gray-400 dark:text-gray-500"
			>
				<span class="min-w-0">模型对这个对话一直生效</span>
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
			<div class="mt-1 text-2xs text-gray-400 dark:text-gray-500" data-halo-hermes-effort-note>
				{#if effortLabel}
					思考强度{effortLabel}，Hermes 各入口共用，调低回复更快{#if $user?.role === 'admin'}{' · '}<a
							class="text-primary-600 hover:underline dark:text-primary-400"
							href="/settings/haloclaw"
							on:click={() => {
								open = false;
							}}>去修改</a
						>{/if}
				{:else}
					思考强度跟随 HaloWebUI 设置（消息网关）
				{/if}
			</div>
		</div>
	{/if}
</div>
