<script lang="ts">
	import type { AnswerRun } from '$lib/apis/answers';
	import type { DiscussAsk, LocalInspect } from '$lib/apis/discussions';

	export let run: AnswerRun | null = null;
	export let ask: DiscussAsk | null = null;

	const inspection: Record<LocalInspect['status'], string> = {
		waiting: '等候本机取证', running: '正在本机取证', done: '已使用本机取证',
		empty: '本机取证无结果', error: '本机取证失败', stopped: '本机取证已停止', skipped: '未使用本机取证'
	};

	$: author = run?.assistant;
	$: writer = ask?.conclusion;
	$: inspect = run?.localInspect ?? ask?.localInspect;
	$: inspected = inspect ? inspection[inspect.status] :
		(run && 'localInspect' in run) || (ask && 'localInspect' in ask) ? '未使用本机取证' : '无本机取证记录';
	$: model = author?.baseName || author?.base || (author?.action === 'direct' ? author.name : '') ||
		(writer?.name || writer?.model);
</script>

{#if run || ask}
	<p class="flex flex-wrap gap-x-2 gap-y-0.5 break-all text-xs text-gray-500 dark:text-gray-400" data-answer-attribution>
		{#if run?.planner?.name}<span>调度 · {run.planner.name}</span>{/if}
		{#if ask?.moderator?.name}<span>主持 · {ask.moderator.name}</span>{/if}
		{#if model}<span title={author?.base || writer?.model}>{run ? '作答' : writer?.standIn ? '代写结论' : '结论'} · {model}</span>{/if}
		<span>{inspected}</span>
	</p>
{/if}
