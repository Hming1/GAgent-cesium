"use client";

import dynamic from "next/dynamic";

// Only load the real CesiumMapClient in the browser
const CesiumMapClient = dynamic(() => import("./CesiumMapClient"), {
  ssr: false,
});

export default function CesiumMap(props: any) {
  return <CesiumMapClient {...props} />;
}
