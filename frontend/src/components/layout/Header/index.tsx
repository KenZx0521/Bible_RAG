/**
 * Bible RAG - Header Component
 *
 * The main navigation header with logo, navigation links, and theme toggle.
 * Features:
 * - Hamburger menu button (controls Sidebar)
 * - Logo "Bible RAG"
 * - Main navigation (Q&A, Browse, Graph)
 * - Theme toggle (light/dark/system)
 * - Responsive design (mobile hides nav, shows hamburger only)
 *
 * @example
 * <Header />
 */

import { useCallback, useState, useRef, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { Menu, Sun, Moon, Monitor, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAppStore } from '@/stores/useAppStore';
import type { Theme } from '@/types';

/** Navigation items configuration */
const NAV_ITEMS = [
  { path: '/', label: '問答' },
  { path: '/browse', label: '瀏覽' },
  { path: '/graph', label: '圖譜' },
] as const;

/** Theme options configuration */
const THEME_OPTIONS: { value: Theme; icon: typeof Sun; label: string }[] = [
  { value: 'light', icon: Sun, label: '淺色模式' },
  { value: 'dark', icon: Moon, label: '深色模式' },
  { value: 'system', icon: Monitor, label: '跟隨系統' },
];

/** Header component */
export function Header() {
  const { sidebarOpen, toggleSidebar, theme, setTheme } = useAppStore();
  const [themeMenuOpen, setThemeMenuOpen] = useState(false);
  const themeMenuRef = useRef<HTMLDivElement>(null);

  // Get current theme icon
  const CurrentThemeIcon =
    THEME_OPTIONS.find((opt) => opt.value === theme)?.icon ?? Monitor;

  // Handle theme selection
  const handleThemeSelect = useCallback(
    (selectedTheme: Theme) => {
      setTheme(selectedTheme);
      setThemeMenuOpen(false);
    },
    [setTheme]
  );

  // Close theme menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        themeMenuRef.current &&
        !themeMenuRef.current.contains(event.target as Node)
      ) {
        setThemeMenuOpen(false);
      }
    };

    if (themeMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [themeMenuOpen]);

  // Close theme menu on escape key
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setThemeMenuOpen(false);
      }
    };

    if (themeMenuOpen) {
      document.addEventListener('keydown', handleEscape);
    }

    return () => {
      document.removeEventListener('keydown', handleEscape);
    };
  }, [themeMenuOpen]);

  return (
    <header
      className={cn(
        'sticky top-0 z-50 h-16',
        'bg-white dark:bg-gray-900',
        'border-b border-gray-200 dark:border-gray-700',
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
              'text-gray-600 dark:text-gray-300',
              'hover:bg-gray-100 dark:hover:bg-gray-800',
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
              'text-gray-900 dark:text-white',
              'hover:text-primary-600 dark:hover:text-primary-400',
              'transition-colors duration-200'
            )}
          >
            <span className="text-primary-600 dark:text-primary-400">
              Bible
            </span>
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
                    ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/50 dark:text-primary-300'
                    : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Right Section: Theme Toggle */}
        <div className="relative" ref={themeMenuRef}>
          <button
            type="button"
            onClick={() => setThemeMenuOpen(!themeMenuOpen)}
            className={cn(
              'flex h-10 w-10 items-center justify-center rounded-lg',
              'text-gray-600 dark:text-gray-300',
              'hover:bg-gray-100 dark:hover:bg-gray-800',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
              'transition-colors duration-200'
            )}
            aria-label="切換主題"
            aria-haspopup="menu"
            aria-expanded={themeMenuOpen}
          >
            <CurrentThemeIcon className="h-5 w-5" aria-hidden="true" />
          </button>

          {/* Theme Dropdown Menu */}
          {themeMenuOpen && (
            <div
              className={cn(
                'absolute right-0 mt-2 w-40',
                'bg-white dark:bg-gray-800',
                'border border-gray-200 dark:border-gray-700',
                'rounded-lg shadow-lg',
                'py-1',
                'animate-fade-in'
              )}
              role="menu"
              aria-orientation="vertical"
              aria-label="主題選項"
            >
              {THEME_OPTIONS.map((option) => {
                const Icon = option.icon;
                const isSelected = theme === option.value;

                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => handleThemeSelect(option.value)}
                    className={cn(
                      'flex w-full items-center gap-3 px-4 py-2',
                      'text-sm',
                      'transition-colors duration-200',
                      isSelected
                        ? 'bg-primary-50 text-primary-700 dark:bg-primary-900/50 dark:text-primary-300'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                    )}
                    role="menuitem"
                    aria-current={isSelected ? 'true' : undefined}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    <span>{option.label}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Mobile Navigation (shown below header on mobile when needed) */}
      <nav
        className={cn(
          'lg:hidden',
          'absolute left-0 right-0 top-16',
          'bg-white dark:bg-gray-900',
          'border-b border-gray-200 dark:border-gray-700',
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
                  ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/50 dark:text-primary-300'
                  : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
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
