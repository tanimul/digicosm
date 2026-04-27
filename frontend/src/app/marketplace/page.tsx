'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Search, Star, ShoppingCart, Check, Zap } from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';
import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { get, post } from '@/lib/api';
import { cn, formatBDT, formatCredits } from '@/lib/utils';
import { useWalletStore } from '@/store/wallet.store';
import type { MarketplaceProduct, PaginatedResponse, SubscriptionPlan } from '@/types';

type Tab = 'products' | 'subscriptions';

const CATEGORY_LABELS: Record<string, string> = {
  SAAS: 'SaaS',
  AI_TOOL: 'AI Tools',
  DIGITAL_ASSET: 'Digital Assets',
  COURSE: 'Courses',
  BUNDLE: 'Bundles',
};

export default function MarketplacePage() {
  const [tab, setTab] = useState<Tab>('products');
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [purchasingId, setPurchasingId] = useState<string | null>(null);
  const [purchasedIds, setPurchasedIds] = useState<Set<string>>(new Set());
  const queryClient = useQueryClient();
  const { wallet, fetchWallet } = useWalletStore();

  const { data: products } = useQuery({
    queryKey: ['marketplace-products', selectedCategory, search],
    queryFn: () => {
      const params = new URLSearchParams({ page_size: '24' });
      if (selectedCategory !== 'all') params.set('category', selectedCategory);
      if (search) params.set('search', search);
      return get<PaginatedResponse<MarketplaceProduct>>(`/marketplace/products/?${params}`);
    },
  });

  const { data: plans } = useQuery({
    queryKey: ['subscription-plans'],
    queryFn: () => get<PaginatedResponse<SubscriptionPlan>>('/subscriptions/plans/'),
    enabled: tab === 'subscriptions',
  });

  const purchaseMutation = useMutation({
    mutationFn: (productId: string) =>
      post('/marketplace/orders/', { product: productId, quantity: 1, payment_method: 'WALLET_BDT' }),
    onSuccess: (_, productId) => {
      setPurchasedIds((prev) => new Set([...prev, productId]));
      fetchWallet();
      queryClient.invalidateQueries({ queryKey: ['wallet'] });
    },
  });

  const subscribeMutation = useMutation({
    mutationFn: (planId: string) =>
      post('/subscriptions/subscribe/', { plan: planId }),
    onSuccess: () => {
      fetchWallet();
      queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
    },
  });

  async function handlePurchase(productId: string) {
    setPurchasingId(productId);
    try {
      await purchaseMutation.mutateAsync(productId);
    } finally {
      setPurchasingId(null);
    }
  }

  async function handleSubscribe(planId: string) {
    setPurchasingId(planId);
    try {
      await subscribeMutation.mutateAsync(planId);
    } finally {
      setPurchasingId(null);
    }
  }

  const categories = ['all', 'SAAS', 'AI_TOOL', 'DIGITAL_ASSET', 'COURSE', 'BUNDLE'];

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <h1 className="text-2xl font-bold">Marketplace</h1>

        {/* Tabs */}
        <div className="flex gap-1 p-1 bg-muted rounded-lg w-fit">
          {(['products', 'subscriptions'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                'px-4 py-1.5 rounded-md text-sm font-medium transition-colors capitalize',
                tab === t ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {t}
            </button>
          ))}
        </div>

        {tab === 'products' && (
          <>
            {/* Search */}
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="Search products..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-9"
                />
              </div>
            </div>

            {/* Category pills */}
            <div className="flex gap-2 overflow-x-auto scrollbar-hide pb-1">
              {categories.map((cat) => (
                <button
                  key={cat}
                  onClick={() => setSelectedCategory(cat)}
                  className={cn(
                    'flex-shrink-0 px-3 py-1.5 rounded-full text-sm font-medium border transition-colors',
                    selectedCategory === cat
                      ? 'bg-primary text-primary-foreground border-primary'
                      : 'border-border text-muted-foreground hover:bg-accent',
                  )}
                >
                  {cat === 'all' ? 'All' : CATEGORY_LABELS[cat] ?? cat}
                </button>
              ))}
            </div>

            {/* Product grid */}
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {products?.results?.map((product) => {
                const isPurchased = purchasedIds.has(product.id);
                const isBuying = purchasingId === product.id;
                return (
                  <Card key={product.id} className="overflow-hidden group hover:shadow-md transition-shadow">
                    {product.thumbnail_url && (
                      <div className="relative h-36 bg-muted overflow-hidden">
                        <Image
                          src={product.thumbnail_url}
                          alt={product.name}
                          fill
                          className="object-cover group-hover:scale-105 transition-transform duration-300"
                          unoptimized
                        />
                        {product.is_featured && (
                          <Badge className="absolute top-2 left-2 text-[10px]">Featured</Badge>
                        )}
                      </div>
                    )}
                    <CardContent className="p-4">
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <h3 className="font-semibold text-sm leading-tight">{product.name}</h3>
                        <Badge variant="secondary" className="text-[9px] flex-shrink-0">
                          {CATEGORY_LABELS[product.category] ?? product.category}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground mb-2 line-clamp-2">{product.description}</p>

                      <div className="flex items-center gap-2 mb-3">
                        {product.rating && (
                          <div className="flex items-center gap-0.5 text-xs text-muted-foreground">
                            <Star className="w-3 h-3 fill-yellow-400 text-yellow-400" />
                            {product.rating} ({product.review_count})
                          </div>
                        )}
                        <span className="text-xs text-muted-foreground">{product.vendor_name}</span>
                      </div>

                      <div className="flex items-center justify-between">
                        <div>
                          <p className="font-bold">{formatBDT(product.price_bdt)}</p>
                          {product.price_credits && (
                            <p className="text-xs text-muted-foreground">or {formatCredits(product.price_credits)}</p>
                          )}
                        </div>
                        <Button
                          size="sm"
                          onClick={() => handlePurchase(product.id)}
                          isLoading={isBuying}
                          disabled={isPurchased}
                          variant={isPurchased ? 'secondary' : 'default'}
                        >
                          {isPurchased ? (
                            <><Check className="w-3.5 h-3.5 mr-1" /> Owned</>
                          ) : (
                            <><ShoppingCart className="w-3.5 h-3.5 mr-1" /> Buy</>
                          )}
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
              {products?.results?.length === 0 && (
                <div className="col-span-full text-center py-16 text-muted-foreground">
                  No products found
                </div>
              )}
            </div>
          </>
        )}

        {tab === 'subscriptions' && (
          <div className="space-y-6">
            <div className="text-center">
              <h2 className="text-xl font-bold mb-2">Choose Your Plan</h2>
              <p className="text-muted-foreground">Unlock AI, streaming, and marketplace with one subscription</p>
            </div>

            <div className="grid md:grid-cols-3 gap-6 max-w-4xl mx-auto">
              {plans?.results?.map((plan) => (
                <Card
                  key={plan.id}
                  className={cn(
                    'relative overflow-hidden',
                    plan.is_popular && 'border-primary shadow-md',
                  )}
                >
                  {plan.is_popular && (
                    <div className="absolute top-0 left-0 right-0 h-1 gradient-dce" />
                  )}
                  <CardContent className="p-6">
                    {plan.is_popular && (
                      <Badge className="mb-3 text-xs">Most Popular</Badge>
                    )}
                    <h3 className="text-xl font-bold mb-1">{plan.name}</h3>
                    <p className="text-xs text-muted-foreground mb-4 capitalize">{plan.billing_cycle.toLowerCase()} billing</p>

                    <div className="mb-6">
                      <span className="text-4xl font-bold">{formatBDT(plan.price_bdt)}</span>
                      <span className="text-muted-foreground text-sm">/{plan.billing_cycle === 'MONTHLY' ? 'mo' : plan.billing_cycle === 'QUARTERLY' ? 'qtr' : 'yr'}</span>
                    </div>

                    <ul className="space-y-2 mb-6">
                      <PlanFeature enabled={plan.has_ai_access} label={`AI Access (${plan.ai_requests_per_day}/day)`} />
                      <PlanFeature enabled={plan.has_streaming} label={`Streaming (${plan.streaming_quality}, ${plan.concurrent_streams} screens)`} />
                      <PlanFeature enabled={plan.has_marketplace} label="Marketplace access" />
                      <PlanFeature enabled label={`${plan.monthly_credits.toLocaleString()} credits/month`} icon={<Zap className="w-3 h-3 text-yellow-500" />} />
                      {plan.features.map((f) => (
                        <PlanFeature key={f} enabled label={f} />
                      ))}
                    </ul>

                    <Button
                      className="w-full"
                      variant={plan.is_popular ? 'gradient' : 'outline'}
                      onClick={() => handleSubscribe(plan.id)}
                      isLoading={purchasingId === plan.id}
                    >
                      Subscribe
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>

            {wallet && (
              <p className="text-center text-sm text-muted-foreground">
                Current balance: <span className="font-medium">{formatBDT(wallet.balance_bdt)}</span>
              </p>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}

function PlanFeature({
  enabled,
  label,
  icon,
}: {
  enabled: boolean;
  label: string;
  icon?: React.ReactNode;
}) {
  return (
    <li className={cn('flex items-center gap-2 text-sm', !enabled && 'opacity-40 line-through')}>
      {icon ?? <Check className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />}
      {label}
    </li>
  );
}
