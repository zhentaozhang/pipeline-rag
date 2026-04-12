// Admin Auth keys
export const ADMIN_TOKEN_KEY = 'pipeline-rag-admin-token';
export const ADMIN_USER_KEY = 'pipeline-rag-admin-user';

export function getAdminToken(): string {
  return window.localStorage.getItem(ADMIN_TOKEN_KEY) || '';
}

export function clearAdminAuth(): void {
  window.localStorage.removeItem(ADMIN_TOKEN_KEY);
  window.localStorage.removeItem(ADMIN_USER_KEY);
}

export function saveAdminAuth(data: { username: string; token: string }): void {
  window.localStorage.setItem(ADMIN_TOKEN_KEY, data.token);
  window.localStorage.setItem(ADMIN_USER_KEY, data.username);
}

export function isAdminAuthenticated(): boolean {
  return !!getAdminToken();
}
