<script lang="ts">
	import { goto } from '$app/navigation';
	import { config, user } from '$lib/stores';
	import { handOff, HANDOFF_PATH } from '$lib/utils/handoff';
	import SidebarModeIcon from '$lib/components/layout/Sidebar/SidebarModeIcon.svelte';
	import { carries, MODE_LABEL, modeDraft, modeLive, type ModeKey } from './mode-relay';

	/**
	 * The dock at the top of every mode page: the chat and its modes side by side, the one you are
	 * in lit, a live count where work is under way. Switching while you are writing takes what you
	 * wrote along (and the background it came with), so the same question can be asked another
	 * way without typing it again. With nothing written it is a plain link.
	 */
	export let current: ModeKey;

	$: studioAllowed =
		!!$config?.features?.enable_image_generation &&
		($user?.role === 'admin' || !!($user as any)?.permissions?.features?.image_generation);
	$: stations = (
		[
			{ key: 'chat', label: '对话', hint: '和一个模型直接聊', show: true },
			{ key: 'answer', label: '精答', hint: '按问题挑最合适的助手来答', show: true },
			{ key: 'discuss', label: '讨论', hint: '几个模型讨论，主持人给结论', show: true },
			{
				key: 'teams',
				label: '协作',
				hint: '一支 AI 团队拆任务、并行完成',
				show: !!($config?.features as any)?.enable_agent_teams
			},
			{
				key: 'studio',
				label: '生图',
				hint: '提示词、参考图、图库',
				show: studioAllowed || current === 'studio'
			}
		] as { key: ModeKey; label: string; hint: string; show: boolean }[]
	).filter((s) => s.show);

	$: draft = $modeDraft?.mode === current ? $modeDraft : null;
	$: carrying = carries(draft);
	$: cargo = draft ? draft.text.trim().length : 0;

	const titleOf = (key: ModeKey, hint: string) =>
		key === current
			? `${MODE_LABEL[key]}（当前）`
			: carrying
				? `带着这段草稿去${MODE_LABEL[key]}`
				: `${MODE_LABEL[key]}：${hint}`;

	const go = (event: MouseEvent, key: ModeKey) => {
		if (key === current || !carrying || !draft) return;
		// open in a new tab / window: a plain link
		if (
			(event.button ?? 0) !== 0 ||
			event.metaKey ||
			event.ctrlKey ||
			event.shiftKey ||
			event.altKey
		)
			return;
		event.preventDefault();
		handOff(typeof sessionStorage === 'undefined' ? null : sessionStorage, {
			to: key,
			text: draft.text,
			context: draft.context,
			files: draft.files,
			from: draft.from
		});
		goto(HANDOFF_PATH[key]);
	};
</script>

<nav
	class="halo-dock"
	aria-label="对话与模式"
	data-halo-dock={current}
	data-carrying={carrying ? '' : undefined}
>
	<div class="halo-dock__rail">
		{#each stations as s (s.key)}
			{@const live = s.key === current ? 0 : ($modeLive[s.key] ?? 0)}
			<a
				href={s.key === 'chat' ? '/?fresh-chat=true' : HANDOFF_PATH[s.key]}
				class="halo-dock__station"
				class:is-current={s.key === current}
				aria-current={s.key === current ? 'page' : undefined}
				title={titleOf(s.key, s.hint)}
				draggable="false"
				data-sveltekit-preload-data="off"
				on:click={(e) => go(e, s.key)}
				data-halo-dock-station={s.key}
			>
				<SidebarModeIcon mode={s.key} className="size-3.5 shrink-0" />
				<span class="halo-dock__label">{s.label}</span>
				{#if live}
					<span class="halo-dock__live" aria-label="{live} 个进行中" data-halo-dock-live={s.key}
						>{live}</span
					>
				{/if}
			</a>
		{/each}
	</div>
	{#if carrying}
		<span class="halo-dock__cargo" aria-live="polite" data-halo-dock-cargo>
			<span aria-hidden="true">⇢</span> 切换会带上草稿{cargo ? ` · ${cargo} 字` : ''}
		</span>
	{/if}
</nav>

<style>
	.halo-dock {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		min-width: 0;
	}
	.halo-dock__rail {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 2px;
		min-width: 0;
		padding: 3px;
		overflow-x: auto;
		scrollbar-width: none;
		border-radius: 9999px;
		background: rgb(255 255 255 / 0.66);
		box-shadow:
			inset 0 0 0 1px rgb(15 23 42 / 0.08),
			0 1px 2px rgb(15 23 42 / 0.04);
	}
	.halo-dock__rail::-webkit-scrollbar {
		display: none;
	}
	:global(.dark) .halo-dock__rail {
		background: rgb(10 14 28 / 0.6);
		box-shadow:
			inset 0 0 0 1px rgb(255 255 255 / 0.07),
			inset 0 1px 0 rgb(255 255 255 / 0.04);
	}
	.halo-dock__station {
		position: relative;
		display: inline-flex;
		flex: none;
		align-items: center;
		gap: 0.3rem;
		padding: 0.3rem 0.65rem;
		border-radius: 9999px;
		font-size: 12px;
		font-weight: 500;
		line-height: 1.2;
		color: rgb(100 116 139);
		white-space: nowrap;
		transition:
			color 0.2s ease,
			background-color 0.2s ease,
			box-shadow 0.25s ease;
	}
	.halo-dock__station:hover {
		color: rgb(15 23 42);
		background: rgb(15 23 42 / 0.05);
	}
	:global(.dark) .halo-dock__station {
		color: rgb(148 163 184);
	}
	:global(.dark) .halo-dock__station:hover {
		color: #fff;
		background: rgb(255 255 255 / 0.06);
	}
	.halo-dock__station.is-current {
		color: rgb(15 23 42);
		background: #fff;
		box-shadow:
			0 0 0 1px rgb(15 23 42 / 0.08),
			0 2px 8px -2px rgb(15 23 42 / 0.12);
	}
	:global(.dark) .halo-dock__station.is-current {
		color: #fff;
		background: rgb(255 255 255 / 0.1);
		box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.1);
	}
	/* while you write, the other stations show they will take it along */
	[data-carrying] .halo-dock__station:not(.is-current) {
		color: rgb(8 145 178);
	}
	:global(.dark) [data-carrying] .halo-dock__station:not(.is-current) {
		color: rgb(165 243 252);
	}
	.halo-dock__live {
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
	.halo-dock__cargo {
		display: none;
		flex: none;
		font-family: var(--font-mono);
		font-size: 10.5px;
		letter-spacing: 0.04em;
		color: rgb(8 145 178);
		white-space: nowrap;
	}
	:global(.dark) .halo-dock__cargo {
		color: rgb(103 232 249 / 0.85);
	}
	@media (min-width: 900px) {
		.halo-dock__cargo {
			display: inline;
		}
	}
	@media (max-width: 380px) {
		.halo-dock__station {
			padding: 0.3rem 0.5rem;
		}
	}

	/* ---- the sci-fi layer: a lit instrument rail --------------------------------------------- */
	:global(html.halo-scifi) .halo-dock__rail {
		box-shadow:
			inset 0 0 0 1px rgb(8 145 178 / 0.18),
			0 6px 22px -14px rgb(8 145 178 / 0.5);
	}
	:global(html.halo-scifi.dark) .halo-dock__rail {
		background: rgb(6 9 20 / 0.66);
		box-shadow:
			inset 0 0 0 1px rgb(94 231 255 / 0.16),
			inset 0 1px 0 rgb(255 255 255 / 0.05),
			0 8px 30px -16px rgb(94 231 255 / 0.55);
	}
	:global(html.halo-scifi) .halo-dock__station.is-current {
		color: var(--scifi-cyan);
		background: linear-gradient(to top, rgb(8 145 178 / 0.14), rgb(255 255 255 / 0.9) 75%);
		box-shadow:
			inset 0 0 0 1px rgb(8 145 178 / 0.3),
			inset 0 -1.5px 0 var(--scifi-cyan);
	}
	:global(html.halo-scifi.dark) .halo-dock__station.is-current {
		color: #e0fbff;
		background: linear-gradient(to top, rgb(94 231 255 / 0.2), rgb(94 231 255 / 0.03) 80%);
		box-shadow:
			inset 0 0 0 1px rgb(94 231 255 / 0.32),
			inset 0 -1.5px 0 var(--scifi-cyan),
			0 0 18px -4px rgb(94 231 255 / 0.55);
		text-shadow: 0 0 10px rgb(94 231 255 / 0.5);
	}
	:global(html.halo-scifi) .halo-dock__station.is-current :global(svg) {
		color: var(--scifi-cyan);
	}
	:global(html.halo-scifi.dark) .halo-dock__station.is-current :global(svg) {
		filter: drop-shadow(0 0 5px var(--scifi-cyan));
	}
	:global(html.halo-scifi) .halo-dock__live {
		background: linear-gradient(120deg, #0891b2, #7c3aed);
	}
	:global(html.halo-scifi.dark) .halo-dock__live {
		color: #03111a;
		background: linear-gradient(120deg, #5ee7ff, #a78bfa);
		box-shadow: 0 0 10px rgb(94 231 255 / 0.6);
	}
	/* the live count breathes (opacity only: the compositor's job) */
	:global(html.halo-scifi) .halo-dock__live {
		animation: halo-dock-live 1.8s ease-in-out infinite;
	}
	@keyframes halo-dock-live {
		50% {
			opacity: 0.6;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.halo-dock__live {
			animation: none !important;
		}
	}
</style>
