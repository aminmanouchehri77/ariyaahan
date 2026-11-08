(() => {
  const nav = document.querySelector('#primary-nav');
  const toggle = document.querySelector('[data-menu-toggle]');
  const close = document.querySelector('[data-menu-close]');
  if (!nav || !toggle) return;
  const setOpen = (open) => {
    toggle.setAttribute('aria-expanded', String(open));
    nav.classList.toggle('is-open', open);
    document.body.style.overflow = open ? 'hidden' : '';
    if (open) (close || nav.querySelector('a'))?.focus();
  };
  toggle.addEventListener('click', () => setOpen(toggle.getAttribute('aria-expanded') !== 'true'));
  close?.addEventListener('click', () => { setOpen(false); toggle.focus(); });
  nav.addEventListener('click', (event) => { if (event.target.closest('a')) setOpen(false); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && nav.classList.contains('is-open')) { setOpen(false); toggle.focus(); }
  });
  window.matchMedia('(min-width: 1000px)').addEventListener('change', (event) => { if (event.matches) setOpen(false); });
})();

(() => {
  const toggle = document.querySelector('[data-search-toggle]');
  const panel = document.querySelector('#mobile-search');
  if (!toggle || !panel) return;
  toggle.addEventListener('click', () => {
    const open = !panel.classList.contains('is-open');
    panel.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    if (open) panel.querySelector('input')?.focus();
  });
})();

(() => {
  const header = document.querySelector('[data-site-header]');
  const toTop = document.querySelector('[data-to-top]');
  let ticking = false;
  const update = () => {
    const y = window.scrollY;
    header?.classList.toggle('is-scrolled', y > 8);
    toTop?.classList.toggle('is-visible', y > 900);
    ticking = false;
  };
  window.addEventListener('scroll', () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
  toTop?.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  update();
})();

(() => {
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const items = document.querySelectorAll('[data-reveal]');
  if (reduce || !('IntersectionObserver' in window)) {
    items.forEach((item) => item.classList.add('is-visible'));
  } else {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    items.forEach((item) => observer.observe(item));
  }

  // Count-up for hero statistics (numbers rendered server-side first).
  const digits = (value) => String(value).replace(/[0-9]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
  document.querySelectorAll('[data-count]').forEach((element) => {
    const target = parseInt(element.dataset.count, 10);
    if (reduce || !target || target < 4) return;
    const start = performance.now();
    const duration = 1400;
    const step = (now) => {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      element.textContent = digits(Math.round(target * eased).toLocaleString('en-US').replace(/,/g, '٬'));
      if (progress < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });

  // Subtle 3D tilt on cards (pointer devices only).
  if (!reduce && window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
    document.querySelectorAll('[data-tilt]').forEach((card) => {
      card.addEventListener('pointermove', (event) => {
        const rect = card.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width - 0.5;
        const y = (event.clientY - rect.top) / rect.height - 0.5;
        card.style.transform = `perspective(900px) rotateX(${(-y * 7).toFixed(2)}deg) rotateY(${(x * 9).toFixed(2)}deg) translateY(-4px)`;
      });
      card.addEventListener('pointerleave', () => { card.style.transform = ''; });
    });
    const art = document.querySelector('[data-parallax-art]');
    if (art) {
      const img = art.querySelector('img');
      art.addEventListener('pointermove', (event) => {
        const rect = art.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width - 0.5;
        const y = (event.clientY - rect.top) / rect.height - 0.5;
        img.style.transform = `perspective(800px) rotateY(${x * 14}deg) rotateX(${-y * 10}deg) scale(1.04)`;
      });
      art.addEventListener('pointerleave', () => { img.style.transform = ''; });
    }
  }
})();

(() => {
  // Quantity steppers around number inputs.
  document.querySelectorAll('[data-qty]').forEach((wrap) => {
    const input = wrap.querySelector('input');
    wrap.querySelectorAll('button[data-step]').forEach((button) => {
      button.addEventListener('click', () => {
        const step = parseFloat(button.dataset.step);
        const current = parseFloat(input.value || '0');
        const next = Math.max(parseFloat(input.min || '0.001'), Math.round((current + step) * 1000) / 1000);
        input.value = String(next);
        input.dispatchEvent(new Event('change', { bubbles: true }));
      });
    });
  });
})();

(() => {
  // Load the interactive 3D hero only when it can run well.
  const stage = document.querySelector('[data-hero-3d][data-hero-src]');
  if (!stage) return;
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const saveData = navigator.connection && navigator.connection.saveData;
  if (reduce || saveData) return;
  const load = () => import(stage.dataset.heroSrc).catch(() => {});
  const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 400));
  if (document.readyState === 'complete') idle(load);
  else window.addEventListener('load', () => idle(load), { once: true });
})();

(() => {
  // Auto-submit the bank redirect form.
  const form = document.querySelector('[data-autosubmit]');
  if (form) setTimeout(() => form.submit(), 900);
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

(() => {
  const section = document.querySelector('[data-recently-viewed]');
  const list = section?.querySelector('[data-recently-viewed-list]');
  if (!section || !list) return;

  const storageKey = 'ariaa_recent_products_v1';
  const current = document.querySelector('[data-current-product]');
  const normalize = (items) => (Array.isArray(items) ? items : []).filter((item) => {
    if (!item || typeof item.id !== 'string' || typeof item.name !== 'string' || typeof item.url !== 'string') return false;
    if (!item.name.trim() || item.name.length > 180 || item.id.length > 32) return false;
    try {
      const url = new URL(item.url, window.location.origin);
      return url.origin === window.location.origin && url.pathname.startsWith('/product/');
    } catch (_) {
      return false;
    }
  }).slice(0, 6);

  try {
    let products = normalize(JSON.parse(window.localStorage.getItem(storageKey) || '[]'));
    const currentId = current?.dataset.productId || '';
    list.replaceChildren();
    products.filter((item) => item.id !== currentId).forEach((item) => {
      const link = document.createElement('a');
      link.className = 'recent-product-link';
      link.href = item.url;
      link.textContent = item.name;
      list.append(link);
    });
    section.hidden = list.childElementCount === 0;

    if (current?.dataset.productId && current.dataset.productName && current.dataset.productUrl) {
      const currentProduct = {
        id: current.dataset.productId,
        name: current.dataset.productName,
        url: current.dataset.productUrl,
      };
      products = [currentProduct, ...products.filter((item) => item.id !== currentProduct.id)].slice(0, 6);
      window.localStorage.setItem(storageKey, JSON.stringify(products));
    }
  } catch (_) {
    section.hidden = true;
  }
})();

(() => {
  const dialog = document.querySelector('#command-palette');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const input = dialog.querySelector('[data-palette-input]');
  const results = dialog.querySelector('[data-palette-results]');
  const quick = dialog.querySelector('[data-palette-quick]');
  let timer;
  let active = -1;
  const open = () => {
    if (dialog.open) return;
    dialog.showModal();
    input.value = '';
    results.replaceChildren();
    quick.hidden = false;
    setTimeout(() => input.focus(), 30);
  };
  const options = () => [...results.querySelectorAll('a'), ...(quick.hidden ? [] : quick.querySelectorAll('a'))];
  const highlight = (index) => {
    const list = options();
    if (!list.length) return;
    active = (index + list.length) % list.length;
    list.forEach((item, i) => item.setAttribute('aria-selected', String(i === active)));
    list[active].scrollIntoView({ block: 'nearest' });
  };
  const render = (items) => {
    results.replaceChildren();
    active = -1;
    if (items.length && items[0].corrected) {
      const note = document.createElement('div');
      note.className = 'palette__corrected';
      note.textContent = `نتایج برای «${items[0].corrected}»`;
      results.append(note);
    }
    items.forEach((item) => {
      const link = document.createElement('a');
      link.href = item.url;
      link.setAttribute('role', 'option');
      const text = document.createElement('span');
      const strong = document.createElement('strong');
      strong.textContent = item.label;
      const small = document.createElement('small');
      small.textContent = item.detail || '';
      text.append(strong, small);
      link.append(text);
      results.append(link);
    });
    const all = document.createElement('a');
    all.href = `${dialog.dataset.searchUrl}?q=${encodeURIComponent(input.value.trim())}`;
    all.textContent = `همهٔ نتایج برای «${input.value.trim()}»`;
    results.append(all);
    quick.hidden = true;
  };
  input.addEventListener('input', () => {
    clearTimeout(timer);
    const query = input.value.trim();
    if (query.length < 2) {
      results.replaceChildren();
      quick.hidden = false;
      return;
    }
    timer = setTimeout(async () => {
      try {
        const url = new URL(dialog.dataset.suggestionsUrl, window.location.origin);
        url.searchParams.set('q', query);
        const response = await fetch(url, { headers: { Accept: 'application/json' } });
        if (response.ok) render((await response.json()).results || []);
      } catch (_) { /* offline */ }
    }, 160);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); highlight(active + 1); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); highlight(active - 1); }
    else if (event.key === 'Enter') {
      event.preventDefault();
      const list = options();
      if (active >= 0 && list[active]) window.location.assign(list[active].href);
      else if (input.value.trim()) window.location.assign(`${dialog.dataset.searchUrl}?q=${encodeURIComponent(input.value.trim())}`);
    }
  });
  dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  document.querySelectorAll('[data-palette-open]').forEach((button) => button.addEventListener('click', open));
  document.addEventListener('keydown', (event) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '') || document.activeElement?.isContentEditable;
    if ((event.ctrlKey || event.metaKey) && (event.code === 'KeyK' || event.key.toLowerCase() === 'k')) { event.preventDefault(); open(); }
    else if (event.key === '/' && !typing) { event.preventDefault(); open(); }
  });
})();

document.addEventListener('submit', (event) => {
  const trigger = event.submitter;
  if (trigger?.dataset.confirm && !window.confirm(trigger.dataset.confirm)) event.preventDefault();
});

(() => {
  const bar = document.querySelector('[data-reading-progress]');
  if (!bar) return;
  const update = () => {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    bar.style.transform = `scaleX(${max > 0 ? Math.min(1, window.scrollY / max) : 0})`;
  };
  window.addEventListener('scroll', update, { passive: true });
  update();
})();
(() => {
  const input = document.querySelector('[data-faq-filter]');
  const list = document.querySelector('[data-faq-list]');
  if (!input || !list) return;
  const empty = document.querySelector('[data-faq-empty]');
  const norm = (text) => text.replace(/ي/g, 'ی').replace(/ك/g, 'ک').replace(/‌/g, ' ').toLowerCase();
  input.addEventListener('input', () => {
    const query = norm(input.value.trim());
    let shown = 0;
    list.querySelectorAll('.faq-item').forEach((item) => {
      const match = !query || norm(item.textContent).includes(query);
      item.hidden = !match;
      if (match) shown += 1;
      if (query && match) item.open = true;
    });
    if (empty) empty.hidden = shown > 0;
  });
})();
