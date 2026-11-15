<template>
  <ElCard class="login-card">
    <h2>{{ registering ? "注册个人账户" : "欢迎登录" }}</h2>
    <p class="course-muted">保存课程资料，安全分享每一份文件。</p>
    <form
      class="grid gap-4"
      @submit.prevent="submit"
    >
      <label>
        账户名
        <input
          v-model="form.accountName"
          autocomplete="username"
          required
          minlength="3"
          maxlength="32"
          pattern="[A-Za-z0-9_]{3,32}"
        />
      </label>
      <label>
        密码
        <input
          v-model="form.password"
          type="password"
          :autocomplete="registering ? 'new-password' : 'current-password'"
          required
          minlength="8"
          maxlength="64"
        />
      </label>
      <template v-if="registering">
        <label>
          昵称
          <input
            v-model="form.nickname"
            required
            maxlength="32"
          />
        </label>
        <label>
          邮箱
          <input
            v-model="form.email"
            type="email"
            required
            maxlength="254"
            autocomplete="email"
          />
        </label>
      </template>
      <ElAlert
        v-if="error"
        :title="error"
        type="error"
        :closable="false"
      />
      <ElAlert
        v-if="notice"
        :title="notice"
        type="success"
        :closable="false"
      />
      <ElButton
        type="primary"
        native-type="submit"
        :loading="busy"
      >
        {{ registering ? "注册" : "登录" }}
      </ElButton>
      <ElButton
        text
        :disabled="busy"
        @click="toggle"
      >
        {{ registering ? "已有账户，去登录" : "创建个人账户" }}
      </ElButton>
    </form>
    <p class="course-muted">账户名为 3–32 位英文字母、数字或下划线；密码 8–64 字符。</p>
  </ElCard>
</template>
<script setup lang="ts">
  import { api, session } from "./api";
  const router = useRouter();
  const registering = ref(false);
  const busy = ref(false);
  const error = ref("");
  const notice = ref("");
  const form = reactive({ accountName: "", password: "", nickname: "", email: "" });
  function toggle() {
    registering.value = !registering.value;
    form.password = "";
    error.value = "";
    notice.value = "";
  }
  async function submit() {
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    notice.value = "";
    try {
      if (registering.value) {
        await api("/auth/register", {
          method: "POST",
          body: JSON.stringify({ ...form, accountType: "personal" }),
        });
        registering.value = false;
        form.password = "";
        notice.value = "注册成功，请登录";
      } else {
        const result = await api<{ token: string }>("/auth/login", {
          method: "POST",
          body: JSON.stringify({ accountName: form.accountName, password: form.password }),
        });
        session.token = result.token;
        localStorage.setItem("course-token", result.token);
        form.password = "";
        await router.push("/files");
      }
    } catch (failure) {
      error.value = (failure as Error).message;
    } finally {
      busy.value = false;
    }
  }
</script>
