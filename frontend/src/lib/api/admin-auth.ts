import { requestApiEnvelope, requestJson, unwrapApiResponse } from '../http/client';

export const adminAuthApi = {
  login(payload: {
    username: string;
    password: string;
  }): Promise<{
    username: string;
    token: string;
    tokenType: string;
    tokenExpireMinutes: number;
  }> {
    return requestApiEnvelope<
      { username: string; token: string; tokenType: string; tokenExpireMinutes: number }
    >('/admin/auth/login', {
      method: 'POST',
      body: payload
    });
  },

  logout() {
    return requestApiEnvelope('/admin/auth/logout', {
      method: 'POST',
      body: {}
    });
  },

  currentUser(): Promise<{ username: string }> {
    return requestJson<{ code: number; data: { username: string }; message: string | null }>(
      '/admin/auth/me'
    ).then((payload) => unwrapApiResponse<{ username: string }>(payload));
  }
};
