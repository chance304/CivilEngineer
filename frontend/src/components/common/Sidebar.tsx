'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  LayoutDashboard,
  FolderKanban,
  Settings,
  ShieldCheck,
  ChevronDown,
  Building2,
} from 'lucide-react';
import { useState } from 'react';

interface SidebarProps {
  role: string;
}

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  children?: { label: string; href: string }[];
  adminOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  {
    label: 'Dashboard',
    href: '/dashboard',
    icon: LayoutDashboard,
  },
  {
    label: 'Projects',
    href: '/projects',
    icon: FolderKanban,
    children: [
      { label: 'All Projects', href: '/dashboard' },
      { label: 'New Project', href: '/projects/new' },
    ],
  },
  {
    label: 'Admin',
    href: '/admin',
    icon: ShieldCheck,
    adminOnly: true,
    children: [
      { label: 'LLM Config', href: '/admin/llm-config' },
      { label: 'Building Codes', href: '/admin/building-codes' },
      { label: 'Users', href: '/admin/users' },
    ],
  },
  {
    label: 'Settings',
    href: '/settings',
    icon: Settings,
  },
];

export function Sidebar({ role }: SidebarProps) {
  const pathname = usePathname();
  const isAdmin = role === 'firm_admin';
  const [expanded, setExpanded] = useState<string[]>([]);

  function toggle(label: string) {
    setExpanded((prev) =>
      prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label]
    );
  }

  return (
    <aside className="w-56 bg-gray-900 text-gray-300 flex flex-col h-full shrink-0">
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-5 border-b border-gray-700">
        <div className="bg-blue-600 p-1.5 rounded-lg">
          <Building2 className="w-5 h-5 text-white" />
        </div>
        <span className="font-semibold text-white text-sm">CivilEngineer</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          if (item.adminOnly && !isAdmin) return null;
          const isExpanded = expanded.includes(item.label);
          const isActive = pathname.startsWith(item.href === '/dashboard' ? '/dashboard' : item.href);

          if (item.children) {
            return (
              <div key={item.label}>
                <button
                  onClick={() => toggle(item.label)}
                  className={cn(
                    'w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors',
                    isActive ? 'bg-gray-700 text-white' : 'hover:bg-gray-800 hover:text-white'
                  )}
                >
                  <span className="flex items-center gap-2.5">
                    <item.icon className="w-4 h-4" />
                    {item.label}
                  </span>
                  <ChevronDown className={cn('w-3 h-3 transition-transform', isExpanded && 'rotate-180')} />
                </button>
                {isExpanded && (
                  <div className="ml-6 mt-0.5 space-y-0.5">
                    {item.children.map((child) => (
                      <Link
                        key={child.href}
                        href={child.href}
                        className={cn(
                          'block px-3 py-1.5 rounded-lg text-xs transition-colors',
                          pathname === child.href
                            ? 'bg-blue-600 text-white'
                            : 'hover:bg-gray-800 hover:text-white'
                        )}
                      >
                        {child.label}
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            );
          }

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors',
                pathname === item.href
                  ? 'bg-gray-700 text-white'
                  : 'hover:bg-gray-800 hover:text-white'
              )}
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
