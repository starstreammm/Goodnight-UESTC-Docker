import { useRef, useState } from "react";
import {
    Alert,
    Box,
    Slider,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import { api } from "../api";
import { errorText, useLanguage } from "../i18n";

export type AccountSettings = {
    id: number;
    alias: string;
    owner_role?: "admin" | "user";
    save_password: boolean;
    checkin_time: string | null;
    school_window: string | null;
};

function minutes(time: string) {
    const [hour, minute] = time.split(":").map(Number);
    return hour * 60 + minute;
}

function time(value: number) {
    return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

function initialRange(account: AccountSettings): number[] | null {
    if (!account.school_window) return null;
    const available = account.school_window.split("_").map(minutes);
    if (!account.checkin_time) return available;
    const saved = account.checkin_time.split("_").map(minutes);
    const start = Math.max(available[0], saved[0]),
        end = Math.min(available[1], saved[1]);
    return start < end ? [start, end] : available;
}

export default function AccountSettingsForm({
    account,
    formId,
    disabled = false,
    autoSave = false,
    onSuccess,
    onSaved,
    onBusyChange,
}: {
    account: AccountSettings;
    formId: string;
    disabled?: boolean;
    autoSave?: boolean;
    onSuccess: () => Promise<void>;
    onSaved?: () => void;
    onBusyChange: (busy: boolean) => void;
}) {
    const { t, language } = useLanguage();
    const [alias, setAlias] = useState(account.alias);
    const [range, setRange] = useState(() => initialRange(account));
    const latestRange = useRef(range);
    const [rangeChanged, setRangeChanged] = useState(false);
    const [saving, setSaving] = useState(false),
        [error, setError] = useState("");
    const busy = saving || disabled;
    const available = account.school_window?.split("_").map(minutes);
    const adjusted =
        !!account.checkin_time &&
        !!range &&
        initialRange(account)?.map(time).join("_") !== account.checkin_time;

    async function action(fn: () => Promise<void>) {
        setSaving(true);
        onBusyChange(true);
        setError("");
        try {
            await fn();
        } catch (e) {
            setError(errorText(e, language));
            if (autoSave) {
                setRange(initialRange(account));
                latestRange.current = initialRange(account);
                setAlias(account.alias);
            }
        } finally {
            setSaving(false);
            onBusyChange(false);
        }
    }

    function save(nextRange = range) {
        if (busy) return;
        void action(async () => {
            await api(`/accounts/${account.id}`, "PATCH", {
                ...(account.owner_role === "user" ? {} : { alias }),
                ...(nextRange && (autoSave || rangeChanged || adjusted)
                    ? { checkin_time: nextRange.map(time).join("_") }
                    : {}),
            });
            setRangeChanged(false);
            await onSuccess();
            onSaved?.();
        });
    }

    return (
        <Box
            component="form"
            id={formId}
            onSubmit={(e) => {
                e.preventDefault();
                if (busy) return;
                save();
            }}
        >
            <Stack spacing={autoSave ? 1 : 2} mt={autoSave ? 0 : 1}>
                {error && <Alert severity="error">{error}</Alert>}
                {autoSave && saving && (
                    <Typography role="status" variant="caption" color="text.secondary">
                        {t("Saving…", "正在保存…")}
                    </Typography>
                )}
                {account.owner_role !== "user" && (
                    <TextField
                        label={t("Alias", "别名")}
                        required
                        value={alias}
                        disabled={busy}
                        inputProps={{ maxLength: 80 }}
                        onChange={(e) => setAlias(e.target.value)}
                        onBlur={(e) => {
                            if (autoSave && alias !== account.alias && e.target.checkValidity()) save();
                        }}
                    />
                )}
                <Box>
                    <Typography id="checkin-range-label" variant="subtitle2">
                        {t("Random check-in range", "随机签到时段")}
                    </Typography>
                    {available && range ? (
                        <>
                            <Stack
                                direction="row"
                                justifyContent="space-between"
                                alignItems="baseline"
                                sx={{ gap: 1, flexWrap: "wrap", mt: 0.5 }}
                            >
                                <Typography
                                    variant="h6"
                                    sx={{
                                        fontVariantNumeric: "tabular-nums",
                                    }}
                                >
                                    {time(range[0])} – {time(range[1])}
                                </Typography>
                                <Typography
                                    variant="caption"
                                    color="text.secondary"
                                >
                                    {t("School accepts", "学校允许")}{" "}
                                    {time(available[0])} –{" "}
                                    {time(available[1] + 5)}
                                </Typography>
                            </Stack>
                            <Box sx={{ px: 1.25, pt: 1 }}>
                                <Slider
                                    value={range}
                                    min={available[0]}
                                    max={available[1]}
                                    step={1}
                                    disableSwap
                                    disabled={busy}
                                    getAriaLabel={(index) =>
                                        index === 0
                                            ? t(
                                                "Earliest check-in time",
                                                "最早签到时间",
                                            )
                                            : t(
                                                "Latest check-in time",
                                                "最晚签到时间",
                                            )
                                    }
                                    getAriaValueText={time}
                                    valueLabelFormat={time}
                                    valueLabelDisplay="auto"
                                    onChangeCommitted={() => {
                                        if (autoSave && latestRange.current?.map(time).join("_") !== account.checkin_time) {
                                            save(latestRange.current);
                                        }
                                    }}
                                    onChange={(_, value, thumb) => {
                                        const next = value as number[];
                                        setRangeChanged(true);
                                        const clamped = thumb === 0
                                            ? [Math.min(next[0], range[1] - 1), range[1]]
                                            : [range[0], Math.max(next[1], range[0] + 1)];
                                        latestRange.current = clamped;
                                        setRange(clamped);
                                    }}
                                />
                                <Stack
                                    direction="row"
                                    justifyContent="space-between"
                                    sx={{ mt: -0.5 }}
                                >
                                    <Typography
                                        variant="caption"
                                        color="text.secondary"
                                    >
                                        {time(available[0])}
                                    </Typography>
                                    <Typography
                                        variant="caption"
                                        color="text.secondary"
                                    >
                                        {time(available[1])}
                                    </Typography>
                                </Stack>
                            </Box>
                            <Typography
                                variant="body2"
                                color="text.secondary"
                                mt={1.5}
                            >
                                {autoSave
                                    ? t(
                                        "Randomized daily. Changes automatically update pending check-ins.",
                                        "每日随机安排签到，更改将自动保存并更新待执行计划。",
                                    )
                                    : t(
                                        "A time is picked randomly within this range each day. Saving updates pending check-ins.",
                                        "每天在此时段内随机安排签到。保存后将更新尚未执行的签到计划。",
                                    )}
                            </Typography>
                            <Typography
                                variant="caption"
                                color="text.secondary"
                                display="block"
                                mt={0.5}
                            >
                                {t(
                                    "Shanghai time. The school window’s final 5 minutes are reserved to avoid late submissions.",
                                    "北京时间。预留学校签到时段的最后 5 分钟，避免超时提交。",
                                )}
                            </Typography>
                            {adjusted && (
                                <Alert severity="info" sx={{ mt: 1.5 }}>
                                    {autoSave
                                        ? t(
                                            "Your saved range no longer fits today’s school hours. Adjust the slider to save a new range.",
                                            "已保存的时段不完全符合今日学校安排。请调整滑块以保存新时段。",
                                        )
                                        : t(
                                            "Your saved range no longer fits today’s school hours. Save to use the range shown above.",
                                            "已保存的时段不完全符合今日学校安排。保存后将使用上方显示的时段。",
                                        )}
                                </Alert>
                            )}
                        </>
                    ) : (
                        <Alert severity="info" sx={{ mt: 1 }}>
                            {t(
                                "Today’s school hours are not available yet. Refresh after the school schedule updates to choose a range.",
                                "暂未获取今日学校签到时段。学校安排更新后，请刷新页面选择时段。",
                            )}
                            {account.checkin_time && (
                                <Typography variant="body2" mt={0.5}>
                                    {t("Saved range", "已保存时段")}:{" "}
                                    {account.checkin_time.replace("_", " – ")}
                                </Typography>
                            )}
                        </Alert>
                    )}
                </Box>
            </Stack>
        </Box>
    );
}
