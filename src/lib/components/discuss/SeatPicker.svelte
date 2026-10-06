<script lang="ts">
	import { slide } from 'svelte/transition';

	import SeatAvatar from './SeatAvatar.svelte';
	import { MAX_SEATS, MIN_SEATS, modelRef, seatHue, type ModeSpec, type SeatDraft } from './model';
	import { searchTemplates, type LibraryEntry, type TemplateEntry } from '$lib/apis/assistant-library';

	type Model = { id: string; name?: string; selection_id?: string; info?: { base_model_id?: string | null } };

	/** The seats of a new discussion: who takes part, each with an optional role, and where its
	 * assistant comes from (matched to the question, picked, or none). */
	export let seats: SeatDraft[] = [];
	export let choices: Model[] = [];
	export let mode: ModeSpec;
	/** 自动匹配助手: seats without their own choice get one matched to each question. */
	export let autoMatch = true;
	/** The user's assistants (hidden ones too) a seat can be given. */
	export let library: LibraryEntry[] = [];

	const DUTY_MAX = 120;
	let pickQuery = '';
	let templateHits: TemplateEntry[] = [];
	let searchTimer: ReturnType<typeof setTimeout> | null = null;

	let editing: number | null = null;
	let adding = false;

	const GENERIC_ROLES = ['怀疑派', '务实派', '领域专家', '用户视角', '风险官', '创新派'];
	$: presets = [...new Set([...mode.roles.slice(0, 3), ...GENERIC_ROLES])];

	const nameOf = (ref: string) => {
		const m = choices.find((c) => modelRef(c) === ref || c.id === ref);
		return m?.name ?? ref;
	};
	// A seat left without a role gets the format's role for its place (the backend fills the
	// same); read as mode.roles[i] in the markup so that switching formats repaints it.

	const add = (model: Model) => {
		if (seats.length >= MAX_SEATS) return;
		seats = [...seats, { model: modelRef(model), role: '' }];
		adding = false;
	};
	const remove = (index: number) => {
		if (seats.length <= MIN_SEATS) return;
		seats = seats.filter((_, i) => i !== index);
		editing = null;
	};
	const setRole = (index: number, role: string) => {
		seats = seats.map((s, i) => (i === index ? { ...s, role: role.slice(0, 40) } : s));
	};
	const setModel = (index: number, model: string) => {
		seats = seats.map((s, i) => (i === index ? { ...s, model } : s));
	};
	const update = (index: number, patch: Partial<SeatDraft>) => {
		seats = seats.map((s, i) => (i === index ? { ...s, ...patch } : s));
	};

	// (reactive: the markup repaints when 自动匹配 or the models change)
	/** A seat whose model is itself an assistant keeps that assistant. */
	$: isAssistantModel = (ref: string) =>
		!!choices.find((c) => modelRef(c) === ref || c.id === ref)?.info?.base_model_id;
	$: assistOf = (seat: SeatDraft) =>
		isAssistantModel(seat.model)
			? 'self'
			: seat.assist === 'pick' && seat.assistant
				? 'pick'
				: seat.assist === 'generic' || !autoMatch
					? 'generic'
					: 'auto';

	const setAssist = (index: number, assist: 'auto' | 'pick' | 'generic') => {
		update(index, assist === 'pick' ? { assist } : { assist, assistant: undefined, assistantName: undefined });
		pickQuery = '';
		templateHits = [];
	};
	const pick = (index: number, ref: string, name: string) => {
		update(index, { assist: 'pick', assistant: ref, assistantName: name });
		pickQuery = '';
		templateHits = [];
	};

	$: q = pickQuery.trim().toLowerCase();
	$: libraryHits = (q
		? library.filter((a) => `${a.name} ${a.domain} ${a.description}`.toLowerCase().includes(q))
		: library
	).slice(0, 12);
	const findTemplates = (text: string) => {
		if (searchTimer) clearTimeout(searchTimer);
		if (!text.trim()) {
			templateHits = [];
			return;
		}
		searchTimer = setTimeout(async () => {
			try {
				templateHits = await searchTemplates(localStorage.token, { q: text, limit: 8 });
			} catch {
				templateHits = [];
			}
		}, 250);
	};
</script>

<div class="flex flex-col gap-2" data-discuss-seats>
	<div class="flex flex-wrap items-center gap-1.5">
		{#each seats as seat, i (i)}
			{@const role = seat.role || mode.roles[i] || ''}
			<button
				type="button"
				class="dc-chip !py-1 !pr-2 !pl-1"
				data-on={editing === i}
				aria-expanded={editing === i}
				on:click={() => {
					editing = editing === i ? null : i;
					adding = false;
				}}
				title="点按设置角色或换模型"
				data-discuss-seat={i}
			>
				<SeatAvatar model={seat.model} name={nameOf(seat.model)} hue={seatHue(i)} state="done" size={18} />
				<span class="max-w-[9rem] truncate font-medium text-gray-800 dark:text-gray-100">{nameOf(seat.model)}</span>
				{#if role}
					<span class="max-w-[6rem] truncate" style="color: hsl({seatHue(i)} 70% 50%)">{role}</span>
				{/if}
				{#if assistOf(seat) === 'pick'}
					<span class="max-w-[7rem] truncate text-[11px] text-gray-500 dark:text-gray-400" data-discuss-seat-assistant
						>· {seat.assistantName || '指定助手'}</span
					>
				{:else if assistOf(seat) === 'auto'}
					<span class="text-[11px] text-gray-400 dark:text-gray-500" data-discuss-seat-assistant>· 自动匹配</span>
				{/if}
			</button>
		{/each}
		{#if seats.length < MAX_SEATS}
			<button
				type="button"
				class="dc-chip border-dashed"
				aria-expanded={adding}
				on:click={() => {
					adding = !adding;
					editing = null;
				}}
				data-discuss-add-seat
			>
				<svg class="size-3" viewBox="0 0 12 12" fill="none" aria-hidden="true"
					><path d="M6 2v8M2 6h8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" /></svg
				>
				添加席位
			</button>
		{/if}
		<span class="text-[11px] text-gray-400 dark:text-gray-500">{seats.length}/{MAX_SEATS} 位</span>
	</div>

	{#if adding}
		<div class="flex flex-wrap gap-1.5 rounded-xl bg-gray-500/5 p-2" transition:slide={{ duration: 160 }} data-discuss-add-list>
			{#each choices as model (model.id)}
				<button type="button" class="dc-chip" on:click={() => add(model)}>
					<SeatAvatar model={modelRef(model)} name={model.name ?? model.id} hue={seatHue(seats.length)} size={16} />
					{model.name ?? model.id}
				</button>
			{:else}
				<span class="px-1 text-xs text-gray-500">没有可用的文本模型</span>
			{/each}
		</div>
	{/if}

	{#if editing !== null && seats[editing]}
		{@const i = editing}
		<div
			class="flex flex-col gap-2 rounded-xl bg-gray-500/5 p-2.5"
			transition:slide={{ duration: 160 }}
			data-discuss-seat-editor
		>
			<div class="flex flex-wrap items-center gap-2">
				<label class="flex min-w-0 items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
					模型
					<select
						class="dc-select"
						value={seats[i].model}
						on:change={(e) => setModel(i, e.currentTarget.value)}
					>
						{#each choices as model (model.id)}
							<option value={modelRef(model)}>{model.name ?? model.id}</option>
						{/each}
					</select>
				</label>
				<label class="flex min-w-0 flex-1 items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
					角色
					<input
						class="min-w-0 flex-1 rounded-lg border border-gray-200/70 bg-transparent px-2 py-1 text-xs text-gray-800 outline-none focus:border-blue-400/60 dark:border-gray-700/60 dark:text-gray-100"
						placeholder={mode.roles[i] || '可选，比如：怀疑派、产品经理'}
						maxlength="40"
						value={seats[i].role}
						on:input={(e) => setRole(i, e.currentTarget.value)}
					/>
				</label>
				<button
					type="button"
					class="rounded-lg px-2 py-1 text-xs text-gray-500 hover:bg-red-500/10 hover:text-red-600 disabled:opacity-40 dark:text-gray-400"
					disabled={seats.length <= MIN_SEATS}
					title={seats.length <= MIN_SEATS ? `至少要 ${MIN_SEATS} 位` : ''}
					on:click={() => remove(i)}>移除</button
				>
			</div>
			<div class="flex flex-wrap gap-1">
				{#each presets as preset}
					<button
						type="button"
						class="dc-chip !px-2 !py-0.5 !text-[11px]"
						aria-pressed={seats[i].role === preset}
						on:click={() => setRole(i, seats[i].role === preset ? '' : preset)}>{preset}</button
					>
				{/each}
			</div>
			<div class="flex flex-col gap-1.5 border-t border-gray-500/10 pt-2" data-discuss-seat-assist>
				{#if assistOf(seats[i]) === 'self'}
					<span class="text-[11px] text-gray-500 dark:text-gray-400">这个模型本身就是助手，按它自己的设定发言</span>
				{:else}
					<div class="flex flex-wrap items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
						助手
						{#each [['auto', '自动匹配'], ['pick', '指定助手'], ['generic', '通用角色']] as [value, label]}
							<button
								type="button"
								class="dc-chip !px-2 !py-0.5 !text-[11px]"
								aria-pressed={assistOf(seats[i]) === value || (value === 'pick' && seats[i].assist === 'pick')}
								disabled={value === 'auto' && !autoMatch}
								title={value === 'auto' && !autoMatch ? '先打开「自动匹配助手」' : ''}
								on:click={() => setAssist(i, value)}
								data-discuss-assist={value}>{label}</button
							>
						{/each}
						{#if seats[i].assist === 'pick' && seats[i].assistant}
							<span class="truncate text-gray-800 dark:text-gray-100">已选：{seats[i].assistantName || seats[i].assistant}</span>
						{/if}
					</div>
					{#if seats[i].assist === 'pick'}
						<input
							class="rounded-lg border border-gray-200/70 bg-transparent px-2 py-1 text-xs text-gray-800 outline-none focus:border-blue-400/60 dark:border-gray-700/60 dark:text-gray-100"
							placeholder="搜索我的助手或内置模板"
							bind:value={pickQuery}
							on:input={(e) => findTemplates(e.currentTarget.value)}
							data-discuss-assist-search
						/>
						<div class="flex max-h-40 flex-wrap gap-1 overflow-y-auto">
							{#each libraryHits as a (a.ref)}
								<button
									type="button"
									class="dc-chip !px-2 !py-0.5 !text-[11px]"
									aria-pressed={seats[i].assistant === a.ref}
									title={a.description}
									on:click={() => pick(i, a.ref, a.name)}
									data-discuss-assist-option={a.ref}>{a.emoji || '✦'} {a.name}</button
								>
							{/each}
							{#each templateHits as t (t.ref)}
								<button
									type="button"
									class="dc-chip !px-2 !py-0.5 !text-[11px]"
									aria-pressed={seats[i].assistant === t.ref}
									title={t.description}
									on:click={() => pick(i, t.ref, t.name)}
									data-discuss-assist-option={t.ref}>{t.emoji || '✦'} {t.name}<span class="text-gray-400">· 模板</span></button
								>
							{/each}
							{#if !libraryHits.length && !templateHits.length}
								<span class="px-1 text-[11px] text-gray-500">{q ? '没找到，换个词试试' : '还没有自己的助手，输入关键词搜索内置模板'}</span>
							{/if}
						</div>
					{/if}
				{/if}
				<label class="flex min-w-0 items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
					职责
					<input
						class="min-w-0 flex-1 rounded-lg border border-gray-200/70 bg-transparent px-2 py-1 text-xs text-gray-800 outline-none focus:border-blue-400/60 dark:border-gray-700/60 dark:text-gray-100"
						placeholder="可选，这次讨论里负责什么；留空时自动匹配会给出"
						maxlength={DUTY_MAX}
						value={seats[i].duty ?? ''}
						on:input={(e) => update(i, { duty: e.currentTarget.value.slice(0, DUTY_MAX) })}
						data-discuss-seat-duty
					/>
				</label>
			</div>
		</div>
	{/if}
</div>
