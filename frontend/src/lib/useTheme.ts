import { useCallback, useSyncExternalStore } from 'react';

export type Theme = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'app-theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';
const THEME_COLOR: Record<'light' | 'dark', string> = {
  light: '#FAFAFA',
  dark: '#0A0A0A',
};

/**
 * 主题存放在模块级单例里，而不是每个组件各自的 useState。
 * 这样 Sidebar 的切换按钮、App 的初始化、以及其他任何调用方共享同一份状态，
 * 不会出现"两个 useTheme 各自记一份"的漂移。
 */
const listeners = new Set<() => void>();

function supportsMatchMedia(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function';
}

function readStoredTheme(): Theme {
  if (typeof window === 'undefined') return 'system';
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  } catch {
    /* localStorage 被禁用时退回 system */
  }
  return 'system';
}

let currentTheme: Theme = readStoredTheme();

function prefersDark(): boolean {
  return supportsMatchMedia() && window.matchMedia(DARK_QUERY).matches;
}

function resolveIsDark(theme: Theme): boolean {
  return theme === 'system' ? prefersDark() : theme === 'dark';
}

/**
 * 把主题落到 <html> 上：
 * - .dark 类驱动 Tailwind 的 dark 变体
 * - color-scheme 让原生滚动条、表单控件、以及浏览器 UI 跟着变深/变浅
 * - theme-color 让移动端地址栏颜色与页面一致
 */
export function applyTheme(theme: Theme) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  const isDark = resolveIsDark(theme);
  root.classList.toggle('dark', isDark);
  root.style.colorScheme = isDark ? 'dark' : 'light';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', isDark ? THEME_COLOR.dark : THEME_COLOR.light);
}

export function setTheme(theme: Theme) {
  currentTheme = theme;
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* 写入失败不影响当前会话 */
  }
  applyTheme(theme);
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);

  if (!supportsMatchMedia()) {
    return () => {
      listeners.delete(listener);
    };
  }

  // "跟随系统" 时，操作系统切换深浅色需要实时生效
  const media = window.matchMedia(DARK_QUERY);
  const onSystemChange = () => {
    if (currentTheme !== 'system') return;
    applyTheme('system');
    listener();
  };
  media.addEventListener('change', onSystemChange);

  return () => {
    listeners.delete(listener);
    media.removeEventListener('change', onSystemChange);
  };
}

const getSnapshot = () => currentTheme;
const getServerSnapshot = (): Theme => 'system';

// 模块加载时与 index.html 的内联引导脚本对齐（避免首帧闪烁 / 状态不一致）
applyTheme(currentTheme);

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const updateTheme = useCallback((next: Theme) => setTheme(next), []);
  return { theme, setTheme: updateTheme };
}
