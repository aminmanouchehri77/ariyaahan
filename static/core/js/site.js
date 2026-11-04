(() => {
  const button = document.querySelector('.menu-toggle');
  const navigation = document.querySelector('#primary-nav');

  if (!button || !navigation) return;

  button.addEventListener('click', () => {
    const isOpen = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!isOpen));
    navigation.classList.toggle('is-open', !isOpen);
  });

  navigation.addEventListener('click', (event) => {
    if (event.target.closest('a')) {
      button.setAttribute('aria-expanded', 'false');
      navigation.classList.remove('is-open');
    }
  });
})();

(() => {
  const filters = document.querySelector('.filter-disclosure');
  if (!filters) return;
  const mobile = window.matchMedia('(max-width: 760px)');
  const syncViewport = () => {
    filters.open = !mobile.matches;
    document.body.classList.remove('filter-drawer-open');
  };
  const syncDrawer = () => {
    document.body.classList.toggle('filter-drawer-open', mobile.matches && filters.open);
  };
  syncViewport();
  filters.addEventListener('toggle', syncDrawer);
  mobile.addEventListener('change', syncViewport);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mobile.matches && filters.open) filters.open = false;
  });
})();

(() => {
  const form = document.querySelector('[data-price-alert-form]');
  const condition = form?.querySelector('[name="condition_type"]');
  if (!condition) return;
  const amount = form.querySelector('[data-alert-field="target_amount"]');
  const percent = form.querySelector('[data-alert-field="percent_change"]');
  const update = () => {
    const isPercent = condition.value === 'percent';
    if (amount) amount.hidden = isPercent;
    if (percent) percent.hidden = !isPercent;
  };
  condition.addEventListener('change', update);
  update();
})();

(() => {
  const shareButton = document.querySelector('[data-share-button]');
  const printButton = document.querySelector('[data-print-button]');
  const status = document.querySelector('[data-share-status]');
  const fallback = document.querySelector('.share-url-fallback');
  if (shareButton) {
    shareButton.hidden = false;
    shareButton.addEventListener('click', async () => {
      const title = shareButton.dataset.shareTitle || document.title;
      const url = shareButton.dataset.shareUrl || window.location.href;
      try {
        if (navigator.share) {
          await navigator.share({ title, url });
        } else if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(url);
          if (status) status.textContent = 'پیوند صفحه کپی شد.';
        } else if (fallback) {
          fallback.hidden = false;
          fallback.focus();
          fallback.select();
          if (status) status.textContent = 'پیوند را کپی کنید.';
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          if (fallback) {
            fallback.hidden = false;
            fallback.focus();
            fallback.select();
          }
          if (status) status.textContent = 'پیوند صفحه آمادهٔ کپی است.';
        }
      }
    });
  }
  if (printButton) {
    printButton.hidden = false;
    printButton.addEventListener('click', () => window.print());
  }
})();

(() => {
  const input = document.querySelector('#site-search');
  const list = document.querySelector('#search-suggestions');
  if (!input || !list) return;

  let timer;
  let activeIndex = -1;
  const close = () => {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    activeIndex = -1;
  };
  const render = (results) => {
    list.replaceChildren();
    results.forEach((result, index) => {
      const link = document.createElement('a');
      link.href = result.url;
      link.id = `search-option-${index}`;
      link.setAttribute('role', 'option');
      link.setAttribute('aria-selected', 'false');
      const title = document.createElement('strong');
      title.textContent = result.label;
      const detail = document.createElement('small');
      detail.textContent = result.detail;
      link.append(title, detail);
      list.append(link);
    });
    list.hidden = results.length === 0;
    input.setAttribute('aria-expanded', String(results.length > 0));
  };
  const load = async () => {
    const query = input.value.trim();
    if (query.length < 2) return close();
    try {
      const url = new URL(input.dataset.suggestionsUrl, window.location.origin);
      url.searchParams.set('q', query);
      const response = await fetch(url, { headers: { 'Accept': 'application/json' } });
      if (!response.ok) return close();
      const payload = await response.json();
      render(payload.results || []);
    } catch (_) {
      close();
    }
  };
  input.addEventListener('input', () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(load, 180);
  });
  input.addEventListener('keydown', (event) => {
    const options = [...list.querySelectorAll('[role="option"]')];
    if (list.hidden || !options.length) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      activeIndex = (activeIndex + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
      options.forEach((option, index) => option.setAttribute('aria-selected', String(index === activeIndex)));
      input.setAttribute('aria-activedescendant', options[activeIndex].id);
    } else if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault();
      window.location.assign(options[activeIndex].href);
    } else if (event.key === 'Escape') {
      close();
    }
  });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.search-form')) close();
  });
  input.addEventListener('blur', () => window.setTimeout(close, 150));
})();

(() => {
  const button = document.querySelector('#push-subscribe-button');
  const status = document.querySelector('#push-subscribe-status');
  if (!button || !status) return;

  const readCookie = (name) => {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : '';
  };
  const decodeKey = (value) => {
    const padded = (value + '='.repeat((4 - value.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/');
    return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  };
  const setStatus = (message, isError = false) => {
    status.textContent = message;
    status.classList.toggle('is-error', isError);
  };
  const postJson = async (url, data) => {
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': readCookie('csrftoken') },
      body: JSON.stringify(data),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || 'درخواست انجام نشد.');
    return body;
  };

  button.addEventListener('click', async () => {
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      setStatus('این مرورگر اعلان وب را پشتیبانی نمی‌کند.', true);
      return;
    }
    button.disabled = true;
    try {
      const registration = await navigator.serviceWorker.ready;
      let subscription = await registration.pushManager.getSubscription();
      if (subscription) {
        await postJson(button.dataset.unsubscribeUrl, { endpoint: subscription.endpoint });
        await subscription.unsubscribe();
        button.textContent = 'فعال‌سازی اعلان مرورگر';
        setStatus('اعلان مرورگر غیرفعال شد.');
        return;
      }
      if (!button.dataset.vapidKey) throw new Error('کلید عمومی اعلان در سرور تنظیم نشده است.');
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') throw new Error('برای فعال‌سازی اعلان، اجازهٔ مرورگر لازم است.');
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: decodeKey(button.dataset.vapidKey),
      });
      await postJson(button.dataset.subscribeUrl, { subscription: subscription.toJSON() });
      button.textContent = 'غیرفعال‌سازی اعلان مرورگر';
      setStatus('اعلان مرورگر فعال شد.');
    } catch (error) {
      setStatus(error.message || 'فعال‌سازی اعلان انجام نشد.', true);
    } finally {
      button.disabled = false;
    }
  });

  navigator.serviceWorker && navigator.serviceWorker.ready.then((registration) =>
    registration.pushManager.getSubscription().then((subscription) => {
      if (subscription) button.textContent = 'غیرفعال‌سازی اعلان مرورگر';
    })
  ).catch(() => {});
})();

(() => {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/service-worker.js', { scope: '/' }).catch(() => {});
    });
  }

  const installButton = document.querySelector('#install-app-button');
  if (!installButton) return;

  let installPrompt;
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    installPrompt = event;
    installButton.hidden = false;
  });

  installButton.addEventListener('click', async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    installButton.hidden = true;
  });

  window.addEventListener('appinstalled', () => {
    installButton.hidden = true;
    installPrompt = null;
  });
})();
