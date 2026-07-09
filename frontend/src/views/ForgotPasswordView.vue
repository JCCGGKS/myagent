<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { postForgotPassword, postResetPassword } from "@/lib/api";

const route = useRoute();
const router = useRouter();

const token = ref<string>((route.query.token as string) || "");
const email = ref("");
const newPassword = ref("");
const message = ref("");
const error = ref("");
const loading = ref(false);

const needsReset = ref(Boolean(token.value));

async function requestLink() {
  error.value = "";
  message.value = "";
  if (!email.value) {
    error.value = "请输入邮箱";
    return;
  }
  loading.value = true;
  try {
    const res = await postForgotPassword({ email: email.value });
    message.value = res.detail || "若账号存在，重置链接已发送";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "请求失败";
  } finally {
    loading.value = false;
  }
}

async function doReset() {
  error.value = "";
  message.value = "";
  if (!token.value || !newPassword.value) {
    error.value = "请填写重置凭证与新密码";
    return;
  }
  loading.value = true;
  try {
    const res = await postResetPassword({ token: token.value, new_password: newPassword.value });
    message.value = res.detail || "密码已重置";
    setTimeout(() => router.push("/login"), 1200);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "重置失败";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1>找回密码</h1>

      <form v-if="!needsReset" class="auth-form" @submit.prevent="requestLink">
        <label>
          <span>邮箱</span>
          <input v-model="email" type="email" />
        </label>
        <p v-if="error" class="auth-error">{{ error }}</p>
        <p v-if="message" class="auth-ok">{{ message }}</p>
        <button type="submit" :disabled="loading">{{ loading ? "提交中…" : "发送重置链接" }}</button>
        <div class="auth-links">
          <router-link to="/login">返回登录</router-link>
        </div>
      </form>

      <form v-else class="auth-form" @submit.prevent="doReset">
        <label>
          <span>新密码（至少 6 位）</span>
          <input v-model="newPassword" type="password" />
        </label>
        <p v-if="error" class="auth-error">{{ error }}</p>
        <p v-if="message" class="auth-ok">{{ message }}</p>
        <button type="submit" :disabled="loading">{{ loading ? "重置中…" : "重置密码" }}</button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: #f3f4f6;
}
.auth-card {
  width: 360px;
  background: #fff;
  border-radius: 14px;
  padding: 28px 26px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
}
.auth-card h1 {
  margin: 0 0 18px;
  font-size: 22px;
}
.auth-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.auth-form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: #374151;
}
.auth-form input {
  padding: 9px 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
}
.auth-form input:focus {
  outline: none;
  border-color: #2563eb;
}
.auth-error {
  margin: 0;
  color: #dc2626;
  font-size: 13px;
}
.auth-ok {
  margin: 0;
  color: #16a34a;
  font-size: 13px;
}
.auth-form button {
  margin-top: 4px;
  padding: 10px;
  border: none;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
}
.auth-form button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.auth-links {
  font-size: 13px;
}
.auth-links a {
  color: #2563eb;
  text-decoration: none;
}
</style>
