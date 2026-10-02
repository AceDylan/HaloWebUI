<script lang="ts">
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import {
		followUpTeamConclusion,
		saveTeamConclusionToKnowledge,
		type Team
	} from '$lib/apis/teams';

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

	let opening = false;
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
