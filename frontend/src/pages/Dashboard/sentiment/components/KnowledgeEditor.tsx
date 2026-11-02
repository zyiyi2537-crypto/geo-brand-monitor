import { useState } from 'react';
import { useTranslation } from 'react-i18next';

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

interface Props {
  knowledge: { brand_voice: string; legal_redlines: string; response_playbook: string };
  onChange: (next: Props['knowledge']) => void;
}

type DocKey = 'brand_voice' | 'legal_redlines' | 'response_playbook';

export function KnowledgeEditor({ knowledge, onChange }: Props) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<DocKey | null>(null);
  const [draft, setDraft] = useState('');

  const docs: DocKey[] = ['brand_voice', 'legal_redlines', 'response_playbook'];

  const handleEdit = (k: DocKey) => {
    setEditing(k);
    setDraft(knowledge[k]);
  };
  const handleSave = () => {
    if (!editing) return;
    onChange({ ...knowledge, [editing]: draft });
    setEditing(null);
  };
  const handleCancel = () => setEditing(null);

  if (editing) {
    return (
      <div className="rounded-xl p-4 space-y-3" style={cardStyle}>
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold text-primary">
            📝 {t(`dashboard.sentiment.settings.knowledge.${editing}`)}
          </h4>
          <span className="text-xs text-muted">
            {t('dashboard.sentiment.settings.knowledge.wordCount', { count: draft.length })}
          </span>
        </div>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className="w-full min-h-72 p-3 text-sm font-mono rounded resize-y"
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-color)',
            color: 'var(--text-primary)',
          }}
        />
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleSave}
            className="btn-solid rounded-md px-4 py-1.5 text-sm font-semibold"
          >
            {t('dashboard.sentiment.settings.knowledge.save')}
          </button>
          <button
            type="button"
            onClick={handleCancel}
            className="rounded-md px-4 py-1.5 text-sm font-semibold"
            style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}
          >
            {t('dashboard.sentiment.settings.knowledge.cancel')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {docs.map((k) => (
        <button
          key={k}
          type="button"
          onClick={() => handleEdit(k)}
          className="rounded-xl p-4 text-left hover:-translate-y-0.5 transition-transform"
          style={cardStyle}
        >
          <div className="text-xl mb-2">📝</div>
          <h5 className="text-sm font-semibold text-primary mb-1">
            {t(`dashboard.sentiment.settings.knowledge.${k}`)}
          </h5>
          <p className="text-xs text-muted">
            {t('dashboard.sentiment.settings.knowledge.wordCount', { count: knowledge[k].length })}
          </p>
        </button>
      ))}
    </div>
  );
}
