<script lang="ts">
	import { slide } from 'svelte/transition';

	import SeatAvatar from './SeatAvatar.svelte';
	import { MAX_SEATS, MIN_SEATS, modelRef, seatHue, type ModeSpec, type SeatDraft } from './model';

	type Model = { id: string; name?: string; selection_id?: string };

	/** The seats of a new discussion: who takes part, each with an optional role. */
	export let seats: SeatDraft[] = [];
	export let choices: Model[] = [];
	export let mode: ModeSpec;

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
						class="rounded-lg border border-gray-200/70 bg-transparent px-2 py-1 text-xs text-gray-800 dark:border-gray-700/60 dark:text-gray-100"
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
		</div>
	{/if}
</div>
