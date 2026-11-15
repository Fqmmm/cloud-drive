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
    throw new ApiError(response.status, result.code, result.msg || "请求失败，请稍后重试");
  }
  return result.data;
}

export async function restoreProfile() {
  session.profile = await api<Profile>("/users/me");
}
