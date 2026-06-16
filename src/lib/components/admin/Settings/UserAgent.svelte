<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';

	import { getUserAgentConfig, setUserAgentConfig } from '$lib/apis/configs';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import type { Writable } from 'svelte/store';
	const i18n: Writable<any> = getContext('i18n');

	export let saveHandler: Function = () => {};

	type UAConfig = {
		USER_AGENT_CLAUDE: string;
		USER_AGENT_GPT: string;
		USER_AGENT_GEMINI: string;
	};

	let config: UAConfig | null = null;

	let loading = true;
	let isSaving = false;

	const fields: { key: keyof UAConfig; label: string; hint: string; placeholder: string }[] = [
		{
			key: 'USER_AGENT_CLAUDE',
			label: 'Claude',
			hint: 'claude*',
			placeholder: 'claude-cli/2.1.170 (external, cli)'
		},
		{
			key: 'USER_AGENT_GPT',
			label: 'GPT / OpenAI',
			hint: 'gpt*',
			placeholder:
				'codex_vscode/0.140.0-alpha.2 (Windows 10.0.26100; x86_64) unknown (VS Code; 26.609.30741)'
		},
		{
			key: 'USER_AGENT_GEMINI',
			label: 'Gemini',
			hint: 'gemini*',
			placeholder: 'GeminiCLI-tui/0.46.0/gemini-3.1-pro-preview (win32; x64; terminal)'
		}
	];

	onMount(async () => {
		try {
			config = await getUserAgentConfig(localStorage.token);
		} catch (error) {
			toast.error(`${error}`);
		}
		loading = false;
	});

	const submitHandler = async () => {
		if (!config) return;

		isSaving = true;
		try {
			const res = await setUserAgentConfig(localStorage.token, config);
			if (res) {
				config = res;
				toast.success($i18n.t('Settings saved successfully!'));
				await saveHandler();
			}
		} catch (error) {
			toast.error(`${error}`);
		}
		isSaving = false;
	};
</script>

<form
	class="flex flex-col h-full justify-between text-sm"
	on:submit|preventDefault={submitHandler}
>
	<div class="overflow-y-scroll scrollbar-hidden h-full">
		{#if loading || !config}
			<div class="flex h-full items-center justify-center">
				<Spinner />
			</div>
		{:else}
			<div class="mb-3">
				<div class="mb-1 text-sm font-medium">
					{$i18n.t('User-Agent (Outbound LLM Requests)')}
				</div>
				<div class="mb-3 text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t(
						'Override the User-Agent header sent to upstream providers, matched by model prefix. Leave a field empty to use the built-in default.'
					)}
				</div>

				<div class="space-y-3">
					{#each fields as field (field.key)}
						<div class="glass-item px-4 py-3">
							<div class="mb-1 flex items-center gap-2">
								<span class="text-sm font-medium">{field.label}</span>
								<span class="text-xs text-gray-400 dark:text-gray-500">{field.hint}</span>
							</div>
							<input
								class="w-full px-3 py-1.5 text-sm dark:text-gray-300 glass-input"
								type="text"
								autocomplete="off"
								spellcheck="false"
								bind:value={config[field.key]}
								placeholder={field.placeholder}
							/>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</div>

	<div class="flex justify-end pt-3">
		<button
			class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full disabled:opacity-50"
			type="submit"
			disabled={isSaving || loading || !config}
		>
			{$i18n.t('Save')}
		</button>
	</div>
</form>
