/* SBF Journal — Service Worker (PWA + Web Push) */
'use strict';

const CACHE_NAME = 'sbf-v9';
const APP_SHELL = [
  '/journal.html',
  '/assets/design.css',
  '/assets/i18n.js',
  '/assets/sbf-header.js',
  '/assets/sbf-journal.js',
  '/assets/sbf-profile.js',
  '/assets/icons/icon-192.png',
  '/manifest.json',
];

// Установка: кэшируем app-shell
self.addEventListener('install', function (e) {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(APP_SHELL).catch(function () {});
    })
  );
});

// Активация: удаляем старые кэши
self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) { return k !== CACHE_NAME; })
            .map(function (k) { return caches.delete(k); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

// Fetch: stale-while-revalidate для статики, network-only для API
self.addEventListener('fetch', function (e) {
  var url = new URL(e.request.url);

  // API и auth — всегда сеть
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/api')) {
    return;
  }

  // HTML-страницы (навигация) — всегда сеть в первую очередь. Раньше эти
  // запросы шли по тому же "stale-while-revalidate", что и статика ниже:
  // return cached || networkFetch — при наличии кэша ответ уходил СРАЗУ из
  // кэша, а свежая версия оседала в Cache Storage только "на следующий раз",
  // который для конкретного URL никогда не наступал повторно с точки зрения
  // пользователя (каждый визит на тот же chart.html снова получал старую
  // закэшированную версию). Для страниц, которые правятся по нескольку раз
  // в день (chart.html и т.п.), это выглядело как баг, который не чинится.
  // Кэш здесь остаётся только офлайн-фоллбеком, не источником правды.
  var isNavigation = e.request.mode === 'navigate' ||
    (e.request.destination === 'document') ||
    /\.html(\?|$)/.test(url.pathname + url.search) || url.pathname.endsWith('/');
  if (isNavigation && e.request.method === 'GET') {
    e.respondWith(
      fetch(e.request).then(function (response) {
        if (response && response.status === 200) {
          caches.open(CACHE_NAME).then(function (cache) { cache.put(e.request, response.clone()); });
        }
        return response;
      }).catch(function () {
        return caches.open(CACHE_NAME).then(function (cache) {
          return cache.match(e.request).then(function (cached) {
            return cached || new Response(
              '<html><body style="font-family:system-ui;padding:24px"><h2>SBF Journal</h2>' +
              '<p style="color:#666">Нет соединения. Данные будут доступны после подключения.</p></body></html>',
              { headers: { 'Content-Type': 'text/html' } }
            );
          });
        });
      })
    );
    return;
  }

  // Прочая статика (JS/CSS/иконки) — NETWORK-FIRST, кэш только офлайн-фоллбек.
  // Раньше было stale-while-revalidate («отдать кэш сразу, обновить в фоне на
  // следующий раз»), с обоснованием «файлы версионируются через ?v=N». Но
  // ключевые файлы (grafik-engine.js) подключаются БЕЗ ?v= — их правки не
  // доходили до пользователя бесконечно: старый движок → нет живого чарта, не
  // грузится M1/M5, старые баги форматирования. Свежесть кода важнее экономии
  // одной сетевой загрузки; офлайн по-прежнему отдаётся из кэша.
  if (e.request.method === 'GET') {
    e.respondWith(
      fetch(e.request).then(function (response) {
        if (response && response.status === 200) {
          var copy = response.clone();
          caches.open(CACHE_NAME).then(function (cache) { cache.put(e.request, copy); });
        }
        return response;
      }).catch(function () {
        return caches.open(CACHE_NAME).then(function (cache) { return cache.match(e.request); });
      })
    );
  }
});

// ── Push event ────────────────────────────────────────────────────────────────
self.addEventListener('push', function (e) {
  var data = {};
  try {
    data = e.data ? e.data.json() : {};
  } catch (_) {
    data = { title: 'SBF Journal', body: e.data ? e.data.text() : '' };
  }

  var title   = data.title || 'SBF Journal';
  var options = {
    body:    data.body  || '',
    icon:    data.icon  || '/assets/icon-192.png',
    badge:   '/assets/icon-72.png',
    tag:     data.tag   || 'sbf-alert',
    renotify: false,
    data:    { url: data.url || '/journal.html' },
    actions: data.actions || [],
  };

  e.waitUntil(self.registration.showNotification(title, options));
});

// ── Notification click ────────────────────────────────────────────────────────
self.addEventListener('notificationclick', function (e) {
  e.notification.close();
  var targetUrl = (e.notification.data && e.notification.data.url) || '/journal.html';

  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(function (clients) {
        for (var i = 0; i < clients.length; i++) {
          var c = clients[i];
          if (c.url.includes('/journal') && 'focus' in c) {
            return c.focus();
          }
        }
        if (self.clients.openWindow) {
          return self.clients.openWindow(targetUrl);
        }
      })
  );
});
