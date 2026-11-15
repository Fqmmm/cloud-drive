import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("browse directories with string IDs, create in current directory and refresh quota", async ({
  page,
}) => {
  const id = "9007199254740993";
  const creates: unknown[] = [];
  await page.addInitScript(() => localStorage.setItem("course-token", "test-file-session"));
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    let data: unknown = null;
    if (url.pathname.endsWith("/me")) data = { nickname: "文件用户" };
    if (url.pathname.endsWith("/quota")) data = { totalBytes: 10737418240, usedBytes: 1024 };
    if (url.pathname.endsWith("/files")) {
      const child = url.searchParams.get("parentId") === id;
      data = {
        breadcrumb: [{ id: "0", name: "根目录" }, ...(child ? [{ id, name: "课程资料" }] : [])],
        items: child
          ? []
          : [
              {
                id,
                originalName: "课程资料",
                fileSize: 0,
                isDirectory: true,
                parentId: "0",
                createTime: new Date().toISOString(),
              },
            ],
      };
    }
    if (url.pathname.endsWith("/directories")) creates.push(route.request().postDataJSON());
    await route.fulfill({ json: { code: "00000", msg: "成功", data } });
  });
  await page.goto("/#/files");
  await expect(page.getByText("已用 1.0 KiB / 10.0 GiB", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "课程资料 /", exact: true }).click();
  await expect(
    page.getByRole("navigation", { name: "文件路径" }).getByText("课程资料")
  ).toBeVisible();
  await page.getByLabel("新目录名称").fill("作业");
  await page.getByRole("button", { name: "新建目录", exact: true }).click();
  await expect.poll(() => creates.length).toBe(1);
  expect(creates[0]).toEqual({ name: "作业", parentId: id });
  await page.getByRole("button", { name: "根目录", exact: true }).click();
  await expect(page.getByRole("button", { name: "课程资料 /", exact: true })).toBeVisible();
});

test("upload, rename, binary download and permanent deletion refresh the file list", async ({
  page,
}) => {
  let name = "";
  const content = Buffer.from("中文文件内容\n");
  await page.addInitScript(() => localStorage.setItem("course-token", "test-file-session"));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = null;
    if (path.endsWith("/me")) data = { nickname: "文件用户" };
    if (path.endsWith("/quota"))
      data = { totalBytes: 10737418240, usedBytes: name ? content.length : 0 };
    if (path.endsWith("/files")) {
      if (route.request().method() === "POST") {
        name = "课程 资料.txt";
      }
      data = {
        breadcrumb: [{ id: "0", name: "根目录" }],
        items: name
          ? [
              {
                id: "9007199254740993",
                originalName: name,
                fileSize: content.length,
                isDirectory: false,
                parentId: "0",
                createTime: new Date().toISOString(),
              },
            ]
          : [],
      };
    }
    if (path.endsWith("/rename")) name = route.request().postDataJSON().name;
    if (route.request().method() === "DELETE") name = "";
    if (path.endsWith("/download")) {
      await route.fulfill({
        body: content,
        contentType: "application/octet-stream",
        headers: {
          "Content-Disposition": "attachment; filename*=UTF-8''" + encodeURIComponent(name),
        },
      });
      return;
    }
    await route.fulfill({ json: { code: "00000", msg: "成功", data } });
  });
  await page.goto("/#/files");
  await page
    .getByLabel("选择上传文件")
    .setInputFiles({ name: "课程 资料.txt", mimeType: "text/plain", buffer: content });
  await page.getByRole("button", { name: "上传文件", exact: true }).click();
  await expect(page.getByText("课程 资料.txt", { exact: true })).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept("改名 资料.txt"));
  await page.getByRole("button", { name: "重命名", exact: true }).click();
  await expect(page.getByText("改名 资料.txt", { exact: true })).toBeVisible();
  const saved = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载", exact: true }).click();
  const download = await saved;
  expect(download.suggestedFilename()).toBe("改名 资料.txt");
  expect(await readFile((await download.path())!)).toEqual(content);
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("无法在网盘中恢复");
    await dialog.accept();
  });
  await page.getByRole("button", { name: "永久删除", exact: true }).click();
  await expect(page.getByText("改名 资料.txt", { exact: true })).toHaveCount(0);
});

test("JSON download errors are shown and never saved as files", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("course-token", "test-file-session"));
  let downloads = 0;
  page.on("download", () => downloads++);
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/download")) {
      await route.fulfill({
        status: 503,
        json: { code: "DEPENDENCY_UNAVAILABLE", msg: "存储暂不可用" },
      });
      return;
    }
    const data = path.endsWith("/files")
      ? {
          breadcrumb: [],
          items: [
            {
              id: "1",
              originalName: "样本.txt",
              isDirectory: false,
              fileSize: 10,
              createTime: new Date().toISOString(),
            },
          ],
        }
      : path.endsWith("/quota")
        ? { totalBytes: 1024, usedBytes: 10 }
        : { nickname: "用户" };
    await route.fulfill({ json: { code: "00000", data } });
  });
  await page.goto("/#/files");
  await page.getByRole("button", { name: "下载", exact: true }).click();
  await expect(page.getByText("存储暂不可用", { exact: true })).toBeVisible();
  expect(downloads).toBe(0);
});
