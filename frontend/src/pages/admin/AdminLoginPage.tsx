import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { adminAuthApi, APIError } from '../../lib/api';
import { saveAdminAuth } from '../../lib/adminAuth';

export const AdminLoginPage: React.FC = () => {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin123456');
  const [errorMessage, setErrorMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  
  const navigate = useNavigate();
  const location = useLocation();

  const submitLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage('');
    
    if (!username.trim() || !password.trim()) {
      setErrorMessage('请输入账号和密码。');
      return;
    }

    setSubmitting(true);
    try {
      const result = await adminAuthApi.login({
        username: username.trim(),
        password: password
      });
      
      saveAdminAuth({
        username: result?.username || username.trim(),
        token: result?.token || ''
      });
      
      const searchParams = new URLSearchParams(location.search);
      const redirect = searchParams.get('redirect');
      if (redirect && redirect.startsWith('/admin')) {
        navigate(redirect, { replace: true });
      } else {
        navigate('/admin/dashboard', { replace: true });
      }
    } catch (error) {
      setErrorMessage(
        error instanceof APIError || error instanceof Error
          ? error.message
          : '登录失败，请稍后重试。'
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="relative min-h-screen p-8 md:p-16 grid place-items-center bg-background">
      <div className="w-full max-w-[960px] grid grid-cols-1 md:grid-cols-[1.15fr_0.9fr] rounded-2xl shadow-lg overflow-hidden border border-border/50">
        
        {/* Left Copy Panel */}
        <div className="bg-secondary/30 p-10 flex flex-col justify-center border-b md:border-b-0 md:border-r border-border/50">
          <h1 className="text-2xl font-semibold text-foreground mb-4">
            文档流水线管理后台
          </h1>
           <p className="max-w-[580px] text-[15px] leading-relaxed text-muted-foreground">
              文档上传、策略配置、索引构建到对话观测，全流程管理。账号和密码由当前部署环境配置，登录后才能进入后台。
            </p>
        </div>

        {/* Right Form Panel */}
        <form className="bg-secondary/30 p-10 flex flex-col justify-center" onSubmit={submitLogin}>
          <div className="mb-8">
            <p className="text-primary text-[13px] font-semibold mb-2">后台入口</p>
            <h2 className="text-xl text-foreground font-medium">管理台登录</h2>
          </div>

          <label className="flex flex-col gap-2 mb-5">
            <span className="text-sm font-semibold text-muted-foreground">账号</span>
            <input 
              type="text" 
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入后台账号" 
              autoComplete="username"
              className="w-full border border-border/50 rounded-md px-3 py-2.5 bg-background text-foreground outline-none transition-all focus:border-primary focus:ring-2 focus:ring-primary/20"
            />
          </label>

          <label className="flex flex-col gap-2 mb-5">
            <span className="text-sm font-semibold text-muted-foreground">密码</span>
            <input 
              type="password" 
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入后台密码" 
              autoComplete="current-password"
              className="w-full border border-border/50 rounded-md px-3 py-2.5 bg-background text-foreground outline-none transition-all focus:border-primary focus:ring-2 focus:ring-primary/20"
            />
          </label>

          {errorMessage && (
            <p className="mt-2 text-destructive text-sm">{errorMessage}</p>
          )}

          <div className="flex gap-3 mt-8">
            <button 
              type="button" 
              onClick={() => navigate('/chat')}
              className="flex-1 py-2.5 px-4 rounded-md text-sm font-semibold text-muted-foreground hover:text-foreground bg-background border border-border/50 hover:bg-secondary/50 transition-colors"
            >
              返回聊天
            </button>
            <button 
              type="submit" 
              disabled={submitting}
              className="flex-1 py-2.5 px-4 rounded-md text-sm font-semibold text-primary-foreground bg-primary hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              {submitting ? '登录中...' : '进入后台'}
            </button>
          </div>
        </form>
      </div>
      
      <div className="absolute bottom-6 text-xs text-muted-foreground/50">
        文档流水线管理后台
      </div>
    </section>
  );
};
