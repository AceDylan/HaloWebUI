<script lang="ts">
	// 并排对比: two answers side by side, each with the question it answered. Opened from an
	// answer's toolbar (its versions) or its 更多 menu (any answer in the chat). Reading only:
	// the chat keeps showing the branch it showed.
	import { Columns2, X } from 'lucide-svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import HaloSelect from '$lib/components/common/HaloSelect.svelte';
	import ContentRenderer from './ContentRenderer.svelte';
	import {
		branchAnswers,
		chatAnswers,
		comparisonPair,
		currentPath,
		type BranchAnswer,
		type CompareHistory,
		type CompareMessage
	} from '$lib/utils/branch-compare';
	import { models } from '$lib/stores';
	import { buildModelIdentityLookup } from '$lib/utils/model-identity';
	import { getModelChatDisplayName } from '$lib/utils/model-display';

	export let history: CompareHistory;
	export let messageId: string;
	export let show = false;

	type Side = 'left' | 'right';

	const branches = branchAnswers(history, messageId);
	const allAnswers = chatAnswers(history);
	const onShownBranch = currentPath(history);
	// Only this question's versions when it has several, else every answer in the chat.
	let includeAll = branches.length < 2;
	let leftId = '';
	let rightId = '';
	[leftId, rightId] = comparisonPair(includeAll ? allAnswers : branches, messageId);

	$: answers = includeAll ? allAnswers : branches;
	$: modelById = buildModelIdentityLookup($models ?? []).byId;
	const modelName = (message: CompareMessage) => {
		const model = modelById.get(message.model ?? '');
		return model ? getModelChatDisplayName(model) : message.modelName || message.model || '回答';
	};
	const excerpt = (text = '', max = 40) => {
		const line = text.replace(/\s+/g, ' ').trim();
		return line.length > max ? `${line.slice(0, max)}…` : line || '（没有文字）';
	};
	const sourcesFor = (message: CompareMessage): any => message.sources ?? message.citations ?? [];

	// The question only goes into the picker when the candidates answer different questions.
	$: samePrompt = new Set(answers.map((a) => a.prompt?.id)).size <= 1;
	$: options = answers.map((a, index) => ({
		value: a.message.id,
		label: `${includeAll ? '' : '版本 '}${index + 1} · ${modelName(a.message)}`,
		description: samePrompt ? undefined : excerpt(a.prompt?.content as string),
		badge: isShown(a.message.id) ? '当前' : undefined
	}));
	$: picked = {
		left: answers.find((a) => a.message.id === leftId),
		right: answers.find((a) => a.message.id === rightId)
	} as Record<Side, BranchAnswer | undefined>;
	// 当前 / 两边不同 tell versions of one question apart; across the whole chat every answer
	// on the shown path is "current" and every question differs, so they say nothing there.
	$: isShown = (id: string) => !includeAll && onShownBranch.has(id);
	$: promptsDiffer = !includeAll && picked.left?.prompt?.id !== picked.right?.prompt?.id;

	const setScope = (all: boolean) => {
		if (all === includeAll) return;
		includeAll = all;
		[leftId, rightId] = comparisonPair(all ? allAnswers : branches, messageId);
	};
	// Picking the other side's answer swaps the two, so both sides never show the same one.
	const choose = (side: Side, id: string) => {
		if (side === 'left') {
			if (id === rightId) rightId = leftId;
			leftId = id;
		} else {
			if (id === leftId) leftId = rightId;
			rightId = id;
		}
	};
	const sides: { side: Side; mark: string }[] = [
		{ side: 'left', mark: 'A' },
		{ side: 'right', mark: 'B' }
	];
	const segButton = (on: boolean) =>
		`flex items-center gap-1.5 font-medium transition-all ${on ? 'bg-white text-gray-900 shadow-[0_1px_3px_rgba(15,23,42,0.08)] dark:bg-gray-800 dark:text-white' : 'text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'}`;
	const panel =
		'flex min-w-0 flex-col overflow-hidden rounded-2xl border border-gray-100/90 bg-white/70 shadow-sm shadow-gray-900/[0.04] dark:border-gray-800/70 dark:bg-gray-900/60 dark:shadow-black/30';
</script>

<Modal bind:show size="xl">
	<div class="flex flex-col" data-halo-branch-comparison>
		<div class="flex items-start gap-3 px-5 pb-3 pt-5">
			<div class="glass-icon-badge shrink-0">
				<Columns2 class="size-[18px]" strokeWidth={1.75} />
			</div>
			<div class="min-w-0 flex-1">
				<h2 class="text-base font-semibold text-gray-900 dark:text-gray-100">并排对比</h2>
				<p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
					只是对照着看，对话里显示的版本不会变。
				</p>
			</div>
			<button type="button" class="halo-icon-btn -mr-1" aria-label="关闭" on:click={() => (show = false)}>
				<X class="size-4" strokeWidth={2} />
			</button>
		</div>

		{#if branches.length > 1 && allAnswers.length > branches.length}
			<div class="px-5 pb-3">
				<div class="halo-seg inline-flex" role="group" aria-label="对比范围">
					<button
						type="button"
						class={segButton(!includeAll)}
						aria-pressed={!includeAll}
						data-compare-scope="branch"
						on:click={() => setScope(false)}
						>这个问题的版本 <span class="tabular-nums text-gray-400">{branches.length}</span></button
					>
					<button
						type="button"
						class={segButton(includeAll)}
						aria-pressed={includeAll}
						data-compare-scope="all"
						on:click={() => setScope(true)}
						>整个对话 <span class="tabular-nums text-gray-400">{allAnswers.length}</span></button
					>
				</div>
			</div>
		{:else if includeAll}
			<p class="px-5 pb-3 text-xs text-gray-500 dark:text-gray-400">
				这条回答没有其他版本，可以和对话里的任意一条回答对比，包括精答和讨论结论。
			</p>
		{/if}

		<div class="grid gap-3 px-5 pb-5 md:grid-cols-2">
			{#each sides as { side, mark } (side)}
				{@const answer = picked[side]}
				<section class={panel} data-halo-compare-side={side}>
					<div
						class="flex items-center gap-2 border-b border-gray-100 px-3 py-2.5 dark:border-white/[0.06]"
					>
						<span
							class="flex size-6 shrink-0 items-center justify-center rounded-lg bg-gray-900 text-2xs font-semibold text-white dark:bg-gray-100 dark:text-gray-900"
							aria-hidden="true">{mark}</span
						>
						<div class="min-w-0 flex-1">
							<HaloSelect
								value={side === 'left' ? leftId : rightId}
								{options}
								className="h-9 w-full max-w-none"
								matchTriggerMinWidth={false}
								on:change={(e) => choose(side, e.detail.value)}
							/>
						</div>
						{#if answer && isShown(answer.message.id)}
							<span class="halo-chip shrink-0" title="对话里正显示这个版本">当前</span>
						{/if}
					</div>
					<div class="max-h-[62vh] overflow-y-auto px-4 py-3">
						{#if answer}
							<div
								class="mb-3 rounded-xl bg-gray-50 px-3 py-2 text-[13px] text-gray-600 dark:bg-white/[0.03] dark:text-gray-300 {promptsDiffer
									? 'border-l-2 border-[var(--halo-ion)]'
									: ''}"
								data-halo-compare-prompt
							>
								<div class="mb-0.5 text-2xs font-medium text-gray-400 dark:text-gray-500">
									{promptsDiffer ? '问题 · 两边不同' : '问题'}
								</div>
								<div class="line-clamp-6 whitespace-pre-wrap">
									{answer.prompt?.content || '（问题没有文字内容）'}
								</div>
							</div>
							{#if answer.message.done === false}
								<p class="mb-2 text-xs text-gray-400">这个回答还在生成</p>
							{/if}
							<ContentRenderer
								id={`compare-${side}-${answer.message.id}`}
								content={answer.message.content ?? ''}
								{history}
								sources={sourcesFor(answer.message)}
								floatingButtons={false}
								forceExpand={true}
								autoOpenArtifacts={false}
							/>
						{/if}
					</div>
					{#if answer}
						<div
							class="flex items-center gap-2 border-t border-gray-100 px-3 py-2 text-2xs text-gray-400 dark:border-white/[0.06] dark:text-gray-500"
						>
							<span class="halo-chip max-w-[60%] truncate">{modelName(answer.message)}</span>
							<span class="tabular-nums">{(answer.message.content ?? '').length} 字</span>
						</div>
					{/if}
				</section>
			{/each}
		</div>
	</div>
</Modal>
