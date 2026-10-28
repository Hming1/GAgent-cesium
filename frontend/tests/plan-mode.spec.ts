import { expect, test } from "@playwright/test";

test("plan mode can be enabled again after multiple chat turns and a confirmed plan", async ({ page }) => {
  await page.route("**/auth/me", (route) => route.fulfill({
    json: { id: "plan-user", email: "plan@example.com" },
  }));
  await page.route("**/settings/options", (route) => route.fulfill({ json: {
    system_prompt: "Test assistant",
    available_tools: [],
    tool_options: {},
    model_options: { MockProvider: [{ name: "mock-model", max_tokens: 4096 }] },
    session_id: "plan-session",
  } }));
  await page.route("**/maps/", (route) => route.fulfill({ json: [] }));
  const requests: any[] = [];
  await page.route("**/chat/stream", async (route) => {
    const payload = route.request().postDataJSON();
    requests.push(payload);
    const plan = payload.execution_plan ?? (payload.options.model_settings.plan_mode ? {
      title: `Plan: ${payload.query}`,
      steps: [{ action: "List current layers", tool: "list_user_layers" }],
      summary: "Show current layers",
      status: "pending",
      step_count: 1,
    } : undefined);
    const result = {
      messages: [...payload.messages, { type: "ai", content: `Reply ${requests.length}` }],
      geodata_results: [],
      geodata_layers: [],
      execution_plan: plan,
    };
    const events = plan?.status === "pending"
      ? `event: plan_created\ndata: ${JSON.stringify(plan)}\n\n`
      : "";
    await route.fulfill({
      contentType: "text/event-stream",
      body: events + `event: result\ndata: ${JSON.stringify(result)}\n\n` +
        'event: done\ndata: {"status":"complete"}\n\n',
    });
  });
  await page.goto("/map");
  const toggle = page.getByRole("checkbox", { name: "计划模式", exact: true });
  const input = page.locator("textarea");
  async function send(query: string, reply: number) {
    await input.fill(query);
    await input.press("Enter");
    await expect(page.getByText(`Reply ${reply}`, { exact: true })).toBeVisible();
    await expect(input).toBeEnabled();
  }

  await toggle.uncheck();
  await send("First ordinary question", 1);
  await send("Second ordinary question", 2);
  await toggle.check();
  await send("First planned task", 3);
  await page.getByRole("button", { name: "展开执行流程", exact: true }).click();
  await expect(page.getByText("Plan: First planned task", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "执行计划", exact: true }).click();
  await expect(page.getByText("Reply 4", { exact: true })).toBeVisible();
  await expect(input).toBeEnabled();
  await toggle.uncheck();
  await send("Another ordinary question", 5);
  await toggle.check();
  await send("Second planned task", 6);
  await page.getByRole("button", { name: "展开执行流程", exact: true }).click();
  await expect(page.getByText("Plan: Second planned task", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByText("Reply 7", { exact: true })).toBeVisible();

  expect(requests.map((request) => request.options.model_settings.plan_mode))
    .toEqual([false, false, true, true, false, true, true]);
  expect(requests[2].execution_plan).toBeUndefined();
  expect(requests[3].execution_plan.status).toBe("confirmed");
  expect(requests[4].execution_plan).toBeUndefined();
  expect(requests[5].execution_plan).toBeUndefined();
  expect(requests[5].messages.some((message: any) => message.content === "确认")).toBe(true);
  expect(requests[6].execution_plan.status).toBe("cancelled");
});
