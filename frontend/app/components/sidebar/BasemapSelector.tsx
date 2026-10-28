"use client";

import { useEffect, useState } from "react";
import { useMapStore } from "../../stores/mapStore";
import { BASEMAP_OPTIONS, getBasemap, getBasemapKey, getBasemapOptions } from "../../utils/basemaps";

interface BasemapSelectorProps {
  onBasemapChange: (basemapKey: string) => void;
}

export default function BasemapSelector({ onBasemapChange }: BasemapSelectorProps) {
  const basemap = useMapStore((state) => state.basemap);
  const notice = useMapStore((state) => state.basemapNotice);
  const setBasemap = useMapStore((state) => state.setBasemap);
  const [options, setOptions] = useState(BASEMAP_OPTIONS);
  useEffect(() => { setOptions(getBasemapOptions()); }, []);

  return (
    <div>
      <h3 className="font-semibold mb-2">底图</h3>
      <select
        aria-label="底图"
        className="w-full p-2 border rounded"
        onChange={(event) => onBasemapChange(event.target.value)}
        value={getBasemapKey(basemap)}
        data-testid="basemap-select"
      >
        {options.map((option) => (
          <option key={option.key} value={option.key} disabled={option.disabled}>
            {option.disabled && option.disabledReason
              ? option.label + "（" + option.disabledReason + "）"
              : option.label}
          </option>
        ))}
      </select>
      {notice && (
        <div role="status" data-testid="basemap-notice" className="mt-2 rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
          <p>{notice.message}</p>
          <button
            type="button"
            className="mt-1 underline"
            onClick={() => setBasemap(getBasemap(notice.retryKey))}
          >
            重试原底图
          </button>
        </div>
      )}
    </div>
  );
}
