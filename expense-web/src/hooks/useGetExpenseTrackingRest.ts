import { useQuery } from '@tanstack/react-query';

export type MerchantRest = {
  id: string;
  name: string;
  updatedAt: string;
};

export const useGetExpenseTrackingRest = (id: string) =>
  useQuery<MerchantRest>({
    queryKey: ['expense', id],
    enabled: Boolean(id),
    queryFn: async () => {
      const res = await fetch(`http://localhost:8080/api/v1/merchants/${id}`);
      if (!res.ok) {
        throw new Error(`HTTP ${String(res.status)}`);
      }
      return res.json() as Promise<MerchantRest>;
    },
  });
