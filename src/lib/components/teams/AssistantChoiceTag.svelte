<script lang="ts">
	import { choiceLabel } from '$lib/apis/assistant-library';

	/** What a member's assistant is in this team: 选用 / 选用模板 / 升级 / 新建 / 仅本次 / 通用角色. */
	export let action: string | null | undefined;

	const TONE: Record<string, string> = {
		use: 'bg-sky-500/10 text-sky-800 ring-sky-500/20 dark:text-sky-200',
		template: 'bg-gray-500/10 text-gray-600 ring-gray-500/15 dark:text-gray-300',
		update: 'bg-violet-500/10 text-violet-800 ring-violet-500/20 dark:text-violet-200',
		create: 'bg-emerald-500/10 text-emerald-800 ring-emerald-500/20 dark:text-emerald-200',
		temporary: 'bg-amber-500/10 text-amber-800 ring-amber-500/20 dark:text-amber-200',
		generic: 'bg-gray-500/10 text-gray-500 ring-gray-500/15'
	};

	$: key = action || 'template';
	$: label = choiceLabel(key);
</script>

{#if label}
	<span
		class="whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] leading-none ring-1 ring-inset {TONE[key] ??
			TONE.template}"
		data-assistant-action={key}>{label}</span
	>
{/if}
