import { useState } from "react";
import {
    Alert,
    Button,
    Checkbox,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControlLabel,
    Typography,
} from "@mui/material";
import { api } from "../api";
import { useAuth } from "../auth";
import type { Account } from "../accounts";
import { useLanguage, errorText } from "../i18n";

export default function DeleteAccountDialog({
    account,
    onClose,
    onSuccess,
}: {
    account: Account;
    onClose: () => void;
    onSuccess: () => Promise<void>;
}) {
    const { setUser } = useAuth();
    const { t, language } = useLanguage();
    const [deleteUser, setDeleteUser] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    return (
        <Dialog open onClose={() => !busy && onClose()} fullWidth maxWidth="xs">
            <DialogTitle>
                {t("Delete account", "删除账号")} · {account.alias}?
            </DialogTitle>
            <DialogContent>
                {error && (
                    <Alert severity="error" sx={{ mb: 1 }}>
                        {error}
                    </Alert>
                )}
                <Typography variant="body2">
                    {t(
                        "Remove saved school credentials, check-in history and the linked WeChat account (unless shared by another account). This cannot be undone.",
                        "删除学校凭据、签到记录及关联微信账号（其他账号仍在使用的微信除外）。此操作不可撤销。",
                    )}
                </Typography>
                <FormControlLabel
                    control={
                        <Checkbox
                            checked={deleteUser}
                            disabled={busy || account.owner_role === "admin"}
                            onChange={(e) => setDeleteUser(e.target.checked)}
                        />
                    }
                    label={t("Also delete associated User", "同时删除关联用户")}
                />
                <Typography
                    variant="caption"
                    display="block"
                    color="text.secondary"
                >
                    {account.owner_role === "admin"
                        ? t(
                              "Admin identities are always retained.",
                              "管理员身份始终保留。",
                          )
                        : deleteUser
                          ? t(
                                "The associated User and their sessions will also be deleted.",
                                "关联用户及其登录会话也将被删除。",
                            )
                          : t(
                                "The User will remain without an Account.",
                                "保留用户，用户将不再关联账号。",
                            )}
                </Typography>
            </DialogContent>
            <DialogActions>
                <Button disabled={busy} onClick={onClose}>
                    {t("Cancel", "取消")}
                </Button>
                <Button
                    disabled={busy}
                    color="error"
                    onClick={async () => {
                        setBusy(true);
                        setError("");
                        try {
                            const result = await (
                                await api(
                                    `/accounts/${account.id}?delete_user=${deleteUser}`,
                                    "DELETE",
                                )
                            ).json();
                            if (result.user_deleted) setUser(null);
                            else await onSuccess();
                            onClose();
                        } catch (e) {
                            setError(errorText(e, language));
                        } finally {
                            setBusy(false);
                        }
                    }}
                >
                    {t("Delete", "删除")}
                </Button>
            </DialogActions>
        </Dialog>
    );
}
