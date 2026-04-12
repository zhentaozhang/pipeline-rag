import React from 'react';
import { Sidebar } from './Sidebar';
import { Menu } from 'lucide-react';

interface AppLayoutProps {
  children: React.ReactNode;
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

export const AppLayout: React.FC<AppLayoutProps> = ({ children, sidebarOpen, toggleSidebar }) => {
  return (
    <div className="flex h-screen w-full bg-background text-foreground overflow-hidden font-sans transition-colors duration-200">
      {/* Mobile sidebar toggle */}
      <div className="xl:hidden absolute top-4 left-4 z-50">
        <button 
          onClick={toggleSidebar}
          className="p-2 rounded-md hover:bg-secondary/50 transition-colors"
        >
          <Menu size={20} />
        </button>
      </div>

      <Sidebar isOpen={sidebarOpen} toggleSidebar={toggleSidebar} />
      
      <main className="flex-1 flex flex-col h-full relative overflow-hidden transition-all duration-300">
        {children}
      </main>
    </div>
  );
};
