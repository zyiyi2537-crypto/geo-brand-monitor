import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ADVANCED_MODES, type AdvancedMode, type RerunMode } from './rerunModes';

interface Props {
  mode: RerunMode;
  onSelect: (m: RerunMode) => void;
  isModeLocked: (m: AdvancedMode) => boolean;
}

export function RerunModeDropdown({ mode, onSelect, isModeLocked }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handlePointer = (e: MouseEvent | TouchEvent) => {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handlePointer);
    document.addEventListener('touchstart', handlePointer);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handlePointer);
      document.removeEventListener('touchstart', handlePointer);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  const labelFor = (m: RerunMode): string =>
    m === 'default'
      ? (t('result.header.modeDefault', { defaultValue: '基础 GEO 检测' }) as string)
      : (t(`home.advanced.cards.${m}.title`) as string);

  const currentLocked = mode !== 'default' && isModeLocked(mode);

  const handlePick = (target: RerunMode) => {
    if (target !== 'default' && isModeLocked(target)) return;
    onSelect(target);
    setOpen(false);
  };

  return (
    <div ref={wrapperRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t('result.header.modeLabel', { defaultValue: '检测类型' }) as string}
        title={t('result.header.modeLabel', { defaultValue: '检测类型' }) as string}
        className="flex items-center gap-1.5 px-3 py-2 rounded-full text-xs sm:text-sm text-primary hover:bg-tertiary border-r border-border max-w-[9rem] sm:max-w-[11rem] transition-colors"
      >
        {currentLocked && <LockIcon className="h-3.5 w-3.5 text-secondary shrink-0" />}
        <span className="truncate font-medium">{labelFor(mode)}</span>
        <ChevronDownIcon
          className={`h-3 w-3 text-secondary shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute left-0 top-[calc(100%+6px)] z-30 w-64 bg-card border border-border rounded-2xl shadow-xl py-1.5 animate-fade-in"
        >
          <DropdownItem
            label={labelFor('default')}
            selected={mode === 'default'}
            locked={false}
            onClick={() => handlePick('default')}
          />
          <div className="my-1 mx-3 border-t border-border" />
          {ADVANCED_MODES.map(({ key }) => {
            const locked = isModeLocked(key);
            return (
              <DropdownItem
                key={key}
                label={labelFor(key)}
                selected={mode === key}
                locked={locked}
                tierBadge={locked ? 'pro+' : undefined}
                lockedTip={
                  locked
                    ? (t('result.header.modeLockedHint', { defaultValue: '升级后可用' }) as string)
                    : undefined
                }
                onClick={() => handlePick(key)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

interface DropdownItemProps {
  label: string;
  selected: boolean;
  locked: boolean;
  tierBadge?: string;
  lockedTip?: string;
  onClick: () => void;
}

function DropdownItem({ label, selected, locked, tierBadge, lockedTip, onClick }: DropdownItemProps) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      aria-disabled={locked}
      disabled={locked}
      onClick={onClick}
      title={lockedTip}
      className={`w-full flex items-center gap-2 px-3 py-2 mx-1 text-sm rounded-lg text-left transition-colors ${
        locked
          ? 'opacity-50 cursor-not-allowed text-secondary'
          : selected
            ? 'bg-accent-primary/10 text-primary'
            : 'text-primary hover:bg-tertiary'
      }`}
      style={{ width: 'calc(100% - 0.5rem)' }}
    >
      {locked && <LockIcon className="h-3.5 w-3.5 shrink-0" />}
      <span className="flex-1 truncate">{label}</span>
      {tierBadge && (
        <span className="text-[10px] font-bold uppercase tracking-wider text-muted border border-border rounded-full px-1.5 py-0.5">
          {tierBadge}
        </span>
      )}
      {selected && !locked && !tierBadge && (
        <CheckIcon className="h-3.5 w-3.5 text-accent-primary shrink-0" />
      )}
    </button>
  );
}

function LockIcon({ className }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
      />
    </svg>
  );
}

function ChevronDownIcon({ className }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
    </svg>
  );
}
