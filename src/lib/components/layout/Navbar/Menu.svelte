<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { getContext } from 'svelte';

	import { chatHandoff, handOff } from '$lib/utils/handoff';

	import {
		showOverview,
		showControls,
		showArtifacts,
		mobile,
		temporaryChatEnabled,
		config
	} from '$lib/stores';
	import { goto } from '$app/navigation';
	import UsersSolid from '$lib/components/icons/UsersSolid.svelte';
	import { flyAndScale } from '$lib/utils/transitions';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Tags from '$lib/components/chat/Tags.svelte';
	import Map from '$lib/components/icons/Map.svelte';
	import AdjustmentsHorizontal from '$lib/components/icons/AdjustmentsHorizontal.svelte';
	import Cube from '$lib/components/icons/Cube.svelte';

	const i18n = getContext('i18n');

	export let shareEnabled: boolean = false;
	export let shareHandler: Function;
	export let downloadHandler: Function;

	// export let tagHandler: Function;

	export let chat;
	export let onClose: Function = () => {};
</script>

<Dropdown
	on:change={(e) => {
		if (e.detail === false) {
			onClose();
		}
	}}
>
	<slot />

	<div slot="content">
		<DropdownMenu.Content
			class="w-full max-w-[280px] rounded-xl px-1 py-1.5  z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg"
			sideOffset={8}
			side="bottom"
			align="end"
			transition={flyAndScale}
		>
			<!-- <DropdownMenu.Item
				class="flex gap-2 items-center px-3 py-2 text-sm  cursor-pointer dark:hover:bg-gray-800 rounded-md"
				on:click={async () => {
					await showSettings.set(!$showSettings);
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="size-4"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z"
					/>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"
					/>
				</svg>
				<div class="flex items-center">{$i18n.t('Settings')}</div>
			</DropdownMenu.Item> -->

			{#if $mobile}
				<DropdownMenu.Item
					class="flex gap-2 items-center px-3 py-2 text-sm  cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
					id="chat-controls-button"
					on:click={async () => {
						await showControls.set(true);
						await showOverview.set(false);
						await showArtifacts.set(false);
					}}
				>
					<AdjustmentsHorizontal className=" size-4" strokeWidth="0.5" />
					<div class="flex items-center">{$i18n.t('Controls')}</div>
				</DropdownMenu.Item>
			{/if}

			{#if !$temporaryChatEnabled}
				<DropdownMenu.Item
					class="flex gap-2 items-center px-3 py-2 text-sm  cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
					id="chat-share-button"
					on:click={() => {
						shareHandler();
					}}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="currentColor"
						class="size-4"
					>
						<path
							fill-rule="evenodd"
							d="M15.75 4.5a3 3 0 1 1 .825 2.066l-8.421 4.679a3.002 3.002 0 0 1 0 1.51l8.421 4.679a3 3 0 1 1-.729 1.31l-8.421-4.678a3 3 0 1 1 0-4.132l8.421-4.679a3 3 0 0 1-.096-.755Z"
							clip-rule="evenodd"
						/>
					</svg>
					<div class="flex items-center">{$i18n.t('Share')}</div>
				</DropdownMenu.Item>
			{/if}

			<DropdownMenu.Item
				class="flex gap-2 items-center px-3 py-2 text-sm  cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
				id="chat-overview-button"
				on:click={async () => {
					await showArtifacts.set(false);
					await showOverview.set(true);
					await showControls.set(true);
				}}
			>
				<Map className=" size-4" strokeWidth="1.5" />
				<div class="flex items-center">{$i18n.t('Overview')}</div>
			</DropdownMenu.Item>

			<DropdownMenu.Item
				class="flex gap-2 items-center px-3 py-2 text-sm  cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
				id="chat-overview-button"
				on:click={async () => {
					await showOverview.set(false);
					await showArtifacts.set(true);
					await showControls.set(true);
				}}
			>
				<Cube className=" size-4" strokeWidth="1.5" />
				<div class="flex items-center">{$i18n.t('Artifacts')}</div>
			</DropdownMenu.Item>

			{#if $config?.features?.enable_agent_teams && chat?.id && !String(chat.id).startsWith('local') && !$temporaryChatEnabled}
				<DropdownMenu.Item
					class="flex gap-2 items-center px-3 py-2 text-sm  cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
					id="chat-agent-teams-button"
					on:click={() => {
						onClose();
						// the conversation goes along as the team's background, like the composer's 「+」 handoff
						handOff(
							typeof sessionStorage === 'undefined' ? null : sessionStorage,
							chatHandoff('teams', {
								text: '',
								history: chat.chat?.history,
								chatId: chat.id,
								title: chat.chat?.title
							})
						);
						goto(`/teams?chat=${encodeURIComponent(chat.id)}`);
					}}
				>
					<UsersSolid className=" size-4" />
					<div class="flex items-center">协作任务</div>
				</DropdownMenu.Item>
			{/if}

			{#if !$temporaryChatEnabled}
				<hr class="border-gray-100 dark:border-gray-850 my-0.5" />

				<div class="flex p-1 w-full overflow-hidden">
					<Tags chatId={chat.id} />
				</div>
			{/if}
		</DropdownMenu.Content>
	</div>
</Dropdown>
