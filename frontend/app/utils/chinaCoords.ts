/**
 * China GCJ-02 (Amap/Tencent) ↔ WGS84 helpers.
 * Tianditu / OSM / Cesium use WGS84 (CGCS2000 ≈ WGS84).
 * Amap basemap tiles and Amap Web Service POIs use GCJ-02.
 */

function outOfChina(lon: number, lat: number): boolean {
  return !(72.004 <= lon && lon <= 137.8347 && 0.8293 <= lat && lat <= 55.8271);
}

function transformLat(x: number, y: number): number {
  let ret =
    -100.0 +
    2.0 * x +
    3.0 * y +
    0.2 * y * y +
    0.1 * x * y +
    0.2 * Math.sqrt(Math.abs(x));
  ret +=
    ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) /
    3.0;
  ret += ((20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin((y / 3.0) * Math.PI)) * 2.0) / 3.0;
  ret +=
    ((160.0 * Math.sin((y / 12.0) * Math.PI) + 320.0 * Math.sin((y * Math.PI) / 30.0)) *
      2.0) /
    3.0;
  return ret;
}

function transformLon(x: number, y: number): number {
  let ret =
    300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  ret +=
    ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) /
    3.0;
  ret += ((20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin((x / 3.0) * Math.PI)) * 2.0) / 3.0;
  ret +=
    ((150.0 * Math.sin((x / 12.0) * Math.PI) + 300.0 * Math.sin((x / 30.0) * Math.PI)) *
      2.0) /
    3.0;
  return ret;
}

function delta(lon: number, lat: number): [number, number] {
  const a = 6378245.0;
  const ee = 0.006693421622965943;
  let dLat = transformLat(lon - 105.0, lat - 35.0);
  let dLon = transformLon(lon - 105.0, lat - 35.0);
  const radLat = (lat / 180.0) * Math.PI;
  let magic = Math.sin(radLat);
  magic = 1 - ee * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180.0) / (((a * (1 - ee)) / (magic * sqrtMagic)) * Math.PI);
  dLon = (dLon * 180.0) / ((a / sqrtMagic) * Math.cos(radLat) * Math.PI);
  return [dLon, dLat];
}

/** WGS84 → GCJ-02 (needed when drawing WGS84 layers on an Amap basemap). */
export function wgs84ToGcj02(lon: number, lat: number): [number, number] {
  if (outOfChina(lon, lat)) return [lon, lat];
  const [dLon, dLat] = delta(lon, lat);
  return [lon + dLon, lat + dLat];
}

/** GCJ-02 → WGS84 (needed when drawing raw Amap coords on Tianditu / OSM). */
export function gcj02ToWgs84(lon: number, lat: number): [number, number] {
  if (outOfChina(lon, lat)) return [lon, lat];
  let resultLon = lon;
  let resultLat = lat;
  for (let i = 0; i < 4; i++) {
    const [dLon, dLat] = delta(resultLon, resultLat);
    resultLon = lon - dLon;
    resultLat = lat - dLat;
  }
  return [resultLon, resultLat];
}

export function basemapUsesGcj02(basemapKey: string | undefined): boolean {
  return !!basemapKey && basemapKey.startsWith("amap-");
}

type Position = number[];

function mapPosition(
  position: Position,
  convert: (lon: number, lat: number) => [number, number],
): Position {
  if (position.length < 2) return position;
  const [lon, lat] = convert(position[0], position[1]);
  return [lon, lat, ...position.slice(2)];
}

function mapRing(
  ring: Position[],
  convert: (lon: number, lat: number) => [number, number],
): Position[] {
  return ring.map((p) => mapPosition(p, convert));
}

function transformGeometry(
  geometry: any,
  convert: (lon: number, lat: number) => [number, number],
): any {
  if (!geometry || !geometry.type || geometry.coordinates == null) return geometry;
  switch (geometry.type) {
    case "Point":
      return { ...geometry, coordinates: mapPosition(geometry.coordinates, convert) };
    case "MultiPoint":
    case "LineString":
      return {
        ...geometry,
        coordinates: geometry.coordinates.map((p: Position) => mapPosition(p, convert)),
      };
    case "MultiLineString":
    case "Polygon":
      return {
        ...geometry,
        coordinates: geometry.coordinates.map((ring: Position[]) => mapRing(ring, convert)),
      };
    case "MultiPolygon":
      return {
        ...geometry,
        coordinates: geometry.coordinates.map((poly: Position[][]) =>
          poly.map((ring) => mapRing(ring, convert)),
        ),
      };
    case "GeometryCollection":
      return {
        ...geometry,
        geometries: (geometry.geometries || []).map((g: any) =>
          transformGeometry(g, convert),
        ),
      };
    default:
      return geometry;
  }
}

/** Deep-clone GeoJSON and transform all positions with ``convert``. */
export function transformGeoJsonCoordinates(
  geojson: any,
  convert: (lon: number, lat: number) => [number, number],
): any {
  if (!geojson || typeof geojson !== "object") return geojson;
  if (geojson.type === "FeatureCollection") {
    return {
      ...geojson,
      features: (geojson.features || []).map((feature: any) => ({
        ...feature,
        geometry: transformGeometry(feature.geometry, convert),
      })),
    };
  }
  if (geojson.type === "Feature") {
    return {
      ...geojson,
      geometry: transformGeometry(geojson.geometry, convert),
    };
  }
  return transformGeometry(geojson, convert);
}
