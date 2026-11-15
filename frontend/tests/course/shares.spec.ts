import { test, expect } from "@playwright/test";

test("create protected share preserves leading zeros, copy and cancel own share", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => localStorage.setItem("course-token", "test-share-session"));
  let cancelled = false;
  let made = false;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = { nickname: "分享用户" };
    if (path.endsWith("/shares")) {
      if (route.request().method() === "POST") {
        expect(route.request().postDataJSON()).toEqual({
          fileId: "9007199254740993",
          accessType: 1,
          expireDays: 7,
        });
        made = true;
        data = {
          id: "8",
          shareToken: "exampleToken",
          shareUrl: "http://localhost:8080/#/s/exampleToken",
          extractCode: "000123",
          expireTime: null,
        };
      } else
        data = made
          ? [
              {
                id: "8",
                fileName: "课程 资料.txt",
                shareUrl: "http://localhost:8080/#/s/exampleToken",
                accessType: 1,
                status: cancelled ? "CANCELLED" : "ACTIVE",
                createTime: new Date().toISOString(),
                expireTime: null,
              },
            ]
          : [];
    }
    if (route.request().method() === "DELETE") {
      cancelled = true;
      data = null;
    }
    await route.fulfill({ json: { code: "00000", data } });
  });
  await page.goto("/#/shares?fileId=9007199254740993&fileName=课程%20资料.txt");
  await page.getByLabel("访问方式").selectOption("1");
  await page.getByRole("button", { name: "创建分享", exact: true }).click();
  await expect(page.getByText("000123", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "复制链接及提取码", exact: true }).click();
  await expect(page.getByText("已复制", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("000123");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "取消分享", exact: true }).click();
  await expect(page.getByText("已取消", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("000123", { exact: true })).toHaveCount(0);
});

test("anonymous page keeps wrong code local and resubmits code for POST download", async ({
  page,
}) => {
  let downloadBody: unknown;
  const requests: string[] = [];
  await page.addInitScript(() =>
    localStorage.setItem("course-token", "test-expired-private-token")
  );
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    requests.push(path);
    const code =
      route.request().method() === "POST" ? route.request().postDataJSON().extractCode : null;
    if (path.endsWith("/verify") || path.endsWith("/download")) {
      if (code !== "000123") {
        await route.fulfill({
          status: 403,
          json: { code: "SHARE_CODE_INVALID", msg: "请输入正确提取码" },
        });
        return;
      }
      if (path.endsWith("/download")) {
        downloadBody = route.request().postDataJSON();
        await route.fulfill({ contentType: "application/octet-stream", body: "share-content" });
        return;
      }
      await route.fulfill({
        json: {
          code: "00000",
          data: { requiresCode: true, fileName: "课程资料.txt", fileSize: 13, expireTime: null },
        },
      });
      return;
    }
    await route.fulfill({
      json: {
        code: "00000",
        data: { requiresCode: true, fileName: null, fileSize: null, expireTime: null },
      },
    });
  });
  await page.goto("/#/s/exampleToken");
  await expect(page.getByText("课程资料.txt", { exact: true })).toHaveCount(0);
  await page.getByLabel("提取码", { exact: true }).fill("111111");
  await page.getByRole("button", { name: "验证提取码" }).click();
  await expect(page.getByText("请输入正确提取码", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/#\/s\/exampleToken/);
  await page.getByLabel("提取码", { exact: true }).fill("000123");
  await page.getByRole("button", { name: "验证提取码" }).click();
  await expect(page.getByText("课程资料.txt", { exact: true })).toBeVisible();
  await page.getByLabel("提取码", { exact: true }).fill("222222");
  await page.getByRole("button", { name: "下载文件", exact: true }).click();
  await expect(page.getByText("请输入正确提取码", { exact: true })).toBeVisible();
  await page.getByLabel("提取码", { exact: true }).fill("000123");
  const saved = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载文件", exact: true }).click();
  expect((await saved).suggestedFilename()).toBe("课程资料.txt");
  expect(downloadBody).toEqual({ extractCode: "000123" });
  expect(requests.every((path) => path.startsWith("/api/v1/s/"))).toBeTruthy();
});

test("cancelled shares show the service reason without a login redirect", async ({ page }) => {
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 410, json: { code: "SHARE_CANCELLED", msg: "分享已取消" } })
  );
  await page.goto("/#/s/cancelledToken");
  await expect(page.getByText("分享已取消", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/#\/s\/cancelledToken/);
});
