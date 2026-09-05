<script lang="ts">
	import { page } from '$app/stores';

	import Chat from '$lib/components/chat/Chat.svelte';
	import Help from '$lib/components/layout/Help.svelte';
	import { hermesUnreadChatIds } from '$lib/stores';
	import { markHermesChatRead } from '$lib/apis/hermes';

	// Opening a chat is what "read" means for a hermes run that finished
	// while nobody was looking: drop the sidebar dot and tell the server.
	$: if ($page.params.id && $hermesUnreadChatIds.has($page.params.id)) {
		const id = $page.params.id;
		hermesUnreadChatIds.update((ids) => {
			ids.delete(id);
			return new Set(ids);
		});
		markHermesChatRead(localStorage.token, id).catch(() => {});
	}
</script>

<Help />
<Chat chatIdProp={$page.params.id} />
