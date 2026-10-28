"use client";

import React, { useEffect, useRef, useState } from "react";
import Sidebar from "../components/sidebar/Sidebar";
import MapComponent from "../components/maps/MapComponent";
import InefficientSpacePanel from "../components/inefficient-space/InefficientSpacePanel";
import ResultSummary from "../components/inefficient-space/ResultSummary";
import AgentInterface from "../components/chat/AgentInterface";
import { useUIStore } from "../stores/uiStore";
import {
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
  Building2,
  MessageCircle,
} from "lucide-react";

export default function InefficientSpacePage() {
  const sidebarWidth = useUIStore((s) => s.sidebarWidth);
  const [widths, setWidths] = useState<number[]>([4, 26, 46, 24]);
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const [chatCollapsed, setChatCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const dragInfo = useRef<{
    active: boolean;
    handleIndex: number;
    startX: number;
    initialWidths: number[];
  }>({ active: false, handleIndex: 0, startX: 0, initialWidths: [0, 0, 0, 0] });

  useEffect(() => {
    const isMobile = window.innerWidth < 768;
    setPanelCollapsed(isMobile);
    setChatCollapsed(isMobile);
  }, []);

  const onMouseMove = (e: MouseEvent) => {
    if (!dragInfo.current.active) return;
    const deltaX = e.clientX - dragInfo.current.startX;
    const deltaPercent = (deltaX / window.innerWidth) * 100;
    const idx = dragInfo.current.handleIndex;
    const newWidths = [...dragInfo.current.initialWidths];
    newWidths[idx] = dragInfo.current.initialWidths[idx] + deltaPercent;
    newWidths[idx + 1] = dragInfo.current.initialWidths[idx + 1] - deltaPercent;
    const minPanelPx = 220;
    const minPanelPct = (minPanelPx / window.innerWidth) * 100;
    const defaultMinPct = 2;
    const minLeft = idx === 1 || idx === 2 ? minPanelPct : defaultMinPct;
    const minRight = idx === 2 ? minPanelPct : defaultMinPct;
    if (newWidths[idx] < minLeft) {
      newWidths[idx + 1] += newWidths[idx] - minLeft;
      newWidths[idx] = minLeft;
    }
    if (newWidths[idx + 1] < minRight) {
      newWidths[idx] += newWidths[idx + 1] - minRight;
      newWidths[idx + 1] = minRight;
    }
    setWidths(newWidths);
  };

  const onMouseUp = () => {
    dragInfo.current.active = false;
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", onMouseUp);
  };

  const onHandleMouseDown = (e: React.MouseEvent, idx: number) => {
    e.preventDefault();
    dragInfo.current = {
      active: true,
      handleIndex: idx,
      startX: e.clientX,
      initialWidths: [...widths],
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  };

  return (
    <>
      <button
        className="md:hidden fixed top-4 right-4 z-[25] p-3 bg-primary-800 rounded-md shadow-lg hover:bg-primary-700"
        onClick={() => setMobileMenuOpen(true)}
        aria-label="打开菜单"
      >
        <Menu className="w-8 h-8 text-white" />
      </button>
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-[30]"
          onClick={() => setMobileMenuOpen(false)}
        >
          <div
            className="fixed top-0 right-0 bottom-0 w-full max-w-xs bg-primary-800 z-[31] text-white flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-4 border-b border-primary-700">
              <h2 className="text-lg font-semibold">菜单</h2>
              <button
                className="p-1 hover:bg-primary-700 rounded"
                onClick={() => setMobileMenuOpen(false)}
                aria-label="关闭菜单"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              <Sidebar
                onLayerToggle={() => {
                  setPanelCollapsed(!panelCollapsed);
                  setMobileMenuOpen(false);
                }}
              />
            </div>
          </div>
        </div>
      )}

      <div className="flex h-screen w-screen overflow-hidden">
        <div
          style={{ flexBasis: `${widths[0]}%` }}
          className="hidden md:flex flex-none relative bg-primary-800"
        >
          <Sidebar onLayerToggle={() => setPanelCollapsed(!panelCollapsed)} />
          <div
            className="absolute top-0 right-0 bottom-0 w-1 hover:bg-primary-400 cursor-ew-resize z-10"
            onMouseDown={(e) => onHandleMouseDown(e, 0)}
          />
        </div>

        {!panelCollapsed ? (
          <div
            style={{ flexBasis: `${widths[1]}%` }}
            className="flex-none relative min-w-[240px] bg-primary-100"
          >
            <button
              className="absolute top-2 right-2 p-1 bg-primary-200 rounded shadow z-10 hover:bg-primary-300"
              onClick={() => setPanelCollapsed(true)}
            >
              <ChevronLeft className="w-4 h-4 text-primary-700" />
            </button>
            <InefficientSpacePanel />
            <div
              className="absolute top-0 right-0 bottom-0 w-1 hover:bg-primary-400 cursor-ew-resize z-10"
              onMouseDown={(e) => onHandleMouseDown(e, 1)}
            />
          </div>
        ) : (
          <button
            className="fixed bottom-4 p-3 bg-primary-800 rounded-full shadow-lg z-[25] hover:bg-primary-700 touch-manipulation"
            style={{ left: `calc(1rem + ${sidebarWidth}vw)` }}
            onClick={() => setPanelCollapsed(false)}
            aria-label="打开低效空间面板"
          >
            <Building2 className="w-9 h-9 text-white" />
          </button>
        )}

        <div className="flex-1 relative">
          <MapComponent />
          {!chatCollapsed && (
            <div
              className="absolute top-0 right-0 bottom-0 w-1 hover:bg-primary-400 cursor-ew-resize z-10"
              onMouseDown={(e) => onHandleMouseDown(e, 2)}
            />
          )}
        </div>

        {!chatCollapsed ? (
          <div
            style={{ flexBasis: `${widths[3]}%` }}
            className="flex-none relative min-w-[260px] bg-primary-50 flex flex-col overflow-hidden"
          >
            <button
              className="absolute top-2 left-2 p-1 bg-primary-200 rounded shadow z-10 hover:bg-primary-300"
              onClick={() => setChatCollapsed(true)}
            >
              <ChevronRight className="w-4 h-4 text-primary-700" />
            </button>
            <div className="flex-shrink-0 border-b border-primary-200 px-4 pt-10 pb-3 max-h-[34%] overflow-auto">
              <h2 className="text-sm font-semibold text-primary-800 mb-2">
                判别结果
              </h2>
              <ResultSummary />
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              <AgentInterface
                title="低效空间助手"
                placeholder="例如：用 public.parcels 识别工业低效用地，闲置按 3 年…"
              />
            </div>
          </div>
        ) : (
          <button
            className="fixed bottom-4 right-4 p-3 bg-primary-800 rounded-full shadow-lg z-[25] hover:bg-primary-700 touch-manipulation"
            onClick={() => setChatCollapsed(false)}
            aria-label="打开智能体对话"
          >
            <MessageCircle className="w-9 h-9 text-white" />
          </button>
        )}
      </div>
    </>
  );
}
