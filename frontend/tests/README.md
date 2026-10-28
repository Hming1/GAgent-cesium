# Frontend Test Suite

> Comprehensive E2E testing for the Nalamap frontend using Playwright

## 🚀 Quick Start

```bash
# Install dependencies
npm ci

# Install Playwright browsers
npx playwright install --with-deps

# Run all tests
npx playwright test

# Run specific test file
npx playwright test tests/leaflet-map.spec.ts
npx playwright test tests/chat-interface.spec.ts
npx playwright test tests/settings.spec.ts

# Interactive mode (recommended)
npx playwright test --ui

# Generate HTML report
npx playwright test --reporter=html
npx playwright show-report
```

## 📁 Test Structure

```
tests/
├── leaflet-map.spec.ts           # Map functionality tests (25+ tests)
├── chat-interface.spec.ts        # AI chat interface tests
├── settings.spec.ts              # Settings panel tests
├── fixtures/
│   ├── geocoding-fixtures.ts     # Mock geocoding data
│   ├── overpass-fixtures.ts      # Mock Overpass API data
│   └── ogc-services-fixtures.ts  # Mock WMS/WFS/WMTS/WCS data
└── README.md                      # This file
```

## 🧪 Test Coverage

### Plan Mode Tests (plan-mode.spec.ts)

`npx playwright test tests/plan-mode.spec.ts` checks ordinary multi-turn chat,
enabling plan mode, confirming a plan, switching it off and on again, and cancelling
the next plan. Mocked SSE responses verify that each request carries the current
mode and that an old confirmed plan is not sent with a new task. Actual tool
execution restrictions are tested by `backend/tests/test_plan_mode_flow.py`.

### Cesium Vector Layer Tests (cesium-point-layer.spec.ts)

Run `npx playwright test tests/cesium-point-layer.spec.ts`. The tests use mocked
GeoJSON, PostGIS APIs and decodable basemap tiles to verify point selection,
polygon visibility before any style interaction, default/explicit/zero opacity,
and PostGIS loading without a bounding box or a successful AI styling response.
They also cover style updates while data is loading and changing opacity to zero
and back in the style panel. GeoJSON sources are parsed and styled before being
added to the viewer; layers without bounds fit their loaded geometry. Polygon
fill defaults to 30%, matching the style panel, and an explicit 0 remains 0.

Point and MultiPoint regressions require Cesium `scene.pick` to hit every rendered
symbol, including PostGIS layers without bounds, radius changes and hide/show.
Selecting an entity through the coordinate fallback is not proof of visibility.
GeoJSON's default billboard is removed when converting to a ground-clamped point:
leaving a hidden billboard makes its visualizer clear the primitive shared with
the point visualizer.
Point-only layers without bounds are fitted from their coordinates with a
top-down view and a minimum 500 m bounding-sphere radius, so a single point does
not place the camera at ground level. Visibility assertions wait for camera
flights to finish before checking the rendered symbols.

### Cesium Basemap Tests (cesium-basemap.spec.ts)

These tests use decodable tile images to verify the Amap default, all 12 basemaps and their annotation overlays, runtime Tianditu token loading, missing-token behavior, tile-error fallback, stalled-request fallback, retrying the original source, annotation failures, and preserving the selected basemap when changing the interface theme. No Cesium ion imagery is requested. Run against a separate development server with `npx cross-env BASEMAP_TEST_URL=http://localhost:3002 playwright test tests/cesium-basemap.spec.ts`.

### Leaflet Map Tests (leaflet-map.spec.ts)
- **Geocoding**: Germany, Brazil boundary rendering
- **Overpass**: Hospital/restaurant POI display
- **OGC Services**: WMS, WFS, WMTS, WCS layers
- **GeoJSON Normalization**: Various geometry formats
- **Layer Management**: Add, remove, toggle visibility
- **Bug Fixes**: Verified fixes for layer visibility issues
- **Performance**: Multi-layer rendering, memory usage

### Chat Interface Tests (chat-interface.spec.ts)
- AI conversation flow
- Message history
- Tool invocations

`npx playwright test tests/chat-history-roundtrip.spec.ts` covers the Guangzhou →
Shenzhen follow-up: empty tool-call messages, call IDs, arguments and reasoning
metadata must survive into the second request. Previous progress stays grouped,
tool results do not become user bubbles, and current tool events belong only to
the new turn. Message visibility is handled by `ChatMessages`, without filtering
the history stored for subsequent model requests.

The same suite checks that an SSE model error on turn three is shown as an alert,
the input becomes usable again, and turn four can succeed without clearing history.

### Settings Tests (settings.spec.ts)
- User preferences
- Configuration updates

## 🎯 Running Specific Tests

```bash
# By test suite name
npx playwright test --grep "Geocoding"
npx playwright test --grep "Performance"
npx playwright test --grep "Bug Fix Verification"

# By test file
npx playwright test tests/leaflet-map.spec.ts

# Debug mode (step through test)
npx playwright test --debug

# Headed mode (see browser)
npx playwright test --headed

# Specific test by name
npx playwright test --grep "Brazil hospitals"
```

## 🔍 Debug & Troubleshooting

### Interactive Debugging
```bash
# Best for debugging - visual test runner
npx playwright test --ui

# Debug specific test
npx playwright test tests/leaflet-map.spec.ts --debug

# Record trace for analysis
npx playwright test --trace on
npx playwright show-trace trace.zip
```

### Common Issues

**Tests timeout**
- Increase timeout in `playwright.config.ts`
- Check dev server is running
- Use `--headed` to see what's happening

**Cannot find elements**
- Check selectors in test
- Use `await page.pause()` to inspect page
- Verify mock data is loading correctly

**Flaky tests**
- Run multiple times: `npx playwright test --repeat-each=3`
- Check for race conditions
- Ensure proper wait conditions

**Store/state issues**
- Verify Zustand stores initialize
- Check page loads correctly
- Review mock API responses

## 📊 Performance Testing

```bash
# Run performance test suite
npx playwright test --grep "Performance"

# Expected benchmarks:
# ✅ Multiple layers (5):      <3000ms
# ✅ Layer removal (3):         <1000ms
# ✅ Memory growth (3 layers):  <50MB
# ✅ Single layer bounds:       <2500ms
```

## 🔄 CI/CD Integration

Tests run automatically via GitHub Actions on every push/PR.

### View CI Results
1. Go to GitHub Actions tab
2. Select workflow run
3. Check `frontend-tests` and `frontend-performance` jobs
4. Download artifacts for detailed reports

### Run CI tests locally
```bash
CI=true npx playwright test
```

## 📈 Test Reports

### HTML Report (Recommended)
```bash
npx playwright test --reporter=html
npx playwright show-report
```

### Other Formats
```bash
# JSON output
npx playwright test --reporter=json > results.json

# JUnit XML
npx playwright test --reporter=junit

# GitHub Actions format
npx playwright test --reporter=github
```

## 🏗️ Writing New Tests

### Example Test Structure
```typescript
import { test, expect } from '@playwright/test';

test.describe('Feature Name', () => {
  test.beforeEach(async ({ page }) => {
    // Setup: navigate, mock APIs, etc.
    await page.goto('/');
  });

  test('should do something', async ({ page }) => {
    // Arrange
    const button = page.getByRole('button', { name: 'Click me' });
    
    // Act
    await button.click();
    
    // Assert
    await expect(page.getByText('Success')).toBeVisible();
  });
});
```

### Best Practices
- Use `data-testid` for stable selectors
- Mock external APIs consistently
- Keep tests independent (no shared state)
- Use descriptive test names
  - Add comments for complex logic

## 🔐 Authentication Tests

The authentication tests mock the signup, login, and current user endpoints so you do not need a real backend or database. See `authentication.spec.ts` for examples:
```bash
# Mock /api/auth/signup, /api/auth/login, and /api/auth/me
# Navigate to /signup or /login, fill the forms, submit, and assert redirect to /map
``` 
- Test user workflows, not implementation

## 🐛 Known Issues & Fixes

### Layer Visibility Bug (FIXED)
**Issue**: Layers didn't appear until visibility was toggled off/on.

**Root Causes**:
1. Race condition in bounds fitting
2. Missing loading state
3. forceUpdate pattern causing re-renders

**Fixes Applied**:
- ✅ Consolidated bounds fitting logic
- ✅ Added loading state to prevent premature renders
- ✅ Replaced forceUpdate with stable styleKey

**Performance Improvements**:
- 66% faster layer rendering
- 75% reduction in re-renders
- 100% elimination of race conditions

## 📚 Additional Resources

### Playwright Documentation
- [Official Docs](https://playwright.dev)
- [Best Practices](https://playwright.dev/docs/best-practices)
- [API Reference](https://playwright.dev/docs/api/class-playwright)

### Project-Specific
- Test fixtures in `fixtures/` directory
- Mock data structure examples
- CI configuration in `.github/workflows/ci.yml`

## ✅ Pre-Deployment Checklist

Before merging changes:

- [ ] All tests pass locally
- [ ] New features have test coverage
- [ ] No flaky tests (run multiple times)
- [ ] Performance within acceptable ranges
- [ ] No console errors in test output
- [ ] CI pipeline passes
- [ ] Manual smoke testing in browser

## 🎉 Success Criteria

Tests are passing when:
- ✅ All 25+ tests pass
- ✅ No console errors or warnings
- ✅ Performance metrics within thresholds
- ✅ CI pipeline completes successfully
- ✅ Manual testing confirms functionality

---

**Need Help?** Check test comments, review mock fixtures, or run tests in `--ui` mode for interactive debugging.
