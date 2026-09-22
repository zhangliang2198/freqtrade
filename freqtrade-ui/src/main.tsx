import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Semi's React 19 adapter must load before any Semi component renders; it hands
// the component library the React 19 `createRoot` for its portals.
import '@douyinfe/semi-ui/react19-adapter'

// `dist/css/*` is not in semi-ui's `exports` map, so vite.config.ts aliases this
// specifier to the real file on disk.
import '@douyinfe/semi-ui/dist/css/semi.min.css'
// Generated: flattens Semi's decorative palette hues to grey and binds its
// status hues to our up/down/warn tokens. Must load after semi.min.css.
import './styles/semi-palette.css'
import './styles/tokens.css'
import './styles/app.css'

import { App } from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
