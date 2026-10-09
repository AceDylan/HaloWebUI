// What kind of work a chat in a list is (backend utils/chat_kinds.py), how it is marked, and
// where it opens: a 讨论台 discussion opens in 讨论台, everything else as a chat.

export const CHAT_KIND_LABEL: Record<string, string> = {
	discuss: '讨论',
	answer: '精答',
	team: '协作',
	image: '生图',
	answer_dispatch: '精答',
	discuss_dispatch: '讨论'
};

export const CHAT_KIND_TITLE: Record<string, string> = {
	answer: '精答：由挑选出的助手回答，可以接着追问',
	discuss: '讨论台里的多模型讨论',
	team: '协作台任务的对话：目标、团队进度和发回的结果',
	image: '这个对话里生成过图片',
	answer_dispatch: '交给精答的对话：精答的进度和发回的回答',
	discuss_dispatch: '交给讨论台的对话：讨论的进度和发回的结论'
};

export const chatHref = (id: string, kind?: string | null) =>
	kind === 'discuss' ? `/discuss/${id}` : `/c/${id}`;
