import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/auth/me", (route) => route.fulfill({
    json: { id: "history-user", email: "history@example.com" },
  }));
  await page.route("**/settings/options", (route) => route.fulfill({ json: {
    system_prompt: "Test assistant", available_tools: [], tool_options: {},
    model_options: { MockProvider: [{ name: "mock-model", max_tokens: 4096 }] },
    session_id: "history-session",
  } }));
  await page.route("**/maps/", (route) => route.fulfill({ json: [] }));
});

test("tool history survives a city follow-up without changing the previous progress", async ({ page }) => {
  const requests: any[] = [];
  const firstTurn = [
    { type: "ai", content: "", id: "ai-search", tool_calls: [
      { id: "gz-search", name: "find_schools", args: { city: "广州" }, type: "tool_call" },
    ], additional_kwargs: { reasoning_content: "Search schools" } },
    { type: "tool", content: "广州工具结果", name: "find_schools", tool_call_id: "gz-search" },
    { type: "ai", content: "正在统计广州中学", tool_calls: [
      { id: "gz-stats", name: "school_statistics", args: {}, type: "tool_call" },
    ] },
    { type: "tool", content: "广州统计结果", name: "school_statistics", tool_call_id: "gz-stats" },
    { type: "ai", content: "广州任务已完成" },
  ];
  await page.route("**/chat/stream", async (route) => {
    const payload = route.request().postDataJSON();
    requests.push(payload);
    const followup = requests.length > 1;
    const callId = followup ? "sz-search" : "gz-search";
    const messages = followup ? [
      ...payload.messages,
      { type: "ai", content: "", tool_calls: [
        { id: callId, name: "find_schools", args: { city: "深圳" }, type: "tool_call" },
      ] },
      { type: "tool", content: "深圳工具结果", name: "find_schools", tool_call_id: callId },
      { type: "ai", content: "深圳任务已完成" },
    ] : [...payload.messages, ...firstTurn];
    const events = [
      ["tool_start", { tool: "find_schools", tool_call_id: callId, input: { query: followup ? "深圳中学" : "广州中学" } }],
      ["tool_end", { tool: "find_schools", tool_call_id: callId, status: "success", output: "schools" }],
      ["result", { messages, geodata_results: [], geodata_layers: [] }],
      ["done", { status: "complete" }],
    ];
    await route.fulfill({ contentType: "text/event-stream", body: events.map(
      ([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
    ).join("") });
  });
  await page.goto("/map");
  await page.getByRole("checkbox", { name: "计划模式", exact: true }).uncheck();
  const input = page.locator("textarea");
  await input.fill("帮我找广州中学，按办学类型统计并上图");
  await input.press("Enter");
  await expect(page.getByText("广州任务已完成", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /执行过程/ })).toHaveCount(1);
  await input.fill("深圳市的也需要");
  await input.press("Enter");
  await expect(page.getByText("深圳任务已完成", { exact: true })).toBeVisible();
  expect(requests[1].messages.slice(1, -1)).toEqual(firstTurn);
  await expect(page.getByRole("button", { name: /执行过程/ })).toHaveCount(1);
  await expect(page.getByText("广州工具结果", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: /执行过程/ }).click();
  await expect(page.getByText("正在统计广州中学", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "展开执行流程", exact: true }).click();
  await expect(page.locator(".agent-run-flow")).toContainText("深圳中学");
  await expect(page.locator(".agent-run-flow")).not.toContainText("广州中学");
});

test("a third-turn model error is visible and the next request can recover", async ({ page }) => {
  let turn = 0;
  await page.route("**/chat/stream", async (route) => {
    turn += 1;
    const payload = route.request().postDataJSON();
    const events = turn === 3 ? [
      ["error", { error: "api_error", message: "System message must be at the beginning." }],
      ["done", { status: "error" }],
    ] : [
      ["result", {
        messages: [...payload.messages, { type: "ai", content: `完成第 ${turn} 轮` }],
        geodata_results: [], geodata_layers: [],
      }],
      ["done", { status: "complete" }],
    ];
    await route.fulfill({ contentType: "text/event-stream", body: events.map(
      ([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
    ).join("") });
  });
  await page.goto("/map");
  await page.getByRole("checkbox", { name: "计划模式", exact: true }).uncheck();
  const input = page.locator("textarea");
  for (const [index, query] of ["广州的", "深圳的", "上海的", "北京的"].entries()) {
    await input.fill(query);
    await input.press("Enter");
    if (index === 2) {
      await expect(page.getByRole("alert").filter({ hasText: "请求未完成" })).toContainText("System message must be at the beginning.");
      await expect(page.getByText("完成第 2 轮", { exact: true })).toBeVisible();
    } else {
      await expect(page.getByText(`完成第 ${index + 1} 轮`, { exact: true })).toBeVisible();
      await expect(page.getByRole("alert").filter({ hasText: "请求未完成" })).toHaveCount(0);
    }
    await expect(input).toBeEnabled();
  }
});
