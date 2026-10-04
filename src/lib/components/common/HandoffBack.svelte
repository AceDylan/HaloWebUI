<script lang="ts">
	import { originHref, originLabel, type HandoffOrigin } from '$lib/utils/handoff';

	/** Where the work on this page came from (a chat, a discussion, a team): a way back. */
	export let origin: HandoffOrigin;
	export let className = 'ml-auto';
</script>

<a
	href={originHref(origin)}
	class="{className} inline-flex min-w-0 max-w-[60%] items-center gap-1 rounded-xl px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-850"
	title="返回{originLabel(origin)}"
	data-handoff-back={origin.kind}
>
	<span aria-hidden="true">←</span>
	<span class="truncate">返回{originLabel(origin)}</span>
</a>
