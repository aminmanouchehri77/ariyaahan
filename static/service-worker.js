const CACHE_NAME = 'ariaa-shell-v5';
const SHELL_ASSETS = [
  '/offline/',
  '/static/core/css/site.css',
  '/static/core/js/site.js',
  '/static/core/icons/icon-192.png',
  '/static/core/icons/icon-512.png',
  '/static/core/fonts/estedad-arabic-var.woff2',
  '/static/core/brand/emblem.svg',
  '/static/core/brand/icons.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key.startsWith('ariaa-shell-') && key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(async () => {
        const offlinePage = await caches.match('/offline/');
        return offlinePage || Response.error();
      })
    );
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const fresh = fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        });
        return cached || fresh;
      })
    );
  }
});

self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (_) {
    payload = { body: event.data ? event.data.text() : '' };
  }
  const title = String(payload.title || 'آهن‌آلات آریا').slice(0, 120);
  const body = String(payload.body || 'اعلان تازه‌ای برای شما ثبت شده است.').slice(0, 240);
  const target = new URL(payload.url || '/', self.location.origin);
  const safeUrl = target.origin === self.location.origin ? target.href : self.location.origin + '/';
  event.waitUntil(self.registration.showNotification(title, {
    body,
    icon: '/static/core/icons/icon-192.png',
    badge: '/static/core/icons/icon-192.png',
    data: { url: safeUrl },
    dir: 'rtl',
    lang: 'fa-IR',
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL(event.notification.data && event.notification.data.url || '/', self.location.origin);
  const safeUrl = target.origin === self.location.origin ? target.href : self.location.origin + '/';
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
    for (const client of clients) {
      if (new URL(client.url).origin === self.location.origin) {
        client.navigate(safeUrl);
        return client.focus();
      }
    }
    return self.clients.openWindow(safeUrl);
  }));
});
