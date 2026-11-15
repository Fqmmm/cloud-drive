export interface Profile {
  userId: string;
  accountId: string;
  nickname: string;
  accountName: string;
  email: string;
}

export const session = reactive({
  token: localStorage.getItem("course-token") || "",
  profile: null as Profile | null,
});

export function clearSession() {
  session.token = "";
  session.profile = null;
  localStorage.removeItem("course-token");
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string
  ) {
    super(message);
  }
}

const shareMessages: Record<string, string> = {
  SHARE_NOT_FOUND: "分享不存在",
  SHARE_FILE_UNAVAILABLE: "文件已失效",
  SHARE_CANCELLED: "分享已取消",
  SHARE_EXPIRED: "分享已过期",
  SHARE_CODE_INVALID: "请输入正确提取码",
  SHARE_CODE_RATE_LIMITED: "尝试过于频繁，请稍后再试",
};

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (session.token) headers.set("Authorization", `Bearer ${session.token}`);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "连接失败，请检查网络后重试");
  }
  let result;
  try {
    result = await response.json();
  } catch {
    throw new ApiError(response.status, "GATEWAY_ERROR", `服务请求失败（${response.status}）`);
  }
  if (!response.ok || result.code !== "00000") {
    if (response.status === 401 && !path.startsWith("/s/")) {
      clearSession();
      location.hash = "/login";
    }
    throw new ApiError(
      response.status,
      result.code,
      shareMessages[result.code] || result.msg || "请求失败，请稍后重试"
    );
  }
  return result.data;
}

export async function restoreProfile() {
  session.profile = await api<Profile>("/users/me");
}

/** Reject failed/JSON/HTML responses before creating a browser download. */
export async function download(path: string, filename: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (session.token) headers.set("Authorization", `Bearer ${session.token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "下载连接失败，请重试");
  }
  const contentType = response.headers.get("Content-Type") || "";
  if (!response.ok || /json|text\/html/i.test(contentType)) {
    let message = `下载失败（${response.status}），请稍后重试`;
    let code = "DOWNLOAD_FAILED";
    if (/json/i.test(contentType)) {
      try {
        const result = await response.json();
        message = result.msg || message;
        code = result.code || code;
        message = shareMessages[code] || message;
      } catch {
        /* A gateway may label an invalid response JSON. Keep a readable fallback. */
      }
    }
    if (response.status === 401 && !path.startsWith("/s/")) {
      clearSession();
      location.hash = "/login";
    }
    throw new ApiError(response.status, code, message);
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const plain = /filename="([^"]+)"/i.exec(disposition);
  try {
    filename = encoded ? decodeURIComponent(encoded[1]) : plain?.[1] || filename;
  } catch {
    /* Retain the caller's safe filename on malformed Content-Disposition. */
  }
  let blob: Blob;
  try {
    blob = await response.blob();
  } catch {
    throw new ApiError(0, "DOWNLOAD_INTERRUPTED", "下载中断，请重试");
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename
    .split("")
    .map((character) =>
      character.charCodeAt(0) < 32 || character === "/" || character === "\\" ? "_" : character
    )
    .join("");
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
