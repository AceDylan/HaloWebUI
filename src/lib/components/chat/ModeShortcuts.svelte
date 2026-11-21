<script lang="ts">
	import { goto } from '$app/navigation';
	import { config, user } from '$lib/stores';
	import { chatHandoff, composerFiles, handOff, HANDOFF_PATH } from '$lib/utils/handoff';
	import SidebarModeIcon from '$lib/components/layout/Sidebar/SidebarModeIcon.svelte';
	import { modeLive, type ModeKey } from '$lib/components/scifi/mode-relay';

	/** Under the new-chat composer: all workbenches at one tap, taking the draft & attachments along. */
	export let prompt = '';
	export let files: any[] = [];

	type ShortcutTarget = 'auto' | 'answer' | 'discuss' | 'teams' | 'studio' | 'video';

	$: uploadedCount = composerFiles(files).length;
	$: draftChars = prompt.trim().length;
	$: carrying = draftChars > 0 || uploadedCount > 0;
	$: cargoSummary = [
		draftChars > 0 ? `${draftChars} 字` : '',
		uploadedCount > 0 ? `${uploadedCount} 个附件` : ''
	]
		.filter(Boolean)
		.join(' · ');

	$: modes = (
		[
			{
				to: 'auto' as const,
				icon: 'auto',
				label: '自动分流',
				cue: '智能路由',
				title: '自动分流：按问题自动选择精答、讨论或协作台',
				accent: 'auto',
				show: true
			},
			{
				to: 'answer' as const,
				icon: 'answer',
				label: '精答',
				cue: '专家助手',
				title: '精答：按问题挑最合适的助手来答',
				accent: 'answer',
				show: true
			},
			{
				to: 'discuss' as const,
				icon: 'discuss',
				label: '多模型讨论',
				cue: '多方共识',
				title: '讨论台：几个模型讨论，主持人给结论',
				accent: 'discuss',
				show: true
			},
			{
				to: 'teams' as const,
				icon: 'teams',
				label: '协作台',
				cue: '团队分工',
				title: '协作台：一支 AI 团队拆任务、并行完成',
				accent: 'teams',
				show: !!$config?.features?.enable_agent_teams
			},
			{
				to: 'studio' as const,
				icon: 'studio',
				label: '生图工作台',
				cue: '绘图图库',
				title: '生图工作台：提示词、参考图、图库',
				accent: 'studio',
				show:
					!!$config?.features?.enable_image_generation &&
					($user?.role === 'admin' || !!$user?.permissions?.features?.image_generation)
			},
			{
				to: 'video' as const,
				icon: 'video',
				label: '视频工作台',
				cue: '视频制作',
				title: '视频工作台：交给 Hermes 或 runner 做视频',
				accent: 'video',
				show: true
			}
		] as {
			to: ShortcutTarget;
			icon: ModeKey;
			label: string;
			cue: string;
			title: string;
			accent: string;
			show: boolean;
		}[]
	).filter((m) => m.show);

	const go = (to: ShortcutTarget) => {
		handOff(
			typeof sessionStorage === 'undefined' ? null : sessionStorage,
			chatHandoff(to, { text: prompt, files })
		);
		goto(HANDOFF_PATH[to]);
	};
</script>

<div
	class="halo-shortcuts flex flex-wrap items-center justify-center gap-1.5 text-xs text-gray-500 dark:text-gray-400"
	data-carrying={carrying ? '' : undefined}
	data-halo-mode-shortcuts
>
	<span class="halo-shortcuts__lead mr-0.5 inline-flex items-center gap-1">
		{#if carrying}
			<span>把这句话交给</span>
			{#if cargoSummary}
				<span class="halo-shortcuts__cargo" data-halo-shortcuts-cargo>{cargoSummary}</span>
			{/if}
		{:else}
			<span>工作台</span>
		{/if}
	</span>
	{#each modes as mode (mode.to)}
		{@const live = $modeLive[mode.to] ?? 0}
		<button
			type="button"
			class="halo-shortcuts__chip group inline-flex items-center gap-1.5 rounded-full border border-gray-200/80 bg-white/75 px-2.5 py-1.5 font-medium text-gray-700 transition hover:text-gray-950 dark:border-gray-700/60 dark:bg-white/[0.035] dark:text-gray-200 dark:hover:text-white"
			data-accent={mode.accent}
			title={carrying ? `带着当前内容去${mode.label}：${mode.title}` : mode.title}
			on:click={() => go(mode.to)}
			data-halo-mode-shortcut={mode.to}
		>
			<span class="halo-shortcuts__icon inline-grid size-[18px] place-items-center rounded-full">
				<SidebarModeIcon mode={mode.icon} className="size-3.5" />
			</span>
			<span>{mode.label}</span>
			{#if live}
				<span
					class="halo-shortcuts__live"
					aria-label="{live} 个进行中"
					data-halo-mode-shortcut-live={mode.to}>{live}</span
				>
			{/if}
		</button>
	{/each}
</div>

<style>
	.halo-shortcuts__lead {
		font-size: 11.5px;
		color: rgb(100 116 139);
	}
	:global(.dark) .halo-shortcuts__lead {
		color: rgb(148 163 184);
	}
	.halo-shortcuts__cargo {
		border-radius: 9999px;
		background: rgb(8 145 178 / 0.1);
		padding: 0.05rem 0.42rem;
		font-size: 10.5px;
		font-weight: 600;
		color: rgb(8 145 178);
	}
	:global(.dark) .halo-shortcuts__cargo {
		background: rgb(94 231 255 / 0.14);
		color: rgb(165 243 252);
	}
	.halo-shortcuts__chip {
		--chip-hue: 215;
		box-shadow: 0 1px 2px rgb(15 23 42 / 0.03);
	}
	.halo-shortcuts__chip[data-accent='auto'] {
		--chip-hue: 190;
	}
	.halo-shortcuts__chip[data-accent='answer'] {
		--chip-hue: 26;
	}
	.halo-shortcuts__chip[data-accent='discuss'] {
		--chip-hue: 245;
	}
	.halo-shortcuts__chip[data-accent='teams'] {
		--chip-hue: 222;
	}
	.halo-shortcuts__chip[data-accent='studio'] {
		--chip-hue: 342;
	}
	.halo-shortcuts__chip[data-accent='video'] {
		--chip-hue: 288;
	}
	.halo-shortcuts__icon {
		color: hsl(var(--chip-hue) 78% 42%);
		background: hsl(var(--chip-hue) 85% 54% / 0.12);
		transition:
			background-color 0.2s ease,
			transform 0.2s ease;
	}
	:global(.dark) .halo-shortcuts__icon {
		color: hsl(var(--chip-hue) 88% 72%);
		background: hsl(var(--chip-hue) 85% 60% / 0.16);
	}
	.halo-shortcuts__chip:hover {
		border-color: hsl(var(--chip-hue) 75% 52% / 0.45);
		background: hsl(var(--chip-hue) 85% 56% / 0.06);
		transform: translateY(-0.5px);
	}
	:global(.dark) .halo-shortcuts__chip:hover {
		border-color: hsl(var(--chip-hue) 88% 70% / 0.42);
		background: hsl(var(--chip-hue) 85% 60% / 0.11);
	}
	.halo-shortcuts__chip:active {
		transform: scale(0.98);
	}
	.halo-shortcuts__live {
		display: inline-grid;
		place-items: center;
		min-width: 1rem;
		height: 1rem;
		padding: 0 0.25rem;
		border-radius: 9999px;
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 600;
		color: #fff;
		background: rgb(14 165 233);
		box-shadow: 0 0 0 2px rgb(14 165 233 / 0.18);
	}

	/* the same instruments as the mode pages' dock (scifi/ModeDock.svelte) */
	:global(html.halo-scifi) .halo-shortcuts__lead {
		font-family: var(--font-mono);
		font-size: 10.5px;
		letter-spacing: 0.06em;
	}
	:global(html.halo-scifi) .halo-shortcuts__chip {
		border-color: rgb(8 145 178 / 0.2);
	}
	:global(html.halo-scifi.dark) .halo-shortcuts__chip {
		border-color: rgb(94 231 255 / 0.16);
		background: rgb(6 9 20 / 0.55);
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
	:global(html.halo-scifi) .halo-shortcuts__live {
		background: linear-gradient(120deg, #0891b2, #7c3aed);
	}
	:global(html.halo-scifi.dark) .halo-shortcuts__live {
		color: #03111a;
		background: linear-gradient(120deg, #5ee7ff, #a78bfa);
		box-shadow: 0 0 10px rgb(94 231 255 / 0.6);
	}
</style>
