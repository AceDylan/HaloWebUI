import { writable } from 'svelte/store';

import type { Team } from '$lib/apis/teams';

/**
 * What each team is doing, by its chat: the chat history marks a team's chat while the team works
 * (a live dot) or waits for you (a violet dot), the way it marks a chat whose Hermes run is going.
 * TeamsBadge fills it from the list it already reads.
 */
export type TeamChatState = 'running' | 'review' | 'attention';

export const teamChatStates = writable<Map<string, TeamChatState>>(new Map());

export const teamChatState = (team: Pick<Team, 'status' | 'phase'>): TeamChatState | null => {
	if (team.status === 'plan_ready') return 'review';
	if (['planning', 'starting'].includes(team.status)) return 'running';
	if (team.status !== 'running') return null;
	if (team.phase === 'attention') return 'attention';
	return ['completed', 'stopped', 'paused'].includes(team.phase ?? '') ? null : 'running';
};

/** chat id → state for the teams that are doing something (the newest team wins a shared chat). */
export const chatStatesOf = (
	teams: Pick<Team, 'chat_id' | 'status' | 'phase' | 'updated_at'>[]
) => {
	const out = new Map<string, TeamChatState>();
	const rank: Record<TeamChatState, number> = { attention: 3, review: 2, running: 1 };
	for (const team of teams) {
		const state = team.chat_id ? teamChatState(team) : null;
		if (!state || !team.chat_id) continue;
		const before = out.get(team.chat_id);
		if (!before || rank[state] > rank[before]) out.set(team.chat_id, state);
	}
	return out;
};
