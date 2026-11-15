import { test, expect } from "@playwright/test";

test("personal registration, login, refresh and logout only call course APIs", async ({ page }) => {
  const requests: string[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    requests.push(path);
    const data = path.endsWith("/login")
      ? { token: "test-browser-session" }
      : path.endsWith("/me")
        ? {
            userId: "9007199254740993",
            accountId: "2",
            nickname: "课程用户",
            accountName: "alice",
            email: "alice@example.test",
          }
        : null;
    await route.fulfill({ json: { code: "00000", msg: "成功", data } });
  });
  await page.goto("/#/system/team");
  await expect(page.getByRole("heading", { name: "欢迎登录" })).toBeVisible();
  await page.getByRole("button", { name: "创建个人账户" }).click();
  await page.getByLabel("账户名", { exact: true }).fill("Alice");
  await page.getByLabel("密码", { exact: true }).fill("test-Pass-123");
  await page.getByLabel("昵称", { exact: true }).fill("课程用户");
  await page.getByLabel("邮箱", { exact: true }).fill("alice@example.test");
  await page.getByRole("button", { name: "注册", exact: true }).click();
  await expect(page.getByText("注册成功，请登录")).toBeVisible();
  await page.getByLabel("密码", { exact: true }).fill("test-Pass-123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("navigation")).toBeVisible();
  await expect(page.getByText("课程用户", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("课程用户", { exact: true })).toBeVisible();
  await expect(page.getByRole("navigation").getByRole("link")).toHaveCount(2);
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByRole("heading", { name: "欢迎登录" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("course-token"))).toBeNull();
  expect(
    requests.every((path) =>
      ["/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/users/me"].includes(path)
    )
  ).toBeTruthy();
});

test("gateway errors stay readable and expired private credentials return to login", async ({
  page,
}) => {
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 502, contentType: "text/html", body: "<h1>Bad Gateway</h1>" })
  );
  await page.goto("/#/login");
  await page.getByLabel("账户名", { exact: true }).fill("alice");
  await page.getByLabel("密码", { exact: true }).fill("test-Pass-123");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByText("服务请求失败（502）")).toBeVisible();
  await page.unroute("**/api/**");
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 401, json: { code: "UNAUTHORIZED", msg: "凭证已过期" } })
  );
  await page.evaluate(() => localStorage.setItem("course-token", "test-expired-session"));
  await page.goto("/#/files");
  await page.reload();
  await expect(page.getByRole("heading", { name: "欢迎登录" })).toBeVisible();
});
