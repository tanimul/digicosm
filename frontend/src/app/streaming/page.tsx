'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, Play, Clock, Star, Lock } from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';
import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { get } from '@/lib/api';
import { cn, truncate } from '@/lib/utils';
import type { ContentItem, StreamingCategory } from '@/types';

export default function StreamingPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [selectedType, setSelectedType] = useState<string>('all');

  const { data: categories } = useQuery({
    queryKey: ['streaming-categories'],
    queryFn: () => get<{ results: StreamingCategory[] }>('/streaming/categories/'),
  });

  const { data: featured } = useQuery({
    queryKey: ['streaming-featured'],
    queryFn: () => get<{ results: ContentItem[] }>('/streaming/content/?is_featured=true&page_size=5'),
  });

  const { data: content } = useQuery({
    queryKey: ['streaming-content', selectedCategory, selectedType, searchQuery],
    queryFn: () => {
      const params = new URLSearchParams({ page_size: '24' });
      if (selectedCategory !== 'all') params.set('category', selectedCategory);
      if (selectedType !== 'all') params.set('content_type', selectedType);
      if (searchQuery) params.set('search', searchQuery);
      return get<{ results: ContentItem[]; count: number }>(`/streaming/content/?${params}`);
    },
  });

  const contentTypes = [
    { id: 'all', label: 'All' },
    { id: 'MOVIE', label: 'Movies' },
    { id: 'SERIES', label: 'Series' },
    { id: 'COURSE', label: 'Courses' },
    { id: 'DOCUMENTARY', label: 'Docs' },
  ];

  const featuredItem = featured?.results?.[0];

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        {/* Hero banner */}
        {featuredItem && (
          <div className="relative h-72 md:h-96 bg-gradient-to-r from-slate-900 to-slate-700 overflow-hidden">
            {featuredItem.thumbnail_url && (
              <Image
                src={featuredItem.thumbnail_url}
                alt={featuredItem.title}
                fill
                className="object-cover opacity-40"
                unoptimized
              />
            )}
            <div className="absolute inset-0 bg-gradient-to-t from-background via-transparent to-transparent" />
            <div className="absolute bottom-0 left-0 p-6 md:p-10">
              <Badge variant="secondary" className="mb-2">{featuredItem.content_type}</Badge>
              <h1 className="text-2xl md:text-4xl font-bold text-white mb-2">{featuredItem.title}</h1>
              <p className="text-slate-300 text-sm max-w-md hidden md:block">
                {truncate(featuredItem.description, 120)}
              </p>
              <div className="flex gap-3 mt-4">
                <Link href={`/streaming/${featuredItem.slug}`}>
                  <Button variant="gradient">
                    <Play className="w-4 h-4 mr-2 fill-white" /> Play Now
                  </Button>
                </Link>
                <Link href={`/streaming/${featuredItem.slug}`}>
                  <Button variant="outline" className="border-white/30 text-white hover:bg-white/10">
                    More Info
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        )}

        <div className="p-6 space-y-6">
          {/* Search + filters */}
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Search movies, series, courses..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>
          </div>

          {/* Type filter pills */}
          <div className="flex gap-2 overflow-x-auto scrollbar-hide pb-1">
            {contentTypes.map((type) => (
              <button
                key={type.id}
                onClick={() => setSelectedType(type.id)}
                className={cn(
                  'flex-shrink-0 px-4 py-1.5 rounded-full text-sm font-medium transition-colors border',
                  selectedType === type.id
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'border-border text-muted-foreground hover:bg-accent',
                )}
              >
                {type.label}
              </button>
            ))}
          </div>

          {/* Category filter */}
          {categories?.results && categories.results.length > 0 && (
            <div className="flex gap-2 overflow-x-auto scrollbar-hide pb-1">
              <button
                onClick={() => setSelectedCategory('all')}
                className={cn(
                  'flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium transition-colors border',
                  selectedCategory === 'all'
                    ? 'bg-secondary text-secondary-foreground border-secondary'
                    : 'border-border text-muted-foreground hover:bg-accent',
                )}
              >
                All Categories
              </button>
              {categories.results.map((cat) => (
                <button
                  key={cat.id}
                  onClick={() => setSelectedCategory(cat.slug)}
                  className={cn(
                    'flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium transition-colors border',
                    selectedCategory === cat.slug
                      ? 'bg-secondary text-secondary-foreground border-secondary'
                      : 'border-border text-muted-foreground hover:bg-accent',
                  )}
                >
                  {cat.icon && <span className="mr-1">{cat.icon}</span>}
                  {cat.name}
                </button>
              ))}
            </div>
          )}

          {/* Content grid */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">
                {searchQuery ? `Results for "${searchQuery}"` : 'Browse Content'}
              </h2>
              {content?.count !== undefined && (
                <span className="text-sm text-muted-foreground">{content.count} titles</span>
              )}
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
              {content?.results?.map((item) => (
                <ContentCard key={item.id} item={item} />
              ))}
              {content?.results?.length === 0 && (
                <div className="col-span-full text-center py-16 text-muted-foreground">
                  No content found
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function ContentCard({ item }: { item: ContentItem }) {
  return (
    <Link href={`/streaming/${item.slug}`} className="group">
      <div className="relative aspect-[2/3] rounded-lg overflow-hidden bg-muted mb-2">
        {item.thumbnail_url ? (
          <Image
            src={item.thumbnail_url}
            alt={item.title}
            fill
            className="object-cover group-hover:scale-105 transition-transform duration-300"
            unoptimized
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Play className="w-8 h-8 text-muted-foreground" />
          </div>
        )}
        {/* Overlay */}
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center">
          <Play className="w-10 h-10 text-white opacity-0 group-hover:opacity-100 transition-opacity fill-white" />
        </div>
        {/* Badges */}
        <div className="absolute top-2 left-2 flex gap-1 flex-wrap">
          {item.is_free ? (
            <Badge variant="success" className="text-[9px] px-1.5 py-0">FREE</Badge>
          ) : (
            <div className="w-5 h-5 bg-black/60 rounded-full flex items-center justify-center">
              <Lock className="w-3 h-3 text-white" />
            </div>
          )}
        </div>
        <div className="absolute bottom-2 right-2">
          <Badge variant="secondary" className="text-[9px] px-1.5">{item.content_type}</Badge>
        </div>
      </div>
      <div>
        <p className="text-sm font-medium truncate">{item.title}</p>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {item.release_year && <span>{item.release_year}</span>}
          {item.duration_minutes && (
            <span className="flex items-center gap-0.5">
              <Clock className="w-3 h-3" />
              {item.duration_minutes}m
            </span>
          )}
          {item.rating && (
            <span className="flex items-center gap-0.5">
              <Star className="w-3 h-3 fill-yellow-400 text-yellow-400" />
              {item.rating}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
