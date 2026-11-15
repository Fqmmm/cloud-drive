<template>
  <ElCard>
    <h2>我的分享</h2>
    <form
      v-if="fileId"
      class="grid gap-4 mb-6"
      @submit.prevent="create"
    >
      <h3>为“{{ selectedName }}”创建分享</h3>
      <label>
        访问方式
        <select v-model.number="accessType">
          <option :value="0">公开访问</option>
          <option :value="1">提取码访问</option>
        </select>
      </label>
      <label>
        有效期
        <select v-model="days">
          <option value="1">1 天</option>
          <option value="7">7 天</option>
          <option value="30">30 天</option>
          <option value="">永久</option>
        </select>
      </label>
      <ElButton
        type="primary"
        native-type="submit"
        :loading="creating"
      >
        创建分享
      </ElButton>
    </form>
    <p v-else><RouterLink to="/files">到个人文件选择一个文件创建分享</RouterLink></p>
    <ElAlert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb-4"
    />
    <section
      v-if="created"
      class="grid gap-2 mb-6"
      aria-label="新分享结果"
    >
      <label>
        分享地址
        <input
          :value="created.shareUrl"
          readonly
        />
      </label>
      <p v-if="created.extractCode">
        提取码：
        <strong>{{ created.extractCode }}</strong>
        （仅此时显示，请保存；遗失后需重建分享）
      </p>
      <ElButton @click="copy(created.shareUrl, created.extractCode)">复制链接及提取码</ElButton>
    </section>
    <p
      v-if="notice"
      role="status"
    >
      {{ notice }}
    </p>
    <p class="course-muted">“未取消”表示链接尚未取消或到期；源文件状态在访问时核验。</p>
    <ElButton
      :loading="loading"
      @click="load"
    >
      刷新分享
    </ElButton>
    <ElTable
      :data="entries"
      empty-text="还没有分享记录"
    >
      <ElTableColumn
        prop="fileName"
        label="创建时文件名"
        min-width="180"
      />
      <ElTableColumn label="访问方式">
        <template #default="{ row }">{{ row.accessType === 1 ? "提取码" : "公开" }}</template>
      </ElTableColumn>
      <ElTableColumn
        label="创建时间"
        min-width="170"
      >
        <template #default="{ row }">{{ new Date(row.createTime).toLocaleString() }}</template>
      </ElTableColumn>
      <ElTableColumn
        label="有效期"
        min-width="170"
      >
        <template #default="{ row }">{{ expiry(row.expireTime) }}</template>
      </ElTableColumn>
      <ElTableColumn label="状态">
        <template #default="{ row }">{{ labels[row.status as ShareEntry["status"]] }}</template>
      </ElTableColumn>
      <ElTableColumn
        label="分享地址"
        min-width="180"
      >
        <template #default="{ row }">
          <a
            :href="row.shareUrl"
            target="_blank"
            rel="noreferrer"
          >
            打开分享
          </a>
          <ElButton
            text
            @click="copy(row.shareUrl)"
          >
            复制链接
          </ElButton>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作">
        <template #default="{ row }">
          <ElButton
            text
            type="danger"
            :disabled="row.status === 'CANCELLED' || cancelling"
            @click="cancel(row as ShareEntry)"
          >
            取消分享
          </ElButton>
        </template>
      </ElTableColumn>
    </ElTable>
  </ElCard>
</template>
<script setup lang="ts">
  import { api } from "./api";
  import { expiry, type ShareCreated, type ShareEntry } from "./shares";
  const route = useRoute();
  const fileId = computed(() => (typeof route.query.fileId === "string" ? route.query.fileId : ""));
  const selectedName = computed(() => route.query.fileName || "所选文件");
  const accessType = ref(0);
  const days = ref("7");
  const entries = ref<ShareEntry[]>([]);
  const created = ref<ShareCreated | null>(null);
  const creating = ref(false);
  const loading = ref(false);
  const cancelling = ref(false);
  const error = ref("");
  const notice = ref("");
  const labels = { ACTIVE: "未取消", CANCELLED: "已取消", EXPIRED: "已过期" };
  async function load() {
    loading.value = true;
    try {
      entries.value = await api<ShareEntry[]>("/shares");
    } catch (failure) {
      error.value = (failure as Error).message;
    } finally {
      loading.value = false;
    }
  }
  async function create() {
    if (creating.value) return;
    creating.value = true;
    error.value = "";
    created.value = null;
    try {
      created.value = await api<ShareCreated>("/shares", {
        method: "POST",
        body: JSON.stringify({
          fileId: fileId.value,
          accessType: accessType.value,
          expireDays: days.value ? Number(days.value) : null,
        }),
      });
      await load();
    } catch (failure) {
      error.value = (failure as Error).message;
    } finally {
      creating.value = false;
    }
  }
  async function copy(url: string, code?: string | null) {
    try {
      await navigator.clipboard.writeText(url + (code ? ` 提取码：${code}` : ""));
      notice.value = "已复制";
    } catch {
      notice.value = "无法自动复制，请选中分享地址手工复制";
    }
  }
  async function cancel(entry: ShareEntry) {
    if (cancelling.value || !window.confirm(`取消“${entry.fileName}”的分享？后续访问将失效。`))
      return;
    cancelling.value = true;
    error.value = "";
    try {
      await api(`/shares/${entry.id}`, { method: "DELETE" });
      await load();
    } catch (failure) {
      error.value = (failure as Error).message;
    } finally {
      cancelling.value = false;
    }
  }
  onMounted(load);
</script>
