import { useEffect, useState } from "react";
import { Box, LinearProgress, Stack, Typography } from "@mui/material";
import { useLanguage } from "../i18n";

export default function ExpiryProgress({
    title,
    expiresAt,
    startsAt,
}: {
    title: string;
    expiresAt?: number | null;
    startsAt?: number | null;
}) {
    const { t, language } = useLanguage();
    const [now, setNow] = useState(Date.now() / 1000);
    useEffect(() => {
        const timer = setInterval(() => setNow(Date.now() / 1000), 30000);
        return () => clearInterval(timer);
    }, []);
    const known = typeof expiresAt === "number" && Number.isFinite(expiresAt);
    const remaining = known ? Math.max(0, expiresAt - now) : 0;
    const duration =
        known && typeof startsAt === "number" ? expiresAt - startsAt : 0;
    const percent =
        duration > 0
            ? Math.max(0, Math.min(100, (remaining / duration) * 100))
            : 0;
    const totalMinutes = Math.ceil(remaining / 60);
    const days = Math.floor(totalMinutes / 1440),
        hours = Math.floor((totalMinutes % 1440) / 60),
        minutes = totalMinutes % 60;
    const left = !known
        ? t("Not available", "暂无信息")
        : remaining === 0
          ? t("Expired", "已过期")
          : days
            ? t(`${days}d ${hours}h left`, `剩余 ${days} 天 ${hours} 小时`)
            : hours
              ? t(
                    `${hours}h ${minutes}m left`,
                    `剩余 ${hours} 小时 ${minutes} 分钟`,
                )
              : t(`${minutes}m left`, `剩余 ${minutes} 分钟`);
    return (
        <Box>
            <Stack
                direction="row"
                justifyContent="space-between"
                spacing={1}
                mb={0.75}
            >
                <Typography variant="body2" fontWeight={600}>
                    {title}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                    {left}
                </Typography>
            </Stack>
            <LinearProgress
                variant="determinate"
                value={percent}
                color={
                    !known
                        ? "inherit"
                        : remaining === 0
                          ? "error"
                          : percent <= 20
                            ? "warning"
                            : "primary"
                }
                aria-label={title}
                aria-valuetext={left}
                sx={{
                    height: 6,
                    borderRadius: 3,
                    "& .MuiLinearProgress-bar": { borderRadius: 3 },
                }}
            />
            {known && (
                <Typography
                    variant="caption"
                    color="text.secondary"
                    display="block"
                    mt={0.5}
                >
                    {new Date(expiresAt * 1000).toLocaleString(
                        language === "zh" ? "zh-CN" : "en-GB",
                        { timeZone: "Asia/Shanghai" },
                    )}
                </Typography>
            )}
        </Box>
    );
}
