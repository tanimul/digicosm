'use client';

import { useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Send, Bot, User, Plus, ChevronDown, Zap, AlertCircle } from 'lucide-react';
import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useWalletStore } from '@/store/wallet.store';
import { get, post } from '@/lib/api';
import { cn, formatCredits } from '@/lib/utils';
import type { AIConversation, AIChatResponse, AIMessage, AIService } from '@/types';

export default function AIPlaygroundPage() {
  const { wallet, fetchWallet } = useWalletStore();
  const [selectedService, setSelectedService] = useState<AIService | null>(null);
  const [conversation, setConversation] = useState<AIConversation | null>(null);
  const [messages, setMessages] = useState<AIMessage[]>([]);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState('');
  const [showServicePicker, setShowServicePicker] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { fetchWallet(); }, [fetchWallet]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const { data: services } = useQuery({
    queryKey: ['ai-services'],
    queryFn: () => get<{ results: AIService[] }>('/ai/services/'),
  });

  // Auto-select first service when loaded
  useEffect(() => {
    if (services?.results?.length && !selectedService) {
      setSelectedService(services.results[0]);
    }
  }, [services, selectedService]);

  const { data: conversations } = useQuery({
    queryKey: ['ai-conversations'],
    queryFn: () => get<{ results: AIConversation[] }>('/ai/conversations/?page_size=20'),
  });

  async function loadConversation(conv: AIConversation) {
    setConversation(conv);
    setError('');
    try {
      const msgs = await get<{ results: AIMessage[] }>(`/ai/conversations/${conv.id}/messages/`);
      setMessages(msgs.results ?? []);
    } catch {
      setMessages([]);
    }
  }

  function startNew() {
    setConversation(null);
    setMessages([]);
    setError('');
    setInput('');
  }

  async function sendMessage() {
    if (!input.trim() || !selectedService || isSending) return;
    const userText = input.trim();
    setInput('');
    setError('');
    setIsSending(true);

    // Optimistic user message
    const optimisticMsg: AIMessage = {
      id: `optimistic-${Date.now()}`,
      role: 'USER',
      content: userText,
      tokens_used: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticMsg]);

    try {
      const response = await post<AIChatResponse>('/ai/chat/', {
        service_slug: selectedService.slug,
        message: userText,
        conversation_id: conversation?.id,
      });

      // Update conversation
      if (!conversation) {
        const convData = await get<AIConversation>(`/ai/conversations/${response.conversation_id}/`);
        setConversation(convData);
      }

      const assistantMsg: AIMessage = {
        id: `assistant-${Date.now()}`,
        role: 'ASSISTANT',
        content: response.message,
        tokens_used: response.tokens_used,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      fetchWallet(); // refresh credits
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { message?: string } } }).response?.data?.message ?? 'Failed to get response'
          : 'Failed to get response';
      setError(msg);
      setMessages((prev) => prev.filter((m) => m.id !== optimisticMsg.id));
    } finally {
      setIsSending(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <AppShell>
      <div className="flex flex-1 h-[calc(100vh-4rem)] md:h-screen overflow-hidden">
        {/* Conversation sidebar */}
        <aside className="hidden lg:flex flex-col w-60 border-r border-border bg-card">
          <div className="p-4 border-b border-border">
            <Button onClick={startNew} size="sm" className="w-full" variant="outline">
              <Plus className="w-4 h-4 mr-2" /> New Chat
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {conversations?.results?.map((conv) => (
              <button
                key={conv.id}
                onClick={() => loadConversation(conv)}
                className={cn(
                  'w-full text-left px-3 py-2 rounded-md text-sm truncate transition-colors',
                  conversation?.id === conv.id
                    ? 'bg-primary/10 text-primary font-medium'
                    : 'hover:bg-accent text-muted-foreground',
                )}
              >
                {conv.title ?? 'Untitled conversation'}
              </button>
            ))}
          </div>
          {/* Credits indicator */}
          {wallet && (
            <div className="p-3 border-t border-border">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Zap className="w-3.5 h-3.5 text-yellow-500" />
                <span>{formatCredits(wallet.credits)} remaining</span>
              </div>
            </div>
          )}
        </aside>

        {/* Chat area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Header / Service selector */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-card">
            <div className="flex items-center gap-2">
              <Bot className="w-5 h-5 text-primary" />
              <button
                onClick={() => setShowServicePicker(!showServicePicker)}
                className="flex items-center gap-1 text-sm font-medium hover:text-primary transition-colors"
              >
                {selectedService?.name ?? 'Select model'}
                <ChevronDown className="w-3.5 h-3.5" />
              </button>
              {selectedService && (
                <Badge variant="secondary" className="text-[10px]">
                  {selectedService.sell_price_credits} cr/req
                </Badge>
              )}
            </div>
            <Button onClick={startNew} size="sm" variant="ghost" className="lg:hidden">
              <Plus className="w-4 h-4" />
            </Button>
          </div>

          {/* Service picker dropdown */}
          {showServicePicker && (
            <div className="absolute top-16 left-0 right-0 z-40 mx-4 bg-card border rounded-lg shadow-lg p-2 max-h-60 overflow-y-auto">
              {services?.results?.map((s) => (
                <button
                  key={s.id}
                  onClick={() => { setSelectedService(s); setShowServicePicker(false); }}
                  className={cn(
                    'w-full text-left flex items-center justify-between p-2 rounded hover:bg-accent text-sm',
                    selectedService?.id === s.id && 'bg-accent',
                  )}
                >
                  <div>
                    <span className="font-medium">{s.name}</span>
                    <span className="text-muted-foreground ml-2">{s.provider}</span>
                  </div>
                  <Badge variant="outline" className="text-[10px]">{s.sell_price_credits} cr</Badge>
                </button>
              ))}
            </div>
          )}

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <div className="w-16 h-16 gradient-dce rounded-2xl flex items-center justify-center mb-4">
                  <Bot className="w-8 h-8 text-white" />
                </div>
                <h2 className="text-xl font-semibold mb-2">DCE AI Playground</h2>
                <p className="text-muted-foreground text-sm max-w-sm">
                  Ask anything — powered by OpenAI, Claude, DeepSeek, Gemini, and Cohere.
                </p>
                <div className="mt-6 grid grid-cols-2 gap-2 text-sm">
                  {['Summarize this article', 'Write a business email', 'Explain a concept', 'Generate code'].map((s) => (
                    <button
                      key={s}
                      onClick={() => { setInput(s); textareaRef.current?.focus(); }}
                      className="px-3 py-2 rounded-lg border hover:bg-accent text-left transition-colors"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg) => (
              <div
                key={msg.id}
                className={cn('flex gap-3', msg.role === 'USER' ? 'justify-end' : 'justify-start')}
              >
                {msg.role === 'ASSISTANT' && (
                  <div className="w-7 h-7 rounded-full gradient-dce flex items-center justify-center flex-shrink-0 mt-0.5">
                    <Bot className="w-3.5 h-3.5 text-white" />
                  </div>
                )}
                <div
                  className={cn(
                    'max-w-[80%] rounded-xl px-4 py-2.5 text-sm whitespace-pre-wrap break-words',
                    msg.role === 'USER'
                      ? 'bg-primary text-primary-foreground rounded-br-sm'
                      : 'bg-muted rounded-bl-sm',
                  )}
                >
                  {msg.content}
                  {msg.tokens_used && (
                    <span className="block text-[10px] mt-1 opacity-60">{msg.tokens_used} tokens</span>
                  )}
                </div>
                {msg.role === 'USER' && (
                  <div className="w-7 h-7 rounded-full bg-primary flex items-center justify-center flex-shrink-0 mt-0.5">
                    <User className="w-3.5 h-3.5 text-primary-foreground" />
                  </div>
                )}
              </div>
            ))}

            {isSending && (
              <div className="flex gap-3">
                <div className="w-7 h-7 rounded-full gradient-dce flex items-center justify-center flex-shrink-0">
                  <Bot className="w-3.5 h-3.5 text-white" />
                </div>
                <div className="bg-muted rounded-xl rounded-bl-sm px-4 py-3">
                  <div className="flex gap-1">
                    <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-2 h-2 bg-muted-foreground rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                </div>
              </div>
            )}

            {error && (
              <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 rounded-lg p-3">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                {error}
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input area */}
          <div className="p-4 border-t border-border bg-card">
            <div className="flex gap-2 items-end">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={selectedService ? `Ask ${selectedService.name}...` : 'Select a model first'}
                rows={1}
                className="flex-1 resize-none rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring min-h-[40px] max-h-32"
                style={{ height: 'auto' }}
                onInput={(e) => {
                  const el = e.currentTarget;
                  el.style.height = 'auto';
                  el.style.height = Math.min(el.scrollHeight, 128) + 'px';
                }}
                disabled={!selectedService || isSending}
              />
              <Button
                onClick={sendMessage}
                disabled={!input.trim() || !selectedService || isSending}
                size="icon"
                className="flex-shrink-0"
              >
                <Send className="w-4 h-4" />
              </Button>
            </div>
            <p className="text-[10px] text-muted-foreground mt-1 text-center">
              Press Enter to send · Shift+Enter for newline
            </p>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
