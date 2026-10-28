import { test, expect } from "@playwright/test";

const mockSettings = {
  system_prompt: "You are a helpful geospatial assistant.",
  tool_options: {
    search: {
      default_prompt: "Search prompt",
      settings: {},
    },
  },
  example_geoserver_backends: [],
  model_options: {
    MockProvider: [{ name: "mock-model", max_tokens: 999 }],
  },
  color_settings: {
    primary: { shade_50: "#FFFFFF", shade_900: "#000000", shade_950: "#000000" },
    second_primary: { shade_50: "#FFFFFF", shade_900: "#000000", shade_950: "#000000" },
    secondary: { shade_50: "#FFFFFF", shade_900: "#000000", shade_950: "#000000" },
    tertiary: { shade_50: "#FFFFFF", shade_900: "#000000", shade_950: "#000000" },
    danger: { shade_50: "#FFFFFF", shade_900: "#000000", shade_950: "#000000" },
    warning: { shade_50: "#FFFFFF", shade_900: "#000000", shade_950: "#000000" },
    info: { shade_50: "#FFFFFF", shade_900: "#000000", shade_950: "#000000" },
    neutral: { shade_50: "#FFFFFF", shade_900: "#000000", shade_950: "#000000" },
    corporate_1: { shade_50: "#FFFFFF", shade_900: "#000000", shade_950: "#000000" },
    corporate_2: { shade_50: "#FFFFFF", shade_900: "#000000", shade_950: "#000000" },
    corporate_3: { shade_50: "#FFFFFF", shade_900: "#000000", shade_950: "#000000" },
  },
  session_id: "test-session-123",
};

test.describe("Agent Settings Component", () => {
  test("renders Agent Settings section", async ({ page }) => {
    // Mock the settings endpoint
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Wait for Settings heading to be visible (中文：设置)
    await expect(
      page.getByRole("heading", { level: 1, name: "设置" }),
    ).toBeVisible();

    // Find the Agent Settings button (中文：智能体设置)
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await expect(agentSettingsButton).toBeVisible();
  });

  test("expands and shows system prompt textarea", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Find and click the Agent Settings collapsible button
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();

    // Wait for expansion
    await page.waitForTimeout(500);

    // Check system prompt textarea is visible
    const systemPromptTextarea = page.locator('textarea[placeholder*="系统提示词"]');
    await expect(systemPromptTextarea).toBeVisible();
    await expect(systemPromptTextarea).toHaveValue("You are a helpful geospatial assistant.");
  });

  test("enables dynamic tool selection toggle", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Find the enable dynamic tools checkbox (default: on)
    const dynamicToolsCheckbox = page.locator("#enable-dynamic-tools");
    await expect(dynamicToolsCheckbox).toBeVisible();
    await expect(dynamicToolsCheckbox).toBeChecked();

    // Strategy selector is visible while enabled
    const strategySelect = page.locator('select').filter({ hasText: /保守模式|语义匹配|最小模式|全部工具/ });
    await expect(strategySelect).toBeVisible();

    // Toggle off then back on
    await dynamicToolsCheckbox.click();
    await expect(dynamicToolsCheckbox).not.toBeChecked();
    await dynamicToolsCheckbox.click();
    await expect(dynamicToolsCheckbox).toBeChecked();
  });

  test("shows tool selection strategy dropdown when enabled", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Dynamic tools default on — strategy controls should already be visible
    const dynamicToolsCheckbox = page.locator("#enable-dynamic-tools");
    await expect(dynamicToolsCheckbox).toBeChecked();

    // Check strategy select is visible
    const strategySelect = page.locator("label:has-text('工具选择策略')").locator("..").locator("select");
    await expect(strategySelect).toBeVisible();
    
    // Check default value is "conservative"
    await expect(strategySelect).toHaveValue("conservative");

    // Test changing strategy
    await strategySelect.selectOption("semantic");
    await expect(strategySelect).toHaveValue("semantic");

    await strategySelect.selectOption("minimal");
    await expect(strategySelect).toHaveValue("minimal");

    await strategySelect.selectOption("all");
    await expect(strategySelect).toHaveValue("all");
  });

  test("adjusts tool similarity threshold slider", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Dynamic tools default on — threshold slider should already be visible
    const dynamicToolsCheckbox = page.locator("#enable-dynamic-tools");
    await expect(dynamicToolsCheckbox).toBeChecked();

    // Find the threshold slider
    const thresholdSlider = page.locator('input[type="range"]');
    await expect(thresholdSlider).toBeVisible();

    // Check default value (0.3)
    await expect(thresholdSlider).toHaveValue("0.3");

    // Adjust slider
    await thresholdSlider.fill("0.5");
    await expect(thresholdSlider).toHaveValue("0.5");

    // Verify label updates
    const thresholdLabel = page.locator("label:has-text('工具相似度阈值')");
    await expect(thresholdLabel).toContainText("0.50");
  });

  test("sets max tools per query input", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Dynamic tools default on — max tools input should already be visible
    const dynamicToolsCheckbox = page.locator("#enable-dynamic-tools");
    await expect(dynamicToolsCheckbox).toBeChecked();

    // Find max tools input
    const maxToolsInput = page.locator('input[type="number"]');
    await expect(maxToolsInput).toBeVisible();

    // Default value is empty (null = unlimited)
    await expect(maxToolsInput).toHaveValue("");

    // Change value
    await maxToolsInput.fill("15");
    await expect(maxToolsInput).toHaveValue("15");
  });

  test("hides dynamic tool settings when toggle is off", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Default on — settings visible without enabling
    const dynamicToolsCheckbox = page.locator("#enable-dynamic-tools");
    await expect(dynamicToolsCheckbox).toBeChecked();

    // Verify settings are visible
    const strategyLabel = page.locator("label:has-text('工具选择策略')");
    await expect(strategyLabel).toBeVisible();

    // Disable dynamic tools
    await dynamicToolsCheckbox.click();
    await page.waitForTimeout(500);

    // Verify settings are hidden
    await expect(strategyLabel).not.toBeVisible();
  });

  test("shows information banner when dynamic tools enabled", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Default on — info banner should already be visible
    const dynamicToolsCheckbox = page.locator("#enable-dynamic-tools");
    await expect(dynamicToolsCheckbox).toBeChecked();

    // Check for information banner
    const infoBanner = page.locator("text=动态工具选择的收益：");
    await expect(infoBanner).toBeVisible();
  });

  test("displays all strategy descriptions", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Default on — strategy select should already be visible
    const dynamicToolsCheckbox = page.locator("#enable-dynamic-tools");
    await expect(dynamicToolsCheckbox).toBeChecked();

    // Get the strategy select
    const strategySelect = page.locator("label:has-text('工具选择策略')").locator("..").locator("select");

    // Test each strategy and verify its description appears
    const strategies = [
      { value: "conservative", text: "平衡选择常用工具" },
      { value: "semantic", text: "根据查询相似度选择工具" },
      { value: "minimal", text: "只提供与查询最相关的工具" },
      { value: "all", text: "提供所有可用工具（默认行为）" },
    ];

    for (const strategy of strategies) {
      await strategySelect.selectOption(strategy.value);
      const description = page.locator(`text=${strategy.text}`);
      await expect(description).toBeVisible();
    }
  });

  test("allows editing system prompt", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Find and click the Agent Settings collapsible button
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.click();

    // Wait for expansion
    await page.waitForTimeout(500);

    // Edit system prompt
    const systemPromptTextarea = page.locator('textarea[placeholder*="系统提示词"]');
    await systemPromptTextarea.fill("New custom prompt");
    await expect(systemPromptTextarea).toHaveValue("New custom prompt");
  });

  test("displays conversation summarization checkbox", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Find the conversation summarization checkbox
    const summarizationCheckbox = page.locator("#enable-summarization");
    await expect(summarizationCheckbox).toBeVisible();
    
    // Check label text
    const label = page.locator("label[for='enable-summarization']");
    await expect(label).toContainText("启用对话摘要");
  });

  test("enables conversation summarization toggle", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Find and check the conversation summarization checkbox
    const summarizationCheckbox = page.locator("#enable-summarization");
    await expect(summarizationCheckbox).not.toBeChecked();
    
    // Enable it
    await summarizationCheckbox.click();
    await page.waitForTimeout(300);
    
    // Verify it's checked
    await expect(summarizationCheckbox).toBeChecked();
  });

  test("disables conversation summarization toggle", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Enable then disable
    const summarizationCheckbox = page.locator("#enable-summarization");
    await summarizationCheckbox.click();
    await page.waitForTimeout(300);
    await expect(summarizationCheckbox).toBeChecked();
    
    await summarizationCheckbox.click();
    await page.waitForTimeout(300);
    await expect(summarizationCheckbox).not.toBeChecked();
  });

  test("shows conversation summarization description and benefits", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Check description text
    const description = page.locator("text=在长对话中自动压缩较早消息");
    await expect(description).toBeVisible();
    
    // Check benefits section
    const benefits = page.locator("text=收益：");
    await expect(benefits).toBeVisible();
    
    // Check specific benefits mentioned
    const tokenReduction = page.locator("text=可降低 50-80% 的令牌成本");
    await expect(tokenReduction).toBeVisible();
  });

  test("conversation summarization and dynamic tools can be enabled independently", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    const dynamicToolsCheckbox = page.locator("#enable-dynamic-tools");
    const summarizationCheckbox = page.locator("#enable-summarization");

    // Dynamic tools default on; summarization still off
    await expect(dynamicToolsCheckbox).toBeChecked();
    await expect(summarizationCheckbox).not.toBeChecked();

    // Enable summarization — dynamic tools stay on
    await summarizationCheckbox.click();
    await page.waitForTimeout(300);
    await expect(summarizationCheckbox).toBeChecked();
    await expect(dynamicToolsCheckbox).toBeChecked();

    // Disable dynamic tools independently
    await dynamicToolsCheckbox.click();
    await page.waitForTimeout(300);
    await expect(dynamicToolsCheckbox).not.toBeChecked();
    await expect(summarizationCheckbox).toBeChecked();

    // Re-enable dynamic tools, then disable summarization
    await dynamicToolsCheckbox.click();
    await summarizationCheckbox.click();
    await page.waitForTimeout(300);
    await expect(summarizationCheckbox).not.toBeChecked();
    await expect(dynamicToolsCheckbox).toBeChecked();
  });

  test("displays memory settings components", async ({ page }) => {
    await page.route("**/settings/options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockSettings),
      });
    });

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Expand Agent Settings
    const agentSettingsButton = page.locator("button:has-text('智能体设置')");
    await agentSettingsButton.scrollIntoViewIfNeeded();
    await agentSettingsButton.click();
    await page.waitForTimeout(500);

    // Find the memory section heading
    const memoryHeading = page.locator("h3:has-text('记忆与上下文设置')");
    await expect(memoryHeading).toBeVisible();

    // Find the overall memory checkbox
    const memoryCheckbox = page.locator("#enable-memory");
    await expect(memoryCheckbox).toBeVisible();
    await expect(memoryCheckbox).toBeChecked(); // defaults to true

    // Find sub-toggles
    const shortTermCheckbox = page.locator("#enable-short-term-memory");
    await expect(shortTermCheckbox).toBeVisible();
    await expect(shortTermCheckbox).toBeChecked(); // defaults to true

    const longTermCheckbox = page.locator("#enable-long-term-memory");
    await expect(longTermCheckbox).toBeVisible();
    await expect(longTermCheckbox).not.toBeChecked(); // defaults to false

    // Disable overall memory context and verify sub-toggles disappear
    await memoryCheckbox.click();
    await page.waitForTimeout(300);
    await expect(memoryCheckbox).not.toBeChecked();
    await expect(shortTermCheckbox).not.toBeVisible();
    await expect(longTermCheckbox).not.toBeVisible();

    // Enable overall memory context and verify sub-toggles reappear
    await memoryCheckbox.click();
    await page.waitForTimeout(300);
    await expect(memoryCheckbox).toBeChecked();
    await expect(shortTermCheckbox).toBeVisible();
    await expect(longTermCheckbox).toBeVisible();

    // Toggle long-term memory
    await longTermCheckbox.click();
    await page.waitForTimeout(300);
    await expect(longTermCheckbox).toBeChecked();
  });
});
