'use client';

import { useQuery } from '@tanstack/react-query';
import {
  Users,
  Wallet,
  Zap,
  TrendingUp,
  AlertTriangle,
  Activity,
  Database,
  Settings,
} from 'lucide-react';
import Link from 'next/link';
import { AppShell } from '@/components/layout/AppShell';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { get } from '@/lib/api';
import { cn, formatBDT } from '@/lib/utils';

interface AdminStats {
  total_users: number;
  active_users_today: number;
  total_revenue_bdt: string;
  revenue_today_bdt: string;
  total_ai_requests: number;
  ai_requests_today: number;
  active_subscriptions: number;
  pending_withdrawals: number;
  fraud_alerts: number;
  system_health: {
    database: boolean;
    redis: boolean;
    celery: boolean;
    ai_providers: number;
  };
}

interface ProviderHealth {
  id: string;
  name: string;
  is_active: boolean;
  success_rate: number;
  total_requests: number;
  avg_response_ms: number;
}

export default function AdminPage() {
  const { data: stats } = useQuery({
    queryKey: ['admin-stats'],
    queryFn: () => get<AdminStats>('/admin-panel/stats/'),
    refetchInterval: 30_000,
  });

  const { data: providers } = useQuery({
    queryKey: ['admin-providers'],
    queryFn: () => get<{ results: ProviderHealth[] }>('/admin-panel/providers/'),
    refetchInterval: 60_000,
  });

  const { data: recentActivity } = useQuery({
    queryKey: ['admin-activity'],
    queryFn: () => get<{ results: Array<{ id: string; event: string; user: string; timestamp: string }> }>('/admin-panel/activity/?page_size=10'),
  });

  const statCards = [
    { label: 'Total Users', value: stats?.total_users?.toLocaleString() ?? '—', sub: `${stats?.active_users_today ?? 0} today`, icon: Users, color: 'text-blue-500' },
    { label: 'Revenue', value: stats ? formatBDT(stats.total_revenue_bdt) : '—', sub: stats ? `${formatBDT(stats.revenue_today_bdt)} today` : '', icon: Wallet, color: 'text-green-500' },
    { label: 'AI Requests', value: stats?.total_ai_requests?.toLocaleString() ?? '—', sub: `${stats?.ai_requests_today?.toLocaleString() ?? 0} today`, icon: Zap, color: 'text-purple-500' },
    { label: 'Subscriptions', value: stats?.active_subscriptions?.toLocaleString() ?? '—', sub: 'Active plans', icon: TrendingUp, color: 'text-orange-500' },
    { label: 'Pending Withdrawals', value: stats?.pending_withdrawals?.toLocaleString() ?? '—', sub: 'Awaiting approval', icon: Wallet, color: 'text-yellow-500' },
    { label: 'Fraud Alerts', value: stats?.fraud_alerts?.toLocaleString() ?? '—', sub: 'Needs review', icon: AlertTriangle, color: stats?.fraud_alerts ? 'text-red-500' : 'text-muted-foreground' },
  ];

  const adminSections = [
    { label: 'User Management', href: '/admin/users', icon: Users, description: 'View, block, KYC users' },
    { label: 'AI Providers', href: '/admin/providers', icon: Zap, description: 'Manage API keys, routing' },
    { label: 'Financials', href: '/admin/financials', icon: Wallet, description: 'Transactions, withdrawals' },
    { label: 'Content', href: '/admin/content', icon: Activity, description: 'Streaming, marketplace' },
    { label: 'System', href: '/admin/system', icon: Settings, description: 'Config, celery, logs' },
    { label: 'Analytics', href: '/admin/analytics', icon: Database, description: 'Usage reports, metrics' },
  ];

  return (
    <AppShell>
      <div className="flex-1 p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Admin Panel</h1>
          {/* System health */}
          {stats?.system_health && (
            <div className="flex items-center gap-2 text-xs">
              <SystemIndicator label="DB" healthy={stats.system_health.database} />
              <SystemIndicator label="Redis" healthy={stats.system_health.redis} />
              <SystemIndicator label="Celery" healthy={stats.system_health.celery} />
              <SystemIndicator
                label={`AI ${stats.system_health.ai_providers} providers`}
                healthy={stats.system_health.ai_providers > 0}
              />
            </div>
          )}
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
          {statCards.map((stat) => {
            const Icon = stat.icon;
            return (
              <Card key={stat.label}>
                <CardContent className="p-4">
                  <Icon className={cn('w-4 h-4 mb-2', stat.color)} />
                  <p className="text-2xl font-bold">{stat.value}</p>
                  <p className="text-xs text-muted-foreground">{stat.label}</p>
                  <p className="text-xs text-muted-foreground">{stat.sub}</p>
                </CardContent>
              </Card>
            );
          })}
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          {/* AI Provider health */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">AI Provider Health</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {providers?.results?.map((p) => (
                <div key={p.id} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <div className={cn('w-2 h-2 rounded-full', p.is_active ? 'bg-green-500' : 'bg-red-500')} />
                    <span className="font-medium">{p.name}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{p.total_requests.toLocaleString()} req</span>
                    <span className={cn(p.success_rate > 95 ? 'text-green-600' : p.success_rate > 80 ? 'text-yellow-600' : 'text-red-600', 'font-medium')}>
                      {p.success_rate.toFixed(1)}%
                    </span>
                    <span>{p.avg_response_ms}ms</span>
                  </div>
                </div>
              ))}
              {!providers?.results?.length && (
                <p className="text-sm text-muted-foreground text-center py-4">No provider data</p>
              )}
            </CardContent>
          </Card>

          {/* Recent activity */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Recent Activity</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {recentActivity?.results?.map((activity) => (
                <div key={activity.id} className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground truncate max-w-[200px]">{activity.event}</span>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground flex-shrink-0">
                    <span>{activity.user}</span>
                  </div>
                </div>
              ))}
              {!recentActivity?.results?.length && (
                <p className="text-sm text-muted-foreground text-center py-4">No recent activity</p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Admin sections */}
        <div>
          <h2 className="text-base font-semibold mb-4">Management Sections</h2>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {adminSections.map((section) => {
              const Icon = section.icon;
              return (
                <Link key={section.href} href={section.href}>
                  <Card className="hover:shadow-md transition-shadow cursor-pointer group">
                    <CardContent className="p-4 flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-muted flex items-center justify-center group-hover:bg-primary/10 transition-colors">
                        <Icon className="w-5 h-5 group-hover:text-primary transition-colors" />
                      </div>
                      <div>
                        <p className="font-medium text-sm">{section.label}</p>
                        <p className="text-xs text-muted-foreground">{section.description}</p>
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              );
            })}
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function SystemIndicator({ label, healthy }: { label: string; healthy: boolean }) {
  return (
    <div className={cn('flex items-center gap-1 px-2 py-1 rounded-full border text-[11px]', healthy ? 'border-green-500/30 text-green-600' : 'border-red-500/30 text-red-600')}>
      <div className={cn('w-1.5 h-1.5 rounded-full', healthy ? 'bg-green-500' : 'bg-red-500')} />
      {label}
    </div>
  );
}
