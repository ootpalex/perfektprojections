import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

// No StrictMode: the launcher runs the dev server, where StrictMode runs every
// valuation step twice (about 4 s of a load on SSB). User decision 2026-10-04.
ReactDOM.createRoot(document.getElementById('root')).render(
  <BrowserRouter>
    <App />
  </BrowserRouter>
)
