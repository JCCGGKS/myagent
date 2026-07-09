import { computed, ref } from "vue";
import { defineStore } from "pinia";

import {
  clearToken,
  getAuthMe,
  getToken,
  postLogin,
  postRegister,
  setToken,
  type AuthUser,
} from "@/lib/api";

export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(getToken());
  const user = ref<AuthUser | null>(null);

  const isLoggedIn = computed(() => Boolean(token.value));

  function _setSession(tk: string, usr: AuthUser | null) {
    token.value = tk;
    user.value = usr;
    setToken(tk);
  }

  async function login(username: string, password: string) {
    const res = await postLogin({ username, password });
    _setSession(res.access_token, null);
    // 尝试拉取用户信息（失败不阻断登录态）
    try {
      user.value = await getAuthMe();
    } catch {
      /* ignore */
    }
    return res;
  }

  async function register(username: string, email: string, password: string) {
    const usr = await postRegister({ username, email, password });
    return usr;
  }

  async function fetchMe() {
    if (!token.value) return;
    try {
      user.value = await getAuthMe();
    } catch {
      /* ignore */
    }
  }

  function logout() {
    token.value = null;
    user.value = null;
    clearToken();
  }

  return { token, user, isLoggedIn, login, register, fetchMe, logout };
});
