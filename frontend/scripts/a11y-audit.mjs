#!/usr/bin/env node
/**
 * 前端可访问性 / 渲染回归审计
 *
 * 为什么需要它：项目里没有任何前端 CI 门禁，颜色对比度、按钮可读名称、
 * 表单标签这类问题靠肉眼在深浅两套主题下翻 18 个页面基本不可能覆盖。
 * 这个脚本用无头 Chrome 走真实 DOM + 计算样式，把可测的部分测掉。
 *
 * 用法：
 *   cd frontend && ./node_modules/.bin/vite build && ./node_modules/.bin/vite preview --port 4173 --strictPort &
 *   node scripts/a11y-audit.mjs                # 全量路由，浅色+深色
 *   node scripts/a11y-audit.mjs --only /chat   # 只跑部分路由
 *
 * 输出：控制台摘要 + /tmp/a11y-audit.json 明细。有硬失败时 exit 1。
 */
import fs from 'node:fs';
import puppeteer from 'puppeteer';

const BASE = process.env.AUDIT_BASE_URL || 'http://127.0.0.1:4173';
const CHROME =
  process.env.CHROME_PATH ||
  '/Users/zhentao/.cache/puppeteer/chrome-headless-shell/mac_arm-155.0.8059.39/chrome-headless-shell-mac-arm64/chrome-headless-shell';

const ROUTES = [
  '/chat',
  '/admin/login',
  '/admin/dashboard',
  '/admin/documents',
  '/admin/documents/center',
  '/admin/knowledge-route',
  '/admin/observability',
  '/admin/evaluation',
  '/admin/metrics',
  '/admin/traces',
];

const THEMES = ['light', 'dark'];

/** 只对明显的"看似有内容其实为空"做兜底，避免页面因后端缺失直接白屏 */
const EMPTY = JSON.stringify({});

const argOnly = process.argv.indexOf('--only');
const only = argOnly > -1 ? process.argv[argOnly + 1] : null;
const routes = only ? [only] : ROUTES;

/**
 * 在页面里跑：遍历所有可见文本节点，算出真实前景/背景（逐级混合半透明背景），
 * 再换算对比度。返回失败项而不是在页面内判定，方便统一格式化。
 */
function collectInPage() {
  // 这些工具函数必须定义在被 evaluate 的函数内部：page.evaluate 只序列化函数体本身
  const parseColor = (input) => {
    if (!input) return null;
    const m = input.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const parts = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    if (parts.length < 3) return null;
    const [r, g, b] = parts;
    const a = parts.length > 3 ? parts[3] : 1;
    return { r, g, b, a };
  };
  const blend = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1,
  });
  const luminance = ({ r, g, b }) => {
    const toLin = (v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * toLin(r) + 0.7152 * toLin(g) + 0.0722 * toLin(b);
  };
  const contrast = (fg, bg) => {
    const l1 = luminance(fg);
    const l2 = luminance(bg);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  };

  const out = { contrast: [], names: [], labels: [], images: [], headings: [], dupIds: [], targets: [], lang: document.documentElement.lang };

  const isVisible = (el) => {
    if (!el || !(el instanceof Element)) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
    if (el.getClientRects().length === 0) return false;
    // sr-only：1px 裁剪盒，视觉上不可见，不参与对比度
    if (cs.clip !== 'auto' && /rect\(0px/.test(cs.clip)) return false;
    if (cs.clipPath && cs.clipPath.includes('inset(50%)')) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) return false;
    return true;
  };

  const bgOf = (el) => {
    const layers = [];
    let node = el;
    while (node && node instanceof Element) {
      const cs = getComputedStyle(node);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') layers.push({ image: cs.backgroundImage });
      const c = cs.backgroundColor;
      if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') layers.push({ color: c });
      node = node.parentElement;
    }
    return layers;
  };

  const pathOf = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 4) {
      let s = node.tagName.toLowerCase();
      if (node.className && typeof node.className === 'string') {
        const cls = node.className.trim().split(/\s+/).slice(0, 3).join('.');
        if (cls) s += '.' + cls;
      }
      parts.unshift(s);
      node = node.parentElement;
    }
    return parts.join(' > ');
  };

  const text = (el) => (el.textContent || '').trim().slice(0, 60);

  // ---- 文本对比度 ----
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  let tn;
  while ((tn = walker.nextNode())) {
    if (!tn.nodeValue || !tn.nodeValue.trim()) continue;
    const el = tn.parentElement;
    if (!el || seen.has(el)) continue;
    if (!isVisible(el)) continue;
    const cs = getComputedStyle(el);
    const fg = parseColor(cs.color);
    if (!fg) continue;
    const layers = bgOf(el);
    if (layers.some((l) => l.image)) continue; // 有背景图/渐变时无法可靠计算，跳过
    let bg = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = layers.length - 1; i >= 0; i -= 1) {
      const c = parseColor(layers[i].color);
      if (c) bg = blend(c, bg);
    }
    seen.add(el);
    const merged = fg.a < 1 ? blend(fg, bg) : fg;
    const ratio = contrast(merged, bg);
    const size = parseFloat(cs.fontSize);
    const weight = Number(cs.fontWeight) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const min = large ? 3 : 4.5;
    if (ratio + 0.05 < min) {
      out.contrast.push({
        ratio: Math.round(ratio * 100) / 100,
        min,
        size,
        weight,
        color: cs.color,
        text: text(el),
        path: pathOf(el),
      });
    }
  }

  // ---- 可交互元素可读名称 ----
  const nameOf = (el) =>
    (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '').trim() ||
    (el.getAttribute('aria-labelledby') ? 'labelledby' : '') ||
    (el.querySelector('svg title') ? 'svg-title' : '');

  document.querySelectorAll('button, a[href], [role="button"], [role="tab"], [role="menuitem"]').forEach((el) => {
    if (!isVisible(el)) return;
    if (!nameOf(el)) {
      out.names.push({ tag: el.tagName.toLowerCase(), path: pathOf(el), html: el.outerHTML.slice(0, 160) });
    }
  });

  // ---- 表单控件标签 ----
  document.querySelectorAll('input:not([type="hidden"]), select, textarea').forEach((el) => {
    if (!isVisible(el)) return;
    const id = el.id;
    const hasLabel =
      (id && document.querySelector('label[for="' + CSS.escape(id) + '"]')) ||
      el.closest('label') ||
      el.getAttribute('aria-label') ||
      el.getAttribute('aria-labelledby') ||
      el.getAttribute('title');
    if (!hasLabel) out.labels.push({ tag: el.tagName.toLowerCase(), path: pathOf(el), html: el.outerHTML.slice(0, 160) });
  });

  // ---- 图片 alt ----
  document.querySelectorAll('img').forEach((el) => {
    if (!isVisible(el)) return;
    if (!el.hasAttribute('alt')) out.images.push({ path: pathOf(el), html: el.outerHTML.slice(0, 160) });
  });

  // ---- 标题层级 ----
  const levels = [];
  document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach((el) => {
    if (!isVisible(el)) return;
    levels.push({ level: Number(el.tagName[1]), text: text(el) });
  });
  for (let i = 1; i < levels.length; i += 1) {
    if (levels[i].level - levels[i - 1].level > 1) {
      out.headings.push({ from: levels[i - 1], to: levels[i] });
    }
  }

  // ---- 重复 id ----
  const counts = new Map();
  document.querySelectorAll('[id]').forEach((el) => counts.set(el.id, (counts.get(el.id) || 0) + 1));
  counts.forEach((n, id) => {
    if (n > 1) out.dupIds.push({ id, count: n });
  });

  // ---- 触控目标尺寸（WCAG 2.2 AA 2.5.8 最小 24×24）----
  document.querySelectorAll('button, a[href], [role="button"]').forEach((el) => {
    if (!isVisible(el)) return;
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) {
      out.targets.push({
        w: Math.round(r.width),
        h: Math.round(r.height),
        path: pathOf(el),
        text: text(el),
      });
    }
  });

  return out;
}

function summarize(rows) {
  const total = (key) => rows.reduce((n, r) => n + (r.issues[key]?.length || 0), 0);
  return {
    contrast: total('contrast'),
    names: total('names'),
    labels: total('labels'),
    images: total('images'),
    headings: total('headings'),
    dupIds: total('dupIds'),
    targets: total('targets'),
    consoleErrors: rows.reduce((n, r) => n + r.consoleErrors.length, 0),
  };
}

const main = async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const results = [];

  for (const theme of THEMES) {
    for (const route of routes) {
      const page = await browser.newPage();
      await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
      await page.emulateMediaFeatures([
        { name: 'prefers-color-scheme', value: theme === 'dark' ? 'dark' : 'light' },
      ]);
      await page.evaluateOnNewDocument((t) => {
        try {
          window.localStorage.setItem('app-theme', t);
          // 后台鉴权是纯前端 token 判定，给个占位值以便进到内页
          window.localStorage.setItem('pipeline-rag-admin-token', 'audit-token');
          window.localStorage.setItem('pipeline-rag-admin-user', 'audit');
        } catch {
          /* ignore */
        }
      }, theme);

      const consoleErrors = [];
      const onConsole = (msg) => {
        if (msg.type() === 'error') {
          const t = msg.text();
          // 后端不在线时的网络错误单独归类，不算前端缺陷
          if (/Failed to load resource|net::ERR|404 \(Not Found\)/.test(t)) return;
          consoleErrors.push(t.slice(0, 300));
        }
      };
      page.on('console', onConsole);
      page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + String(e).slice(0, 300)));

      await page.setRequestInterception(true);
      page.on('request', (req) => {
        const url = req.url();
        if (/\/(api|manage|admin\/auth)\//.test(url) && !url.startsWith(BASE)) {
          req.respond({
            status: 200,
            contentType: 'application/json',
            body: EMPTY,
            headers: { 'access-control-allow-origin': '*' },
          });
          return;
        }
        if (url.startsWith(BASE) && /\/(api|manage|admin\/auth)\//.test(url)) {
          req.respond({ status: 200, contentType: 'application/json', body: EMPTY });
          return;
        }
        req.continue();
      });

      try {
        await page.goto(BASE + route, { waitUntil: 'networkidle2', timeout: 30000 });
      } catch (e) {
        consoleErrors.push('goto: ' + String(e).slice(0, 200));
      }
      await new Promise((r) => setTimeout(r, 700));

      const issues = await page.evaluate(collectInPage);

      // 页面是否为"空壳"：主内容区几乎没有可见文字
      const visibleText = await page.evaluate(() => (document.body.innerText || '').trim().length);
      const boundary = await page.evaluate(
        () => /页面出错了/.test(document.body.innerText || '')
      );

      results.push({
        theme,
        route,
        visibleText,
        errorBoundary: boundary,
        issues,
        consoleErrors,
      });
      page.off('console', onConsole);
      await page.close();
    }
  }

  await browser.close();

  fs.writeFileSync('/tmp/a11y-audit.json', JSON.stringify(results, null, 2));

  const totals = summarize(results);
  console.log('\n== 汇总 ==');
  console.log(totals);
  console.log('\n== 每条路由 ==');
  for (const r of results) {
    const c = r.issues;
    const flags = [
      c.contrast.length ? 'contrast=' + c.contrast.length : '',
      c.names.length ? 'name=' + c.names.length : '',
      c.labels.length ? 'label=' + c.labels.length : '',
      c.images.length ? 'img=' + c.images.length : '',
      c.headings.length ? 'heading=' + c.headings.length : '',
      c.dupIds.length ? 'dupId=' + c.dupIds.length : '',
      c.targets.length ? 'target=' + c.targets.length : '',
      r.consoleErrors.length ? 'console=' + r.consoleErrors.length : '',
      r.errorBoundary ? 'ERROR_BOUNDARY' : '',
      r.visibleText < 40 ? 'EMPTY(' + r.visibleText + ')' : '',
    ].filter(Boolean);
    console.log(
      (r.theme + ' ' + r.route).padEnd(40),
      flags.length ? flags.join(' ') : 'ok'
    );
  }

  const hardFailures =
    totals.names + totals.labels + totals.images + totals.dupIds + results.filter((r) => r.errorBoundary).length;
  console.log('\n明细: /tmp/a11y-audit.json');
  process.exitCode = hardFailures > 0 ? 1 : 0;
};

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
