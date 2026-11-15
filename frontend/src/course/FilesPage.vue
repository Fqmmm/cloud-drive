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
    </ElTable>
  </ElCard>
</template>
<script setup lang="ts">
  import { api } from "./api";
  import { formatBytes, type Listing, type Quota } from "./files";
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
  onMounted(() => load("0"));
</script>
