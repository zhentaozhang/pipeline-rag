# Pipeline RAG — 前端

Pipeline RAG 的 React + TypeScript 前端 SPA，提供流式对话界面和管理后台。

## 技术栈

- **React 19** + **TypeScript** + **Vite**
- **React Router** — 路由管理
- **Zustand** — 状态管理
- **Tailwind CSS 4** — 样式
- **lucide-react** — 图标

## 目录结构

```
src/
├── components/
│   ├── chat/          # 对话界面组件
│   ├── layout/        # 布局组件（Sidebar, AppLayout）
│   ├── ui/            # 通用 UI 组件（Button, Card, Tabs, Badge）
│   └── admin/         # 管理后台组件
├── pages/
│   ├── admin/         # 管理后台页面
│   └── ChatPage.tsx   # 对话主页面
├── store/
│   └── chatStore.ts   # Zustand 全局状态
├── lib/               # 工具库（API 客户端、主题、格式化）
└── main.tsx           # 入口
```

## 启动

```bash
cd frontend
npm install
npm run dev       # 开发服务器（默认端口 5173）
npm run build     # 生产构建
```
