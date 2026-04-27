import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatBDT(amount: number | string): string {
  const num = typeof amount === 'string' ? parseFloat(amount) : amount;
  return new Intl.NumberFormat('en-BD', {
    style: 'currency',
    currency: 'BDT',
    minimumFractionDigits: 2,
  }).format(num);
}

export function formatCredits(credits: number): string {
  return new Intl.NumberFormat('en-BD').format(credits) + ' cr';
}

export function formatPhone(phone: string): string {
  // Convert +8801XXXXXXXXX to 01X-XXXX-XXXX display format
  const cleaned = phone.replace(/\D/g, '');
  if (cleaned.startsWith('880') && cleaned.length === 13) {
    const local = cleaned.slice(3);
    return `+880 ${local.slice(0, 3)}-${local.slice(3, 7)}-${local.slice(7)}`;
  }
  return phone;
}

export function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 7) return date.toLocaleDateString('en-BD');
  if (days > 1) return `${days}d ago`;
  if (hours > 1) return `${hours}h ago`;
  if (minutes > 1) return `${minutes}m ago`;
  return 'just now';
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + '…';
}

export function getWalletTierColor(tier: string): string {
  const map: Record<string, string> = {
    BRONZE: 'text-amber-700',
    SILVER: 'text-slate-400',
    GOLD: 'text-yellow-500',
    PLATINUM: 'text-cyan-400',
  };
  return map[tier] ?? 'text-muted-foreground';
}
