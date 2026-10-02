<script lang="ts">
	// 变更: what a team working on a project changed on its own branch — commits per task, files
	// with +/−, a file's diff on demand — and the user's explicit actions: merge into the base
	// branch, push, throw the branch away. Nothing is merged or pushed without a click here.
	import { onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import {
		discardTeamChanges,
		getTeamChangeDiff,
		getTeamChanges,
		mergeTeamChanges,
		pushTeamChanges,
		type TeamChanges
	} from '$lib/apis/teams';
	import { now, timeAgo } from './clock';

	export let teamId: string;
	export let phase: string | null = null;

	let data: TeamChanges | null = null;
	let error = '';
	let loading = false;
	let busy = '';
	let open: Record<string, string | null> = {};
	let loadingDiff: Record<string, boolean> = {};
	let confirmMerge = false;
	let confirmPushBase = false;
	let confirmDiscard = false;
	let timer: ReturnType<typeof setTimeout> | null = null;

	$: finished = phase === 'completed' || phase === 'stopped';
	$: project = data?.project ?? null;
	$: files = data?.files ?? [];
	$: commits = data?.commits ?? [];
	$: merged = !!data?.merged;
	$: pushedBranch = !!project?.pushed?.branch;
	$: pushedBase = !!project?.pushed?.base;

	const load = async () => {
		loading = true;
		try {
			data = await getTeamChanges(localStorage.token, teamId);
			error = '';
		} catch (e) {
			error = `${e?.message ?? e}`;
		} finally {
			loading = false;
		}
		if (timer) clearTimeout(timer);
		// While members work the branch grows: look again now and then (cheap, git only).
		if (!finished) timer = setTimeout(load, 20000);
	};

	$: teamId, phase, load();
	onDestroy(() => timer && clearTimeout(timer));

	const toggle = async (path: string) => {
		if (open[path] !== undefined && open[path] !== null) {
			open = { ...open, [path]: null };
			return;
		}
		loadingDiff = { ...loadingDiff, [path]: true };
		try {
			const res = await getTeamChangeDiff(localStorage.token, teamId, path);
			open = { ...open, [path]: res.diff || '（没有文本差异）' };
		} catch (e) {
			toast.error(`${e?.message ?? e}`);
		} finally {
			loadingDiff = { ...loadingDiff, [path]: false };
		}
	};

	const act = async (name: string, fn: () => Promise<unknown>, ok: string) => {
		busy = name;
		try {
			await fn();
			toast.success(ok);
			await load();
		} catch (e) {
			toast.error(`${e?.message ?? e}`);
		} finally {
			busy = '';
		}
	};

	const merge = () =>
		act(
			'merge',
			() => mergeTeamChanges(localStorage.token, teamId),
			`已合并到 ${project?.base_branch || '原分支'}`
		);
	const pushBranch = () =>
		act(
			'push-branch',
			() => pushTeamChanges(localStorage.token, teamId, 'branch'),
			`已推送 ${project?.branch}`
		);
	const pushBase = () =>
		act(
			'push-base',
			() => pushTeamChanges(localStorage.token, teamId, 'base'),
			`已推送 ${project?.base_branch}`
		);
	const discard = () =>
		act('discard', () => discardTeamChanges(localStorage.token, teamId), '已删除团队分支');

	const lineClass = (line: string) =>
		line.startsWith('+++') || line.startsWith('---')
			? 'text-gray-400'
			: line.startsWith('+')
				? 'bg-emerald-500/10 text-emerald-800 dark:text-emerald-300'
				: line.startsWith('-')
					? 'bg-red-500/10 text-red-800 dark:text-red-300'
					: line.startsWith('@@')
						? 'text-sky-700 dark:text-sky-300'
						: 'text-gray-600 dark:text-gray-300';
</script>

<div class="flex flex-col gap-4" data-team-changes>
	{#if error && !data}
		<div class="text-sm text-red-600" role="alert">{error}</div>
	{:else if !data}
		<div class="tm-shimmer text-sm text-gray-500">正在读团队分支…</div>
	{:else if !project}
		<div class="text-sm text-gray-500">这个团队不是在项目里做的，没有代码改动可看。</div>
	{:else}
		<section class="tm-card flex flex-col gap-3 px-4 py-3.5">
			<div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]">
				<span class="font-semibold text-gray-900 dark:text-gray-50">{project.name}</span>
				<span class="font-mono text-xs text-gray-500">{project.branch}</span>
				<span class="text-xs text-gray-400"
					>基于 {project.base_branch || '分离 HEAD'} · {project.base_sha?.slice(0, 8)}</span
				>
				{#if merged}
					<span
						class="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
						data-changes-merged>已合并到 {project.base_branch}</span
					>
				{/if}
				{#if pushedBranch}
					<span
						class="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] text-sky-700 dark:bg-sky-950 dark:text-sky-300"
						>分支已推送</span
					>
				{/if}
				{#if pushedBase}
					<span
						class="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] text-sky-700 dark:bg-sky-950 dark:text-sky-300"
						>{project.base_branch} 已推送</span
					>
				{/if}
				{#if project.discarded_at}
					<span
						class="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-500 dark:bg-gray-800"
						>分支已删除</span
					>
				{/if}
			</div>
			{#if data.available}
				<div
					class="tm-num flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm"
					data-changes-stats
				>
					<span><b class="font-semibold">{files.length}</b> 个文件</span>
					<span class="text-emerald-700 dark:text-emerald-300">+{data.added ?? 0}</span>
					<span class="text-red-700 dark:text-red-300">−{data.removed ?? 0}</span>
					<span class="text-gray-500">{commits.length} 次提交</span>
					{#if data.base_moved}
						<span class="text-xs text-amber-700 dark:text-amber-300"
							>{project.base_branch} 之后又有 {data.base_moved} 个新提交</span
						>
					{/if}
				</div>
				{#if data.pending?.length}
					<p class="text-xs text-gray-500">
						还有 {data.pending.length} 个文件没提交{finished
							? '，合并或推送前会自动提交'
							: '（成员还在改）'}。
					</p>
				{/if}
				<div class="flex flex-wrap items-center gap-2">
					{#if !finished}
						<span class="text-xs text-gray-500">成员还在干活；团队完成或停止后可以合并、推送。</span
						>
					{:else}
						{#if !merged && project.base_branch}
							<button
								type="button"
								class="tm-btn-primary !py-1.5 !text-xs"
								disabled={!!busy || (!commits.length && !data.pending?.length)}
								on:click={() => (confirmMerge = true)}
								data-changes-merge
								>{busy === 'merge' ? '合并中…' : `合并到 ${project.base_branch}`}</button
							>
						{/if}
						{#if merged && project.base_branch && !pushedBase}
							<button
								type="button"
								class="tm-btn-primary !py-1.5 !text-xs"
								disabled={!!busy}
								on:click={() => (confirmPushBase = true)}
								data-changes-push-base
								>{busy === 'push-base' ? '推送中…' : `推送 ${project.base_branch}`}</button
							>
						{/if}
						<button
							type="button"
							class="tm-btn-ghost !py-1.5 !text-xs"
							disabled={!!busy}
							on:click={pushBranch}
							data-changes-push-branch
							>{busy === 'push-branch'
								? '推送中…'
								: pushedBranch
									? '再次推送团队分支'
									: '推送团队分支'}</button
						>
						<button
							type="button"
							class="tm-btn-ghost !py-1.5 !text-xs !text-red-600 dark:!text-red-400"
							disabled={!!busy}
							on:click={() => (confirmDiscard = true)}
							data-changes-discard>放弃分支</button
						>
					{/if}
					<button
						type="button"
						class="tm-btn-ghost ml-auto !py-1.5 !text-xs"
						disabled={loading}
						on:click={load}>{loading ? '刷新中…' : '刷新'}</button
					>
				</div>
			{/if}
		</section>

		{#if data.available && commits.length}
			<section>
				<div class="tm-eyebrow mb-2">提交</div>
				<ol class="flex flex-col gap-1.5" data-changes-commits>
					{#each commits as c (c.sha)}
						<li class="flex min-w-0 items-center gap-2 text-[13px]">
							{#if c.task_key}
								<span
									class="tm-num shrink-0 rounded-md border px-1.5 text-[11px] text-gray-500 tm-hairline"
									>{c.task_key}</span
								>
							{/if}
							<span
								class="min-w-0 flex-1 truncate text-gray-800 dark:text-gray-100"
								title={c.subject}>{c.subject.replace(/^\[[^\]]+\]\s*/, '')}</span
							>
							{#if c.member}<span class="shrink-0 text-xs text-gray-500">{c.member}</span>{/if}
							<span class="shrink-0 font-mono text-[11px] text-gray-400">{c.sha.slice(0, 7)}</span>
							<span class="shrink-0 text-[11px] text-gray-400">{timeAgo(c.at, $now)}</span>
						</li>
					{/each}
				</ol>
			</section>
		{/if}

		{#if data.available}
			<section>
				<div class="tm-eyebrow mb-2">改动的文件</div>
				{#if files.length === 0}
					<div class="text-sm text-gray-500">还没有改动。</div>
				{:else}
					<ul class="flex flex-col gap-1" data-changes-files>
						{#each files as f (f.path)}
							<li class="tm-card-quiet overflow-hidden">
								<button
									type="button"
									class="flex w-full min-w-0 items-center gap-2 px-3 py-2 text-left text-[13px]"
									aria-expanded={!!open[f.path]}
									on:click={() => toggle(f.path)}
									data-changes-file={f.path}
								>
									<span
										class="min-w-0 flex-1 truncate font-mono text-xs text-gray-800 dark:text-gray-100"
										>{f.path}</span
									>
									{#if f.binary}
										<span class="shrink-0 text-[11px] text-gray-400">二进制</span>
									{:else}
										<span class="tm-num shrink-0 text-xs text-emerald-700 dark:text-emerald-300"
											>+{f.added}</span
										>
										<span class="tm-num shrink-0 text-xs text-red-700 dark:text-red-300"
											>−{f.removed}</span
										>
									{/if}
									{#if loadingDiff[f.path]}<span class="tm-shimmer shrink-0 text-[11px]">…</span
										>{/if}
								</button>
								{#if open[f.path]}
									<pre
										class="tm-scroll max-h-[28rem] overflow-auto border-t px-0 py-1 font-mono text-[11.5px] leading-[1.55] tm-hairline"
										data-changes-diff>{#each open[f.path]?.split('\n') ?? [] as line}<div
												class="whitespace-pre px-3 {lineClass(line)}">{line ||
													' '}</div>{/each}</pre>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			</section>
		{/if}
	{/if}
</div>

<ConfirmDialog
	bind:show={confirmMerge}
	title="合并到 {project?.base_branch}？"
	message="把团队分支 {project?.branch} 合并进 {project?.path} 的 {project?.base_branch}（能快进就快进，否则生成一个合并提交；有冲突会撤回并告诉你）。你的工作区必须没有未提交的改动。不会推送。"
	confirmLabel="合并"
	on:confirm={merge}
/>
<ConfirmDialog
	bind:show={confirmPushBase}
	title="推送 {project?.base_branch}？"
	message="把 {project?.path} 的 {project?.base_branch} 推送到 origin。如果这个仓库推送后会自动构建或部署（比如 HaloWebUI），推送就会触发它。"
	confirmLabel="推送"
	on:confirm={pushBase}
/>
<ConfirmDialog
	bind:show={confirmDiscard}
	title="放弃团队分支？"
	message="删除团队的 worktree 和分支 {project?.branch}（没合并、没推送的改动会丢失）。结论报告保留。"
	confirmLabel="放弃分支"
	on:confirm={discard}
/>
