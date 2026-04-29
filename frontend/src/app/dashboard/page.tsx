'use client';

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Wallet,
  Bot,
  Play,
  ShoppingBag,
  TrendingUp,
  Zap,
  ArrowUpRight,
  Clock,
} from 'lucide-react';
import Link from 'next/link';
import { AppShell } from '@/components/layout/AppShell';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/store/auth.store';
import { useWalletStore } from '@/store/wallet.store';
import { get } from '@/lib/api';
import { formatBDT, formatCredits, formatRelativeTime, getWalletTierColor } from '@/lib/utils';
import type { Notification, Transaction, UserSubscription } from '@/types';
import { cn } from '@/lib/utils';

export default function DashboardPage() {
  const { user } = useAuthStore();
  const { wallet, fetchWallet } = useWalletStore();

  useEffect(() => {
    fetchWallet();
  }, [fetchWallet]);

  const { data: subscriptions } = useQuery({
    queryKey: ['subscriptions'],
    queryFn: () => get<{ results: UserSubscription[] }>('/subscriptions/my/'),
  });

  const { data: recentTxns } = useQuery({
    queryKey: ['transactions', 'recent'],
    queryFn: () => get<{ results: Transaction[] }>('/wallet/transactions/?page=1'),
  });

  const { data: notifications } = useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: () => get<{ results: Notification[]; unread_count: number }>('/notifications/?is_read=false&page_size=5'),
  });

  const activeSub = subscriptions?.results?.find((s) => s.status === 'ACTIVE');

  const quickActions = [
    { label: 'Deposit', href: '/wallet?tab=deposit', icon: Wallet, color: 'text-green-500' },
    { label: 'Ask AI', href: '/ai', icon: Bot, color: 'text-purple-500' },
    { label: 'Watch', href: '/streaming', icon: Play, color: 'text-blue-500' },
    { label: 'Shop', href: '/marketplace', icon: ShoppingBag, color: 'text-orange-500' },
  ];

  return (
    <AppShell>
      <div className="flex-1 p-6 space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold">
            Welcome back{user?.full_name ? `, ${user.full_name.split(' ')[0]}` : ''}!
          </h1>
          <p className="text-muted-foreground text-sm">Here&apos;s your DCE overview</p>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Wallet Balance */}
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <Wallet className="w-4 h-4 text-muted-foreground" />
                {wallet && (
                  <span className={cn('text-xs font-bold', getWalletTierColor(wallet.tier))}>
                    {wallet.tier}
                  </span>
                )}
              </div>
              <p className="text-2xl font-bold">{wallet ? formatBDT(wallet.balance_bdt) : '—'}</p>
              <p className="text-xs text-muted-foreground">BDT Balance</p>
            </CardContent>
          </Card>

          {/* Credits */}
          <Card>
            <CardContent className="p-4">
              <Zap className="w-4 h-4 text-muted-foreground mb-2" />
              <p className="text-2xl font-bold">{wallet ? formatCredits(wallet.credits) : '—'}</p>
              <p className="text-xs text-muted-foreground">AI Credits</p>
            </CardContent>
          </Card>

          {/* Active Subscription */}
          <Card>
            <CardContent className="p-4">
              <TrendingUp className="w-4 h-4 text-muted-foreground mb-2" />
              <p className="text-2xl font-bold">{activeSub ? activeSub.plan.name : 'None'}</p>
              <p className="text-xs text-muted-foreground">
                {activeSub ? `Until ${new Date(activeSub.end_date).toLocaleDateString('en-BD')}` : 'No active plan'}
              </p>
            </CardContent>
          </Card>

          {/* Notifications */}
          <Card>
            <CardContent className="p-4">
              <ArrowUpRight className="w-4 h-4 text-muted-foreground mb-2" />
              <p className="text-2xl font-bold">{notifications?.unread_count ?? 0}</p>
              <p className="text-xs text-muted-foreground">Unread alerts</p>
            </CardContent>
          </Card>
        </div>

        {/* Quick Actions */}
        <div>
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            Quick Actions
          </h2>
          <div className="grid grid-cols-4 gap-3">
            {quickActions.map((action) => {
              const Icon = action.icon;
              return (
                <Link key={action.href} href={action.href}>
                  <div className="flex flex-col items-center gap-2 p-4 rounded-lg border bg-card hover:bg-accent transition-colors cursor-pointer">
                    <div className={cn('w-10 h-10 rounded-full bg-muted flex items-center justify-center', action.color)}>
                      <Icon className="w-5 h-5" />
                    </div>
                    <span className="text-xs font-medium">{action.label}</span>
                  </div>
                </Link>
              );
            })}
          </div>
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          {/* Recent Transactions */}
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Recent Transactions</CardTitle>
                <Link href="/wallet" className="text-xs text-primary hover:underline">
                  View all
                </Link>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {recentTxns?.results?.slice(0, 5).map((txn) => (
                <div key={txn.id} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <Clock className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                    <div>
                      <p className="font-medium truncate max-w-[140px]">{txn.description || txn.transaction_type}</p>
                      <p className="text-xs text-muted-foreground">{formatRelativeTime(txn.created_at)}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className={cn('font-semibold', txn.transaction_type === 'DEPOSIT' ? 'text-green-600' : 'text-foreground')}>
                      {txn.transaction_type === 'DEPOSIT' ? '+' : ''}{formatBDT(txn.amount)}
                    </p>
                    <Badge
                      variant={txn.status === 'COMPLETED' ? 'success' : txn.status === 'FAILED' ? 'destructive' : 'secondary'}
                      className="text-[10px] px-1.5 py-0"
                    >
                      {txn.status}
                    </Badge>
                  </div>
                </div>
              ))}
              {!recentTxns?.results?.length && (
                <p className="text-sm text-muted-foreground text-center py-4">No transactions yet</p>
              )}
            </CardContent>
          </Card>

          {/* Notifications */}
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Notifications</CardTitle>
                <Link href="/notifications" className="text-xs text-primary hover:underline">
                  View all
                </Link>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {notifications?.results?.slice(0, 5).map((n) => (
                <div key={n.id} className="flex items-start gap-2 text-sm">
                  <div className={cn('w-2 h-2 rounded-full mt-1.5 flex-shrink-0', n.is_read ? 'bg-muted' : 'bg-primary')} />
                  <div>
                    <p className="font-medium">{n.title}</p>
                    <p className="text-xs text-muted-foreground line-clamp-1">{n.message}</p>
                    <p className="text-xs text-muted-foreground">{formatRelativeTime(n.created_at)}</p>
                  </div>
                </div>
              ))}
              {!notifications?.results?.length && (
                <p className="text-sm text-muted-foreground text-center py-4">No notifications</p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Subscription CTA */}
        {!activeSub && (
          <Card className="border-primary/30 bg-primary/5">
            <CardContent className="p-6 flex flex-col md:flex-row items-center justify-between gap-4">
              <div>
                <h3 className="font-bold text-lg">Unlock the full DCE experience</h3>
                <p className="text-muted-foreground text-sm">Get AI access, HD streaming, and marketplace credits in one plan.</p>
              </div>
              <Link href="/marketplace?tab=subscriptions">
                <Button variant="gradient">View Plans</Button>
              </Link>
            </CardContent>
          </Card>
        )}
      </div>
    </AppShell>
  );
}
