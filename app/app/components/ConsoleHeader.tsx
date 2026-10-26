import type { ReactNode } from "react";
import { Box, Button, Stack, Typography } from "@mui/material";
import { Bedtime, LogoutOutlined, Translate } from "@mui/icons-material";
import { useLanguage } from "../i18n";

export default function ConsoleHeader({
    children,
    complete = 0,
    total,
    status,
    busy,
    onLogout,
}: {
    children?: ReactNode;
    status?: ReactNode;
    complete?: number;
    total?: number;
    busy: boolean;
    onLogout: () => void;
}) {
    const { t, language, toggle } = useLanguage();
    return (
        <Stack
            component="header"
            direction="row"
            alignItems="center"
            sx={{
                gap: 2,
                flexWrap: "wrap",
                mb: 2,
                width: "100%",
                flexShrink: 0,
            }}
        >
            <Stack
                direction="row"
                spacing={1.5}
                alignItems="center"
                sx={{ flex: 1 }}
            >
                <Box className="brand">
                    <Bedtime />
                </Box>
                <Box>
                    <Typography fontWeight={750}>GoodNight</Typography>
                    <Typography variant="caption" color="text.secondary">
                        {t("UESTC · NIGHT CHECK-IN", "电子科技大学 · 晚安签到")}
                    </Typography>
                </Box>
            </Stack>
            {status}
            {total !== undefined && (
                <Stack
                    direction="row"
                    spacing={1.5}
                    alignItems="center"
                    sx={{
                        order: { xs: 1, sm: 0 },
                        width: { xs: "100%", sm: "auto" },
                    }}
                >
                    <Typography variant="h5" sx={{ whiteSpace: "nowrap" }}>
                        {complete}{" "}
                        <Box component="span" sx={{ color: "text.secondary" }}>
                            / {total}
                        </Box>
                    </Typography>
                    <Box>
                        <Typography variant="body2" fontWeight={600}>
                            {t("TONIGHT", "今晚")}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                            {t("Confirmed school records", "学校已确认的记录")}
                        </Typography>
                    </Box>
                </Stack>
            )}
            {children}
            <Button startIcon={<Translate />} onClick={toggle}>
                {language === "en" ? "中文" : "English"}
            </Button>
            <Button
                startIcon={<LogoutOutlined />}
                disabled={busy}
                onClick={onLogout}
            >
                {t("Log out", "退出登录")}
            </Button>
        </Stack>
    );
}
