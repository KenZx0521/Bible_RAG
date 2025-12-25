/**
 * Bible RAG - Header Component
 *
 * The main navigation header with logo and navigation links.
 * Features:
 * - Hamburger menu button (controls Sidebar)
 * - Logo "Bible RAG"
 * - Main navigation (Q&A, Browse, Graph)
 * - Responsive design (mobile hides nav, shows hamburger only)
 *
 * @example
 * <Header />
 */

import { NavLink } from 'react-router-dom';
import { Menu, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAppStore } from '@/stores/useAppStore';

/** Navigation items configuration */
const NAV_ITEMS = [
  { path: '/', label: '問答' },
  { path: '/browse', label: '瀏覽' },
  { path: '/graph', label: '圖譜' },
] as const;

/** Header component */
export function Header() {
  const { sidebarOpen, toggleSidebar } = useAppStore();

  return (
    <header
      className={cn(
        'sticky top-0 z-50 h-16',
        'bg-white',
        'border-b border-gray-200',
        'transition-colors duration-200'
      )}
    >
      <div className="flex h-full items-center justify-between px-4 lg:px-6">
        {/* Left Section: Hamburger + Logo */}
        <div className="flex items-center gap-3">
          {/* Hamburger Menu Button */}
          <button
            type="button"
            onClick={toggleSidebar}
            className={cn(
              'flex h-10 w-10 items-center justify-center rounded-lg',
              'text-gray-600',
              'hover:bg-gray-100',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
              'transition-colors duration-200'
            )}
            aria-label={sidebarOpen ? '關閉側邊欄' : '開啟側邊欄'}
            aria-expanded={sidebarOpen}
          >
            {sidebarOpen ? (
              <X className="h-5 w-5" aria-hidden="true" />
            ) : (
              <Menu className="h-5 w-5" aria-hidden="true" />
            )}
          </button>

          {/* Logo */}
          <NavLink
            to="/"
            className={cn(
              'flex items-center gap-2',
              'text-xl font-bold',
              'text-gray-900',
              'hover:text-primary-600',
              'transition-colors duration-200'
            )}
          >
            <span className="text-primary-600">Bible</span>
            <span>RAG</span>
          </NavLink>
        </div>

        {/* Center Section: Main Navigation (hidden on mobile) */}
        <nav
          className="hidden lg:flex items-center gap-1"
          aria-label="主導航"
        >
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) =>
                cn(
                  'px-4 py-2 rounded-lg',
                  'text-sm font-medium',
                  'transition-colors duration-200',
                  isActive
                    ? 'bg-primary-100 text-primary-700'
                    : 'text-gray-600 hover:bg-gray-100'
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Right Section: Placeholder for future features */}
        <div className="w-10" />
      </div>

      {/* Mobile Navigation (shown below header on mobile when needed) */}
      <nav
        className={cn(
          'lg:hidden',
          'absolute left-0 right-0 top-16',
          'bg-white',
          'border-b border-gray-200',
          'px-4 py-2',
          'flex items-center justify-center gap-2',
          'shadow-sm'
        )}
        aria-label="行動版導航"
      >
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              cn(
                'px-4 py-2 rounded-lg',
                'text-sm font-medium',
                'transition-colors duration-200',
                isActive
                  ? 'bg-primary-100 text-primary-700'
                  : 'text-gray-600 hover:bg-gray-100'
              )
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}

export default Header;
