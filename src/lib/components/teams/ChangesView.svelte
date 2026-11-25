<script lang="ts">
	// 变更与部署: what a team working on a project changed on its own branch — commits per task,
	// files with +/−, a file's diff on demand — plus one-click & automatic merge → push → CI →
	// deploy → cleanup, and granular manual actions.
	import { onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import {
		deployTeamChanges,
		discardTeamChanges,
		getTeamChangeDiff,
		getTeamChanges,
		mergeTeamChanges,
		pushTeamChanges,
		setTeamAutoDeploy,
		type TeamChanges
	} from '$lib/apis/teams';
	import { elapsed, now, timeAgo } from './clock';

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
	let confirmDeploy = false;
	let deployCleanup = true;
	let deployReview = false;
	let showDeployLog = false;
	let timer: ReturnType<typeof setTimeout> | null = null;

	$: finished = phase === 'completed' || phase === 'stopped';
	$: project = data?.project ?? null;
	$: files = data?.files ?? [];
	$: commits = data?.commits ?? [];
	$: merged = !!data?.merged;
	$: pushedBranch = !!project?.pushed?.branch;
	$: pushedBase = !!project?.pushed?.base;
	$: deploy = data?.deploy ?? null;
	$: deployProfile = data?.deploy_profile ?? null;
	$: deployRunning = deploy?.status === 'running';
	$: autoDeploy = !!data?.auto_deploy;
	$: hasChanges = commits.length > 0 || (data?.pending?.length ?? 0) > 0;
	$: canShip =
		finished &&
		!deployRunning &&
		!!project?.base_branch &&
		((!!data?.available && hasChanges) || (!!project?.merged_at && deploy?.status === 'failed'));

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
		// Poll briskly while pushing/deploying; gently while members are still editing.
		if (data?.deploy?.status === 'running') {
			timer = setTimeout(load, 3000);
		} else if (!finished) {
			timer = setTimeout(load, 20000);
		}
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
	const startDeploy = () =>
		act(
			'deploy',
			() => deployTeamChanges(localStorage.token, teamId, deployCleanup, deployReview),
			'已启动推送部署流水线'
		);
	const toggleAutoDeploy = () =>
		act(
			'auto-deploy',
			() => setTeamAutoDeploy(localStorage.token, teamId, !autoDeploy),
			!autoDeploy ? '已开启完成后自动推送部署' : '已关闭自动推送部署'
		);

	const stepIcon = (status: string) =>
		({
			done: '✓',
			running: '…',
			failed: '✕',
			skipped: '–',
			pending: '·'
		})[status] ?? '·';

	const stepTone = (status: string) =>
		status === 'done'
			? 'text-emerald-700 dark:text-emerald-300'
			: status === 'running'
				? 'text-sky-700 dark:text-sky-300 font-medium'
				: status === 'failed'
					? 'text-red-700 dark:text-red-300 font-medium'
					: 'text-gray-400 dark:text-gray-500';

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
						data-changes-discarded
						>{project.auto_cleaned
							? '没有改动，分支已自动清理'
							: project.shipped_cleaned
								? '已发布并清理分支'
								: '分支已删除'}</span
					>
				{/if}
			</div>
			{#if project.auto_cleaned}
				<p class="text-xs text-gray-500">
					团队没有改动项目里的任何文件，团队分支和 worktree 已经自动删掉；结论保留。再对负责人追加工作，会从
					{project.base_branch || '原来的提交'} 重新开一个分支。
				</p>
			{:else if project.shipped_cleaned}
				<p class="text-xs text-gray-500">
					代码已合并、推送并完成发布，团队分支与 worktree 已自动清理；结论报告保留。
				</p>
			{/if}

			{#if deployProfile || deploy}
				<div
					class="tm-card-quiet flex flex-col gap-2.5 px-3 py-2.5 text-xs"
					data-changes-deploy-panel
				>
					<div class="flex flex-wrap items-center gap-x-2 gap-y-1.5">
						<span class="font-semibold text-gray-800 dark:text-gray-100">推送与部署</span>
						{#if deployProfile?.label}
							<span class="min-w-0 flex-1 truncate text-gray-500 dark:text-gray-400" title={deployProfile.label}
								>{deployProfile.label}</span
							>
						{/if}
						{#if !project.discarded_at}
							<button
								type="button"
								class="rounded-full border px-2 py-0.5 text-[11px] transition tm-hairline {autoDeploy
									? 'border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300'
									: 'text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'}"
								disabled={!!busy || deployRunning}
								aria-pressed={autoDeploy}
								on:click={toggleAutoDeploy}
								title="开启后，任务完成且验收通过时自动合并、推送、部署并清理分支"
								data-changes-auto-deploy>{autoDeploy ? '自动部署：开' : '自动部署：关'}</button
							>
						{/if}
					</div>

					{#if deploy}
						<div class="flex flex-wrap items-center gap-x-2.5 gap-y-1" data-deploy-status={deploy.status}>
							{#if deploy.status === 'running'}
								<span class="tm-shimmer font-medium text-sky-700 dark:text-sky-300"
									>正在执行推送部署…</span
								>
								{#if deploy.started_at}
									<span class="tm-num text-gray-400">{elapsed($now - deploy.started_at)}</span>
								{/if}
							{:else if deploy.status === 'succeeded'}
								<span class="font-medium text-emerald-700 dark:text-emerald-300"
									>推送与部署已完成</span
								>
								{#if deploy.sha}
									<span class="font-mono text-[11px] text-gray-500">{deploy.sha.slice(0, 8)}</span>
								{/if}
								{#if deploy.seconds}
									<span class="tm-num text-gray-400">用时 {elapsed(deploy.seconds)}</span>
								{/if}
							{:else if deploy.status === 'skipped'}
								<span class="font-medium text-amber-700 dark:text-amber-300">已跳过自动部署</span>
							{:else if deploy.status === 'failed'}
								<span class="font-medium text-red-700 dark:text-red-300">推送部署失败</span>
								{#if deploy.seconds}
									<span class="tm-num text-gray-400">用时 {elapsed(deploy.seconds)}</span>
								{/if}
							{/if}
							{#if deploy.ci_url}
								<a
									href={deploy.ci_url}
									target="_blank"
									rel="noopener noreferrer"
									class="ml-auto text-sky-700 hover:underline dark:text-sky-300"
									data-changes-ci-link>查看 CI 运行 ↗</a
								>
							{/if}
						</div>

						{#if deploy.steps?.length}
							<ol class="flex flex-col gap-1" data-deploy-steps>
								{#each deploy.steps as s (s.key)}
									<li class="flex min-w-0 items-baseline gap-2 {stepTone(s.status)}">
										<span class="w-3 shrink-0 text-center font-mono">{stepIcon(s.status)}</span>
										<span class="shrink-0">{s.label}</span>
										{#if s.detail}
											<span class="min-w-0 truncate text-[11px] opacity-80" title={s.detail}
												>{s.detail}</span
											>
										{/if}
									</li>
								{/each}
							</ol>
						{/if}

						{#if deploy.error}
							<div
								class="rounded-lg border border-red-500/20 bg-red-500/[0.06] px-2.5 py-1.5 text-[11.5px] leading-relaxed text-red-700 dark:text-red-300"
								role="alert"
								data-deploy-error
							>
								{deploy.error}
							</div>
						{/if}
						{#if deploy.note}
							<p class="text-[11px] text-sky-700 dark:text-sky-300">{deploy.note}</p>
						{/if}
						{#if deploy.log}
							<div>
								<button
									type="button"
									class="text-[11px] text-sky-700 hover:underline dark:text-sky-300"
									on:click={() => (showDeployLog = !showDeployLog)}
									data-deploy-log-toggle>{showDeployLog ? '收起部署输出' : '查看部署输出'}</button
								>
								{#if showDeployLog}
									<pre
										class="tm-scroll mt-1.5 max-h-56 overflow-auto rounded-lg border bg-black/[0.03] p-2 font-mono text-[11px] leading-relaxed text-gray-700 tm-hairline dark:bg-white/[0.03] dark:text-gray-300"
										data-changes-deploy-log>{deploy.log}</pre>
								{/if}
							</div>
						{/if}
					{/if}

					{#if canShip}
						<div class="flex flex-wrap items-center gap-2 pt-0.5">
							<button
								type="button"
								class="tm-btn-primary !py-1.5 !text-xs"
								disabled={!!busy}
								on:click={() => {
									deployCleanup = deployProfile?.cleanup ?? true;
									deployReview = !!(deploy?.codex_review ?? deployProfile?.codex_review);
									confirmDeploy = true;
								}}
								data-changes-deploy
								>{busy === 'deploy'
									? '启动中…'
									: deploy?.status === 'failed'
										? '重试推送部署'
										: '一键推送部署'}</button
							>
							<span class="text-[11px] text-gray-400">
								{deployProfile?.codex_review ? 'Codex 审查 → ' : ''}合并到 {project.base_branch} → 推送{deployProfile?.has_ci ? ' → 等待 CI' : ''}{deployProfile?.has_command
									? ' → 自动拉取部署'
									: ''} → 清理分支{deployProfile?.has_verify ? ' → 核实线上' : ''}
							</span>
						</div>
					{/if}
				</div>
			{/if}

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
						<span class="text-xs text-gray-500"
							>成员还在干活；团队完成后可一键推送部署，或手动合并、推送。</span
						>
					{:else}
						{#if !merged && project.base_branch}
							<button
								type="button"
								class="tm-btn-ghost !py-1.5 !text-xs"
								disabled={!!busy || deployRunning || (!commits.length && !data.pending?.length)}
								on:click={() => (confirmMerge = true)}
								data-changes-merge
								>{busy === 'merge' ? '合并中…' : `合并到 ${project.base_branch}`}</button
							>
						{/if}
						{#if merged && project.base_branch && !pushedBase}
							<button
								type="button"
								class="tm-btn-ghost !py-1.5 !text-xs"
								disabled={!!busy || deployRunning}
								on:click={() => (confirmPushBase = true)}
								data-changes-push-base
								>{busy === 'push-base' ? '推送中…' : `推送 ${project.base_branch}`}</button
							>
						{/if}
						<button
							type="button"
							class="tm-btn-ghost !py-1.5 !text-xs"
							disabled={!!busy || deployRunning}
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
							disabled={!!busy || deployRunning}
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
	bind:show={confirmDeploy}
	title="一键推送并部署？"
	confirmLabel="开始推送部署"
	on:confirm={startDeploy}
>
	<div class="flex flex-col gap-3 text-sm text-gray-500 dark:text-gray-400">
		<p>
			将按顺序执行：{deployReview ? 'Codex 审查（最多 2 轮，不通过自动派 Claude 修） → ' : ''}合并
			<span class="font-mono text-gray-700 dark:text-gray-200">{project?.branch}</span>
			到 <span class="font-mono text-gray-700 dark:text-gray-200">{project?.base_branch}</span> →
			推送 origin{deployProfile?.has_ci ? ' → 等待 GitHub CI 通过' : ''}{deployProfile?.has_command
				? ' → 自动拉取并更新部署'
				: ''}{deployCleanup ? ' → 清理团队分支与 worktree（结论保留）' : ''}{deployProfile?.has_verify
				? ' → 核实线上状态'
				: ''}。
		</p>
		<label
			class="inline-flex cursor-pointer select-none items-center gap-2 text-xs text-gray-700 dark:text-gray-200"
		>
			<input
				type="checkbox"
				class="size-3.5 rounded accent-sky-600"
				bind:checked={deployReview}
				data-deploy-review-checkbox
			/>
			<span>合并前先做 Codex 审查（最多 2 轮，用 Codex 默认配置）</span>
		</label>
		<label
			class="inline-flex cursor-pointer select-none items-center gap-2 text-xs text-gray-700 dark:text-gray-200"
		>
			<input
				type="checkbox"
				class="size-3.5 rounded accent-sky-600"
				bind:checked={deployCleanup}
				data-deploy-cleanup-checkbox
			/>
			<span>部署完成后自动清理团队分支与 worktree</span>
		</label>
	</div>
</ConfirmDialog>
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
