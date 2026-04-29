'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Zap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAuthStore } from '@/store/auth.store';
import { isAuthenticated } from '@/lib/auth';

type Step = 'phone' | 'otp';

const OTP_LENGTH = 6;
const OTP_RESEND_SECONDS = 60;

export default function AuthPage() {
  const router = useRouter();
  const { sendOTP, verifyOTP, isLoading, error, otpSent, clearError } = useAuthStore();

  const [step, setStep] = useState<Step>('phone');
  const [phone, setPhone] = useState('');
  const [phoneError, setPhoneError] = useState('');
  const [otp, setOtp] = useState<string[]>(Array(OTP_LENGTH).fill(''));
  const [resendTimer, setResendTimer] = useState(0);
  const otpRefs = useRef<Array<HTMLInputElement | null>>([]);

  useEffect(() => {
    if (isAuthenticated()) router.replace('/dashboard');
  }, [router]);

  useEffect(() => {
    if (otpSent) setStep('otp');
  }, [otpSent]);

  // Resend countdown
  useEffect(() => {
    if (resendTimer <= 0) return;
    const id = setTimeout(() => setResendTimer((t) => t - 1), 1000);
    return () => clearTimeout(id);
  }, [resendTimer]);

  function formatPhoneInput(raw: string): string {
    const digits = raw.replace(/\D/g, '');
    if (digits.startsWith('880')) return '+' + digits;
    if (digits.startsWith('0')) return '+880' + digits.slice(1);
    if (digits.length > 0) return '+880' + digits;
    return '';
  }

  function validatePhone(value: string): boolean {
    const regex = /^\+8801[3-9]\d{8}$/;
    return regex.test(value);
  }

  async function handleSendOTP() {
    clearError();
    const formatted = formatPhoneInput(phone);
    if (!validatePhone(formatted)) {
      setPhoneError('Enter a valid Bangladesh mobile number (e.g. 01XXXXXXXXX)');
      return;
    }
    setPhoneError('');
    try {
      await sendOTP({ phone: formatted });
      setResendTimer(OTP_RESEND_SECONDS);
    } catch {
      // error is set in store
    }
  }

  function handleOTPInput(index: number, value: string) {
    if (!/^\d?$/.test(value)) return;
    const next = [...otp];
    next[index] = value;
    setOtp(next);
    if (value && index < OTP_LENGTH - 1) {
      otpRefs.current[index + 1]?.focus();
    }
  }

  function handleOTPKeyDown(index: number, e: React.KeyboardEvent) {
    if (e.key === 'Backspace' && !otp[index] && index > 0) {
      otpRefs.current[index - 1]?.focus();
    }
  }

  function handleOTPPaste(e: React.ClipboardEvent) {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, OTP_LENGTH);
    const next = [...Array(OTP_LENGTH).fill('')];
    for (let i = 0; i < pasted.length; i++) next[i] = pasted[i];
    setOtp(next);
    otpRefs.current[Math.min(pasted.length, OTP_LENGTH - 1)]?.focus();
  }

  async function handleVerifyOTP() {
    clearError();
    const code = otp.join('');
    if (code.length < OTP_LENGTH) return;
    const formatted = formatPhoneInput(phone);
    try {
      await verifyOTP({ phone: formatted, otp: code });
      router.replace('/dashboard');
    } catch {
      setOtp(Array(OTP_LENGTH).fill(''));
      otpRefs.current[0]?.focus();
    }
  }

  async function handleResend() {
    clearError();
    const formatted = formatPhoneInput(phone);
    await sendOTP({ phone: formatted });
    setResendTimer(OTP_RESEND_SECONDS);
    setOtp(Array(OTP_LENGTH).fill(''));
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 gradient-dce rounded-2xl flex items-center justify-center mb-4 shadow-lg">
            <Zap className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold">DCE Platform</h1>
          <p className="text-muted-foreground text-sm mt-1">Bangladesh Digital Economy</p>
        </div>

        {step === 'phone' ? (
          <div className="space-y-4">
            <div>
              <h2 className="text-lg font-semibold mb-1">Sign in</h2>
              <p className="text-sm text-muted-foreground">Enter your Bangladesh mobile number</p>
            </div>

            <div>
              <label className="text-sm font-medium mb-1 block">Mobile Number</label>
              <Input
                type="tel"
                placeholder="01XXXXXXXXX"
                value={phone}
                onChange={(e) => {
                  setPhone(e.target.value);
                  setPhoneError('');
                }}
                onKeyDown={(e) => e.key === 'Enter' && handleSendOTP()}
                error={phoneError || error || undefined}
                autoFocus
              />
            </div>

            <Button
              className="w-full"
              variant="gradient"
              onClick={handleSendOTP}
              isLoading={isLoading}
            >
              Send OTP
            </Button>

            <p className="text-xs text-center text-muted-foreground">
              We&apos;ll send a 6-digit code via SMS to verify your number.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <button
                onClick={() => {
                  setStep('phone');
                  clearError();
                }}
                className="text-sm text-primary hover:underline mb-2 flex items-center gap-1"
              >
                ← Change number
              </button>
              <h2 className="text-lg font-semibold">Enter OTP</h2>
              <p className="text-sm text-muted-foreground">
                Sent to <span className="font-medium">{formatPhoneInput(phone)}</span>
              </p>
            </div>

            {/* OTP inputs */}
            <div className="flex gap-2 justify-center" onPaste={handleOTPPaste}>
              {otp.map((digit, i) => (
                <input
                  key={i}
                  ref={(el) => { otpRefs.current[i] = el; }}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  onChange={(e) => handleOTPInput(i, e.target.value)}
                  onKeyDown={(e) => handleOTPKeyDown(i, e)}
                  className="w-11 h-12 text-center text-xl font-bold border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
                />
              ))}
            </div>

            {error && <p className="text-sm text-destructive text-center">{error}</p>}

            <Button
              className="w-full"
              variant="gradient"
              onClick={handleVerifyOTP}
              disabled={otp.join('').length < OTP_LENGTH}
              isLoading={isLoading}
            >
              Verify & Continue
            </Button>

            <div className="text-center">
              {resendTimer > 0 ? (
                <p className="text-sm text-muted-foreground">Resend in {resendTimer}s</p>
              ) : (
                <button
                  onClick={handleResend}
                  className="text-sm text-primary hover:underline"
                  disabled={isLoading}
                >
                  Resend OTP
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
