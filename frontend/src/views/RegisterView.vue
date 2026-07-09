<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const router = useRouter();

const username = ref("");
const email = ref("");
const password = ref("");
const error = ref("");
const loading = ref(false);

async function onSubmit() {
  error.value = "";
  if (!username.value || !email.value || !password.value) {
    error.value = "请填写所有字段";
    return;
  }
  loading.value = true;
  try {
    await auth.register(username.value, email.value, password.value);
    router.push("/login");
  } catch (e) {
    error.value = e instanceof Error ? e.message : "注册失败";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1>注册</h1>
      <form class="auth-form" @submit.prevent="onSubmit">
        <label>
          <span>用户名</span>
          <input v-model="username" type="text" />
        </label>
        <label>
          <span>邮箱</span>
          <input v-model="email" type="email" />
        </label>
        <label>
          <span>密码（至少 6 位）</span>
          <input v-model="password" type="password" />
        </label>
        <p v-if="error" class="auth-error">{{ error }}</p>
        <button type="submit" :disabled="loading">{{ loading ? "注册中…" : "注册" }}</button>
      </form>
      <div class="auth-links">
        <router-link to="/login">已有账号？登录</router-link>
      </div>
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
  margin-top: 16px;
  font-size: 13px;
}
.auth-links a {
  color: #2563eb;
  text-decoration: none;
}
</style>
