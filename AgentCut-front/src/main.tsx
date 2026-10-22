import React from 'react';
import ReactDOM from 'react-dom/client';
import 'antd/dist/reset.css';
import '@fontsource/inter/latin-400.css';
import '@fontsource/inter/latin-600.css';
import '@fontsource/inter/latin-700.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-600.css';
import '@fontsource/ibm-plex-mono/latin-700.css';
import './styles/studio.css';
import App from './App';
import { initializeDemo } from './dev/demo';

initializeDemo();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
