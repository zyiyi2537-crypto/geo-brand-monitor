import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { initI18n } from './i18n'

// Await i18n before first render so no component ever sees raw translation
// keys during mount. initI18n loads exactly one language pack (current
// locale) instead of both, which is the whole point of the split.
initI18n().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
