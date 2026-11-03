import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { locale, t } from './i18n'
import './index.css'

document.documentElement.lang = locale
document.title = t('title')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
