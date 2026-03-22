const TEMPORARY_CHAT_OVERRIDE_KEY = 'temporary-chat-override';

type TemporaryChatOptions = {
	defaultEnabled?: boolean;
	enforced?: boolean;
	allowed?: boolean;
};

type TemporaryChatNavigationOptions = TemporaryChatOptions & {
	currentUrl: URL;
	enabled: boolean;
	pathname?: string;
};

const parseTemporaryChatValue = (value: string | null | undefined): boolean | null => {
	if (value === 'true') {
		return true;
	}

	if (value === 'false') {
		return false;
	}

	return null;
};

export const resolveTemporaryChatEnabled = ({
	searchParams,
	defaultEnabled = false,
	enforced = false,
	allowed = true
}: TemporaryChatOptions & {
	searchParams?: URLSearchParams;
}) => {
	if (!allowed) {
		return false;
	}

	if (enforced) {
		return true;
	}

	const urlValue = parseTemporaryChatValue(searchParams?.get('temporary-chat'));
	if (urlValue !== null) {
		return urlValue;
	}

	if (typeof sessionStorage !== 'undefined') {
		const overrideValue = parseTemporaryChatValue(
			sessionStorage.getItem(TEMPORARY_CHAT_OVERRIDE_KEY)
		);
		if (overrideValue !== null) {
			return overrideValue;
		}
	}

	return defaultEnabled;
};

export const persistTemporaryChatOverride = (
	enabled: boolean,
	{ defaultEnabled = false, enforced = false, allowed = true }: TemporaryChatOptions = {}
) => {
	if (typeof sessionStorage === 'undefined') {
		return;
	}

	if (!allowed || enforced || enabled === defaultEnabled) {
		sessionStorage.removeItem(TEMPORARY_CHAT_OVERRIDE_KEY);
		return;
	}

	sessionStorage.setItem(TEMPORARY_CHAT_OVERRIDE_KEY, String(enabled));
};

export const getTemporaryChatNavigationPath = ({
	currentUrl,
	enabled,
	defaultEnabled = false,
	enforced = false,
	allowed = true,
	pathname
}: TemporaryChatNavigationOptions) => {
	const nextUrl = new URL(currentUrl.toString());

	if (pathname) {
		nextUrl.pathname = pathname;
	}

	nextUrl.searchParams.delete('temporary-chat');

	if (allowed && !enforced && enabled !== defaultEnabled) {
		nextUrl.searchParams.set('temporary-chat', String(enabled));
	}

	return `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`;
};
