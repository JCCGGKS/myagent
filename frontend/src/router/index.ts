import { createRouter, createWebHistory } from "vue-router";

import { getToken } from "@/lib/api";
import ConsoleView from "@/views/ConsoleView.vue";
import LoginView from "@/views/LoginView.vue";
import RegisterView from "@/views/RegisterView.vue";
import ForgotPasswordView from "@/views/ForgotPasswordView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "console",
      component: ConsoleView,
    },
    {
      path: "/login",
      name: "login",
      component: LoginView,
    },
    {
      path: "/register",
      name: "register",
      component: RegisterView,
    },
    {
      path: "/forgot",
      name: "forgot",
      component: ForgotPasswordView,
    },
  ],
});

const AUTH_ROUTES = new Set(["login", "register", "forgot"]);

router.beforeEach((to) => {
  const hasToken = Boolean(getToken());
  if (!hasToken && !AUTH_ROUTES.has(to.name as string)) {
    return { name: "login" };
  }
  if (hasToken && AUTH_ROUTES.has(to.name as string)) {
    return { name: "console" };
  }
  return true;
});

export default router;
