import { Box, Divider, Stack, Typography } from "@mui/material";
import { useLanguage } from "../i18n";

export type SchoolSchedule = {
    date?: string;
    response?: { data?: Record<string, unknown> | null };
};

export default function SchoolDetails({
    detail,
    schedule,
    locationName,
    showSchedule = true,
}: {
    detail: Record<string, unknown>;
    schedule?: SchoolSchedule;
    locationName?: string | null;
    showSchedule?: boolean;
}) {
    const { t } = useLanguage();
    const names: Record<string, string> = {
        realName: t("Real name", "姓名"),
        userName: t("Name", "姓名"),
        studentName: t("Name", "姓名"),
        studentId: t("Student ID", "学号"),
        sn: t("Student number", "学号"),
        name: t("Name", "姓名"),
        phone: t("Phone", "电话"),
        genderName: t("Gender", "性别"),
        organizationName: t("College", "学院"),
        className: t("Class", "班级"),
        instructorName: t("Instructor name", "辅导员姓名"),
        instructorPhone: t("Instructor phone", "辅导员电话"),
        gradeName: t("Grade", "年级"),
        专业: t("Major", "专业"),
        majorName: t("Major", "专业"),
    };

    const hidden = new Set([
        "gendercode",
        "gradecode",
        "organizationsn",
        "usertype",
        "collegesn",
        "majorsn",
        "collegename",
        "学院",
        "classsn",
        "instructorsn",
    ]);

    return (
        <Stack spacing={0.75}>
            {Object.entries(detail)
                .filter(
                    ([key, value]) =>
                        value !== null && !hidden.has(key.toLowerCase()),
                )
                .map(([key, value]) => (
                    <Box
                        key={key}
                        sx={{
                            display: "grid",
                            gridTemplateColumns:
                                "minmax(90px, 1fr) minmax(0, 2fr)",
                            gap: 1,
                            py: 0.25,
                            alignItems: "baseline",
                        }}
                    >
                        <Typography variant="caption" color="text.secondary">
                            {names[key] || key}
                        </Typography>
                        <Typography
                            variant="body2"
                            sx={{ overflowWrap: "anywhere" }}
                        >
                            {typeof value === "object"
                                ? JSON.stringify(value)
                                : String(value)}
                        </Typography>
                    </Box>
                ))}
            {(showSchedule || locationName) && <Divider />}
            {showSchedule && <SchoolCheckinSchedule schedule={schedule} />}
            {locationName && (
                <Box>
                    <Typography variant="subtitle2">
                        {t("Check-in location", "签到位置")}
                    </Typography>
                    <Typography>{locationName}</Typography>
                </Box>
            )}
        </Stack>
    );
}

export function SchoolCheckinSchedule({ schedule }: { schedule?: SchoolSchedule }) {
    const { t } = useLanguage();
    const data = schedule?.response?.data;

    function time(value: unknown) {
        if (typeof value !== "number" || !Number.isFinite(value) || value < 0)
            return t("Not available", "暂无信息");
        const minutes = Math.round(value),
            days = Math.floor(minutes / 1440);
        return `${String(Math.floor(minutes / 60) % 24).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}${days ? ` (+${days} ${t("day", "天")})` : ""}`;
    }

    return (
        <Box>
            <Typography variant="subtitle2">
                {t("School check-in schedule", "学校签到安排")}
            </Typography>
            <Typography>
                {data
                    ? `${time(data.studentCheckinStartOffsetMinute)} – ${time(data.studentCheckinEndOffsetMinute)}`
                    : t(
                        "No effective schedule returned by the school.",
                        "学校尚未返回有效签到安排。",
                    )}
            </Typography>
            <Typography variant="caption" color="text.secondary">
                {schedule?.date} · Asia/Shanghai
            </Typography>
        </Box>
    );
}
