<template>
  <div class="course-shell">
    <header class="course-header">
      <h1>
        云端网盘
        <small>个人文件与分享</small>
      </h1>
      <div
        v-if="session.token"
        class="flex items-center gap-4"
      >
        <span>{{ session.profile?.nickname || "个人账户" }}</span>
        <ElButton @click="logout">退出登录</ElButton>
      </div>
    </header>
    <nav
      v-if="session.token"
      class="flex gap-6 mb-6"
      aria-label="课程导航"
    >
      <RouterLink to="/files">个人文件</RouterLink>
      <RouterLink to="/shares">我的分享</RouterLink>
    </nav>
    <ElAlert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      class="mb-4"
    />
    <RouterView />
  </div>
</template>
<script setup lang="ts">
  import { clearSession, restoreProfile, session } from "./api";
  const router = useRouter();
  const error = ref("");
  watch(
    () => session.token,
    async (token) => {
      error.value = "";
      if (token) {
        try {
          await restoreProfile();
        } catch (failure) {
          error.value = (failure as Error).message;
        }
      }
    },
    { immediate: true }
  );
  function logout() {
    clearSession();
    router.push("/login");
  }
</script>
