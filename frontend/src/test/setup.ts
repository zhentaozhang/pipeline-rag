import '@testing-library/jest-dom/vitest';

// Node 22+ 内置实验性 localStorage 与 jsdom 冲突时 clear 方法未实现，提供规范 mock
const storage: Record<string, string> = {};
const localStorageMock: Storage = {
  getItem: (key: string) => storage[key] ?? null,
  setItem: (key: string, value: string) => {
    storage[key] = String(value);
  },
  removeItem: (key: string) => {
    delete storage[key];
  },
  clear: () => {
    for (const key of Object.keys(storage)) {
      delete storage[key];
    }
  },
  get length() {
    return Object.keys(storage).length;
  },
  key: (index: number) => Object.keys(storage)[index] ?? null,
};

Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageMock,
  configurable: true,
  writable: true,
});
