'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth';
import { useAuthStore } from '@/store/auth.store';
import { getStoredUser } from '@/lib/auth';
import { Sidebar } from './Sidebar';
import { MobileNav } from './MobileNav';

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { setUser } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace('/auth');
      return;
    }
    const storedUser = getStoredUser();
    if (storedUser) setUser(storedUser);
  }, [router, setUser]);

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <main className="flex-1 flex flex-col min-h-screen pb-16 md:pb-0">
        {children}
      </main>
      <MobileNav />
    </div>
  );
}
