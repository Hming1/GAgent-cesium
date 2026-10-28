import { test, expect, Page } from "@playwright/test";

const mockSettings = {
  system_prompt: "You are a helpful assistant.",
  tool_options: {
    search: {
      default_prompt: "Search prompt",
      settings: {},
    },
  },
  example_geoserver_backends: [
    {
      url: "https://geoserver.mapx.org/geoserver/",
      name: "MapX",
      description: "Example GeoServer",
    },
  ],
  model_options: {
    MockProvider: [{ name: "mock-model", max_tokens: 999 }],
  },
  session_id: "test-session",
};


async function mockAuth(page: Page) {
  await page.route("**/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        username: "test-user",
        email: "test@example.com",
      }),
    });
  });
}
async function mockStreamingResponse(page: Page, response: unknown) {
  await page.addInitScript((mockResponse: unknown) => {
    const originalFetch = window.fetch;
    (window as any).fetch = async function(input: RequestInfo | URL, init?: RequestInit) {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;

      if (url.includes("/chat/stream")) {
        const encoder = new TextEncoder();
        const stream = new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(`event: result\ndata: ${JSON.stringify(mockResponse)}\n\n`),
            );
            controller.enqueue(
              encoder.encode(`event: done\ndata: ${JSON.stringify({ status: "complete" })}\n\n`),
            );
            controller.close();
          },
        });

        return new Response(stream, {
          status: 200,
          headers: {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
          },
        });
      }

      return originalFetch(input, init);
    };
  }, response);
}

test.describe("Chat interface", () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page);
  });
  test("sends a message and renders agent response", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    const mockResponse = {
      messages: [
        { type: "human", content: "Hello agent!" },
        { type: "ai", content: "Mock agent response" },
      ],
      geodata_results: [],
      geodata_layers: [],
      metrics: {
        agent_execution_time: 1.5,
        token_usage: { total: 50, prompt: 25, completion: 25 },
      },
    };

    await mockStreamingResponse(page, mockResponse);

    await page.goto("/map");

    const chatInput = page.locator("textarea");
    await chatInput.fill("Hello agent!");
    await chatInput.press("Enter");

    await expect(page.getByText("Hello agent!").first()).toBeVisible();
    await expect(page.getByText("Mock agent response")).toBeVisible();
  });

  test("hides stale search results when a normal chat response has no geodata", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    const mockResponse = {
      messages: [
        { type: "human", content: "What model are you?" },
        { type: "ai", content: "I am the configured GeoAgent assistant." },
      ],
      geodata_results: [],
      geodata_layers: [],
    };

    await mockStreamingResponse(page, mockResponse);

    await page.goto("/map");

    await page.evaluate(() => {
      const { useChatInterfaceStore } = (window as any);
      const store = useChatInterfaceStore.getState();
      store.setGeoDataList([
        {
          id: "old-result",
          title: "Old Layer Intersection",
          llm_description: "A stale result from a previous task",
          layer_type: "GeoJSON",
        },
      ]);
    });

    await expect(page.getByText("Old Layer Intersection")).toBeVisible();

    const chatInput = page.locator("textarea");
    await chatInput.fill("What model are you?");
    await chatInput.press("Enter");

    await expect(page.getByText("I am the configured GeoAgent assistant.")).toBeVisible();
    await expect(page.getByText("Old Layer Intersection")).not.toBeVisible();
  });
  test("renders markdown tables in agent responses", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    const mockResponse = {
      messages: [
        { type: "human", content: "Show a table" },
        {
          type: "ai",
          content:
            "Here is a table:\n\n| Name | Value |\n| --- | --- |\n| Alpha | 1 |\n| Beta | 2 |",
        },
      ],
      geodata_results: [],
      geodata_layers: [],
    };

    await mockStreamingResponse(page, mockResponse);

    await page.goto("/map");

    const chatInput = page.locator("textarea");
    await chatInput.fill("Show a table");
    await chatInput.press("Enter");

    const table = page.locator(".chat-markdown table");
    await expect(table).toBeVisible();
    await expect(table.locator("th")).toContainText(["Name", "Value"]);
    await expect(table.locator("td")).toContainText(["Alpha", "1", "Beta", "2"]);
  });
  test("collapses intermediate agent process messages", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    const mockResponse = {
      messages: [
        { type: "human", content: "统计深圳各区公园密度" },
        { type: "ai", content: "先获取深圳市行政区边界。" },
        { type: "ai", content: "继续获取公园面数据。" },
        { type: "ai", content: "正在执行空间叠加分析。" },
        { type: "ai", content: "分析完成：南山区公园密度最高。" },
      ],
      geodata_results: [],
      geodata_layers: [],
    };

    await mockStreamingResponse(page, mockResponse);

    await page.goto("/map");

    const chatInput = page.locator("textarea");
    await chatInput.fill("统计深圳各区公园密度");
    await chatInput.press("Enter");

    await expect(page.getByRole("button", { name: /执行过程/ })).toBeVisible();
    await expect(page.getByText("3 条进度")).toBeVisible();
    await expect(page.getByText("分析完成：南山区公园密度最高。")).toBeVisible();
    await expect(page.getByText("继续获取公园面数据。")).not.toBeVisible();

    await page.getByRole("button", { name: /执行过程/ }).click();

    await expect(page.getByText("继续获取公园面数据。")).toBeVisible();
    await expect(page.getByText("正在执行空间叠加分析。")).toBeVisible();
  });
});
