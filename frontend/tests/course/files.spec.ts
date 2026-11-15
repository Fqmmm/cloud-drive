import { test, expect } from "@playwright/test";

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
