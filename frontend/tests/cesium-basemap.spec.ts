import { expect, test, type Page } from "@playwright/test";

test.use({ baseURL: process.env.BASEMAP_TEST_URL ?? "http://localhost:3000" });

const tilePattern =
  /^https:\/\/(?:[^/]+\.(?:basemaps\.cartocdn\.com|tile\.openstreetmap\.org|is\.autonavi\.com|tianditu\.gov\.cn)|mt1\.google\.com)\//;

async function prepareMap(page: Page, token = "test-browser-token") {
  const requestedUrls: string[] = [];
  // Generate a real decodable image: invalid PNG fixtures can make Cesium
  // fail every provider even when HTTP requests succeed.
  const dataUrl = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 256;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#7fa878";
    context.fillRect(0, 0, 256, 256);
    return canvas.toDataURL("image/png");
  });
  const png = Buffer.from(dataUrl.split(",")[1], "base64");
  await page.route("**/auth/me", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ id: "playwright-user", email: "playwright@example.com", display_name: "Playwright User" }),
    }),
  );
  await page.route(tilePattern, (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: png }),
  );
  await page.route("**/runtime-env.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: "window.__RUNTIME_CONFIG__ = " + JSON.stringify({
        NEXT_PUBLIC_API_BASE_URL: "/api",
        NEXT_PUBLIC_TIANDITU_TOKEN: token,
      }) + ";",
    }),
  );
  page.on("request", (request) => requestedUrls.push(request.url()));
  return requestedUrls;
}

test("Tianditu is the default when a token is present and all 12 basemaps request their complete tile layers", async ({ page }) => {
  const requestedUrls = await prepareMap(page);
  await page.goto("/map");
  await page.waitForSelector(".cesium-widget");
  const select = page.getByTestId("basemap-select");
  await expect(select).toHaveValue("tianditu-vector");
  await expect.poll(() => requestedUrls.some((url) => url.includes("T=vec_w"))).toBe(true);
  const sources: [string, string[]][] = [
    ["osm", ["tile.openstreetmap.org"]],
    ["carto-positron", ["/light_all/"]],
    ["carto-dark", ["/dark_all/"]],
    ["google-satellite", ["lyrs=s"]],
    ["google-hybrid", ["lyrs=y"]],
    ["google-terrain", ["lyrs=p"]],
    ["amap-satellite", ["style=6"]],
    ["amap-hybrid", ["style=6", "style=8"]],
    ["amap-standard", ["wprd"]],
    ["tianditu-satellite", ["T=img_w"]],
    ["tianditu-hybrid", ["T=img_w", "T=cia_w"]],
    ["tianditu-vector", ["T=vec_w", "T=cva_w"]],
  ];
  for (const [key, layers] of sources) {
    const from = requestedUrls.length;
    await select.selectOption(key);
    for (const layer of layers) {
      await expect.poll(() => requestedUrls.slice(from).some((url) => url.includes(layer))).toBe(true);
    }
  }
  const tianditu = requestedUrls.filter((url) => url.includes("tianditu.gov.cn"));
  expect(tianditu.length).toBeGreaterThan(0);
  expect(tianditu.every((url) => new URL(url).searchParams.get("tk") === "test-browser-token")).toBe(true);
  expect(tianditu.every((url) => Number(new URL(url).searchParams.get("l")) >= 1)).toBe(true);
  expect(requestedUrls.some((url) => new URL(url).hostname === "api.cesium.com")).toBe(false);
  await expect(page.getByTestId("basemap-notice")).toHaveCount(0);
});

test("missing runtime token disables Tianditu without using a build-time token", async ({ page }) => {
  await prepareMap(page, "");
  await page.goto("/map");
  await expect(page.getByTestId("basemap-select")).toHaveValue("amap-standard");
  await expect(page.locator('option[value="tianditu-vector"]')).toBeDisabled();
});

test("failed tiles switch to a labelled fallback and allow retrying the original basemap", async ({ page }) => {
  const requestedUrls = await prepareMap(page);
  let failing = true;
  await page.route(/https:\/\/t\d+\.tianditu\.gov\.cn\//, (route) =>
    failing ? route.abort("connectionfailed") : route.fallback(),
  );
  await page.goto("/map");
  await expect(page.getByTestId("basemap-select")).toHaveValue("carto-positron", { timeout: 20000 });
  await expect(page.getByTestId("basemap-notice")).toContainText("天地图矢量地图");
  await expect(page.getByTestId("basemap-notice")).toContainText("Carto 浅色底图");
  await expect.poll(() => requestedUrls.some((url) => url.includes("/light_all/"))).toBe(true);
  failing = false;
  const from = requestedUrls.length;
  await page.getByRole("button", { name: "重试原底图" }).click();
  await expect(page.getByTestId("basemap-select")).toHaveValue("tianditu-vector");
  await expect.poll(() => requestedUrls.slice(from).some((url) => url.includes("T=vec_w"))).toBe(true);
  await expect(page.getByTestId("basemap-notice")).toHaveCount(0);
});

test("stalled tile requests fall back instead of leaving an empty globe", async ({ page }) => {
  await prepareMap(page);
  let release: () => void = () => {};
  const stalled = new Promise<void>((resolve) => { release = resolve; });
  await page.route(/https:\/\/t\d+\.tianditu\.gov\.cn\//, async (route) => {
    await stalled;
    await route.abort();
  });
  try {
    await page.goto("/map");
    await expect(page.getByTestId("basemap-select")).toHaveValue("carto-positron", { timeout: 20000 });
    await expect(page.getByTestId("basemap-notice")).toBeVisible();
  } finally {
    release();
  }
});


test("annotation failure switches to a complete satellite fallback", async ({ page }) => {
  await prepareMap(page);
  await page.route(/https:\/\/webst\d+\.is\.autonavi\.com\/.*style=8/, (route) => route.abort("connectionfailed"));
  await page.goto("/map");
  await page.getByTestId("basemap-select").selectOption("amap-hybrid");
  await expect(page.getByTestId("basemap-select")).toHaveValue("google-satellite", { timeout: 20000 });
  await expect(page.getByTestId("basemap-notice")).toContainText("高德卫星混合图");
  await expect(page.getByTestId("basemap-notice")).toContainText("Google 卫星影像");
});

test("changing the interface theme preserves the selected basemap", async ({ page }) => {
  await prepareMap(page);
  await page.goto("/map");
  await page.getByTestId("basemap-select").selectOption("osm");
  await page.locator('a[href="/settings"]').click();
  await page.getByRole("button", { name: /主题偏好/ }).click();
  await page.getByRole("button", { name: /深色模式/ }).click();
  await page.locator('a[href="/map"]:visible').click();
  await expect(page.getByTestId("basemap-select")).toHaveValue("osm");
});
