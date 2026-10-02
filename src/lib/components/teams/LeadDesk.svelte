<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { adjustTeam, decideTeamChange, type TeamChangeRequest } from '$lib/apis/teams';
	import TeamAvatar from './TeamAvatar.svelte';
	import { runnerLabel } from './model';

	/**
	 * 对负责人说: the user talks to the lead while the team works (or after it finished). The lead
	 * answers and, when the request calls for it, proposes a plan change — shown here as a card.
	 * Nothing on the board changes until the user applies it.
	 */
	export let teamId: string;
	export let change: TeamChangeRequest | null = null;
	export let phase = 'running';

	const dispatch = createEventDispatcher();
	let text = '';
	let sending = false;
	let deciding: '' | 'apply' | 'discard' = '';
	let input: HTMLTextAreaElement | null = null;

	$: status = change?.status ?? null;
	$: proposal = change?.proposal ?? null;
	$: thinking = status === 'thinking';
	$: completed = phase === 'completed';
	$: placeholder = completed
		? '团队做完了。还要补什么、改什么，对负责人说…'
		: '对负责人说：追加需求、调整分工、改某个任务的做法…';
	$: changeCount = proposal
		? proposal.add_members.length +
			proposal.add_tasks.length +
			proposal.edit_tasks.length +
			proposal.cancel_tasks.length
		: 0;

	const grow = () => {
		if (!input) return;
		input.style.height = 'auto';
		input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
	};

	const send = async () => {
		const body = text.trim();
		if (!body || sending || thinking) return;
		sending = true;
		try {
			await adjustTeam(localStorage.token, teamId, body);
			text = '';
			if (input) input.style.height = '';
			dispatch('changed');
		} catch (error) {
			toast.error(`${error?.message ?? error}`);
		} finally {
			sending = false;
		}
	};

	const onKey = (e: KeyboardEvent) => {
		if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
			e.preventDefault();
			send();
		}
	};

	const decide = async (action: 'apply' | 'discard') => {
		if (!change || deciding) return;
		deciding = action;
		try {
			const res = await decideTeamChange(localStorage.token, teamId, change.id, action);
			if (action === 'apply') {
				toast.success(res.reopened ? '变更已应用，团队重新开工' : '变更已应用，新任务会按依赖开始');
			}
			dispatch('changed');
		} catch (error) {
			toast.error(`${error?.message ?? error}`);
			dispatch('changed');
		} finally {
			deciding = '';
		}
	};
</script>

<section class="flex flex-col gap-2" aria-label="对负责人说" data-lead-desk>
	{#if change && status && ['thinking', 'ready', 'answered', 'failed'].includes(status)}
		<div
			class="proposal tm-card tm-rise p-3.5 sm:p-4 {status === 'ready' ? 'is-ready' : ''}"
			data-lead-proposal
			data-change-status={status}
			role={status === 'thinking' ? 'status' : undefined}
		>
			<div class="flex items-start gap-3">
				<div class="shrink-0 pt-0.5">
					<TeamAvatar
						kind="lead"
						size={32}
						status={thinking ? 'running' : status === 'ready' ? 'waiting_user' : 'done'}
					/>
				</div>
				<div class="min-w-0 flex-1">
					<div
						class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs text-gray-500 dark:text-gray-400"
					>
						<span class="font-semibold text-gray-900 dark:text-gray-50">负责人</span>
						{#if thinking}
							<span class="tm-shimmer">在看团队现在的状态，想怎么改…</span>
						{:else if status === 'ready'}
							<span>提出了计划变更，等你确认</span>
						{:else if status === 'failed'}
							<span class="text-red-600 dark:text-red-300">没能给出调整</span>
						{:else}
							<span>回复你</span>
						{/if}
						{#if change.via === 'telegram'}<span class="text-sky-600 dark:text-sky-300"
								>· 来自 Telegram</span
							>{/if}
						{#if change.model}<span class="ml-auto font-mono text-[11px] text-gray-400"
								>{change.model}</span
							>{/if}
					</div>
					<p
						class="said mt-1.5 line-clamp-3 whitespace-pre-wrap break-words text-xs text-gray-500 dark:text-gray-400"
						title={change.text}
					>
						{change.source === 'acceptance' ? '补上验收缺口：' : '你说：'}{change.text}
					</p>

					{#if status === 'failed'}
						<p class="mt-2 text-[13px] text-red-700 dark:text-red-300" role="alert">
							{change.error ?? '原因未知'}
						</p>
					{:else if proposal}
						<p
							class="mt-2 whitespace-pre-wrap break-words text-[13.5px] leading-relaxed text-gray-800 dark:text-gray-100"
							data-lead-reply
						>
							{proposal.reply}
						</p>
					{/if}

					{#if status === 'ready' && proposal}
						<ul class="mt-3 flex flex-col gap-1.5" aria-label="计划变更 {changeCount} 项">
							{#each proposal.add_members as m}
								<li class="item" data-change-item="member">
									<span class="tag tag-add">新成员</span>
									<span class="min-w-0 flex-1">
										<span class="font-medium text-gray-900 dark:text-gray-50">{m.name}</span>
										<span class="text-gray-500"> · {m.role}</span>
										<span class="text-gray-400"> · {runnerLabel(m.runner ?? m.executor)}</span>
									</span>
								</li>
							{/each}
							{#each proposal.add_tasks as t}
								<li class="item" data-change-item="task">
									<span class="tag tag-add">新任务</span>
									<span class="min-w-0 flex-1">
										<span class="font-mono text-gray-400">#{t.key}</span>
										<span class="font-medium text-gray-900 dark:text-gray-50">{t.title}</span>
										<span class="text-gray-500"> → {t.member}</span>
										{#if t.depends_on.length}<span class="whitespace-nowrap text-gray-400">
												· 等 {t.depends_on.map((d) => `#${d}`).join('、')}</span
											>{/if}
										<span class="desc">{t.description}</span>
									</span>
								</li>
							{/each}
							{#each proposal.edit_tasks as t}
								<li class="item" data-change-item="edit">
									<span class="tag tag-edit">{t.retry ? '改写重试' : '改写'}</span>
									<span class="min-w-0 flex-1">
										<span class="font-mono text-gray-400">#{t.key}</span>
										<span class="font-medium text-gray-900 dark:text-gray-50">{t.title}</span>
										<span class="desc">{t.description}</span>
									</span>
								</li>
							{/each}
							{#each proposal.cancel_tasks as t}
								<li class="item" data-change-item="cancel">
									<span class="tag tag-cancel">取消</span>
									<span class="min-w-0 flex-1">
										<span class="font-mono text-gray-400">#{t.key}</span>
										<span
											class="text-gray-600 line-through decoration-gray-400/70 dark:text-gray-300"
											>{t.title}</span
										>
									</span>
								</li>
							{/each}
						</ul>
						{#if proposal.notes.length || completed}
							<ul class="mt-2.5 flex flex-col gap-1 text-xs text-amber-800 dark:text-amber-200">
								{#if completed}<li>团队已经做完：应用后重新开工，做完会重写结论。</li>{/if}
								{#each proposal.notes as note}<li>注意：{note}</li>{/each}
							</ul>
						{/if}
					{/if}

					{#if !thinking}
						<div class="mt-3 flex flex-wrap items-center gap-2">
							{#if status === 'ready'}
								<button
									type="button"
									class="tm-btn-primary !py-1.5 !text-xs"
									disabled={!!deciding}
									on:click={() => decide('apply')}
									data-change-apply
									>{deciding === 'apply' ? '正在应用…' : `应用变更（${changeCount} 项）`}</button
								>
								<button
									type="button"
									class="tm-btn-ghost"
									disabled={!!deciding}
									on:click={() => decide('discard')}
									data-change-discard>放弃</button
								>
								<span class="text-[11px] text-gray-400">想再改？直接在下面接着说</span>
							{:else}
								<button
									type="button"
									class="tm-btn-ghost"
									disabled={!!deciding}
									on:click={() => decide('discard')}
									data-change-dismiss>知道了</button
								>
							{/if}
						</div>
					{/if}
				</div>
			</div>
		</div>
	{/if}

	<form
		class="compose tm-card-quiet flex items-end gap-2 p-1.5 pl-2.5"
		on:submit|preventDefault={send}
		data-lead-compose
	>
		<div class="shrink-0 pb-1.5" aria-hidden="true">
			<TeamAvatar kind="lead" size={22} />
		</div>
		<label class="sr-only" for="lead-say-{teamId}">对负责人说</label>
		<textarea
			id="lead-say-{teamId}"
			bind:this={input}
			bind:value={text}
			on:input={grow}
			on:keydown={onKey}
			rows="1"
			maxlength="2000"
			{placeholder}
			disabled={thinking}
			class="min-h-[2.25rem] min-w-0 flex-1 resize-none bg-transparent py-2 text-sm leading-5 text-gray-900 outline-none placeholder:text-gray-400 disabled:opacity-60 dark:text-gray-100"
		/>
		<button
			type="submit"
			class="tm-btn-primary mb-0.5 shrink-0 !px-3 !py-1.5 !text-xs"
			disabled={!text.trim() || sending || thinking}
			>{sending ? '发送中…' : thinking ? '负责人在想' : '发送'}</button
		>
	</form>
</section>

<style>
	.proposal.is-ready {
		border-color: hsl(var(--tm-violet) / 0.32);
		background: radial-gradient(120% 140% at 0% 0%, hsl(var(--tm-violet) / 0.08), transparent 55%),
			hsl(var(--tm-surface));
	}
	.said {
		border-left: 2px solid hsl(var(--tm-line-strong));
		padding-left: 0.5rem;
	}
	.item {
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
		font-size: 0.8125rem;
		line-height: 1.35rem;
		min-width: 0;
	}
	.desc {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		font-size: 0.75rem;
		line-height: 1.1rem;
		color: hsl(var(--tm-muted));
		overflow-wrap: anywhere;
	}
	.tag {
		flex-shrink: 0;
		margin-top: 0.1rem;
		border-radius: 0.375rem;
		padding: 0 0.375rem;
		font-size: 0.6875rem;
		font-weight: 600;
		line-height: 1.15rem;
		white-space: nowrap;
	}
	.tag-add {
		color: hsl(var(--tm-ok));
		background: hsl(var(--tm-ok) / 0.12);
	}
	.tag-edit {
		color: hsl(var(--tm-accent));
		background: hsl(var(--tm-accent) / 0.12);
	}
	.tag-cancel {
		color: hsl(var(--tm-bad));
		background: hsl(var(--tm-bad) / 0.1);
	}
	.compose:focus-within {
		border-color: hsl(var(--tm-accent) / 0.45);
		box-shadow: 0 0 0 3px hsl(var(--tm-accent) / 0.12);
	}
</style>
