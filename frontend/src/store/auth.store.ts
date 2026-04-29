import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import type { AuthResponse, OTPSendRequest, OTPVerifyRequest, User } from '@/types';
import { post } from '@/lib/api';
import { clearTokens, setStoredUser, setTokens } from '@/lib/auth';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  otpSent: boolean;
  // Actions
  sendOTP: (payload: OTPSendRequest) => Promise<void>;
  verifyOTP: (payload: OTPVerifyRequest) => Promise<AuthResponse>;
  logout: () => void;
  setUser: (user: User) => void;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>()(
  devtools(
    persist(
      (set) => ({
        user: null,
        isAuthenticated: false,
        isLoading: false,
        error: null,
        otpSent: false,

        sendOTP: async (payload) => {
          set({ isLoading: true, error: null });
          try {
            await post('/auth/otp/send/', {
              phone_number: payload.phone,
              purpose: (payload.purpose ?? 'LOGIN').toLowerCase(),
            });
            set({ otpSent: true, isLoading: false });
          } catch (err: unknown) {
            const msg = extractErrorMessage(err, 'Failed to send OTP');
            set({ error: msg, isLoading: false });
            throw new Error(msg);
          }
        },

        verifyOTP: async (payload) => {
          set({ isLoading: true, error: null });
          try {
            const raw = await post<{ success: boolean; data: AuthResponse }>('/auth/otp/verify/', {
              phone_number: payload.phone,
              otp_code: payload.otp,
              purpose: (payload.purpose ?? 'LOGIN').toLowerCase(),
            });
            const response = raw.data;
            setTokens(response.tokens);
            setStoredUser(response.user);
            set({
              user: response.user,
              isAuthenticated: true,
              isLoading: false,
              otpSent: false,
            });
            return response;
          } catch (err: unknown) {
            const msg = extractErrorMessage(err, 'Invalid OTP');
            set({ error: msg, isLoading: false });
            throw new Error(msg);
          }
        },

        logout: () => {
          clearTokens();
          set({ user: null, isAuthenticated: false, otpSent: false, error: null });
        },

        setUser: (user) => {
          set({ user, isAuthenticated: true });
          setStoredUser(user);
        },

        clearError: () => set({ error: null }),
      }),
      {
        name: 'dce-auth',
        partialize: (state) => ({
          user: state.user,
          isAuthenticated: state.isAuthenticated,
        }),
      },
    ),
    { name: 'AuthStore' },
  ),
);

function extractErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const axiosErr = err as { response?: { data?: { message?: string; detail?: string } } };
    return (
      axiosErr.response?.data?.message ??
      axiosErr.response?.data?.detail ??
      fallback
    );
  }
  if (err instanceof Error) return err.message;
  return fallback;
}
