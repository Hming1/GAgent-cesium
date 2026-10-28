import { expect, Page, test } from "@playwright/test";

const mockSettings = {
  system_prompt: "You are a helpful assistant.",
  available_tools: [],
  tool_options: {},
  available_example_geoservers: [],
  available_example_mcp_servers: [],
  model_options: {
    MockProvider: [{ name: "mock-model", max_tokens: 999 }],
  },
  session_id: "test-session",
};

const pointLayerGeoJSON = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [13.405, 52.52],
      },
      properties: {
        name: "Clickable Test Point",
        category: "visual-regression",
      },
    },
  ],
};

const polygonLayerGeoJSON = {
  type: "FeatureCollection",
  features: [{
    type: "Feature",
    properties: {},
    geometry: {
      type: "Polygon",
      coordinates: [[[13.38, 52.5], [13.43, 52.5], [13.43, 52.54], [13.38, 52.54], [13.38, 52.5]]],
    },
  }],
};

async function expectPolygonVisible(page: Page, layerId: string) {
  // Pick the interior to verify a rendered primitive, not just entity properties.
  await expect.poll(() => page.evaluate((id) => {
    const viewer = (window as any).__nalamapCesiumViewer;
    const entity = viewer.dataSources.getByName(id)[0]?.entities.values[0];
    if (!entity) return false;
    const positions = entity.polygon.hierarchy.getValue(viewer.clock.currentTime).positions;
    const center = positions[0].clone();
    center.x = (positions[0].x + positions[2].x) / 2;
    center.y = (positions[0].y + positions[2].y) / 2;
    center.z = (positions[0].z + positions[2].z) / 2;
    const point = viewer.scene.cartesianToCanvasCoordinates(center);
    const canvas = viewer.scene.canvas;
    return Boolean(point && point.x >= 0 && point.y >= 0 &&
      point.x < canvas.clientWidth && point.y < canvas.clientHeight &&
      viewer.scene.pick(point)?.id === entity);
  }, layerId), { timeout: 15000 }).toBe(true);
}

async function expectPointsVisible(page: Page, layerId: string, count: number) {
  // Require real rendered symbols. Coordinate-based click fallback can select
  // an invisible point, so opening the details panel alone is insufficient.
  await expect.poll(() => page.evaluate(({ id, expectedCount }) => {
    const viewer = (window as any).__nalamapCesiumViewer;
    if (viewer.scene.tweens.length > 0) return false;
    const entities = viewer.dataSources.getByName(id)[0]?.entities.values;
    if (entities?.length !== expectedCount) return false;
    const canvas = viewer.scene.canvas;
    return entities.every((entity: any) => {
      const position = entity.position?.getValue(viewer.clock.currentTime);
      if (!position) return false;
      const point = viewer.scene.cartesianToCanvasCoordinates(position);
      return Boolean(point && point.x >= 0 && point.y >= 0 &&
        point.x < canvas.clientWidth && point.y < canvas.clientHeight &&
        viewer.scene.pick(point)?.id === entity);
    });
  }, { id: layerId, expectedCount: count }), { timeout: 15000 }).toBe(true);
}

async function setupCesiumTestMocks(page: Page) {
  await page.route("**/layers/created-layer", (route) => route.fulfill({ json: {} }));
  const tile = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 256;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#7fa878";
    context.fillRect(0, 0, 256, 256);
    return canvas.toDataURL("image/png").split(",")[1];
  });
  await page.route(/^https:\/\/(?:[^/]+\.(?:basemaps\.cartocdn\.com|tile\.openstreetmap\.org|is\.autonavi\.com|tianditu\.gov\.cn)|mt1\.google\.com)\//,
    (route) => route.fulfill({ contentType: "image/png", body: Buffer.from(tile, "base64") }));
  await page.route("**/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "test-user",
        email: "test@example.com",
      }),
    });
  });

  await page.route("**/settings/options", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockSettings),
    });
  });

  await page.route("**/maps/", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "test-map",
          name: "Test Map",
          description: "Default test map",
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "test-map",
          name: "Test Map",
          description: "Default test map",
        },
      ]),
    });
  });

  await page.route("**/maps/test-map/layers", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.route("**/layers/", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "created-layer",
        data_link: "/test-point-layer.geojson",
        data_type: "geojson",
        name: "Cesium Point Test",
        description: null,
        derived: false,
        payload: {},
      }),
    });
  });

  await page.route("**/test-point-layer.geojson", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/geo+json",
      body: JSON.stringify(pointLayerGeoJSON),
    });
  });
}

test.describe("Cesium point layers", () => {
  test("renders point layers with visible defaults and opens feature details on click", async ({
    page,
  }) => {
    await setupCesiumTestMocks(page);

    await page.goto("/map");

    await expect(page.locator(".cesium-widget canvas")).toBeVisible({
      timeout: 20000,
    });

    await page.waitForFunction(
      () =>
        Boolean(
          (window as any).useLayerStore &&
            (window as any).__nalamapCesiumViewer,
        ),
      { timeout: 20000 },
    );

    await page.evaluate(() => {
      const { useLayerStore } = window as any;
      useLayerStore.getState().resetLayers();
      useLayerStore.getState().addLayer({
        id: "cesium-point-test",
        data_source_id: "test",
        data_type: "geojson",
        data_origin: "test",
        data_source: "test",
        data_link: "/test-point-layer.geojson",
        name: "Cesium Point Test",
        title: "Cesium Point Test",
        layer_type: "UPLOADED",
        bounding_box: [13.35, 52.48, 13.46, 52.56],
        visible: true,
      });
    });

    await page.waitForFunction(
      () => {
        const viewer = (window as any).__nalamapCesiumViewer;
        const dataSource = viewer?.dataSources?.getByName("cesium-point-test")?.[0];
        const entity = dataSource?.entities?.values?.[0];
        return Boolean(entity?.point);
      },
      { timeout: 20000 },
    );

    const style = await page.evaluate(() => {
      const viewer = (window as any).__nalamapCesiumViewer;
      const dataSource = viewer.dataSources.getByName("cesium-point-test")[0];
      const entity = dataSource.entities.values[0];
      const time = viewer.clock.currentTime;

      return {
        pixelSize: entity.point.pixelSize.getValue(time),
        fillAlpha: entity.point.color.getValue(time).alpha,
        outlineWidth: entity.point.outlineWidth.getValue(time),
        depthTestDistance: entity.point.disableDepthTestDistance.getValue(time),
      };
    });

    expect(style.pixelSize).toBe(10);
    expect(style.fillAlpha).toBeCloseTo(0.9, 1);
    expect(style.outlineWidth).toBe(2);
    expect(style.depthTestDistance).toBe(Number.POSITIVE_INFINITY);

    await expectPointsVisible(page, "cesium-point-test", 1);

    const canvasPoint = await page.waitForFunction(
      () => {
        const viewer = (window as any).__nalamapCesiumViewer;
        const dataSource = viewer?.dataSources?.getByName("cesium-point-test")?.[0];
        const entity = dataSource?.entities?.values?.[0];
        if (!viewer || !entity?.position) return null;

        const position = entity.position.getValue(viewer.clock.currentTime);
        const point = viewer.scene.cartesianToCanvasCoordinates(position);
        const canvas = viewer.scene.canvas;
        if (
          !point ||
          point.x < 0 ||
          point.y < 0 ||
          point.x > canvas.clientWidth ||
          point.y > canvas.clientHeight
        ) {
          return null;
        }

        return { x: point.x, y: point.y };
      },
      { timeout: 20000 },
    );

    const point = await canvasPoint.jsonValue();
    expect(point).not.toBeNull();

    await page.evaluate(({ x, y }) => {
      const canvas = document.querySelector(".cesium-widget canvas");
      if (!canvas) throw new Error("Cesium canvas not found");

      const rect = canvas.getBoundingClientRect();
      canvas.dispatchEvent(
        new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          clientX: rect.left + x,
          clientY: rect.top + y,
          view: window,
        }),
      );
    }, point!);

    await page.waitForFunction(
      () => Boolean((window as any).__nalamapCesiumViewer?.selectedEntity),
      { timeout: 5000 },
    );

    await expect(page.getByText("Clickable Test Point")).toBeVisible({
      timeout: 5000,
    });
    await expect(page.getByText("visual-regression")).toBeVisible();
  });
});

for (const geometryType of ["Point", "MultiPoint"]) {
  test(`PostGIS ${geometryType} symbols render without bounds and survive style and visibility changes`, async ({ page }) => {
    await setupCesiumTestMocks(page);
    await page.route("**/postgis/tables", (route) => route.fulfill({ json: {
      tables: [{ schema: "public", table: "test_points", geometry_column: "geom", type: geometryType.toUpperCase() }],
    } }));
    await page.route("**/postgis/layer/public/test_points?*", (route) => route.fulfill({
      json: { id: "postgis-point-test", url: "/test-postgis-points.geojson" },
    }));
    await page.route("**/test-postgis-points.geojson", (route) => route.fulfill({ json: {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        properties: { name: "PostGIS point" },
        geometry: {
          type: geometryType,
          coordinates: geometryType === "Point" ? [13.405, 52.52] : [[13.405, 52.52], [13.415, 52.53]],
        },
      }],
    } }));
    await page.route("**/ai-style", (route) => route.fulfill({ status: 503, json: {} }));
    await page.goto("/map");
    await page.waitForFunction(() => Boolean((window as any).__nalamapCesiumViewer));
    const addButton = page.getByRole("button", { name: "加至地图", exact: true });
    if (!await addButton.isVisible()) await page.getByTitle("图层管理", { exact: true }).click();
    await addButton.click();
    const count = geometryType === "Point" ? 1 : 2;
    await expectPointsVisible(page, "postgis-point-test", count);
    await page.getByTitle("设置图层样式", { exact: true }).click();
    const radiusSlider = page.locator("label").filter({ hasText: /^点半径$/ })
      .locator("..").locator('input[type="range"]');
    await radiusSlider.fill("9");
    await expectPointsVisible(page, "postgis-point-test", count);
    await page.getByTitle("切换可见性", { exact: true }).click();
    await expect.poll(() => page.evaluate(() =>
      (window as any).__nalamapCesiumViewer.dataSources.getByName("postgis-point-test").length,
    )).toBe(0);
    await page.getByTitle("切换可见性", { exact: true }).click();
    await expectPointsVisible(page, "postgis-point-test", count);
  });
}

for (const fillOpacity of [undefined, 0.3, 0]) {
  test(`polygon applies initial fill opacity ${fillOpacity ?? "default"} without a style change`, async ({ page }) => {
    await setupCesiumTestMocks(page);
    await page.route("**/test-polygon.geojson", (route) => route.fulfill({
      contentType: "application/geo+json",
      body: JSON.stringify(polygonLayerGeoJSON),
    }));
    await page.goto("/map");
    await page.waitForFunction(() => Boolean((window as any).__nalamapCesiumViewer));
    await page.evaluate((opacity) => {
      const viewer = (window as any).__nalamapCesiumViewer;
      viewer.dataSources.dataSourceAdded.addEventListener((_collection: any, source: any) => {
        if (source.name !== "polygon-default-test") return;
        (window as any).__polygonInitialState = {
          loading: source.isLoading,
          alpha: source.entities.values[0]?.polygon?.material?.getValue(viewer.clock.currentTime)?.color?.alpha,
        };
      });
      (window as any).useLayerStore.getState().addLayer({
        id: "polygon-default-test",
        name: "Polygon default test",
        data_link: "/test-polygon.geojson",
        layer_type: "UPLOADED",
        bounding_box: [13.35, 52.48, 13.46, 52.56],
        visible: true,
        ...(opacity === undefined ? {} : { style: { fill_opacity: opacity } }),
      });
    }, fillOpacity);
    await expect.poll(() => page.evaluate(() => {
      const viewer = (window as any).__nalamapCesiumViewer;
      const entity = viewer.dataSources.getByName("polygon-default-test")[0]?.entities.values[0];
      return entity?.polygon?.material?.getValue(viewer.clock.currentTime)?.color?.alpha;
    })).toBe(fillOpacity ?? 0.3);
    expect(await page.evaluate(() => (window as any).__polygonInitialState)).toEqual({
      loading: false,
      alpha: fillOpacity ?? 0.3,
    });
    if (fillOpacity !== 0) {
      await expectPolygonVisible(page, "polygon-default-test");
    }
  });
}

for (const updateWhileLoading of [false, true]) {
  test(`PostGIS polygon is visible after adding without bounds (pending style update: ${updateWhileLoading})`, async ({ page }) => {
    await setupCesiumTestMocks(page);
    const dataUrl = updateWhileLoading ? "/test-postgis-data" : "/test-postgis-data.geojson";
    await page.route("**/postgis/tables", (route) => route.fulfill({ json: {
      tables: [{ schema: "public", table: "test_polygons", geometry_column: "geom", type: "POLYGON" }],
    } }));
    await page.route("**/postgis/layer/public/test_polygons?*", (route) => route.fulfill({
      json: { id: "postgis-polygon-test", url: dataUrl },
    }));
    // Rendering must not depend on the optional AI styling service.
    await page.route("**/ai-style", (route) => route.fulfill({ status: 503, json: {} }));
    let releaseData!: () => void;
    const dataReady = new Promise<void>((resolve) => { releaseData = resolve; });
    await page.route(`**${dataUrl}`, async (route) => {
      await dataReady;
      await route.fulfill({ json: polygonLayerGeoJSON });
    });
    await page.goto("/map");
    await page.waitForFunction(() => Boolean((window as any).__nalamapCesiumViewer));
    const addButton = page.getByRole("button", { name: "加至地图", exact: true });
    if (!await addButton.isVisible()) await page.getByTitle("图层管理", { exact: true }).click();
    await Promise.all([
      page.waitForRequest(`**${dataUrl}`),
      addButton.click(),
    ]);
    if (updateWhileLoading) {
      await page.evaluate(() => {
        (window as any).useLayerStore.getState().updateLayerStyle("postgis-polygon-test", { fill_opacity: 0.7 });
      });
    }
    releaseData();
    await expectPolygonVisible(page, "postgis-polygon-test");
    await expect.poll(() => page.evaluate(() => {
      const viewer = (window as any).__nalamapCesiumViewer;
      return viewer.dataSources.getByName("postgis-polygon-test")[0]?.entities.values[0]
        ?.polygon.material.getValue(viewer.clock.currentTime).color.alpha;
    })).toBe(updateWhileLoading ? 0.7 : 0.3);

    await page.getByTitle("设置图层样式", { exact: true }).click();
    const fillSlider = page.locator("label").filter({ hasText: /^填充透明度$/ })
      .locator("..").locator('input[type="range"]');
    await expect(fillSlider).toHaveValue(updateWhileLoading ? "0.7" : "0.3");
    await fillSlider.fill("0");
    await expect(fillSlider).toHaveValue("0");
    await expect.poll(() => page.evaluate(() => {
      const viewer = (window as any).__nalamapCesiumViewer;
      return viewer.dataSources.getByName("postgis-polygon-test")[0].entities.values[0]
        .polygon.material.getValue(viewer.clock.currentTime).color.alpha;
    })).toBe(0);
    await fillSlider.fill("0.6");
    await expectPolygonVisible(page, "postgis-polygon-test");
    await page.getByTitle("切换可见性", { exact: true }).click();
    await expect.poll(() => page.evaluate(() =>
      (window as any).__nalamapCesiumViewer.dataSources.getByName("postgis-polygon-test").length,
    )).toBe(0);
    await page.getByTitle("切换可见性", { exact: true }).click();
    await expectPolygonVisible(page, "postgis-polygon-test");
    expect(await page.evaluate(() => {
      const viewer = (window as any).__nalamapCesiumViewer;
      const sources = viewer.dataSources.getByName("postgis-polygon-test");
      return { count: sources.length, alpha: sources[0].entities.values[0].polygon.material
        .getValue(viewer.clock.currentTime).color.alpha };
    })).toEqual({ count: 1, alpha: 0.6 });
  });
}
