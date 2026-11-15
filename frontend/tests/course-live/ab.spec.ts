import { test, expect, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

test("two users and anonymous recipients complete the real course workflow", async ({
  browser,
}) => {
  const ownerContext = await browser.newContext();
  const otherContext = await browser.newContext();
  const anonymousContext = await browser.newContext();
  const owner = await ownerContext.newPage();
  const other = await otherContext.newPage();
  const anonymous = await anonymousContext.newPage();
  const base = process.env.COURSE_BASE_URL!;
  const suffix = process.env.COURSE_TEST_SUFFIX!;
  const password = process.env.COURSE_TEST_PASSWORD!;
  const origins: string[] = [];
  for (const page of [owner, other, anonymous])
    page.on("request", (request) => {
      if (request.url().includes("/api/")) origins.push(new URL(request.url()).origin);
    });
  async function register(page: Page, name: string) {
    await page.goto(base + "/#/login");
    await page.getByRole("button", { name: "创建个人账户" }).click();
    await page.getByLabel("账户名", { exact: true }).fill(name);
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByLabel("昵称", { exact: true }).fill(name);
    await page.getByLabel("邮箱", { exact: true }).fill(name + "@example.test");
    await page.getByRole("button", { name: "注册", exact: true }).click();
    await expect(page.getByText("注册成功，请登录")).toBeVisible();
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await expect(page.getByRole("heading", { name: "个人文件", exact: true })).toBeVisible();
    await expect(page.getByText("10.0 GiB", { exact: false })).toBeVisible();
  }
  const content = Buffer.alloc(65536);
  for (let index = 0; index < content.length; index++) content[index] = index % 251;
  const hash = createHash("sha256").update(content).digest("hex");
  async function download(page: Page, button: string, filename: string) {
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: button, exact: true }).click();
    const saved = await pending;
    expect(saved.suggestedFilename()).toBe(filename);
    expect(
      createHash("sha256")
        .update(await readFile((await saved.path())!))
        .digest("hex")
    ).toBe(hash);
  }
  try {
    await test.step("register owner, refresh login and create a directory", async () => {
      await register(owner, "owner_" + suffix);
      await owner.reload();
      await expect(owner.getByRole("heading", { name: "个人文件", exact: true })).toBeVisible();
      await owner.getByLabel("新目录名称").fill("课程资料");
    });
    const directoryResponse = owner.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/directories") && response.request().method() === "POST"
    );
    await owner.getByRole("button", { name: "新建目录", exact: true }).click();
    const directory = (await (await directoryResponse).json()).data.id as string;
    expect(directory).toBe("9007199254740993");
    await owner.getByRole("button", { name: "课程资料 /", exact: true }).click();
    await expect(
      owner.getByRole("navigation", { name: "文件路径" }).getByText("课程资料")
    ).toBeVisible();
    const uploadedResponse = owner.waitForResponse(
      (response) =>
        response.url().includes("/api/v1/files?parentId=") && response.request().method() === "POST"
    );
    await owner.getByLabel("选择上传文件").setInputFiles({
      name: "课程 资料.bin",
      mimeType: "application/octet-stream",
      buffer: content,
    });
    await owner.getByRole("button", { name: "上传文件", exact: true }).click();
    const file = (await (await uploadedResponse).json()).data.id as string;
    expect(typeof file).toBe("string");
    await expect(owner.getByText("课程 资料.bin", { exact: true })).toBeVisible();
    await test.step("download owner bytes and rename source", async () => {
      await download(owner, "下载", "课程 资料.bin");
      owner.once("dialog", (dialog) => dialog.accept("重命名 资料.bin"));
      await owner.getByRole("button", { name: "重命名", exact: true }).click();
      await expect(owner.getByText("重命名 资料.bin", { exact: true })).toBeVisible();
    });
    await owner.getByRole("button", { name: "分享", exact: true }).click();
    await owner.getByRole("button", { name: "创建分享", exact: true }).click();
    const publicUrl = await owner.getByLabel("分享地址", { exact: true }).inputValue();
    expect(publicUrl.startsWith(base + "/#/s/")).toBe(true);
    await owner.getByLabel("访问方式").selectOption("1");
    await owner.getByRole("button", { name: "创建分享", exact: true }).click();
    await expect(owner.locator("[aria-label='新分享结果'] strong")).toBeVisible();
    const code = (await owner.locator("[aria-label='新分享结果'] strong").textContent())!;
    const protectedUrl = await owner.getByLabel("分享地址", { exact: true }).inputValue();
    expect(/^[0-9]{6}$/.test(code)).toBe(true);
    await test.step("second user cannot operate owner resources", async () => {
      await register(other, "other_" + suffix);
      const statuses = await other.evaluate(
        async ({ file, directory }) => {
          const authorization = "Bearer " + localStorage.getItem("course-token");
          const calls = [
            { path: "/files?parentId=" + directory, method: "GET" },
            { path: `/files/${file}/download`, method: "GET" },
            { path: `/files/${file}/rename`, method: "PUT", body: { name: "越权.bin" } },
            { path: `/files/${file}`, method: "DELETE" },
            {
              path: "/shares",
              method: "POST",
              body: { fileId: file, accessType: 0, expireDays: null },
            },
          ];
          return Promise.all(
            calls.map(
              async (call) =>
                (
                  await fetch("/api/v1" + call.path, {
                    method: call.method,
                    headers: { Authorization: authorization, "Content-Type": "application/json" },
                    body: call.body ? JSON.stringify(call.body) : undefined,
                  })
                ).status
            )
          );
        },
        { file, directory }
      );
      expect(statuses).toEqual([404, 404, 404, 404, 404]);
    });
    await owner.getByRole("link", { name: "个人文件", exact: true }).click();
    owner.once("dialog", (dialog) => dialog.accept());
    await owner.getByRole("button", { name: "永久删除", exact: true }).click();
    await expect(owner.getByText("请先删除目录中的内容", { exact: true })).toBeVisible();
    owner.once("dialog", (dialog) => dialog.accept("归档资料"));
    await owner.getByRole("button", { name: "重命名", exact: true }).click();
    await owner.getByRole("button", { name: "归档资料 /", exact: true }).click();
    await expect(owner.getByText("重命名 资料.bin", { exact: true })).toBeVisible();
    owner.once("dialog", (dialog) => dialog.accept("最终 文件.bin"));
    await owner.getByRole("button", { name: "重命名", exact: true }).click();
    await expect(owner.getByText("最终 文件.bin", { exact: true })).toBeVisible();
    await test.step("public and protected downloads use current name and matching bytes", async () => {
      await anonymous.goto(publicUrl);
      await expect(anonymous.getByText("最终 文件.bin", { exact: true })).toBeVisible();
      await download(anonymous, "下载文件", "最终 文件.bin");
      await anonymous.goto(protectedUrl);
      await expect(anonymous.getByText("最终 文件.bin", { exact: true })).toHaveCount(0);
      const wrong = code === "999999" ? "888888" : "999999";
      await anonymous.getByLabel("提取码", { exact: true }).fill(wrong);
      await anonymous.getByRole("button", { name: "验证提取码" }).click();
      await expect(anonymous.getByText("请输入正确提取码", { exact: true })).toBeVisible();
      await anonymous.getByLabel("提取码", { exact: true }).fill(code);
      await anonymous.getByRole("button", { name: "验证提取码" }).click();
      await expect(anonymous.getByText("最终 文件.bin", { exact: true })).toBeVisible();
      await anonymous.getByLabel("提取码", { exact: true }).fill(wrong);
      await anonymous.getByRole("button", { name: "下载文件", exact: true }).click();
      await expect(anonymous.getByText("请输入正确提取码", { exact: true })).toBeVisible();
      await anonymous.getByLabel("提取码", { exact: true }).fill(code);
      await download(anonymous, "下载文件", "最终 文件.bin");
    });
    await test.step("snapshot stays unchanged and cancelling one share leaves another active", async () => {
      await owner.getByRole("link", { name: "我的分享", exact: true }).click();
      await expect(owner.getByRole("cell", { name: "重命名 资料.bin", exact: true })).toHaveCount(
        2
      );
      const publicRow = owner
        .getByRole("row")
        .filter({ hasText: "重命名 资料.bin" })
        .filter({ hasText: "公开" });
      owner.once("dialog", (dialog) => dialog.accept());
      await publicRow.getByRole("button", { name: "取消分享", exact: true }).click();
      await expect(publicRow.getByText("已取消", { exact: true })).toBeVisible();
      await anonymous.goto(publicUrl);
      await expect(anonymous.getByText("分享已取消", { exact: true })).toBeVisible();
    });
    await test.step("permanent deletion invalidates protected share and restores quota", async () => {
      await owner.getByRole("link", { name: "个人文件", exact: true }).click();
      await owner.getByRole("button", { name: "归档资料 /", exact: true }).click();
      owner.once("dialog", (dialog) => dialog.accept());
      await owner.getByRole("button", { name: "永久删除", exact: true }).click();
      await expect(owner.getByText("最终 文件.bin", { exact: true })).toHaveCount(0);
      await expect(owner.getByText("已用 0 B", { exact: false })).toBeVisible();
      await owner.getByRole("button", { name: "根目录", exact: true }).click();
      owner.once("dialog", (dialog) => dialog.accept());
      await owner.getByRole("button", { name: "永久删除", exact: true }).click();
      await expect(owner.getByRole("button", { name: "归档资料 /", exact: true })).toHaveCount(0);
      await anonymous.goto(protectedUrl);
      await anonymous.getByLabel("提取码", { exact: true }).fill(code);
      await anonymous.getByRole("button", { name: "验证提取码" }).click();
      await expect(anonymous.getByText("文件已失效", { exact: true })).toBeVisible();
      await expect(anonymous.getByRole("button", { name: "下载文件", exact: true })).toHaveCount(0);
      await owner.getByRole("button", { name: "退出登录" }).click();
      expect(await owner.evaluate(() => localStorage.getItem("course-token"))).toBeNull();
    });
    expect(origins.length > 0 && origins.every((origin) => origin === new URL(base).origin)).toBe(
      true
    );
  } finally {
    await ownerContext.close();
    await otherContext.close();
    await anonymousContext.close();
  }
});
