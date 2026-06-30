/// <reference types="vitest" />
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setupTests.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    server: {
      deps: {
        inline: ['msw'],
      },
    },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/test/**',
        'src/gql/generated/**',
        'dist/**',
        'coverage/**',
      ],
      thresholds: {
        // Branches at >= 70 is load-bearing for the W4D5 capstone.
        // Lines/functions/statements track current realistic coverage —
        // raise them in Task 4 once additional component/page tests land.
        branches: 70,
        lines: 65,
        functions: 70,
        statements: 65,
      },
    },
  },
});
