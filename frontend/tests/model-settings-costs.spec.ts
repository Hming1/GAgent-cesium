import { test, expect } from "@playwright/test";

const mockSettingsWithModelCosts = {
  system_prompt: "You are a helpful assistant.",
  tool_options: {
    search: {
      default_prompt: "Search prompt",
      settings: {},
    },
  },
  example_geoserver_backends: [],
  example_mcp_servers: [],
  model_options: {
    openai: [
      {
        name: "gpt-5-mini",
        max_tokens: 100000,
        input_cost_per_million: 0.25,
        output_cost_per_million: 0.025,
        cache_cost_per_million: 2.0,
        description: "GPT-5 Mini - Balanced performance and cost",
        supports_tools: true,
        tool_calling_quality: "excellent",
        supports_vision: true,
      },
      {
        name: "gpt-5-nano",
        max_tokens: 50000,
        input_cost_per_million: 0.05,
        output_cost_per_million: 0.005,
        cache_cost_per_million: 0.4,
        description: "GPT-5 Nano - Fast and efficient for simple tasks",
        supports_tools: true,
        tool_calling_quality: "excellent",
        supports_vision: false,
      },
    ],
    google: [
      {
        name: "gemini-1.5-flash",
        max_tokens: 8192,
        input_cost_per_million: 0.075,
        output_cost_per_million: 0.3,
        cache_cost_per_million: 0.01875,
        description: "Gemini 1.5 Flash - Fast and efficient model",
        supports_tools: true,
        tool_calling_quality: "excellent",
        supports_vision: true,
      },
    ],
  },
  session_id: "test-session-123",
};

test.describe("Model settings with cost display", () => {
  test.beforeEach(async ({ page }) => {
  await page.route("**/auth/me", route => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ id: "test-user", email: "test@example.com" }),
  }));
  });
  test("displays model cost information", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettingsWithModelCosts),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand 模型设置 component
    const modelSettingsButton = page.locator("button:has-text('模型设置')");
    await modelSettingsButton.scrollIntoViewIfNeeded();
    await expect(modelSettingsButton).toBeVisible();
    await modelSettingsButton.click();

    // Wait for expansion
    await page.waitForTimeout(500);

    // Check that provider is set to openai
    const providerSelect = page.locator("label:has-text('服务提供商')").locator("..").locator("select");
    await expect(providerSelect).toBeVisible({ timeout: 5000 });
    await expect(providerSelect).toHaveValue("openai");

    // Check that model is selected
    const modelSelect = page.locator("label:text-is('模型')").locator("..").locator("select");
    await expect(modelSelect).toBeVisible();
    await expect(modelSelect).toHaveValue("gpt-5-mini");

    // Check that model cost information is displayed
    await expect(page.locator('text=/输入：.*\\$0\\.25\\/M/')).toBeVisible();
    await expect(page.locator('text=/输出：.*\\$0\\.03\\/M/')).toBeVisible();
    await expect(page.locator('text=/缓存：.*\\$2\\.00\\/M/')).toBeVisible();

    // Check that description is displayed
    await expect(page.locator("text=GPT-5 Mini - Balanced performance and cost")).toBeVisible();

    // Check that capabilities are shown (now as badges)
    await expect(page.getByText("Excellent 工具", { exact: true })).toBeVisible();
    await expect(page.locator("text=视觉")).toBeVisible();
  });

  test("updates cost display when model changes", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettingsWithModelCosts),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand 模型设置
    const modelSettingsButton = page.locator("button:has-text('模型设置')");
    await modelSettingsButton.click();
    await page.waitForTimeout(500);

    // Change to gpt-5-nano
    const modelSelect = page.locator("label:text-is('模型')").locator("..").locator("select");
    await modelSelect.selectOption("gpt-5-nano");

    // Wait for UI to update
    await page.waitForTimeout(200);

    // Check that costs updated for nano model
    await expect(page.locator('text=/输入：.*\\$0\\.05\\/M/')).toBeVisible();
    await expect(page.locator('text=/输出：.*\\$0\\.01\\/M/')).toBeVisible();
    await expect(page.locator('text=/缓存：.*\\$0\\.40\\/M/')).toBeVisible();

    // Check description updated
    await expect(page.locator("text=GPT-5 Nano - Fast and efficient for simple tasks")).toBeVisible();

    // Vision should not be shown for nano
    const visionMarkers = await page.locator("text=视觉").count();
    expect(visionMarkers).toBe(0);
  });

  test("updates cost display when provider changes", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettingsWithModelCosts),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand 模型设置
    const modelSettingsButton = page.locator("button:has-text('模型设置')");
    await modelSettingsButton.click();
    await page.waitForTimeout(500);

    // Change provider to Google
    const providerSelect = page.locator("label:has-text('服务提供商')").locator("..").locator("select");
    await providerSelect.selectOption("google");

    // Wait for UI to update
    await page.waitForTimeout(1000);

    // Check that model changed to gemini-1.5-flash
    const modelSelect = page.locator("label:text-is('模型')").locator("..").locator("select");
    await expect(modelSelect).toHaveValue("gemini-1.5-flash");

    // Check Google model costs
    await expect(page.locator('text=/输入：.*\\$0\\.07\\/M/')).toBeVisible();
    await expect(page.locator('text=/输出：.*\\$0\\.30\\/M/')).toBeVisible();

    // Check description
    await expect(page.locator("text=Gemini 1.5 Flash - Fast and efficient model")).toBeVisible();
  });

  test("displays model without costs correctly", async ({ page }) => {
    const settingsWithNoCosts = {
      ...mockSettingsWithModelCosts,
      model_options: {
        vllm: [
          {
            name: "test-deployment",
            max_tokens: 6000,
            input_cost_per_million: null,
            output_cost_per_million: null,
            cache_cost_per_million: null,
            description: "vLLM deployment: test-deployment",
            supports_tools: true,
        tool_calling_quality: "excellent",
            supports_vision: false,
          },
        ],
      },
    };

    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(settingsWithNoCosts),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand 模型设置
    const modelSettingsButton = page.locator("button:has-text('模型设置')");
    await modelSettingsButton.click();
    await page.waitForTimeout(500);

    // Should still show description even without costs
    await expect(page.locator("text=vLLM deployment: test-deployment")).toBeVisible();

    // Cost fields should not be visible when null
    const inputCostVisible = await page.getByText("输入：", { exact: true }).count();
    expect(inputCostVisible).toBe(0);
  });
});
