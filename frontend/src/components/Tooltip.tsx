import type { ReactNode } from 'react';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';

/**
 * Site-themed tooltip wrapper around Radix Tooltip.
 *
 * Single canonical tooltip for the app — use this instead of the browser's
 * native `title` attribute for any hover/focus hint that should match the
 * dark theme and survive edge-flipping, Portal z-index escape, Esc-to-close,
 * and screen-reader aria-describedby.
 *
 * Pass `disabled={true}` to skip rendering the trigger wrapper entirely —
 * useful for empty-state tiles where hover should be inert.
 */
export function Tooltip({
  content,
  children,
  disabled = false,
  side = 'top',
  align = 'center',
  delayDuration = 200,
}: {
  content: ReactNode;
  children: ReactNode;
  disabled?: boolean;
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
  delayDuration?: number;
}) {
  if (disabled) {
    return <>{children}</>;
  }

  return (
    <TooltipPrimitive.Provider delayDuration={delayDuration} skipDelayDuration={100}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            side={side}
            align={align}
            sideOffset={6}
            collisionPadding={12}
            className="z-[200] max-w-xs max-h-[60vh] overflow-y-auto rounded-lg border px-3 py-2 text-xs leading-relaxed shadow-xl"
            style={{
              background: 'var(--bg-card)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-primary)',
            }}
          >
            {content}
            <TooltipPrimitive.Arrow
              width={10}
              height={5}
              style={{ fill: 'var(--bg-card)' }}
            />
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}
