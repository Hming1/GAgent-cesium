"""Point, boundary, and China POI helpers for Nominatim outages."""

import hashlib
import logging
import math
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from shapely.geometry import MultiPolygon, Polygon, mapping

logger = logging.getLogger(__name__)

AMAP_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"
# Radius / centre constrained POI search. Amap ignores location+radius on
# place/text, so around is required for "within N metres of X" queries.
AMAP_PLACE_AROUND_URL = "https://restapi.amap.com/v3/place/around"
AMAP_DISTRICT_URL = "https://restapi.amap.com/v3/config/district"
BAIDU_URL = "https://api.map.baidu.com/geocoding/v3/"
REQUEST_TIMEOUT = 5
AMAP_POI_PAGE_SIZE = 25
# Amap stops paging a single keyword/type/city query at roughly 200 POIs, so
# city-wide searches are split per district (see _amap_city_district_adcodes).
AMAP_POI_MAX_PAGES = 40
AMAP_MUNICIPALITIES = ("北京市", "上海市", "天津市", "重庆市")
# QPS throttling infocodes; worth a short back-off and retry.
AMAP_QPS_INFOCODES = {"10019", "10020", "10021"}
AMAP_QPS_RETRY_DELAYS = (0.5, 1.0)

# Amenity key / Chinese topic → Amap place type codes.
# See https://lbs.amap.com/api/webservice/download (POI classification).
AMAP_POI_TYPE_MAPPING = {
    "school": "141200",
    "schools": "141200",
    "middle_school": "141202",
    "middle schools": "141202",
    "high_school": "141202",
    "primary_school": "141203",
    "kindergarten": "141204",
    "university": "141201",
    "college": "141201",
    "hospital": "090100|090200",
    "hospitals": "090100|090200",
    "pharmacy": "090601",
    "pharmacies": "090601",
    "restaurant": "050000",
    "restaurants": "050000",
    "cafe": "050500",
    "cafes": "050500",
    "hotel": "100000",
    "hotels": "100000",
    "bank": "160100",
    "banks": "160100",
    "atm": "160300",
    "supermarket": "060100",
    "supermarkets": "060100",
    "park": "110101",
    "parks": "110101",
    "parking": "150900",
    "gas station": "010100",
    "gas stations": "010100",
    "fuel": "010100",
    "police": "130501",
    "fire station": "130502",
    "library": "140500",
    "libraries": "140500",
    "cinema": "080601",
    "cinemas": "080601",
    "bus stop": "150700",
    "bus stops": "150700",
    "train station": "150200",
    "train stations": "150200",
    "subway station": "150500",
    "airport": "150100",
    "airports": "150100",
}

AMAP_POI_KEYWORD_HINTS = {
    "中学": "141202",
    "初中": "141202",
    "高中": "141202",
    "小学": "141203",
    "幼儿园": "141204",
    "大学": "141201",
    "高校": "141201",
    "医院": "090100|090200",
    "药店": "090601",
    "餐厅": "050000",
    "饭店": "050000",
    "酒店": "100000",
    "宾馆": "100000",
    "银行": "160100",
    "超市": "060100",
    "公园": "110101",
    "加油站": "010100",
    "派出所": "130501",
    "图书馆": "140500",
    "电影院": "080601",
    "地铁站": "150500",
    "火车站": "150200",
    "机场": "150100",
}

_CN_CHAR = re.compile(r"[\u4e00-\u9fff]")


def _gcj02_offset(lon: float, lat: float) -> Tuple[float, float]:
    """Return the GCJ-02 offset for a WGS84 position in mainland China."""
    if not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return 0.0, 0.0

    x, y = lon - 105.0, lat - 35.0
    lat_delta = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
        + (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        + (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        + (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    )
    lon_delta = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * math.sqrt(abs(x))
        + (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        + (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        + (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    )
    a, eccentricity = 6378245.0, 0.006693421622965943
    rad_lat = lat / 180.0 * math.pi
    magic = 1 - eccentricity * math.sin(rad_lat) ** 2
    sqrt_magic = math.sqrt(magic)
    lat_delta = lat_delta * 180.0 / ((a * (1 - eccentricity)) / (magic * sqrt_magic) * math.pi)
    lon_delta = lon_delta * 180.0 / (a / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lon_delta, lat_delta


def gcj02_to_wgs84(lon: float, lat: float) -> Tuple[float, float]:
    """Invert GCJ-02 for GeoJSON's WGS84 coordinates."""
    result_lon, result_lat = lon, lat
    for _ in range(4):
        delta_lon, delta_lat = _gcj02_offset(result_lon, result_lat)
        result_lon = lon - delta_lon
        result_lat = lat - delta_lat
    return result_lon, result_lat


def wgs84_to_gcj02(lon: float, lat: float) -> Tuple[float, float]:
    """Apply the GCJ-02 offset used by Chinese map providers."""
    delta_lon, delta_lat = _gcj02_offset(lon, lat)
    return lon + delta_lon, lat + delta_lat


def haversine_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance between two WGS84 points, in metres."""
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def looks_like_china_query(
    location_name: str,
    *,
    display_name: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> bool:
    """Heuristic: Chinese text or a mainland China center point."""
    text = f"{location_name or ''} {display_name or ''}"
    if _CN_CHAR.search(text):
        return True
    lowered = text.lower()
    if "china" in lowered or "prc" in lowered:
        return True
    if lat is None or lon is None:
        return False
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return 73.0 <= lon_f <= 135.5 and 18.0 <= lat_f <= 53.8


def resolve_amap_poi_types(amenity_key: str, query: str = "") -> Optional[str]:
    """Map an amenity key or Chinese topic onto Amap type codes."""
    cleaned = (amenity_key or "").lower().replace(" ", "_").strip()
    spaced = cleaned.replace("_", " ")
    text = f"{query or ''} {amenity_key or ''}"
    for hint, type_code in AMAP_POI_KEYWORD_HINTS.items():
        if hint in text:
            return type_code
    return AMAP_POI_TYPE_MAPPING.get(cleaned) or AMAP_POI_TYPE_MAPPING.get(spaced)


def _poi_keywords(query: str, amenity_key: str, location_name: str) -> str:
    text = (query or "").strip()
    for token in (location_name or "", "的", "附近", "周边", "范围内", "帮我找", "查找"):
        if token:
            text = text.replace(token, "")
    text = re.sub(r"\s+", "", text).strip(" ，,。.")
    if text and _CN_CHAR.search(text):
        return text
    labels = {
        "school": "学校",
        "schools": "学校",
        "middle_school": "中学",
        "hospital": "医院",
        "hospitals": "医院",
        "restaurant": "餐厅",
        "restaurants": "餐厅",
        "park": "公园",
        "parks": "公园",
        "hotel": "酒店",
        "hotels": "酒店",
        "bank": "银行",
        "banks": "银行",
        "supermarket": "超市",
        "pharmacy": "药店",
        "cafe": "咖啡店",
        "parking": "停车场",
        "police": "派出所",
        "library": "图书馆",
        "cinema": "电影院",
        "fuel": "加油站",
        "gas station": "加油站",
        "airport": "机场",
        "train station": "火车站",
        "bus stop": "公交站",
        "subway station": "地铁站",
    }
    cleaned = (amenity_key or "").lower().replace(" ", "_")
    return labels.get(cleaned) or labels.get(cleaned.replace("_", " ")) or (amenity_key or "POI")


def _amap_poi_to_feature(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    location = item.get("location")
    if not isinstance(location, str) or "," not in location:
        return None
    try:
        lon_s, lat_s = location.split(",", 1)
        lon, lat = gcj02_to_wgs84(float(lon_s), float(lat_s))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return None
    name = item.get("name") or "未命名"
    # Store WGS84 geometry for Tianditu/OSM/Cesium; keep original GCJ-02 for
    # diagnostics and for optional display on an Amap (GCJ-02) basemap.
    gcj_lon, gcj_lat = float(lon_s), float(lat_s)
    props = {
        "name": name,
        "id": item.get("id"),
        "type": item.get("type"),
        "typecode": item.get("typecode"),
        "address": item.get("address"),
        "pname": item.get("pname"),
        "cityname": item.get("cityname"),
        "adname": item.get("adname"),
        "tel": item.get("tel"),
        "source": "Amap",
        "crs": "EPSG:4326",
        "coord_transform": "gcj02_to_wgs84",
        "gcj02": [gcj_lon, gcj_lat],
    }
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {k: v for k, v in props.items() if v not in (None, "", [])},
    }


def search_amap_pois(
    *,
    amenity_key: str,
    query: str,
    location_name: str,
    max_results: int = 2500,
    city: Optional[str] = None,
    center: Optional[Tuple[float, float]] = None,
    radius_meters: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Search Amap for domestic POIs. Returns WGS84 GeoJSON features.

    ``location``/``radius`` on Amap's ``place/text`` endpoint are ignored, so a
    radius-constrained request must go through ``place/around`` instead. Without
    that, "hospitals within 500 m of X" silently returns hospitals for the whole
    city. When ``center`` and ``radius_meters`` are both provided we therefore use
    the around endpoint and additionally drop any POI outside the radius.
    """
    key = os.getenv("AMAP_WEB_SERVICE_KEY")
    if not key:
        return []
    types = resolve_amap_poi_types(amenity_key, query)
    keywords = _poi_keywords(query, amenity_key, location_name)
    if not types and not keywords:
        return []

    city_name = (city or location_name or "").strip()
    # Prefer the first administrative chunk: "深圳市, 广东省" → "深圳市"
    city_name = re.split(r"[,，(（]", city_name, maxsplit=1)[0].strip()
    city_name = re.sub(r"\s*\(.*?\)\s*", "", city_name).strip() or location_name

    limit = max(1, int(max_results or 2500))

    # A radius search only makes sense with a real centre and a positive radius.
    around_center = None
    if center is not None and radius_meters and int(radius_meters) > 0:
        try:
            c_lon, c_lat = float(center[0]), float(center[1])
            if math.isfinite(c_lon) and math.isfinite(c_lat):
                # Amap expects GCJ-02 input coordinates.
                g_lon, g_lat = wgs84_to_gcj02(c_lon, c_lat)
                around_center = (g_lon, g_lat, int(radius_meters), c_lon, c_lat)
        except (TypeError, ValueError):
            around_center = None

    features: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    if around_center is not None:
        g_lon, g_lat, radius, _, _ = around_center
        _collect_amap_pois(
            AMAP_PLACE_AROUND_URL,
            {
                "key": key,
                "location": f"{g_lon:.6f},{g_lat:.6f}",
                "radius": str(radius),
                "sortrule": "distance",
                **({"types": types} if types else {}),
            },
            features,
            seen_ids,
            limit,
            around_center=around_center,
        )
        return features

    # City-level areas exceed Amap's per-query paging cap, so query each
    # district separately; districts and smaller areas are queried directly.
    district_adcodes = _amap_city_district_adcodes(key, city_name) if city_name else None
    for area in district_adcodes or [city_name]:
        params = {"key": key, "keywords": keywords, "citylimit": "true"}
        if area:
            params["city"] = area
        if types:
            params["types"] = types
        _collect_amap_pois(AMAP_PLACE_TEXT_URL, params, features, seen_ids, limit)
        if len(features) >= limit:
            break
    if district_adcodes:
        logger.info(
            "Amap POI search for %s merged %s districts into %s features",
            city_name,
            len(district_adcodes),
            len(features),
        )
    return features


def _collect_amap_pois(
    url: str,
    base_params: Dict[str, str],
    features: List[Dict[str, Any]],
    seen_ids: set,
    limit: int,
    around_center: Optional[Tuple[float, float, int, float, float]] = None,
) -> None:
    """Page through one Amap POI query, appending unseen features in place."""
    for page in range(1, AMAP_POI_MAX_PAGES + 1):
        params = {
            **base_params,
            "offset": str(AMAP_POI_PAGE_SIZE),
            "page": str(page),
            "extensions": "base",
            "output": "JSON",
        }
        payload = _get_amap_json(url, params)
        if not payload or str(payload.get("status")) != "1":
            return
        pois = payload.get("pois")
        if not isinstance(pois, list) or not pois:
            return

        for item in pois:
            if not isinstance(item, dict):
                continue
            poi_id = str(item.get("id") or "")
            if poi_id and poi_id in seen_ids:
                continue
            feature = _amap_poi_to_feature(item)
            if not feature:
                continue
            # Belt-and-braces: never let a POI escape the requested radius, even
            # if the upstream endpoint returns something outside it.
            if around_center is not None:
                _, _, radius, c_lon, c_lat = around_center
                coords = ((feature.get("geometry") or {}).get("coordinates")) or []
                if len(coords) >= 2:
                    if haversine_meters(c_lon, c_lat, coords[0], coords[1]) > radius:
                        continue
            if poi_id:
                seen_ids.add(poi_id)
            features.append(feature)
            if len(features) >= limit:
                return

        if len(pois) < AMAP_POI_PAGE_SIZE:
            return


def _amap_city_district_adcodes(key: str, city_name: str) -> Optional[List[str]]:
    """Return district adcodes when ``city_name`` resolves to a city-level area.

    Prefecture-level cities and the four municipalities are split; districts,
    counties, streets, ordinary provinces and cities without districts (e.g.
    东莞市) return ``None`` so the caller queries the area directly.
    """
    payload = _get_amap_json(
        AMAP_DISTRICT_URL,
        {
            "key": key,
            "keywords": city_name,
            "subdistrict": "2",
            "extensions": "base",
            "output": "JSON",
        },
    )
    if not payload or str(payload.get("status")) != "1":
        return None
    districts = payload.get("districts")
    if not isinstance(districts, list) or not districts or not isinstance(districts[0], dict):
        return None
    top = districts[0]
    level = top.get("level")
    if level == "province" and top.get("name") not in AMAP_MUNICIPALITIES:
        return None
    if level not in ("city", "province"):
        return None

    children = [c for c in top.get("districts") or [] if isinstance(c, dict)]
    # Municipalities may nest districts under a "城区" city-level node.
    if children and all(c.get("level") == "city" for c in children):
        children = [g for c in children for g in c.get("districts") or [] if isinstance(g, dict)]
    adcodes = [
        str(c["adcode"]) for c in children if c.get("level") == "district" and c.get("adcode")
    ]
    return adcodes if len(adcodes) > 1 else None


def _get_amap_json(url: str, params: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """GET an Amap endpoint, backing off briefly when the key's QPS is exceeded."""
    payload = _get_json(url, params)
    for delay in AMAP_QPS_RETRY_DELAYS:
        if not payload or str(payload.get("infocode")) not in AMAP_QPS_INFOCODES:
            break
        time.sleep(delay)
        payload = _get_json(url, params)
    return payload


def _point_result(
    query: str, provider: str, lon: Any, lat: Any, address: str, details: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    lon, lat = gcj02_to_wgs84(lon, lat)
    if not isinstance(address, str) or not address:
        address = query
    identifier = hashlib.sha256(f"{provider}:{query}:{lon}:{lat}".encode("utf-8")).hexdigest()[:16]
    return {
        "place_id": identifier,
        "name": query,
        "display_name": address or query,
        "lat": str(lat),
        "lon": str(lon),
        "boundingbox": [str(lat), str(lat), str(lon), str(lon)],
        "geojson": {"type": "Point", "coordinates": [lon, lat]},
        "licence": provider,
        "importance": 0.0,
        "_provider": provider,
        "address": details,
    }


def _get_json(url: str, params: Dict[str, str]) -> Optional[Dict[str, Any]]:
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            logger.warning("Geocoding provider returned HTTP %s", response.status_code)
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Geocoding provider request failed: %s", type(exc).__name__)
        return None


def geocode_with_fallbacks(query: str, limit: int) -> List[Dict[str, Any]]:
    """Try configured Chinese address providers in order: Amap, then Baidu."""
    amap_key = os.getenv("AMAP_WEB_SERVICE_KEY")
    if amap_key:
        payload = _get_json(AMAP_URL, {"key": amap_key, "address": query, "output": "JSON"})
        if (
            payload
            and str(payload.get("status")) == "1"
            and isinstance(payload.get("geocodes"), list)
        ):
            results = []
            for item in payload.get("geocodes", [])[:limit]:
                if not isinstance(item, dict):
                    continue
                location = item.get("location")
                if not isinstance(location, str) or "," not in location:
                    continue
                lon, lat = location.split(",", 1)
                result = _point_result(
                    query, "Amap", lon, lat, item.get("formatted_address", query), item
                )
                if result:
                    results.append(result)
            if results:
                return results

    baidu_key = os.getenv("BAIDU_GEOCODING_AK")
    if baidu_key:
        payload = _get_json(
            BAIDU_URL,
            {"ak": baidu_key, "address": query, "output": "json", "ret_coordtype": "gcj02ll"},
        )
        if payload and payload.get("status") == 0:
            result = payload.get("result")
            if isinstance(result, dict) and isinstance(result.get("location"), dict):
                location = result["location"]
                point = _point_result(
                    query, "Baidu", location.get("lng"), location.get("lat"), query, result
                )
                if point:
                    return [point]
    return []


def geocode_boundary_with_amap(query: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch administrative polygons; never substitute a geocoded center point."""
    key = os.getenv("AMAP_WEB_SERVICE_KEY")
    if not key or not query.strip() or limit < 1:
        return []
    payload = _get_json(
        "https://restapi.amap.com/v3/config/district",
        {
            "key": key,
            "keywords": query,
            "subdistrict": "0",
            "extensions": "all",
            "offset": str(min(limit, 20)),
            "output": "JSON",
        },
    )
    if not payload or str(payload.get("status")) != "1":
        return []
    districts = payload.get("districts")
    if not isinstance(districts, list):
        return []
    results = []
    for district in districts[:limit]:
        if not isinstance(district, dict) or not isinstance(district.get("polyline"), str):
            continue
        try:
            polygons = []
            for part in district["polyline"].split("|"):
                ring = []
                for pair in part.split(";"):
                    lon, lat = map(float, pair.split(","))
                    if not (
                        math.isfinite(lon)
                        and math.isfinite(lat)
                        and -180 <= lon <= 180
                        and -90 <= lat <= 90
                    ):
                        raise ValueError("Invalid boundary coordinate")
                    ring.append(gcj02_to_wgs84(lon, lat))
                if len(set(ring)) < 3:
                    raise ValueError("Incomplete boundary ring")
                polygon = Polygon(ring)
                if not polygon.is_valid or polygon.area == 0:
                    raise ValueError("Invalid boundary polygon")
                polygons.append(polygon)
            geometry = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
            if not geometry.is_valid:
                raise ValueError("Invalid boundary topology")
        except (TypeError, ValueError):
            logger.warning("Amap returned an invalid administrative boundary")
            continue
        west, south, east, north = geometry.bounds
        center = geometry.representative_point()
        name = district.get("name") or query
        identifier = hashlib.sha256(
            f"Amap:boundary:{district.get('adcode')}:{name}".encode("utf-8")
        ).hexdigest()[:16]
        results.append(
            {
                "place_id": identifier,
                "name": name,
                "display_name": name,
                "lat": str(center.y),
                "lon": str(center.x),
                "boundingbox": list(map(str, (south, north, west, east))),
                "geojson": mapping(geometry),
                "licence": "Amap",
                "importance": 0.0,
                "_provider": "Amap",
                "class": "boundary",
                "type": "administrative",
                "address": {"adcode": district.get("adcode"), "level": district.get("level")},
            }
        )
    return results
