<script lang="ts">
	import './teams.css';

	/**
	 * Under a team's result in its chat: the parts of it that live on the 协作台 — the result page,
	 * the files the team produced, the record of how each task went — and the team itself. Each
	 * opens in place (the chat is one step back).
	 */
	export let teamId: string;
	/** The way to the team itself too (off where the team is one click away already). */
	export let team = true;

	$: page = `/teams/${teamId}/conclusion`;
	$: links = [
		{ key: 'page', href: page, label: '结果页', hint: '目录、复制、下载 .md、重写' },
		{ key: 'files', href: `${page}#files`, label: '产出文件', hint: '团队工作目录里的图片和文件' },
		{ key: 'process', href: `${page}#process`, label: '过程记录', hint: '每个任务交付时的原始结果' }
	];
</script>

<nav
	class="not-prose {team ? 'mt-3' : ''} flex flex-wrap items-center gap-1.5"
	aria-label="在协作台查看"
	data-teams-ui
	data-team-result-bar={teamId}
>
	{#each links as link (link.key)}
		<a href={link.href} class="tm-btn-ghost" title={link.hint} data-team-result-link={link.key}>
			{#if link.key === 'page'}
				<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
					><path
						d="M4 1.8h5.2L12.5 5v9.2H4V1.8Z"
						stroke="currentColor"
						stroke-width="1.4"
						stroke-linejoin="round"
					/><path
						d="M6 8h4.5M6 10.8h3"
						stroke="currentColor"
						stroke-width="1.4"
						stroke-linecap="round"
					/></svg
				>
			{:else if link.key === 'files'}
				<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
					><path
						d="M1.8 4.2a1.2 1.2 0 0 1 1.2-1.2h3.1l1.4 1.6H13a1.2 1.2 0 0 1 1.2 1.2v6.2a1.2 1.2 0 0 1-1.2 1.2H3a1.2 1.2 0 0 1-1.2-1.2V4.2Z"
						stroke="currentColor"
						stroke-width="1.4"
						stroke-linejoin="round"
					/></svg
				>
			{:else}
				<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
					><path
						d="M2.5 4h1.6M2.5 8h1.6M2.5 12h1.6M6.5 4h7M6.5 8h7M6.5 12h5"
						stroke="currentColor"
						stroke-width="1.4"
						stroke-linecap="round"
					/></svg
				>
			{/if}
			{link.label}
		</a>
	{/each}
	{#if team}
		<a
			href="/teams/{teamId}"
			class="ml-auto inline-flex items-center gap-1 rounded-lg px-1.5 py-1 text-xs text-gray-500 transition hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
			title="成员、任务板、通讯记录和回放"
			data-team-result-link="team"
			>打开协作台<svg class="size-3" viewBox="0 0 16 16" fill="none" aria-hidden="true"
				><path
					d="M6 3.5 10.5 8 6 12.5"
					stroke="currentColor"
					stroke-width="1.6"
					stroke-linecap="round"
					stroke-linejoin="round"
				/></svg
			></a
		>
	{/if}
</nav>
