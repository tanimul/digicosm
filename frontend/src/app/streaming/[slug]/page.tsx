'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation } from '@tanstack/react-query';
import { ArrowLeft, Play, Clock, Star, Lock, Globe, Subtitles } from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';
import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { get, post } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { ContentEpisode, ContentItem } from '@/types';

export default function ContentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params.slug as string;
  const [selectedEpisode, setSelectedEpisode] = useState<ContentEpisode | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  const { data: content, isLoading } = useQuery({
    queryKey: ['streaming-content', slug],
    queryFn: () => get<ContentItem>(`/streaming/content/${slug}/`),
  });

  const { data: episodes } = useQuery({
    queryKey: ['streaming-episodes', slug],
    queryFn: () => get<{ results: ContentEpisode[] }>(`/streaming/content/${slug}/episodes/`),
    enabled: content?.content_type === 'SERIES',
  });

  const streamMutation = useMutation({
    mutationFn: (episodeId?: string) =>
      post<{ stream_url: string; token: string }>(`/streaming/content/${slug}/stream/`, {
        episode_id: episodeId,
      }),
    onSuccess: () => setIsPlaying(true),
  });

  if (isLoading) {
    return (
      <AppShell>
        <div className="flex-1 flex items-center justify-center">
          <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      </AppShell>
    );
  }

  if (!content) {
    return (
      <AppShell>
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <p className="text-muted-foreground">Content not found</p>
          <Link href="/streaming"><Button variant="outline">Back to Streaming</Button></Link>
        </div>
      </AppShell>
    );
  }

  const episodeToPlay = selectedEpisode ?? episodes?.results?.[0] ?? undefined;

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        {/* Hero */}
        <div className="relative h-64 md:h-96 bg-slate-900 overflow-hidden">
          {content.thumbnail_url && !isPlaying && (
            <Image
              src={content.thumbnail_url}
              alt={content.title}
              fill
              className="object-cover opacity-50"
              unoptimized
            />
          )}
          {isPlaying && streamMutation.data && (
            <video
              className="w-full h-full object-contain bg-black"
              src={streamMutation.data.stream_url}
              controls
              autoPlay
            />
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-background to-transparent" />

          {/* Back button */}
          <button
            onClick={() => router.back()}
            className="absolute top-4 left-4 flex items-center gap-1 text-white/80 hover:text-white text-sm"
          >
            <ArrowLeft className="w-4 h-4" /> Back
          </button>

          {/* Play button */}
          {!isPlaying && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Button
                variant="gradient"
                size="lg"
                onClick={() => streamMutation.mutate(episodeToPlay?.id)}
                isLoading={streamMutation.isPending}
                className="rounded-full w-16 h-16"
              >
                <Play className="w-6 h-6 fill-white" />
              </Button>
            </div>
          )}
        </div>

        <div className="p-6 space-y-6">
          {/* Title and meta */}
          <div>
            <div className="flex items-start justify-between gap-4 mb-2">
              <h1 className="text-3xl font-bold">{content.title}</h1>
              {!content.is_free && <Lock className="w-5 h-5 text-muted-foreground flex-shrink-0 mt-1" />}
            </div>
            <div className="flex flex-wrap gap-3 text-sm text-muted-foreground mb-3">
              {content.release_year && <span>{content.release_year}</span>}
              {content.duration_minutes && (
                <span className="flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5" /> {content.duration_minutes}m
                </span>
              )}
              {content.rating && (
                <span className="flex items-center gap-1">
                  <Star className="w-3.5 h-3.5 fill-yellow-400 text-yellow-400" /> {content.rating}
                </span>
              )}
              {content.language && (
                <span className="flex items-center gap-1">
                  <Globe className="w-3.5 h-3.5" /> {content.language}
                </span>
              )}
              {content.subtitle_languages?.length > 0 && (
                <span className="flex items-center gap-1">
                  <Subtitles className="w-3.5 h-3.5" /> {content.subtitle_languages.join(', ')}
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5 mb-4">
              <Badge variant="secondary">{content.content_type}</Badge>
              {content.is_free && <Badge variant="success">FREE</Badge>}
              {content.categories?.map((cat) => (
                <Badge key={cat.id} variant="outline">{cat.name}</Badge>
              ))}
            </div>
            <p className="text-muted-foreground">{content.description}</p>
          </div>

          {/* Cast / Director */}
          {(content.director || content.cast?.length > 0) && (
            <Card>
              <CardContent className="p-4">
                {content.director && (
                  <p className="text-sm mb-1">
                    <span className="font-medium">Director:</span>{' '}
                    <span className="text-muted-foreground">{content.director}</span>
                  </p>
                )}
                {content.cast?.length > 0 && (
                  <p className="text-sm">
                    <span className="font-medium">Cast:</span>{' '}
                    <span className="text-muted-foreground">{content.cast.join(', ')}</span>
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {/* Episodes for series */}
          {content.content_type === 'SERIES' && episodes?.results && episodes.results.length > 0 && (
            <div>
              <h2 className="text-lg font-semibold mb-3">Episodes</h2>
              <div className="space-y-2">
                {episodes.results.map((ep) => (
                  <div
                    key={ep.id}
                    onClick={() => setSelectedEpisode(ep)}
                    className={cn(
                      'flex items-center gap-4 p-3 rounded-lg border cursor-pointer hover:bg-accent transition-colors',
                      selectedEpisode?.id === ep.id && 'border-primary bg-primary/5',
                    )}
                  >
                    <div className="w-10 h-10 rounded bg-muted flex items-center justify-center flex-shrink-0">
                      <Play className="w-4 h-4 text-muted-foreground" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">
                        S{ep.season_number}E{ep.episode_number} — {ep.title}
                      </p>
                      {ep.description && (
                        <p className="text-xs text-muted-foreground truncate">{ep.description}</p>
                      )}
                    </div>
                    {ep.duration_minutes && (
                      <span className="text-xs text-muted-foreground flex-shrink-0">
                        {ep.duration_minutes}m
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* CTA if locked */}
          {!content.is_free && (
            <Card className="border-primary/30 bg-primary/5">
              <CardContent className="p-5 flex flex-col sm:flex-row items-center justify-between gap-4">
                <div>
                  <p className="font-semibold">Premium Content</p>
                  <p className="text-sm text-muted-foreground">Subscribe to unlock HD streaming and this title.</p>
                </div>
                <Link href="/marketplace?tab=subscriptions">
                  <Button variant="gradient">Subscribe Now</Button>
                </Link>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </AppShell>
  );
}
