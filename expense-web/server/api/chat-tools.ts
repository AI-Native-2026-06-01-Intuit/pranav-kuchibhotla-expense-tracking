import { tool } from 'ai';
import { z } from 'zod';

// W3 D2 REST backend lives at this base. Kept server-side so the browser
// never learns the upstream host.
const BACKEND = 'http://localhost:8080/api/v1';

export const merchantTools = {
  lookupMerchant: tool({
    description: 'looks up one merchant by id from W3 D2 REST backend',
    parameters: z.object({ id: z.string() }),
    execute: async ({ id }): Promise<unknown> => {
      const res = await fetch(`${BACKEND}/merchants/${id}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    },
  }),
  classifyDeduction: tool({
    description:
      'classifies/searches deduction category by merchantId using W3 D2 REST backend',
    parameters: z.object({ merchantId: z.string() }),
    execute: async ({ merchantId }): Promise<unknown> => {
      const res = await fetch(
        `${BACKEND}/merchants?merchantId=${merchantId}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    },
  }),
};
