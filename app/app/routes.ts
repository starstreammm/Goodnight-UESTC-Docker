import {
    type RouteConfig,
    index,
    layout,
    route,
} from "@react-router/dev/routes";

export default [
    index("routes/index.tsx"),
    route("login", "routes/login.tsx"),
    layout("routes/console.tsx", [
        route("admin", "routes/home.tsx"),
        route("user/:username", "routes/user.tsx"),
    ]),
] satisfies RouteConfig;
