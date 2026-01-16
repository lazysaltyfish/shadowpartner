const CACHE_NAME = 'shadow-partner-v1';
const urlsToCache = [
  './',
  './index.html',
  './css/style.css',
  './js/app.js',
  'https://cdn.tailwindcss.com',
  'https://unpkg.com/vue@3/dist/vue.global.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});

self.addEventListener('fetch', event => {
  // Skip API requests - let them go directly to network
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/api') ||
      url.pathname.startsWith('/health') ||
      url.pathname.startsWith('/upload') ||
      url.port === '8000') {
    return;
  }

  event.respondWith(
    caches.match(event.request)
      .then(response => response || fetch(event.request))
  );
});
