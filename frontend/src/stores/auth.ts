import { computed, ref } from "vue";
import { defineStore } from "pinia";

import {
  clearToken,
  getToken,
  postLogin,
  postRegister,
  setToken,
  type AuthUser,
} from "@/lib/api";

const USER_KEY = "myagent_user";

function loadUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(getToken());
  const user = ref<AuthUser | null>(loadUser());

  const isLoggedIn = computed(() => Boolean(token.value));

  function _setSession(tk: string, usr: AuthUser) {
    token.value = tk;
    user.value = usr;
    setToken(tk);
    localStorage.setItem(USER_KEY, JSON.stringify(usr));
  }

  async function login(username: string, password: string) {
    const res = await postLogin({ username, password });
    _setSession(res.access_token, res.user);
    return res;
  }

  async function register(username: string, email: string, password: string) {
    const usr = await postRegister({ username, email, password });
    return usr;
  }

  function logout() {
    token.value = null;
    user.value = null;
    clearToken();
    localStorage.removeItem(USER_KEY);
  }

  return { token, user, isLoggedIn, login, register, logout };
});
