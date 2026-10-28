import { useState } from "react";
import {
    Alert,
    Button,
    FormControlLabel,
    Link,
    Stack,
    Switch,
    TextField,
    Typography,
} from "@mui/material";
import { useAuth, type Preferences } from "../auth";
import { errorText, useLanguage } from "../i18n";

export default function BarkSettings({
    introduction = false,
    onBusyChange,
}: {
    introduction?: boolean;
    onBusyChange?: (busy: boolean) => void;
}) {
    const { user, updatePreferences } = useAuth();
    const { t, language } = useLanguage();
    const [key, setKey] = useState("");
    const [enabled, setEnabled] = useState(introduction || !!user?.bark_enabled);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [saved, setSaved] = useState(false);
    const canSave = !busy && (!enabled || !!key.trim() || !!user?.bark_configured);

    async function save(remove = false) {
        setBusy(true);
        onBusyChange?.(true);
        setError("");
        setSaved(false);
        try {
            const preferences: Preferences = {
                bark_enabled: remove ? false : enabled,
                bark_prompt_dismissed: true,
            };
            if (remove || key.trim()) {
                preferences.bark_key = remove ? "" : key.trim();
            }
            await updatePreferences(preferences);
            setKey("");
            if (remove) setEnabled(false);
            setSaved(true);
        } catch (error) {
            setError(errorText(error, language));
        } finally {
            setBusy(false);
            onBusyChange?.(false);
        }
    }

    return (
        <Stack spacing={1.5}>
            <Typography variant="subtitle2">
                {t("Bark notifications · optional", "Bark 通知 · 可选")}
            </Typography>
            <Typography variant="body2" color="text.secondary">
                {t(
                    "Get School session reminders, check-in deadline alerts, and success notifications on your iPhone or iPad. Bark supports iOS and iPadOS only.",
                    "在 iPhone 或 iPad 上接收学校会话提醒、签到截止提醒和签到成功通知。Bark 仅支持 iOS 和 iPadOS。",
                )}
            </Typography>
            <Link
                href="https://bark.day.app/?utm_source=chatgpt.com#/tutorial?id=发送推送"
                target="_blank"
                rel="noopener noreferrer"
            >
                {t("How to set up Bark", "如何设置 Bark")}
            </Link>
            {error && <Alert severity="error">{error}</Alert>}
            {saved && (
                <Alert severity="success">
                    {t("Bark settings saved", "Bark 设置已保存")}
                </Alert>
            )}
            <FormControlLabel
                control={
                    <Switch
                        checked={enabled}
                        disabled={busy}
                        onChange={(_, checked) => {
                            setEnabled(checked);
                            setSaved(false);
                        }}
                    />
                }
                label={t("Enable Bark notifications", "启用 Bark 通知")}
            />
            <TextField
                size="small"
                type="password"
                autoComplete="off"
                label={t("Bark device key", "Bark 设备密钥")}
                value={key}
                disabled={busy}
                onChange={(event) => {
                    setKey(event.target.value);
                    setSaved(false);
                }}
                onKeyDown={(event) => {
                    if (event.key === "Enter") {
                        event.preventDefault();
                        if (canSave) void save();
                    }
                }}
                helperText={
                    user?.bark_configured
                        ? t(
                            "A key is saved. Leave blank to keep it, or enter a replacement.",
                            "已保存密钥。留空以保留，或输入新密钥替换。",
                        )
                        : t(
                            "Paste only your device key from Bark, not the full URL.",
                            "仅粘贴 Bark 设备密钥，不要填写完整网址。",
                        )
                }
                slotProps={{ htmlInput: { maxLength: 256, spellCheck: false } }}
            />
            <Stack direction="row" spacing={1} flexWrap="wrap">
                <Button
                    type="button"
                    variant={introduction ? "contained" : "outlined"}
                    disabled={!canSave}
                    onClick={() => void save()}
                >
                    {introduction
                        ? t("Save and continue", "保存并继续")
                        : t("Save Bark settings", "保存 Bark 设置")}
                </Button>
                {!!user?.bark_configured && (
                    <Button
                        type="button"
                        color="warning"
                        disabled={busy}
                        onClick={() => void save(true)}
                    >
                        {t("Remove Bark key", "删除 Bark 密钥")}
                    </Button>
                )}
            </Stack>
        </Stack>
    );
}
