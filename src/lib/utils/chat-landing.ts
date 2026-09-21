// 地址栏上「落地即发」的问题:/?q=<问题>[&models=<模型>]。书签中心(Bookmark Hub)的
// 「发送到 AI 聊天」就是这样把一句话送进来的:/auth?redirect=%2F%3Fq%3D… → 登录页跟着
// redirect 落到 /,Chat.svelte 的 initNewChat 读到 q 就自动发出去。
//
// 这句问题只能发一次。取的时候就把 q 从地址里摘掉:之后同一个页面实例上再开新对话
// (点「新对话」、删掉或归档当前对话……)时地址上已经没有它,不会再发一遍、再建一个对话。
// 其余参数(models=、temporary-chat=、hash)原样留下。

export const LANDING_PROMPT_PARAM = 'q';

export type LandingPrompt = {
	/** 要发出去的问题(已解码)。 */
	prompt: string;
	/** 摘掉 q 之后的地址(路径 + 其余查询串 + hash),供 replaceState 写回地址栏。 */
	path: string;
};

/** 从地址里取走 ?q=。地址上没有 q、或 q 为空时返回 null,什么都不改。 */
export const takeLandingPrompt = (href: string): LandingPrompt | null => {
	let url: URL;
	try {
		url = new URL(href);
	} catch {
		return null;
	}
	const prompt = url.searchParams.get(LANDING_PROMPT_PARAM);
	if (!prompt) {
		return null;
	}
	url.searchParams.delete(LANDING_PROMPT_PARAM);
	return { prompt, path: `${url.pathname}${url.search}${url.hash}` };
};
