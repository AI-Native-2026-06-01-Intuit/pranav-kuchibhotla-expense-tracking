import { test, expect, type Page, type Route } from '@playwright/test';

const MERCHANT_ID = 'stub-1';

interface GraphQLPayload {
  readonly operationName?: string;
  readonly query?: string;
}

const mockGraphQL = async (page: Page): Promise<void> => {
  await page.route('**/graphql', async (route: Route) => {
    const body = route.request().postDataJSON() as GraphQLPayload | null;
    const op = body?.operationName ?? '';
    if (op === 'LatestMerchants' || body?.query?.includes('latestMerchants')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            latestMerchants: [
              {
                __typename: 'Merchant',
                id: MERCHANT_ID,
                name: 'stub one',
                updatedAt: '2025-01-01T00:00:00Z',
              },
              {
                __typename: 'Merchant',
                id: 'stub-2',
                name: 'stub two',
                updatedAt: '2025-01-02T00:00:00Z',
              },
              {
                __typename: 'Merchant',
                id: 'stub-3',
                name: 'stub three',
                updatedAt: '2025-01-03T00:00:00Z',
              },
            ],
          },
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, body: JSON.stringify({ data: null }) });
  });
};

// Vercel AI SDK data-stream protocol. Each frame is `<code>:<json>\n`.
//   0:"..."  text token
//   9:{toolCallId, toolName, args}  tool call
//   a:{toolCallId, result}          tool result
//   d:{finishReason,...}            finish
const buildChatStream = (): string => {
  const text1 = `0:${JSON.stringify('stub ')}\n`;
  const text2 = `0:${JSON.stringify('merchant ')}\n`;
  const text3 = `0:${JSON.stringify('reply.')}\n`;
  const toolCall = `9:${JSON.stringify({
    toolCallId: 'tool-1',
    toolName: 'lookup_merchant',
    args: { id: MERCHANT_ID },
  })}\n`;
  const toolResult = `a:${JSON.stringify({
    toolCallId: 'tool-1',
    result: { ok: true, id: MERCHANT_ID },
  })}\n`;
  const finish = `d:${JSON.stringify({
    finishReason: 'stop',
    usage: { promptTokens: 1, completionTokens: 3 },
  })}\n`;
  return text1 + text2 + text3 + toolCall + toolResult + finish;
};

const mockChat = async (page: Page): Promise<void> => {
  await page.route('**/api/chat', async (route: Route) => {
    await route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'X-Vercel-AI-Data-Stream': 'v1',
      },
      body: buildChatStream(),
    });
  });
};

test.describe('merchant chat happy path (E2E)', () => {
  test('signs in, opens a merchant, streams a reply with a tool call, and survives reload', async ({
    page,
  }) => {
    await mockGraphQL(page);
    await mockChat(page);

    await page.goto('/merchants');
    await expect(
      page.getByRole('list', { name: /merchant-list/i }),
    ).toBeVisible();

    const firstMerchantLink = page.getByRole('link', { name: 'stub one' });
    await expect(firstMerchantLink).toHaveAttribute(
      'href',
      `/merchants/${MERCHANT_ID}`,
    );
    await firstMerchantLink.click();
    await expect(page).toHaveURL(new RegExp(`/merchants/${MERCHANT_ID}$`));

    await page.goto(`/merchants/${MERCHANT_ID}/chat`);
    await expect(
      page.getByRole('heading', { level: 1, name: new RegExp(MERCHANT_ID) }),
    ).toBeVisible();

    const input = page.getByRole('textbox', { name: /chat-message/i });
    await input.fill('hello there');
    await page.getByRole('button', { name: /^send$/i }).click();

    const transcript = page.getByRole('log', { name: /chat-transcript/i });
    await expect(transcript).toContainText('stub merchant reply.');
    await expect(transcript.getByRole('listitem').last()).toHaveAttribute(
      'data-role',
      'assistant',
    );

    const toolCall = page.getByLabel('tool-call');
    await expect(toolCall).toBeVisible();
    await expect(toolCall).toContainText('lookup_merchant');

    await page.reload();

    const transcriptAfter = page.getByRole('log', { name: /chat-transcript/i });
    await expect(transcriptAfter).toContainText('stub merchant reply.');
  });
});
