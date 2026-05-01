import type { Metadata } from "next";
// import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Script from "next/script";
import ColorInjector from "./components/ColorInjector";
import SettingsInitializer from "./components/SettingsInitializer";
import { AuthProvider } from "./context/AuthContext";
import AuthGuard from "./components/AuthGuard";
import UserDataInitializer from "./components/UserDataInitializer";

// const geistSans = Geist({
//   variable: "--font-geist-sans",
//   subsets: ["latin"],
// });

// const geistMono = Geist_Mono({
//   variable: "--font-geist-mono",
//   subsets: ["latin"],
// });

export const metadata: Metadata = {
  title: "NaLaMap",
  description:
    "NaLaMap 是一个开源平台，帮助用户以自然语言方式查找和分析地理空间数据。它结合现代 Web 技术与 AI 能力，为地理信息交互提供直观界面。",
  icons: {
    icon: '/favicon.ico',
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">
        {/* Runtime environment variables injected at container start */}
        <Script src="/runtime-env.js" strategy="beforeInteractive" />
        {/* Initialize settings early to load custom colors */}
        <SettingsInitializer />
        {/* Dynamic CSS color injection */}
        <ColorInjector />
        {/* Authentication context + guard */}
        <AuthProvider>
          <UserDataInitializer />
          <AuthGuard>
            {children}
          </AuthGuard>
        </AuthProvider>
      </body>
    </html>
  );
}
