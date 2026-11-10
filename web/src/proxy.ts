import { NextResponse, type NextRequest } from "next/server";

/**
 * 乐观跳转：只检查登录 cookie 是否存在，不校验其内容。
 * 真正的鉴权由后端的 require_user 强制执行；cookie 过期或无效时，AppShell 调用 /auth/me 再跳转登录页。
 */
const COOKIE_NAME = "rag_session";

// 无需登录即可访问的页面
const PUBLIC_PATHS = ["/login", "/register", "/verify", "/forgot"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // 公开页面一律放行。注意：登录页不能因为「有 cookie」而重定向到首页——
  // cookie 可能已过期，那样会在 "/" 与 "/login" 之间死循环
  if (PUBLIC_PATHS.includes(pathname)) {
    return NextResponse.next();
  }

  if (!request.cookies.has(COOKIE_NAME)) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // 静态资源与 API 不经过 proxy（API 由后端自行鉴权）
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/).*)"],
};
