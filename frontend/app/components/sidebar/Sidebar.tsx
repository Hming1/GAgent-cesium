"use client";

import Link from "next/link";
import Head from "next/head";
import { LogOut, Maximize, RefreshCcw, Settings, Home, Layers } from "lucide-react";
import { useRouter } from "next/navigation";
import { useAuth } from "../../context/AuthContext";
import { useChatInterfaceStore } from "../../stores/chatInterfaceStore";
import { useLayerStore } from "../../stores/layerStore";
import { useSettingsStore } from "../../stores/settingsStore";

const toggleFullscreen = () => {
  const elem = document.documentElement;

  if (!document.fullscreenElement) {
    if (elem.requestFullscreen) {
      elem.requestFullscreen();
    } else if ((elem as any).webkitRequestFullscreen) {
      (elem as any).webkitRequestFullscreen(); // Safari
    } else if ((elem as any).msRequestFullscreen) {
      (elem as any).msRequestFullscreen(); // IE11
    }
  } else {
    if (document.exitFullscreen) {
      document.exitFullscreen();
    } else if ((document as any).webkitExitFullscreen) {
      (document as any).webkitExitFullscreen(); // Safari
    } else if ((document as any).msExitFullscreen) {
      (document as any).msExitFullscreen(); // IE11
    }
  }
};

const handleReset = () => {
  if (
    !window.confirm(
      "确定要重置应用吗？这会清空所有聊天记录、图层和设置。"
    )
  ) {
    return;
  }

  try {
    // Clear chat interface store
    useChatInterfaceStore.getState().clearMessages();
    useChatInterfaceStore.getState().clearToolUpdates();
    useChatInterfaceStore.getState().clearStreamingMessage();
    useChatInterfaceStore.getState().setInput("");
    useChatInterfaceStore.getState().setGeoDataList([]);
    useChatInterfaceStore.getState().clearError();

    // Clear layer store
    useLayerStore.getState().resetLayers();

    // Reset settings
    useSettingsStore.getState().resetColorSettings();

    // Clear all localStorage (except items we want to preserve)
    const keysToRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key) {
        keysToRemove.push(key);
      }
    }
    keysToRemove.forEach((key) => localStorage.removeItem(key));

    // Reload the page to ensure clean state
    window.location.reload();
  } catch (error) {
    console.error("重置时出错:", error);
    alert("重置应用时发生错误，请尝试刷新页面。");
  }
};

export default function Sidebar({ onLayerToggle }: { onLayerToggle?: () => void }) {
  const router = useRouter();
  const { user, logout } = useAuth();

  const handleSignOut = async () => {
    await logout();
    router.push("/login");
  };

  return (
    <>
      <Head>
        <title>NaLaMapAI</title>
        <meta name="description" content="轻松获取地理空间洞察" />
      </Head>
      {/* Top Icon Section */}
      <div className="flex flex-col md:flex-col items-center justify-start md:py-4 py-2 md:space-y-4 space-y-3 h-full w-full bg-primary-800">
        {/* Home Icon */}
        <Link href="/map">
          <button
            className="hover:bg-secondary-800 rounded focus:outline-none text-white transition-colors cursor-pointer w-full md:w-auto flex items-center md:justify-center justify-start md:px-2 px-4 py-3 md:py-2"
            title="首页"
          >
            <Home className="w-6 h-6 md:mr-0 mr-3" />
            <span className="md:hidden text-base">首页</span>
          </button>
        </Link>
        {/* Layer Management Icon */}
        {onLayerToggle && (
          <button
            onClick={onLayerToggle}
            className="hover:bg-secondary-800 rounded focus:outline-none text-white transition-colors cursor-pointer w-full md:w-auto flex items-center md:justify-center justify-start md:px-2 px-4 py-3 md:py-2"
            title="图层管理"
          >
            <Layers className="w-6 h-6 md:mr-0 mr-3" />
            <span className="md:hidden text-base">图层管理</span>
          </button>
        )}
        {/* Sign out */}
        {user && (
          <button
            onClick={handleSignOut}
            className="hover:bg-secondary-800 rounded focus:outline-none text-white transition-colors cursor-pointer w-full md:w-auto flex items-center md:justify-center justify-start md:px-2 px-4 py-3 md:py-2"
            title={`退出登录 ${user.email}`}
          >
            <LogOut className="w-6 h-6 md:mr-0 mr-3" />
            <span className="md:hidden text-base">退出登录</span>
          </button>
        )}

        {/* Fullscreen Icon */}
        <button
          onClick={toggleFullscreen}
          className="hover:bg-secondary-800 rounded focus:outline-none text-white transition-colors cursor-pointer w-full md:w-auto flex items-center md:justify-center justify-start md:px-2 px-4 py-3 md:py-2"
          title="全屏模式"
        >
          <Maximize className="w-6 h-6 md:mr-0 mr-3" />
          <span className="md:hidden text-base">全屏模式</span>
        </button>

        {/* Reset Icon */}
        <button
          onClick={handleReset}
          className="hover:bg-secondary-800 rounded focus:outline-none text-white transition-colors cursor-pointer w-full md:w-auto flex items-center md:justify-center justify-start md:px-2 px-4 py-3 md:py-2"
          title="重置应用"
          data-testid="reset-button"
        >
          <RefreshCcw className="w-6 h-6 md:mr-0 mr-3" />
          <span className="md:hidden text-base">重置应用</span>
        </button>

        {/* Settings Icon */}
        <Link href="/settings">
          <button
            className="hover:bg-secondary-800 rounded focus:outline-none text-white transition-colors cursor-pointer w-full md:w-auto flex items-center md:justify-center justify-start md:px-2 px-4 py-3 md:py-2"
            title="设置"
          >
            <Settings className="w-6 h-6 md:mr-0 mr-3" />
            <span className="md:hidden text-base">设置</span>
          </button>
        </Link>
      </div>
    </>
  );
}
