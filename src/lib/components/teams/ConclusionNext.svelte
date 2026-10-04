<script lang="ts">
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { createEventDispatcher } from 'svelte';

	import {
		followUpTeamConclusion,
		getTeamsMeta,
		illustrateTeamConclusion,
		saveTeamConclusionToKnowledge,
		type ConclusionIllustration,
		type ImageTemplateRef,
		type Team
	} from '$lib/apis/teams';
	import { elapsed, now } from './clock';
	import { handOff, HANDOFF_PATH } from '$lib/utils/handoff';
	import SidebarModeIcon from '$lib/components/layout/Sidebar/SidebarModeIcon.svelte';

	/**
	 * What to do with a written conclusion: carry on in a chat (the one the team came from, or a
	 * new one that opens with the conclusion) or keep it in the 「协作结论」 knowledge base.
	 */
	export let teamId: string;
	export let chatId: string | null = null;
	export let outputs: Team['outputs'] = undefined;
	/** The version on screen (its generated_at): saved / posted state is per version. */
	export let generatedAt: number | undefined = undefined;
	export let variant: 'panel' | 'page' = 'panel';
	/** The team's title and the conclusion on screen: what 「让几个模型讨论」 hands to 讨论台. */
	export let title = '';
	export let markdown = '';
	/** 「为结果配图」 as it stands (the conclusion entry's). */
	export let illustration: ConclusionIllustration | null | undefined = undefined;

	const dispatch = createEventDispatcher<{ illustrate: ConclusionIllustration }>();
	let opening = false;
	let picking = false;
	let drawing = false;
	let templates: ImageTemplateRef[] | null = null;
	let templateId = '';
	$: drawingNow = drawing || illustration?.status === 'generating';

	const pick = async () => {
		picking = !picking;
		if (!picking || templates) return;
		try {
			templates = (await getTeamsMeta(localStorage.token)).image_templates ?? [];
		} catch {
			templates = [];
		}
		// The all-round hand-drawn template first when the user has it.
		templateId = templates.find((t) => /万能|auto_style/.test(`${t.name} ${t.id}`))?.id ?? '';
	};

	const draw = async () => {
		if (drawingNow) return;
		drawing = true;
		try {
			const out = await illustrateTeamConclusion(localStorage.token, teamId, templateId || undefined);
			picking = false;
			dispatch('illustrate', out);
			toast.success('开始配图：负责人先提炼要点，再用 gpt-image 画，通常 1–3 分钟');
		} catch (e) {
			toast.error(`${(e as Error)?.message ?? e}`);
		} finally {
			drawing = false;
		}
	};
	let saving = false;
	let knowledge: NonNullable<Team['outputs']>['knowledge'] = null;
	// The team record catches up after a save here; a newer version saved here is not undone by it.
	const follow = (o: Team['outputs']) => {
		if (o?.knowledge && (!knowledge || o.knowledge.generated_at >= knowledge.generated_at))
			knowledge = o.knowledge;
	};
	$: follow(outputs);
	$: saved = !!knowledge && !!generatedAt && knowledge.generated_at === generatedAt;
	$: posted = !!chatId && !!generatedAt && outputs?.chat_posted?.generated_at === generatedAt;

	const ask = async () => {
		if (opening) return;
		opening = true;
		try {
			const out = await followUpTeamConclusion(localStorage.token, teamId);
			if (out.busy) toast.info('这个对话正在回答别的问题，结论稍后会补进去');
			await goto(`/c/${out.chat_id}`);
		} catch (e) {
			toast.error(`${(e as Error)?.message ?? e}`);
		} finally {
			opening = false;
		}
	};

	// A second opinion on the result: 讨论台 with the conclusion as background, and a way back here.
	const discuss = () => {
		handOff(typeof sessionStorage === 'undefined' ? null : sessionStorage, {
			to: 'discuss',
			text: `关于「${title || '这次协作'}」的结果：哪些地方站得住，哪些有问题、有风险，或有更好的做法？`,
			context: markdown,
			from: { kind: 'team', id: teamId, title }
		});
		goto(HANDOFF_PATH.discuss);
	};

	const save = async () => {
		if (saving || saved) return;
		saving = true;
		try {
			const out = await saveTeamConclusionToKnowledge(localStorage.token, teamId);
			knowledge = { id: out.knowledge_id, generated_at: out.generated_at };
			toast.success(
				out.replaced
					? `已更新「${out.knowledge_name}」里这份结论`
					: `已存入「${out.knowledge_name}」知识库`
			);
		} catch (e) {
			toast.error(`${(e as Error)?.message ?? e}`);
		} finally {
			saving = false;
		}
	};
</script>

<section
	class="next mt-8 {variant === 'page' ? 'lg:ml-[15rem]' : ''}"
	aria-label="接下来"
	data-conclusion-next
>
	<h3 class="tm-eyebrow mb-3">接下来</h3>
	<div class="grid gap-2 {variant === 'page' ? 'sm:grid-cols-2' : ''}">
		<button
			type="button"
			class="tm-card tm-hover flex items-start gap-3 !rounded-xl px-3.5 py-3 text-left disabled:opacity-60"
			disabled={opening}
			on:click={ask}
			data-conclusion-ask
		>
			<span class="icon grid size-8 shrink-0 place-items-center rounded-lg" aria-hidden="true">
				<svg class="size-4" viewBox="0 0 16 16" fill="none"
					><path
						d="M2.75 4.25a1.5 1.5 0 0 1 1.5-1.5h7.5a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 1-1.5 1.5H7l-2.75 2.5v-2.5h0a1.5 1.5 0 0 1-1.5-1.5v-5Z"
						stroke="currentColor"
						stroke-width="1.3"
						stroke-linejoin="round"
					/><path
						d="M5.5 6.25h5M5.5 8.25h3"
						stroke="currentColor"
						stroke-width="1.3"
						stroke-linecap="round"
					/></svg
				>
			</span>
			<span class="min-w-0 flex-1">
				<span class="block text-sm font-medium text-gray-900 dark:text-gray-100">
					{opening ? '正在打开对话…' : chatId ? '回到对话接着问' : '在对话里追问'}
				</span>
				<span class="mt-0.5 block text-xs leading-relaxed text-gray-500 dark:text-gray-400">
					{#if chatId}
						{posted
							? '结论已经发回发起它的对话，在那里接着问就行'
							: '把结论发回发起它的对话，在那里接着问'}
					{:else}
						开一个新对话，结论是第一条回复；Hermes 知道团队的工作目录，可以直接问产出文件
					{/if}
				</span>
			</span>
		</button>

		{#if markdown}
			<button
				type="button"
				class="tm-card tm-hover flex items-start gap-3 !rounded-xl px-3.5 py-3 text-left"
				on:click={discuss}
				data-conclusion-discuss
			>
				<span class="icon grid size-8 shrink-0 place-items-center rounded-lg" aria-hidden="true">
					<SidebarModeIcon mode="discuss" className="size-4" />
				</span>
				<span class="min-w-0 flex-1">
					<span class="block text-sm font-medium text-gray-900 dark:text-gray-100">让几个模型讨论</span>
					<span class="mt-0.5 block text-xs leading-relaxed text-gray-500 dark:text-gray-400">
						在讨论台请几个模型挑错、补漏，主持人给结论；这份结果作为背景
					</span>
				</span>
			</button>
		{/if}

		{#if saved && knowledge}
			<a
				href="/workspace/knowledge/{knowledge.id}"
				class="tm-card tm-hover flex items-start gap-3 !rounded-xl px-3.5 py-3"
				data-conclusion-saved
			>
				<span
					class="icon done grid size-8 shrink-0 place-items-center rounded-lg"
					aria-hidden="true"
				>
					<svg class="size-4" viewBox="0 0 16 16" fill="none"
						><path
							d="m3.5 8.5 3 3 6-7"
							stroke="currentColor"
							stroke-width="1.7"
							stroke-linecap="round"
							stroke-linejoin="round"
						/></svg
					>
				</span>
				<span class="min-w-0 flex-1">
					<span class="block text-sm font-medium text-gray-900 dark:text-gray-100"
						>已存入「协作结论」</span
					>
					<span class="mt-0.5 block text-xs leading-relaxed text-gray-500 dark:text-gray-400">
						在任何对话里输入 # 就能引用它 · 打开知识库 →
					</span>
				</span>
			</a>
		{:else}
			<button
				type="button"
				class="tm-card tm-hover flex items-start gap-3 !rounded-xl px-3.5 py-3 text-left disabled:opacity-60"
				disabled={saving}
				on:click={save}
				data-conclusion-save
			>
				<span class="icon grid size-8 shrink-0 place-items-center rounded-lg" aria-hidden="true">
					<svg class="size-4" viewBox="0 0 16 16" fill="none"
						><path
							d="M3.25 3.5A1.25 1.25 0 0 1 4.5 2.25h7a1.25 1.25 0 0 1 1.25 1.25v10.25L8 11l-4.75 2.75V3.5Z"
							stroke="currentColor"
							stroke-width="1.3"
							stroke-linejoin="round"
						/></svg
					>
				</span>
				<span class="min-w-0 flex-1">
					<span class="block text-sm font-medium text-gray-900 dark:text-gray-100">
						{saving ? '正在存入…' : knowledge ? '更新知识库里的结论' : '存入知识库'}
					</span>
					<span class="mt-0.5 block text-xs leading-relaxed text-gray-500 dark:text-gray-400">
						{knowledge
							? '知识库里是上一版，换成现在这一版'
							: '存进你的「协作结论」知识库，以后在任何对话里输入 # 就能引用'}
					</span>
				</span>
			</button>
		{/if}
		<div
			class="tm-card flex flex-col gap-2 !rounded-xl px-3.5 py-3 {variant === 'page'
				? 'sm:col-span-2'
				: ''} {drawingNow ? 'tm-live' : ''}"
			data-conclusion-illustrate={illustration?.status ?? 'none'}
		>
			<button
				type="button"
				class="flex items-start gap-3 text-left disabled:opacity-60"
				disabled={drawingNow}
				on:click={pick}
				aria-expanded={picking}
			>
				<span class="icon grid size-8 shrink-0 place-items-center rounded-lg" aria-hidden="true">
					<svg class="size-4" viewBox="0 0 16 16" fill="none"
						><rect x="2.25" y="3" width="11.5" height="10" rx="1.6" stroke="currentColor" stroke-width="1.3" /><circle
							cx="6"
							cy="6.6"
							r="1.2"
							stroke="currentColor"
							stroke-width="1.2"
						/><path
							d="m2.75 11.5 3.2-2.9 2.3 2 2.1-1.7 2.9 2.6"
							stroke="currentColor"
							stroke-width="1.3"
							stroke-linejoin="round"
						/></svg
					>
				</span>
				<span class="min-w-0 flex-1">
					<span class="block text-sm font-medium text-gray-900 dark:text-gray-100">
						{#if drawingNow}
							<span class="tm-shimmer">正在为结果配图</span>
						{:else if illustration?.status === 'ready'}
							已配图 · 换个风格再画一张
						{:else}
							为结果配图
						{/if}
					</span>
					<span class="mt-0.5 block text-xs leading-relaxed text-gray-500 dark:text-gray-400">
						{#if drawingNow}
							{illustration?.template ? `「${illustration.template}」· ` : ''}{illustration?.step ===
							'draw'
								? 'gpt-image 在画图'
								: '负责人在提炼图上的要点'}{#if illustration?.started_at}
								· 已 {elapsed($now - illustration.started_at)}{/if}
						{:else if illustration?.status === 'failed'}
							<span class="text-red-600 dark:text-red-300">{illustration.error || '没画成'}</span> · 可以再试一次
						{:else if illustration?.status === 'ready'}
							图在结果的标题下面{illustration.template ? `（${illustration.template}）` : ''}，提示词也存在工作目录里
						{:else}
							用 gpt-image 把结果画成一张图，放在结果最上面；可以选你在生图工作台存的模板风格
						{/if}
					</span>
				</span>
			</button>
			{#if picking && !drawingNow}
				<div class="flex flex-wrap items-center gap-2 pl-11" data-illustrate-picker>
					{#if templates === null}
						<span class="text-xs text-gray-400">正在读你的生图模板…</span>
					{:else}
						<label class="sr-only" for="illustrate-template-{teamId}">生图模板</label>
						<select
							id="illustrate-template-{teamId}"
							class="compact-select min-w-0 max-w-full flex-1 truncate rounded-lg border border-gray-200 bg-white py-1 pl-2 pr-7 text-xs text-gray-900 focus:border-sky-400 focus:outline-none dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
							bind:value={templateId}
						>
							<option value="">手绘信息图（Hermes 默认）</option>
							{#each templates as t (t.id)}
								<option value={t.id}>{t.name}{t.aspect ? ` · ${t.aspect}` : ''}</option>
							{/each}
						</select>
						<button
							type="button"
							class="tm-btn-primary !px-3 !py-1 !text-xs"
							disabled={drawing}
							on:click={draw}
							data-illustrate-start>{drawing ? '正在开始…' : '开始配图'}</button
						>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</section>

<style>
	.icon {
		color: hsl(var(--tm-accent));
		background: hsl(var(--tm-accent) / 0.08);
	}
	.icon.done {
		color: rgb(5 150 105);
		background: rgb(16 185 129 / 0.1);
	}
</style>
