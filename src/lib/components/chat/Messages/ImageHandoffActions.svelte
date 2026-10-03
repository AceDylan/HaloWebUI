<script lang="ts">
	// "改这张" and "工作台" on an image in a reply. The parent is a `.halo-image-card`
	// (the buttons show on its hover / focus, always on touch screens).
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { translateWithDefault } from '$lib/i18n';
	import PencilSquare from '$lib/components/icons/PencilSquare.svelte';
	import Photo from '$lib/components/icons/Photo.svelte';
	import { requestChatImageEdit, studioUrlForImage } from '$lib/utils/image-handoff';

	const i18n = getContext('i18n');

	export let url = '';
	export let name = '';
	// The message the reply answers: the studio fills it in as the prompt.
	export let prompt = '';

	const tr = (key: string, defaultValue: string) => translateWithDefault($i18n, key, defaultValue);

	const edit = () => {
		if (!requestChatImageEdit(url, name)) {
			toast.error(tr('这张图不能在这里修改', 'This image cannot be edited here'));
		}
	};
	const openInStudio = () => void goto(studioUrlForImage(url, prompt));
</script>

<div class="halo-image-actions absolute right-2 bottom-2 flex gap-1.5" data-image-actions>
	<button
		type="button"
		class="flex items-center gap-1 rounded-full bg-black/55 px-2.5 py-1 text-xs font-medium text-white backdrop-blur transition hover:bg-black/75"
		data-image-action="edit"
		title={tr('把这张图放进输入框，接着改', 'Put this image in the message box to edit it')}
		on:click|stopPropagation={edit}
	>
		<PencilSquare className="size-3.5" strokeWidth="2" />
		{tr('改这张', 'Edit')}
	</button>
	<button
		type="button"
		class="flex items-center gap-1 rounded-full bg-black/55 px-2.5 py-1 text-xs font-medium text-white backdrop-blur transition hover:bg-black/75"
		data-image-action="studio"
		title={tr('在图片工作台打开（作为参考图）', 'Open in the image studio as a reference')}
		on:click|stopPropagation={openInStudio}
	>
		<Photo className="size-3.5" strokeWidth="2" />
		{tr('工作台', 'Studio')}
	</button>
</div>

<style>
	.halo-image-actions {
		opacity: 0;
		transition: opacity 150ms ease;
	}
	:global(.halo-image-card:hover) .halo-image-actions,
	:global(.halo-image-card:focus-within) .halo-image-actions {
		opacity: 1;
	}
	@media (hover: none) {
		.halo-image-actions {
			opacity: 1;
		}
	}
</style>
