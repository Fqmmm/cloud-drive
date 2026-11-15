<template>
  <ElCard>
    <div class="flex flex-wrap items-center justify-between gap-4 mb-4">
      <h2>个人文件</h2>
      <ElButton
        :loading="loading"
        @click="load(parentId)"
      >
        刷新
      </ElButton>
    </div>
    <p v-if="quota">
      已用 {{ formatBytes(quota.usedBytes) }} / {{ formatBytes(quota.totalBytes) }} · 可用
      {{ formatBytes(quota.totalBytes - quota.usedBytes) }}
    </p>
    <ElProgress
      v-if="quota"
      :percentage="Math.min(100, quota.totalBytes ? (quota.usedBytes / quota.totalBytes) * 100 : 0)"
      :show-text="false"
    />
    <nav
      class="flex flex-wrap gap-2 my-4"
      aria-label="文件路径"
    >
      <ElButton
        v-for="crumb in listing.breadcrumb"
        :key="crumb.id"
        text
        @click="load(crumb.id)"
      >
        {{ crumb.name }}
      </ElButton>
    </nav>
    <form
      class="flex gap-2 mb-4"
      @submit.prevent="createDirectory"
    >
      <input
        v-model="directoryName"
        aria-label="新目录名称"
        maxlength="255"
        placeholder="新目录名称"
        required
      />
      <ElButton
        native-type="submit"
        :loading="creating"
      >
        新建目录
      </ElButton>
    </form>
    <ElAlert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb-4"
    />
    <form
      class="flex flex-wrap items-center gap-2 mb-4"
      @submit.prevent="upload"
    >
      <input
        type="file"
        aria-label="选择上传文件"
        :disabled="uploading"
        @change="selectFile"
      />
      <ElButton
        type="primary"
        native-type="submit"
        :loading="uploading"
        :disabled="!selectedFile"
      >
        上传文件
      </ElButton>
      <span class="course-muted">
        单文件上限 {{ formatBytes(maxFileBytes) }}，剩余空间以服务端为准
      </span>
      <span
        v-if="uploading"
        role="status"
      >
        正在上传，请稍候…
      </span>
    </form>
    <ElTable
      :data="listing.items"
      empty-text="当前目录为空，可以新建目录或上传文件"
    >
      <ElTableColumn
        label="名称"
        min-width="200"
      >
        <template #default="{ row }">
          <ElButton
            v-if="row.isDirectory"
            text
            type="primary"
            @click="load(row.id)"
          >
            {{ row.originalName }} /
          </ElButton>
          <span v-else>{{ row.originalName }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="类型">
        <template #default="{ row }">
          {{ row.isDirectory ? "目录" : row.mimeType || "文件" }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="大小">
        <template #default="{ row }">
          {{ row.isDirectory ? "—" : formatBytes(row.fileSize) }}
        </template>
      </ElTableColumn>
      <ElTableColumn
        label="创建时间"
        min-width="170"
      >
        <template #default="{ row }">{{ new Date(row.createTime).toLocaleString() }}</template>
      </ElTableColumn>
      <ElTableColumn
        label="操作"
        min-width="240"
      >
        <template #default="{ row }">
          <ElButton
            v-if="!row.isDirectory"
            text
            :disabled="working"
            @click="downloadFile(row as FileItem)"
          >
            下载
          </ElButton>
          <ElButton
            v-if="!row.isDirectory"
            text
            @click="share(row as FileItem)"
          >
            分享
          </ElButton>
          <ElButton
            text
            :disabled="working"
            @click="rename(row as FileItem)"
          >
            重命名
          </ElButton>
          <ElButton
            text
            type="danger"
            :disabled="working"
            @click="remove(row as FileItem)"
          >
            永久删除
          </ElButton>
        </template>
      </ElTableColumn>
    </ElTable>
  </ElCard>
</template>
<script setup lang="ts">
  import { api, download } from "./api";
  import { formatBytes, type Listing, type Quota, type FileItem } from "./files";
  const router = useRouter();
  function share(item: FileItem) {
    router.push({ path: "/shares", query: { fileId: item.id, fileName: item.originalName } });
  }
  const parentId = ref("0");
  const listing = ref<Listing>({ breadcrumb: [], items: [] });
  const quota = ref<Quota | null>(null);
  const loading = ref(false);
  const creating = ref(false);
  const directoryName = ref("");
  const error = ref("");
  async function load(id: string) {
    if (loading.value) return;
    loading.value = true;
    error.value = "";
    try {
      const [next, space] = await Promise.all([
        api<Listing>(`/files?parentId=${encodeURIComponent(id)}`),
        api<Quota>("/quota"),
      ]);
      listing.value = next;
      quota.value = space;
      parentId.value = id;
    } catch (failure) {
      error.value = (failure as Error).message;
    } finally {
      loading.value = false;
    }
  }
  async function createDirectory() {
    if (creating.value) return;
    creating.value = true;
    error.value = "";
    try {
      await api("/directories", {
        method: "POST",
        body: JSON.stringify({ name: directoryName.value, parentId: parentId.value }),
      });
      directoryName.value = "";
      await load(parentId.value);
    } catch (failure) {
      error.value = (failure as Error).message;
    } finally {
      creating.value = false;
    }
  }
  const uploading = ref(false);
  const working = ref(false);
  const selectedFile = ref<File | null>(null);
  const maxFileBytes = Number(import.meta.env.VITE_MAX_FILE_BYTES || 104857600);
  function selectFile(event: Event) {
    selectedFile.value = (event.target as HTMLInputElement).files?.[0] || null;
  }
  async function upload() {
    if (!selectedFile.value || uploading.value) return;
    if (selectedFile.value.size > maxFileBytes) {
      error.value = "文件超过单文件大小限制";
      return;
    }
    uploading.value = true;
    error.value = "";
    try {
      const form = new FormData();
      form.set("file", selectedFile.value);
      await api(`/files?parentId=${encodeURIComponent(parentId.value)}`, {
        method: "POST",
        body: form,
      });
      await load(parentId.value);
    } catch (failure) {
      error.value = (failure as Error).message;
    } finally {
      uploading.value = false;
    }
  }
  async function downloadFile(item: FileItem) {
    if (working.value) return;
    working.value = true;
    error.value = "";
    try {
      await download(`/files/${item.id}/download`, item.originalName);
    } catch (failure) {
      error.value = (failure as Error).message;
    } finally {
      working.value = false;
    }
  }
  async function rename(item: FileItem) {
    const name = window.prompt("输入新的名称", item.originalName);
    if (name === null || working.value) return;
    working.value = true;
    error.value = "";
    try {
      await api(`/${item.isDirectory ? "directories" : "files"}/${item.id}/rename`, {
        method: "PUT",
        body: JSON.stringify({ name }),
      });
      await load(parentId.value);
    } catch (failure) {
      error.value = (failure as Error).message;
    } finally {
      working.value = false;
    }
  }
  async function remove(item: FileItem) {
    if (
      working.value ||
      !window.confirm(
        `永久删除“${item.originalName}”，无法在网盘中恢复。${item.isDirectory ? "目录必须为空。" : "原分享也将失效。"}`
      )
    )
      return;
    working.value = true;
    error.value = "";
    try {
      await api(`/${item.isDirectory ? "directories" : "files"}/${item.id}`, { method: "DELETE" });
      await load(parentId.value);
    } catch (failure) {
      error.value = (failure as Error).message;
    } finally {
      working.value = false;
    }
  }
  onMounted(() => load("0"));
</script>
