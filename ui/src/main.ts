import '@fontsource-variable/instrument-sans/wght.css';
import '@fontsource/instrument-serif/latin-400.css';
import '@fontsource/instrument-serif/latin-400-italic.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-500.css';
import { mount } from 'svelte';
import './app.css';
import App from './App.svelte';

mount(App, { target: document.getElementById('app')! });
