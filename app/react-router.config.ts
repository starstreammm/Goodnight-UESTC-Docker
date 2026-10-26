import type { Config } from "@react-router/dev/config";

export default {
    ssr: false,
    prerender: ["/", "/login", "/admin"],
} satisfies Config;
