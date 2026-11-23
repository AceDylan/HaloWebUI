<script lang="ts">
	// 「Hermes 模型」: which model hermes answers with, what it falls back to, and the side
	// models for sub-agents, auxiliary tasks and media. Hermes owns the write and the history
	// (hermes_cli/routing_admin.py); config.yaml stays the one source, so Telegram and the CLI
	// follow the same routing. A save applies from the next message, no restart.
	// 「AGY 优先」 rides along: the HTML card's offiagy model (a HaloWebUI setting), where team UI
	// tasks start and offiagy's model (hermes' halo-teams-runners.json); one save bar for all.
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import {
		getHermesAgyPrefs,
		getHermesRouting,
		probeHermesRoutingModel,
		rollbackHermesRouting,
		saveHermesAgyPrefs,
		saveHermesRouting,
		type HermesAgyPrefs,
		type HermesRouting,
		type HermesRoutingModel,
		type HermesRoutingSnapshot
	} from '$lib/apis/hermes';
	import { getHaloClawConfig } from '$lib/apis/haloclaw';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ModelPicker from './HermesRouting/ModelPicker.svelte';
	import ChainEditor from './HermesRouting/ChainEditor.svelte';
	import {
		API_MODE_LABELS,
		AUX_TASKS,
		MEDIA_TIMEOUT_MAX,
		MEDIA_TIMEOUT_MIN,
		ROUTING_MAX_AUX_FALLBACKS,
		ROUTING_MAX_FALLBACKS,
		agyChanges,
		agyDraftFrom,
		auxTaskLabel,
		describeChange,
		diffRouting,
		historySourceLabel,
		isForeignModel,
		modelFamily,
		modelLabel,
		orderedAuxTasks,
		runnerLabel,
		withPrimary,
		type AgyDraft
	} from '$lib/utils/hermes-routing';

	const EFFORT_LABELS: Record<string, string> = {
		none: '关闭',
		low: '低',
		medium: '中',
		high: '高',
		xhigh: '超高',
		max: '最大'
	};

	let loading = true;
	let loadError = '';
	let saving = false;
	let snap: HermesRoutingSnapshot | null = null;
	let draft: HermesRouting | null = null;
	let haloEffort = '';
	let conflict = false;
	let confirmRollback = '';
	let confirmTimer: ReturnType<typeof setTimeout> | undefined;
	type ProbeState = { state: 'run' | 'ok' | 'fail'; ms?: number; error?: string };
	let probes: Record<string, ProbeState> = {};
	let agyPrefs: HermesAgyPrefs | null = null;
	let agyDraft: AgyDraft | null = null;
	let agyError = '';

	const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

	const adopt = (next: HermesRoutingSnapshot) => {
		snap = next;
		draft = clone(next.routing);
		conflict = false;
	};

	const adoptAgy = (next: HermesAgyPrefs) => {
		agyPrefs = next;
		agyDraft = agyDraftFrom(next);
	};

	const loadAgy = async () => {
		agyError = '';
		try {
			adoptAgy(await getHermesAgyPrefs(localStorage.token));
		} catch (e) {
			agyError = `${(e as Error)?.message ?? e}`;
		}
	};

	const load = async () => {
		loading = !snap;
		loadError = '';
		try {
			adopt(await getHermesRouting(localStorage.token));
		} catch (e) {
			loadError = `${e}`;
		}
		loading = false;
	};

	onMount(() => {
		load();
		loadAgy();
		getHaloClawConfig(localStorage.token)
			.then((cfg: any) => (haloEffort = String(cfg?.default_reasoning_effort ?? '')))
			.catch(() => {});
		return () => clearTimeout(confirmTimer);
	});

	$: models = snap?.models ?? [];
	$: modelIds = models.map((m) => m.id);
	$: modelById = Object.fromEntries(models.map((m) => [m.id, m])) as Record<
		string,
		HermesRoutingModel
	>;
	$: changes = snap && draft ? diffRouting(snap.routing, draft) : [];
	$: routingDirty = changes.length > 0;
	$: agy =
		agyPrefs && agyDraft
			? agyChanges(agyDraftFrom(agyPrefs), agyDraft)
			: { update: {}, lines: [] as string[] };
	$: agyDirty = agy.lines.length > 0;
	$: dirty = routingDirty || agyDirty;
	$: changeLines = [...changes.map(describeChange), ...agy.lines];
	$: agyModels = agyPrefs?.teams.offiagy_models ?? [];
	$: agyChoices = agyPrefs?.teams.ui_choices ?? [];
	$: uiChain =
		agyChoices.find((c) => c.name === agyDraft?.ui_runner)?.chain ??
		(agyDraft?.ui_runner ? [agyDraft.ui_runner] : []);
	// a saved model the list does not have (listing failed, or set by hand) stays selectable
	const modelOptions = (list: { id: string; name: string }[], current: string) =>
		current && !list.some((m) => m.id === current)
			? [{ id: current, name: current }, ...list]
			: list;
	$: auxTasks = draft ? orderedAuxTasks(Object.keys(draft.auxiliary)) : [];
	$: mainModel = draft ? modelById[draft.main] : undefined;
	$: delegationPrimary = draft ? draft.delegation.model || draft.main : '';

	const touch = () => (draft = draft);

	const setMain = (id: string) => {
		if (!draft) return;
		draft.main = id;
		draft.fallback = withPrimary(draft.fallback, id);
		touch();
	};
	const setDelegation = (id: string) => {
		if (!draft) return;
		draft.delegation.model = id;
		draft.delegation.fallback = withPrimary(draft.delegation.fallback, id || draft.main);
		touch();
	};
	const setAux = (task: string, id: string) => {
		if (!draft) return;
		const row = draft.auxiliary[task];
		row.model = id;
		// Following the main model means following its chain too.
		row.fallback = id ? withPrimary(row.fallback, id) : [];
		touch();
	};

	const discard = () => {
		if (snap) draft = clone(snap.routing);
		if (agyPrefs) agyDraft = agyDraftFrom(agyPrefs);
	};

	const errorStatus = (e: any) => Number(e?.status) || 0;

	const save = async () => {
		if (!snap || !draft || !dirty) return;
		saving = true;
		let saved = 0;
		try {
			if (routingDirty) {
				const next = await saveHermesRouting(localStorage.token, draft, snap.revision);
				saved += next.changes?.length ?? 0;
				adopt(next);
			}
			if (agyDirty) {
				const n = agy.lines.length;
				adoptAgy(await saveHermesAgyPrefs(localStorage.token, agy.update));
				saved += n;
			}
			toast.success(saved ? `已保存 ${saved} 处改动，下一次任务起生效` : '没有需要保存的改动');
		} catch (e) {
			if (errorStatus(e) === 409) conflict = true;
			toast.error(`${(e as Error)?.message ?? e}`);
		}
		saving = false;
	};

	const askRollback = (id: string) => {
		clearTimeout(confirmTimer);
		confirmRollback = id;
		confirmTimer = setTimeout(() => (confirmRollback = ''), 5000);
	};

	const rollback = async (id: string) => {
		if (!snap) return;
		confirmRollback = '';
		saving = true;
		try {
			const next = await rollbackHermesRouting(localStorage.token, id, snap.revision);
			adopt(next);
			toast.success(
				next.changes?.length ? '已回滚，下一条消息起生效' : '当前已经是那次改动之前的样子'
			);
		} catch (e) {
			if (errorStatus(e) === 409) conflict = true;
			toast.error(`${(e as Error)?.message ?? e}`);
		}
		saving = false;
	};

	const probe = async (id: string) => {
		probes = { ...probes, [id]: { state: 'run' } };
		try {
			const r = await probeHermesRoutingModel(localStorage.token, id);
			probes = {
				...probes,
				[id]: r.ok
					? { state: 'ok', ms: r.latency_ms }
					: { state: 'fail', ms: r.latency_ms, error: r.error || '无回复' }
			};
		} catch (e) {
			probes = { ...probes, [id]: { state: 'fail', error: `${(e as Error)?.message ?? e}` } };
		}
	};
	const probeAll = () => modelIds.forEach((id) => probe(id));

	const probeText = (p?: ProbeState) =>
		!p
			? '未测'
			: p.state === 'run'
				? '测试中'
				: p.state === 'ok'
					? `${((p.ms ?? 0) / 1000).toFixed(1)}s`
					: '不通';

	const timeText = (at: number) => {
		const d = new Date(at * 1000);
		const pad = (n: number) => String(n).padStart(2, '0');
		return `${d.getMonth() + 1}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
	};

	type Lane = {
		key: string;
		title: string;
		primary: string;
		chain: string[];
		empty: string;
		label?: (id: string) => string;
	};
	const lanes = (r: HermesRouting, a: AgyDraft | null, ui: string[]): Lane[] => [
		{ key: 'chat', title: '对话', primary: r.main, chain: r.fallback, empty: '' },
		{
			key: 'delegation',
			title: '子代理',
			primary: r.delegation.model,
			chain: r.delegation.fallback,
			empty: '跟随主模型'
		},
		{ key: 'media', title: '媒体识别', primary: r.media.model, chain: [], empty: '不走首选' },
		...(a
			? [
					{
						key: 'card',
						title: '回答卡片',
						primary: a.card_model,
						chain: a.card_model ? ['agy'] : [],
						empty: runnerLabel('agy'),
						label: (id: string) => (id === 'agy' ? runnerLabel('agy') : id)
					},
					{
						key: 'ui',
						title: '界面任务',
						primary: ui[0] ?? '',
						chain: ui.slice(1),
						empty: '—',
						label: runnerLabel
					}
				]
			: [])
	];
</script>

<div class="hr-page flex flex-col h-full text-sm" data-halo-mode="hermes" data-hermes-routing>
	<div class="overflow-y-scroll scrollbar-hidden h-full min-h-0">
		{#if loading}
			<div class="flex h-full items-center justify-center"><Spinner /></div>
		{:else if loadError || !snap || !draft}
			<section class="halo-settings-head glass-section p-5">
				<div class="halo-settings-title text-base font-semibold">Hermes 模型</div>
				<p class="mt-2 text-xs text-rose-500">读取失败：{loadError}</p>
				<button type="button" class="halo-wb-opt mt-3" on:click={load}>重试</button>
			</section>
		{:else}
			<section class="halo-settings-head glass-section p-5 mb-4">
				<div class="flex flex-wrap items-start gap-3">
					<div class="glass-icon-badge">
						<svg
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							class="size-[18px]"
							aria-hidden="true"
						>
							<circle cx="12" cy="12" r="3.2" />
							<ellipse cx="12" cy="12" rx="9" ry="3.6" />
							<ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(60 12 12)" />
							<ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(-60 12 12)" />
						</svg>
					</div>
					<div class="min-w-0 flex-1">
						<div
							class="halo-settings-title text-base font-semibold text-gray-800 dark:text-gray-100"
						>
							Hermes 模型
						</div>
						<p class="halo-settings-desc mt-1 text-xs text-gray-500 dark:text-gray-400">
							Hermes 用哪个模型回答、失败了换谁、子代理和后台小任务用谁。和
							Telegram、命令行是同一份配置，保存后下一条消息起生效，不用重启。对话里单独选过模型的不受影响。
						</p>
					</div>
				</div>

				<!-- the star-core: every lane at a glance, reflecting unsaved edits -->
				<div class="hr-lanes mt-4">
					{#each lanes(draft, agyDraft, uiChain) as lane (lane.key)}
						<div class="hr-lane" data-lane={lane.key}>
							<span class="hr-lane-title">{lane.title}</span>
							<span class="hr-node hr-core" class:hr-follow={!lane.primary}>
								<span class="hr-orbit" aria-hidden="true"></span>
								<span
									class="hr-dot"
									class:hr-dot-follow={!lane.primary}
									data-family={modelFamily(lane.primary)}
									aria-hidden="true"
								></span>
								{lane.label && lane.primary
									? lane.label(lane.primary)
									: modelLabel(lane.primary, lane.empty)}
							</span>
							{#each lane.chain as id (id)}
								<span class="hr-beam" aria-hidden="true"></span>
								<span class="hr-node" data-model={id}>
									<span class="hr-dot" data-family={modelFamily(id)} aria-hidden="true"
									></span>{lane.label ? lane.label(id) : modelLabel(id)}
								</span>
							{/each}
							{#if lane.key === 'chat' && !lane.chain.length}
								<span class="hr-beam hr-beam-off" aria-hidden="true"></span>
								<span class="hr-lane-warn">没有兜底，主模型挂了就没人回答</span>
							{/if}
							{#if lane.key === 'media'}
								<span class="hr-lane-meta">超时 {draft.media.timeout} 秒</span>
							{/if}
						</div>
					{/each}
				</div>

				{#if dirty}
					<div class="hr-unsaved mt-3" role="status">
						未保存：{changeLines.length} 处改动，上面是改完后的样子
					</div>
				{/if}
			</section>

			<div class="space-y-3 pb-4">
				<!-- the model array -->
				<section class="glass-item hr-card px-4 py-3">
					<div class="hr-card-head">
						<div>
							<div class="hr-card-title">可用模型</div>
							<div class="hr-card-hint">
								Hermes 配置里的模型，下面每一处都只能从这里选。点「测试」发一条真实小请求。
							</div>
						</div>
						<button type="button" class="halo-wb-opt hr-nowrap" on:click={probeAll}>全部测试</button
						>
					</div>
					<div class="hr-models mt-2">
						{#each models as m (m.id)}
							<div class="hr-model" data-model={m.id}>
								<span class="hr-dot" data-family={modelFamily(m.id)} aria-hidden="true"></span>
								<span class="hr-model-name">{m.id}</span>
								<span class="hr-tag">{API_MODE_LABELS[m.api_mode] ?? m.api_mode}</span>
								{#if m.vision}<span class="hr-tag hr-tag-on">原生看图</span>{/if}
								<span class="flex-1"></span>
								<span
									class="hr-probe"
									data-state={probes[m.id]?.state ?? 'idle'}
									title={probes[m.id]?.error ?? ''}>{probeText(probes[m.id])}</span
								>
								<button
									type="button"
									class="hr-mini-btn"
									disabled={probes[m.id]?.state === 'run'}
									on:click={() => probe(m.id)}>测试</button
								>
							</div>
						{/each}
					</div>
					{#each models.filter((m) => probes[m.id]?.state === 'fail') as m (m.id)}
						<div class="hr-probe-error mt-1">{m.id}：{probes[m.id]?.error}</div>
					{/each}
				</section>

				<!-- main + fallback -->
				<section class="glass-item hr-card px-4 py-3" data-section="main">
					<div class="hr-card-title">对话主模型</div>
					<div class="hr-card-hint">所有对话默认由它回答（网页、Telegram、QQ、定时任务）。</div>
					<div class="mt-2">
						<ModelPicker
							label="主模型"
							value={draft.main}
							models={modelIds}
							on:change={(e) => setMain(e.detail)}
						/>
					</div>
					{#if mainModel && !mainModel.vision}
						<div class="hr-note mt-2">
							{mainModel.id} 不能直接看图：附图会先交给「媒体识别」描述成文字。
						</div>
					{/if}
					<div class="hr-sub mt-3">
						<span class="hr-sub-label">失败时依次换</span>
						<ChainEditor
							label="兜底链"
							chain={draft.fallback}
							models={modelIds}
							primary={draft.main}
							limit={ROUTING_MAX_FALLBACKS}
							emptyText="不兜底"
							on:change={(e) => {
								if (draft) draft.fallback = e.detail;
								touch();
							}}
						/>
					</div>
					<div class="hr-note mt-2">
						思考强度由「消息网关」统一设置{haloEffort
							? `：${EFFORT_LABELS[haloEffort] ?? haloEffort}`
							: ''}，
						<a class="hr-link-text" href="/settings/haloclaw">去修改</a>
					</div>
				</section>

				<!-- delegation -->
				<section class="glass-item hr-card px-4 py-3" data-section="delegation">
					<div class="hr-card-title">子代理</div>
					<div class="hr-card-hint">
						Hermes 把子任务分给子代理时用的模型。它有自己的兜底链，不会沿用上面那条。
					</div>
					<div class="mt-2">
						<ModelPicker
							label="子代理模型"
							value={draft.delegation.model}
							models={modelIds}
							emptyLabel="跟随主模型"
							on:change={(e) => setDelegation(e.detail)}
						/>
					</div>
					<div class="hr-sub mt-3">
						<span class="hr-sub-label">失败时依次换</span>
						<ChainEditor
							label="子代理兜底链"
							chain={draft.delegation.fallback}
							models={modelIds}
							primary={delegationPrimary}
							limit={ROUTING_MAX_FALLBACKS}
							on:change={(e) => {
								if (draft) draft.delegation.fallback = e.detail;
								touch();
							}}
						/>
					</div>
				</section>

				<!-- media -->
				<section class="glass-item hr-card px-4 py-3" data-section="media">
					<div class="hr-card-title">媒体识别</div>
					<div class="hr-card-hint">
						语音转文字、看图、看视频先交给它，失败再走各入口原来的路径。
					</div>
					<div class="mt-2">
						<ModelPicker
							label="媒体识别模型"
							value={draft.media.model}
							models={modelIds}
							emptyLabel="不走首选"
							on:change={(e) => {
								if (draft) draft.media.model = e.detail;
								touch();
							}}
						/>
					</div>
					<label class="hr-sub mt-3">
						<span class="hr-sub-label">超时</span>
						<input
							class="glass-input hr-num"
							type="number"
							min={MEDIA_TIMEOUT_MIN}
							max={MEDIA_TIMEOUT_MAX}
							step="10"
							bind:value={draft.media.timeout}
						/>
						<span class="hr-card-hint">秒（{MEDIA_TIMEOUT_MIN}–{MEDIA_TIMEOUT_MAX}）</span>
					</label>
				</section>

				<!-- auxiliary -->
				<section class="glass-item hr-card px-4 py-3" data-section="auxiliary">
					<div class="hr-card-title">后台小任务</div>
					<div class="hr-card-hint">
						压缩上下文、起标题、提取网页这类辅助活儿。「跟随主模型」就用上面的主模型和兜底链。
					</div>
					<div class="hr-aux mt-2">
						{#each auxTasks as task (task)}
							<div class="hr-aux-row" data-task={task}>
								<div class="hr-aux-name">
									<span>{auxTaskLabel(task)}</span>
									{#if AUX_TASKS[task]?.hint}<span class="hr-card-hint">{AUX_TASKS[task].hint}</span
										>{/if}
								</div>
								<div class="hr-aux-ctl">
									<ModelPicker
										compact
										label={auxTaskLabel(task)}
										value={draft.auxiliary[task].model}
										models={modelIds}
										emptyLabel="跟随主模型"
										on:change={(e) => setAux(task, e.detail)}
									/>
									{#if draft.auxiliary[task].model && !isForeignModel(draft.auxiliary[task].model)}
										<div class="hr-aux-chain">
											<span class="hr-sub-label">兜底</span>
											<ChainEditor
												compact
												label="{auxTaskLabel(task)}兜底"
												chain={draft.auxiliary[task].fallback}
												models={modelIds}
												primary={draft.auxiliary[task].model}
												limit={ROUTING_MAX_AUX_FALLBACKS}
												on:change={(e) => {
													if (draft) draft.auxiliary[task].fallback = e.detail;
													touch();
												}}
											/>
										</div>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</section>

				<!-- AGY first -->
				<section class="glass-item hr-card px-4 py-3" data-section="agy">
					<div class="hr-card-title">AGY 优先</div>
					<div class="hr-card-hint">
						回答卡片和协作台的前端 / 界面任务，先用 Google 账号登录的
						AGY（offiagy），不行再换网关上的 agy（Hermes 的 gemini-chat）。
					</div>
					{#if !agyPrefs || !agyDraft}
						{#if agyError}
							<div class="hr-probe-error mt-2">读取失败：{agyError}</div>
							<button type="button" class="hr-mini-btn mt-2" on:click={loadAgy}>重试</button>
						{:else}
							<div class="hr-card-hint mt-2">读取中…（要列出 offiagy 的模型，第一次稍慢）</div>
						{/if}
					{:else}
						<div class="hr-aux mt-2">
							<div class="hr-aux-row" data-agy="card">
								<div class="hr-aux-name">
									<span>回答卡片</span>
									<span class="hr-card-hint">HTML 卡片先用它，失败或用掉一半时间就走网关 agy</span>
								</div>
								<div class="hr-aux-ctl">
									<select
										class="glass-input hr-select"
										aria-label="回答卡片的 offiagy 模型"
										bind:value={agyDraft.card_model}
									>
										<option value="">关闭：直接走网关 agy</option>
										{#each modelOptions(agyModels, agyDraft.card_model) as m (m.id)}
											<option value={m.id}>{m.name === m.id ? m.id : `${m.name} · ${m.id}`}</option>
										{/each}
									</select>
									{#if !agyPrefs.card.signed_in}
										<div class="hr-note">
											没有 Google 登录凭据，卡片不会尝试 offiagy，只走网关 agy。
										</div>
									{/if}
								</div>
							</div>
							{#if agyPrefs.teams.error}
								<div class="hr-probe-error">协作台部分读取失败：{agyPrefs.teams.error}</div>
							{:else}
								<div class="hr-aux-row" data-agy="ui">
									<div class="hr-aux-name">
										<span>协作台界面任务</span>
										<span class="hr-card-hint">没点名执行器的前端 / UI 成员从这里开始</span>
									</div>
									<div class="hr-aux-ctl">
										<div class="hr-picker" role="radiogroup" aria-label="界面任务起点">
											{#each agyChoices as c (c.name)}
												<button
													type="button"
													class="halo-wb-opt hr-runner"
													role="radio"
													data-runner={c.name}
													title={c.note}
													aria-checked={agyDraft.ui_runner === c.name}
													on:click={() => {
														if (agyDraft) agyDraft.ui_runner = c.name;
													}}>{runnerLabel(c.name)}</button
												>
											{/each}
										</div>
										<div class="hr-note">依次尝试：{uiChain.map(runnerLabel).join(' › ')}</div>
									</div>
								</div>
								<div class="hr-aux-row" data-agy="offiagy-model">
									<div class="hr-aux-name">
										<span>offiagy 模型</span>
										<span class="hr-card-hint">协作台和 /offiagy 派发用 Google 账号跑 AGY 时</span>
									</div>
									<div class="hr-aux-ctl">
										<select
											class="glass-input hr-select"
											aria-label="offiagy 模型"
											bind:value={agyDraft.offiagy_model}
										>
											<option value="">AGY 默认（agy 自己的设置）</option>
											{#each modelOptions(agyModels, agyDraft.offiagy_model) as m (m.id)}
												<option value={m.id}
													>{m.name === m.id ? m.id : `${m.name} · ${m.id}`}</option
												>
											{/each}
										</select>
									</div>
								</div>
							{/if}
						</div>
					{/if}
				</section>

				<!-- history -->
				<section class="glass-item hr-card px-4 py-3" data-section="history">
					<div class="hr-card-title">改动记录</div>
					<div class="hr-card-hint">
						每次保存前都备份了整份配置。回滚只恢复模型这几项，其他配置不动（「AGY
						优先」的改动不记在这里）。
					</div>
					{#if snap.history.length === 0}
						<div class="hr-card-hint mt-2">还没有网页上的改动。</div>
					{:else}
						<ul class="hr-history mt-2">
							{#each snap.history as h (h.id)}
								<li class="hr-history-row" data-history={h.id}>
									<span class="hr-history-time">{timeText(h.at)}</span>
									<span class="hr-tag">{historySourceLabel(h.source)}</span>
									<span class="hr-history-changes">
										{#each h.changes as c}<span>{describeChange(c)}</span>{/each}
									</span>
									{#if confirmRollback === h.id}
										<button
											type="button"
											class="hr-mini-btn hr-danger"
											disabled={saving}
											on:click={() => rollback(h.id)}>确认回滚</button
										>
									{:else}
										<button
											type="button"
											class="hr-mini-btn"
											disabled={saving || dirty}
											title={dirty ? '先保存或放弃当前改动' : '恢复成这次改动之前'}
											on:click={() => askRollback(h.id)}>回滚</button
										>
									{/if}
								</li>
							{/each}
						</ul>
					{/if}
				</section>
			</div>
		{/if}
	</div>

	{#if snap && draft}
		<div class="hr-bar" class:hr-bar-dirty={dirty || conflict}>
			<div class="hr-bar-text">
				{#if conflict}
					<span class="text-rose-500">配置刚被别处改过</span>
					<button type="button" class="hr-link-text" on:click={load}>重新读取</button>
				{:else if dirty}
					<span class="hr-bar-count">{changeLines.length} 处改动</span>
					<span class="hr-bar-list">{changeLines.join('；')}</span>
				{:else}
					<span class="hr-card-hint">没有未保存的改动</span>
				{/if}
			</div>
			<button type="button" class="halo-wb-opt" disabled={!dirty || saving} on:click={discard}
				>放弃</button
			>
			<button
				type="button"
				class="workspace-primary-button hr-save"
				disabled={!dirty || saving || conflict}
				on:click={save}
			>
				{saving ? '保存中…' : '保存并生效'}
			</button>
		</div>
	{/if}
</div>

<style>
	/* family colours: one hue per vendor, used by every dot and core on the page */
	.hr-page {
		--hr-gpt: #10b981;
		--hr-deepseek: #3b82f6;
		--hr-gemini: #8b5cf6;
		--hr-claude: #f97316;
		--hr-other: #94a3b8;
	}
	.hr-page :global(.hr-dot) {
		--hr-c: var(--hr-other);
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 999px;
		flex: none;
		background: var(--hr-c);
		box-shadow: 0 0 0 2px rgb(148 163 184 / 0.15);
	}
	.hr-page :global(.hr-dot[data-family='gpt']) {
		--hr-c: var(--hr-gpt);
	}
	.hr-page :global(.hr-dot[data-family='deepseek']) {
		--hr-c: var(--hr-deepseek);
	}
	.hr-page :global(.hr-dot[data-family='gemini']) {
		--hr-c: var(--hr-gemini);
	}
	.hr-page :global(.hr-dot[data-family='claude']) {
		--hr-c: var(--hr-claude);
	}
	.hr-page :global(.hr-dot-follow) {
		background: transparent;
		box-shadow: inset 0 0 0 1.5px var(--hr-other);
	}
	:global(html.halo-scifi.dark) .hr-page :global(.hr-dot:not(.hr-dot-follow)) {
		box-shadow: 0 0 8px var(--hr-c);
	}

	/* ---- the lanes: core node + beams + fallbacks ---- */
	.hr-lanes {
		display: grid;
		gap: 0.55rem;
	}
	.hr-lane {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
		min-height: 2.1rem;
	}
	.hr-lane-title {
		width: 4.2rem;
		flex: none;
		font-size: 0.7rem;
		font-weight: 600;
		letter-spacing: 0.08em;
		color: rgb(100 116 139);
	}
	.hr-node {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		border-radius: 0.7rem;
		border: 1px solid rgb(15 23 42 / 0.1);
		background: rgb(255 255 255 / 0.7);
		padding: 0.28rem 0.6rem;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.74rem;
		color: rgb(51 65 85);
	}
	:global(.dark) .hr-node {
		border-color: rgb(255 255 255 / 0.09);
		background: rgb(255 255 255 / 0.03);
		color: rgb(203 213 225);
	}
	.hr-core {
		font-weight: 600;
		font-size: 0.8rem;
		padding: 0.38rem 0.75rem;
		color: rgb(15 23 42);
		border-color: rgb(15 23 42 / 0.25);
	}
	:global(.dark) .hr-core {
		color: #fff;
		border-color: rgb(255 255 255 / 0.25);
	}
	.hr-core.hr-follow {
		font-weight: 500;
		border-style: dashed;
	}
	.hr-orbit {
		display: none;
	}
	.hr-beam {
		width: 1.4rem;
		height: 1px;
		background: linear-gradient(90deg, rgb(100 116 139 / 0.25), rgb(100 116 139 / 0.65));
		position: relative;
	}
	.hr-beam::after {
		content: '';
		position: absolute;
		right: -1px;
		top: -2.5px;
		border-left: 5px solid rgb(100 116 139 / 0.65);
		border-top: 3px solid transparent;
		border-bottom: 3px solid transparent;
	}
	.hr-beam-off {
		opacity: 0.35;
	}
	.hr-lane-warn {
		font-size: 0.72rem;
		color: rgb(225 29 72);
	}
	.hr-lane-meta {
		font-size: 0.7rem;
		color: rgb(100 116 139);
	}
	.hr-unsaved {
		font-size: 0.72rem;
		color: rgb(217 119 6);
	}

	/* star-core: the primary is a reactor core with a spinning orbit, beams carry a pulse */
	:global(html.halo-scifi) .hr-core:not(.hr-follow) {
		border-color: var(--scifi-cyan);
		box-shadow:
			0 0 0 1px rgb(8 145 178 / 0.15),
			0 0 18px -6px var(--scifi-glow);
	}
	:global(html.halo-scifi) .hr-core:not(.hr-follow) .hr-orbit {
		display: block;
		position: absolute;
		inset: -3px;
		border-radius: 0.85rem;
		padding: 1px;
		background: conic-gradient(
			from var(--hr-a, 0deg),
			transparent 0turn,
			transparent 0.6turn,
			var(--scifi-cyan) 0.8turn,
			var(--scifi-violet, #8b5cf6) 0.92turn,
			transparent 1turn
		);
		-webkit-mask:
			linear-gradient(#000 0 0) content-box,
			linear-gradient(#000 0 0);
		-webkit-mask-composite: xor;
		mask-composite: exclude;
		animation: hr-orbit 4.5s linear infinite;
		pointer-events: none;
	}
	:global(html.halo-scifi.dark) .hr-node {
		border-color: rgb(94 231 255 / 0.16);
		background: rgb(9 13 28 / 0.65);
	}
	:global(html.halo-scifi.dark) .hr-core:not(.hr-follow) {
		background: radial-gradient(
			120% 140% at 0% 50%,
			rgb(94 231 255 / 0.16),
			rgb(9 13 28 / 0.75) 70%
		);
		color: #e0fbff;
	}
	:global(html.halo-scifi.dark) .hr-beam {
		background: linear-gradient(90deg, rgb(94 231 255 / 0.1), rgb(94 231 255 / 0.75));
		box-shadow: 0 0 6px rgb(94 231 255 / 0.45);
		overflow: visible;
	}
	:global(html.halo-scifi.dark) .hr-beam::after {
		border-left-color: rgb(94 231 255 / 0.8);
	}
	:global(html.halo-scifi.dark) .hr-beam:not(.hr-beam-off)::before {
		content: '';
		position: absolute;
		top: -1px;
		left: 0;
		width: 5px;
		height: 3px;
		border-radius: 3px;
		background: #e0fbff;
		box-shadow: 0 0 6px #5ee7ff;
		animation: hr-pulse 1.8s var(--sf-ease, ease-in-out) infinite;
	}
	@property --hr-a {
		syntax: '<angle>';
		inherits: false;
		initial-value: 0deg;
	}
	@keyframes hr-orbit {
		to {
			--hr-a: 360deg;
		}
	}
	@keyframes hr-pulse {
		from {
			transform: translateX(0);
			opacity: 0;
		}
		30% {
			opacity: 1;
		}
		to {
			transform: translateX(1.2rem);
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		:global(html.halo-scifi) .hr-core .hr-orbit,
		:global(html.halo-scifi.dark) .hr-beam::before {
			animation: none !important;
		}
	}

	/* ---- cards ---- */
	.hr-card-head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 0.75rem;
	}
	.hr-card-title {
		font-size: 0.85rem;
		font-weight: 600;
		color: rgb(30 41 59);
	}
	:global(.dark) .hr-card-title {
		color: rgb(241 245 249);
	}
	.hr-card-hint {
		font-size: 0.72rem;
		color: rgb(100 116 139);
	}
	:global(.dark) .hr-card-hint {
		color: rgb(148 163 184);
	}
	.hr-note {
		font-size: 0.72rem;
		color: rgb(100 116 139);
	}
	.hr-link-text {
		color: var(--scifi-cyan, #0891b2);
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	.hr-sub {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem;
	}
	.hr-sub-label {
		font-size: 0.7rem;
		color: rgb(100 116 139);
		flex: none;
	}
	.hr-select {
		width: min(100%, 22rem);
		padding: 0.3rem 0.5rem;
		font-size: 0.78rem;
	}
	.hr-runner {
		font-size: 0.72rem;
	}
	.hr-num {
		width: 5.5rem;
		padding: 0.25rem 0.5rem;
		font-size: 0.8rem;
	}

	.hr-models {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 19rem), 1fr));
		gap: 0.4rem;
	}
	.hr-model {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		border-radius: 0.6rem;
		border: 1px solid rgb(15 23 42 / 0.08);
		padding: 0.35rem 0.5rem;
	}
	:global(.dark) .hr-model {
		border-color: rgb(255 255 255 / 0.07);
	}
	.hr-nowrap {
		flex: none;
		white-space: nowrap;
	}
	.hr-model-name {
		white-space: nowrap;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.78rem;
		font-weight: 600;
	}
	.hr-tag {
		white-space: nowrap;
		border-radius: 0.4rem;
		padding: 0.05rem 0.35rem;
		font-size: 0.62rem;
		color: rgb(100 116 139);
		background: rgb(100 116 139 / 0.1);
		flex: none;
	}
	.hr-tag-on {
		color: #0e7490;
		background: rgb(8 145 178 / 0.12);
	}
	:global(.dark) .hr-tag-on {
		color: #67e8f9;
	}
	.hr-probe {
		white-space: nowrap;
		font-size: 0.68rem;
		font-variant-numeric: tabular-nums;
		color: rgb(148 163 184);
	}
	.hr-probe[data-state='ok'] {
		color: #059669;
	}
	.hr-probe[data-state='fail'] {
		color: #e11d48;
	}
	.hr-probe[data-state='run'] {
		color: var(--scifi-cyan, #0891b2);
		animation: hr-blink 1.2s ease-in-out infinite;
	}
	@keyframes hr-blink {
		50% {
			opacity: 0.4;
		}
	}
	.hr-probe-error {
		font-size: 0.7rem;
		color: #e11d48;
		word-break: break-all;
	}
	.hr-mini-btn {
		border-radius: 0.5rem;
		border: 1px solid rgb(15 23 42 / 0.12);
		padding: 0.12rem 0.5rem;
		font-size: 0.7rem;
		color: rgb(71 85 105);
		flex: none;
	}
	.hr-mini-btn:hover:not(:disabled) {
		border-color: var(--scifi-cyan, #0891b2);
		color: var(--scifi-cyan, #0891b2);
	}
	.hr-mini-btn:disabled {
		opacity: 0.4;
	}
	:global(.dark) .hr-mini-btn {
		border-color: rgb(255 255 255 / 0.12);
		color: rgb(203 213 225);
	}
	.hr-danger {
		border-color: #e11d48 !important;
		color: #e11d48 !important;
	}

	.hr-aux {
		display: grid;
		gap: 0.15rem;
	}
	.hr-aux-row {
		display: grid;
		grid-template-columns: 11rem 1fr;
		gap: 0.75rem;
		align-items: start;
		padding: 0.45rem 0;
		border-top: 1px solid rgb(15 23 42 / 0.05);
	}
	.hr-aux-row:first-child {
		border-top: 0;
	}
	:global(.dark) .hr-aux-row {
		border-top-color: rgb(255 255 255 / 0.05);
	}
	.hr-aux-name {
		display: flex;
		flex-direction: column;
		font-size: 0.78rem;
		font-weight: 500;
		padding-top: 0.15rem;
	}
	.hr-aux-ctl {
		display: grid;
		gap: 0.3rem;
	}
	.hr-aux-chain {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		flex-wrap: wrap;
	}

	.hr-history {
		display: grid;
		gap: 0.3rem;
	}
	.hr-history-row {
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
		font-size: 0.74rem;
	}
	.hr-history-time {
		font-variant-numeric: tabular-nums;
		color: rgb(100 116 139);
		flex: none;
		width: 5.6rem;
	}
	.hr-history-changes {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-width: 0;
		word-break: break-word;
	}

	/* ---- the save bar ---- */
	.hr-bar {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding-top: 0.75rem;
		border-top: 1px solid transparent;
	}
	.hr-bar-dirty {
		border-top-color: rgb(217 119 6 / 0.25);
	}
	.hr-bar-text {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.74rem;
	}
	.hr-bar-count {
		flex: none;
		font-weight: 600;
		color: rgb(217 119 6);
	}
	.hr-bar-list {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: rgb(100 116 139);
	}
	.hr-save {
		flex: none;
	}

	@media (max-width: 640px) {
		.hr-lane-title {
			width: 100%;
		}
		.hr-aux-row {
			grid-template-columns: 1fr;
			gap: 0.35rem;
		}
		.hr-bar-list {
			display: none;
		}
	}
</style>
