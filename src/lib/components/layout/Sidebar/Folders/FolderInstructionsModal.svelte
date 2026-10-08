<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { updateFolderSystemPromptById } from '$lib/apis/folders';
	import { translateWithDefault } from '$lib/i18n';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();
	const tr = (key: string, defaultValue: string, options: Record<string, any> = {}) =>
		translateWithDefault($i18n, key, defaultValue, options);

	// Same cap as backend/open_webui/utils/folder_instructions.py.
	const MAX_CHARS = 20000;

	export let show = false;
	export let folderId = '';
	export let folderName = '';
	export let systemPrompt: string | null = null;

	let text = '';
	let saving = false;
	let openedFor: string | null = null;

	// Load the saved text each time the dialog opens, not while the person types.
	$: if (show && openedFor !== folderId) {
		openedFor = folderId;
		text = systemPrompt ?? '';
	}
	$: if (!show) {
		openedFor = null;
	}

	const save = async () => {
		if (saving) return;
		const value = text.trim();
		saving = true;
		const res = await updateFolderSystemPromptById(
			localStorage.token,
			folderId,
			value === '' ? null : value
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		saving = false;
		if (res) {
			toast.success(value ? tr('分组指令已保存', 'Folder instructions saved') : tr('分组指令已清除', 'Folder instructions cleared'));
			dispatch('save', { systemPrompt: value === '' ? null : value });
			show = false;
		}
	};
</script>

<Modal size="md" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-1">
			<div class="min-w-0 self-center">
				<div class="text-lg font-medium">{tr('分组指令', 'Folder instructions')}</div>
				<div class="truncate text-xs text-gray-500">{folderName}</div>
			</div>
			<button
				class="self-center"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						fill-rule="evenodd"
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
						clip-rule="evenodd"
					/>
				</svg>
			</button>
		</div>

		<form class="flex flex-col w-full px-5 pb-4 dark:text-gray-200" on:submit|preventDefault={save}>
			<div class="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
				{tr(
					'这个分组（含子分组）里的每段对话，回答前都会先读这段说明。适合写项目背景、技术栈、回答偏好。',
					'Every chat in this folder (and its sub-folders) reads this before answering. Good for project background, stack and answer preferences.'
				)}
			</div>

			<textarea
				class="mt-3 min-h-[220px] w-full resize-y rounded-xl border border-gray-200 bg-transparent px-3 py-2 text-sm outline-hidden placeholder:text-gray-400 focus:border-gray-300 dark:border-gray-800 dark:placeholder:text-gray-600 dark:focus:border-gray-700"
				bind:value={text}
				maxlength={MAX_CHARS}
				placeholder={tr(
					'例如：这是 HaloWebUI 的开发讨论。前端 Svelte 4 + Tailwind，后端 FastAPI。回答给出文件路径，代码风格跟现有代码一致。',
					'e.g. This is HaloWebUI development. Frontend Svelte 4 + Tailwind, backend FastAPI. Name file paths and match the existing code style.'
				)}
			></textarea>

			<div class="mt-1 flex items-center justify-between text-2xs text-gray-400 tabular-nums">
				<span>{tr('留空保存即清除', 'Save empty to clear')}</span>
				<span>{text.length.toLocaleString()} / {MAX_CHARS.toLocaleString()}</span>
			</div>

			<div class="flex justify-end pt-3 text-sm font-medium gap-1.5">
				<button
					class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex flex-row space-x-1 items-center disabled:opacity-60"
					type="submit"
					disabled={saving}
				>
					<span>{$i18n.t('Save')}</span>
					{#if saving}
						<Spinner className="size-3.5 ml-1" />
					{/if}
				</button>
			</div>
		</form>
	</div>
</Modal>
