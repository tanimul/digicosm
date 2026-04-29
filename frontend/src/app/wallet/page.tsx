'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import {
  Wallet,
  ArrowDownToLine,
  ArrowUpFromLine,
  RefreshCw,
  ExternalLink,
  ChevronDown,
} from 'lucide-react';
import { AppShell } from '@/components/layout/AppShell';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { useWalletStore } from '@/store/wallet.store';
import { formatBDT, formatCredits, formatRelativeTime, getWalletTierColor, cn } from '@/lib/utils';
import { get } from '@/lib/api';
import type { DepositMethod, PaginatedResponse, Transaction } from '@/types';

type Tab = 'overview' | 'deposit' | 'withdraw' | 'history';

const DEPOSIT_METHODS: { id: DepositMethod; label: string; logo: string }[] = [
  { id: 'BKASH', label: 'bKash', logo: '🟣' },
  { id: 'NAGAD', label: 'Nagad', logo: '🟠' },
  { id: 'SSLCOMMERZ', label: 'SSL Commerz', logo: '🔵' },
];

const TIER_THRESHOLDS = {
  BRONZE: 0,
  SILVER: 1000,
  GOLD: 5000,
  PLATINUM: 20000,
};

export default function WalletPage() {
  const searchParams = useSearchParams();
  const initialTab = (searchParams.get('tab') as Tab) ?? 'overview';
  const [activeTab, setActiveTab] = useState<Tab>(initialTab);
  const [depositMethod, setDepositMethod] = useState<DepositMethod>('BKASH');
  const [depositAmount, setDepositAmount] = useState('');
  const [depositError, setDepositError] = useState('');
  const [withdrawMethod, setWithdrawMethod] = useState<DepositMethod>('BKASH');
  const [withdrawAmount, setWithdrawAmount] = useState('');
  const [withdrawAccount, setWithdrawAccount] = useState('');
  const [withdrawError, setWithdrawError] = useState('');
  const [txPage, setTxPage] = useState(1);

  const {
    wallet,
    transactions,
    transactionCount,
    isLoading,
    isDepositing,
    isWithdrawing,
    error,
    fetchWallet,
    fetchTransactions,
    initiateDeposit,
    initiateWithdrawal,
  } = useWalletStore();

  useEffect(() => { fetchWallet(); }, [fetchWallet]);
  useEffect(() => { fetchTransactions(txPage); }, [fetchTransactions, txPage]);

  async function handleDeposit() {
    setDepositError('');
    const amount = parseFloat(depositAmount);
    if (isNaN(amount) || amount < 10) {
      setDepositError('Minimum deposit is ৳10');
      return;
    }
    if (amount > 50000) {
      setDepositError('Maximum single deposit is ৳50,000');
      return;
    }
    try {
      const deposit = await initiateDeposit(depositMethod, amount);
      if (deposit.payment_url) {
        window.open(deposit.payment_url, '_blank');
      }
      setDepositAmount('');
    } catch {
      // error in store
    }
  }

  async function handleWithdraw() {
    setWithdrawError('');
    const amount = parseFloat(withdrawAmount);
    if (isNaN(amount) || amount < 100) {
      setWithdrawError('Minimum withdrawal is ৳100');
      return;
    }
    if (!withdrawAccount || withdrawAccount.length < 11) {
      setWithdrawError('Enter a valid account number');
      return;
    }
    try {
      await initiateWithdrawal(withdrawMethod, amount, withdrawAccount);
      setWithdrawAmount('');
      setWithdrawAccount('');
    } catch {
      // error in store
    }
  }

  const tierOrder = ['BRONZE', 'SILVER', 'GOLD', 'PLATINUM'];
  const tierIndex = wallet ? tierOrder.indexOf(wallet.tier) : 0;
  const nextTier = tierOrder[tierIndex + 1] as keyof typeof TIER_THRESHOLDS | undefined;
  const nextThreshold = nextTier ? TIER_THRESHOLDS[nextTier] : null;
  const balance = wallet ? parseFloat(wallet.balance_bdt) : 0;
  const tierProgress = nextThreshold ? Math.min((balance / nextThreshold) * 100, 100) : 100;

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'overview', label: 'Overview', icon: <Wallet className="w-4 h-4" /> },
    { id: 'deposit', label: 'Deposit', icon: <ArrowDownToLine className="w-4 h-4" /> },
    { id: 'withdraw', label: 'Withdraw', icon: <ArrowUpFromLine className="w-4 h-4" /> },
    { id: 'history', label: 'History', icon: <RefreshCw className="w-4 h-4" /> },
  ];

  return (
    <AppShell>
      <div className="flex-1 p-6 space-y-6">
        <h1 className="text-2xl font-bold">Wallet</h1>

        {/* Tab bar */}
        <div className="flex gap-1 p-1 bg-muted rounded-lg w-fit">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                activeTab === tab.id
                  ? 'bg-background shadow-sm text-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {tab.icon}
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          ))}
        </div>

        {/* Overview */}
        {activeTab === 'overview' && (
          <div className="space-y-4">
            <div className="grid sm:grid-cols-2 gap-4">
              <Card>
                <CardContent className="p-6">
                  <p className="text-sm text-muted-foreground">BDT Balance</p>
                  <p className="text-4xl font-bold mt-1">{wallet ? formatBDT(wallet.balance_bdt) : '—'}</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    1 BDT = 10 credits
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-6">
                  <p className="text-sm text-muted-foreground">AI Credits</p>
                  <p className="text-4xl font-bold mt-1">{wallet ? wallet.credits.toLocaleString() : '—'}</p>
                  <p className="text-xs text-muted-foreground mt-1">Available for AI usage</p>
                </CardContent>
              </Card>
            </div>

            {/* Tier progress */}
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <p className="text-sm font-medium">Tier Status</p>
                    <p className={cn('text-xl font-bold', wallet ? getWalletTierColor(wallet.tier) : '')}>
                      {wallet?.tier ?? 'BRONZE'}
                    </p>
                  </div>
                  {nextTier && (
                    <div className="text-right">
                      <p className="text-xs text-muted-foreground">Next: {nextTier}</p>
                      <p className="text-sm font-medium">{formatBDT(nextThreshold ?? 0)}</p>
                    </div>
                  )}
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full gradient-dce rounded-full transition-all duration-500"
                    style={{ width: `${tierProgress}%` }}
                  />
                </div>
                {nextTier && (
                  <p className="text-xs text-muted-foreground mt-2">
                    {formatBDT(Math.max(0, (nextThreshold ?? 0) - balance))} more to reach {nextTier}
                  </p>
                )}
              </CardContent>
            </Card>

            <div className="flex gap-3">
              <Button onClick={() => setActiveTab('deposit')} className="flex-1" variant="default">
                <ArrowDownToLine className="w-4 h-4 mr-2" /> Deposit
              </Button>
              <Button onClick={() => setActiveTab('withdraw')} className="flex-1" variant="outline">
                <ArrowUpFromLine className="w-4 h-4 mr-2" /> Withdraw
              </Button>
            </div>
          </div>
        )}

        {/* Deposit */}
        {activeTab === 'deposit' && (
          <Card className="max-w-md">
            <CardHeader>
              <CardTitle className="text-base">Deposit BDT</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium mb-2 block">Payment Method</label>
                <div className="grid grid-cols-3 gap-2">
                  {DEPOSIT_METHODS.map((m) => (
                    <button
                      key={m.id}
                      onClick={() => setDepositMethod(m.id)}
                      className={cn(
                        'flex flex-col items-center gap-1 p-3 rounded-lg border text-sm font-medium transition-colors',
                        depositMethod === m.id
                          ? 'border-primary bg-primary/5 text-primary'
                          : 'border-border hover:bg-accent',
                      )}
                    >
                      <span className="text-xl">{m.logo}</span>
                      {m.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-sm font-medium mb-1 block">Amount (BDT)</label>
                <Input
                  type="number"
                  placeholder="Enter amount (min ৳10)"
                  value={depositAmount}
                  onChange={(e) => { setDepositAmount(e.target.value); setDepositError(''); }}
                  error={depositError || error || undefined}
                />
              </div>

              {/* Quick amounts */}
              <div className="flex gap-2 flex-wrap">
                {[100, 500, 1000, 5000].map((amt) => (
                  <button
                    key={amt}
                    onClick={() => setDepositAmount(String(amt))}
                    className="px-3 py-1 text-xs rounded-full border hover:bg-accent transition-colors"
                  >
                    ৳{amt}
                  </button>
                ))}
              </div>

              <Button
                className="w-full"
                variant="gradient"
                onClick={handleDeposit}
                isLoading={isDepositing}
              >
                <ExternalLink className="w-4 h-4 mr-2" />
                Continue to {DEPOSIT_METHODS.find((m) => m.id === depositMethod)?.label}
              </Button>

              <p className="text-xs text-muted-foreground text-center">
                You will be redirected to complete the payment. Credits are added automatically.
              </p>
            </CardContent>
          </Card>
        )}

        {/* Withdraw */}
        {activeTab === 'withdraw' && (
          <Card className="max-w-md">
            <CardHeader>
              <CardTitle className="text-base">Withdraw BDT</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium mb-2 block">Withdrawal Method</label>
                <div className="grid grid-cols-3 gap-2">
                  {DEPOSIT_METHODS.map((m) => (
                    <button
                      key={m.id}
                      onClick={() => setWithdrawMethod(m.id)}
                      className={cn(
                        'flex flex-col items-center gap-1 p-3 rounded-lg border text-sm font-medium transition-colors',
                        withdrawMethod === m.id
                          ? 'border-primary bg-primary/5 text-primary'
                          : 'border-border hover:bg-accent',
                      )}
                    >
                      <span className="text-xl">{m.logo}</span>
                      {m.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-sm font-medium mb-1 block">Account Number</label>
                <Input
                  type="tel"
                  placeholder="01XXXXXXXXX"
                  value={withdrawAccount}
                  onChange={(e) => { setWithdrawAccount(e.target.value); setWithdrawError(''); }}
                />
              </div>

              <div>
                <label className="text-sm font-medium mb-1 block">Amount (BDT)</label>
                <Input
                  type="number"
                  placeholder="Enter amount (min ৳100)"
                  value={withdrawAmount}
                  onChange={(e) => { setWithdrawAmount(e.target.value); setWithdrawError(''); }}
                  error={withdrawError || error || undefined}
                />
              </div>

              <Button
                className="w-full"
                onClick={handleWithdraw}
                isLoading={isWithdrawing}
              >
                <ArrowUpFromLine className="w-4 h-4 mr-2" />
                Submit Withdrawal
              </Button>

              <p className="text-xs text-muted-foreground text-center">
                Withdrawals are processed within 1–3 business days after admin approval.
              </p>
            </CardContent>
          </Card>
        )}

        {/* Transaction History */}
        {activeTab === 'history' && (
          <div className="space-y-4">
            <Card>
              <CardContent className="p-0">
                <div className="divide-y divide-border">
                  {transactions.map((txn) => (
                    <div key={txn.id} className="flex items-center justify-between p-4">
                      <div className="flex items-center gap-3">
                        <div className={cn(
                          'w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold',
                          txn.transaction_type === 'DEPOSIT' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-700',
                        )}>
                          {txn.transaction_type === 'DEPOSIT' ? '+' : '-'}
                        </div>
                        <div>
                          <p className="text-sm font-medium">{txn.description || txn.transaction_type}</p>
                          <p className="text-xs text-muted-foreground">{txn.transaction_id}</p>
                          <p className="text-xs text-muted-foreground">{formatRelativeTime(txn.created_at)}</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className={cn(
                          'font-semibold',
                          txn.transaction_type === 'DEPOSIT' ? 'text-green-600' : 'text-foreground',
                        )}>
                          {txn.transaction_type === 'DEPOSIT' ? '+' : ''}{formatBDT(txn.amount)}
                        </p>
                        <Badge
                          variant={
                            txn.status === 'COMPLETED' ? 'success' :
                            txn.status === 'FAILED' ? 'destructive' : 'secondary'
                          }
                          className="text-[10px]"
                        >
                          {txn.status}
                        </Badge>
                      </div>
                    </div>
                  ))}
                  {transactions.length === 0 && !isLoading && (
                    <p className="text-sm text-muted-foreground text-center py-12">No transactions yet</p>
                  )}
                </div>
              </CardContent>
            </Card>

            {transactions.length < transactionCount && (
              <div className="flex justify-center">
                <Button
                  variant="outline"
                  onClick={() => setTxPage((p) => p + 1)}
                  isLoading={isLoading}
                >
                  <ChevronDown className="w-4 h-4 mr-2" /> Load More
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
