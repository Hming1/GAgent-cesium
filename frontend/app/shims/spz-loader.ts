/**
 * Browser-safe replacement for Cesium's optional SPZ Gaussian-splat decoder.
 *
 * The upstream decoder embeds a WebAssembly binary in a template literal,
 * which Next/Webpack currently emits as invalid client-side JavaScript. This
 * app does not load SPZ Gaussian-splat assets; fail explicitly if one is used
 * rather than preventing all Cesium maps from loading.
 */
export async function loadSpz(): Promise<never> {
  throw new Error(
    "SPZ Gaussian-splat data is not supported in this Next.js build. " +
      "Use a standard Cesium-compatible tileset instead.",
  );
}
