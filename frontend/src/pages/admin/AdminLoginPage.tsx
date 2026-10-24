import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { adminAuthApi } from '../../lib/api';
import { saveAdminAuth } from '../../lib/adminAuth';
import { Button } from '../../components/ui/Button';
import { Field, Input } from '../../components/ui/Field';
import { actionFailure } from '../../components/admin/adminFormat';

/** 后台登录：登录成功后回到 redirect 指定的后台页，否则进总览 */
export const AdminLoginPage: React.FC = () => {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin123456');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const navigate = useNavigate();
  const location = useLocation();

  const submitLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!username.trim() || !password.trim()) {
      setError('账号和密码都不能为空。请填写部署环境里配置的后台账号后重试。');
      return;
    }

    setError('');
    setSubmitting(true);
    try {
      const result = await adminAuthApi.login({ username: username.trim(), password: password.trim() });
      saveAdminAuth({ username: result?.username || username.trim(), token: result?.token || '' });

      const redirect = new URLSearchParams(location.search).get('redirect');
      navigate(redirect && redirect.startsWith('/admin') ? redirect : '/admin/dashboard', { replace: true });
    } catch (loginError) {
      setError(actionFailure(loginError, '登录', '请确认账号密码与后端配置一致，然后重试。'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="grid min-h-dvh place-items-center bg-background p-6">
      <div className="grid w-full max-w-[900px] grid-cols-1 overflow-hidden rounded-xl border border-border bg-card shadow-sm md:grid-cols-[1.1fr_0.9fr]">
        <div className="flex flex-col justify-center gap-3 border-b border-border bg-secondary/40 p-8 md:border-b-0 md:border-r">
          <h1 className="text-lg font-semibold text-foreground">文档流水线管理后台</h1>
          <p className="text-xs leading-relaxed text-muted-foreground">
            文档上传、策略配置、索引构建到对话观测，全流程管理。账号密码由当前部署环境配置，登录后才能进入后台。
          </p>
        </div>

        <form className="flex flex-col justify-center gap-4 p-8" onSubmit={submitLogin}>
          <div>
            <p className="text-2xs font-medium uppercase tracking-wider text-primary">后台入口</p>
            <h2 className="mt-1 text-sm font-medium text-foreground">管理台登录</h2>
          </div>

          <Field label="账号" required>
            <Input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="请输入后台账号"
              autoComplete="username"
            />
          </Field>

          <Field label="密码" required>
            <Input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入后台密码"
              autoComplete="current-password"
            />
          </Field>

          {error ? (
            <p className="text-xs text-destructive" role="alert">
              {error}
            </p>
          ) : null}

          <div className="mt-2 flex gap-2">
            <Button variant="outline" className="flex-1" onClick={() => navigate('/chat')}>
              返回聊天
            </Button>
            {/* 表单提交走 submit，Button 默认 type="button"，这里显式声明 */}
            <Button type="submit" className="flex-1" loading={submitting}>
              进入后台
            </Button>
          </div>
        </form>
      </div>
    </section>
  );
};
