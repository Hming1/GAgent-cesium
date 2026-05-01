"use client";

interface BasemapSelectorProps {
  onBasemapChange: (basemapKey: string) => void;
}

export default function BasemapSelector({
  onBasemapChange,
}: BasemapSelectorProps) {
  const handleBasemapChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    onBasemapChange(e.target.value);
  };

  return (
    <div>
      <h3 className="font-semibold mb-2">底图</h3>
      <select
        className="w-full p-2 border rounded"
        onChange={handleBasemapChange}
        defaultValue="carto-positron"
        data-testid="basemap-select"
      >
        <option value="osm">OpenStreetMap 标准底图</option>
        <option value="carto-positron">Carto 浅色底图</option>
        <option value="carto-dark">Carto 深色底图</option>
        <option value="google-satellite">Google 卫星影像</option>
        <option value="google-hybrid">Google 混合底图</option>
        <option value="google-terrain">Google 地形图</option>
      </select>
    </div>
  );
}
