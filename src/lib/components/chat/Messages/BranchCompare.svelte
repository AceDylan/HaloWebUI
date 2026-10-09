<script lang="ts">
	import Modal from '$lib/components/common/Modal.svelte';
	import ContentRenderer from './ContentRenderer.svelte';
	import {
		branchAnswers,
		chatAnswers,
		comparisonPair,
		type CompareHistory
	} from '$lib/utils/branch-compare';
	import { models } from '$lib/stores';
	import { buildModelIdentityLookup } from '$lib/utils/model-identity';
	import { getModelChatDisplayName } from '$lib/utils/model-display';

	export let history: CompareHistory;
	export let messageId: string;
	let show = false;
	let leftId = '';
	let rightId = '';
	let includeAll = false;
	$: branches = branchAnswers(history, messageId);
	$: allAnswers = chatAnswers(history);
	$: answers = includeAll ? allAnswers : branches;
	let columns: { side: 'left' | 'right'; id: string }[] = [];
	$: columns = [
		{ side: 'left', id: leftId },
		{ side: 'right', id: rightId }
	];
	$: modelById = buildModelIdentityLookup($models ?? []).byId;
	const sourcesFor = (message: (typeof answers)[number]['message']): any =>
		message.sources ?? message.citations ?? [];
	const modelName = (message: (typeof answers)[number]['message']) => {
		const model = modelById.get(message.model ?? '');
		return model ? getModelChatDisplayName(model) : message.modelName || message.model || '回答';
	};
	const open = () => {
		includeAll = branches.length < 2;
		[leftId, rightId] = comparisonPair(includeAll ? allAnswers : branches, messageId);
		show = true;
	};
	const toggleScope = () => {
		includeAll = !includeAll;
		[leftId, rightId] = comparisonPair(includeAll ? allAnswers : branches, messageId);
	};
	const choose = (side: 'left' | 'right', id: string) => {
		if (side === 'left') {
			if (id === rightId) rightId = leftId;
			leftId = id;
		} else {
			if (id === leftId) leftId = rightId;
			rightId = id;
		}
	};
</script>

{#if branches.length > 1 || (history.messages[messageId]?.role === 'assistant' && allAnswers.length > 1)}
	<button
		type="button"
		class="mt-1 self-end rounded-lg px-2 py-1 text-xs text-gray-500 hover:bg-black/5 dark:hover:bg-white/5"
		data-halo-branch-compare
		on:click={open}>分支对比</button
	>
{/if}

{#if show}
	<Modal bind:show size="xl">
		<div class="p-4 sm:p-6" data-halo-branch-comparison>
			<div class="mb-4 flex items-center justify-between">
				<h2 class="font-semibold">分支对比</h2>
				<button
					class="rounded-lg px-3 py-1 text-sm hover:bg-black/5 dark:hover:bg-white/5"
					on:click={() => (show = false)}>关闭</button
				>
			</div>
			{#if branches.length > 1 && allAnswers.length > branches.length}
				<button class="mb-3 text-xs text-gray-500 underline" on:click={toggleScope}
					>{includeAll ? '只看本问题的分支' : '对比此对话的其他回答'}</button
				>
			{:else if includeAll}
				<p class="mb-3 text-xs text-gray-500">选择此对话中的两条回答，也可以比较精答与讨论结论。</p>
			{/if}
			<div class="grid gap-4 md:grid-cols-2">
				{#each columns as column}
					{@const answer = answers.find((a) => a.message.id === column.id)}
					<div
						class="min-w-0 rounded-xl border border-gray-200 dark:border-gray-700"
						data-halo-compare-side={column.side}
					>
						<label class="block border-b border-gray-200 p-3 text-sm dark:border-gray-700">
							{column.side === 'left' ? '左侧版本' : '右侧版本'}
							<select
								class="mt-2 block w-full rounded-lg bg-gray-100 p-2 dark:bg-gray-850"
								value={column.id}
								on:change={(e) => choose(column.side, e.currentTarget.value)}
							>
								{#each answers as option, index}<option value={option.message.id}
										>版本 {index + 1} · {modelName(option.message)}</option
									>{/each}
							</select>
						</label>
						<div class="max-h-[65vh] overflow-auto p-4">
							{#if answer}
								<div
									class="mb-4 whitespace-pre-wrap rounded-lg bg-gray-100 p-3 text-sm dark:bg-gray-850"
									data-halo-compare-prompt
								>
									{answer.prompt?.content || '（问题没有文字内容）'}
								</div>
								{#if answer.message.done === false}<p class="mb-2 text-xs text-gray-500">
										这个回答仍在生成
									</p>{/if}
								<ContentRenderer
									id={`compare-${column.side}-${answer.message.id}`}
									content={answer.message.content ?? ''}
									{history}
									sources={sourcesFor(answer.message)}
									floatingButtons={false}
									forceExpand={true}
									autoOpenArtifacts={false}
								/>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>
	</Modal>
{/if}
