import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { applyDocumentLanguage } from './i18n'
import './index.css'

applyDocumentLanguage()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
