import { useState } from "react";
import {
    Alert,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Stack,
    Typography,
} from "@mui/material";
import { api } from "../api";
import { errorText, useLanguage } from "../i18n";
import AccountSettingsForm, {
    type AccountSettings,
} from "./AccountSettingsForm";
export type { AccountSettings } from "./AccountSettingsForm";

export default function SettingsDialog({
    account,
    onClose,
    onSuccess,
    onLocation,
}: {
    account: AccountSettings;
    onClose: () => void;
    onSuccess: () => Promise<void>;
    onLocation: () => void;
}) {
    const { t, language } = useLanguage();
    const [busy, setBusy] = useState(false);
    const [savePassword, setSavePassword] = useState(account.save_password);
    const [error, setError] = useState("");
    return (
        <Dialog open onClose={() => !busy && onClose()} fullWidth maxWidth="sm">
            <DialogTitle>{t("Account settings", "账号设置")}</DialogTitle>
            <DialogContent>
                <Stack spacing={2}>
                    {error && <Alert severity="error">{error}</Alert>}
                    <AccountSettingsForm
                        account={account}
                        formId="account-settings-dialog"
                        disabled={busy}
                        onSuccess={onSuccess}
                        onSaved={onClose}
                        onBusyChange={setBusy}
                    />
                    <Button
                        variant="outlined"
                        disabled={busy}
                        onClick={onLocation}
                    >
                        {t("Choose check-in location", "选择签到位置")}
                    </Button>
                    {savePassword && (
                        <Button
                            color="warning"
                            disabled={busy}
                            onClick={async () => {
                                setBusy(true);
                                setError("");
                                try {
                                    await api(
                                        `/accounts/${account.id}/password`,
                                        "DELETE",
                                    );
                                    setSavePassword(false);
                                    await onSuccess();
                                } catch (e) {
                                    setError(errorText(e, language));
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            {t("Forget saved password", "删除已保存密码")}
                        </Button>
                    )}
                    <Typography variant="body2" color="text.secondary">
                        {t(
                            "To save a new password, use Sign in again.",
                            "如需保存新密码，请使用“重新登录”。",
                        )}
                    </Typography>
                </Stack>
            </DialogContent>
            <DialogActions>
                <Button disabled={busy} onClick={onClose}>
                    {t("Cancel", "取消")}
                </Button>
                <Button
                    type="submit"
                    form="account-settings-dialog"
                    variant="contained"
                    disabled={busy}
                >
                    {t("Save", "保存")}
                </Button>
            </DialogActions>
        </Dialog>
    );
}
