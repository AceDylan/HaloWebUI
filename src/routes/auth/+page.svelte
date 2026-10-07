<script>
	import { toast } from 'svelte-sonner';

	import { onMount, getContext, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { getBackendConfig } from '$lib/apis';
	import { ldapUserSignIn, getSessionUser, userSignIn, userSignUp } from '$lib/apis/auths';
	import { exchangeHubTicket } from '$lib/apis/hub';

	import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';
	import { WEBUI_NAME, config, user, socket } from '$lib/stores';

	import { generateInitialsImage, canvasPixelTest } from '$lib/utils';
	import { localizeCommonError } from '$lib/utils/common-errors';
	import { takeHubTicket } from '$lib/utils/hub-embed';
	import { safeRedirectPath } from '$lib/utils/safe-redirect';

	import HaloConstellation from '$lib/components/common/HaloConstellation.svelte';
	import StarField from '$lib/components/scifi/StarField.svelte';
	import { warp } from '$lib/components/scifi/scifi';
	import { guardViewTransition, prefersReducedMotion } from '$lib/utils/transitions';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import OnBoarding from '$lib/components/OnBoarding.svelte';

	const i18n = getContext('i18n');

	let loaded = false;

	let mode = $config?.features.enable_ldap ? 'ldap' : 'signin';

	let name = '';
	let email = '';
	let password = '';

	let ldapUsername = '';

	// The stage's halo leans a little toward the pointer (-1…1 on each axis).
	let pointerX = 0;
	let pointerY = 0;
	const onStagePointer = (event) => {
		if (event.pointerType !== 'mouse' || document.hidden || prefersReducedMotion() || !window.matchMedia('(min-width: 1024px) and (pointer: fine)').matches) return;
		const box = event.currentTarget.getBoundingClientRect();
		pointerX = Math.max(-1, Math.min(1, ((event.clientX - box.left) / box.width) * 2 - 1));
		pointerY = Math.max(-1, Math.min(1, ((event.clientY - box.top) / box.height) * 2 - 1));
	};

	const formatError = (error) =>
		localizeCommonError(error, (key, options) => $i18n.t(key, options));

	const querystringValue = (key) => {
		const querystring = window.location.search;
		const urlParams = new URLSearchParams(querystring);
		return urlParams.get(key);
	};

	// ?redirect= comes from whoever built the link, so only a path on this very
	// site is ever followed (see $lib/utils/safe-redirect).
	const redirectTarget = () => safeRedirectPath(querystringValue('redirect'));

	const setSessionUser = async (sessionUser) => {
		if (sessionUser) {
			console.log(sessionUser);
			toast.success($i18n.t(`You're now logged in.`));
			if (sessionUser.token) {
				localStorage.token = sessionUser.token;
			}

			$socket.emit('user-join', { auth: { token: sessionUser.token } });
			await user.set(sessionUser);
			await config.set(await getBackendConfig(sessionUser.token ?? localStorage.token));

			// Replace, don't push: a sign-in page left behind in the history bounces Back
			// forward again (signed in → off to the target). Framed by the Bookmark Hub, that
			// entry sits in the Hub tab's own history, so Back could never leave the Hub.
			// signed in: the stars jump as the stage pushes through into the app
			warp(1100);
			if (typeof document.startViewTransition === 'function' && !prefersReducedMotion() && !document.hidden) {
				document.documentElement.classList.add('halo-auth-vt');
				const transition = guardViewTransition(
					document.startViewTransition(() => goto(redirectTarget(), { replaceState: true }))
				);
				transition.finished.catch(() => {}).finally(() => document.documentElement.classList.remove('halo-auth-vt'));
			} else goto(redirectTarget(), { replaceState: true });
		}
	};

	// A refused sign-in nudges the form sideways once (halo.css .halo-shake; off with reduced motion).
	let formElement = null;
	const nudge = () => {
		if (!formElement) return;
		formElement.classList.remove('halo-shake');
		void formElement.offsetWidth;
		formElement.classList.add('halo-shake');
	};

	const signInHandler = async () => {
		const sessionUser = await userSignIn(email, password).catch((error) => {
			toast.error(formatError(error));
			nudge();
			return null;
		});

		await setSessionUser(sessionUser);
	};

	const signUpHandler = async () => {
		const sessionUser = await userSignUp(name, email, password, generateInitialsImage(name)).catch(
			(error) => {
				toast.error(formatError(error));
				nudge();
				return null;
			}
		);

		await setSessionUser(sessionUser);
	};

	const ldapSignInHandler = async () => {
		const sessionUser = await ldapUserSignIn(ldapUsername, password).catch((error) => {
			toast.error(formatError(error));
			nudge();
			return null;
		});
		await setSessionUser(sessionUser);
	};

	const submitHandler = async () => {
		if (mode === 'ldap') {
			await ldapSignInHandler();
		} else if (mode === 'signin') {
			await signInHandler();
		} else {
			await signUpHandler();
		}
	};

	const checkOauthCallback = async () => {
		if (!$page.url.hash) {
			return;
		}
		const hash = $page.url.hash.substring(1);
		if (!hash) {
			return;
		}
		const params = new URLSearchParams(hash);
		const token = params.get('token');
		if (!token) {
			return;
		}
		const sessionUser = await getSessionUser(token).catch((error) => {
			toast.error(formatError(error));
			return null;
		});
		if (!sessionUser) {
			return;
		}
		localStorage.token = token;
		await setSessionUser(sessionUser);
	};

	// Framed by the Bookmark Hub: its unlocked administrator arrives with a
	// single-use ticket in the address fragment (see $lib/utils/hub-embed).
	//
	// hubSigningIn holds from the moment the ticket is traded until the app
	// replaces this page. The trade is quick, but the app's code still has to
	// arrive after it — seconds over a slow link — and showing the sign-in form
	// meanwhile looks exactly like a failed sign-in, which invites a reload.
	let hubSigningIn = false;

	/** @param {string} ticket @returns {Promise<boolean>} signed in */
	const signInWithHubTicket = async (ticket) => {
		const sessionUser = await exchangeHubTicket(ticket).catch((error) => {
			// Expired, already used, or the two deployments disagree on the secret.
			// Nothing is broken for the person in front of the screen: the form below still works.
			console.warn('Bookmark Hub ticket refused:', error?.reason ?? error?.error ?? error);
			toast.info(
				$i18n.t('Automatic sign-in from the Bookmark Hub did not go through. Please sign in here.')
			);
			return null;
		});
		await setSessionUser(sessionUser);
		return !!sessionUser;
	};

	let onboarding = false;

	async function setLogoImage() {
		await tick();
		const logo = document.getElementById('logo');

		if (logo) {
			const isDarkMode = document.documentElement.classList.contains('dark');

			if (isDarkMode) {
				const darkImage = new Image();
				darkImage.src = '/static/favicon-dark.png';

				darkImage.onload = () => {
					logo.src = '/static/favicon-dark.png';
					logo.style.filter = ''; // Ensure no inversion is applied if favicon-dark.png exists
				};

				darkImage.onerror = () => {
					logo.style.filter = 'invert(1)'; // Invert image if favicon-dark.png is missing
				};
			}
		}
	}

	onMount(async () => {
		// Single-use and short-lived: take it out of the address before anything else.
		const hubTicket = takeHubTicket();

		if ($user !== undefined) {
			goto(redirectTarget(), { replaceState: true });
		}
		await checkOauthCallback();
		// Already signed in (a password session is longer than the one a ticket opens): leave it alone.
		hubSigningIn = !!hubTicket && $user === undefined;

		loaded = true;
		setLogoImage();

		if (hubSigningIn) {
			// Refused: the form below takes over, with a note saying why.
			hubSigningIn = await signInWithHubTicket(hubTicket);
		}

		if (($config?.features.auth_trusted_header ?? false) || $config?.features.auth === false) {
			await signInHandler();
		} else {
			onboarding = $config?.onboarding ?? false;
		}
	});
</script>

<svelte:head>
	<title>
		{`${$WEBUI_NAME}`}
	</title>
</svelte:head>

<OnBoarding
	bind:show={onboarding}
	getStartedHandler={() => {
		onboarding = false;
		mode = $config?.features.enable_ldap ? 'ldap' : 'signup';
	}}
/>

<div class="halo-auth">
	<div class="w-full absolute top-0 left-0 right-0 h-8 drag-region" />

	{#if loaded}
		<!-- The stage: the Halo mark at full size, its light turning slowly, leaning a little
		     toward the pointer. Decorative; the caption is the only text in it. -->
		<section
			class="halo-auth__stage"
			style="--mx: {pointerX}; --my: {pointerY}"
			on:pointermove={onStagePointer}
			on:pointerleave={() => {
				pointerX = 0;
				pointerY = 0;
			}}
		>
			<div class="halo-auth__stars" aria-hidden="true"><StarField tone="dark" /></div>
			<div class="halo-auth__scene" aria-hidden="true"><HaloConstellation /></div>
			<div class="halo-auth__caption">
				<div class="halo-auth__eyebrow">
					<span class="halo-presence" aria-hidden="true"></span>
					{$WEBUI_NAME}
				</div>
				<p class="halo-auth__headline">{$i18n.t('Ask. Research. Collaborate.')}</p>
				<p class="halo-auth__lede">
					{$i18n.t('Your models, agents and teams, gathered in one halo.')}
				</p>
			</div>
		</section>

		<main class="halo-auth__panel">
			<div class="halo-auth__brand">
				<svg class="halo-mark" viewBox="0 0 120 120" aria-hidden="true">
					<path class="halo-mark__ring" d="M60 17 A43 43 0 1 1 17 60" />
					<circle class="halo-mark__core" cx="60" cy="60" r="13" />
				</svg>
				<span class="halo-wordmark">{$WEBUI_NAME}</span>
			</div>

			<div class="halo-auth__body font-primary">
			{#if hubSigningIn || ($config?.features.auth_trusted_header ?? false) || $config?.features.auth === false}
				<div class="w-full">
					<div
						class="flex items-center justify-center gap-3 text-xl sm:text-2xl text-center font-semibold dark:text-gray-200"
					>
						<div>
							{$i18n.t('Signing in to {{WEBUI_NAME}}', { WEBUI_NAME: $WEBUI_NAME })}
						</div>

						<div>
							<Spinner />
						</div>
					</div>
				</div>
			{:else}
				<div class="w-full text-gray-900 dark:text-gray-100">
					<form
						bind:this={formElement}
						class=" flex flex-col justify-center"
						on:animationend={() => formElement?.classList.remove('halo-shake')}
						on:submit={(e) => {
							e.preventDefault();
							submitHandler();
						}}
					>
						<div class="mb-1">
							<h1 class="halo-auth__title">
								{#if $config?.onboarding ?? false}
									{$i18n.t(`Get started with {{WEBUI_NAME}}`, { WEBUI_NAME: $WEBUI_NAME })}
								{:else if mode === 'ldap'}
									{$i18n.t(`Sign in to {{WEBUI_NAME}} with LDAP`, { WEBUI_NAME: $WEBUI_NAME })}
								{:else if mode === 'signin'}
									{$i18n.t(`Sign in to {{WEBUI_NAME}}`, { WEBUI_NAME: $WEBUI_NAME })}
								{:else}
									{$i18n.t(`Sign up to {{WEBUI_NAME}}`, { WEBUI_NAME: $WEBUI_NAME })}
								{/if}
							</h1>

							{#if $config?.onboarding ?? false}
								<div class=" mt-2 text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
									ⓘ {$WEBUI_NAME}
									{$i18n.t(
										'does not make any external connections, and your data stays securely on your locally hosted server.'
									)}
								</div>
							{/if}
						</div>

						{#if $config?.features.enable_login_form || $config?.features.enable_ldap}
							<div class="flex flex-col gap-3 mt-7">
								{#if mode === 'signup'}
									<div>
										<div class="halo-label">{$i18n.t('Name')}</div>
										<input
											bind:value={name}
											type="text"
											class="halo-input"
											autocomplete="name"
											placeholder={$i18n.t('Enter Your Full Name')}
											required
										/>
									</div>
								{/if}

								{#if mode === 'ldap'}
									<div>
										<div class="halo-label">{$i18n.t('Username')}</div>
										<input
											bind:value={ldapUsername}
											type="text"
											class="halo-input"
											autocomplete="username"
											name="username"
											placeholder={$i18n.t('Enter Your Username')}
											required
										/>
									</div>
								{:else}
									<div>
										<div class="halo-label">{$i18n.t('Email')}</div>
										<input
											bind:value={email}
											type="email"
											class="halo-input"
											autocomplete="email"
											name="email"
											placeholder={$i18n.t('Enter Your Email')}
											required
										/>
									</div>
								{/if}

								<div>
									<div class="halo-label">{$i18n.t('Password')}</div>

									<input
										bind:value={password}
										type="password"
										class="halo-input"
										placeholder={$i18n.t('Enter Your Password')}
										autocomplete="current-password"
										name="current-password"
										required
									/>
								</div>
							</div>
						{/if}
						<div class="mt-6">
							{#if $config?.features.enable_login_form || $config?.features.enable_ldap}
								{#if mode === 'ldap'}
									<button
										class="halo-btn-primary group w-full"
										type="submit"
									>
										<span>{$i18n.t('Authenticate')}</span>
										<svg class="halo-btn-arrow" viewBox="0 0 16 16" fill="none" aria-hidden="true">
											<path d="M3 8h9m-3.5-4 4 4-4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
										</svg>
									</button>
								{:else}
									<button
										class="halo-btn-primary group w-full"
										type="submit"
									>
										<span
											>{mode === 'signin'
												? $i18n.t('Sign in')
												: ($config?.onboarding ?? false)
													? $i18n.t('Create Admin Account')
													: $i18n.t('Create Account')}</span
										>
										<svg class="halo-btn-arrow" viewBox="0 0 16 16" fill="none" aria-hidden="true">
											<path d="M3 8h9m-3.5-4 4 4-4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
										</svg>
									</button>

									{#if $config?.features.enable_signup && !($config?.onboarding ?? false)}
										<div class="mt-5 text-[13px] text-center text-gray-500 dark:text-gray-400">
											{mode === 'signin'
												? $i18n.t("Don't have an account?")
												: $i18n.t('Already have an account?')}

											<button
												class="halo-link"
												type="button"
												on:click={() => {
													if (mode === 'signin') {
														mode = 'signup';
													} else {
														mode = 'signin';
													}
												}}
											>
												{mode === 'signin' ? $i18n.t('Sign up') : $i18n.t('Sign in')}
											</button>
										</div>
									{/if}
								{/if}
							{/if}
						</div>
					</form>

					{#if Object.keys($config?.oauth?.providers ?? {}).length > 0}
						<div class="inline-flex items-center justify-center w-full">
							<hr class="flex-1 h-px my-5 border-0 bg-[var(--surface-border)]" />
							{#if $config?.features.enable_login_form || $config?.features.enable_ldap}
								<span
									class="px-3 text-xs font-medium uppercase tracking-wider text-gray-400 dark:text-gray-500 bg-transparent"
									>{$i18n.t('or')}</span
								>
							{/if}

							<hr class="flex-1 h-px my-5 border-0 bg-[var(--surface-border)]" />
						</div>
						<div class="flex flex-col space-y-2">
							{#if $config?.oauth?.providers?.google}
								<button
									class="halo-btn-secondary w-full"
									on:click={() => {
										window.location.href = `${WEBUI_BASE_URL}/oauth/google/login`;
									}}
								>
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" class="size-6 mr-3">
										<path
											fill="#EA4335"
											d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
										/><path
											fill="#4285F4"
											d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
										/><path
											fill="#FBBC05"
											d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
										/><path
											fill="#34A853"
											d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
										/><path fill="none" d="M0 0h48v48H0z" />
									</svg>
									<span>{$i18n.t('Continue with {{provider}}', { provider: 'Google' })}</span>
								</button>
							{/if}
							{#if $config?.oauth?.providers?.microsoft}
								<button
									class="halo-btn-secondary w-full"
									on:click={() => {
										window.location.href = `${WEBUI_BASE_URL}/oauth/microsoft/login`;
									}}
								>
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 21 21" class="size-6 mr-3">
										<rect x="1" y="1" width="9" height="9" fill="#f25022" /><rect
											x="1"
											y="11"
											width="9"
											height="9"
											fill="#00a4ef"
										/><rect x="11" y="1" width="9" height="9" fill="#7fba00" /><rect
											x="11"
											y="11"
											width="9"
											height="9"
											fill="#ffb900"
										/>
									</svg>
									<span>{$i18n.t('Continue with {{provider}}', { provider: 'Microsoft' })}</span>
								</button>
							{/if}
							{#if $config?.oauth?.providers?.github}
								<button
									class="halo-btn-secondary w-full"
									on:click={() => {
										window.location.href = `${WEBUI_BASE_URL}/oauth/github/login`;
									}}
								>
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" class="size-6 mr-3">
										<path
											fill="currentColor"
											d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.92 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57C20.565 21.795 24 17.31 24 12c0-6.63-5.37-12-12-12z"
										/>
									</svg>
									<span>{$i18n.t('Continue with {{provider}}', { provider: 'GitHub' })}</span>
								</button>
							{/if}
							{#if $config?.oauth?.providers?.oidc}
								<button
									class="halo-btn-secondary w-full"
									on:click={() => {
										window.location.href = `${WEBUI_BASE_URL}/oauth/oidc/login`;
									}}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="1.5"
										stroke="currentColor"
										class="size-6 mr-3"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1 1 21.75 8.25Z"
										/>
									</svg>

									<span
										>{$i18n.t('Continue with {{provider}}', {
											provider: $config?.oauth?.providers?.oidc ?? 'SSO'
										})}</span
									>
								</button>
							{/if}
						</div>
					{/if}

					{#if $config?.features.enable_ldap && $config?.features.enable_login_form}
						<div class="mt-2">
							<button
								class="flex justify-center items-center text-xs w-full text-center underline"
								type="button"
								on:click={() => {
									if (mode === 'ldap')
										mode = ($config?.onboarding ?? false) ? 'signup' : 'signin';
									else mode = 'ldap';
								}}
							>
								<span
									>{mode === 'ldap'
										? $i18n.t('Continue with Email')
										: $i18n.t('Continue with LDAP')}</span
								>
							</button>
						</div>
					{/if}
				</div>
			{/if}
			</div>
		</main>
	{/if}
</div>
