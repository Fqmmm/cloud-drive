import { createRouter, createWebHashHistory } from "vue-router";
import LoginPage from "./LoginPage.vue";
import FilesPage from "./FilesPage.vue";
import SharesPage from "./SharesPage.vue";
import PublicSharePage from "./PublicSharePage.vue";
import { session } from "./api";
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/login", component: LoginPage },
    { path: "/s/:token", component: PublicSharePage },
    { path: "/files", component: FilesPage },
    { path: "/shares", component: SharesPage },
    { path: "/:pathMatch(.*)*", redirect: "/files" },
  ],
});
router.beforeEach((to) => {
  if (to.path !== "/login" && !to.path.startsWith("/s/") && !session.token) return "/login";
});
