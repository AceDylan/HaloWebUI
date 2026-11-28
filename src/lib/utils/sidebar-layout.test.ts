import { describe, expect, it } from 'vitest';
import {
	COMPACT_EXPANDED_HEIGHT_MAX,
	COMPACT_HEIGHT_MAX,
	FOLDABLE_MAX_WIDTH,
	MOBILE_BREAKPOINT,
	TIGHT_HEIGHT_MAX,
	computeSidePopoverPosition,
	resolveInitialAssistantSectionOpen,
	resolveInitialSidebarOpen,
	resolveSidebarLayout
} from './sidebar-layout';

describe('sidebar-layout', () => {
	describe('resolveSidebarLayout standard viewports', () => {
		it('classifies mobile and Fold6 outer screen as drawer mode', () => {
			expect(resolveSidebarLayout({ width: 390, height: 844 })).toEqual({
				mode: 'drawer',
				railDensity: 'compact',
				compactExpanded: true,
				overlayOnExpand: true,
				persistDesktopPreference: false
			});

			expect(resolveSidebarLayout({ width: 373, height: 843 })).toEqual({
				mode: 'drawer',
				railDensity: 'compact',
				compactExpanded: true,
				overlayOnExpand: true,
				persistDesktopPreference: false
			});
		});

		it('classifies Fold6 inner portrait and landscape as foldable-rail compact', () => {
			expect(resolveSidebarLayout({ width: 771, height: 835 })).toEqual({
				mode: 'foldable-rail',
				railDensity: 'compact',
				compactExpanded: true,
				overlayOnExpand: true,
				persistDesktopPreference: false
			});

			expect(resolveSidebarLayout({ width: 835, height: 771 })).toEqual({
				mode: 'foldable-rail',
				railDensity: 'compact',
				compactExpanded: true,
				overlayOnExpand: true,
				persistDesktopPreference: false
			});
		});

		it('switches to tight rail density on ultra-short foldable viewports', () => {
			expect(resolveSidebarLayout({ width: 835, height: 580 })).toEqual({
				mode: 'foldable-rail',
				railDensity: 'tight',
				compactExpanded: true,
				overlayOnExpand: true,
				persistDesktopPreference: false
			});
		});

		it('classifies tablet and desktop viewports accurately (including 1440x800 R2 guard)', () => {
			expect(resolveSidebarLayout({ width: 1024, height: 768 })).toEqual({
				mode: 'desktop',
				railDensity: 'compact',
				compactExpanded: false,
				overlayOnExpand: false,
				persistDesktopPreference: true
			});

			expect(resolveSidebarLayout({ width: 1440, height: 800 })).toEqual({
				mode: 'desktop',
				railDensity: 'compact',
				compactExpanded: false,
				overlayOnExpand: false,
				persistDesktopPreference: true
			});

			expect(resolveSidebarLayout({ width: 1440, height: 900 })).toEqual({
				mode: 'desktop',
				railDensity: 'comfortable',
				compactExpanded: false,
				overlayOnExpand: false,
				persistDesktopPreference: true
			});
		});
	});

	describe('resolveSidebarLayout boundary thresholds', () => {
		it('switches mode at 767/768 and 899/900', () => {
			expect(MOBILE_BREAKPOINT).toBe(768);
			expect(FOLDABLE_MAX_WIDTH).toBe(900);

			expect(resolveSidebarLayout({ width: 767, height: 900 }).mode).toBe('drawer');
			expect(resolveSidebarLayout({ width: 768, height: 900 }).mode).toBe('foldable-rail');
			expect(resolveSidebarLayout({ width: 768, height: 900 }).railDensity).toBe('compact');

			expect(resolveSidebarLayout({ width: 899, height: 900 })).toMatchObject({
				mode: 'foldable-rail',
				railDensity: 'compact',
				compactExpanded: true,
				overlayOnExpand: true,
				persistDesktopPreference: false
			});
			expect(resolveSidebarLayout({ width: 900, height: 900 })).toMatchObject({
				mode: 'desktop',
				railDensity: 'comfortable',
				compactExpanded: false,
				overlayOnExpand: false,
				persistDesktopPreference: true
			});
		});

		it('switches rail density and compactExpanded at 620/621, 760/761, 860/861', () => {
			expect(TIGHT_HEIGHT_MAX).toBe(620);
			expect(COMPACT_EXPANDED_HEIGHT_MAX).toBe(760);
			expect(COMPACT_HEIGHT_MAX).toBe(860);

			expect(resolveSidebarLayout({ width: 1200, height: 620 }).railDensity).toBe('tight');
			expect(resolveSidebarLayout({ width: 1200, height: 621 }).railDensity).toBe('compact');

			expect(resolveSidebarLayout({ width: 1200, height: 760 }).compactExpanded).toBe(true);
			expect(resolveSidebarLayout({ width: 1200, height: 761 }).compactExpanded).toBe(false);

			expect(resolveSidebarLayout({ width: 1200, height: 860 }).railDensity).toBe('compact');
			expect(resolveSidebarLayout({ width: 1200, height: 861 }).railDensity).toBe('comfortable');
		});
	});

	describe('resolveInitialSidebarOpen', () => {
		it('always starts closed below 900px regardless of stored desktop preference', () => {
			const foldable = resolveSidebarLayout({ width: 771, height: 835 });
			const mobile = resolveSidebarLayout({ width: 390, height: 844 });

			expect(resolveInitialSidebarOpen(foldable, 'true')).toBe(false);
			expect(resolveInitialSidebarOpen(foldable, undefined)).toBe(false);
			expect(resolveInitialSidebarOpen(mobile, 'true')).toBe(false);
		});

		it('restores stored preference on desktop (>= 900px) and defaults open', () => {
			const desktop = resolveSidebarLayout({ width: 1440, height: 900 });

			expect(resolveInitialSidebarOpen(desktop, undefined)).toBe(true);
			expect(resolveInitialSidebarOpen(desktop, null)).toBe(true);
			expect(resolveInitialSidebarOpen(desktop, 'true')).toBe(true);
			expect(resolveInitialSidebarOpen(desktop, 'false')).toBe(false);
		});
	});

	describe('resolveInitialAssistantSectionOpen', () => {
		it('respects explicit stored values over compactExpanded default', () => {
			expect(resolveInitialAssistantSectionOpen('true', true)).toBe(true);
			expect(resolveInitialAssistantSectionOpen('false', false)).toBe(false);
			expect(resolveInitialAssistantSectionOpen('true', false)).toBe(true);
			expect(resolveInitialAssistantSectionOpen('false', true)).toBe(false);
		});

		it('defaults collapsed in compactExpanded and open otherwise when unset', () => {
			expect(resolveInitialAssistantSectionOpen(null, true)).toBe(false);
			expect(resolveInitialAssistantSectionOpen(undefined, true)).toBe(false);
			expect(resolveInitialAssistantSectionOpen('', true)).toBe(false);
			expect(resolveInitialAssistantSectionOpen(null, false)).toBe(true);
			expect(resolveInitialAssistantSectionOpen(undefined, false)).toBe(true);
		});
	});

	describe('computeSidePopoverPosition', () => {
		it('places the popover to the right of the trigger with the configured gap', () => {
			const pos = computeSidePopoverPosition(
				{ top: 320, left: 10, right: 50, bottom: 356, width: 40, height: 36 },
				{ width: 220, height: 150 },
				{ width: 771, height: 835 }
			);
			expect(pos).toEqual({ left: 58, top: 320 });
		});

		it('clamps the popover vertically so it never overflows the bottom of a short viewport', () => {
			const pos = computeSidePopoverPosition(
				{ top: 520, left: 10, right: 50, bottom: 552, width: 40, height: 32 },
				{ width: 220, height: 168 },
				{ width: 835, height: 580 }
			);
			// 580 - 168 - 8 = 404
			expect(pos).toEqual({ left: 58, top: 404 });
		});

		it('clamps horizontally and to top margin on tight viewports', () => {
			const pos = computeSidePopoverPosition(
				{ top: -10, left: 200, right: 240, bottom: 26, width: 40, height: 36 },
				{ width: 220, height: 150 },
				{ width: 320, height: 400 }
			);
			// maxLeft = 320 - 220 - 8 = 92; top clamped to margin 8
			expect(pos).toEqual({ left: 92, top: 8 });
		});
	});
});
