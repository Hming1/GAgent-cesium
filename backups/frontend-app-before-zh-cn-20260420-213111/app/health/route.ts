import { NextResponse } from "next/server";

/**
 * Lightweight health check endpoint for Next.js frontend
 * Returns immediately with minimal processing - used by nginx health checks
 * and the loading page to determine when the frontend is ready
 */
/*** Next.js前端的轻量级健康检查端点*立即返回与nginx健康检查使用的最小处理*和加载页面，以确定何时前端准备好*/
export async function GET() {
  return NextResponse.json(
    { 
      status: "ok",
      service: "frontend",
      timestamp: Date.now()
    },
    {
      status: 200,
      headers: {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Content-Type": "application/json",
      },
    }
  );
}
