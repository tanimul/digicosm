import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import type {
  DepositMethod,
  DepositRequest,
  PaginatedResponse,
  Transaction,
  Wallet,
  WithdrawalRequest,
} from '@/types';
import { get, post } from '@/lib/api';

interface WalletState {
  wallet: Wallet | null;
  transactions: Transaction[];
  transactionCount: number;
  isLoading: boolean;
  isDepositing: boolean;
  isWithdrawing: boolean;
  error: string | null;
  // Actions
  fetchWallet: () => Promise<void>;
  fetchTransactions: (page?: number) => Promise<void>;
  initiateDeposit: (method: DepositMethod, amount: number) => Promise<DepositRequest>;
  initiateWithdrawal: (method: DepositMethod, amount: number, accountNumber: string) => Promise<WithdrawalRequest>;
  clearError: () => void;
}

export const useWalletStore = create<WalletState>()(
  devtools(
    (set, get) => ({
      wallet: null,
      transactions: [],
      transactionCount: 0,
      isLoading: false,
      isDepositing: false,
      isWithdrawing: false,
      error: null,

      fetchWallet: async () => {
        set({ isLoading: true, error: null });
        try {
          const wallet = await get<Wallet>('/wallet/balance/');
          set({ wallet, isLoading: false });
        } catch (err) {
          set({ error: extractError(err, 'Failed to fetch wallet'), isLoading: false });
        }
      },

      fetchTransactions: async (page = 1) => {
        set({ isLoading: true, error: null });
        try {
          const res = await get<PaginatedResponse<Transaction>>(`/wallet/transactions/?page=${page}`);
          set({
            transactions: page === 1 ? res.results : [...get().transactions, ...res.results],
            transactionCount: res.count,
            isLoading: false,
          });
        } catch (err) {
          set({ error: extractError(err, 'Failed to fetch transactions'), isLoading: false });
        }
      },

      initiateDeposit: async (method, amount) => {
        set({ isDepositing: true, error: null });
        try {
          const deposit = await post<DepositRequest>('/wallet/deposit/', {
            method,
            amount_bdt: amount,
          });
          set({ isDepositing: false });
          return deposit;
        } catch (err) {
          const msg = extractError(err, 'Deposit failed');
          set({ error: msg, isDepositing: false });
          throw new Error(msg);
        }
      },

      initiateWithdrawal: async (method, amount, accountNumber) => {
        set({ isWithdrawing: true, error: null });
        try {
          const withdrawal = await post<WithdrawalRequest>('/wallet/withdraw/', {
            method,
            amount_bdt: amount,
            account_number: accountNumber,
          });
          set({ isWithdrawing: false });
          return withdrawal;
        } catch (err) {
          const msg = extractError(err, 'Withdrawal failed');
          set({ error: msg, isWithdrawing: false });
          throw new Error(msg);
        }
      },

      clearError: () => set({ error: null }),
    }),
    { name: 'WalletStore' },
  ),
);

function extractError(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const axiosErr = err as { response?: { data?: { message?: string; detail?: string } } };
    return axiosErr.response?.data?.message ?? axiosErr.response?.data?.detail ?? fallback;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}
