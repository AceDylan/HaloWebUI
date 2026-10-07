<script lang="ts">
	import { goto } from '$app/navigation';
	import { config, user } from '$lib/stores';
	import { chatHandoff, handOff, HANDOFF_PATH } from '$lib/utils/handoff';
	import SidebarModeIcon from '$lib/components/layout/Sidebar/SidebarModeIcon.svelte';

	/** Under the new-chat composer: the same question, asked another way. Takes the draft along. */
	export let prompt = '';
	export let files: any[] = [];

	$: modes = [
		{ to: 'answer' as const, icon: 'answer', label: '精答', title: '按问题挑最合适的助手来答', show: true },
		{ to: 'discuss' as const, icon: 'discuss', label: '多模型讨论', title: '几个模型讨论，主持人给结论', show: true },
		{
			to: 'teams' as const,
			icon: 'teams',
			label: '交给协作台',
			title: '一支 AI 团队拆任务、并行完成',
			show: !!$config?.features?.enable_agent_teams
		},
		{
			to: 'studio' as const,
			icon: 'studio',
			label: '生图工作台',
			title: '提示词、参考图、图库',
			show:
				!!$config?.features?.enable_image_generation &&
				($user?.role === 'admin' || !!$user?.permissions?.features?.image_generation)
		}
	].filter((m) => m.show);

	const go = (to: 'answer' | 'discuss' | 'teams' | 'studio') => {
		handOff(typeof sessionStorage === 'undefined' ? null : sessionStorage, chatHandoff(to, { text: prompt, files }));
		goto(HANDOFF_PATH[to]);
	};
</script>

<div
	class="halo-shortcuts flex flex-wrap items-center justify-center gap-1.5 text-xs text-gray-500 dark:text-gray-400"
	data-carrying={prompt.trim() ? '' : undefined}
	data-halo-mode-shortcuts
>
	<span class="halo-shortcuts__lead mr-0.5">{prompt.trim() ? '把这句话交给' : '也可以'}</span>
	{#each modes as mode (mode.to)}
		<button
			type="button"
			class="halo-shortcuts__chip inline-flex items-center gap-1.5 rounded-full border border-gray-200/80 bg-white/70 px-2.5 py-1 font-medium text-gray-600 transition hover:border-gray-300 hover:text-gray-900 dark:border-gray-700/60 dark:bg-white/[0.03] dark:text-gray-300 dark:hover:border-gray-600 dark:hover:text-white"
			title={prompt.trim() ? `带着这句话去${mode.label}：${mode.title}` : mode.title}
			on:click={() => go(mode.to)}
			data-halo-mode-shortcut={mode.to}
		>
			<SidebarModeIcon mode={mode.icon} className="size-3.5" />
			{mode.label}
		</button>
	{/each}
</div>

<style>
	/* the same instruments as the mode pages' dock (scifi/ModeDock.svelte) */
	:global(html.halo-scifi) .halo-shortcuts__lead {
		font-family: var(--font-mono);
		font-size: 10.5px;
		letter-spacing: 0.08em;
	}
	:global(html.halo-scifi) .halo-shortcuts__chip {
		border-color: rgb(8 145 178 / 0.2);
	}
	:global(html.halo-scifi.dark) .halo-shortcuts__chip {
		border-color: rgb(94 231 255 / 0.16);
		background: rgb(6 9 20 / 0.5);
		box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.04);
	}
	:global(html.halo-scifi) .halo-shortcuts__chip:hover {
		border-color: var(--scifi-cyan);
		box-shadow: 0 0 18px -4px var(--scifi-glow);
	}
	/* with a draft written, each one says it will take it along */
	:global(html.halo-scifi) [data-carrying] .halo-shortcuts__chip {
		color: var(--scifi-cyan);
	}
	:global(html.halo-scifi.dark) [data-carrying] .halo-shortcuts__chip {
		color: #a5f3fc;
		border-color: rgb(94 231 255 / 0.3);
	}
</style>
