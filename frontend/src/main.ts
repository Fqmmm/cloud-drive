import { createApp } from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import "uno.css";
import CourseApp from "./course/CourseApp.vue";
import { router } from "./course/router";
import "./course/course.css";
createApp(CourseApp).use(ElementPlus).use(router).mount("#app");
