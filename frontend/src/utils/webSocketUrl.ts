/** Absolute WebSocket URL of a backend path, on the page's host (the dev server relays it) */
const webSocketUrl = (path: string) => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}`;

export default webSocketUrl;
