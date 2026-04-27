'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, CheckCheck, Trash2 } from 'lucide-react';
import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { get, post } from '@/lib/api';
import { cn, formatRelativeTime } from '@/lib/utils';
import type { Notification, PaginatedResponse } from '@/types';

const TYPE_COLORS: Record<string, string> = {
  SYSTEM: 'bg-slate-500',
  PAYMENT: 'bg-green-500',
  AI_USAGE: 'bg-purple-500',
  SUBSCRIPTION: 'bg-blue-500',
  PROMOTION: 'bg-orange-500',
  SECURITY: 'bg-red-500',
};

export default function NotificationsPage() {
  const [page, setPage] = useState(1);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ['notifications', page],
    queryFn: () => get<PaginatedResponse<Notification> & { unread_count: number }>(`/notifications/?page=${page}`),
  });

  const markAllReadMutation = useMutation({
    mutationFn: () => post('/notifications/mark-all-read/'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notifications'] }),
  });

  const markReadMutation = useMutation({
    mutationFn: (id: string) => post(`/notifications/${id}/mark-read/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notifications'] }),
  });

  const unreadCount = data?.unread_count ?? 0;

  return (
    <AppShell>
      <div className="flex-1 p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">Notifications</h1>
            {unreadCount > 0 && (
              <Badge variant="destructive">{unreadCount}</Badge>
            )}
          </div>
          {unreadCount > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => markAllReadMutation.mutate()}
              isLoading={markAllReadMutation.isPending}
            >
              <CheckCheck className="w-4 h-4 mr-2" /> Mark all read
            </Button>
          )}
        </div>

        <div className="space-y-2">
          {data?.results?.map((notification) => (
            <div
              key={notification.id}
              className={cn(
                'flex items-start gap-4 p-4 rounded-lg border transition-colors cursor-pointer',
                notification.is_read ? 'bg-card' : 'bg-primary/5 border-primary/20',
              )}
              onClick={() => !notification.is_read && markReadMutation.mutate(notification.id)}
            >
              <div className={cn('w-2 h-2 rounded-full mt-2 flex-shrink-0', TYPE_COLORS[notification.notification_type] ?? 'bg-muted')} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <p className={cn('text-sm font-medium', !notification.is_read && 'text-foreground')}>
                    {notification.title}
                  </p>
                  <span className="text-xs text-muted-foreground flex-shrink-0">
                    {formatRelativeTime(notification.created_at)}
                  </span>
                </div>
                <p className="text-sm text-muted-foreground">{notification.message}</p>
                {notification.action_url && (
                  <a
                    href={notification.action_url}
                    className="text-xs text-primary hover:underline mt-1 inline-block"
                    onClick={(e) => e.stopPropagation()}
                  >
                    View →
                  </a>
                )}
              </div>
              <Badge variant="outline" className="text-[9px] flex-shrink-0">
                {notification.notification_type}
              </Badge>
            </div>
          ))}

          {!isLoading && data?.results?.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Bell className="w-12 h-12 text-muted-foreground mb-4" />
              <p className="text-muted-foreground">No notifications yet</p>
              <p className="text-sm text-muted-foreground">We&apos;ll notify you about payments, AI usage, and more.</p>
            </div>
          )}
        </div>

        {data && data.count > (data.results?.length ?? 0) && (
          <div className="flex justify-center">
            <Button variant="outline" onClick={() => setPage((p) => p + 1)} isLoading={isLoading}>
              Load More
            </Button>
          </div>
        )}
      </div>
    </AppShell>
  );
}
