'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  Wallet,
  Bot,
  Play,
  ShoppingBag,
  Bell,
  Settings,
  LogOut,
  Zap,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/store/auth.store';
import { formatBDT, formatCredits, getWalletTierColor } from '@/lib/utils';
import { useWalletStore } from '@/store/wallet.store';
import { useEffect } from 'react';

const navItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/wallet', label: 'Wallet', icon: Wallet },
  { href: '/ai', label: 'AI Playground', icon: Bot },
  { href: '/streaming', label: 'Streaming', icon: Play },
  { href: '/marketplace', label: 'Marketplace', icon: ShoppingBag },
  { href: '/notifications', label: 'Notifications', icon: Bell },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();
  const { wallet, fetchWallet } = useWalletStore();

  useEffect(() => {
    fetchWallet();
  }, [fetchWallet]);

  return (
    <aside className="hidden md:flex flex-col w-64 min-h-screen bg-card border-r border-border">
      {/* Logo */}
      <div className="flex items-center gap-2 p-6 border-b border-border">
        <div className="w-8 h-8 gradient-dce rounded-lg flex items-center justify-center">
          <Zap className="w-4 h-4 text-white" />
        </div>
        <span className="text-xl font-bold">DCE</span>
      </div>

      {/* Wallet summary */}
      {wallet && (
        <div className="mx-4 mt-4 p-3 rounded-lg bg-muted/50 border border-border">
          <p className="text-xs text-muted-foreground mb-1">
            Wallet
            <span className={cn('ml-2 font-semibold text-xs', getWalletTierColor(wallet.tier))}>
              {wallet.tier}
            </span>
          </p>
          <p className="text-lg font-bold">{formatBDT(wallet.balance_bdt)}</p>
          <p className="text-xs text-muted-foreground">{formatCredits(wallet.credits)} available</p>
        </div>
      )}

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
              )}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* User / Logout */}
      <div className="p-4 border-t border-border">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-8 h-8 gradient-dce rounded-full flex items-center justify-center text-white text-xs font-bold">
            {user?.full_name?.charAt(0) ?? user?.phone?.charAt(-2) ?? 'U'}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{user?.full_name ?? 'User'}</p>
            <p className="text-xs text-muted-foreground truncate">{user?.phone}</p>
          </div>
        </div>
        <button
          onClick={logout}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-md text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
        >
          <LogOut className="w-4 h-4" />
          Logout
        </button>
      </div>
    </aside>
  );
}
