import { Hono } from 'hono';
import { serve } from '@hono/node-server';
import { chatRoute } from './api/chat';

// Threat model: this proxy holds the upstream AI baseURL and any future
// secrets. The browser only ever calls /api/chat — it never sees the
// upstream host. Keep all model/provider config server-side.
const app = new Hono();

const api = new Hono();
api.route('/chat', chatRoute);
app.route('/api', api);

const port = 3001;
serve({ fetch: app.fetch, port }, (info) => {
  console.log(`[expense-web] chat proxy listening on http://localhost:${info.port}`);
});
