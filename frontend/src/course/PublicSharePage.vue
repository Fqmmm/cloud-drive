<template>
  <ElCard class="login-card">
    <h2>文件分享</h2>
    <ElAlert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb-4"
    />
    <p
      v-if="loading"
      role="status"
    >
      正在读取分享…
    </p>
    <form
      v-if="details?.requiresCode"
      class="grid gap-4 mb-4"
      @submit.prevent="verify"
    >
      <label>
        提取码
        <input
          v-model="code"
          inputmode="numeric"
          autocomplete="off"
          pattern="[0-9]{6}"
          minlength="6"
          maxlength="6"
          required
        />
      </label>
      <ElButton
        native-type="submit"
        :loading="busy"
      >
        验证提取码
      </ElButton>
    </form>
    <section v-if="details?.fileName && details.fileSize !== null">
      <h3>{{ details.fileName }}</h3>
      <p>{{ formatBytes(details.fileSize) }} · {{ expiry(details.expireTime) }}</p>
      <ElButton
        type="primary"
        :loading="busy"
        @click="save"
      >
        下载文件
      </ElButton>
    </section>
    <ElButton
      text
      :disabled="busy || loading"
      @click="load"
    >
      重新读取分享
    </ElButton>
  </ElCard>
</template>
<script setup lang="ts">
  import { api, download, ApiError } from "./api";
  import { formatBytes } from "./files";
  import { expiry, type ShareDetails } from "./shares";
  const route = useRoute();
  const endpoint = computed(() => `/s/${encodeURIComponent(String(route.params.token))}`);
  const details = ref<ShareDetails | null>(null);
  const code = ref("");
  const error = ref("");
  const loading = ref(false);
  const busy = ref(false);
  async function load() {
    loading.value = true;
    error.value = "";
    details.value = null;
    try {
      details.value = await api<ShareDetails>(endpoint.value);
    } catch (failure) {
      error.value = (failure as Error).message;
    } finally {
      loading.value = false;
    }
  }
  async function verify() {
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    try {
      details.value = await api<ShareDetails>(endpoint.value + "/verify", {
        method: "POST",
        body: JSON.stringify({ extractCode: code.value }),
      });
    } catch (failure) {
      error.value = (failure as Error).message;
      if (details.value) details.value.fileName = null;
    } finally {
      busy.value = false;
    }
  }
  async function save() {
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    try {
      await download(endpoint.value + "/download", details.value?.fileName || "分享文件", {
        method: "POST",
        body: JSON.stringify({ extractCode: code.value }),
      });
    } catch (failure) {
      error.value = (failure as Error).message;
      if (failure instanceof ApiError && [404, 410].includes(failure.status)) details.value = null;
    } finally {
      busy.value = false;
    }
  }
  watch(
    () => route.params.token,
    () => {
      code.value = "";
      load();
    },
    { immediate: true }
  );
</script>
