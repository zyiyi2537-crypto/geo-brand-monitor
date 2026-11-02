import { useState, type KeyboardEvent } from 'react';

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  max?: number;
  /** Clickable suggestion chips shown below the input */
  suggestions?: string[];
  /** 已存在 / 已保存的值;输入命中时拒绝添加(value 之外的额外去重源) */
  reserved?: string[];
}

export function TagInput({ value, onChange, placeholder, max, suggestions, reserved }: Props) {
  const [draft, setDraft] = useState('');
  const [dupHint, setDupHint] = useState<string | null>(null);

  const isDuplicate = (v: string): boolean => {
    if (value.includes(v)) return true;
    if (reserved && reserved.includes(v)) return true;
    return false;
  };

  const add = () => {
    const v = draft.trim().replace(/,$/, '');
    if (!v) return;
    if (isDuplicate(v)) {
      setDupHint(v);
      setDraft('');
      return;
    }
    if (max && value.length >= max) return;
    setDupHint(null);
    onChange([...value, v]);
    setDraft('');
  };

  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      add();
    } else if (e.key === 'Backspace' && draft === '' && value.length > 0) {
      onChange(value.slice(0, -1));
    }
  };

  const remove = (i: number) => onChange(value.filter((_, idx) => idx !== i));

  const reservedSet = reserved ? new Set(reserved) : null;
  const remainingSuggestions = suggestions?.filter(s => !value.includes(s) && !(reservedSet && reservedSet.has(s)));

  const addSuggestion = (s: string) => {
    if (max && value.length >= max) return;
    if (isDuplicate(s)) {
      setDupHint(s);
      return;
    }
    setDupHint(null);
    onChange([...value, s]);
  };

  return (
    <div>
      <div
        className="rounded-md flex flex-wrap items-center gap-1.5 p-2 min-h-10"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}
        onClick={(e) => {
          const input = (e.currentTarget as HTMLDivElement).querySelector('input');
          input?.focus();
        }}
      >
        {value.map((tag, i) => (
          <span
            key={`${tag}-${i}`}
            className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs"
            style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)' }}
          >
            {tag}
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); remove(i); }}
              className="text-muted hover:text-primary"
              aria-label="remove"
            >
              ×
            </button>
          </span>
        ))}
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKey}
          onBlur={add}
          placeholder={placeholder}
          className="flex-1 min-w-32 bg-transparent text-sm outline-none border-none"
          style={{ color: 'var(--text-primary)' }}
        />
      </div>
      {dupHint && (
        <div className="text-xs text-rose-500 mt-1">⚠ "{dupHint}" 已存在,不能重复</div>
      )}
      {remainingSuggestions && remainingSuggestions.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1.5">
          {remainingSuggestions.map(s => (
            <button
              key={s}
              type="button"
              onClick={() => addSuggestion(s)}
              className="rounded px-2 py-0.5 text-xs transition-colors"
              style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)', border: '1px dashed var(--border-color)' }}
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
